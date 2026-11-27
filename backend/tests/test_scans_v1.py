"""
Integration Tests for PhotoCAD Scan Sessions & Calibration API
Document ID: PCAD-API-ADT-003
"""

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_create_scan_session():
    res = client.post("/api/scans", json={
        "project_id": "proj_test_123",
        "title": "Precision Aluminum Flange"
    })
    assert res.status_code == 200
    data = res.json()
    assert "scan_id" in data
    assert data["status"] == "capturing"
    assert "front" in data["upload_urls"]
    assert "top" in data["upload_urls"]
    assert len(data["upload_urls"]) == 6

def test_confirm_view_with_blur_score():
    # 1. Create session
    create_res = client.post("/api/scans", json={"project_id": "proj_test_456"})
    scan_id = create_res.json()["scan_id"]

    # 2. Confirm sharp front view
    confirm_res = client.post(f"/api/scans/{scan_id}/views/front/confirm", json={
        "blur_score": 158.4,
        "width_px": 1920,
        "height_px": 1080
    })
    assert confirm_res.status_code == 200
    confirm_data = confirm_res.json()
    assert confirm_data["side"] == "front"
    assert confirm_data["is_sharp"] is True
    assert confirm_data["views_completed"] == 1

def test_metric_calibration_known_dimension():
    # 1. Create session
    create_res = client.post("/api/scans", json={"project_id": "proj_test_789"})
    scan_id = create_res.json()["scan_id"]

    # 2. Submit calibration spec
    calib_res = client.post(f"/api/scans/{scan_id}/calibrate", json={
        "mode": "known_dimension",
        "reference_side": "front",
        "known_length_mm": 64.5,
        "point_a_px": [100.0, 500.0],
        "point_b_px": [745.0, 500.0]  # dx = 645px -> scale = 64.5 / 645 = 0.1 mm/px
    })
    assert calib_res.status_code == 200
    calib_data = calib_res.json()
    assert calib_data["status"] == "calibrated"
    assert abs(calib_data["scale_px_to_mm"] - 0.1) < 0.001
