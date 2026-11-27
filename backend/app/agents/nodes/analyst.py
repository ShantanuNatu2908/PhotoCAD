"""
PhotoCAD LangGraph Node 1: Spatial Geometry Analyst (`geometry_analyst`)
Document ID: PCAD-LG-004 Section 3 (Node 1) / langgraph-agents.skill.md

Reconciles the 6 hand-masked views with Open3DGeometryReport metric ground truth
using strict Pydantic `.with_structured_output(SpatialAnalysisModel)` (Gemini VLM
with Anthropic fallback) or deterministic Open3D synthesis in offline mode.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

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


def _deterministic_analysis(report: Open3DGeometryReport) -> SpatialAnalysisModel:
    """Derives exact millimeter inventory directly from Open3DGeometryReport ADT."""
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

    classification = (
        "Flanged Cylindrical Housing"
        if features and any(f.kind == "boss" for f in features)
        else "Machined Mounting Block with Through-Bore"
        if features
        else "Prismatic Mechanical Block"
    )

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


def _get_structured_analyst_llm():
    gemini_key = settings.GEMINI_API_KEY or os.getenv("GEMINI_API_KEY", "")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")

    if gemini_key and "your-gemini" not in gemini_key:
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI

            model_name = os.getenv("ANALYST_MODEL", settings.DEFAULT_LLM_MODEL or "gemini-2.0-flash")
            return ChatGoogleGenerativeAI(
                model=model_name, google_api_key=gemini_key, temperature=0.1
            ).with_structured_output(SpatialAnalysisModel)
        except Exception:
            pass

    if anthropic_key and "your-anthropic" not in anthropic_key:
        try:
            from langchain_anthropic import ChatAnthropic

            return ChatAnthropic(
                model="claude-sonnet-4-5-20250929", api_key=anthropic_key, temperature=0.1
            ).with_structured_output(SpatialAnalysisModel)
        except Exception:
            pass

    return None


async def geometry_analyst_node(state: PhotoCADGraphState) -> Dict[str, Any]:
    """Node 1: Synthesizes Open3D report + 6 masked views into strict millimeter spatial analysis."""
    report = state["geometry_report"]
    if isinstance(report, dict):
        report = Open3DGeometryReport(**report)

    ts = datetime.now(timezone.utc).isoformat()
    llm = _get_structured_analyst_llm()
    analysis: SpatialAnalysisModel

    if llm is not None:
        prompt = (
            "You are PhotoCAD Node 1 (Geometry Analyst). Reconcile the millimeter Open3D ground truth "
            "and 6 captured viewpoints into a structured mechanical engineering specification.\n"
            f"Open3DGeometryReport:\n{json.dumps(report.model_dump(), indent=2)}\n"
            f"Masked View Keys: {list((state.get('masked_image_urls') or {}).keys())}\n"
            "Rules: Always work strictly in millimeters (1:1 mm). Trust bounding_box_mm and high-confidence cylinder radii."
        )
        try:
            analysis = await llm.ainvoke(prompt)
        except Exception:
            analysis = _deterministic_analysis(report)
    else:
        analysis = _deterministic_analysis(report)

    analysis_dict = analysis.model_dump()
    event = {
        "event": "agent_node_started",
        "scan_id": state["scan_id"],
        "timestamp": ts,
        "progress_pct": 45,
        "payload": {
            "node": "geometry_analyst",
            "iteration": state.get("geometry_iterations", 0) + 1,
            "message": f"Identified {analysis.object_classification}: {analysis.length_x_mm}×{analysis.width_y_mm}×{analysis.height_z_mm} mm",
            "analysis": analysis_dict,
        },
    }

    return {
        "spatial_analysis": analysis_dict,
        "event_log": [event],
    }
