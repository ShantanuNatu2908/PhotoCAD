"""
PhotoCAD LangGraph Node 3: RAG-Enabled build123d Synthesizer (`cad_synthesizer`)
Document ID: PCAD-LG-004 Section 3 (Node 3) / cad-kernel.skill.md

Queries build123d documentation chunks from Build123dRAGService, synthesizes clean
builder-mode build123d Python scripts with named uppercase mm constants and RESULT_PART,
applies self-healing trace fixes on Inner Loop retries, and computes unified code diffs.
"""

from __future__ import annotations

import difflib
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, cast

from app.agents.llm_router import build_llm_candidates, invoke_with_failover
from app.agents.media_utils import encode_scan_thumbnails_b64
from app.agents.rag import Build123dRAGService
from app.agents.state import PhotoCADGraphState
from app.core.config import settings
from app.schemas.adt import CSGFeatureTree


def _load_hull_meta(scan_id: str) -> Optional[Dict[str, Any]]:
    hull_path = settings.EXPORTS_DIR / scan_id / "visual_hull.json"
    if not hull_path.exists():
        return None
    try:
        return json.loads(hull_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _render_sculpted_hull_build123d(
    tree: CSGFeatureTree,
    hull_meta: Dict[str, Any],
) -> str:
    """Synthesizes multi-view silhouette-intersected build123d code for curved/contoured parts."""
    params = dict(tree.global_parameters_mm)
    length_mm = float(params.get("LENGTH_MM", 80.0))
    width_mm = float(params.get("WIDTH_MM", 50.0))
    thickness_mm = float(params.get("THICKNESS_MM", 30.0))
    hole_dia_mm = float(params.get("HOLE_DIA_MM", 0.0))
    chamfer_mm = float(params.get("CHAMFER_MM", 0.0))
    contours = hull_meta.get("contours_2d") or {}

    def fmt_poly(pts: List[List[float]]) -> str:
        safe = pts[:24] if len(pts) >= 3 else [[-0.5, -0.5], [0.5, -0.5], [0.5, 0.5], [-0.5, 0.5]]
        return ", ".join(f"({p[0]:.3f}, {p[1]:.3f})" for p in safe)

    xy_pts = fmt_poly(contours.get("xy") or [])
    xz_pts = fmt_poly(contours.get("xz") or [])
    yz_pts = fmt_poly(contours.get("yz") or [])

    lines = [
        "from build123d import (",
        "    BuildPart, BuildSketch, Plane, Polygon, Circle, Mode, Axis, extrude, chamfer",
        ")",
        "",
        "# Parametric Dimensions (1:1 Millimeters)",
        f"LENGTH_MM = {length_mm:.2f}",
        f"WIDTH_MM = {width_mm:.2f}",
        f"THICKNESS_MM = {thickness_mm:.2f}",
    ]
    if hole_dia_mm > 0.5:
        lines.append(f"HOLE_DIA_MM = {hole_dia_mm:.2f}")
    if chamfer_mm > 0.1:
        lines.append(f"CHAMFER_MM = {chamfer_mm:.2f}")

    lines.extend([
        "",
        f"TOP_XY_NORM = [{xy_pts}]",
        f"FRONT_XZ_NORM = [{xz_pts}]",
        f"SIDE_YZ_NORM = [{yz_pts}]",
        "",
        "with BuildPart() as part:",
        "    # 1. Primary Plan Silhouette (Top XY)",
        "    with BuildSketch(Plane.XY):",
        "        Polygon(*[(x * LENGTH_MM, y * WIDTH_MM) for x, y in TOP_XY_NORM], align=None)",
        "    extrude(amount=THICKNESS_MM / 2.0, both=True)",
        "",
        "    # 2. Cross-Carve Front Silhouette (XZ)",
        "    with BuildSketch(Plane.XZ):",
        "        Polygon(*[(x * LENGTH_MM, z * THICKNESS_MM) for x, z in FRONT_XZ_NORM], align=None)",
        "    extrude(amount=WIDTH_MM, both=True, mode=Mode.INTERSECT)",
        "",
        "    # 3. Cross-Carve Side Profile (YZ)",
        "    with BuildSketch(Plane.YZ):",
        "        Polygon(*[(y * WIDTH_MM, z * THICKNESS_MM) for y, z in SIDE_YZ_NORM], align=None)",
        "    extrude(amount=LENGTH_MM, both=True, mode=Mode.INTERSECT)",
    ])
    if hole_dia_mm > 0.5:
        lines.extend([
            "",
            "    # 4. Detected Interior Bore",
            "    with BuildSketch(part.faces().sort_by(Axis.Z)[-1]):",
            "        Circle(radius=HOLE_DIA_MM / 2.0)",
            "    extrude(amount=-THICKNESS_MM, mode=Mode.SUBTRACT)",
        ])
    if chamfer_mm > 0.1:
        lines.extend([
            "",
            "    chamfer(part.edges().filter_by(Axis.Z), length=CHAMFER_MM)",
        ])
    lines.extend(["", "RESULT_PART = part.part", ""])
    return "\n".join(lines)


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
    tree = cast(CSGFeatureTree, tree)

    ops: List[str] = [step.operation for step in tree.steps]
    retrieval = await Build123dRAGService.aretrieve(
        operations=ops,
        query_text=f"{tree.part_summary}. " + " ".join(step.rationale for step in tree.steps),
    )
    rag_chunks = retrieval.chunks
    err_trace = state.get("compile_error_trace")
    prev_code = state.get("current_code")
    retries = state.get("compile_retries", 0)

    temperature = 0.0 if retries == 0 else 0.15
    candidates = build_llm_candidates(
        override_env="SYNTHESIZER_MODEL",
        temperature=temperature,
        structured_schema=None,
        prefer_anthropic=False,
    )
    hull_meta = _load_hull_meta(state["scan_id"])
    synthesized_code: str = ""
    used_model: Optional[str] = None

    def _deterministic_fallback() -> str:
        if hull_meta and hull_meta.get("is_sculpted") and not err_trace:
            return _render_sculpted_hull_build123d(tree, hull_meta)
        return _render_canonical_build123d(tree, err_trace, prev_code)

    if candidates:
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
            "For contoured/curved parts (vehicles, organic housings, sculpted brackets), use multi-plane Polygon / Spline / "
            "loft / Mode.INTERSECT rather than a plain Rectangle.\n"
            "Rules: 1) Declare uppercase millimeter constants at top. 2) Set RESULT_PART = part.part. "
            "3) NEVER import os/sys/subprocess or call export_step()/export_stl(). 4) Return pure Python only.\n\n"
            f"CSGFeatureTree:\n{tree.model_dump_json(indent=2)}\n\n"
            f"Silhouette Hull Summary:\n{json.dumps((hull_meta or {}).get('contours_2d') or {}, indent=2)[:1500]}\n\n"
            f"Reference build123d Docs (RAG):\n{rag_text}\n{repair_block}"
        )
        thumbs = encode_scan_thumbnails_b64(state["scan_id"])
        if thumbs:
            from langchain_core.messages import HumanMessage

            content: List[Any] = [{"type": "text", "text": prompt}]
            for t in thumbs:
                content.append({"type": "text", "text": f"Captured View [{t['side'].upper()}]:"})
                content.append({"type": "image_url", "image_url": {"url": t["data_url"]}})
            payload_msg: Any = [HumanMessage(content=content)]
        else:
            payload_msg = prompt

        resp, used_model, _ = await invoke_with_failover(payload_msg, candidates)
        if resp is not None:
            raw_text = resp.content if isinstance(resp.content, str) else str(resp.content)
            candidate_code = raw_text.replace("```python", "").replace("```", "").strip() + "\n"
            if "RESULT_PART" in candidate_code:
                synthesized_code = candidate_code

    if not synthesized_code:
        synthesized_code = _deterministic_fallback()
        used_model = None

    code_diff = _compute_unified_diff(prev_code, synthesized_code)
    ts = datetime.now(timezone.utc).isoformat()
    iteration = state.get("geometry_iterations", 0) + 1
    engine_tag = f"[{used_model}] " if used_model else ""

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
                "model": used_model or "deterministic",
                "rag_symbols": [c["symbol"] for c in rag_chunks],
                "rag_backend": retrieval.backend,
                "message": (
                    f"{engine_tag}Synthesizing self-healing patch (compile retry {retries})..."
                    if err_trace
                    else f"{engine_tag}Generating build123d script with {len(rag_chunks)} RAG docs..."
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
