"""JWT auth and tenant isolation tests (auth-multitenancy.skill.md)."""

from __future__ import annotations

import asyncio
import uuid

import jwt
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.database import init_db
from app.main import app

asyncio.run(init_db())
client = TestClient(app)
SECRET = "photocad-test-secret-with-at-least-32-bytes"


def _token(subject: str, tenant: str) -> str:
    return jwt.encode(
        {"sub": subject, "tenant_id": tenant, "iat": 1_700_000_000, "exp": 4_100_000_000},
        SECRET,
        algorithm="HS256",
    )


def _headers(tenant: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token('user-' + tenant, tenant)}"}


def test_dev_bypass_allows_unauthenticated_requests(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    response = client.get("/api/projects")
    assert response.status_code == 200


def test_missing_token_is_rejected_when_auth_is_enabled(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", SECRET)
    response = client.get("/api/projects")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_project_is_private_to_its_tenant(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", SECRET)
    created = client.post(
        "/api/projects",
        json={"name": f"Tenant A project {uuid.uuid4().hex[:8]}"},
        headers=_headers("tenant-a"),
    )
    assert created.status_code == 200
    project_id = created.json()["id"]

    owner = client.get(f"/api/projects/{project_id}", headers=_headers("tenant-a"))
    assert owner.status_code == 200

    other = client.get(f"/api/projects/{project_id}", headers=_headers("tenant-b"))
    assert other.status_code == 404

    listing = client.get("/api/projects", headers=_headers("tenant-b"))
    assert all(item["id"] != project_id for item in listing.json())


def test_scan_session_is_private_to_its_tenant(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", SECRET)
    project_id = f"proj_scan_auth_{uuid.uuid4().hex[:8]}"
    created = client.post(
        "/api/scans",
        json={"project_id": project_id},
        headers=_headers("tenant-c"),
    )
    assert created.status_code == 200
    scan_id = created.json()["scan_id"]

    assert client.get(f"/api/scans/{scan_id}", headers=_headers("tenant-c")).status_code == 200
    assert client.get(f"/api/scans/{scan_id}", headers=_headers("tenant-d")).status_code == 404


def test_websocket_handshake_rejects_foreign_tenant(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", SECRET)
    created = client.post(
        "/api/scans",
        json={"project_id": f"proj_ws_auth_{uuid.uuid4().hex[:8]}"},
        headers=_headers("tenant-e"),
    )
    scan_id = created.json()["scan_id"]

    with pytest.raises(WebSocketDisconnect) as denied:
        with client.websocket_connect(
            f"/ws/v1/scans/{scan_id}", headers=_headers("tenant-f")
        ):
            pass
    assert denied.value.code == 1008
