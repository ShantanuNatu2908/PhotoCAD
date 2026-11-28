# Vector RAG Skill (`rag-pgvector.skill.md`)

*Apply whenever modifying `backend/app/agents/rag.py`, pgvector migrations, or LangGraph Node 3 retrieval.*

## Non-negotiable rules

1. **Golden docs remain the immutable seed.** `GOLDEN_BUILD123D_DOCS` is the canonical offline corpus and the seed for the `build123d_docs` table. Never delete the in-memory fallback.
2. **Embedding provider is pluggable and deterministic in dev.** Production uses Gemini `gemini-embedding-001` or `text-embedding-3-small`. Without a provider key, use a stable hashed bag-of-words embedding with fixed dimensionality; never random vectors.
3. **Cosine distance + HNSW.** The live table uses `vector(1536)` (configurable), `vector_cosine_ops`, and an HNSW index. Query with `1 - (embedding <=> :q)` as similarity and filter by a minimum score.
4. **Fail open, never fail closed.** If the database or embedding provider is unavailable, Node 3 must still receive keyword-matched golden chunks and continue synthesis. Log the degraded mode in the retrieval result, not as an exception.
5. **No raw LLM output in SQL.** All queries are parameterized through SQLAlchemy `text()` bind parameters. Document IDs and symbols are validated identifiers.
6. **ADT shape is contractual.** Public retrieval returns `{"symbol", "guidance", "canonical_pattern"}` exactly; semantic metadata is attached separately so existing `test_rag.py` and the synthesizer keep working.
7. **Idempotent seeding.** Upsert by `api_symbol` so repeated startup never duplicates context. Migration SQL uses `CREATE EXTENSION IF NOT EXISTS vector` and `CREATE INDEX IF NOT EXISTS`.

## Verification checklist

- Keyword retrieval tests still pass (`tests/test_rag.py`).
- A paraphrased query (no shared tokens) ranks the correct chunk first via semantic search.
- With no `DATABASE_URL` or provider key, retrieval returns golden chunks and reports `backend: "keyword_fallback"`.
- Migration SQL contains extension, table, HNSW index, and idempotent guards.
