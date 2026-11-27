# CAD Kernel Skill (`cad-kernel.skill.md`)

> **Scope:** Apply these rules whenever writing, validating, or prompting `build123d` / OpenCascade B-Rep synthesis scripts in `backend/app/cad/`, `backend/app/agents/`, or RAG fixtures.

---

## 1. Precision & Unit Rules
1. **Strict 1:1 Millimeter Units (`mm`):** Every dimensional value in scripts, ADTs, and exports represents millimeters. Never convert to inches or meters inside CAD generation scripts.
2. **Uppercase Parametric Constants Header:** Declare all critical design dimensions (`LENGTH_MM`, `WIDTH_MM`, `THICKNESS_MM`, `HOLE_DIA_MM`, `FILLET_R_MM`) as named uppercase float constants at the top of the script so downstream `/refine` edits are clean and diffable.

## 2. Builder Mode Construction Order
1. **Prefer `build123d` Context Managers:** Use `with BuildPart() as part:` and `with BuildSketch():` rather than legacy CadQuery fluent chaining.
2. **Topological Stability Sequence:**
   - Step 1: Primary Base Solid (`extrude`, `revolve`).
   - Step 2: Secondary Bosses / Structural Ribs.
   - Step 3: Cutouts and Hole Patterns (`mode=Mode.SUBTRACT`).
   - Step 4: **Fillets and Chamfers LAST** (guards against OpenCascade `BRep_API` self-intersection failures). Guard edge fillet radii with `radius < min_adjacent_thickness / 2.5`.

## 3. Sandbox & Verification Contract
1. **Exposed Solid Variable:** Every generated script must assign its final B-Rep solid to `RESULT_PART = part.part` and assert `RESULT_PART.is_valid()`.
2. **No File I/O Inside LLM Code:** Synthesized code must never import `os`, `sys`, `subprocess`, or call `export_step()` directly. Export serialization is controlled strictly by the isolated sandbox runner (`backend/app/cad/sandbox.py`).
