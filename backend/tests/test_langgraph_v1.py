"""
End-to-End Integration Tests for Phase 4 Cyclic 5-Node LangGraph Workflow
Document ID: PCAD-LG-004 / langgraph-agents.skill.md

Verifies:
1. Full 5-node happy-path convergence with valid watertight .STEP/.STL/.DXF + Chamfer <= 1.0mm
2. Inner Self-Healing Loop catching BRepFilletAPI failure and patching code on retry
3. Outer Accuracy Loop catching high-Chamfer delta (>1.0mm) and converging in Iteration 2
4. Stateful Checkpointing & `/refine` parametric editing skipping Node 1
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

from langgraph.checkpoint.memory import MemorySaver

from app.agents.graph import run_photocad_langgraph
from app.schemas.adt import (
    CSGFeatureTree,
    DetectedCylinder,
    FeatureStep,
    Open3DGeometryReport,
)


def _make_report(scan_id: str = "scn_lg_01", lx: float = 80.0, wy: float = 50.0, hz: float = 30.0) -> Open3DGeometryReport:
    return Open3DGeometryReport(
        scan_id=scan_id,
        units="mm",
        point_count=4500,
        icp_fitness_score=0.93,
        icp_inlier_rmse_mm=0.22,
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
                radius_mm=8.0,
                depth_mm=hz,
                confidence=0.96,
            )
        ],
        ply_object_key=f"cad_exports/{scan_id}/fused_cloud.ply",
    )


def test_langgraph_happy_path_5_node_convergence():
    events = []

    async def capture_ev(ev):
        events.append(ev)

    state = asyncio.run(
        run_photocad_langgraph(
            scan_id="scn_lg_happy",
            geometry_report=_make_report("scn_lg_happy"),
            masked_image_urls={"front": "/storage/front.png"},
            thread_id="th_happy_01",
            ws_event_cb=capture_ev,
            checkpointer=MemorySaver(),
        )
    )

    assert state["final_status"] == "completed"
    assert state["best_chamfer_mm"] <= 1.0
    assert state["geometry_iterations"] == 1
    assert state["compile_retries"] == 0
    assert "RESULT_PART = part.part" in (state.get("best_code") or "")
    assert Path(state["best_artifact_keys"]["step_path"]).exists()
    assert Path(state["best_artifact_keys"]["stl_path"]).exists()
    assert Path(state["best_artifact_keys"]["dxf_path"]).exists()

    ev_names = [e["event"] for e in events]
    assert "agent_node_started" in ev_names
    assert "cad_code_diff" in ev_names
    assert "validation_completed" in ev_names


def test_langgraph_inner_self_healing_loop_repairs_fillet_crash():
    call_counter = {"count": 0}
    from app.agents.nodes import synthesizer

    original_render = synthesizer._render_canonical_build123d

    def faulty_first_render(tree, error_trace=None, previous_code=None):
        call_counter["count"] += 1
        if call_counter["count"] == 1 and not error_trace:
            # Inject impossible fillet radius (20mm on 30mm wall > 30/2.5 = 12mm)
            return """from build123d import BuildPart, BuildSketch, Rectangle, Circle, Mode, Axis, extrude, fillet
LENGTH_MM = 80.0
WIDTH_MM = 50.0
THICKNESS_MM = 30.0
HOLE_DIA_MM = 16.0
TOP_FILLET_MM = 20.0
with BuildPart() as part:
    with BuildSketch():
        Rectangle(LENGTH_MM, WIDTH_MM)
    extrude(amount=THICKNESS_MM)
    with BuildSketch(part.faces().sort_by(Axis.Z)[-1]):
        Circle(radius=HOLE_DIA_MM / 2.0)
    extrude(amount=-THICKNESS_MM, mode=Mode.SUBTRACT)
    fillet(part.edges().filter_by(Axis.Z), radius=TOP_FILLET_MM)
RESULT_PART = part.part
"""
        return original_render(tree, error_trace=error_trace, previous_code=previous_code)

    with patch.object(synthesizer, "_render_canonical_build123d", side_effect=faulty_first_render):
        state = asyncio.run(
            run_photocad_langgraph(
                scan_id="scn_lg_inner",
                geometry_report=_make_report("scn_lg_inner"),
                thread_id="th_inner_01",
                checkpointer=MemorySaver(),
            )
        )

    assert call_counter["count"] >= 2
    assert state["final_status"] == "completed"
    assert state["best_chamfer_mm"] <= 1.0
    assert any(e["event"] == "cad_compile_error" for e in state["event_log"])


def test_langgraph_outer_accuracy_loop_fixes_chamfer_delta():
    from app.agents.nodes import architect

    original_builder = architect._build_deterministic_feature_tree
    build_calls = {"count": 0}

    def imprecise_initial_tree(state):
        build_calls["count"] += 1
        if build_calls["count"] == 1:
            # First iteration starts with oversized +10mm length and +8mm height error
            return CSGFeatureTree(
                part_summary="Oversized Draft Guess",
                coordinate_origin="center_bottom",
                global_parameters_mm={
                    "LENGTH_MM": 90.0,
                    "WIDTH_MM": 50.0,
                    "THICKNESS_MM": 38.0,
                    "HOLE_DIA_MM": 16.0,
                    "FILLET_RADIUS_MM": 2.0,
                },
                steps=[
                    FeatureStep(
                        step_index=1,
                        operation="base_extrude",
                        target_plane="XY",
                        parameters_mm={"length": 90.0, "width": 50.0, "thickness": 38.0},
                        rationale="Initial unrefined guess",
                    )
                ],
            )
        # Iteration 2 applies Node 5 bbox_delta_mm feedback cleanly inside original_builder!
        return original_builder(state)

    with patch.object(architect, "_build_deterministic_feature_tree", side_effect=imprecise_initial_tree):
        state = asyncio.run(
            run_photocad_langgraph(
                scan_id="scn_lg_outer",
                geometry_report=_make_report("scn_lg_outer"),
                thread_id="th_outer_01",
                checkpointer=MemorySaver(),
            )
        )

    assert build_calls["count"] == 2
    assert state["geometry_iterations"] == 2
    assert state["final_status"] == "completed"
    assert state["best_chamfer_mm"] <= 1.0


def test_langgraph_checkpoint_refine_skips_node_1():
    cp = MemorySaver()
    report = _make_report("scn_lg_refine")

    # Pass 1: Full synthesis with 16mm hole
    init_state = asyncio.run(
        run_photocad_langgraph(
            scan_id="scn_lg_refine",
            geometry_report=report,
            thread_id="th_refine_shared",
            checkpointer=cp,
        )
    )
    assert init_state["final_status"] == "completed"
    assert "HOLE_DIA_MM = 16.00" in (init_state.get("best_code") or "")

    # Pass 2: Conversational /refine on same thread updates hole to 10mm cleanly
    refine_events = []

    async def capture_ref(ev):
        refine_events.append(ev)

    refine_state = asyncio.run(
        run_photocad_langgraph(
            scan_id="scn_lg_refine",
            geometry_report=report,
            thread_id="th_refine_shared",
            user_edit_instruction="Change the center hole diameter from 16 mm to 10 mm.",
            ws_event_cb=capture_ref,
            checkpointer=cp,
        )
    )

    nodes_visited = [
        e["payload"]["node"]
        for e in refine_events
        if e["event"] == "agent_node_started"
    ]
    assert "geometry_analyst" not in nodes_visited
    assert "parametric_architect" in nodes_visited
    assert "HOLE_DIA_MM = 10.00" in (refine_state.get("best_code") or "")
    assert refine_state["best_dimensions_mm"] == {"x": 80.0, "y": 50.0, "z": 30.0}
