"""
End-to-End FastAPI Integration Tests for Phase 4 Scan-to-CAD Generation & /refine API
Document ID: PCAD-API-ADT-003 / PCAD-LG-004
"""

from __future__ import annotations

import asyncio
import io

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from app.core.database import init_db
from app.main import app

asyncio.run(init_db())
client = TestClient(app)

SIX_SIDES = ["front", "back", "left", "right", "top", "bottom"]


def _make_part_png(width: int = 320, height: int = 240) -> bytes:
    arr = np.full((height, width, 3), 20, dtype=np.uint8)
    arr[50:190, 70:250] = [180, 200, 215]
    buf = io.BytesIO()
    Image.fromarray(arr, mode="RGB").save(buf, format="PNG")
    return buf.getvalue()


def test_full_scan_fuse_generate_refine_export_flow():
    # 1. Create scan, upload 6 views, confirm sharpness, calibrate & fuse
    scan_id = client.post("/api/scans", json={"project_id": "proj_phase4_e2e"}).json()["scan_id"]
    png_bytes = _make_part_png()

    for side in SIX_SIDES:
        client.put(f"/api/scans/{scan_id}/views/{side}/upload", content=png_bytes)
        client.post(f"/api/scans/{scan_id}/views/{side}/confirm", json={"blur_score": 185.0})

    client.post(f"/api/scans/{scan_id}/calibrate", json={
        "mode": "known_dimension",
        "reference_side": "front",
        "known_length_mm": 90.0,
        "point_a_px": [70.0, 120.0],
        "point_b_px": [250.0, 120.0],
    })

    fuse_res = client.post(f"/api/scans/{scan_id}/fuse")
    assert fuse_res.status_code == 200

    # 2. Generate CAD B-Rep via Phase 4 5-Node LangGraph Pipeline
    gen_res = client.post(f"/api/scans/{scan_id}/generate")
    assert gen_res.status_code == 200
    gen_data = gen_res.json()
    assert gen_data["revision"] == 1
    assert gen_data["status"] == "completed"
    assert "RESULT_PART = part.part" in gen_data["code"]
    gen_id = gen_data["generation_id"]

    # Verify downloadable exports (.step, .stl, .dxf, .py)
    step_res = client.get(f"/api/export/{gen_id}/step")
    assert step_res.status_code == 200
    assert step_res.text.startswith("ISO-10303-21;")

    stl_res = client.get(f"/api/export/{gen_id}/stl")
    assert stl_res.status_code == 200
    assert "endsolid" in stl_res.text

    dxf_res = client.get(f"/api/export/{gen_id}/dxf")
    assert dxf_res.status_code == 200
    assert "$INSUNITS" in dxf_res.text

    py_res = client.get(f"/api/export/{gen_id}/py")
    assert py_res.status_code == 200
    assert "from build123d import" in py_res.text

    # 3. Conversational Parametric Edit (/refine) -> Revision 2
    ref_res = client.post(f"/api/scans/{scan_id}/refine", json={
        "base_revision": 1,
        "instruction": "Change the center hole diameter to 12 mm and add a 1.5 mm chamfer.",
    })
    assert ref_res.status_code == 200
    ref_data = ref_res.json()
    assert ref_data["revision"] == 2
    assert "HOLE_DIA_MM = 12.00" in ref_data["code"]
    assert "CHAMFER_MM = 1.50" in ref_data["code"]

    # 4. Revision Artifacts lookup endpoint
    art_res = client.get(f"/api/scans/{scan_id}/revisions/2/artifacts")
    assert art_res.status_code == 200
    assert art_res.json()["revision"] == 2
    assert art_res.json()["artifacts"]["step_url"].endswith("/step")


def test_async_trigger_endpoint_avoids_lazy_load_error():
    """Regression test: POST /api/generate/trigger must serialize cleanly under AsyncSession."""
    scan_id = client.post("/api/scans", json={"project_id": "proj_async_trigger"}).json()["scan_id"]
    trig = client.post("/api/generate/trigger", json={
        "scan_session_id": scan_id,
        "target_engine": "build123d",
    })
    assert trig.status_code == 200
    data = trig.json()
    assert "id" in data
    assert data["agent_logs"] == []

    # Verify status endpoint returns populated generation & logs
    gen_id = data["id"]
    status_res = client.get(f"/api/generate/{gen_id}")
    assert status_res.status_code == 200
    assert status_res.json()["status"] in ("completed", "pending", "generating", "compiling")


def test_refine_supports_natural_language_without_mm_suffix_and_removal():
    """Verifies /refine handles missing 'mm' units, LxWxH triples, and 'remove hole' requests."""
    scan_id = client.post("/api/scans", json={"project_id": "proj_refine_nlp"}).json()["scan_id"]
    png_bytes = _make_part_png()

    for side in SIX_SIDES:
        client.put(f"/api/scans/{scan_id}/views/{side}/upload", content=png_bytes)
        client.post(f"/api/scans/{scan_id}/views/{side}/confirm", json={"blur_score": 190.0})

    client.post(f"/api/scans/{scan_id}/calibrate", json={
        "mode": "known_dimension",
        "reference_side": "front",
        "known_length_mm": 80.0,
        "point_a_px": [70.0, 120.0],
        "point_b_px": [250.0, 120.0],
    })
    assert client.post(f"/api/scans/{scan_id}/fuse").status_code == 200
    assert client.post(f"/api/scans/{scan_id}/generate").status_code == 200

    # Refine without 'mm' unit suffix and with LxWxH shorthand
    ref1 = client.post(f"/api/scans/{scan_id}/refine", json={
        "base_revision": 1,
        "instruction": "change hole to 14 and 100x60x25",
    })
    assert ref1.status_code == 200
    body1 = ref1.json()
    assert body1["dimensions_mm"]["x"] == 100.0
    assert body1["dimensions_mm"]["y"] == 60.0
    assert body1["dimensions_mm"]["z"] == 25.0
    assert "HOLE_DIA_MM = 14.00" in body1["code"]
    assert isinstance(body1.get("agent_logs"), list) and len(body1["agent_logs"]) > 0
    assert isinstance(body1.get("validation_metrics"), dict)

    # Remove center hole cleanly (no hole constant or subtractive cylinder emitted)
    ref2 = client.post(f"/api/scans/{scan_id}/refine", json={
        "base_revision": 2,
        "instruction": "remove center hole",
    })
    assert ref2.status_code == 200
    body2 = ref2.json()
    assert "HOLE_DIA_MM" not in body2["code"]
    assert "Mode.SUBTRACT" not in body2["code"]
    assert body2["dimensions_mm"]["x"] == 100.0
