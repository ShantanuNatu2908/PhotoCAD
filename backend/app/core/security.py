"""
PhotoCAD optional JWT auth and tenant resolution (auth-multitenancy.skill.md).

When no JWT secret is configured the API stays in explicit local-developer bypass
mode (`tenant_id = "public"`). Setting JWT_SECRET or SUPABASE_JWT_SECRET turns on
enforcement for every REST route and WebSocket handshake.
"""

from __future__ import annotations

import os
from contextvars import ContextVar
from typing import Any, AsyncGenerator, Dict, Optional

import jwt
from fastapi import HTTPException, Request, WebSocket, WebSocketDisconnect, status
from jwt.types import Options

PUBLIC_TENANT = "public"
_TENANT_CONTEXT: ContextVar[str] = ContextVar("photocad_tenant_id", default=PUBLIC_TENANT)


def auth_enabled() -> bool:
    """True when a JWT secret has been configured (Supabase HS256 compatible)."""
    for name in ("JWT_SECRET", "SUPABASE_JWT_SECRET"):
        value = os.getenv(name, "").strip()
        if value and "your-" not in value:
            return True
    return False


def _secret() -> str:
    for name in ("JWT_SECRET", "SUPABASE_JWT_SECRET"):
        value = os.getenv(name, "").strip()
        if value and "your-" not in value:
            return value
    return ""


def tenant_from_claims(claims: Dict[str, Any]) -> str:
    """Derives tenant scope only from verified claims, never from request bodies."""
    metadata = claims.get("app_metadata") or {}
    candidate = (
        claims.get("tenant_id")
        or claims.get("organization_id")
        or metadata.get("tenant_id")
        or claims.get("sub")
        or PUBLIC_TENANT
    )
    tenant = str(candidate).strip()
    return tenant or PUBLIC_TENANT


def decode_token(token: str) -> Dict[str, Any]:
    """Validates signature, expiry and optionally issuer without any network call."""
    options: Options = {"verify_aud": False}
    kwargs: Dict[str, Any] = {}
    issuer = os.getenv("JWT_ISSUER", "").strip()
    if issuer and "your-" not in issuer:
        kwargs["issuer"] = issuer
    try:
        return jwt.decode(token, _secret(), algorithms=["HS256"], options=options, **kwargs)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def bearer_token(headers: Any) -> Optional[str]:
    """Accepts `Authorization: Bearer <token>` from FastAPI or WebSocket headers."""
    raw = headers.get("authorization") or headers.get("Authorization") or ""
    if not isinstance(raw, str):
        return None
    parts = raw.strip().split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


async def get_current_tenant(request: Request) -> AsyncGenerator[str, None]:
    """FastAPI dependency that sets and then resets the request tenant context."""
    tenant = PUBLIC_TENANT
    if auth_enabled():
        token = bearer_token(request.headers)
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )
        tenant = tenant_from_claims(decode_token(token))
    context_token = _TENANT_CONTEXT.set(tenant)
    try:
        yield tenant
    finally:
        _TENANT_CONTEXT.reset(context_token)


def current_tenant() -> str:
    """Returns the tenant scope for the current request/task."""
    return _TENANT_CONTEXT.get()


async def authenticate_websocket(websocket: WebSocket) -> str:
    """Authenticates a WS handshake before `accept()`, preventing data leaks."""
    tenant = PUBLIC_TENANT
    if auth_enabled():
        token = bearer_token(websocket.headers)
        if not token:
            await websocket.close(code=1008, reason="Authentication required")
            raise WebSocketDisconnect(code=1008)
        try:
            tenant = tenant_from_claims(decode_token(token))
        except HTTPException as exc:
            await websocket.close(code=1008, reason=str(exc.detail))
            raise WebSocketDisconnect(code=1008) from exc
    _TENANT_CONTEXT.set(tenant)
    return tenant
