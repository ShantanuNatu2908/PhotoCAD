"""
Integration Tests for Phase 3 Cloud CV & 6-Side 3D Fusion Pipeline
Document ID: PCAD-API-ADT-003 / PCAD-PRD-SRS-001 (FR-07..FR-10)
"""

from __future__ import annotations

import asyncio
import io
from unittest.mock import MagicMock, patch

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from app.core.database import init_db
from app.main import app
from app.schemas.adt import Open3DGeometryReport


asyncio.run(init_db())
client = TestClient(app)

SIX_SIDES = ["front", "back", "left", "right", "top", "bottom"]


def _make_synthetic_png_bytes(width: int = 320, height: int = 240) -> bytes:
    """Generates a deterministic mechanical-part test PNG with crisp foreground box & background."""
    arr = np.full((height, width, 3), 24, dtype=np.uint8)  # Dark studio desk background
    # Metallic silver bracket silhouette in center
    arr[50:190, 70:250] = [175, 195, 210]
    # Simulated holding skin band on bottom-left corner (tests hand stripping)
    arr[195:240, 0:65] = [210, 150, 125]
    buf = io.BytesIO()
    Image.fromarray(arr, mode="RGB").save(buf, format="PNG")
    return buf.getvalue()


def test_fuse_rejects_missing_calibration():
    create_res = client.post("/api/scans", json={"project_id": "proj_phase3_01"})
    assert create_res.status_code == 200
    scan_id = create_res.json()["scan_id"]

    # Attempting fusion before calibration must return CALIBRATION_MISSING envelope
    fuse_res = client.post(f"/api/scans/{scan_id}/fuse")
    assert fuse_res.status_code == 400
    body = fuse_res.json()
    assert body["error"]["code"] == "CALIBRATION_MISSING"


def test_fuse_rejects_incomplete_views():
    create_res = client.post("/api/scans", json={"project_id": "proj_phase3_02"})
    scan_id = create_res.json()["scan_id"]

    # Lock calibration first, confirm only 1 side
    calib_res = client.post(f"/api/scans/{scan_id}/calibrate", json={
        "mode": "known_dimension",
        "reference_side": "front",
        "known_length_mm": 80.0,
        "point_a_px": [70.0, 120.0],
        "point_b_px": [250.0, 120.0],
    })
    assert calib_res.status_code == 200

    client.post(f"/api/scans/{scan_id}/views/front/confirm", json={"blur_score": 165.0})

    fuse_res = client.post(f"/api/scans/{scan_id}/fuse")
    assert fuse_res.status_code == 400
    body = fuse_res.json()
    assert body["error"]["code"] == "VIEWS_INCOMPLETE"
    assert "back" in body["error"]["details"]["missing_sides"]


def test_end_to_end_6_view_upload_calibration_and_fusion():
    # 1. Initialize scan session
    create_res = client.post("/api/scans", json={"project_id": "proj_phase3_e2e"})
    assert create_res.status_code == 200
    scan_id = create_res.json()["scan_id"]
    png_bytes = _make_synthetic_png_bytes()

    # 2. Upload raw PNG keyframes + confirm sharp Laplacian blur score for all 6 sides
    for side in SIX_SIDES:
        put_res = client.put(
            f"/api/scans/{scan_id}/views/{side}/upload",
            content=png_bytes,
            headers={"Content-Type": "image/png"},
        )
        assert put_res.status_code == 200
        assert put_res.json()["bytes_written"] == len(png_bytes)

        confirm_res = client.post(f"/api/scans/{scan_id}/views/{side}/confirm", json={
            "blur_score": 195.5,
            "width_px": 320,
            "height_px": 240,
        })
        assert confirm_res.status_code == 200
        assert confirm_res.json()["is_sharp"] is True

    # 3. Calibrate real-world millimeter scale (180 px wide object = 90.0 mm -> 0.5 mm/px)
    calib_res = client.post(f"/api/scans/{scan_id}/calibrate", json={
        "mode": "known_dimension",
        "reference_side": "front",
        "known_length_mm": 90.0,
        "point_a_px": [70.0, 120.0],
        "point_b_px": [250.0, 120.0],
    })
    assert calib_res.status_code == 200
    assert abs(calib_res.json()["scale_px_to_mm"] - 0.5) < 0.001

    # 4. Run Phase 3 CV & 3D Fusion pipeline
    fuse_res = client.post(f"/api/scans/{scan_id}/fuse")
    assert fuse_res.status_code == 200
    fused = fuse_res.json()
    assert fused["status"] == "fused"

    # Validate strict ADT conformance
    report = Open3DGeometryReport(**fused["geometry_report"])
    assert report.units == "mm"
    assert report.point_count >= 1000
    assert report.icp_fitness_score >= 0.65
    assert len(report.planes) >= 4
    assert len(report.cylinders) >= 1
    assert abs(report.bounding_box_mm[0] - 90.0) < 5.0

    # 5. Verify generated .PLY file and masked RGBA image are served cleanly
    ply_res = client.get(fused["ply_url"])
    assert ply_res.status_code == 200
    assert ply_res.text.startswith("ply\nformat ascii 1.0")
    assert f"element vertex {report.point_count}" in ply_res.text

    masked_front_res = client.get(fused["masked_urls"]["front"])
    assert masked_front_res.status_code == 200
    masked_img = Image.open(io.BytesIO(masked_front_res.content))
    assert masked_img.mode == "RGBA"
    # Verify bottom-left skin region has been stripped to transparent alpha=0
    assert masked_img.getpixel((10, 230))[3] == 0

    # 6. Retrieve geometry endpoint
    geo_res = client.get(f"/api/scans/{scan_id}/geometry")
    assert geo_res.status_code == 200
    assert geo_res.json()["geometry_report"]["scan_id"] == scan_id


def test_modal_remote_gpu_dispatch_contract():
    """Verifies CVPipelineService invokes Modal remote L4 function cleanly when configured."""
    create_res = client.post("/api/scans", json={"project_id": "proj_phase3_modal"})
    scan_id = create_res.json()["scan_id"]
    png_bytes = _make_synthetic_png_bytes()

    for side in SIX_SIDES:
        client.put(f"/api/scans/{scan_id}/views/{side}/upload", content=png_bytes)
        client.post(f"/api/scans/{scan_id}/views/{side}/confirm", json={"blur_score": 180.0})

    client.post(f"/api/scans/{scan_id}/calibrate", json={
        "mode": "id1_card",
        "reference_side": "front",
        "known_length_mm": 85.6,
        "point_a_px": [50.0, 50.0],
        "point_b_px": [221.2, 50.0],
    })

    mock_fn = MagicMock()
    mock_fn.remote.return_value = {
        "status": "completed",
        "geometry_report": {
            "scan_id": scan_id,
            "units": "mm",
            "point_count": 24500,
            "icp_fitness_score": 0.91,
            "icp_inlier_rmse_mm": 0.34,
            "bounding_box_mm": [85.6, 53.98, 22.0],
            "principal_axes": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            "symmetry_planes": ["XY", "XZ"],
            "planes": [],
            "cylinders": [],
            "ply_object_key": f"cad_exports/{scan_id}/fused_cloud.ply",
        },
        "masked_views": {},
        "ply_b64": "cGx5CmZvcm1hdCBhc2NpaSAxLjAKZWxlbWVudCB2ZXJ0ZXggMAplbmRfaGVhZGVyCg==",
        "telemetry": {"total_elapsed_ms": 9420.5},
    }

    fake_modal = MagicMock()
    fake_modal.Function.from_name.return_value = mock_fn

    with patch("app.services.cv_pipeline_service._is_modal_configured", return_value=True), \
         patch.dict("sys.modules", {"modal": fake_modal}):
        fuse_res = client.post(f"/api/scans/{scan_id}/fuse")

    assert fuse_res.status_code == 200
    body = fuse_res.json()
    assert body["execution_mode"] == "modal_l4_gpu"
    assert body["geometry_report"]["point_count"] == 24500
    assert body["telemetry"]["total_elapsed_ms"] < 15000
    mock_fn.remote.assert_called_once()
