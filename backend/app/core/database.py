from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from app.core.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

Base = declarative_base()

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

async def _migrate_sqlite_columns(conn) -> None:
    """Idempotently adds Phase 3 columns to existing local SQLite scan_sessions tables."""
    if "sqlite" not in settings.DATABASE_URL:
        return
    res = await conn.execute(text("PRAGMA table_info(scan_sessions)"))
    existing = {row[1] for row in res.fetchall()}
    migrations = {
        "status": "ALTER TABLE scan_sessions ADD COLUMN status VARCHAR(32) DEFAULT 'capturing'",
        "calibration_json": "ALTER TABLE scan_sessions ADD COLUMN calibration_json JSON",
        "geometry_report_json": "ALTER TABLE scan_sessions ADD COLUMN geometry_report_json JSON",
        "ply_file": "ALTER TABLE scan_sessions ADD COLUMN ply_file VARCHAR(256)",
    }
    for col_name, ddl in migrations.items():
        if col_name not in existing:
            await conn.execute(text(ddl))


async def _migrate_tenant_columns(conn) -> None:
    """Idempotently adds tenant_id to legacy rows on SQLite and PostgreSQL."""
    from sqlalchemy import inspect

    for table in ("projects", "scan_sessions", "cad_generations"):
        columns = await conn.run_sync(
            lambda sync_conn, t=table: [column["name"] for column in inspect(sync_conn).get_columns(t)]
        )
        if "tenant_id" in columns:
            continue
        await conn.execute(text(
            f"ALTER TABLE {table} ADD COLUMN tenant_id VARCHAR(64) DEFAULT 'public' NOT NULL"
        ))
        await conn.execute(text(f"UPDATE {table} SET tenant_id = 'public' WHERE tenant_id IS NULL"))
        try:
            await conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant_id ON {table} (tenant_id)"
            ))
        except Exception:
            # Some engines reject IF NOT EXISTS; the column migration still succeeded.
            pass


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate_sqlite_columns(conn)
        await _migrate_tenant_columns(conn)
