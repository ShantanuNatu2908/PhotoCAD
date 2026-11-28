"""Semantic RAG layer tests (PCAD-LG-004 / rag-pgvector.skill.md)."""

from __future__ import annotations

import asyncio

import pytest

from app.agents.rag import (
    GOLDEN_BUILD123D_DOCS,
    Build123dRAGService,
    DeterministicEmbedder,
    PgVectorRepository,
    load_schema_sql,
    semantic_rank,
)


def test_deterministic_embedder_is_stable_and_normalized():
    embedder = DeterministicEmbedder(dimension=256)
    first = asyncio.run(embedder.embed("round the outer edges with a fillet"))
    second = asyncio.run(embedder.embed("round the outer edges with a fillet"))
    assert first.values == second.values
    assert first.dimension == 256
    assert abs(sum(v * v for v in first.values) - 1.0) < 1e-6


def test_semantic_rank_finds_paraphrased_operation():
    embedder = DeterministicEmbedder(dimension=512)
    query = asyncio.run(embedder.embed("round sharp corners smoothly on the outside perimeter"))
    ranked = semantic_rank(GOLDEN_BUILD123D_DOCS, query.values, embedder, limit=3, min_score=0.0)
    assert ranked
    assert ranked[0][0].api_symbol == "fillet"


@pytest.mark.asyncio
async def test_aretrieve_falls_back_without_pgvector(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///storage/photocad.db")
    monkeypatch.delenv("PHOTOCAD_RAG_BACKEND", raising=False)
    result = await Build123dRAGService.aretrieve(["fillet", "hole"])
    assert result.backend == "keyword_fallback"
    assert {"fillet", "hole"}.issubset({chunk["symbol"] for chunk in result.chunks})
    assert result.chunks[0]["symbol"] == "BuildPart"


@pytest.mark.asyncio
async def test_aretrieve_uses_injected_repository(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pw@localhost:5432/photocad")

    class FakeAcquire:
        def __init__(self, conn):
            self.conn = conn

        async def __aenter__(self):
            return self.conn

        async def __aexit__(self, *_args):
            return False

    class FakeConn:
        def __init__(self):
            self.executed = []
            self.fetched_sql = ""

        async def execute(self, sql, *params):
            self.executed.append((sql, params))

        async def fetch(self, sql, *params):
            self.fetched_sql = sql
            return [{"api_symbol": "fillet", "content": "rounded edges", "code_example": "fillet(edges, 1.5)", "similarity": 0.71}]

    class FakePool:
        def __init__(self, conn):
            self.conn = conn

        def acquire(self):
            return FakeAcquire(self.conn)

        async def close(self):
            return None

    conn = FakeConn()
    embedder = DeterministicEmbedder(dimension=128)
    repo = PgVectorRepository("postgresql://user:pw@localhost:5432/photocad")
    repo.pool = FakePool(conn)

    result = await Build123dRAGService.aretrieve(
        ["fillet"], query_text="smooth outer corners", repository=repo, embedder=embedder
    )
    assert result.backend == "pgvector_hnsw"
    assert result.chunks[0]["symbol"] == "fillet"
    assert "vector_cosine_ops" in conn.executed[0][0]
    assert "<=>" in conn.fetched_sql


def test_migration_sql_is_idempotent_and_hnsw():
    sql = load_schema_sql(768)
    for marker in (
        "CREATE EXTENSION IF NOT EXISTS vector",
        "CREATE TABLE IF NOT EXISTS build123d_docs",
        "CREATE INDEX IF NOT EXISTS build123d_docs_embedding_hnsw",
        "vector_cosine_ops",
        "vector(768)",
    ):
        assert marker in sql
