"""
PhotoCAD - CAD Ecosystem Interoperability Verifier (.STEP / .DXF / .STL)
Document ID: PCAD-PRD-SRS-001 (NFR-06) / Phase 5 Deliverable 2

Performs automated structural, referential, unit-scale (1:1 mm), and 2-manifold topology
verification of exported CAD packages to ensure seamless import into:
- Autodesk AutoCAD (.STEP AP214 & .DXF $INSUNITS=4 mm)
- Autodesk Fusion 360 (.STEP AP214 & .DXF)
- Dassault SOLIDWORKS (.STEP AP214 & .STL)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
from pydantic import BaseModel

from app.cad.chamfer_validator import check_mesh_watertight_and_props, load_ascii_stl_triangles


class StepInteropResult(BaseModel):
    valid: bool
    schema_protocol: str
    units_millimeters: bool
    has_closed_shell: bool
    has_manifold_solid: bool
    entity_count: int
    dangling_references: List[int]
    bounding_box_mm: Tuple[float, float, float]
    issues: List[str]


class DxfInteropResult(BaseModel):
    valid: bool
    acad_version: str
    insunits_mm: bool
    has_geometry_layer: bool
    line_count: int
    circle_count: int
    issues: List[str]


class StlInteropResult(BaseModel):
    valid: bool
    is_watertight: bool
    triangle_count: int
    volume_mm3: float
    surface_area_mm2: float
    bounding_box_mm: Tuple[float, float, float]
    issues: List[str]


class InteropReport(BaseModel):
    autocad_compatible: bool
    fusion360_compatible: bool
    solidworks_compatible: bool
    step: StepInteropResult
    dxf: DxfInteropResult
    stl: StlInteropResult


class InteropVerifier:
    """Validates ISO 10303-21 .STEP, AutoCAD .DXF, and manifold .STL files."""

    @staticmethod
    def verify_step(step_path: str | Path) -> StepInteropResult:
        path = Path(step_path)
        if not path.exists():
            return StepInteropResult(
                valid=False,
                schema_protocol="missing",
                units_millimeters=False,
                has_closed_shell=False,
                has_manifold_solid=False,
                entity_count=0,
                dangling_references=[],
                bounding_box_mm=(0.0, 0.0, 0.0),
                issues=["STEP file does not exist."],
            )

        text = path.read_text(encoding="utf-8", errors="ignore")
        issues: List[str] = []

        if "ISO-10303-21;" not in text or "END-ISO-10303-21;" not in text:
            issues.append("Missing ISO-10303-21 header/footer sentinels.")

        schema_proto = "UNKNOWN"
        if "AUTOMOTIVE_DESIGN" in text:
            schema_proto = "AP214 (AUTOMOTIVE_DESIGN)"
        elif "CONFIG_CONTROL_DESIGN" in text:
            schema_proto = "AP203 (CONFIG_CONTROL_DESIGN)"
        else:
            issues.append("Unrecognized STEP FILE_SCHEMA.")

        units_mm = "SI_UNIT(.MILLI.,.METRE.)" in text.replace(" ", "")
        if not units_mm:
            issues.append("STEP lacks SI_UNIT(.MILLI.,.METRE.) 1:1 mm unit definition.")

        has_closed_shell = "CLOSED_SHELL" in text
        has_manifold_solid = "MANIFOLD_SOLID_BREP" in text
        if not has_closed_shell or not has_manifold_solid:
            issues.append("Missing CLOSED_SHELL or MANIFOLD_SOLID_BREP B-Rep solid entity.")

        # Referential integrity scan: check every `#id` reference exists in `#id=...;`
        data_start = text.find("DATA;")
        data_end = text.find("ENDSEC;", data_start if data_start >= 0 else 0)
        data_block = text[data_start:data_end] if data_start >= 0 and data_end > data_start else text

        defined_ids: Set[int] = {int(m) for m in re.findall(r"(?m)^#(\d+)\s*=", data_block)}
        referenced_ids: Set[int] = set()
        for line in data_block.splitlines():
            if "=" in line:
                rhs = line.split("=", 1)[1]
                for ref in re.findall(r"#(\d+)", rhs):
                    referenced_ids.add(int(ref))

        dangling = sorted(referenced_ids - defined_ids)
        if dangling:
            issues.append(f"Unresolved STEP entity references: {dangling[:10]}")

        # Extract CARTESIAN_POINT bounds to confirm millimeter dimensions
        pts = re.findall(r"CARTESIAN_POINT\([^,]*,\s*\(\s*([-0-9.eE+]+)\s*,\s*([-0-9.eE+]+)\s*,\s*([-0-9.eE+]+)\s*\)\s*\)", data_block)
        bbox = (0.0, 0.0, 0.0)
        if pts:
            arr = np.asarray([[float(a), float(b), float(c)] for a, b, c in pts], dtype=np.float64)
            ext = np.ptp(arr, axis=0)
            bbox = (round(float(ext[0]), 2), round(float(ext[1]), 2), round(float(ext[2]), 2))

        valid = len(issues) == 0 and len(defined_ids) >= 10
        return StepInteropResult(
            valid=valid,
            schema_protocol=schema_proto,
            units_millimeters=units_mm,
            has_closed_shell=has_closed_shell,
            has_manifold_solid=has_manifold_solid,
            entity_count=len(defined_ids),
            dangling_references=dangling,
            bounding_box_mm=bbox,
            issues=issues,
        )

    @staticmethod
    def verify_dxf(dxf_path: str | Path) -> DxfInteropResult:
        path = Path(dxf_path)
        if not path.exists():
            return DxfInteropResult(
                valid=False,
                acad_version="missing",
                insunits_mm=False,
                has_geometry_layer=False,
                line_count=0,
                circle_count=0,
                issues=["DXF file does not exist."],
            )

        lines = [line.strip() for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()]
        issues: List[str] = []

        if "SECTION" not in lines or "ENTITIES" not in lines or "EOF" not in lines:
            issues.append("DXF missing required SECTION/ENTITIES/EOF markers.")

        acad_ver = "UNKNOWN"
        insunits_mm = False
        has_geom_layer = "GEOMETRY" in lines
        line_count = 0
        circle_count = 0

        for idx, tok in enumerate(lines):
            if tok == "$ACADVER" and idx + 2 < len(lines) and lines[idx + 1] == "1":
                acad_ver = lines[idx + 2]
            elif tok == "$INSUNITS" and idx + 2 < len(lines) and lines[idx + 1] == "70":
                insunits_mm = lines[idx + 2] == "4"
            elif tok == "0" and idx + 1 < len(lines):
                ent = lines[idx + 1]
                if ent == "LINE":
                    line_count += 1
                elif ent == "CIRCLE":
                    circle_count += 1

        if not insunits_mm:
            issues.append("DXF $INSUNITS is not set to 4 (Millimeters).")
        if line_count < 4:
            issues.append(f"Expected >= 4 LINE entities for closed orthographic loops, found {line_count}.")

        return DxfInteropResult(
            valid=len(issues) == 0,
            acad_version=acad_ver,
            insunits_mm=insunits_mm,
            has_geometry_layer=has_geom_layer,
            line_count=line_count,
            circle_count=circle_count,
            issues=issues,
        )

    @staticmethod
    def verify_stl(stl_path: str | Path) -> StlInteropResult:
        path = Path(stl_path)
        if not path.exists():
            return StlInteropResult(
                valid=False,
                is_watertight=False,
                triangle_count=0,
                volume_mm3=0.0,
                surface_area_mm2=0.0,
                bounding_box_mm=(0.0, 0.0, 0.0),
                issues=["STL file does not exist."],
            )

        tris = load_ascii_stl_triangles(path)
        is_wt, vol, area = check_mesh_watertight_and_props(tris)
        issues: List[str] = []
        bbox = (0.0, 0.0, 0.0)

        if len(tris) < 12:
            issues.append("STL has too few triangles for a closed solid.")
        else:
            ext = np.ptp(tris.reshape(-1, 3), axis=0)
            bbox = (round(float(ext[0]), 2), round(float(ext[1]), 2), round(float(ext[2]), 2))

        if not is_wt:
            issues.append("STL mesh is non-manifold or has open boundary edges.")
        if vol <= 0.0:
            issues.append("STL signed volume <= 0 mm^3.")

        return StlInteropResult(
            valid=len(issues) == 0,
            is_watertight=is_wt,
            triangle_count=int(len(tris)),
            volume_mm3=vol,
            surface_area_mm2=area,
            bounding_box_mm=bbox,
            issues=issues,
        )

    @classmethod
    def verify_bundle(
        cls,
        step_path: str | Path,
        dxf_path: str | Path,
        stl_path: str | Path,
    ) -> InteropReport:
        step_res = cls.verify_step(step_path)
        dxf_res = cls.verify_dxf(dxf_path)
        stl_res = cls.verify_stl(stl_path)

        return InteropReport(
            autocad_compatible=step_res.valid and dxf_res.valid,
            fusion360_compatible=step_res.valid and dxf_res.valid,
            solidworks_compatible=step_res.valid and stl_res.valid,
            step=step_res,
            dxf=dxf_res,
            stl=stl_res,
        )
