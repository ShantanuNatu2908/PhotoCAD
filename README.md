# PhotoCAD 📐🤖

> **Multi-Axis Vision to Parametric B-Rep CAD Platform**  
> Turn physical object photos from 6 orthogonal perspectives into production-ready, editable 3D CAD models (`.STEP`, `.DXF`, `.STL`) for AutoCAD, SolidWorks, and Fusion 360 using Multi-Agent AI and Computer Vision.

---

## 🌟 Key Highlights

- **True Parametric B-Rep Solids (Not Just Meshes):** Unlike AI mesh generators that output hollow polygon meshes, PhotoCAD generates editable OpenCascade **B-Rep** solids (`.STEP`) with precise dimensions, holes, and fillets.
- **6-Axis Orthographic Vision Pipeline:** Ingests Front, Back, Left, Right, Top, and Bottom photos with OpenCV contour extraction and metric scale calibration.
- **4-Stage Multi-Agent AI Loop:**
  1. *Spatial Vision Analyst* (Multi-view cross-correlation)
  2. *CSG Geometric Architect* (Constructive solid geometry planning)
  3. *CadQuery Synthesizer* (Deterministic Python CAD generation)
  4. *Self-Healing Compiler* (Catches kernel errors and self-corrects code)
- **AutoCAD & Ecosystem Exports:** One-click download of `.STEP` (SolidWorks/AutoCAD), `.DXF` (2D technical drawings), and `.STL` (3D printing).
- **Interactive 3D Simulation Viewport:** Three.js / React-Three-Fiber viewer with Wireframe toggles, dimension bounding boxes, and turntable physics simulation.

---

## 🏗️ Project Architecture

```
PhotoCAD/
├── backend/                  # FastAPI Async Backend
│   ├── app/
│   │   ├── api/              # REST & WebSocket Endpoints
│   │   ├── core/             # Configuration & Database setup
│   │   ├── models/           # SQLAlchemy DB Models (Projects, Scans, CAD)
│   │   ├── schemas/          # Pydantic v2 Contract Schemas
│   │   └── services/
│   │       ├── vision_engine.py      # OpenCV 6-Axis Contours & Calibration
│   │       ├── cad_engine.py         # CadQuery & OpenCascade compiler
│   │       └── agents/               # 4-tier Multi-Agent Orchestrator
├── frontend/                 # Vite + React + TypeScript + Tailwind CSS
│   ├── src/
│   │   ├── components/3d/    # Three.js 3D Viewport & Simulation
│   │   ├── components/scanner/ # Guided 6-Axis Capture & Edge Preview
│   │   └── components/agents/  # Real-time Agent Reasoning Stream
├── docs/                     # System Architecture, Plan & API Docs
└── storage/                  # Generated .STEP, .DXF, .STL artifacts
```

---

## 🚀 Quickstart & Setup Guide

### Prerequisites
* Python 3.11+ (managed via `uv` or standard Python)
* Node.js v18+ & npm
* (Optional) OpenSCAD installed for fallback rendering

### Backend Setup
```bash
cd backend
uv venv
source .venv/bin/activate  # Or on Windows: .venv\Scripts\activate
uv pip install -e .
python -m uvicorn app.main:app --reload --port 8000
```

### Frontend Setup
```bash
cd frontend
npm install
npm run dev
```

Visit `http://localhost:5173` to launch the PhotoCAD Studio.

---

## 📖 Documentation
* [Project Plan & Roadmap](docs/PROJECT_PLAN.md)
* [System Architecture & Data Flow](docs/ARCHITECTURE.md)
