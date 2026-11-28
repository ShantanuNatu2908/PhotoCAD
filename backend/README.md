# PhotoCAD Backend

FastAPI control plane for the PhotoCAD Scan-to-CAD platform. This package contains
the async SQLAlchemy models, Pydantic ADTs, 5-node LangGraph dual-loop orchestrator,
build123d RAG/sandbox pipeline, and cloud-tier diagnostics.

## Development

```bash
cd backend
uv sync --extra dev
uv run uvicorn app.main:app --reload --port 8000
```

## Verification

```bash
uv run ruff check .
uv run mypy app
uv run pytest tests/ -q
```

The package intentionally contains no PyTorch/CUDA imports: GPU work is dispatched
to the Modal workers in `gpu_workers/`. See `../docs/ARCHITECTURE.md` for boundaries
and `../AGENTS.md` for non-negotiable engineering rules.
