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
