-- PhotoCAD PCAD-LG-004 / rag-pgvector.skill.md
-- Supabase PostgreSQL 16 + pgvector HNSW index for build123d retrieval.
-- __EMBEDDING_DIM__ is replaced at runtime by the configured embedding dimension.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS build123d_docs (
    api_symbol TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    content TEXT NOT NULL,
    code_example TEXT NOT NULL,
    embedding vector(__EMBEDDING_DIM__) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS build123d_docs_embedding_hnsw
    ON build123d_docs USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

COMMENT ON TABLE build123d_docs IS
    'Seeded build123d documentation corpus with semantic embeddings (PhotoCAD Node 3 RAG).';
