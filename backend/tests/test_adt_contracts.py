"""
Unit Tests for PhotoCAD Abstract Data Types (ADTs) & Data Contracts
Document ID: PCAD-API-ADT-003
"""

import pytest
from pydantic import ValidationError
from app.schemas.adt import (
    CaptureSide,
    CalibrationSpec,
    DetectedPlane,
    DetectedCylinder,
    Open3DGeometryReport,
    FeatureStep,
    CSGFeatureTree,
    ValidationMetrics
)

def test_calibration_spec_validation():
    # Valid known dimension
    spec = CalibrationSpec(
        mode="known_dimension",
        reference_side=CaptureSide.FRONT,
        known_length_mm=64.5,
        point_a_px=(100.0, 200.0),
        point_b_px=(500.0, 200.0),
        mm_per_unit=0.16125
    )
    assert spec.known_length_mm == 64.5
    assert spec.reference_side == CaptureSide.FRONT

    # Invalid length (<= 1.0mm)
    with pytest.raises(ValidationError):
        CalibrationSpec(
            mode="known_dimension",
            reference_side=CaptureSide.FRONT,
            known_length_mm=0.5
        )


def test_open3d_geometry_report_roundtrip():
    sample_data = {
        "scan_id": "scn_test_001",
        "units": "mm",
        "point_count": 125000,
        "icp_fitness_score": 0.94,
        "icp_inlier_rmse_mm": 0.32,
        "bounding_box_mm": [80.0, 50.0, 30.0],
        "principal_axes": [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0]
        ],
        "symmetry_planes": ["XY", "YZ"],
        "planes": [
            {
                "plane_id": "plane_base_01",
                "normal": [0.0, 0.0, -1.0],
                "centroid_mm": [0.0, 0.0, 0.0],
                "area_mm2": 4000.0,
                "inlier_ratio": 0.35
            }
        ],
        "cylinders": [
            {
                "cylinder_id": "cyl_center_hole",
                "kind": "through_hole",
                "axis_origin_mm": [0.0, 0.0, 15.0],
                "axis_direction": [0.0, 0.0, 1.0],
                "radius_mm": 8.0,
                "depth_mm": 30.0,
                "confidence": 0.98
            }
        ],
        "ply_object_key": "scans/scn_test_001/fused_cloud.ply"
    }

    report = Open3DGeometryReport(**sample_data)
    assert report.bounding_box_mm == (80.0, 50.0, 30.0)
    assert report.cylinders[0].radius_mm == 8.0
    assert report.planes[0].inlier_ratio == 0.35


def test_csg_feature_tree_structure():
    tree = CSGFeatureTree(
        part_summary="Precision Aluminum Mounting Bracket",
        coordinate_origin="center_bottom",
        global_parameters_mm={
            "LENGTH_MM": 80.0,
            "WIDTH_MM": 50.0,
            "THICKNESS_MM": 30.0,
            "HOLE_DIA_MM": 16.0,
            "FILLET_RADIUS_MM": 4.0
        },
        steps=[
            FeatureStep(
                step_index=1,
                operation="base_extrude",
                target_plane="XY",
                parameters_mm={"length": 80.0, "width": 50.0, "height": 30.0},
                rationale="Create primary bounding block solid"
            ),
            FeatureStep(
                step_index=2,
                operation="fillet",
                target_plane="|Z",
                parameters_mm={"radius": 4.0},
                rationale="Fillet vertical corner edges before cuts"
            ),
            FeatureStep(
                step_index=3,
                operation="hole",
                target_plane=">Z",
                parameters_mm={"diameter": 16.0, "depth": 30.0},
                rationale="Center through-hole cut along Z axis"
            )
        ]
    )
    assert len(tree.steps) == 3
    assert tree.global_parameters_mm["HOLE_DIA_MM"] == 16.0
    assert tree.steps[0].operation == "base_extrude"


def test_validation_metrics_tolerance():
    # Model passing tolerance (Chamfer <= 1.0mm)
    pass_metrics = ValidationMetrics(
        is_watertight=True,
        volume_mm3=115200.0,
        surface_area_mm2=15800.0,
        chamfer_mean_mm=0.65,
        chamfer_p95_mm=1.05,
        bbox_delta_mm=(0.2, -0.1, 0.4),
        passed_tolerance=True,
        discrepancy_notes=[]
    )
    assert pass_metrics.passed_tolerance is True
    assert pass_metrics.chamfer_mean_mm <= 1.0

    # Model failing tolerance (Chamfer > 1.0mm)
    fail_metrics = ValidationMetrics(
        is_watertight=True,
        volume_mm3=119000.0,
        surface_area_mm2=16200.0,
        chamfer_mean_mm=1.85,
        chamfer_p95_mm=3.20,
        bbox_delta_mm=(1.8, 0.5, 2.2),
        passed_tolerance=False,
        discrepancy_notes=["Top Z face exceeds scan by +2.2mm", "Fillet radius too small"]
    )
    assert fail_metrics.passed_tolerance is False
    assert len(fail_metrics.discrepancy_notes) == 2
