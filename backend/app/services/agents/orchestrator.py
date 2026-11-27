"""
PhotoCAD - Phase 4 Multi-Agent LangGraph CAD Orchestrator
Document ID: PCAD-LG-004 / PCAD-API-ADT-003

Coordinates execution of the 5-node cyclic LangGraph Dual-Loop workflow,
persists live AgentLog entries (node transitions, code diffs, compile errors,
and Chamfer metrics), copies final .STEP/.STL/.DXF/.py exports to FastAPI's
export directory, and streams real-time events over WebSockets.
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import run_photocad_langgraph
from app.core.config import settings
from app.models.db_models import AgentLog, CadGeneration
from app.schemas.adt import DetectedCylinder, Open3DGeometryReport


def _fallback_report_from_views(scan_id: str, views_data: Dict[str, Any]) -> Open3DGeometryReport:
    """Synthesizes an Open3DGeometryReport ADT when running from legacy un-fused 2D view summaries."""
    top_dim = (views_data.get("top") or {}).get("primary_dimensions_mm", [80.0, 50.0])
    front_dim = (views_data.get("front") or {}).get("primary_dimensions_mm", [80.0, 30.0])

    lx = float(top_dim[0] or front_dim[0] or 80.0)
    wy = float(top_dim[1] or 50.0)
    hz = float(front_dim[1] or 30.0)

    return Open3DGeometryReport(
        scan_id=scan_id,
        units="mm",
        point_count=4000,
        icp_fitness_score=0.90,
        icp_inlier_rmse_mm=0.30,
        bounding_box_mm=(lx, wy, hz),
        principal_axes=[(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)],
        symmetry_planes=["XY", "YZ"],
        planes=[],
        cylinders=[
            DetectedCylinder(
                cylinder_id="cyl_center_01",
                kind="through_hole",
                axis_origin_mm=(0.0, 0.0, 0.0),
                axis_direction=(0.0, 0.0, 1.0),
                radius_mm=round(min(lx, wy) * 0.16, 2),
                depth_mm=hz,
                confidence=0.85,
            )
        ],
        ply_object_key=f"cad_exports/{scan_id}/fused_cloud.ply",
    )


def _map_event_to_log(ev: Dict[str, Any]) -> tuple[str, str, str]:
    """Maps a structured PCAD-API-ADT-003 event into (agent_name, log_type, message) for DB AgentLog."""
    ev_name = ev.get("event", "agent_node_started")
    payload = ev.get("payload", {})

    if ev_name == "agent_node_started":
        node_map = {
            "geometry_analyst": "VisionAnalyst",
            "parametric_architect": "CSGArchitect",
            "cad_synthesizer": "CadCoder",
            "sandbox_executor": "SandboxExecutor",
            "geometric_validator": "Validator",
        }
        agent = node_map.get(payload.get("node", ""), "Orchestrator")
        return agent, "thought", payload.get("message", f"Executing node {payload.get('node')}")

    if ev_name == "cad_code_diff":
        diff_txt = payload.get("diff") or payload.get("code", "")
        return "CadCoder", "diff", diff_txt

    if ev_name == "cad_compile_error":
        return "SandboxExecutor", "error", f"[Retry {payload.get('attempt')}/{payload.get('max_attempts')}] {payload.get('error_summary', '')}"

    if ev_name == "validation_completed":
        passed = payload.get("passed", False)
        chamfer = payload.get("chamfer_mean_mm", 0.0)
        p95 = payload.get("chamfer_p95_mm", 0.0)
        notes = "; ".join(payload.get("discrepancy_notes") or [])
        msg = f"Iter {payload.get('iteration')}: Mean Chamfer={chamfer:.3f}mm (P95={p95:.3f}mm), Watertight={payload.get('is_watertight')}."
        if notes:
            msg += f" Feedback: {notes}"
        return "Validator", "success" if passed else "info", msg

    return "Orchestrator", "info", str(payload)


class AgentOrchestrator:
    """Executes the Phase 4 LangGraph Dual-Loop CAD Pipeline for a ScanSession + CadGeneration."""

    def __init__(
        self,
        db: AsyncSession,
        ws_broadcast: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    ):
        self.db = db
        self.ws_broadcast = ws_broadcast

    async def log_step(self, generation_id: str, agent_name: str, log_type: str, message: str) -> None:
        log_entry = AgentLog(
            generation_id=generation_id,
            agent_name=agent_name,
            log_type=log_type,
            message=message,
        )
        self.db.add(log_entry)
        await self.db.commit()

        if self.ws_broadcast:
            await self.ws_broadcast({
                "type": "agent_log",
                "generation_id": generation_id,
                "agent_name": agent_name,
                "log_type": log_type,
                "message": message,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })

    async def run_pipeline(
        self,
        generation_id: str,
        views_data: Dict[str, Any],
        scale_ratio: float,
        engine_type: str = "build123d",
        scan_session_id: Optional[str] = None,
        geometry_report_json: Optional[Dict[str, Any]] = None,
        ply_local_path: Optional[str] = None,
        refinement_prompt: Optional[str] = None,
    ) -> CadGeneration:
        gen = await self.db.get(CadGeneration, generation_id)
        if not gen:
            raise ValueError(f"Generation {generation_id} not found")

        scan_id = scan_session_id or gen.scan_session_id
        gen.status = "generating"
        await self.db.commit()

        if geometry_report_json:
            report = Open3DGeometryReport(**geometry_report_json)
        else:
            report = _fallback_report_from_views(scan_id, views_data)

        masked_urls = {
            k: v.get("masked_url") or v.get("image_url", "")
            for k, v in (views_data or {}).items()
            if not k.startswith("_") and isinstance(v, dict)
        }

        # Check default local PLY path if not passed explicitly
        if not ply_local_path:
            candidate_ply = settings.EXPORTS_DIR / scan_id / "fused_cloud.ply"
            if candidate_ply.exists():
                ply_local_path = str(candidate_ply)

        async def on_langgraph_event(ev: Dict[str, Any]) -> None:
            agent_name, log_type, msg = _map_event_to_log(ev)
            await self.log_step(generation_id, agent_name, log_type, msg)
            if self.ws_broadcast:
                # Also forward raw PCAD-API-ADT-003 envelope
                await self.ws_broadcast(ev)

        final_state = await run_photocad_langgraph(
            scan_id=scan_id,
            geometry_report=report,
            masked_image_urls=masked_urls,
            ply_local_path=ply_local_path,
            thread_id=f"thread_{scan_id}",
            user_edit_instruction=refinement_prompt,
            ws_event_cb=on_langgraph_event,
        )

        best_code = final_state.get("best_code") or final_state.get("current_code") or ""
        best_artifacts = final_state.get("best_artifact_keys") or {}
        best_dims = final_state.get("best_dimensions_mm") or {}
        final_status = final_state.get("final_status", "failed")

        # Promote best artifacts to `/storage/cad_exports/{generation_id}.{ext}` so download route finds them
        gen_step = settings.EXPORTS_DIR / f"{generation_id}.step"
        gen_stl = settings.EXPORTS_DIR / f"{generation_id}.stl"
        gen_dxf = settings.EXPORTS_DIR / f"{generation_id}.dxf"
        gen_py = settings.EXPORTS_DIR / f"{generation_id}.py"

        for src_key, dst_path in [
            ("step_path", gen_step),
            ("stl_path", gen_stl),
            ("dxf_path", gen_dxf),
        ]:
            src_str = best_artifacts.get(src_key)
            if src_str and os.path.exists(src_str):
                shutil.copyfile(src_str, dst_path)

        if best_code:
            gen_py.write_text(best_code, encoding="utf-8")

        gen.code = best_code
        gen.dimensions_mm = best_dims or {
            "x": report.bounding_box_mm[0],
            "y": report.bounding_box_mm[1],
            "z": report.bounding_box_mm[2],
        }
        gen.status = "completed" if final_status in ("completed", "completed_with_warning") else "failed"
        gen.error_log = final_state.get("compile_error_trace")

        if gen_step.exists():
            gen.step_file = f"/storage/cad_exports/{generation_id}.step"
        if gen_stl.exists():
            gen.stl_file = f"/storage/cad_exports/{generation_id}.stl"
        if gen_dxf.exists():
            gen.dxf_file = f"/storage/cad_exports/{generation_id}.dxf"

        await self.db.commit()
        await self.db.refresh(gen)

        best_metrics = final_state.get("best_metrics")
        metrics_dict = (
            best_metrics.model_dump()
            if hasattr(best_metrics, "model_dump")
            else (best_metrics if isinstance(best_metrics, dict) else {})
        )
        setattr(gen, "_latest_validation_metrics", metrics_dict)

        # Broadcast terminal completion envelope
        if self.ws_broadcast:
            await self.ws_broadcast({
                "event": "pipeline_completed" if gen.status == "completed" else "pipeline_failed",
                "scan_id": scan_id,
                "generation_id": generation_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "progress_pct": 100,
                "payload": {
                    "revision": gen.version,
                    "status": final_status,
                    "validation_metrics": metrics_dict,
                    "artifacts": {
                        "step_url": gen.step_file,
                        "dxf_url": gen.dxf_file,
                        "stl_url": gen.stl_file,
                        "py_url": f"/api/export/{generation_id}/py",
                    },
                },
            })

        return gen
