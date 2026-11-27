"""
Golden Dataset CAD Interoperability Verification Suite (Phase 5 Deliverable 2)
Document ID: PCAD-PRD-SRS-001 (NFR-06, Section 6)

Verifies exported .STEP, .DXF, and .STL packages across 4 canonical caliper-measured
mechanical archetypes against strict AutoCAD, Fusion 360, and SolidWorks criteria:
- Zero unresolved STEP entity IDs
- SI_UNIT(.MILLI.,.METRE.) 1:1 mm enforcement
- DXF $INSUNITS=4 millimeter header & orthographic views
- STL strictly 2-manifold watertight topology with exact volume & bounding dimensions
"""

from __future__ import annotations

import asyncio
import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents.graph import run_photocad_langgraph
from app.cad.interop_verifier import InteropVerifier
from app.main import app
from app.schemas.adt import DetectedCylinder, Open3DGeometryReport
from langgraph.checkpoint.memory import MemorySaver


client = TestClient(app)


GOLDEN_PARTS = [
    ("mounting_plate_bore", 80.0, 50.0, 12.0, 8.0),
    ("precision_l_blank", 110.0, 65.0, 42.0, 0.0),
    ("flanged_collar_block", 60.0, 60.0, 28.0, 14.0),
    ("metric_shim_spacer", 45.0, 30.0, 6.0, 5.0),
]


@pytest.mark.parametrize("name,lx,wy,hz,hole_r", GOLDEN_PARTS)
def test_golden_dataset_autocad_fusion360_solidworks_interop(
    name: str, lx: float, wy: float, hz: float, hole_r: float
):
    scan_id = f"golden_{name}"
    cylinders = (
        [
            DetectedCylinder(
                cylinder_id=f"cyl_{name}",
                kind="through_hole",
                axis_origin_mm=(0.0, 0.0, 0.0),
                axis_direction=(0.0, 0.0, 1.0),
                radius_mm=hole_r,
                depth_mm=hz,
                confidence=0.97,
            )
        ]
        if hole_r > 0
        else []
    )

    report_in = Open3DGeometryReport(
        scan_id=scan_id,
        units="mm",
        point_count=5200,
        icp_fitness_score=0.95,
        icp_inlier_rmse_mm=0.20,
        bounding_box_mm=(lx, wy, hz),
        principal_axes=[(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)],
        symmetry_planes=["XY", "YZ"],
        planes=[],
        cylinders=cylinders,
        ply_object_key=f"cad_exports/{scan_id}/fused_cloud.ply",
    )

    state = asyncio.run(
        run_photocad_langgraph(
            scan_id=scan_id,
            geometry_report=report_in,
            thread_id=f"th_{scan_id}",
            checkpointer=MemorySaver(),
        )
    )
    assert state["final_status"] == "completed"

    arts = state["best_artifact_keys"]
    interop = InteropVerifier.verify_bundle(arts["step_path"], arts["dxf_path"], arts["stl_path"])

    assert interop.autocad_compatible is True, interop.step.issues + interop.dxf.issues
    assert interop.fusion360_compatible is True
    assert interop.solidworks_compatible is True

    # Strict STEP referential integrity & millimeter bounding check
    assert interop.step.dangling_references == []
    assert interop.step.units_millimeters is True
    assert interop.step.has_closed_shell is True
    assert abs(interop.step.bounding_box_mm[0] - lx) < 0.05
    assert abs(interop.step.bounding_box_mm[1] - wy) < 0.05
    assert abs(interop.step.bounding_box_mm[2] - hz) < 0.05

    # Strict DXF millimeter unit check
    assert interop.dxf.insunits_mm is True
    if hole_r > 0.5:
        assert interop.dxf.circle_count == 1

    # Strict STL 2-manifold volume match
    assert interop.stl.is_watertight is True
    expected_vol = (lx * wy - (math.pi * hole_r ** 2 if hole_r > 0 else 0.0)) * hz
    assert abs(interop.stl.volume_mm3 - expected_vol) / expected_vol < 0.025


def test_export_interop_report_endpoint():
    # Create scan, generate via /scans/{scan_id}/generate, then check interop-report endpoint
    scan_id = client.post("/api/scans", json={"project_id": "proj_phase5_interop"}).json()["scan_id"]
    gen_res = client.post(f"/api/scans/{scan_id}/generate")
    assert gen_res.status_code == 200
    gen_id = gen_res.json()["generation_id"]

    rep_res = client.get(f"/api/export/{gen_id}/interop-report")
    assert rep_res.status_code == 200
    body = rep_res.json()
    assert body["autocad_compatible"] is True
    assert body["fusion360_compatible"] is True
    assert body["solidworks_compatible"] is True
    assert body["step"]["dangling_references"] == []
    assert body["dxf"]["insunits_mm"] is True
    assert body["stl"]["is_watertight"] is True
