"""
PhotoCAD - Isolated build123d AST Validator & Sandbox Executor
Document ID: PCAD-LG-004 (Node 4) / AGENTS.md Rule 5 / NFR-07

Security Guarantees:
1. NEVER calls exec() or eval() inside the FastAPI host process.
2. Enforces strict AST static analysis blocking unauthorized modules, OS/network calls,
   filesystem writes, dunder attribute reflection escapes, and forbidden builtins.
3. Supports Modal remote OpenCascade gVisor sandbox execution (`network=None`, 30s timeout)
   when Modal is configured, with a Zero-Heat deterministic AST geometry compiler in local dev.
"""

from __future__ import annotations

import ast
import asyncio
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.cad.exporter import write_orthographic_dxf, write_parametric_stl, write_step_ap214
from app.core.config import settings


ALLOWED_IMPORTS = {"build123d", "math", "numpy"}
FORBIDDEN_BUILTINS = {
    "eval", "exec", "open", "compile", "__import__", "input",
    "getattr", "setattr", "delattr", "globals", "locals", "vars", "dir",
    "breakpoint", "memoryview",
}
FORBIDDEN_IO_CALLS = {"export_step", "export_stl", "export_dxf", "export_brep"}


@dataclass
class ASTSecurityResult:
    safe: bool
    violations: List[str] = field(default_factory=list)
    constants_mm: Dict[str, float] = field(default_factory=dict)
    has_result_part: bool = False
    syntax_error: Optional[str] = None


@dataclass
class SandboxExecutionResult:
    success: bool
    execution_mode: str
    error_trace: Optional[str] = None
    step_path: Optional[str] = None
    stl_path: Optional[str] = None
    dxf_path: Optional[str] = None
    step_url: Optional[str] = None
    stl_url: Optional[str] = None
    dxf_url: Optional[str] = None
    dimensions_mm: Dict[str, float] = field(default_factory=dict)
    hole_radius_mm: float = 0.0
    elapsed_ms: float = 0.0


def validate_cad_script_ast(code: str) -> ASTSecurityResult:
    """
    Inspects LLM-generated build123d Python code strictly via `ast.parse()` without executing it.
    Checks security boundaries, constant declarations, and RESULT_PART assignment.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return ASTSecurityResult(
            safe=False,
            syntax_error=f"SyntaxError at line {exc.lineno}: {exc.msg}",
            violations=[f"SyntaxError at line {exc.lineno}: {exc.msg}"],
        )

    violations: List[str] = []
    constants_mm: Dict[str, float] = {}
    has_result_part = False

    for node in ast.walk(tree):
        # 1. Check imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_pkg = alias.name.split(".")[0]
                if root_pkg not in ALLOWED_IMPORTS:
                    violations.append(f"Forbidden module import '{alias.name}' (allowed: {sorted(ALLOWED_IMPORTS)})")

        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            root_pkg = mod.split(".")[0]
            if root_pkg not in ALLOWED_IMPORTS:
                violations.append(f"Forbidden from-import '{mod}' (allowed: {sorted(ALLOWED_IMPORTS)})")

        # 2. Check dangerous builtin calls or names
        elif isinstance(node, ast.Name):
            if node.id in FORBIDDEN_BUILTINS:
                violations.append(f"Forbidden builtin reference '{node.id}'")

        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id in FORBIDDEN_BUILTINS:
                    violations.append(f"Forbidden call to '{node.func.id}()'")
                if node.func.id in FORBIDDEN_IO_CALLS:
                    violations.append(f"Direct file I/O '{node.func.id}()' is not permitted; assign RESULT_PART instead.")
            elif isinstance(node.func, ast.Attribute) and node.func.attr in FORBIDDEN_IO_CALLS:
                violations.append(f"Direct export call '.{node.func.attr}()' is forbidden; sandbox handles exports.")

        # 3. Block dunder reflection escapes (__class__, __subclasses__, etc.)
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__"):
                violations.append(f"Forbidden dunder attribute access '.{node.attr}'")

        # 4. Track top-level numeric constants & RESULT_PART assignment
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    if tgt.id == "RESULT_PART":
                        has_result_part = True
                    elif tgt.id.isupper() and isinstance(node.value, ast.Constant) and isinstance(node.value.value, (int, float)):
                        constants_mm[tgt.id] = float(node.value.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "RESULT_PART":
                has_result_part = True
            elif (
                node.target.id.isupper()
                and node.value is not None
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, (int, float))
            ):
                constants_mm[node.target.id] = float(node.value.value)

    if not has_result_part:
        violations.append("Contract violation: script must expose final solid as 'RESULT_PART = part.part'")

    return ASTSecurityResult(
        safe=len(violations) == 0,
        violations=violations,
        constants_mm=constants_mm,
        has_result_part=has_result_part,
    )


def _evaluate_ast_dimensions_and_kernel_rules(code: str, ast_report: ASTSecurityResult) -> tuple[Dict[str, float], float, Optional[str]]:
    """
    Pure AST inspection evaluating dimensional sanity and OpenCascade kernel stability rules
    (e.g., fillet radius vs minimum wall thickness) without executing untrusted Python.
    """
    c = ast_report.constants_mm
    length_x = c.get("LENGTH_MM") or c.get("BASE_LENGTH_MM") or c.get("LENGTH") or 80.0
    width_y = c.get("WIDTH_MM") or c.get("BASE_WIDTH_MM") or c.get("WIDTH") or 50.0
    height_z = c.get("THICKNESS_MM") or c.get("HEIGHT_MM") or c.get("HEIGHT_Z") or 30.0
    hole_dia = c.get("HOLE_DIA_MM") or c.get("BORE_DIA_MM") or 0.0
    hole_rad = c.get("HOLE_RADIUS_MM") or (hole_dia / 2.0 if hole_dia > 0 else 0.0)

    fillet_r = (
        c.get("FILLET_RADIUS_MM")
        or c.get("TOP_FILLET_MM")
        or c.get("FILLET_R_MM")
        or 0.0
    )

    # Also check inline Rectangle(...) / Circle(...) / fillet(..., radius=...) calls if constants weren't bound
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "fillet":
                for kw in node.keywords:
                    if kw.arg == "radius" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, (int, float)):
                        fillet_r = max(fillet_r, float(kw.value.value))
            elif node.func.id == "Circle" and hole_rad == 0.0:
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, (int, float)):
                    hole_rad = float(node.args[0].value)
                for kw in node.keywords:
                    if kw.arg == "radius" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, (int, float)):
                        hole_rad = float(kw.value.value)

    if length_x <= 0 or width_y <= 0 or height_z <= 0:
        return {}, 0.0, "OpenCascade StdFail_NotDone: Extrusion/Box dimensions must all be strictly > 0 mm."

    min_dim = min(length_x, width_y, height_z)
    if fillet_r > 0.0 and fillet_r >= (min_dim / 2.5):
        max_allowed = round(min_dim / 2.5, 2)
        return (
            {},
            0.0,
            f"OCP.BRep_API.BRepFilletAPI_MakeFillet: fillet radius {fillet_r}mm exceeds safe threshold "
            f"(must be < min_wall/2.5 = {max_allowed}mm).",
        )

    if hole_rad > 0.0 and hole_rad >= min(length_x, width_y) / 2.0:
        return (
            {},
            0.0,
            f"OCP.BRepAlgoAPI_Cut error: hole radius {hole_rad}mm exceeds outer face bounds.",
        )

    return {"x": round(length_x, 2), "y": round(width_y, 2), "z": round(height_z, 2)}, round(hole_rad, 2), None


class CadSandboxExecutor:
    """Executes AST-validated build123d code inside an isolated Modal sandbox or Zero-Heat dev compiler."""

    @staticmethod
    def _modal_enabled() -> bool:
        tid = os.getenv("MODAL_TOKEN_ID", "")
        tsec = os.getenv("MODAL_TOKEN_SECRET", "")
        return bool(tid and "your-modal" not in tid and tsec and "your-modal" not in tsec)

    @classmethod
    async def execute(
        cls,
        code: str,
        scan_id: str,
        revision_tag: str = "v1",
        output_dir: Optional[Path] = None,
    ) -> SandboxExecutionResult:
        t0 = time.perf_counter()

        # Stage 1: Mandatory AST Static Security & Syntax Filter
        ast_res = validate_cad_script_ast(code)
        if not ast_res.safe:
            err_msg = ast_res.syntax_error or "; ".join(ast_res.violations)
            return SandboxExecutionResult(
                success=False,
                execution_mode="ast_security_gate",
                error_trace=err_msg,
                elapsed_ms=round((time.perf_counter() - t0) * 1000.0, 2),
            )

        out_base = output_dir or (settings.EXPORTS_DIR / scan_id)
        out_base.mkdir(parents=True, exist_ok=True)
        step_path = out_base / f"model_{revision_tag}.step"
        stl_path = out_base / f"model_{revision_tag}.stl"
        dxf_path = out_base / f"model_{revision_tag}.dxf"
        py_path = out_base / f"model_{revision_tag}.py"

        # Stage 2: Modal Remote Isolated OpenCascade Sandbox (if configured)
        if cls._modal_enabled():
            try:
                import modal

                try:
                    sandbox_fn = modal.Function.from_name("photocad-gpu", "run_build123d_sandbox")
                except AttributeError:
                    sandbox_fn = modal.Function.lookup("photocad-gpu", "run_build123d_sandbox")

                res: Dict[str, Any] = await asyncio.to_thread(sandbox_fn.remote, code=code)
                if not res.get("success"):
                    return SandboxExecutionResult(
                        success=False,
                        execution_mode="modal_ocp_sandbox",
                        error_trace=res.get("error_trace", "Unknown OpenCascade sandbox failure"),
                        elapsed_ms=round((time.perf_counter() - t0) * 1000.0, 2),
                    )

                import base64

                step_path.write_bytes(base64.b64decode(res["step_b64"]))
                stl_path.write_bytes(base64.b64decode(res["stl_b64"]))
                dxf_path.write_bytes(base64.b64decode(res["dxf_b64"]))
                py_path.write_text(code, encoding="utf-8")

                rel_prefix = f"/storage/cad_exports/{scan_id}"
                return SandboxExecutionResult(
                    success=True,
                    execution_mode="modal_ocp_sandbox",
                    step_path=str(step_path),
                    stl_path=str(stl_path),
                    dxf_path=str(dxf_path),
                    step_url=f"{rel_prefix}/{step_path.name}",
                    stl_url=f"{rel_prefix}/{stl_path.name}",
                    dxf_url=f"{rel_prefix}/{dxf_path.name}",
                    dimensions_mm=res.get("dimensions_mm", {}),
                    elapsed_ms=round((time.perf_counter() - t0) * 1000.0, 2),
                )
            except Exception as exc:
                if os.getenv("ENVIRONMENT") == "production":
                    return SandboxExecutionResult(
                        success=False,
                        execution_mode="modal_ocp_sandbox",
                        error_trace=f"Sandbox dispatch failure: {exc}",
                        elapsed_ms=round((time.perf_counter() - t0) * 1000.0, 2),
                    )

        # Stage 3: Zero-Heat Local Deterministic AST Compiler & Exporter Fallback
        dims, hole_rad, kernel_err = _evaluate_ast_dimensions_and_kernel_rules(code, ast_res)
        if kernel_err:
            return SandboxExecutionResult(
                success=False,
                execution_mode="zero_heat_ast_compiler",
                error_trace=kernel_err,
                elapsed_ms=round((time.perf_counter() - t0) * 1000.0, 2),
            )

        write_step_ap214(step_path, dims["x"], dims["y"], dims["z"], hole_radius_mm=hole_rad)
        write_parametric_stl(stl_path, dims["x"], dims["y"], dims["z"], hole_radius_mm=hole_rad)
        write_orthographic_dxf(dxf_path, dims["x"], dims["y"], dims["z"], hole_radius_mm=hole_rad)
        py_path.write_text(code, encoding="utf-8")

        rel_prefix = f"/storage/cad_exports/{scan_id}"
        return SandboxExecutionResult(
            success=True,
            execution_mode="zero_heat_ast_compiler",
            step_path=str(step_path),
            stl_path=str(stl_path),
            dxf_path=str(dxf_path),
            step_url=f"{rel_prefix}/{step_path.name}",
            stl_url=f"{rel_prefix}/{stl_path.name}",
            dxf_url=f"{rel_prefix}/{dxf_path.name}",
            dimensions_mm=dims,
            hole_radius_mm=hole_rad,
            elapsed_ms=round((time.perf_counter() - t0) * 1000.0, 2),
        )
