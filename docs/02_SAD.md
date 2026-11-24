# PhotoCAD — System Architecture Document (SAD)

**Document ID:** `PCAD-SAD-002`  
**Version:** `1.0.0`  
**Status:** Approved for Development (Wave 1)  

---

## 1. Architectural Strategy & Design Principles

PhotoCAD adopts a **Decoupled Thin-Client + Serverless Cloud GPU + Stateful Agentic Control Plane** architecture designed around four core principles:

1. **Keyframe Quality Over Video Bandwidth:** Never reconstruct CAD edges from lossy compressed WebRTC video streams. Capture uncompressed `.PNG` keyframes in the browser only when local motion-blur filters confirm high sharpness.
2. **Mathematical 3D Grounding Before LLM Synthesis:** Never ask an LLM to guess 3D geometry purely from 2D contours. Compute true 3D multi-view depth, camera poses, and Open3D primitive extraction first, feeding exact millimeter measurements into the agent graph.
3. **Cyclic Self-Correction Over One-Shot Prompting:** CAD code generation is executed inside a deterministic LangGraph state machine with both a **Compile-Repair Inner Loop** and a **Chamfer-Validation Outer Loop**.
4. **Zero-Heat Cloud-First Development:** All GPU inference (Modal), database workloads (Supabase, Redis Cloud), and blob storage (Cloudflare R2) run in managed cloud tiers so developers never bottleneck local laptop RAM or VRAM.

---

## 2. System Context & Container Architecture

~~~text
+-----------------------------------------------------------------------------+
|                        USER BROWSER (Web Thin-Client)                       |
|   [React 19 + TypeScript + Vite]                                            |
|   - Camera Capture Module (getUserMedia + Local Sharpness/Blur Filter)      |
|   - Calibration UI (ArUco Detector / 2-Point Known Dimension Input)         |
|   - 3D Viewport (React Three Fiber / Three.js: .PLY & .STL Preview)         |
|   - Live Agent Console (WebSocket Event Stream + Parametric Edit Prompt)    |
+--------------------+-------------------------------------+------------------+
                     | Direct Pre-Signed PUT (.PNG)        | HTTPS REST + WSS
                     v                                     v
+--------------------------------------+   +----------------------------------+
|    OBJECT STORAGE (Cloudflare R2)    |   |   CONTROL PLANE API (FastAPI)    |
|  - Raw 6-Side Keyframes (24h TTL)    |<->|  - Auth & Session Management     |
|  - Masked Views & Depth Maps         |   |  - Pre-Signed URL Signing        |
|  - Fused Point Clouds (.PLY)         |   |  - WebSocket Connection Hub      |
|  - Exported .STEP, .DXF, .STL, .py   |   |  - ARQ Async Job Dispatcher      |
+--------------------+-----------------+   +--------+----------------+--------+
                     ^                              |                |
                     |                              v                v
+--------------------+-----------------+   +------------------+ +-------------+
|    SERVERLESS GPU PLANE (Modal)      |   |  HOT DATA TIER   | |  WARM TIER  |
|  [NVIDIA L4 / A10G - Scale-to-Zero]  |   |  (Redis 8.0+)    | | (Supabase)  |
|  1. SAM 2.1 / SAM 3.1 (FP16 Masking) |   |  - Redis Streams | | - Postgres  |
|  2. Depth Anything 3 (Multi-View     |   |  - Pub/Sub Events| | - pgvector  |
|     Depth & Camera Pose Recovery)    |   |  - LangGraph     | |   (build123d|
|  3. Open3D (RANSAC/ICP + Primitives) |   |    Checkpointer  | |    API RAG) |
+--------------------+-----------------+   +--------+---------+ +------+------+
                     |                              ^                  ^
                     | Open3DGeometryReport JSON    |                  |
                     v                              v                  v
+-----------------------------------------------------------------------------+
|                 AGENTIC CAD ORCHESTRATION PLANE (Worker)                    |
|  [LangGraph Dual-Loop State Machine + LangSmith/Langfuse Observability]     |
|  - Node 1: Geometry Analyst (Gemini 3 Pro VLM)                              |
|  - Node 2: Parametric Architect (Gemini 3 Pro / Claude Sonnet 4.5)          |
|  - Node 3: CAD Code Synthesizer (Claude Sonnet 4.5 + pgvector RAG)          |
|  - Node 4: Isolated Sandbox Executor (build123d + OpenCascade in gVisor)    |
|  - Node 5: Geometric Validator (Open3D Chamfer Distance + Visual Check)     |
+-----------------------------------------------------------------------------+
~~~

---

## 3. Component Deep-Dive

### 3.1 Web Thin-Client (`frontend/`)
* **Framework:** React 19, TypeScript, Vite, Tailwind CSS.
* **Capture Engine:** Uses `MediaDevices.getUserMedia` with constraints requesting maximum optical sharpness. A lightweight Web Worker runs a $3 \times 3$ Laplacian variance sharpness check at $15\text{--}30\text{ FPS}$ so the user receives instant green/red stability feedback before each keyframe snap.
* **Direct-to-Storage Uploads:** Keyframes are uploaded directly from the browser to **Cloudflare R2** using short-lived pre-signed `PUT` URLs generated by FastAPI, keeping large binary payloads off the API server.
* **3D Renderer:** **React Three Fiber** loads the fused `.PLY` preview and compiled `.STL` mesh, providing dimension callouts, orbit controls, and side-by-side deviation overlays.

### 3.2 Control Plane API (`backend/`)
* **Framework:** FastAPI (Python 3.12, managed via `uv`), Pydantic v2, Async SQLAlchemy 2.0.
* **Job Orchestration:** Uses **ARQ** (async Redis-backed worker queue) to dispatch non-blocking CV and LangGraph pipelines while FastAPI streams status updates over WebSockets via Redis Pub/Sub.

### 3.3 Serverless GPU Compute Plane (`gpu_workers/` on Modal)
Running on **Modal** (`@app.function(gpu="L4", scaledown_window=60)`), all neural inference runs in `torch.bfloat16` / `FP16`:
1. **Hand & Background Removal:** **SAM 2.1 (Small)** or **SAM 3.1** (drop-in upgrade) isolates the handheld object across all 6 keyframes, outputting clean alpha masks and removing fingers/palms that occlude edges.
2. **Multi-View 3D Geometry Recovery:** **Depth Anything 3 (DA3)** processes the 6 masked views jointly to predict camera extrinsics/poses and mutually consistent, fusible depth maps (with **Depth Anything V2 Metric** available as a lightweight fallback).
3. **3D Fusion & Primitive Extraction:** **Open3D (C++ backend)** unprojects masked depth maps into 3D space, applies statistical outlier removal, refines alignment via **Multi-Scale Colored/Point-to-Plane ICP**, scales the cloud to $1:1\text{ mm}$ using the calibration factor, and extracts planes (RANSAC), cylinders/holes, symmetry axes, and bounding box dimensions into `Open3DGeometryReport`.

### 3.4 Agentic CAD Synthesis & Sandbox Plane
* **Orchestrator:** **LangGraph** executing the 5-node dual-loop workflow.
* **CAD Modeling Kernel:** **`build123d`** (built on OpenCascade / OCP) is selected as the primary B-Rep engine due to its concise Pythonic context-manager syntax (`with BuildPart():`), higher LLM syntactic reliability, and native `.STEP`, `.DXF`, and `.STL` export capabilities.
* **Isolated Execution Sandbox:** LLM-generated Python scripts **never** run inside the FastAPI or LangGraph host process. They execute inside ephemeral, rootless **Modal Sandboxes** (gVisor isolated) with:
  * `network=None` (zero outbound/inbound internet access)
  * Read-only system mounts + ephemeral `/tmp/work` directory
  * Strict resource limits: $2\text{ vCPU}$, $2\text{ GB RAM}$, $30\text{ s}$ wall-clock timeout
  * Whitelisted imports (`build123d`, `math`, `numpy`) verified via Python AST static analysis prior to execution.

---

## 4. 3-Tier Data & Storage Architecture

| Tier | Service | Data Stored | Architectural Notes |
| :--- | :--- | :--- | :--- |
| **Hot Tier** | **Redis 8.0+ (Redis Cloud / Stack)** | LangGraph Checkpoints (`langgraph-checkpoint-redis`), ARQ Job Queues, WebSocket Pub/Sub events. | **Critical Note:** `langgraph-checkpoint-redis` requires `RediSearch` and `RedisJSON` modules (bundled natively in Redis 8.0+). If deploying on a serverless Redis provider lacking those modules (e.g., standard Upstash), route LangGraph checkpointing to `AsyncPostgresSaver` on Supabase while keeping Redis for Pub/Sub and ARQ queues. |
| **Warm Tier** | **PostgreSQL 16 + `pgvector` (Supabase / Neon)** | User accounts, scan projects, view metadata, revision history, parametric JSON specs, and `build123d` API documentation embeddings (`HNSW` index). | Single source of truth for relational integrity and agent RAG retrieval. |
| **Cold Tier** | **Cloudflare R2 (S3-Compatible)** | Raw `.PNG` keyframes, alpha masks, `.PLY` point clouds, `.STEP`, `.DXF`, `.STL`, `.py` exports. | Zero egress fees for heavy 3D downloads; automated lifecycle rule purges raw user camera frames after $24\text{ hours}$. |

---

## 5. End-to-End Request Sequence Flow

~~~text
User Browser         FastAPI API        Cloudflare R2       Modal GPU Worker     LangGraph + Sandbox
     |                    |                   |                    |                      |
     |--POST /scans------>|                   |                    |                      |
     |<--6 PreSigned URLs-|                   |                    |                      |
     |                    |                   |                    |                      |
     |--PUT 6x PNGs (Direct Upload)---------->|                    |                      |
     |--POST /calibrate-->|                   |                    |                      |
     |--POST /generate--->|--Enqueue Job----->|                    |                      |
     |==WSS Connected====>|                   |                    |                      |
     |                    |===================|==Dispatch CV======>|                      |
     |                    |                   |<--Fetch 6 PNGs-----|                      |
     |                    |                   |   [SAM -> DA3 -> Open3D Fusion]           |
     |                    |                   |<--Save .PLY + Masks|                      |
     |<--WSS: fusion_done-|<--Geometry JSON---|--------------------|                      |
     |                    |                   |                    |                      |
     |                    |--Invoke Graph (Geometry JSON + Masks)------------------------>|
     |<--WSS: agent_nodes-|<--Stream Node Transitions-------------------------------------|
     |                    |                   |                    |  [Dual-Loop CAD Gen] |
     |                    |                   |<--Upload .STEP/.DXF/.STL/.py--------------|
     |<--WSS: completed---|<--Signed URLs-----|-------------------------------------------|
     |--GET .STEP/.STL----------------------->|                    |                      |
~~~

---

## 6. Security, Resilience & Fault Tolerance

* **Remote Code Execution (RCE) Defense-in-Depth:**
  1. **AST Pre-Scanner:** Rejects `os`, `sys`, `subprocess`, `socket`, `open()`, `eval`, `exec`, and `__import__` before the script enters the sandbox.
  2. **gVisor / Modal Sandbox:** OS-level syscall isolation with zero network access and non-root execution.
* **LLM Provider Resilience:** Primary routing uses **Gemini 3 Pro** (multimodal geometry analysis) and **Claude Sonnet 4.5** (`build123d` code synthesis), with automatic fallback to alternate models via LangChain/LangGraph configurable runnables if a provider returns HTTP `429` or `5xx`.
* **Graceful Degradation:** If the Outer Accuracy Loop hits its 3-iteration cap with Chamfer Distance slightly above $1.0\text{ mm}$ (e.g., $1.3\text{ mm}$), the system returns the lowest-error valid `.STEP` revision flagged with `status: "completed_with_warning"` and highlights the high-deviation regions in the 3D viewport.

---

## 7. Cloud-First Deployment Topology

| Environment | Frontend | Backend API & Workers | GPU Workers | Databases |
| :--- | :--- | :--- | :--- | :--- |
| **Development ("Zero-Heat")** | Local Vite (`npm run dev`) or Lightning AI | Local FastAPI (`uv`) or Antigravity Sandbox | **Modal Dev** (`modal serve`) | Supabase Free + Redis Cloud Free + R2 Free |
| **Production** | **Vercel / Cloudflare Pages** | **Fly.io / Render / Railway** (Auto-scaling containers) | **Modal Prod** (`modal deploy`, L4 GPU pool) | Supabase Pro + Redis Cloud 8.0 + Cloudflare R2 |
