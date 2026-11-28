"""Row-level tenant ownership helpers (auth-multitenancy.skill.md)."""

from __future__ import annotations

from typing import Any, Type

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.core.security import current_tenant


def apply_tenant(instance: Any) -> Any:
    """Stamps a new ORM row with the immutable request tenant scope."""
    if hasattr(instance, "tenant_id") and not instance.tenant_id:
        instance.tenant_id = current_tenant()
    return instance


def scoped(stmt: Select, model: Type[Any]) -> Select:
    """Adds a tenant predicate to a SELECT; omits rows from other tenants."""
    if hasattr(model, "tenant_id"):
        return stmt.where(model.tenant_id == current_tenant())
    return stmt


async def find_owned(db: AsyncSession, model: Type[Any], object_id: str) -> Any:
    """Returns the row only when it belongs to the current tenant, else None."""
    instance = await db.get(model, object_id)
    if instance is None:
        return None
    tenant = getattr(instance, "tenant_id", None)
    if tenant is not None and tenant != current_tenant():
        return None
    return instance


async def get_owned(
    db: AsyncSession,
    model: Type[Any],
    object_id: str,
    *,
    detail: str | None = None,
) -> Any:
    """Fetches a row only when it belongs to the current tenant.

    Mismatches return 404 so the endpoint never confirms another tenant's asset.
    """
    instance = await db.get(model, object_id)
    tenant = getattr(instance, "tenant_id", None) if instance is not None else None
    if instance is None or (tenant is not None and tenant != current_tenant()):
        raise HTTPException(status_code=404, detail=detail or f"{model.__name__} not found")
    return instance
