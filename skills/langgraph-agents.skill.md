# LangGraph Agents Skill (`langgraph-agents.skill.md`)

> **Scope:** Apply these architectural guardrails whenever writing, modifying, or testing `backend/app/agents/` and `backend/app/cad/`.

---

## 1. Dual-Loop Cyclic Graph Topology (`PCAD-LG-004`)
1. **Node 1 (`geometry_analyst`):** Reconciles the 6 hand-masked views with `Open3DGeometryReport` (`bounding_box_mm`, `planes`, `cylinders`, `symmetry_planes`).
2. **Node 2 (`parametric_architect`):** Translates spatial inventory, optional `validation_metrics.discrepancy_notes`, or `/refine` edits into a deterministic `CSGFeatureTree` Pydantic ADT using structured outputs.
3. **Node 3 (`cad_synthesizer`):** Retrieves curated `build123d` chunks via RAG (`Build123dRAGService`) and synthesizes self-contained Python `build123d` code assigning `RESULT_PART`.
4. **Node 4 (`sandbox_executor` — Inner Self-Healing Loop):** Validates code via `ast.parse()` static security scanner, executes in an isolated sandbox, and exports `.STEP`, `.STL`, `.DXF`. Syntax or kernel failures route back to Node 3 with trimmed traceback up to `compile_retries <= 3`.
5. **Node 5 (`geometric_validator` — Outer Accuracy Loop):** Samples $N = 20{,}000$ triangles from compiled mesh and computes bidirectional Chamfer Distance against the fused scan. If `chamfer_mean_mm > 1.0`, routes back to Node 2 with spatial discrepancy notes up to `geometry_iterations <= 3`.

---

## 2. Hard Safety & Reliability Rules
1. **Structured Outputs Only:** Never parse free-form markdown from Node 1 or Node 2 with regex. Always bind Pydantic models (`CSGFeatureTree`, `SpatialAnalysisReport`).
2. **Loop Caps & Circuit Breakers:** Enforce `compile_retries <= 3`, `geometry_iterations <= 3`, and invoke compiled graphs with `recursion_limit=20`.
3. **Zero Host `exec()`/`eval()`:** All generated CAD code must pass AST security filtering and run inside `backend/app/cad/sandbox.py` (blocking `os`, `sys`, `subprocess`, `socket`, `open`, `eval`, `exec`, `__import__`).
4. **Best-Effort Tracking:** Always retain the lowest-Chamfer valid solid inside `state["best_code"]`, `state["best_chamfer_mm"]`, and `state["best_artifact_keys"]`.
5. **Real-Time Parity:** Stream typed node transitions, compile errors, code diffs, and Chamfer scores over WebSockets (`PCAD-API-ADT-003`).
