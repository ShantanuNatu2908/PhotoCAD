"""
Security & Compilation Unit Tests for Isolated CAD Sandbox & B-Rep Exporters
Document ID: PCAD-LG-004 (Node 4) / NFR-07
"""

from __future__ import annotations

import asyncio
from collections import Counter
from pathlib import Path

from app.cad.exporter import build_manifold_prism_triangles
from app.cad.sandbox import CadSandboxExecutor, validate_cad_script_ast


def test_ast_security_blocks_malicious_imports_and_builtins():
    malicious_scripts = [
        "import os\nos.system('rm -rf /')\nRESULT_PART = None",
        "from subprocess import Popen\nRESULT_PART = None",
        "import socket\nRESULT_PART = None",
        "eval('__import__(\"os\")')\nRESULT_PART = None",
        "x = ().__class__.__bases__[0].__subclasses__()\nRESULT_PART = None",
        "open('/etc/passwd', 'r').read()\nRESULT_PART = None",
    ]

    for script in malicious_scripts:
        res = validate_cad_script_ast(script)
        assert res.safe is False, f"Security gate failed to block: {script}"
        assert len(res.violations) >= 1


def test_ast_requires_result_part_and_blocks_syntax_errors():
    missing_target = """
from build123d import BuildPart, Box
with BuildPart() as part:
    Box(40.0, 20.0, 10.0)
"""
    res = validate_cad_script_ast(missing_target)
    assert res.safe is False
    assert any("RESULT_PART" in v for v in res.violations)

    bad_syntax = "with BuildPart() as part:\n    Box(40.0, 20.0\nRESULT_PART = part.part"
    syn_res = validate_cad_script_ast(bad_syntax)
    assert syn_res.safe is False
    assert syn_res.syntax_error is not None


def test_sandbox_catches_fillet_radius_crash_for_self_healing():
    # Fillet 12.0mm exceeds safe wall threshold (min(80, 50, 10)/2.5 = 4.0mm)
    oversized_fillet_script = """
from build123d import BuildPart, BuildSketch, Rectangle, extrude, fillet, Axis

LENGTH_MM = 80.0
WIDTH_MM = 50.0
THICKNESS_MM = 10.0
TOP_FILLET_MM = 12.0

with BuildPart() as part:
    with BuildSketch():
        Rectangle(LENGTH_MM, WIDTH_MM)
    extrude(amount=THICKNESS_MM)
    fillet(part.edges().filter_by(Axis.Z), radius=TOP_FILLET_MM)

RESULT_PART = part.part
"""
    exec_res = asyncio.run(CadSandboxExecutor.execute(oversized_fillet_script, scan_id="test_fillet_fail"))
    assert exec_res.success is False
    assert "BRepFilletAPI" in (exec_res.error_trace or "")


def test_sandbox_compiles_valid_script_and_exports_watertight_artifacts(tmp_path: Path):
    valid_script = """
from build123d import BuildPart, BuildSketch, Rectangle, Circle, Mode, Axis, extrude, fillet

LENGTH_MM = 80.0
WIDTH_MM = 50.0
THICKNESS_MM = 30.0
HOLE_DIA_MM = 16.0
TOP_FILLET_MM = 2.5

with BuildPart() as part:
    with BuildSketch():
        Rectangle(LENGTH_MM, WIDTH_MM)
    extrude(amount=THICKNESS_MM)
    with BuildSketch(part.faces().sort_by(Axis.Z)[-1]):
        Circle(HOLE_DIA_MM / 2.0)
    extrude(amount=-THICKNESS_MM, mode=Mode.SUBTRACT)
    fillet(part.edges().filter_by(Axis.Z), radius=TOP_FILLET_MM)

RESULT_PART = part.part
"""
    res = asyncio.run(
        CadSandboxExecutor.execute(valid_script, scan_id="test_valid_01", output_dir=tmp_path)
    )
    assert res.success is True
    assert res.dimensions_mm == {"x": 80.0, "y": 50.0, "z": 30.0}
    assert res.hole_radius_mm == 8.0

    assert Path(res.step_path).read_text(encoding="utf-8").startswith("ISO-10303-21;")
    assert "endsolid" in Path(res.stl_path).read_text(encoding="utf-8")
    assert "$INSUNITS" in Path(res.dxf_path).read_text(encoding="utf-8")

    # Verify generated mesh topology is strictly manifold & watertight (every undirected edge has degree 2)
    tris = build_manifold_prism_triangles(80.0, 50.0, 30.0, hole_radius_mm=8.0)
    directed_edges = Counter()
    for v0, v1, v2 in tris:
        for a, b in [(v0, v1), (v1, v2), (v2, v0)]:
            ka = tuple(round(x, 5) for x in a)
            kb = tuple(round(x, 5) for x in b)
            directed_edges[(ka, kb)] += 1

    assert len(directed_edges) > 0
    for (a, b), cnt in directed_edges.items():
        assert cnt == 1, f"Duplicate half-edge {(a, b)}"
        assert directed_edges[(b, a)] == 1, f"Open/non-manifold edge {(a, b)}"
