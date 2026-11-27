"""
PhotoCAD LangGraph Node 4: Isolated Sandbox Executor (`sandbox_executor`)
Document ID: PCAD-LG-004 Section 3 (Node 4) / Inner Self-Healing Loop

Runs AST security checks and executes synthesized build123d code inside the isolated
sandbox, exporting .STEP, .STL, and .DXF or catching kernel tracebacks for self-healing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from app.agents.state import PhotoCADGraphState
from app.cad.sandbox import CadSandboxExecutor


async def sandbox_executor_node(state: PhotoCADGraphState) -> Dict[str, Any]:
    """Node 4: Runs AST validator + isolated CAD compiler on `current_code`."""
    code = state.get("current_code") or ""
    scan_id = state["scan_id"]
    geo_iter = state.get("geometry_iterations", 0) + 1
    retry_num = state.get("compile_retries", 0)
    rev_tag = f"iter{geo_iter}_r{retry_num}"

    res = await CadSandboxExecutor.execute(code=code, scan_id=scan_id, revision_tag=rev_tag)
    ts = datetime.now(timezone.utc).isoformat()

    if not res.success:
        next_retry = retry_num + 1
        err_event = {
            "event": "cad_compile_error",
            "scan_id": scan_id,
            "timestamp": ts,
            "progress_pct": 68,
            "payload": {
                "attempt": next_retry,
                "max_attempts": 3,
                "error_summary": (res.error_trace or "Compilation error")[:400],
            },
        }
        return {
            "compile_error_trace": res.error_trace,
            "compile_retries": next_retry,
            "event_log": [err_event],
        }

    ok_event = {
        "event": "agent_node_started",
        "scan_id": scan_id,
        "timestamp": ts,
        "progress_pct": 78,
        "payload": {
            "node": "sandbox_executor",
            "iteration": geo_iter,
            "execution_mode": res.execution_mode,
            "message": f"Sandbox compiled watertight B-Rep in {res.elapsed_ms:.0f}ms ({res.dimensions_mm}).",
        },
    }

    return {
        "compile_error_trace": None,
        "latest_artifacts": {
            "step_url": res.step_url or "",
            "stl_url": res.stl_url or "",
            "dxf_url": res.dxf_url or "",
            "step_path": res.step_path or "",
            "stl_path": res.stl_path or "",
            "dxf_path": res.dxf_path or "",
        },
        "latest_dimensions_mm": res.dimensions_mm,
        "event_log": [ok_event],
    }
