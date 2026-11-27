"""
PhotoCAD LangGraph Node 2: Parametric CAD Architect (`parametric_architect`)
Document ID: PCAD-LG-004 Section 3 (Node 2) / cad-kernel.skill.md

Constructs a top-down CSGFeatureTree ADT with:
- Uppercase millimeter parameter constants (LENGTH_MM, WIDTH_MM, THICKNESS_MM, HOLE_DIA_MM, FILLET_RADIUS_MM)
- Topological ordering: Base Solid -> Secondary Bosses -> Holes -> Fillets/Chamfers LAST
- Outer Loop spatial delta correction from Node 5 discrepancy_notes
- Natural-language /refine parametric edit updates when user_edit_instruction is supplied
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.agents.state import PhotoCADGraphState
from app.core.config import settings
from app.schemas.adt import CSGFeatureTree, FeatureStep, Open3DGeometryReport, ValidationMetrics


def _extract_clause_target_mm(clause: str, keywords_pattern: str) -> Optional[float]:
    """Extracts the target millimeter dimension from a single clause, preferring 'to X [mm]' over 'from Y [mm]'."""
    if not re.search(keywords_pattern, clause):
        return None
    if re.search(r"\b(?:remove|delete|drop|clear|without|no)\b", clause):
        return 0.0
    to_match = re.search(r"\bto\s+(\d+(?:\.\d+)?)(?:\s*mm\b)?", clause)
    if to_match:
        return round(float(to_match.group(1)), 2)
    nums = re.findall(r"(\d+(?:\.\d+)?)(?:\s*mm\b)?", clause)
    if nums:
        return round(float(nums[-1]), 2)
    return None


def _apply_refine_instruction(params: Dict[str, float], instruction: str) -> Dict[str, float]:
    """Deterministically interprets common multi-clause mechanical edit instructions in millimeters."""
    updated = dict(params)
    lower = instruction.lower()

    # Handle compact L x W x H shorthand (e.g., "100x60x25" or "120 x 70 x 30 mm")
    dim_triple = re.search(
        r"\b(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)(?:\s*mm\b)?",
        lower,
    )
    if dim_triple:
        updated["LENGTH_MM"] = round(float(dim_triple.group(1)), 2)
        updated["WIDTH_MM"] = round(float(dim_triple.group(2)), 2)
        updated["THICKNESS_MM"] = round(float(dim_triple.group(3)), 2)

    clauses = re.split(r"(?:[,;]|\.(?!\d)|\band\b)", lower)

    for clause in clauses:
        if not clause.strip():
            continue
        val = _extract_clause_target_mm(clause, r"\b(?:hole|holes|bore|diameter|dia)\b")
        if val is not None:
            updated["HOLE_DIA_MM"] = val

        val = _extract_clause_target_mm(clause, r"\b(?:length|x\s*axis)\b")
        if val is not None:
            updated["LENGTH_MM"] = val

        val = _extract_clause_target_mm(clause, r"\b(?:width|y\s*axis)\b")
        if val is not None:
            updated["WIDTH_MM"] = val

        val = _extract_clause_target_mm(clause, r"\b(?:thickness|height|depth|z\s*axis)\b")
        if val is not None:
            updated["THICKNESS_MM"] = val

        val = _extract_clause_target_mm(clause, r"\b(?:fillet|radius)\b")
        if val is not None:
            updated["FILLET_RADIUS_MM"] = val

        val = _extract_clause_target_mm(clause, r"\bchamfer\b")
        if val is not None:
            updated["CHAMFER_MM"] = val

    return updated


def _build_deterministic_feature_tree(
    state: PhotoCADGraphState,
) -> CSGFeatureTree:
    report = state["geometry_report"]
    if isinstance(report, dict):
        report = Open3DGeometryReport(**report)

    analysis = state.get("spatial_analysis") or {}
    prev_tree = state.get("feature_tree")
    metrics = state.get("validation_metrics")
    if isinstance(metrics, dict):
        metrics = ValidationMetrics(**metrics)

    # Start from previous parameters if looping in Outer Accuracy Loop or /refine
    if prev_tree is not None:
        if isinstance(prev_tree, dict):
            prev_tree = CSGFeatureTree(**prev_tree)
        params = dict(prev_tree.global_parameters_mm)
    else:
        lx = float(analysis.get("length_x_mm") or report.bounding_box_mm[0])
        wy = float(analysis.get("width_y_mm") or report.bounding_box_mm[1])
        hz = float(analysis.get("height_z_mm") or report.bounding_box_mm[2])
        params = {
            "LENGTH_MM": round(lx, 2),
            "WIDTH_MM": round(wy, 2),
            "THICKNESS_MM": round(hz, 2),
        }

        features = analysis.get("features") or []
        if features:
            first_hole = features[0]
            if first_hole.get("diameter_mm"):
                params["HOLE_DIA_MM"] = round(float(first_hole["diameter_mm"]), 2)
        elif report.cylinders:
            params["HOLE_DIA_MM"] = round(report.cylinders[0].radius_mm * 2.0, 2)

        # Safe fillet guard (< min_wall / 2.5) per cad-kernel.skill.md
        min_dim = min(params["LENGTH_MM"], params["WIDTH_MM"], params["THICKNESS_MM"])
        params["FILLET_RADIUS_MM"] = round(min(2.5, max(0.5, min_dim / 5.0)), 2)

    # Outer Loop Corrective Adjustment: compensate exact bbox_delta_mm feedback from Node 5
    if metrics and not metrics.passed_tolerance:
        dx, dy, dz = metrics.bbox_delta_mm
        params["LENGTH_MM"] = round(max(2.0, params["LENGTH_MM"] - dx), 2)
        params["WIDTH_MM"] = round(max(2.0, params["WIDTH_MM"] - dy), 2)
        params["THICKNESS_MM"] = round(max(2.0, params["THICKNESS_MM"] - dz), 2)

    # Apply natural-language parametric /refine edit if provided
    edit_instr = state.get("user_edit_instruction")
    if edit_instr:
        params = _apply_refine_instruction(params, edit_instr)

    # Enforce safe fillet cap against OpenCascade BRep_API crashes
    min_dim = min(params["LENGTH_MM"], params["WIDTH_MM"], params["THICKNESS_MM"])
    if "FILLET_RADIUS_MM" in params and params["FILLET_RADIUS_MM"] >= min_dim / 2.5:
        params["FILLET_RADIUS_MM"] = round((min_dim / 2.5) * 0.85, 2)

    steps: List[FeatureStep] = [
        FeatureStep(
            step_index=1,
            operation="base_extrude",
            target_plane="XY",
            parameters_mm={
                "length": params["LENGTH_MM"],
                "width": params["WIDTH_MM"],
                "thickness": params["THICKNESS_MM"],
            },
            rationale="Extrude primary bounding prism centered on XY datum in 1:1 mm.",
        )
    ]

    if params.get("HOLE_DIA_MM", 0.0) > 0.5:
        steps.append(
            FeatureStep(
                step_index=len(steps) + 1,
                operation="hole",
                target_plane=">Z",
                parameters_mm={
                    "diameter": params["HOLE_DIA_MM"],
                    "depth": params["THICKNESS_MM"],
                },
                rationale="Cut through-bore from top Z face prior to edge dressing.",
            )
        )

    if params.get("CHAMFER_MM", 0.0) > 0.1:
        steps.append(
            FeatureStep(
                step_index=len(steps) + 1,
                operation="chamfer",
                target_plane=">Z",
                parameters_mm={"length": params["CHAMFER_MM"]},
                rationale="Bevel outer top edges last to preserve topological stability.",
            )
        )
    elif params.get("FILLET_RADIUS_MM", 0.0) > 0.1:
        steps.append(
            FeatureStep(
                step_index=len(steps) + 1,
                operation="fillet",
                target_plane="|Z",
                parameters_mm={"radius": params["FILLET_RADIUS_MM"]},
                rationale="Apply vertical corner fillets LAST (radius < min_wall / 2.5).",
            )
        )

    summary = analysis.get("object_classification") or "Parametric Mechanical Solid"
    return CSGFeatureTree(
        part_summary=summary,
        coordinate_origin="center_bottom",
        global_parameters_mm=params,
        steps=steps,
    )


def _get_structured_architect_llm():
    gemini_key = settings.GEMINI_API_KEY or os.getenv("GEMINI_API_KEY", "")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")

    if gemini_key and "your-gemini" not in gemini_key:
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI

            model_name = os.getenv("ARCHITECT_MODEL", settings.DEFAULT_LLM_MODEL or "gemini-2.0-flash")
            return ChatGoogleGenerativeAI(
                model=model_name, google_api_key=gemini_key, temperature=0.1
            ).with_structured_output(CSGFeatureTree)
        except Exception:
            pass

    if anthropic_key and "your-anthropic" not in anthropic_key:
        try:
            from langchain_anthropic import ChatAnthropic

            return ChatAnthropic(
                model="claude-sonnet-4-5-20250929", api_key=anthropic_key, temperature=0.1
            ).with_structured_output(CSGFeatureTree)
        except Exception:
            pass

    return None


async def parametric_architect_node(state: PhotoCADGraphState) -> Dict[str, Any]:
    """Node 2: Builds or refines CSGFeatureTree ADT in strict topological order."""
    ts = datetime.now(timezone.utc).isoformat()
    llm = _get_structured_architect_llm()
    metrics = state.get("validation_metrics")
    edit_instr = state.get("user_edit_instruction")

    # Skip LLM round-trip during deterministic Outer Loop delta adjustment if delta is unambiguous,
    # otherwise consult structured LLM when API keys are live
    if llm is not None and not (metrics and getattr(metrics, "discrepancy_notes", None)):
        prompt = (
            "You are PhotoCAD Node 2 (Parametric CAD Architect). Produce a CSGFeatureTree in strictly 1:1 mm.\n"
            f"Spatial Analysis:\n{json.dumps(state.get('spatial_analysis') or {}, indent=2)}\n"
            f"Open3D Report:\n{json.dumps(state['geometry_report'].model_dump() if hasattr(state['geometry_report'], 'model_dump') else state['geometry_report'], indent=2)}\n"
            f"User Edit Instruction: {edit_instr or 'None'}\n"
            "CRITICAL: Always place fillets and chamfers LAST in `steps`, and use uppercase parameter names like LENGTH_MM."
        )
        try:
            feature_tree = await llm.ainvoke(prompt)
        except Exception:
            feature_tree = _build_deterministic_feature_tree(state)
    else:
        feature_tree = _build_deterministic_feature_tree(state)

    iteration = state.get("geometry_iterations", 0) + 1
    event = {
        "event": "agent_node_started",
        "scan_id": state["scan_id"],
        "timestamp": ts,
        "progress_pct": min(55 + iteration * 5, 70),
        "payload": {
            "node": "parametric_architect",
            "iteration": iteration,
            "message": f"Planned {len(feature_tree.steps)}-step CSG tree ({', '.join(s.operation for s in feature_tree.steps)})",
            "global_parameters_mm": feature_tree.global_parameters_mm,
        },
    }

    return {
        "feature_tree": feature_tree,
        "compile_retries": 0,
        "compile_error_trace": None,
        "event_log": [event],
    }
