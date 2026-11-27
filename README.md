# PhotoCAD 📐🤖

> **Real-Time 6-Sided Web Scan-to-CAD Platform**  
> Turn 6 handheld camera keyframes into editable, millimeter-accurate **Boundary Representation (B-Rep) 3D CAD solids** (`.STEP`, `.DXF`, `.STL`, `.py`) compatible with **AutoCAD**, **Fusion 360**, and **SolidWorks**.

---

## 🌟 Architecture & Capabilities

* **Real-Time Zero-Compression Web Capture (Phase 2):** Browser `getUserMedia` capture chamber with 60 FPS client-side discrete Laplacian variance blur rejection ($\sigma^2 \ge 120.0$), 6-axis guided overlay (`FRONT`, `BACK`, `LEFT`, `RIGHT`, `TOP`, `BOTTOM`), and 1-step $1:1\text{ mm}$ metric caliper / ID-1 card / ArUco calibration.
* **Serverless Cloud GPU 3D Fusion (Phase 3):** Offloads heavy vision models to **Modal NVIDIA L4** workers (`scale-to-zero`):
  1. **SAM 2.1 (`bfloat16`):** Border-connected hand/finger & studio background stripping.
  2. **Depth Anything 3 / V2 (`bfloat16`):** Dense depth & camera-space 3D unprojection across masked pixels.
  3. **Open3D Registration:** Statistical outlier removal, 6-axis `SO(3)` alignment, FPFH + RANSAC + Point-to-Plane ICP, metric scaling, and primitive extraction (`Open3DGeometryReport` + `.PLY` cloud).
* **5-Node Cyclic LangGraph Dual-Loop CAD Synthesis (Phase 4):**
  1. **Geometry Analyst:** Reconciles 6 masked views with Open3D metric ground truth.
  2. **Parametric Architect:** Generates top-down `CSGFeatureTree` Pydantic ADTs + parses conversational `/refine` edits.
  3. **CAD Synthesizer + RAG:** Retrieves verified `build123d` API patterns (`Build123dRAGService`) and emits live unified code diffs.
  4. **Isolated Sandbox Executor *(Inner Self-Healing Loop)*:** Screens code via strict `ast.parse()` security gates before isolated execution, catching syntax or `BRep_API` errors up to 3 automatic retries.
  5. **Chamfer Distance Validator *(Outer Accuracy Loop)*:** Measures bidirectional Chamfer Distance over 20,000 surface samples against the fused `.PLY` scan ($\le 1.0\text{ mm}$ target tolerance), retaining the lowest-error watertight revision.
* **AutoCAD Ecosystem Interoperability & Interactive 3D Viewport (Phase 5):**
  * Three.js / React Three Fiber viewport supporting **`.STL` Solid**, **`.PLY` Point Cloud**, **Overlay Comparison**, **3D Point-to-Point Tape Measure (`mm` / `inch`)**, Wireframe, X-Ray, and Turntable inspection.
  * Export Center with automated ISO 10303-21 AP214 `.STEP` (`SI_UNIT(.MILLI.,.METRE.)`), AutoCAD `.DXF` (`$INSUNITS=4 mm`), 2-Manifold `.STL`, and editable `.py` `build123d` source downloads.

---

## 🏗️ Monorepo Layout

```text
PhotoCAD/
├── frontend/                   # React 19 + TypeScript + Vite + React Three Fiber
│   └── src/
│       ├── components/
│       │   ├── scanner/        # ScannerChamber, ScaleCalibrator
│       │   ├── CadViewport3D.tsx # .STL / .PLY / Overlay + 3D Tape Measure
│       │   ├── AgentTerminal.tsx # Live LangGraph Stepper & Code Diff Stream
│       │   └── ExportModal.tsx   # .STEP / .DXF / .STL / .py + Interop Checklist
│       ├── services/scanApi.ts
│       └── utils/blurDetector.ts
├── backend/                    # FastAPI + Async SQLAlchemy + LangGraph + CAD Sandbox
│   ├── app/
│   │   ├── api/                # REST (/scans, /generate, /export, /projects)
│   │   ├── agents/             # 5-Node Cyclic StateGraph, Nodes, RAG Retriever
│   │   ├── cad/                # AST Sandbox, Manifold Exporters, Chamfer & Interop Verifiers
│   │   ├── models/             # SQLAlchemy Async ORM (PostgreSQL / SQLite fallback)
│   │   ├── schemas/            # Canonical Pydantic v2 ADTs (PCAD-API-ADT-003)
│   │   └── services/           # R2 SigV4 Storage Signer & CV Pipeline Bridge
│   └── tests/                  # Automated Pytest Suites (ADT, CV, Sandbox, Chamfer, LangGraph, Interop)
├── gpu_workers/                # Modal Serverless GPU & OpenCascade Sandbox Workers
│   ├── modal_app.py            # @app.function(gpu="L4") entrypoints
│   ├── segmentation.py         # SAM 2.1 Hand & BG Removal
│   ├── depth_estimation.py     # Depth Anything 3 / V2 Inference
│   ├── fusion_open3d.py        # 6-Side RANSAC + ICP + Primitive Extraction
│   └── cad_sandbox.py          # Network-disabled OpenCascade build123d runner
├── skills/                     # AI Coding Guardrails (cad-kernel, cv-pipeline, langgraph-agents)
└── docs/                       # PRD/SRS, SAD, API ADTs, LangGraph & Deployment Specs
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
* [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) — Production Launch & Cloud Provisioning Guide
