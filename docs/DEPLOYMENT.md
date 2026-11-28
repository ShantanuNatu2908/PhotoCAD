# PhotoCAD — Production Deployment & Interoperability Launch Guide

**Document ID:** `PCAD-OPS-005`  
**Phase:** Phase 5 (Production Launch & Verification Checklist)

---

## 1. Zero-Heat Cloud Production Topology

| Layer | Recommended Managed Host | Runtime & Scaling |
| :--- | :--- | :--- |
| **Web Frontend** | **Vercel** or **Cloudflare Pages** (`frontend/`) | Static Vite SPA build (`npm run build`), global CDN, TLS 1.3 |
| **Control Plane API** | **Railway / Fly.io / Render** (`backend/`) | Python `3.12` + `uvicorn app.main:app --host 0.0.0.0 --port 8000` |
| **Serverless GPU + OCP Sandbox** | **Modal** (`gpu_workers/modal_app.py`) | NVIDIA L4 (`scaledown_window=60`), cached `/root/.cache` volume, `block_network=True` CAD sandbox |
| **Warm Tier Database** | **Supabase** (`PostgreSQL 16 + pgvector`) | Session storage + HNSW embeddings index for `build123d` RAG |
| **Hot Tier Cache & State** | **Redis Cloud 8.0+** (or **Upstash**) | WebSocket Pub/Sub, ARQ job queues, LangGraph checkpoint persistence |
| **Cold Tier Object Storage** | **Cloudflare R2** | Pre-signed SigV4 uploads; 24-hour lifecycle expiration rule on `uploads/*` raw user PNGs |

---

## 2. Cloud Deployment Steps

### Step A: Deploy Modal GPU & OpenCascade Workers
```bash
modal token set --token-id <MODAL_TOKEN_ID> --token-secret <MODAL_TOKEN_SECRET>
modal deploy gpu_workers/modal_app.py
```
Verify remote telemetry via FastAPI health diagnostics:
```bash
curl http://localhost:8000/api/health/cloud
```

### Step B: Configure Environment Variables (`.env` / Host Secrets)
Reference [`.env.example`](../.env.example):
- `ENVIRONMENT="production"`
- `DATABASE_URL` (Supabase async Postgres connection string `postgresql+asyncpg://...`)
- `REDIS_URL` (Redis Cloud / Upstash URL)
- `CLOUDFLARE_R2_ACCOUNT_ID`, `CLOUDFLARE_R2_ACCESS_KEY_ID`, `CLOUDFLARE_R2_SECRET_ACCESS_KEY`, `CLOUDFLARE_R2_BUCKET_NAME`
- `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`
- `GEMINI_API_KEY` and `ANTHROPIC_API_KEY`
- Optional: `LANGCHAIN_TRACING_V2="true"` + `LANGSMITH_API_KEY` for end-to-end LangGraph trace observability.

### Step C: Configure R2 Privacy Lifecycle Rule (`NFR-08`)
In the Cloudflare R2 Bucket Dashboard (`photocad-assets`), add an Object Lifecycle Rule:
- **Prefix:** `uploads/`
- **Action:** Delete objects after **1 day (24 hours)**.
Raw camera frames containing user hands are automatically purged while `.STEP`, `.DXF`, `.STL`, and `.PLY` exports persist.

### Step D: Provision Persistent State & Semantic RAG (v1.1)

1. In Supabase SQL Editor, run the idempotent migrations in order:
   ```sql
   -- backend/migrations/001_pgvector_rag.sql
   -- backend/migrations/002_tenant_columns.sql
   ```
   Confirm `vector` is installed (`SELECT extname FROM pg_extension WHERE extname = 'vector'`) and that `photocad_rag_chunks` has an HNSW index.
2. Set `DATABASE_URL` to the async Supabase connection string. `resolve_checkpointer()` then selects `AsyncPostgresSaver`; if Postgres is unavailable it degrades to `AsyncRedisSaver`, then a durable `FileSaver`, and only then `MemorySaver`. Set `REDIS_URL` to enable the Redis tier.
3. The RAG service keeps immutable golden chunks as a safe fallback when no vector repository is injected. With `DATABASE_URL` configured, semantic retrieval uses deterministic embeddings plus domain synonyms through `PgVectorRepository`; keyword retrieval remains the last resort.
4. For authenticated deployments set `JWT_SECRET` (or `SUPABASE_JWT_SECRET`, HS256) and optionally `JWT_ISSUER`. With neither secret set, the API remains in explicit local-developer bypass mode with tenant `public`.
5. Set `PHOTOCAD_SMOOTH_SURFACES=true` only after consumers accept an `OPEN_SHELL` B-spline representation alongside the authoritative watertight STEP. The flag adds C2 patch metadata to `visual_hull.json` for both Modal and Zero-Heat fusion paths.
6. Verify the deployment contract locally before shipping:
   ```bash
   node scripts/verify.mjs baseline
   node scripts/verify.mjs cicd
   node scripts/verify.mjs docs
   ```

---

## 3. AutoCAD, Fusion 360 & SolidWorks Verification Protocol (`NFR-06`)

Before releasing a build, verify all exported packages pass both automated checks and manual desktop CAD import tests:

1. **Automated Interop Check (API & Pytest):**
   ```bash
   cd backend
   .venv\Scripts\python.exe -m pytest tests/test_interop_golden_v1.py -v
   ```
   Confirms across Golden Dataset parts (`mounting_plate_bore`, `precision_l_blank`, `flanged_collar_block`, `metric_shim_spacer`):
   - **ISO 10303-21 `.STEP`:** `AUTOMOTIVE_DESIGN` AP214 header, `SI_UNIT(.MILLI.,.METRE.)`, `CLOSED_SHELL`, `MANIFOLD_SOLID_BREP`, zero dangling `#id` references, exact $\pm 0.05\text{ mm}$ bounding box match.
   - **AutoCAD `.DXF`:** `$ACADVER`, `$INSUNITS = 4` (Millimeters), valid `GEOMETRY` and `ANNOTATIONS` layers, 3 orthographic projection views + circular bore geometry.
   - **Watertight `.STL`:** Every undirected edge shared by 2 opposing triangles, positive volume ($\text{mm}^3$).

2. **Desktop CAD Sanity Import Steps:**
   - **AutoCAD (`IMPORT` command):** Open `.STEP` $\to$ verify `PROPERTIES` reports Solid3D with selectable planar and cylindrical faces; open `.DXF` $\to$ run `UNITS` to confirm `Millimeters` (`4`) and measure bore/length with `DIST`.
   - **Autodesk Fusion 360:** *File $\to$ Open* `.STEP` $\to$ inspect *Measure* tool in `mm` $\to$ verify Push/Pull (`Press Pull`) modifies extruded thickness and hole faces cleanly.
   - **SOLIDWORKS:** *File $\to$ Open* `.STEP` $\to$ run *Evaluate $\to$ Check Entity* (`Solid Body`, 0 invalid faces/edges) $\to$ verify *Mass Properties* matches reported `volume_mm3`.

---

## 4. v1.1 External Handoff Checklist (not claimable from source control)

These steps require account access and dashboard actions; the repository only prepares the code and configuration contracts.

| Owner | Action | Done when |
| :--- | :--- | :--- |
| Modal account admin | Add billing/payment method and run `modal deploy gpu_workers/modal_app.py` | `/api/health/cloud` reports the Modal GPU worker ready. |
| Supabase admin | Create Postgres 16 project, enable `vector`, apply `001_pgvector_rag.sql` and `002_tenant_columns.sql` | HNSW index exists and tenant RLS policies are present. |
| Redis admin | Provision Redis Cloud / Upstash and set `REDIS_URL` | `resolve_checkpointer()` logs the `AsyncRedisSaver` tier (when Postgres is intentionally disabled). |
| Cloudflare R2 admin | Create `photocad-assets` bucket and the `uploads/*` 24-hour `lifecycle` expiration rule | Raw keyframes expire after 1 day while export prefixes persist. |
| CI admin | Protect `main`, add optional deploy secrets, and enable `.github/workflows/ci.yml` | Pull requests run backend, frontend, and gate-ledger jobs without live paid API keys. |

The NURBS path emits opt-in C2 B-spline patches as an open-shell representation; the authoritative watertight STEP body remains the faceted AP214 `CLOSED_SHELL` exporter until a trimmed-patch solid passes interop verification.
