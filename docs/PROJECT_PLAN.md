# PhotoCAD - Project Execution Plan & Specifications

## 1. Executive Summary
**PhotoCAD** is an industry-grade, multi-agent AI and Computer Vision platform that converts 4-to-6-sided physical object photographs into fully editable, millimeter-accurate, parametric 3D CAD models (STEP, DXF, STL, .py) for engineering, 3D printing, and CAD/CAM simulation pipelines.

Unlike naive polygon-mesh generators or uneditable photogrammetry point clouds, PhotoCAD leverages:
1. **Real-time Web Client Sharpness & Guided Capture (Laplacian $\sigma^2 \ge 120.0$)** with zero-compression PNG keyframes.
2. **Serverless Cloud GPU 3D Fusion (Modal NVIDIA L4)** via SAM 2.1 (hand/background stripping), Depth Anything 3 / V2, and Open3D 6-axis ICP registration.
3. **Local Zero-Heat 3D Volumetric Visual Hull Carving** fallback engine for instant offline prototyping without cloud GPU costs.
4. **5-Node Cyclic LangGraph Dual-Loop State Machine** synthesizing native Boundary Representation (B-Rep) solids via `build123d` (OpenCascade kernel), with AST sandbox security, compile self-healing (Inner Loop), and Chamfer Distance outer accuracy verification ($\le 1.0\text{ mm}$).
5. **AutoCAD, Fusion 360 & SolidWorks Ecosystem Interoperability** with ISO 10303-21 AP214 STEP solids, AutoCAD DXF ($INSUNITS=4\text{ mm}$), watertight STL, and interactive 3D WebGL inspection with 3D tape measure.

---

## 2. Implemented Tech Stack & Architecture

### A. Backend & Geometry Kernel
* **Framework:** FastAPI (Python 3.12 managed via `uv`), Async SQLAlchemy 2.0, Pydantic v2 schemas.
* **Dual Routing:** Unified `/api` and `/api/v1` route aliasing across projects, scans, generation, and exports.
* **CAD Modeling Kernel:** **`build123d`** (OpenCascade B-Rep / OCP kernel) replacing legacy CadQuery.
* **AST Security Gate:** Static `ast.parse()` validation blocking OS escapes, file writes, and forbidden builtins before execution.
* **Native Exporters:** Referentially-complete ISO 10303-21 STEP AP214 (`SI_UNIT(.MILLI.,.METRE.)`), AutoCAD DXF R12/2010 (`$INSUNITS=4`), watertight manifold ASCII/binary STL, and editable `.py` source.
* **Communication:** REST API + native **WebSockets** for real-time node transitions, unified code diffs, and Chamfer metrics streaming.

### B. Computer Vision & 3D Reconstruction
* **Serverless Cloud GPU (Modal NVIDIA L4):**
  * **SAM 2.1 (Small / BF16):** Keyframe foreground segmentation with YCrCb border-connected skin/hand stripping.
  * **Depth Anything 3 / V2 (BF16):** Dense depth estimation and camera-space 3D unprojection.
  * **Open3D Registration:** Outlier removal, SO(3) 6-axis alignment, FPFH + RANSAC, Point-to-Plane ICP, metric scaling, and primitive extraction (`Open3DGeometryReport`).
* **Zero-Heat Volumetric Visual Hull Engine (`app/cad/visual_hull.py`):**
  * Offline multi-view silhouette carving across 4-6 views.
  * Aspect ratio and circular Euler hole detection.
  * Taubin surface smoothing and watertight mesh extraction.

### C. Multi-Agent AI System (5-Node Cyclic LangGraph)
* **Provider Router & Failover (`app/agents/llm_router.py`):** Ordered fallback across Gemini 3.5 Flash, Gemini 3.1 Flash-Lite, Gemini 2.5 Flash, and Claude Sonnet 4.5, with automatic circuit-breaker cooldowns for 404, 429, or exhausted credit errors.
* **Node 1 - Geometry Analyst:** VLM multimodal reconciliation of 6 views with Open3D metric report and visual hull geometry.
* **Node 2 - Parametric Architect:** Generates sequential `CSGFeatureTree` ADT with topological constraints (fillets/chamfers ordered last).
* **Node 3 - CAD Code Synthesizer + RAG:** Retrieves curated `build123d` API patterns (`Build123dRAGService`) and generates unified diffs.
* **Node 4 - Isolated Sandbox Executor (Inner Loop):** Executes in network-isolated environment with up to 3 automatic compile/syntax self-healing retries.
* **Node 5 - Geometric Chamfer Validator (Outer Loop):** Evaluates watertight topology and 20,000-point bidirectional Chamfer Distance against the fused scan ($\le 1.0\text{ mm}$ tolerance) with Best-Effort retention guard.

### D. Frontend & Interactive 3D Studio
* **Core:** React 19, TypeScript, Vite, Tailwind CSS.
* **4-Page Workflow:**
  * **Page 1 (Capture Studio):** Camera feed with continuous mounting, passive permission checks, 60 FPS Laplacian blur rejection ($\ge 120.0$), manual file upload fallback, and 3-second timer.
  * **Page 2 (Calibrate & Generate):** 2-point caliper scale calibrator ($px \to mm$), reconstruction mode toggle (`auto_hull` vs `prismatic`), edge finish selector, and live LangGraph AgentTerminal.
  * **Page 3 (3D CAD Output):** Three.js / React Three Fiber viewport with Solid/Wireframe/X-Ray/Turntable modes, Point-to-Point 3D tape measure (`mm`/`inch`), Export Center, and always-visible conversational `/refine` studio.
  * **Page 4 (Saved Projects & Scans):** Archive of previous scans with thumbnails, confirmed views, and instant 3D reload.
* **Cloud Diagnostics HUD:** Real-time 4-tier status monitoring (Modal GPU, Relational DB, Redis hot tier, R2 cold tier).

---

## 3. Milestones & Implementation Progress

### Milestone 1: Architectural Foundation & Database Core
- [x] Monorepo structure setup (`frontend`, `backend`, `gpu_workers`, `skills`, `docs`).
- [x] Product Requirements Document (`docs/01_PRD_SRS.md`) and System Architecture Document (`docs/02_SAD.md`).
- [x] Canonical Pydantic v2 ADTs (`Open3DGeometryReport`, `CSGFeatureTree`, `ValidationMetrics`).
- [x] Async SQLAlchemy 2.0 database engine supporting SQLite (local dev) and PostgreSQL (production).
- [x] ORM Models: `Project`, `ScanSession`, `CadGeneration`, `AgentLog`.
- [x] Unified `/api` and `/api/v1` REST routing architecture.

### Milestone 2: Computer Vision Pipeline & 3D Volumetric Engine
- [x] Client-side discrete Laplacian variance blur rejection ($\sigma^2 \ge 120.0$) in Web Worker / Canvas.
- [x] 6-axis guided sequence (`FRONT`, `BACK`, `LEFT`, `RIGHT`, `TOP`, `BOTTOM`) with manual upload fallback.
- [x] 2-point interactive caliper metric scale calibration ($px \to mm$).
- [x] Serverless Cloud GPU worker on Modal (`gpu_workers/modal_app.py`):
  - [x] SAM 2.1 hand & background segmentation with YCrCb skin-border suppression.
  - [x] Depth Anything 3 / V2 dense depth estimation and camera-space unprojection.
  - [x] Open3D 6-axis FPFH + RANSAC + Point-to-Plane ICP registration and primitive extraction.
- [x] Zero-Heat Volumetric Visual Hull Carving Engine (`app/cad/visual_hull.py`):
  - [x] Cluttered background GrabCut & studio matte segmentation.
  - [x] Aspect ratio orientation matching & circular hole detection.
  - [x] 6-axis voxel carving with Taubin smoothing and watertight STL mesh generation.

### Milestone 3: 5-Node Cyclic LangGraph Multi-Agent Orchestrator
- [x] LangGraph Dual-Loop StateGraph topology (`app/agents/graph.py`).
- [x] Multi-Model LLM Router with circuit-breaker cooldowns (`app/agents/llm_router.py`).
- [x] Node 1 (Geometry Analyst) with VLM thumbnail image payloads and Open3D report fusion.
- [x] Node 2 (Parametric Architect) producing structured `CSGFeatureTree` ADTs.
- [x] Node 3 (CAD Synthesizer) with `build123d` RAG service and unified code diff generation.
- [x] Node 4 (Isolated Sandbox Executor) with AST security gate and Inner Self-Healing Loop (max 3 retries).
- [x] Node 5 (Geometric Validator) with 20,000-point bidirectional Chamfer Distance, watertight checks, and Outer Loop accuracy iteration (max 3 iterations).
- [x] Best-Effort artifact retention guard ensuring output quality never regresses across iterations.
- [x] Conversational `/refine` endpoint with NLP intent parsing for dimension and feature updates.

### Milestone 4: CAD Kernel & Interoperability Exporters
- [x] Pure Python ISO 10303-21 STEP AP214 B-Rep exporter with complete entity topology (`app/cad/exporter.py`).
- [x] AutoCAD DXF R12/2010 orthographic projection with `$INSUNITS = 4` ($mm$).
- [x] Manifold watertight ASCII STL generator with Divergence Theorem volume calculations.
- [x] Interoperability verification suite (`app/cad/interop_verifier.py`).
- [x] Golden Dataset automated test suite verifying 10 mechanical archetypes across AutoCAD, Fusion 360, and SolidWorks criteria.

### Milestone 5: Web UI & Interactive 3D Studio
- [x] 4-Page Studio navigation (`capture`, `generate`, `viewer`, `projects`).
- [x] Real-time Agent Terminal with step indicator, thoughts, tool diffs, and Chamfer badges.
- [x] React Three Fiber 3D viewport with OrbitControls, Solid/Wireframe/X-Ray/Turntable modes.
- [x] Interactive 3D Point-to-Point Tape Measure with millimeter and inch readouts.
- [x] Live 4-tier Cloud Diagnostics HUD in Navbar.
- [x] Saved Scans & Projects dashboard with re-generation and viewing capabilities.
- [x] Export Modal with instant format downloads and compatibility checklist.

---

## 4. v1.1 Foundation Increment — Code-Owned Scope (complete)

Observable evidence lives in [`GATES.md`](../GATES.md); every gate is runnable with `node scripts/verify.mjs <gate>`.

| Gate | Roadmap item | Delivered code-owned capability |
| :--- | :--- | :--- |
| G1 | Baseline repair | Green backend suite, `uv run` resolution, fixed invalid `FeatureStep` fixture. |
| G2 | Engineering skills | Six enforceable `skills/*.skill.md` playbooks for the new domains. |
| G3 | Persistent checkpointer | Tiered `AsyncPostgresSaver` → `AsyncRedisSaver` → durable `FileSaver` → `MemorySaver`; `/refine` threads survive process restarts. |
| G4 | `pgvector` RAG | Deterministic semantic embeddings, domain synonyms, injectable `PgVectorRepository`, idempotent HNSW migration, keyword fallback. |
| G5 | Auto scale detection | ID-1 / ArUco detectors in `frontend/src/utils/scaleDetection.ts`, wired into `ScaleCalibrator` with manual override. |
| G6 | JWT auth / multi-tenancy | Opt-in HS256 JWT enforcement, tenant stamping and scoping on all ORM-backed routes and WebSocket handshakes; local `public` bypass. |
| G7 | NURBS surfaces | Opt-in C2 clamped cubic B-spline patches from the visual hull; authoritative watertight AP214 `CLOSED_SHELL` stays unchanged. |
| G8 | CI/CD | `.github/workflows/ci.yml`, schema drift script, shared local/CI commands. |
| G9 | Deployment docs | Actionable provisioning plus explicit external handoffs in [`DEPLOYMENT.md`](DEPLOYMENT.md). |

### Remaining work & future roadmap

| Priority | Feature / Work Item | Scope & Description | Target |
| :--- | :--- | :--- | :--- |
| **P0** | **Live Cloud Deployment & Cluster Binding** | Requires external account provisioning: deploy `gpu_workers/modal_app.py` to a billed Modal account and configure Supabase/Redis credentials. Documented as handoff, not claimed complete. | Production Launch |
| **P0** | **Managed Service Verification** | Run `001_pgvector_rag.sql` / `002_tenant_columns.sql` in Supabase, configure the R2 `uploads/*` 24-hour lifecycle rule, and confirm the checkpointer tier from `/api/health/cloud`. | Production Launch |
| **P2** | **Watertight Trimmed NURBS Solid** | Promote C2 patch groups to a single validated trimmed B-Rep `CLOSED_SHELL`, then update interop golden tests before replacing the faceted authoritative body. | v1.3 |
| **P3** | **Multi-Body Assemblies & Kinematics** | Support multi-part mechanisms with joint constraints and exploded assembly views. | v2.0 |
