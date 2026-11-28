# CI/CD Skill (`cicd.skill.md`)

*Apply whenever modifying `.github/workflows/`, `scripts/`, `backend/pyproject.toml`, or `frontend/package.json`.*

## Non-negotiable rules

1. **One source of truth for verification.** The same commands run locally and in CI: `ruff check`, `mypy`, `pytest`, `npm run typecheck`, `npm run build`, and schema sync.
2. **Never call live paid APIs in CI.** The autouse `conftest.py` fixture strips Gemini/Anthropic/Modal credentials; CI jobs must not inject real keys for unit tests.
3. **Fail on schema drift.** A committed script compares Pydantic ADT fields in `backend/app/schemas/adt.py` with `frontend/src/types/cad.ts` and `docs/03_API_ADT_SPEC.md`; drift fails the job.
4. **Pin toolchains.** Backend uses Python 3.12 + `uv`, frontend uses Node 20 + `npm ci`. Lockfiles are committed and CI uses frozen installs.
5. **Keep jobs small and observable.** Separate backend and frontend jobs; cache `uv` and npm caches; print concise step summaries instead of dumping full logs.
6. **No deploy on untrusted events.** Pull requests from forks run tests only. Deployment jobs require a protected environment and explicit secrets; they are not part of the PR gate.
7. **Portable scripts.** Verification scripts are Node `.mjs` files so they work on Windows, Linux, and macOS without `grep`/`sed` assumptions.

## Verification checklist

- `node scripts/verify.mjs cicd` passes locally.
- Workflow YAML contains `ruff check`, `mypy`, `pytest`, `typecheck`, and `schema-sync` steps.
- `npm run typecheck` exists in `frontend/package.json`.
- `uv run` works from a clean checkout (hatchling package selection configured).
