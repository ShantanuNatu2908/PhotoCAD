# Gates: PhotoCAD v1.1 foundation increment

OWNS: backend/**, frontend/**, gpu_workers/**, docs/**, skills/**, scripts/**, .github/**, .env.example, AGENTS.md, README.md

Scope: Repair the baseline, codify new engineering skills, and implement the code-owned parts of the P0/P1/P2 roadmap (persistent checkpointer, pgvector RAG, automated scale detection, auth/tenancy, NURBS surfacing, CI/CD) with runnable evidence. External account provisioning is recorded as handoff, not claimed as done.

- [x] G1: Baseline is green — all pre-existing backend tests pass and `uv run` can resolve the project.
  CHECK: node scripts/verify.mjs baseline
  EXPECT: BASELINE_OK
  EVIDENCE: `node scripts/verify.mjs baseline` -> `BASELINE_OK` (2026-11-28); backend pytest now `66 passed` in the gate run and two consecutive stability reruns. Baseline repairs included `backend/README.md`, hatchling package selection, and one invalid `FeatureStep` in `test_llm_router_v1.py`. Ruff/mypy are green (`All checks passed!`, `Success: no issues found in 44 source files`).

- [x] G2: New engineering skills exist and carry enforceable rules for each new domain.
  CHECK: node scripts/verify.mjs skills
  EXPECT: SKILLS_OK
  EVIDENCE: `node scripts/verify.mjs skills` -> `SKILLS_OK` (2026-11-28); 6 new `skills/*.skill.md` files with enforceable markers.

- [x] G3: LangGraph checkpoints survive a process-equivalent restart for both fresh and `/refine` threads.
  CHECK: node scripts/verify.mjs checkpointer
  EXPECT: CHECKPOINTER_OK
  EVIDENCE: `node scripts/verify.mjs checkpointer` -> `CHECKPOINTER_OK` (2026-11-28); 5 tests cover file round-trip, durable default, Postgres->File degradation, explicit memory, and restart survival. `FileSaver.flush()` was hardened with a process-wide lock, unique temp files, and bounded retries; the Windows `PermissionError` race no longer reproduces across three full-suite runs.

- [x] G4: build123d RAG retrieves semantically relevant chunks through a vector repository and degrades safely without a database.
  CHECK: node scripts/verify.mjs rag
  EXPECT: RAG_OK
  EVIDENCE: `node scripts/verify.mjs rag` -> `RAG_OK` (2026-11-28); `7 passed` across `test_rag.py` and `test_rag_pgvector_v1.py` covering deterministic embeddings, paraphrase ranking, keyword fallback, injected pgvector repository, and migration idempotency.

- [x] G5: Frontend can auto-detect ID-1 card and ArUco fiducials and still supports manual calibration.
  CHECK: node scripts/verify.mjs calibration
  EXPECT: CALIBRATION_OK
  EVIDENCE: `node scripts/verify.mjs calibration` -> `CALIBRATION_OK` (2026-11-28); 5 vitest cases (axis-aligned ID-1, rotated ID-1, square rejection, exact ArUco decode, unknown marker rejection) plus `npm run typecheck` and production build pass.

- [x] G6: API enforces optional JWT auth and per-user ownership when configured, with an explicit local-developer bypass.
  CHECK: node scripts/verify.mjs auth
  EXPECT: AUTH_OK
  EVIDENCE: `node scripts/verify.mjs auth` -> `AUTH_OK` (2026-11-28); 5 tests cover dev bypass, 401 without token, project/scan tenant isolation, and 1008 WS rejection. Full baseline remains green.

- [x] G7: Visual-hull reconstruction can emit continuous C2 B-spline surface patches while the authoritative watertight AP214 shell remains unchanged.
  CHECK: node scripts/verify.mjs nurbs
  EXPECT: NURBS_OK
  EVIDENCE: `node scripts/verify.mjs nurbs` -> `NURBS_OK` (2026-11-28); 5 tests cover clamped C2 knots, six bounded-deviation face groups, deterministic AP214 patch entities, faceted fallback, and opt-in hull metadata. The Cox–de Boor `t=1` endpoint bug was fixed, and `PHOTOCAD_SMOOTH_SURFACES=true` now enables the opt-in patches from both the Zero-Heat and Modal fusion paths without changing the authoritative watertight STEP.

- [x] G8: CI workflow, schema sync verification, and local typecheck/build commands are wired and pass.
  CHECK: node scripts/verify.mjs cicd
  EXPECT: CICD_OK
  EVIDENCE: `node scripts/verify.mjs cicd` -> `CICD_OK` (2026-11-28); `.github/workflows/ci.yml` runs backend lint/types/tests/schema-sync, frontend typecheck/build/vitest, and the gate ledger. `check_schema_sync.py` reported `SCHEMA_SYNC_OK: 7 Pydantic ADTs, 5 shared TS interfaces`; a deliberately removed `mm_per_unit` field produced `SCHEMA_SYNC_FAIL`, confirming the check can fail.

- [x] G9: Deployment docs record actionable provisioning steps and explicit external handoffs.
  CHECK: node scripts/verify.mjs docs
  EXPECT: DOCS_OK
  EVIDENCE: `node scripts/verify.mjs docs` -> `DOCS_OK` (2026-11-28); `DEPLOYMENT.md` documents Modal, Supabase/pgvector migrations, checkpointer tiers, Redis, R2 lifecycle, JWT, the `PHOTOCAD_SMOOTH_SURFACES` opt-in, and a handoff table; `PROJECT_PLAN.md` records v1.1 code-owned scope and deferred external provisioning.

Manual handoff (not claimable in this environment): provision Modal billing account and deploy GPU app; provision Supabase Postgres + pgvector and Redis Cloud instances; configure the Cloudflare R2 `uploads/*` 24-hour lifecycle rule in the dashboard.
