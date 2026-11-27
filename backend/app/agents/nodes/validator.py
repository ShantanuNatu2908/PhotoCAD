"""
PhotoCAD LangGraph Node 5: Geometric Accuracy Validator (`geometric_validator`)
Document ID: PCAD-LG-004 Section 3 (Node 5) / Outer Accuracy Loop

Evaluates watertight solidity and computes bidirectional Chamfer Distance between the
compiled .STL solid and the fused Open3D scan (.PLY). Preserves the lowest-Chamfer best
artifact revision across iterations so later iterations can never regress output quality.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from app.agents.state import PhotoCADGraphState
from app.cad.chamfer_validator import ChamferValidator
from app.schemas.adt import Open3DGeometryReport


async def geometric_validator_node(state: PhotoCADGraphState) -> Dict[str, Any]:
    """Node 5: Measures Chamfer Distance vs scan and manages Best-Effort artifact retention."""
    report = state["geometry_report"]
    if isinstance(report, dict):
        report = Open3DGeometryReport(**report)

    artifacts = state.get("latest_artifacts") or {}
    stl_path = artifacts.get("stl_path", "")
    ply_path = state.get("ply_local_path")

    metrics = ChamferValidator.evaluate(
        stl_path=stl_path,
        geometry_report=report,
        ply_path=ply_path,
    )

    next_iter = state.get("geometry_iterations", 0) + 1
    best_chamfer = state.get("best_chamfer_mm", float("inf"))
    best_code = state.get("best_code")
    best_artifacts = state.get("best_artifact_keys") or {}
    best_dims = state.get("best_dimensions_mm") or {}
    best_metrics = state.get("best_metrics")

    # Best-Effort Retention Guard (langgraph-agents.skill.md Rule 4)
    if metrics.is_watertight and (metrics.chamfer_mean_mm < best_chamfer or not best_code):
        best_chamfer = metrics.chamfer_mean_mm
        best_code = state.get("current_code")
        best_artifacts = {
            "step": artifacts.get("step_url", ""),
            "stl": artifacts.get("stl_url", ""),
            "dxf": artifacts.get("dxf_url", ""),
            "step_path": artifacts.get("step_path", ""),
            "stl_path": artifacts.get("stl_path", ""),
            "dxf_path": artifacts.get("dxf_path", ""),
        }
        best_dims = state.get("latest_dimensions_mm") or {}
        best_metrics = metrics

    final_status = state.get("final_status", "running")
    if metrics.passed_tolerance:
        final_status = "completed"
    elif next_iter >= 3:
        final_status = "completed_with_warning" if best_code else "failed"

    ts = datetime.now(timezone.utc).isoformat()
    val_event = {
        "event": "validation_completed",
        "scan_id": state["scan_id"],
        "timestamp": ts,
        "progress_pct": 92 if metrics.passed_tolerance or next_iter >= 3 else 84,
        "payload": {
            "iteration": next_iter,
            "chamfer_mean_mm": metrics.chamfer_mean_mm,
            "chamfer_p95_mm": metrics.chamfer_p95_mm,
            "is_watertight": metrics.is_watertight,
            "bbox_delta_mm": list(metrics.bbox_delta_mm),
            "passed": metrics.passed_tolerance,
            "discrepancy_notes": metrics.discrepancy_notes,
        },
    }

    return {
        "validation_metrics": metrics,
        "geometry_iterations": next_iter,
        "best_code": best_code,
        "best_chamfer_mm": best_chamfer,
        "best_artifact_keys": best_artifacts,
        "best_dimensions_mm": best_dims,
        "best_metrics": best_metrics,
        "final_status": final_status,
        "event_log": [val_event],
    }
