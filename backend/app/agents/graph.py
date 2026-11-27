"""
PhotoCAD - 5-Node Cyclic Dual-Loop LangGraph State Machine
Document ID: PCAD-LG-004 / langgraph-agents.skill.md

Topology:
  [START] -> (entry_router: refine->Node 2, initial->Node 1)
  Node 1: Geometry Analyst (VLM / Open3D Inventory)
  Node 2: Parametric Architect (CSGFeatureTree + Outer Delta Repair + /refine)
  Node 3: CAD Code Synthesizer (build123d + RAG + Inner Patch + Diffs)
  Node 4: Isolated Sandbox Executor (AST Security Gate + OCP / Zero-Heat Compiler)
    -> Inner Loop (if compile error & compile_retries < 3 -> Node 3)
  Node 5: Geometric Validator (Chamfer Distance + Watertight Check + Best-Effort Retain)
    -> Outer Loop (if chamfer > 1.0mm & geometry_iterations < 3 -> Node 2)
  [END]
"""

from __future__ import annotations

import os
from typing import Any, Awaitable, Callable, Dict, Optional

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph

from app.agents.nodes.analyst import geometry_analyst_node
from app.agents.nodes.architect import parametric_architect_node
from app.agents.nodes.executor import sandbox_executor_node
from app.agents.nodes.synthesizer import cad_synthesizer_node
from app.agents.nodes.validator import geometric_validator_node
from app.agents.state import PhotoCADGraphState
from app.schemas.adt import Open3DGeometryReport


WsStreamCallback = Optional[Callable[[Dict[str, Any]], Awaitable[None]]]

ALLOWED_ADT_MODULES = [
    ("app.schemas.adt", "Open3DGeometryReport"),
    ("app.schemas.adt", "CSGFeatureTree"),
    ("app.schemas.adt", "ValidationMetrics"),
    ("app.schemas.adt", "FeatureStep"),
    ("app.schemas.adt", "DetectedPlane"),
    ("app.schemas.adt", "DetectedCylinder"),
]

# Shared in-memory checkpointer with strict Pydantic ADT allowlist
_MEMORY_CHECKPOINTER = MemorySaver(
    serde=JsonPlusSerializer(allowed_msgpack_modules=ALLOWED_ADT_MODULES)
)


def _entry_router(state: PhotoCADGraphState) -> str:
    """Routes checkpointed /refine edits directly to Node 2 (<15s turnaround), bypassing Node 1."""
    if state.get("user_edit_instruction") and state.get("spatial_analysis"):
        return "parametric_architect"
    return "geometry_analyst"


def _inner_compile_router(state: PhotoCADGraphState) -> str:
    """Routes compiler/kernel exceptions back to Node 3 up to max 3 attempts."""
    if state.get("compile_error_trace"):
        if state.get("compile_retries", 0) < 3:
            return "cad_synthesizer"
        return END
    return "geometric_validator"


def _outer_accuracy_router(state: PhotoCADGraphState) -> str:
    """Routes dimensional Chamfer deviations (>1.0mm) back to Node 2 up to max 3 iterations."""
    metrics = state.get("validation_metrics")
    passed = False
    is_watertight = False
    if metrics is not None:
        passed = bool(
            metrics.passed_tolerance
            if hasattr(metrics, "passed_tolerance")
            else metrics.get("passed_tolerance", False)
        )
        is_watertight = bool(
            metrics.is_watertight
            if hasattr(metrics, "is_watertight")
            else metrics.get("is_watertight", False)
        )

    # During conversational /refine edits, user instructions intentionally diverge from raw scan
    if state.get("user_edit_instruction") and is_watertight:
        return END

    if passed or state.get("geometry_iterations", 0) >= 3:
        return END
    return "parametric_architect"


def build_photocad_graph(checkpointer: Any = None):
    """Builds and compiles the 5-node cyclic dual-loop StateGraph."""
    builder = StateGraph(PhotoCADGraphState)

    builder.add_node("geometry_analyst", geometry_analyst_node)
    builder.add_node("parametric_architect", parametric_architect_node)
    builder.add_node("cad_synthesizer", cad_synthesizer_node)
    builder.add_node("sandbox_executor", sandbox_executor_node)
    builder.add_node("geometric_validator", geometric_validator_node)

    builder.add_conditional_edges(
        START,
        _entry_router,
        {
            "geometry_analyst": "geometry_analyst",
            "parametric_architect": "parametric_architect",
        },
    )
    builder.add_edge("geometry_analyst", "parametric_architect")
    builder.add_edge("parametric_architect", "cad_synthesizer")
    builder.add_edge("cad_synthesizer", "sandbox_executor")

    builder.add_conditional_edges(
        "sandbox_executor",
        _inner_compile_router,
        {
            "cad_synthesizer": "cad_synthesizer",
            "geometric_validator": "geometric_validator",
            END: END,
        },
    )

    builder.add_conditional_edges(
        "geometric_validator",
        _outer_accuracy_router,
        {
            "parametric_architect": "parametric_architect",
            END: END,
        },
    )

    active_cp = checkpointer or _get_checkpointer()
    return builder.compile(checkpointer=active_cp)


def _get_checkpointer():
    """Attempts RedisSaver if configured with Redis Stack modules; falls back cleanly to MemorySaver."""
    redis_url = os.getenv("REDIS_URL", "")
    if redis_url and "your-endpoint" not in redis_url:
        try:
            from langgraph.checkpoint.redis import RedisSaver  # type: ignore

            return RedisSaver.from_conn_string(redis_url)
        except Exception:
            pass
    return _MEMORY_CHECKPOINTER


async def run_photocad_langgraph(
    scan_id: str,
    geometry_report: Open3DGeometryReport | Dict[str, Any],
    masked_image_urls: Optional[Dict[str, str]] = None,
    ply_local_path: Optional[str] = None,
    thread_id: Optional[str] = None,
    user_edit_instruction: Optional[str] = None,
    ws_event_cb: WsStreamCallback = None,
    checkpointer: Any = None,
) -> PhotoCADGraphState:
    """
    Executes or resumes the cyclic Dual-Loop LangGraph pipeline with streaming node transitions
    and hard `recursion_limit=20` safety cap.
    """
    compiled = build_photocad_graph(checkpointer=checkpointer)
    tid = thread_id or f"thread_{scan_id}"

    if isinstance(geometry_report, dict):
        geometry_report = Open3DGeometryReport(**geometry_report)

    config: Dict[str, Any] = {
        "configurable": {"thread_id": tid},
        "recursion_limit": 20,
        "tags": [f"scan:{scan_id}", "photocad-dual-loop"],
        "metadata": {
            "scan_id": scan_id,
            "mode": "refine" if user_edit_instruction else "initial_synthesis",
        },
    }

    # Check if resuming existing checkpoint thread for /refine
    snapshot = compiled.get_state(config)
    if user_edit_instruction and snapshot and snapshot.values:
        # Preserve prior spatial analysis & feature tree, update only edit instruction & loop counters
        input_state: Dict[str, Any] = {
            "user_edit_instruction": user_edit_instruction,
            "compile_retries": 0,
            "geometry_iterations": 0,
            "compile_error_trace": None,
            "validation_metrics": None,
            "best_chamfer_mm": float("inf"),
            "best_code": None,
            "best_artifact_keys": {},
            "final_status": "running",
        }
    else:
        input_state = {
            "scan_id": scan_id,
            "masked_image_urls": masked_image_urls or {},
            "geometry_report": geometry_report,
            "ply_local_path": ply_local_path,
            "user_edit_instruction": user_edit_instruction,
            "compile_retries": 0,
            "geometry_iterations": 0,
            "best_chamfer_mm": float("inf"),
            "best_artifact_keys": {},
            "final_status": "running",
            "event_log": [],
        }

    # Stream node-by-node updates for live WebSocket transitions & code diffs
    async for update in compiled.astream(input_state, config=config, stream_mode="updates"):
        if ws_event_cb:
            for _node_name, node_out in update.items():
                if isinstance(node_out, dict):
                    for ev in node_out.get("event_log", []):
                        await ws_event_cb(ev)

    final_snapshot = compiled.get_state(config)
    final_state: PhotoCADGraphState = dict(final_snapshot.values)

    if not final_state.get("best_code"):
        final_state["final_status"] = "failed"
    elif final_state.get("final_status") not in ("completed", "completed_with_warning"):
        metrics = final_state.get("best_metrics")
        passed = bool(
            metrics.passed_tolerance
            if hasattr(metrics, "passed_tolerance")
            else (metrics or {}).get("passed_tolerance", False)
        )
        final_state["final_status"] = "completed" if passed else "completed_with_warning"

    return final_state
