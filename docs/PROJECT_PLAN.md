# PhotoCAD - Project Execution Plan & Specifications

## 1. Executive Summary
**PhotoCAD** is an industry-grade, multi-agent AI and Computer Vision platform that converts multi-axial physical object photographs into fully editable, parametric 3D CAD models (STEP, DXF, STL) for engineering and CAD/CAM simulation pipelines.

Unlike naive polygon-mesh generators, PhotoCAD leverages **multi-view orthographic Computer Vision (OpenCV)** and a **4-tier Agentic LLM loop** to synthesize native **Boundary Representation (B-Rep) solids** via the OpenCascade-backed CadQuery engine.

---

## 2. Industry-Grade Tech Stack

### A. Backend & Geometry Kernel
* **Framework:** FastAPI (Python 3.11/3.12 via `uv`), Async I/O, OpenAPI / Swagger documentation.
* **Database & Persistence:** SQLite (Dev) / PostgreSQL (Production) with **SQLAlchemy 2.0 (Async)** and **Pydantic v2** validation.
* **CAD Modeling Kernel:** **CadQuery** (OpenCascade B-Rep kernel) + **OpenSCAD** fallback engine.
  * Native exports: `.STEP` / `.STP` (AutoCAD, SolidWorks, Fusion 360), `.DXF` (2D technical drawings), and `.STL` (3D printing & web preview).
* **Communication:** REST API + **WebSockets** for real-time agent reasoning streaming, compilation events, and diagnostic logs.

### B. Computer Vision Engine
* **Library:** OpenCV (`cv2`), `numpy`, `scipy`.
* **Modules:**
  * 6-axial perspective calibration (Front, Back, Left, Right, Top, Bottom).
  * Adaptive Canny edge detection & Otsu threshold contour extraction.
  * Real-world metric scaling via ArUco marker or reference calibration token ($1:1\text{ mm}$ mapping).
  * Polygonal approximation (Ramer-Douglas-Peucker) for clean vector path generation.

### C. Multi-Agent AI System
* **Provider:** Google Gemini 2.0 / 1.5 Flash (via `google-genai` SDK) with fallback support for OpenAI / Anthropic / Ollama.
* **Agent 1 - Spatial Vision Analyst:** Evaluates the 6 multi-axis photos and extracted edge maps to compute geometric symmetry, aspect ratios, and feature coordinates.
* **Agent 2 - CSG Geometric Architect:** Generates the sequential Constructive Solid Geometry (CSG) recipe (base extrusions, cutouts, revolutions, fillets, chamfers).
* **Agent 3 - CadQuery Code Synthesizer:** Writes pure, deterministic, parametric CadQuery Python code.
* **Agent 4 - Self-Healing Compiler & Validator:** Executes the script in an isolated sandbox, catches topology errors or kernel crashes, and executes a self-healing reflection loop.

### D. Modern Frontend & 3D Simulation Viewport
* **Core:** Vite + React + TypeScript + Tailwind CSS.
* **3D Viewport:** Three.js with `@react-three/fiber` & `@react-three/drei`.
* **CAD Simulation Tools:**
  * Interactive Orbit / Pan / Zoom controls.
  * Render modes: Solid Shaded, Wireframe, Normal Map, X-Ray Transparency.
  * Dynamic Turntable & Inertial Simulation.
  * Real-time dimension bounding box measuring gizmo.
  * Live CadQuery code editor with in-browser recompilation trigger.

---

## 3. Milestones & Work Breakdown Structure (WBS)

### Milestone 1: Architectural Foundation & Database Core
- [x] Directory structure setup under `d:\Devloper\Projects\PhotoCAD`.
- [x] Architecture & Project Plan documentation.
- [ ] Async Database Engine (SQLAlchemy) with models for:
  - `Project` (name, description, metric unit).
  - `ScanSession` (6-axis image paths, calibration data).
  - `CadGeneration` (versioning, CadQuery code, compile status, export file paths).
  - `AgentLog` (real-time thought stream and tool calls).

### Milestone 2: Computer Vision Pipeline (6-Axis Edge Engine)
- [ ] 6-axis image validator and normalizer.
- [ ] ArUco / Reference marker metric scaling calculation ($px \to mm$).
- [ ] Multi-pass edge detection (Canny, morphological closing, contour hierarchy).
- [ ] Vector feature extraction (bounding boxes, hole centers, radii, symmetry planes).

### Milestone 3: Multi-Agent Orchestrator & Self-Healing CadQuery Engine
- [ ] Agentic prompts with strict Pydantic JSON schemas.
- [ ] Sandboxed CadQuery script execution environment.
- [ ] Multi-turn self-correction loop when compilation throws runtime geometry errors.
- [ ] Exporters for `.STEP`, `.DXF`, and `.STL`.

### Milestone 4: FastAPI REST & WebSocket Backend
- [ ] `/api/projects`: Project CRUD.
- [ ] `/api/scans`: Upload 6-axis photos + trigger CV edge detection.
- [ ] `/api/generate`: Multi-agent pipeline trigger with WebSocket progress streaming.
- [ ] `/api/export`: Download ready-to-use `.STEP`, `.DXF`, and `.STL` files.

### Milestone 5: Modern Dashboard & Three.js 3D Viewport
- [ ] Guided 6-axis camera/image upload wizard with edge preview.
- [ ] Real-time Agent Terminal streaming reasoning steps.
- [ ] Three.js 3D viewport with OrbitControls, Wireframe toggle, and Turntable simulation.
- [ ] Export center for AutoCAD / SolidWorks formats.

---

## 4. Verification & Testing Strategy
* **Unit Testing:** Pytest for CV feature extraction and CadQuery compiler safety.
* **Geometric Regression:** Validating known canonical shapes (cylinder with through-hole, L-bracket, mounting plate) to verify dimensional accuracy ($\pm 1.5\text{ mm}$ tolerance).
* **AutoCAD / FreeCAD Compatibility:** Inspecting generated `.STEP` and `.DXF` files in standard CAD viewers.
