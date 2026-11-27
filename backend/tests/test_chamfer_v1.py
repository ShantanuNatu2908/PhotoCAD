"""
Unit Tests for Phase 4 Open3D/NumPy Chamfer Distance Validator
Document ID: PCAD-LG-004 (Node 5) / NFR-04
"""

from __future__ import annotations

import math
from pathlib import Path

from app.cad.chamfer_validator import ChamferValidator
from app.cad.exporter import write_parametric_stl
from app.schemas.adt import DetectedCylinder, Open3DGeometryReport


def _sample_report(lx: float = 80.0, wy: float = 50.0, hz: float = 30.0, hole_r: float = 8.0) -> Open3DGeometryReport:
    return Open3DGeometryReport(
        scan_id="scn_chamfer_01",
        units="mm",
        point_count=4500,
        icp_fitness_score=0.92,
        icp_inlier_rmse_mm=0.25,
        bounding_box_mm=(lx, wy, hz),
        principal_axes=[(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)],
        symmetry_planes=["XY", "YZ"],
        planes=[],
        cylinders=[
            DetectedCylinder(
                cylinder_id="cyl_01",
                kind="through_hole",
                axis_origin_mm=(0.0, 0.0, 0.0),
                axis_direction=(0.0, 0.0, 1.0),
                radius_mm=hole_r,
                depth_mm=hz,
                confidence=0.95,
            )
        ],
        ply_object_key="cad_exports/scn_chamfer_01/fused_cloud.ply",
    )


def test_chamfer_validator_passes_matching_watertight_part(tmp_path: Path):
    stl_path = tmp_path / "matching.stl"
    write_parametric_stl(stl_path, 80.0, 50.0, 30.0, hole_radius_mm=8.0)

    report = _sample_report(80.0, 50.0, 30.0, hole_r=8.0)
    metrics = ChamferValidator.evaluate(stl_path, geometry_report=report)

    assert metrics.is_watertight is True
    assert metrics.passed_tolerance is True
    assert metrics.chamfer_mean_mm <= 1.0
    expected_vol = (80.0 * 50.0 - math.pi * (8.0 ** 2)) * 30.0
    assert abs(metrics.volume_mm3 - expected_vol) / expected_vol < 0.02
    assert all(abs(d) < 0.5 for d in metrics.bbox_delta_mm)


def test_chamfer_validator_rejects_mismatched_dimensions_with_notes(tmp_path: Path):
    stl_path = tmp_path / "oversized.stl"
    # Intentionally synthesize wrong length (+14mm) & wrong thickness (+8mm)
    write_parametric_stl(stl_path, 94.0, 50.0, 38.0, hole_radius_mm=8.0)

    report = _sample_report(80.0, 50.0, 30.0, hole_r=8.0)
    metrics = ChamferValidator.evaluate(stl_path, geometry_report=report)

    assert metrics.is_watertight is True
    assert metrics.passed_tolerance is False
    assert metrics.chamfer_mean_mm > 1.0
    assert abs(metrics.bbox_delta_mm[0] - 14.0) < 0.5
    assert abs(metrics.bbox_delta_mm[2] - 8.0) < 0.5
    assert any("LENGTH_MM" in note for note in metrics.discrepancy_notes)
    assert any("THICKNESS_MM" in note for note in metrics.discrepancy_notes)
