from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
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

from sqlalchemy import text


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


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate_sqlite_columns(conn)
