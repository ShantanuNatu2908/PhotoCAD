"""
Tests for Multi-View 3D Visual Hull Reconstruction, Cluttered Background Segmentation,
Sculpted STL/STEP/DXF Export, 5-View Fusion, and Saved Scans Listing API.
"""

from __future__ import annotations

import asyncio
import io

import cv2
import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from app.cad.interop_verifier import InteropVerifier
from app.core.config import settings
from app.core.database import init_db
from app.main import app

asyncio.run(init_db())
client = TestClient(app)


def _encode_png(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(arr, mode="RGB").save(buf, format="PNG")
    return buf.getvalue()


def _make_car_silhouette_views() -> dict[str, bytes]:
    """
    Synthesizes 5 distinct views (front, back, left, right, top — intentionally omitting bottom)
    of a low-slung tapered aerodynamic vehicle silhouette on a cluttered backdrop.
    """
    views: dict[str, bytes] = {}

    # 1. Left & Right: long low coupe profile (aspect ~ 3.2 : 1) on textured outdoor ground/sky backdrop
    for side in ("left", "right"):
        h, w = 220, 420
        bg = np.full((h, w, 3), 210, dtype=np.uint8)
        bg[:110, :] = [180, 195, 215]  # bright sky/wall upper band
        bg[110:, :] = [145, 145, 140]  # darker pavement lower band
        pts = np.array([[45, 165], [65, 130], [140, 118], [215, 92], [310, 96], [365, 128], [380, 165]], dtype=np.int32)
        if side == "left":
            pts[:, 0] = w - pts[:, 0]
        cv2.fillPoly(bg, [pts], (25, 115, 225))
        views[side] = _encode_png(bg)

    # 2. Front & Back: wide low nose/rear stance (aspect ~ 1.8 : 1)
    for side in ("front", "back"):
        h, w = 220, 320
        bg = np.full((h, w, 3), 235, dtype=np.uint8)
        pts = np.array([[50, 165], [58, 125], [105, 95], [215, 95], [262, 125], [270, 165]], dtype=np.int32)
        cv2.fillPoly(bg, [pts], (20, 110, 215))
        views[side] = _encode_png(bg)

    # 3. Top (portrait orientation matching overhead top photo, vertical nose-to-tail)
    h, w = 400, 240
    bg = np.full((h, w, 3), 245, dtype=np.uint8)
    pts_top = np.array([[75, 45], [120, 28], [165, 45], [178, 150], [176, 330], [160, 370], [80, 370], [64, 330], [62, 150]], dtype=np.int32)
    cv2.fillPoly(bg, [pts_top], (30, 95, 200))
    views["top"] = _encode_png(bg)

    return views


def test_5_view_sculpted_car_fusion_cad_and_saved_scans_api():
    scan_id = client.post("/api/scans", json={"project_id": "proj_car_hull", "title": "Sports Coupe"}).json()["scan_id"]
    car_views = _make_car_silhouette_views()

    for side, png_bytes in car_views.items():
        assert client.put(f"/api/scans/{scan_id}/views/{side}/upload", content=png_bytes).status_code == 200
        assert client.post(
            f"/api/scans/{scan_id}/views/{side}/confirm",
            json={"blur_score": 180.0, "manual_override": True},
        ).status_code == 200

    # Calibrate 1:1 mm using front grille width = 180 mm (scale model)
    assert client.post(f"/api/scans/{scan_id}/calibrate", json={
        "mode": "known_dimension",
        "reference_side": "front",
        "known_length_mm": 180.0,
    }).status_code == 200

    # 5-view fusion must succeed cleanly even without bottom view
    fuse_res = client.post(f"/api/scans/{scan_id}/fuse")
    assert fuse_res.status_code == 200, fuse_res.text
    fused = fuse_res.json()
    report = fused["geometry_report"]

    # Must NOT hallucinate a central circular bore hole on a solid car body
    assert report["cylinders"] == []
    lx, wy, hz = report["bounding_box_mm"]
    # Side car length (Y) must exceed front width (X), and height (Z) must be smallest
    assert wy > lx > hz

    # Generate sculpted B-Rep CAD
    gen_res = client.post(f"/api/scans/{scan_id}/generate")
    assert gen_res.status_code == 200
    gen_data = gen_res.json()
    assert gen_data["status"] == "completed"
    assert "Polygon(" in gen_data["code"]
    assert "Mode.INTERSECT" in gen_data["code"]
    assert "HOLE_DIA_MM" not in gen_data["code"]

    gen_id = gen_data["generation_id"]
    step_p = settings.EXPORTS_DIR / f"{gen_id}.step"
    dxf_p = settings.EXPORTS_DIR / f"{gen_id}.dxf"
    stl_p = settings.EXPORTS_DIR / f"{gen_id}.stl"
    interop = InteropVerifier.verify_bundle(step_p, dxf_p, stl_p)
    assert interop.autocad_compatible is True, interop.step.issues + interop.dxf.issues
    assert interop.stl.is_watertight is True
    assert interop.stl.triangle_count > 100

    # Saved scans listing API exposes the project, 5 confirmed sides, and latest generation
    scans_res = client.get("/api/scans")
    assert scans_res.status_code == 200
    listed = [row for row in scans_res.json() if row["scan_id"] == scan_id]
    assert len(listed) == 1
    assert listed[0]["views_count"] == 5
    assert listed[0]["latest_generation"]["id"] == gen_id
    assert "active_models" in gen_data


def test_strict_cloud_mode_refuses_silent_local_fallback():
    """When strict_cloud=True without Modal/LLM keys, endpoints fail cleanly with 503 instead of downgrading."""
    scan_id = client.post("/api/scans", json={"project_id": "proj_strict"}).json()["scan_id"]
    car_views = _make_car_silhouette_views()
    for side, png_bytes in car_views.items():
        client.put(f"/api/scans/{scan_id}/views/{side}/upload", content=png_bytes)
        client.post(f"/api/scans/{scan_id}/views/{side}/confirm", json={"blur_score": 180.0, "manual_override": True})
    client.post(f"/api/scans/{scan_id}/calibrate", json={"mode": "known_dimension", "reference_side": "front", "known_length_mm": 120.0})

    fuse_strict = client.post(f"/api/scans/{scan_id}/fuse", json={"strict_cloud": True})
    assert fuse_strict.status_code == 503
    assert fuse_strict.json()["error"]["code"] == "CLOUD_GPU_UNAVAILABLE"

    gen_strict = client.post(f"/api/scans/{scan_id}/generate", json={"strict_cloud": True})
    assert gen_strict.status_code == 503
    assert gen_strict.json()["error"]["code"] == "CLOUD_HIGH_ACCURACY_NOT_READY"
