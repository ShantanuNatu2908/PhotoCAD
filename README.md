# PhotoCAD 📐🤖

> **Real-Time 4-to-6-Sided Web Scan-to-CAD Platform**<br>
> Turn handheld camera keyframes into editable, millimeter-accurate **Boundary Representation (B-Rep) 3D CAD solids** (`.STEP`, `.DXF`, `.STL`, `.py`) compatible with **AutoCAD**, **Fusion 360**, and **SolidWorks**.

---

## 🌟 Architecture & Capabilities

* **Real-Time Zero-Compression Web Capture (Phase 2):** Browser `getUserMedia` capture chamber with continuous video mounting, 60 FPS client-side discrete Laplacian variance blur rejection ($\sigma^2 \ge 120.0$), 6-axis guided overlay (`FRONT`, `BACK`, `LEFT`, `RIGHT`, `TOP`, `BOTTOM`), manual photo upload fallback, and 1-step $1:1\text{ mm}$ metric caliper calibration.
* **Serverless Cloud GPU 3D Fusion (Phase 3):** Offloads heavy vision models to **Modal NVIDIA L4** workers (`scale-to-zero`):
  1. **SAM 2.1 (`bfloat16`):** Border-connected hand/finger & studio background stripping.
  2. **Depth Anything 3 / V2 (`bfloat16`):** Dense depth & camera-space 3D unprojection across masked pixels.
  3. **Open3D Registration:** Statistical outlier removal, 6-axis `SO(3)` alignment, FPFH + RANSAC + Point-to-Plane ICP, metric scaling, and primitive extraction (`Open3DGeometryReport` + `.PLY` cloud).
* **Local Zero-Heat 3D Volumetric Visual Hull Engine:** Offline GrabCut foreground segmentation, circular Euler hole detection, 6-axis volumetric voxel carving with Taubin smoothing, and watertight B-Rep generation for zero-cost offline development.
* **5-Node Cyclic LangGraph Dual-Loop CAD Synthesis (Phase 4):**
  1. **Multi-Model LLM Router:** Ordered fallback across Gemini 3.5 Flash, 3.1 Flash-Lite, 2.5 Flash, and Claude Sonnet 4.5, with circuit-breaker cooldowns.
  2. **Geometry Analyst:** Reconciles 6 masked views with Open3D metric ground truth and carved visual hull metadata.
  3. **Parametric Architect:** Generates top-down `CSGFeatureTree` Pydantic ADTs with strict topological constraints + parses conversational `/refine` edits.
  4. **CAD Synthesizer + RAG:** Retrieves verified `build123d` API patterns (`Build123dRAGService`) and emits live unified code diffs.
  5. **Isolated Sandbox Executor *(Inner Self-Healing Loop)*:** Screens code via strict `ast.parse()` security gates before isolated execution, catching syntax or `BRep_API` errors up to 3 automatic retries.
  6. **Chamfer Distance Validator *(Outer Accuracy Loop)*:** Measures bidirectional Chamfer Distance over 20,000 surface samples against the fused `.PLY` scan ($\le 1.0\text{ mm}$ target tolerance), retaining the lowest-error watertight revision.
* **AutoCAD Ecosystem Interoperability & Interactive 3D Studio (Phase 5):**
  * **4-Page Workflow:**
    * **Page 1: Capture Studio:** Guided 6-axis camera chamber with real-time blur score and upload fallbacks.
    * **Page 2: Calibrate & Generate:** Caliper metric calibration, reconstruction options (`auto_hull` vs `prismatic`), edge finish selector, and live LangGraph terminal.
    * **Page 3: 3D CAD Output:** Three.js / React Three Fiber viewport with Solid, Wireframe, X-Ray, Turntable, **3D Point-to-Point Tape Measure (`mm` / `inch`)**, Export Center, and conversational `/refine` studio.
    * **Page 4: Saved Projects & Scans:** Instant archive of past scans with thumbnail previews and 1-click reload.
  * **Export Center:** Automated ISO 10303-21 AP214 `.STEP` (`SI_UNIT(.MILLI.,.METRE.)`), AutoCAD `.DXF` (`$INSUNITS=4 mm`), 2-Manifold `.STL`, and editable `.py` `build123d` source downloads.
  * **Golden Dataset Verifier:** Automated validation of 10 mechanical archetypes against AutoCAD, Fusion 360, and SolidWorks criteria.

---

## 🏗️ Monorepo Layout

```text
PhotoCAD/
├── frontend/                   # React 19 + TypeScript + Vite + React Three Fiber
│   └── src/
│       ├── components/
│       │   ├── pages/          # 4-Page Workflow: Capture, Generate, Output, Saved Scans
│       │   ├── scanner/        # ScannerChamber (Blur Filter, Camera), ScaleCalibrator
│       │   ├── CadViewport3D.tsx # .STL / .PLY / Overlay + 3D Point-to-Point Tape Measure
│       │   ├── AgentTerminal.tsx # Live LangGraph Stepper, Unified Diffs & Chamfer Badges
│       │   ├── ExportModal.tsx   # .STEP / .DXF / .STL / .py + CAD Interop Checklist
│       │   └── Navbar.tsx        # Navigation Stepper + 4-Tier Cloud Diagnostics HUD
│       ├── services/scanApi.ts
│       └── utils/blurDetector.ts
├── backend/                    # FastAPI + Async SQLAlchemy + LangGraph + CAD Sandbox
│   ├── app/
│   │   ├── api/                # REST (/scans, /generate, /export, /projects, /health)
│   │   ├── agents/             # 5-Node Cyclic StateGraph, LLM Router, RAG Retriever
│   │   ├── cad/                # AST Sandbox, Visual Hull Voxel Carver, Exporters, Interop
│   │   ├── core/               # Cloud Auth Diagnostics, Health Service, Config, DB
│   │   ├── models/             # SQLAlchemy Async ORM (PostgreSQL / SQLite fallback)
│   │   ├── schemas/            # Canonical Pydantic v2 ADTs (PCAD-API-ADT-003)
│   │   └── services/           # R2 SigV4 Storage Signer & CV Pipeline Bridge
│   └── tests/                  # Automated Pytest Suites (Golden Dataset, Hull, LangGraph, Interop)
├── gpu_workers/                # Modal Serverless GPU & OpenCascade Sandbox Workers
│   ├── modal_app.py            # @app.function(gpu="L4") entrypoints
│   ├── segmentation.py         # SAM 2.1 Hand & BG Removal
│   ├── depth_estimation.py     # Depth Anything 3 / V2 Inference
│   ├── fusion_open3d.py        # 6-Side RANSAC + ICP + Primitive Extraction
│   └── cad_sandbox.py          # Network-disabled OpenCascade build123d runner
├── skills/                     # AI Coding Guardrails (cad-kernel, cv-pipeline, langgraph-agents)
└── docs/                       # PRD/SRS, SAD, API ADTs, LangGraph, Architecture & Deployment Specs
```

---

## 🚀 Quickstart (Zero-Heat Local Dev)

### Prerequisites
* Python `3.12+` (managed via `uv`)
* Node.js `v20+` & `npm`

### 1. Start Studio Launcher (Windows)
```powershell
.\start.ps1
```

### 2. Manual Backend & Frontend Launch
```bash
# Backend (http://localhost:8000)
cd backend
uv venv && .venv\Scripts\activate   # Or source .venv/bin/activate on Linux/macOS
uv pip install -e .
python -m uvicorn app.main:app --reload --port 8000

# Frontend (http://localhost:5173)
cd frontend
npm install
npm run dev
```

### 3. Deploy Serverless Cloud GPUs (Optional Production Cloud Mode)
Copy `.env.example` to `.env`, configure Supabase, Redis, Cloudflare R2, Gemini/Anthropic keys, and Modal credentials, then deploy:
```bash
modal deploy gpu_workers/modal_app.py
```

---

## ✅ Verification & Testing

```bash
# Run full backend integration, LangGraph & Golden Dataset CAD interoperability suite
cd backend
.venv\Scripts\python.exe -m pytest tests/ -v

# Verify frontend production TypeScript bundle & lint rules
cd frontend
npm run build
npm run lint
```

---

## 📖 Engineering Specifications
* [`docs/01_PRD_SRS.md`](docs/01_PRD_SRS.md) — Functional & Non-Functional Requirements (`FR-01`..`FR-18`, `NFR-01`..`NFR-10`)
* [`docs/02_SAD.md`](docs/02_SAD.md) — Decoupled Thin-Client + Modal Cloud GPU Architecture
* [`docs/03_API_ADT_SPEC.md`](docs/03_API_ADT_SPEC.md) — REST, WebSocket & Pydantic v2 Contracts
* [`docs/04_LANGGRAPH_SPEC.md`](docs/04_LANGGRAPH_SPEC.md) — Cyclic Dual-Loop State Machine Topology
* [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — End-to-End System Architecture & Data Flow
* [`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md) — Milestones, Deliverables & Roadmap
* [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) — Production Launch & Cloud Provisioning Guide
