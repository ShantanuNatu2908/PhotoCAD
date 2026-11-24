# PhotoCAD — Agentic Orchestration & LangGraph Specification

**Document ID:** `PCAD-LG-004`  
**Version:** `1.0.0`  
**Status:** Approved for Development (Wave 1)  

---

## 1. Dual-Loop Graph Topology

PhotoCAD replaces brittle linear prompt chains with a **5-Node Cyclic LangGraph State Machine** engineered with two independent feedback loops:

* **Inner Loop (Syntax & Kernel Self-Healing):** Catches Python syntax errors, invalid OpenCascade boolean intersections, or impossible fillet radii and auto-repairs code immediately.
* **Outer Loop (Geometric Accuracy Verification):** Measures the compiled `.STEP` solid against the physical Open3D scan using bidirectional Chamfer Distance and iteratively adjusts dimensions until error $\le 1.0\text{ mm}$.

~~~text
                         [START: 6 Masked Views + Open3DGeometryReport]
                                               |
                                               v
                                 +---------------------------+
                                 | Node 1: Geometry Analyst  | (Gemini 3 Pro VLM)
                                 +-------------+-------------+
                                               |
                                               v
                      +--------->+---------------------------+
                      |          | Node 2: Parametric        | (Gemini 3 Pro /
                      |          |         Architect         |  Claude Sonnet 4.5)
                      |          +-------------+-------------+
                      |                        |
                      |                        v
            Outer Loop|          +---------------------------+
       (Chamfer > 1mm,|    +---->| Node 3: CAD Synthesizer   | (Claude Sonnet 4.5
        iter < 3)     |    |     |         + pgvector RAG    |  + build123d Docs)
                      |    |     +-------------+-------------+
                      |    |                   |
                      |    | Inner Loop        v
                      |    | (Compile Err,  +---------------------------+
                      |    |  retry < 3)    | Node 4: Isolated Sandbox  | (Deterministic
                      |    +----------------|         Executor          |  Modal/gVisor)
                      |                     +-------------+-------------+
                      |                                   | Compile OK
                      |                                   v
                      |                     +---------------------------+
                      +---------------------| Node 5: Geometric         | (Open3D Chamfer +
                                            |         Validator         |  VLM Sanity Check)
                                            +-------------+-------------+
                                                          | Passed (<= 1.0mm)
                                                          | OR Max Outer Iter Reached
                                                          v
                                            [END: Publish Best .STEP/.DXF/.STL]
~~~

---

## 2. Canonical LangGraph State Schema

~~~python
from typing import Annotated, Optional, TypedDict
from operator import add
from app.schemas.adt import Open3DGeometryReport, CSGFeatureTree, ValidationMetrics

class PhotoCADGraphState(TypedDict):
    # Immutable Inputs
    scan_id: str
    masked_image_urls: dict[str, str]          # front/back/left/right/top/bottom
    geometry_report: Open3DGeometryReport
    user_edit_instruction: Optional[str]       # Populated during /refine calls

    # Intermediate Agent Artifacts
    spatial_analysis: Optional[str]            # Output of Node 1
    feature_tree: Optional[CSGFeatureTree]     # Output of Node 2
    retrieved_api_docs: list[str]              # Output of pgvector RAG lookup
    current_code: Optional[str]                # Output of Node 3

    # Execution & Validation State
    compile_error_trace: Optional[str]         # Output of Node 4 on failure
    compile_retries: int                       # Inner loop counter (0..3)
    geometry_iterations: int                   # Outer loop counter (0..3)
    validation_metrics: Optional[ValidationMetrics]

    # Best-Effort Tracking (Guarantees safest output if outer loop caps out)
    best_code: Optional[str]
    best_chamfer_mm: float                     # Initialized to float("inf")
    best_artifact_keys: dict[str, str]         # {"step": ..., "dxf": ..., "stl": ...}

    # Streaming Audit Trail
    event_log: Annotated[list[dict], add]
~~~

---

## 3. Detailed Node Specifications

### Node 1 — Geometry Analyst (`geometry_analyst`)
* **Model:** `gemini-3-pro` (Temperature: `0.1`, Multimodal Vision enabled).
* **Fallback Model:** `claude-sonnet-4-5`.
* **Input:** All 6 hand-masked views (`front`, `back`, `left`, `right`, `top`, `bottom`) + `Open3DGeometryReport` JSON.
* **Responsibility:** Reconcile visual details (blind vs. through-holes, chamfers, ribs, bosses, counterbores) with exact millimeter dimensions from Open3D. Explicitly resolve ambiguities where depth noise occurred on reflective/dark surfaces.
* **System Prompt Directives:**
  * Treat `Open3DGeometryReport.bounding_box_mm` and high-confidence cylinder radii ($\text{confidence} \ge 0.75$) as primary dimensional ground truth.
  * Identify exact symmetry planes (`XY`, `YZ`, `XZ`) to simplify downstream CAD code.
  * Output a concise, structured engineering specification in millimeters (`mm`)—never inches.

### Node 2 — Parametric Architect (`parametric_architect`)
* **Model:** `gemini-3-pro` (or `claude-sonnet-4-5`, Temperature: `0.1`, Structured Output enforced via Pydantic `CSGFeatureTree`).
* **Input:** `spatial_analysis`, `Open3DGeometryReport`, optional `validation_metrics.discrepancy_notes` (on Outer Loop iterations), and optional `user_edit_instruction` (on `/refine` runs).
* **Responsibility:** Translate the geometric inventory into a clean, top-down **Constructive Solid Geometry / B-Rep feature tree** (`CSGFeatureTree`):
  1. Define top-level named parameters (`global_parameters_mm`, e.g., `base_length`, `wall_thickness`, `hole_diameter`).
  2. Order operations cleanly: *Primary Base Extrusion/Revolve* $\rightarrow$ *Secondary Bosses/Cutouts* $\rightarrow$ *Hole Patterns* $\rightarrow$ *Fillets & Chamfers LAST* (prevents topological naming failures in OpenCascade).

### Node 3 — CAD Code Synthesizer (`cad_synthesizer`)
* **Model:** `claude-sonnet-4-5` (Temperature: `0.0` on attempt 0; `0.15` on retries).
* **Fallback Model:** `gemini-3-pro`.
* **RAG Retrieval Step:** Before invoking the LLM, embed the required operations from `feature_tree.steps` and query Supabase `build123d_doc_chunks` (`top_k = 6`, cosine similarity $\ge 0.72$).
* **Responsibility:** Emit a single, self-contained, deterministic Python script using **`build123d`** builder mode (`with BuildPart() as part:`).
* **Strict Output Contract:**
  * Every key dimension must be declared as a named uppercase constant in millimeters at the top of the script.
  * Must assign the final solid to a variable named `RESULT_PART` (`Solid` or `Compound`).
  * Must NOT include `export_step()` or file I/O calls—the Sandbox Runner appends standardized export commands after verifying `RESULT_PART.is_valid()`.
  * On Inner Loop retries, inspect `compile_error_trace` and fix the exact OpenCascade/Python error without dropping existing valid features.

### Node 4 — Deterministic Sandbox Executor (`sandbox_executor`)
* **Type:** Non-LLM Deterministic Tool Node (Modal gVisor Sandbox).
* **Execution Steps:**
  1. Run Python `ast.parse()` static security filter (block unauthorized imports, filesystem I/O, `eval`/`exec`).
  2. Execute `current_code` with $30\text{ s}$ timeout and $2\text{ GB}$ RAM cap.
  3. Assert `RESULT_PART` exists, `RESULT_PART.is_valid()` is `True`, and `RESULT_PART.volume > 0`.
  4. Export `model.step` (AP214), `model.stl` (linear deflection $0.05\text{ mm}$), and `model.dxf` (3-view orthographic projection) to `/tmp/out`.
  5. Upload temporary artifacts to R2 staging prefix.
* **On Failure:** Capture exact traceback (trimmed to last 40 lines), increment `compile_retries`, and route back to **Node 3**.

### Node 5 — Geometric Validator (`geometric_validator`)
* **Type:** Hybrid Deterministic (Open3D) + Optional VLM Judge.
* **Execution Steps:**
  1. Uniformly sample $N = 20{,}000$ surface points from the compiled `model.stl` mesh.
  2. Align sampled mesh points against the fused Open3D scan point cloud via fine ICP (bounded within $5\text{ mm}$ translation to prevent false shifts).
  3. Compute bidirectional **Chamfer Distance**:
     $$d_{\text{CD}}(P, Q) = \frac{1}{|P|}\sum_{p \in P}\min_{q \in Q}\|p - q\|_2 + \frac{1}{|Q|}\sum_{q \in Q}\min_{p \in P}\|q - p\|_2$$
  4. Compute mean surface error, 95th-percentile error ($P_{95}$), and axis-aligned bounding box delta $(\Delta X, \Delta Y, \Delta Z)$.
  5. If `chamfer_mean_mm < best_chamfer_mm`, update `best_code`, `best_chamfer_mm`, and `best_artifact_keys`.
  6. If `chamfer_mean_mm > 1.0`: generate localized `discrepancy_notes` (e.g., *"Top Z-face is $+2.4\text{ mm}$ taller than scanned cloud; missing cutout on `-X` face"*), increment `geometry_iterations`, reset `compile_retries = 0`, and route back to **Node 2**.

---

## 4. Routing Rules & Circuit Breakers

| Condition | Next Node | Guardrail Action |
| :--- | :--- | :--- |
| Node 4 fails AND `compile_retries < 3` | `cad_synthesizer` (Node 3) | Pass full Python/OCP traceback for self-healing. |
| Node 4 fails AND `compile_retries >= 3` | `END` (or fallback to `best_code` if exists) | If `geometry_iterations > 0` and a prior valid solid exists, return `best_artifact_keys` with warning; otherwise emit `pipeline_failed`. |
| Node 5 passes (`chamfer_mean_mm <= 1.0` AND `is_watertight`) | `END` | Promote artifacts to permanent R2 path and emit `pipeline_completed`. |
| Node 5 fails tolerance AND `geometry_iterations < 3` | `parametric_architect` (Node 2) | Pass spatial error vectors (`discrepancy_notes`) for dimensional refinement. |
| Node 5 fails tolerance AND `geometry_iterations >= 3` | `END` | Publish lowest-error `best_artifact_keys` with status `completed_with_warning`. |

---

## 5. Checkpointing, Parametric Editing & Observability

* **Checkpointing (`langgraph-checkpoint-redis` v0.6+):**
  * Persists full graph state keyed by `thread_id = scan_projects.langgraph_thread_id` with a `default_ttl = 10080` minutes (7 days, refreshed on read).
  * **Fallback:** If Redis lacks `RediSearch`/`RedisJSON`, use `langgraph-checkpoint-postgres` (`AsyncPostgresSaver`) against Supabase.
* **Conversational Parametric Edits (`/refine`):**
  * Loads the existing checkpoint for `thread_id`, updates `user_edit_instruction`, resets `compile_retries = 0` and `geometry_iterations = 0`, and enters directly at **Node 2 (`parametric_architect`)**, bypassing CV fusion and Node 1 entirely for $< 15\text{ s}$ turnaround.
* **Observability (LangSmith / Langfuse):**
  * Every graph invocation tags runs with `scan_id`, `user_id`, `iteration`, `chamfer_mean_mm`, and `model_provider`.
  * Failed compilations and high-Chamfer runs are automatically flagged into a review queue to expand the `build123d` RAG index and Golden Dataset.
