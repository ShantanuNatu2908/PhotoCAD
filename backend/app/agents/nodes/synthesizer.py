"""
PhotoCAD LangGraph Node 3: RAG-Enabled build123d Synthesizer (`cad_synthesizer`)
Document ID: PCAD-LG-004 Section 3 (Node 3) / cad-kernel.skill.md

Queries build123d documentation chunks from Build123dRAGService, synthesizes clean
builder-mode build123d Python scripts with named uppercase mm constants and RESULT_PART,
applies self-healing trace fixes on Inner Loop retries, and computes unified code diffs.
"""

from __future__ import annotations

import difflib
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.agents.rag import Build123dRAGService
from app.agents.state import PhotoCADGraphState
from app.core.config import settings
from app.schemas.adt import CSGFeatureTree


def _render_canonical_build123d(
    tree: CSGFeatureTree,
    error_trace: str | None = None,
    previous_code: str | None = None,
) -> str:
    """
    Generates deterministic, well-commented build123d builder-mode code from a CSGFeatureTree.
    If Inner Loop `error_trace` is present, repairs oversized fillets, missing RESULT_PART,
    or invalid parameter bounds cleanly.
    """
    params = dict(tree.global_parameters_mm)
    length_mm = float(params.get("LENGTH_MM", 80.0))
    width_mm = float(params.get("WIDTH_MM", 50.0))
    thickness_mm = float(params.get("THICKNESS_MM", 30.0))
    hole_dia_mm = float(params.get("HOLE_DIA_MM", 0.0))
    fillet_r = float(params.get("FILLET_RADIUS_MM", 0.0))
    chamfer_mm = float(params.get("CHAMFER_MM", 0.0))

    # Inner Loop self-healing reflex if previous attempt failed in OpenCascade / Sandbox
    if error_trace:
        err_l = error_trace.lower()
        if "fillet" in err_l or "brepfilletapi" in err_l:
            min_wall = min(length_mm, width_mm, thickness_mm)
            fillet_r = round(max(0.4, (min_wall / 2.5) * 0.65), 2)
        if "hole" in err_l or "exceeds outer face" in err_l:
            hole_dia_mm = round(min(length_mm, width_mm) * 0.35, 2)

        # If caller supplied malformed raw previous_code without valid AST parameters,
        # rebuild from clean CSGFeatureTree constants below.
        if previous_code and "SyntaxError" not in error_trace and "BRepFilletAPI" in error_trace:
            # Patch numeric fillet radius constant inside existing code when possible
            patched = re.sub(
                r"(TOP_FILLET_MM|FILLET_RADIUS_MM)\s*=\s*[0-9.]+",
                rf"\1 = {fillet_r}",
                previous_code,
            )
            if patched != previous_code:
                return patched

    imports = [
        "from build123d import (",
        "    BuildPart, BuildSketch, Rectangle, Circle, Mode, Axis, extrude, fillet, chamfer",
        ")",
    ]
    consts = [
        "# Parametric Dimensions (1:1 Millimeters)",
        f"LENGTH_MM = {length_mm:.2f}",
        f"WIDTH_MM = {width_mm:.2f}",
        f"THICKNESS_MM = {thickness_mm:.2f}",
    ]
    if hole_dia_mm > 0.5:
        consts.append(f"HOLE_DIA_MM = {hole_dia_mm:.2f}")
    if chamfer_mm > 0.1:
        consts.append(f"CHAMFER_MM = {chamfer_mm:.2f}")
    elif fillet_r > 0.1:
        consts.append(f"TOP_FILLET_MM = {fillet_r:.2f}")

    body = [
        "",
        "with BuildPart() as part:",
        "    # 1. Base Prismatic Solid",
        "    with BuildSketch():",
        "        Rectangle(LENGTH_MM, WIDTH_MM)",
        "    extrude(amount=THICKNESS_MM)",
    ]

    if hole_dia_mm > 0.5:
        body.extend([
            "",
            "    # 2. Subtractive Mounting / Bore Hole",
            "    with BuildSketch(part.faces().sort_by(Axis.Z)[-1]):",
            "        Circle(radius=HOLE_DIA_MM / 2.0)",
            "    extrude(amount=-THICKNESS_MM, mode=Mode.SUBTRACT)",
        ])

    if chamfer_mm > 0.1:
        body.extend([
            "",
            "    # 3. Outer Perimeter Chamfer (Applied LAST)",
            "    top_edges = part.edges().filter_by(Axis.Z, reverse=True).group_by(Axis.Z)[-1]",
            "    chamfer(top_edges, length=CHAMFER_MM)",
        ])
    elif fillet_r > 0.1:
        body.extend([
            "",
            "    # 3. Vertical Edge Fillet (Applied LAST, guarded < min_wall / 2.5)",
            "    fillet(part.edges().filter_by(Axis.Z), radius=TOP_FILLET_MM)",
        ])

    footer = [
        "",
        "RESULT_PART = part.part",
    ]

    return "\n".join(imports + [""] + consts + body + footer) + "\n"


def _get_synthesizer_llm(attempt: int):
    temperature = 0.0 if attempt == 0 else 0.15
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    gemini_key = settings.GEMINI_API_KEY or os.getenv("GEMINI_API_KEY", "")

    if anthropic_key and "your-anthropic" not in anthropic_key:
        try:
            from langchain_anthropic import ChatAnthropic

            return ChatAnthropic(
                model="claude-sonnet-4-5-20250929",
                api_key=anthropic_key,
                temperature=temperature,
            )
        except Exception:
            pass

    if gemini_key and "your-gemini" not in gemini_key:
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI

            return ChatGoogleGenerativeAI(
                model=os.getenv("SYNTHESIZER_MODEL", settings.DEFAULT_LLM_MODEL or "gemini-2.0-flash"),
                google_api_key=gemini_key,
                temperature=temperature,
            )
        except Exception:
            pass

    return None


def _compute_unified_diff(old_code: str | None, new_code: str) -> str:
    if not old_code:
        lines = [f"+ {line}" for line in new_code.splitlines()]
        return "\n".join(lines[:40])
    diff = list(
        difflib.unified_diff(
            old_code.splitlines(),
            new_code.splitlines(),
            fromfile="prev_model.py",
            tofile="next_model.py",
            lineterm="",
        )
    )
    return "\n".join(diff[:60]) if diff else "# No diff (identical code)"


async def cad_synthesizer_node(state: PhotoCADGraphState) -> Dict[str, Any]:
    """Node 3: Retrieves build123d RAG context and emits executable parametric code + diff."""
    tree = state["feature_tree"]
    if isinstance(tree, dict):
        tree = CSGFeatureTree(**tree)

    ops: List[str] = [step.operation for step in tree.steps]
    rag_chunks = Build123dRAGService.retrieve_context_for_operations(ops)
    err_trace = state.get("compile_error_trace")
    prev_code = state.get("current_code")
    retries = state.get("compile_retries", 0)

    llm = _get_synthesizer_llm(retries)
    synthesized_code: str

    if llm is not None:
        rag_text = "\n\n".join(
            f"[{c['symbol']}] {c['guidance']}\nExample:\n{c['canonical_pattern']}" for c in rag_chunks
        )
        repair_block = (
            f"\nPREVIOUS SANDBOX COMPILE ERROR:\n{err_trace}\nFix ONLY the failing geometry/syntax while preserving valid features.\n"
            if err_trace
            else ""
        )
        prompt = (
            "Write a clean, self-contained build123d Python script using builder mode (`with BuildPart() as part:`).\n"
            "Rules: 1) Declare uppercase millimeter constants at top. 2) Set RESULT_PART = part.part. "
            "3) NEVER import os/sys/subprocess or call export_step()/export_stl(). 4) Return pure Python only.\n\n"
            f"CSGFeatureTree:\n{tree.model_dump_json(indent=2)}\n\n"
            f"Reference build123d Docs (RAG):\n{rag_text}\n{repair_block}"
        )
        try:
            resp = await llm.ainvoke(prompt)
            raw_text = resp.content if isinstance(resp.content, str) else str(resp.content)
            synthesized_code = raw_text.replace("```python", "").replace("```", "").strip() + "\n"
            if "RESULT_PART" not in synthesized_code:
                synthesized_code = _render_canonical_build123d(tree, err_trace, prev_code)
        except Exception:
            synthesized_code = _render_canonical_build123d(tree, err_trace, prev_code)
    else:
        synthesized_code = _render_canonical_build123d(tree, err_trace, prev_code)

    code_diff = _compute_unified_diff(prev_code, synthesized_code)
    ts = datetime.now(timezone.utc).isoformat()
    iteration = state.get("geometry_iterations", 0) + 1

    events = [
        {
            "event": "agent_node_started",
            "scan_id": state["scan_id"],
            "timestamp": ts,
            "progress_pct": min(62 + retries * 3, 74),
            "payload": {
                "node": "cad_synthesizer",
                "iteration": iteration,
                "retry": retries,
                "rag_symbols": [c["symbol"] for c in rag_chunks],
                "message": (
                    f"Synthesizing self-healing patch (compile retry {retries})..."
                    if err_trace
                    else f"Generating build123d script with {len(rag_chunks)} RAG docs..."
                ),
            },
        },
        {
            "event": "cad_code_diff",
            "scan_id": state["scan_id"],
            "timestamp": ts,
            "progress_pct": min(64 + retries * 3, 76),
            "payload": {
                "code": synthesized_code,
                "diff": code_diff,
            },
        },
    ]

    return {
        "retrieved_api_docs": rag_chunks,
        "previous_code": prev_code,
        "current_code": synthesized_code,
        "code_diff": code_diff,
        "event_log": events,
    }
