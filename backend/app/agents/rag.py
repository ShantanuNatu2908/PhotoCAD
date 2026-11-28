"""
PhotoCAD - build123d API Documentation RAG Retriever
Document ID: PCAD-LG-004 (Node 3 Synthesizer RAG Layer)

Provides curated, verified build123d context chunks to eliminate LLM syntax hallucinations.
Production retrieval uses a Supabase pgvector HNSW table with semantic embeddings;
zero-heat development uses deterministic keyword matching over the immutable golden corpus.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import httpx
from pydantic import BaseModel, Field

DEFAULT_EMBEDDING_DIM = 1536
DEFAULT_MIN_SIMILARITY = 0.18
MIGRATION_PATH = Path(__file__).resolve().parents[2] / "migrations" / "001_pgvector_rag.sql"


class Build123dDocChunk(BaseModel):
    api_symbol: str
    category: str  # "builder_3d", "sketch_2d", "operations", "export"
    content: str
    code_example: str


# Curated Golden Dataset of build123d API Conventions (v0.9.x / v1.0)
GOLDEN_BUILD123D_DOCS: List[Build123dDocChunk] = [
    Build123dDocChunk(
        api_symbol="BuildPart",
        category="builder_3d",
        content=(
            "BuildPart is the primary 3D context manager in build123d. "
            "All additive or subtractive 3D solid operations must execute inside 'with BuildPart() as part:'. "
            "Always assign RESULT_PART = part.part at the conclusion of the script."
        ),
        code_example=(
            "from build123d import BuildPart, BuildSketch, Rectangle, extrude\n"
            "with BuildPart() as part:\n"
            "    with BuildSketch():\n"
            "        Rectangle(60.0, 40.0)\n"
            "    extrude(amount=25.0)\n"
            "RESULT_PART = part.part"
        )
    ),
    Build123dDocChunk(
        api_symbol="BuildSketch",
        category="sketch_2d",
        content=(
            "BuildSketch creates 2D planar profiles. It can be constructed on standard planes "
            "(Plane.XY, Plane.XZ, Plane.YZ) or directly onto faces of an existing solid using "
            "'with BuildSketch(part.faces().sort_by(Axis.Z)[-1]):'."
        ),
        code_example=(
            "with BuildSketch(part.faces().sort_by(Axis.Z)[-1]):\n"
            "    Circle(radius=8.0)\n"
            "extrude(amount=-10.0, mode=Mode.SUBTRACT)"
        )
    ),
    Build123dDocChunk(
        api_symbol="fillet",
        category="operations",
        content=(
            "fillet rounds selected edges. Edge selection must filter or group edges safely. "
            "CRITICAL: Always apply fillets LAST in the feature tree. "
            "Ensure radius < min_adjacent_wall_thickness / 2.5 to avoid OpenCascade BRep_API crashes."
        ),
        code_example=(
            "# Fillet all vertical Z-aligned edges safely\n"
            "vertical_edges = part.edges().filter_by(Axis.Z)\n"
            "fillet(vertical_edges, radius=3.0)"
        )
    ),
    Build123dDocChunk(
        api_symbol="hole",
        category="operations",
        content=(
            "Locations with Circle and subtractive extrude creates precise mounting hole patterns. "
            "Prefer Locations tuples for symmetrical 4-hole or circular patterns."
        ),
        code_example=(
            "with BuildSketch(part.faces().sort_by(Axis.Z)[-1]):\n"
            "    with Locations((20, 15), (-20, 15), (20, -15), (-20, -15)):\n"
            "        Circle(radius=3.0)\n"
            "extrude(amount=-THICKNESS_MM, mode=Mode.SUBTRACT)"
        )
    ),
    Build123dDocChunk(
        api_symbol="chamfer",
        category="operations",
        content=(
            "chamfer applies beveled edges to planar boundaries. "
            "Use length parameter in millimeters (1:1 mm)."
        ),
        code_example=(
            "top_edges = part.edges().filter_by(Axis.Z, reverse=True).group_by(Axis.Z)[-1]\n"
            "chamfer(top_edges, length=1.5)"
        )
    )
]


class EmbeddingVector(BaseModel):
    """Provider-neutral embedding result with deterministic provenance."""

    values: List[float]
    backend: str
    model: str

    @property
    def dimension(self) -> int:
        return len(self.values)


class RetrievalResult(BaseModel):
    """Node 3 retrieval payload. `chunks` keeps the ADT shape used by the synthesizer."""

    chunks: List[Dict[str, str]] = Field(default_factory=list)
    backend: str = "keyword_fallback"
    model: Optional[str] = None
    reason: Optional[str] = None


def _embedding_dim() -> int:
    try:
        return max(8, int(os.getenv("PHOTOCAD_EMBEDDING_DIM", str(DEFAULT_EMBEDDING_DIM))))
    except ValueError:
        return DEFAULT_EMBEDDING_DIM


# Canonical domain synonyms let the zero-heat embedder resolve paraphrases such as
# "smooth the corners" -> fillet without any network call or model download.
DOMAIN_SYNONYMS: Dict[str, str] = {
    "round": "fillet", "rounded": "fillet", "rounds": "fillet", "rounding": "fillet",
    "smooth": "fillet", "smoothly": "fillet", "corner": "fillet", "corners": "fillet",
    "bevel": "chamfer", "beveled": "chamfer", "bevelled": "chamfer",
    "bore": "hole", "bores": "hole", "drill": "hole", "drilled": "hole",
    "boring": "hole", "perforation": "hole",
    "subtract": "cut_extrude", "subtractive": "cut_extrude", "carve": "cut_extrude",
    "sketch": "BuildSketch", "profile": "BuildSketch", "profiles": "BuildSketch",
    "solid": "BuildPart", "body": "BuildPart", "prism": "BuildPart",
}


def deterministic_embed_values(text: str, dimension: int) -> List[float]:
    """Signed sha256 feature hashing over lexically expanded tokens (sync, pure)."""
    vector = [0.0] * dimension
    tokens = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", text.lower())
    expanded: List[str] = []
    for token in tokens:
        expanded.append(token)
        canonical = DOMAIN_SYNONYMS.get(token)
        if canonical:
            expanded.append(canonical.lower())
    for token in expanded:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimension
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(v * v for v in vector))
    if norm > 1e-12:
        vector = [v / norm for v in vector]
    return vector


class DeterministicEmbedder:
    """
    Zero-heat embedding provider: signed feature hashing with canonical domain
    synonym expansion. Deterministic across processes and L2-normalised, so
    cosine similarity is meaningful without any network call or model download.
    """

    def __init__(self, dimension: Optional[int] = None):
        self.dimension = dimension or _embedding_dim()
        self.model = f"deterministic-lexical-hash-{self.dimension}"

    async def embed(self, text: str) -> EmbeddingVector:
        return EmbeddingVector(
            values=deterministic_embed_values(text, self.dimension),
            backend="deterministic",
            model=self.model,
        )


class HttpEmbeddingProvider:
    """
    OpenAI-compatible embeddings endpoint. Works with OpenAI (`text-embedding-3-small`)
    and Gemini's OpenAI compatibility layer (`text-embedding-004`) via env configuration.
    """

    def __init__(self) -> None:
        self.base_url = os.getenv(
            "EMBEDDING_BASE_URL", "https://api.openai.com/v1"
        ).rstrip("/")
        self.api_key = os.getenv("EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
        self.model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

    @property
    def configured(self) -> bool:
        return bool(self.api_key) and "your-" not in self.api_key

    async def embed(self, text: str) -> EmbeddingVector:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{self.base_url}/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "input": text},
            )
            response.raise_for_status()
            payload = response.json()
        values = [float(v) for v in payload["data"][0]["embedding"]]
        return EmbeddingVector(values=values, backend="http", model=self.model)


async def get_embedding_provider() -> Any:
    """Returns the configured live provider, or the deterministic zero-heat provider."""
    provider = HttpEmbeddingProvider()
    if provider.configured:
        return provider
    return DeterministicEmbedder()


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b:
        return 0.0
    length = min(len(a), len(b))
    dot = sum(a[i] * b[i] for i in range(length))
    na = math.sqrt(sum(v * v for v in a[:length]))
    nb = math.sqrt(sum(v * v for v in b[:length]))
    return float(dot / (na * nb)) if na > 1e-12 and nb > 1e-12 else 0.0


def semantic_rank(
    chunks: Iterable[Build123dDocChunk],
    query_vector: Sequence[float],
    embedder: Any,
    limit: int = 4,
    min_score: float = DEFAULT_MIN_SIMILARITY,
) -> List[Tuple[Build123dDocChunk, float]]:
    """
    Pure semantic ranking helper. Used by the pgvector repository's local mirror and
    by tests so ranking behaviour is verifiable without a live database.
    """
    scored: List[Tuple[Build123dDocChunk, float]] = []
    for chunk in chunks:
        text = f"{chunk.api_symbol} {chunk.content} {chunk.code_example}"
        if isinstance(embedder, DeterministicEmbedder):
            embedded_values = deterministic_embed_values(text, embedder.dimension)
        else:  # live providers only need a network call when explicitly configured
            embedded_values = asyncio.run(embedder.embed(text)).values
        score = _cosine(query_vector, embedded_values)
        if score >= min_score:
            scored.append((chunk, score))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:limit]


def load_schema_sql(dimension: Optional[int] = None) -> str:
    """Reads the idempotent migration template with the configured vector dimension."""
    sql = MIGRATION_PATH.read_text(encoding="utf-8")
    return sql.replace("__EMBEDDING_DIM__", str(dimension or _embedding_dim()))


class PgVectorRepository:
    """Minimal asyncpg-backed repository for the `build123d_docs` HNSW table."""

    def __init__(self, dsn: str, dimension: Optional[int] = None):
        self.dsn = dsn
        self.dimension = dimension or _embedding_dim()
        self.pool: Any = None

    async def connect(self) -> "PgVectorRepository":
        import asyncpg
        from pgvector.asyncpg import register_vector

        self.pool = await asyncpg.create_pool(self.dsn, init=register_vector)
        return self

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    async def ensure_schema(self) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(load_schema_sql(self.dimension))

    async def seed(self, chunks: Sequence[Build123dDocChunk], embedder: Any) -> int:
        """Idempotently upserts golden chunks; returns the number written."""
        from pgvector import Vector

        written = 0
        async with self.pool.acquire() as conn:
            for chunk in chunks:
                embedded = await embedder.embed(
                    f"{chunk.api_symbol} {chunk.content} {chunk.code_example}"
                )
                await conn.execute(
                    """
                    INSERT INTO build123d_docs
                        (api_symbol, category, content, code_example, embedding)
                    VALUES ($1, $2, $3, $4, $5::vector)
                    ON CONFLICT (api_symbol) DO UPDATE SET
                        category = EXCLUDED.category,
                        content = EXCLUDED.content,
                        code_example = EXCLUDED.code_example,
                        embedding = EXCLUDED.embedding,
                        updated_at = now()
                    """,
                    chunk.api_symbol,
                    chunk.category,
                    chunk.content,
                    chunk.code_example,
                    Vector(embedded.values),
                )
                written += 1
        return written

    async def search(
        self,
        query_vector: Sequence[float],
        limit: int = 4,
        min_score: float = DEFAULT_MIN_SIMILARITY,
    ) -> List[Dict[str, Any]]:
        from pgvector import Vector

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT api_symbol, content, code_example,
                       1 - (embedding <=> $1::vector) AS similarity
                FROM build123d_docs
                WHERE 1 - (embedding <=> $1::vector) >= $2
                ORDER BY embedding <=> $1::vector
                LIMIT $3
                """,
                Vector(list(query_vector)),
                float(min_score),
                int(limit),
            )
        return [
            {
                "symbol": row["api_symbol"],
                "guidance": row["content"],
                "canonical_pattern": row["code_example"],
                "similarity": float(row["similarity"]),
            }
            for row in rows
        ]


class Build123dRAGService:
    """Retrieves relevant build123d code snippets for LangGraph Node 3."""

    _repository: Optional[PgVectorRepository] = None
    _seeded: bool = False

    @staticmethod
    def _keyword_chunks(operations: List[str]) -> List[Dict[str, str]]:
        matched_chunks: List[Dict[str, str]] = []
        op_set = {op.lower() for op in operations}
        for chunk in GOLDEN_BUILD123D_DOCS:
            symbol_lower = chunk.api_symbol.lower()
            if symbol_lower in op_set or any(op in symbol_lower for op in op_set):
                matched_chunks.append({
                    "symbol": chunk.api_symbol,
                    "guidance": chunk.content,
                    "canonical_pattern": chunk.code_example,
                })
        if not any(c["symbol"] == "BuildPart" for c in matched_chunks):
            matched_chunks.insert(0, {
                "symbol": GOLDEN_BUILD123D_DOCS[0].api_symbol,
                "guidance": GOLDEN_BUILD123D_DOCS[0].content,
                "canonical_pattern": GOLDEN_BUILD123D_DOCS[0].code_example,
            })
        return matched_chunks

    @staticmethod
    def retrieve_context_for_operations(operations: List[str]) -> List[Dict[str, str]]:
        """Synchronous keyword retrieval retained for offline callers and tests."""
        return Build123dRAGService._keyword_chunks(operations)

    @classmethod
    async def aretrieve(
        cls,
        operations: List[str],
        query_text: Optional[str] = None,
        repository: Optional[PgVectorRepository] = None,
        embedder: Any = None,
    ) -> RetrievalResult:
        """Semantic retrieval with safe keyword fallback; never raises on cloud failure."""
        keyword = cls._keyword_chunks(operations)
        db_url = os.getenv("DATABASE_URL", "")
        live_enabled = (
            db_url.startswith("postgresql")
            and "your-project" not in db_url
            and os.getenv("PHOTOCAD_RAG_BACKEND", "auto").lower() != "keyword"
        )
        if not live_enabled:
            return RetrievalResult(
                chunks=keyword,
                backend="keyword_fallback",
                reason="no pgvector DATABASE_URL configured",
            )

        try:
            embedder = embedder or await get_embedding_provider()
            query = " ".join([
                query_text or "",
                " ".join(operations),
            ]).strip() or "BuildPart build123d"
            query_vector = (await embedder.embed(query)).values

            repo = repository or cls._repository
            owns_repo = False
            if repo is None:
                dsn = db_url.replace("+asyncpg", "").replace("+psycopg", "")
                repo = PgVectorRepository(dsn)
                await repo.connect()
                cls._repository = repo
                owns_repo = True

            await repo.ensure_schema()
            if not cls._seeded:
                await repo.seed(GOLDEN_BUILD123D_DOCS, embedder)
                cls._seeded = True

            rows = await repo.search(query_vector, limit=4)
            if not rows:
                return RetrievalResult(
                    chunks=keyword,
                    backend="keyword_fallback",
                    model=getattr(embedder, "model", None),
                    reason="no row passed the similarity threshold",
                )
            return RetrievalResult(
                chunks=[{k: str(v) for k, v in row.items() if k in ("symbol", "guidance", "canonical_pattern")} for row in rows],
                backend="pgvector_hnsw",
                model=getattr(embedder, "model", None),
            )
        except Exception as exc:  # provider/DB failure must never block synthesis
            if owns_repo and cls._repository is not None:
                await cls._repository.close()
                cls._repository = None
            return RetrievalResult(
                chunks=keyword,
                backend="keyword_fallback",
                reason=f"{type(exc).__name__}: {exc}",
            )
