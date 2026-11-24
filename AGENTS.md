# AGENTS.md — PhotoCAD Engineering Rules & AI Coding Skills

> **Audience:** Autonomous & interactive coding agents (**Google Antigravity**, **OpenCode**, Cursor, Claude Code) and human contributors working on the **PhotoCAD** monorepo.  
> **Rule:** Read this file completely before modifying any code, schema, or infrastructure configuration.

---

## 1. Repository Identity & Golden Architectural Rules

**PhotoCAD** is a real-time, web-based 6-sided Scan-to-CAD platform converting handheld camera keyframes into parametric B-Rep solids (`.STEP`, `.DXF`, `.STL`).

### Non-Negotiable Constraints
1. **Zero-Heat Cloud-First Development:** Do NOT add heavy local Docker Compose stacks (local Postgres + local Redis + local PyTorch) as mandatory dev dependencies. Target managed cloud services (**Supabase**, **Redis Cloud**, **Cloudflare R2**, **Modal**) via `.env` variables.
2. **No OpenCV Canny Edge Reconstruction:** Never build 3D CAD geometry from 2D OpenCV Canny/Otsu contours. Handheld object capture MUST follow: `Uncompressed PNG Keyframes -> SAM 2.1/3.1 Masking -> Depth Anything 3 (DA3) -> Open3D Fusion -> LangGraph -> build123d`.
3. **Strict Monorepo Boundaries:**
   * `frontend/`: React 19 + TypeScript + Vite + React Three Fiber (zero Python).
   * `backend/`: FastAPI + Async SQLAlchemy 2.0 + LangGraph + ARQ (zero PyTorch / CUDA).
   * `gpu_workers/`: Modal serverless functions (`@app.function(gpu="L4")`) running PyTorch, SAM, Depth Anything 3, and Open3D.
4. **Binary Blob Hygiene:** Never store raw images, `.PLY` point clouds, or `.STEP`/`.STL` binaries in PostgreSQL or Redis. Store all binary assets in Cloudflare R2 and persist only object keys.
5. **Mandatory Sandbox Isolation:** Never call `exec()`, `eval()`, or run LLM-generated `build123d` code directly inside the FastAPI or ARQ worker process. Always route execution through `backend/app/cad/sandbox.py` (AST checker + isolated Modal/gVisor sandbox).

---

## 2. Approved Tech Stack & Version Pins

| Layer | Approved Libraries | Explicitly Banned |
| :--- | :--- | :--- |
| **Python Tooling** | Python `3.12`, `uv`, `ruff`, `mypy`, `pytest` | `pipenv`, `poetry`, Python `< 3.11` |
| **Backend API** | `fastapi`, `pydantic>=2.7`, `sqlalchemy[asyncio]>=2.0`, `arq` | `flask`, `django`, sync `psycopg2` |
| **Agents & RAG** | `langgraph`, `langgraph-checkpoint-redis` (or `postgres`), `pgvector`, `langchain-google-genai`, `langchain-anthropic` | Unstructured regex-parsed LLM chains, `AutoGPT` |
| **CAD Kernel** | `build123d` (primary), `ocp` (OpenCascade) | `OpenSCAD` CLI as primary kernel, mesh-only Booleans |
| **CV / 3D GPU** | `modal`, `torch` (`FP16`/`BF16`), `sam2`/`sam3`, `depth-anything-3`, `open3d` | Local Colab/Kaggle ngrok tunnels, `FP32`-only inference |
| **Frontend** | `react@19`, `typescript`, `vite`, `@react-three/fiber`, `@react-three/drei`, `tailwindcss` | Raw uncompressed video streaming over WebRTC for reconstruction |

---

## 3. Embedded Agent Skill: `cad-kernel.skill.md`

*Apply these rules whenever writing, testing, or prompting `build123d` CAD generation code (`backend/app/cad/` and `backend/app/agents/nodes/synthesizer.py`).*

### Rules
1. **Units Are Strictly Millimeters (`mm`):** Every numeric constant represents millimeters ($1:1\text{ mm}$). Never convert to inches or meters inside CAD scripts.
2. **Prefer Builder Mode (`BuildPart` / `BuildSketch`):** Always use `build123d` context managers rather than legacy CadQuery fluent chains.
3. **Parametric Constants First:** Declare all critical dimensions as uppercase floats at the top of every generated script so `/refine` edits are trivial and diffable.
4. **Apply Fillets & Chamfers Last:** Always construct primary solids, bosses, and hole cuts *before* calling `fillet()` or `chamfer()`. Guard edge fillets with `radius < min_adjacent_thickness / 2.5` to prevent OpenCascade `BRep_API` crashes.
5. **Standardized Output Variable & Validation:** Every synthesized script must expose `RESULT_PART` and pass validity assertions before export.

### Canonical `build123d` Pattern
~~~python
from build123d import (
    BuildPart, BuildSketch, Rectangle, Circle, Locations,
    Mode, Axis, extrude, fillet
)

# Parametric Dimensions (mm)
LENGTH_MM = 64.5
WIDTH_MM = 42.0
THICKNESS_MM = 12.0
HOLE_DIA_MM = 5.0
HOLE_OFFSET_X = 24.0
HOLE_OFFSET_Y = 14.0
TOP_FILLET_MM = 1.5

with BuildPart() as part:
    with BuildSketch():
        Rectangle(LENGTH_MM, WIDTH_MM)
    extrude(amount=THICKNESS_MM)

    with BuildSketch(part.faces().sort_by(Axis.Z)[-1]):
        with Locations(
            (HOLE_OFFSET_X, HOLE_OFFSET_Y),
            (-HOLE_OFFSET_X, HOLE_OFFSET_Y),
            (HOLE_OFFSET_X, -HOLE_OFFSET_Y),
            (-HOLE_OFFSET_X, -HOLE_OFFSET_Y),
        ):
            Circle(HOLE_DIA_MM / 2.0)
    extrude(amount=-THICKNESS_MM, mode=Mode.SUBTRACT)

    top_edges = part.edges().filter_by(Axis.Z, reverse=True).group_by(Axis.Z)[-1]
    fillet(top_edges, radius=TOP_FILLET_MM)

RESULT_PART = part.part
assert RESULT_PART.is_valid(), "Generated B-Rep solid is invalid"
~~~

---

## 4. Embedded Agent Skill: `cv-pipeline.skill.md`

*Apply these rules whenever modifying `gpu_workers/` (Modal, SAM, Depth Anything 3, Open3D).*

### Rules
1. **Keyframe-Only Inference (Prevent OOM):** Never hold continuous video embedding caches in VRAM. Process the 6 uploaded `.PNG` keyframes as a bounded batch, calling `torch.cuda.empty_cache()` after segmentation and depth stages.
2. **Mandatory Half-Precision (`FP16`/`BF16`):** Wrap all PyTorch forward passes in `torch.inference_mode()` and `torch.autocast(device_type="cuda", dtype=torch.bfloat16)`.
3. **Modal Function Configuration:** Decorate GPU workers with explicit `gpu="L4"`, `scaledown_window=60`, and mount a persistent `modal.Volume` for cached model weights so cold starts never re-download gigabytes from Hugging Face.
4. **Open3D Registration Hygiene:**
   * Always run `remove_statistical_outlier(nb_neighbors=20, std_ratio=2.0)` before ICP.
   * Reject fusions where `icp_fitness_score < 0.65` and return structured error `FUSION_LOW_OVERLAP` instead of sending garbage geometry to LangGraph.
   * Apply metric calibration scaling *before* RANSAC plane/cylinder extraction so all `Open3DGeometryReport` fields are strictly in `mm`.

---

## 5. Embedded Agent Skill: `langgraph-agents.skill.md`

*Apply these rules whenever modifying `backend/app/agents/`.*

### Rules
1. **Strict Structured Outputs:** Nodes 1 and 2 must use `.with_structured_output(PydanticModel)`—never parse free-form Markdown with regex.
2. **Hard Loop Caps:** Never allow unbounded recursion. Enforce `compile_retries <= 3` (Inner Loop) and `geometry_iterations <= 3` (Outer Loop) in conditional edge routers AND set LangGraph `recursion_limit=20`.
3. **Event Streaming Parity:** Every node entry and exit must append a typed event matching `docs/03_API_ADT_SPEC.md` Section 3 so the React `AgentConsole` updates in real time.
4. **Best-Effort Tracking:** Node 5 must always preserve the lowest-Chamfer valid `.STEP` revision in `state["best_artifact_keys"]` so users never lose a valid model if iteration 3 regresses.

---

## 6. Agent Pre-Commit Verification Checklist

Before marking any task or pull request complete, coding agents must run and pass:

1. **Backend Lint & Types:** `uv run ruff check backend/ gpu_workers/` and `uv run mypy backend/`
2. **Backend & Contract Tests:** `uv run pytest backend/tests/` (must include Pydantic ADT round-trip tests and AST sandbox security tests)
3. **Frontend Type & Build Check:** `cd frontend && npm run typecheck && npm run build`
4. **Schema Sync Verification:** Confirm any Pydantic model changes in `backend/app/schemas/` remain synchronized with `docs/03_API_ADT_SPEC.md` and `frontend/src/types/`.
