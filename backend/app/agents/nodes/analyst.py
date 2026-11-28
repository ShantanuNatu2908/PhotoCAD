"""
PhotoCAD LangGraph Node 1: Spatial Geometry Analyst (`geometry_analyst`)
Document ID: PCAD-LG-004 Section 3 (Node 1) / langgraph-agents.skill.md

Reconciles the 6 hand-masked views with Open3DGeometryReport metric ground truth
using strict Pydantic `.with_structured_output(SpatialAnalysisModel)` (Gemini VLM
with Anthropic fallback) or deterministic Open3D synthesis in offline mode.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.agents.llm_router import build_llm_candidates, invoke_with_failover
from app.agents.media_utils import encode_scan_thumbnails_b64
from app.agents.state import PhotoCADGraphState
from app.core.config import settings
from app.schemas.adt import Open3DGeometryReport


class IdentifiedFeature(BaseModel):
    kind: Literal["boss", "through_hole", "blind_hole", "fillet", "chamfer", "pocket"]
    axis: Literal["X", "Y", "Z"] = "Z"
    origin_mm: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    diameter_mm: Optional[float] = None
    depth_mm: Optional[float] = None
    confidence: float = 0.9


class SpatialAnalysisModel(BaseModel):
    object_classification: str
    length_x_mm: float = Field(..., gt=0.1)
    width_y_mm: float = Field(..., gt=0.1)
    height_z_mm: float = Field(..., gt=0.1)
    symmetry_planes: List[Literal["XY", "YZ", "XZ"]] = Field(default_factory=list)
    features: List[IdentifiedFeature] = Field(default_factory=list)
    engineering_summary: str


def _load_visual_hull_meta(scan_id: str) -> Optional[Dict[str, Any]]:
    hull_path = settings.EXPORTS_DIR / scan_id / "visual_hull.json"
    if not hull_path.exists():
        return None
    try:
        return json.loads(hull_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _deterministic_analysis(report: Open3DGeometryReport, hull_meta: Optional[Dict[str, Any]] = None) -> SpatialAnalysisModel:
    """Derives exact millimeter inventory directly from Open3DGeometryReport ADT + carved visual hull."""
    lx, wy, hz = report.bounding_box_mm
    features: List[IdentifiedFeature] = []

    for cyl in report.cylinders:
        if cyl.confidence >= 0.70 or len(report.cylinders) == 1:
            dx, dy, dz = cyl.axis_direction
            axis: Literal["X", "Y", "Z"] = "Z"
            if abs(dx) >= abs(dy) and abs(dx) >= abs(dz):
                axis = "X"
            elif abs(dy) >= abs(dx) and abs(dy) >= abs(dz):
                axis = "Y"
            features.append(
                IdentifiedFeature(
                    kind=cyl.kind,
                    axis=axis,
                    origin_mm=list(cyl.axis_origin_mm),
                    diameter_mm=round(cyl.radius_mm * 2.0, 2),
                    depth_mm=round(cyl.depth_mm, 2),
                    confidence=cyl.confidence,
                )
            )

    is_sculpted = bool(hull_meta and hull_meta.get("is_sculpted"))
    fill_pct = int(round(float((hull_meta or {}).get("fill_ratio", 1.0)) * 100))

    if features and any(f.kind == "boss" for f in features):
        classification = "Flanged Cylindrical Housing"
    elif features and is_sculpted:
        classification = f"Contoured Multi-View Part with Bore ({fill_pct}% hull fill)"
    elif features:
        classification = "Machined Mounting Block with Through-Bore"
    elif is_sculpted:
        classification = f"Sculpted Multi-View 3D Solid ({fill_pct}% hull fill)"
    else:
        classification = "Prismatic Mechanical Block"

    return SpatialAnalysisModel(
        object_classification=classification,
        length_x_mm=round(float(lx), 2),
        width_y_mm=round(float(wy), 2),
        height_z_mm=round(float(hz), 2),
        symmetry_planes=list(report.symmetry_planes),
        features=features,
        engineering_summary=(
            f"{classification} ({lx:.1f}×{wy:.1f}×{hz:.1f} mm, ICP {report.icp_fitness_score:.2f}, "
            f"{len(report.planes)} planes, {len(features)} cylindrical features)."
        ),
    )


async def geometry_analyst_node(state: PhotoCADGraphState) -> Dict[str, Any]:
    """Node 1: Synthesizes Open3D report + 6 masked views into strict millimeter spatial analysis."""
    report = state["geometry_report"]
    if isinstance(report, dict):
        report = Open3DGeometryReport(**report)

    ts = datetime.now(timezone.utc).isoformat()
    candidates = build_llm_candidates(
        override_env="ANALYST_MODEL",
        temperature=0.1,
        structured_schema=SpatialAnalysisModel,
        prefer_anthropic=False,
    )
    analysis: Optional[SpatialAnalysisModel] = None
    used_model: Optional[str] = None

    hull_meta = _load_visual_hull_meta(state["scan_id"])

    if candidates:
        thumbs = encode_scan_thumbnails_b64(state["scan_id"])
        text_prompt = (
            "You are PhotoCAD Node 1 (Geometry Analyst). Inspect ALL attached orthogonal view images alongside the "
            "millimeter Open3D ground truth to identify the real object (car, enclosure, bracket, housing, etc.), "
            "its curved/contoured silhouette characteristics, and true internal bores (do NOT invent holes if absent).\n"
            f"Open3DGeometryReport:\n{json.dumps(report.model_dump(), indent=2)}\n"
            f"Sculpted Hull Fill Ratio: {(hull_meta or {}).get('fill_ratio', 1.0)}\n"
            f"Captured Sides: {[t['side'] for t in thumbs] or list((state.get('masked_image_urls') or {}).keys())}\n"
            "Rules: Always work strictly in millimeters (1:1 mm)."
        )
        if thumbs:
            from langchain_core.messages import HumanMessage

            content: List[Any] = [{"type": "text", "text": text_prompt}]
            for t in thumbs:
                content.append({"type": "text", "text": f"Perspective [{t['side'].upper()}]:"})
                content.append({"type": "image_url", "image_url": {"url": t["data_url"]}})
            prompt_payload: Any = [HumanMessage(content=content)]
        else:
            prompt_payload = text_prompt

        analysis, used_model, _ = await invoke_with_failover(prompt_payload, candidates)

    if analysis is None:
        analysis = _deterministic_analysis(report, hull_meta)

    analysis_dict = analysis.model_dump()
    engine_tag = f"[{used_model}] " if used_model else ""
    event = {
        "event": "agent_node_started",
        "scan_id": state["scan_id"],
        "timestamp": ts,
        "progress_pct": 45,
        "payload": {
            "node": "geometry_analyst",
            "iteration": state.get("geometry_iterations", 0) + 1,
            "model": used_model or "deterministic",
            "message": f"{engine_tag}Identified {analysis.object_classification}: {analysis.length_x_mm}×{analysis.width_y_mm}×{analysis.height_z_mm} mm",
            "analysis": analysis_dict,
        },
    }

    return {
        "spatial_analysis": analysis_dict,
        "event_log": [event],
    }
