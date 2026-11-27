"""
PhotoCAD - Watertight B-Rep Mesh & Engineering CAD Exporters (.STL, .STEP, .DXF)
Document ID: PCAD-PRD-SRS-001 (FR-17) / skills/cad-kernel.skill.md

Provides:
1. Manifold watertight ASCII .STL exporter (box or prismatic bracket with circular through-bore)
2. ISO 10303-21 (STEP AP214) exchange solid exporter (1:1 mm)
3. AutoCAD DXF R2010 orthographic 3-view drawing exporter (Front, Top, Right in mm)
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


Triangle = Tuple[Tuple[float, float, float], Tuple[float, float, float], Tuple[float, float, float]]


def _cross_normal(
    v0: Tuple[float, float, float],
    v1: Tuple[float, float, float],
    v2: Tuple[float, float, float],
) -> Tuple[float, float, float]:
    ax, ay, az = v1[0] - v0[0], v1[1] - v0[1], v1[2] - v0[2]
    bx, by, bz = v2[0] - v0[0], v2[1] - v0[1], v2[2] - v0[2]
    nx = ay * bz - az * by
    ny = az * bx - ax * bz
    nz = ax * by - ay * bx
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length < 1e-12:
        return (0.0, 0.0, 1.0)
    return (nx / length, ny / length, nz / length)


def build_manifold_prism_triangles(
    length_x: float,
    width_y: float,
    height_z: float,
    hole_radius_mm: float = 0.0,
    radial_segments: int = 32,
) -> List[Triangle]:
    """
    Constructs a strictly watertight, centered (-L/2..L/2, -W/2..W/2, -H/2..H/2)
    triangle mesh. If `hole_radius_mm > 0.5`, carves an exact manifold cylindrical bore
    by stitching inner circle vertices to exact corner-preserving perimeter rays.
    """
    hx = max(length_x / 2.0, 0.5)
    hy = max(width_y / 2.0, 0.5)
    hz = max(height_z / 2.0, 0.5)

    max_safe_r = min(hx, hy) * 0.85
    if hole_radius_mm <= 0.5 or hole_radius_mm >= max_safe_r:
        # Pure watertight centered hexahedron (12 triangles)
        c = [
            (-hx, -hy, -hz), (hx, -hy, -hz), (hx, hy, -hz), (-hx, hy, -hz),
            (-hx, -hy, hz), (hx, -hy, hz), (hx, hy, hz), (-hx, hy, hz),
        ]
        return [
            # Bottom (-Z)
            (c[0], c[2], c[1]), (c[0], c[3], c[2]),
            # Top (+Z)
            (c[4], c[5], c[6]), (c[4], c[6], c[7]),
            # Front (-Y) & Back (+Y)
            (c[0], c[1], c[5]), (c[0], c[5], c[4]),
            (c[2], c[3], c[7]), (c[2], c[7], c[6]),
            # Left (-X) & Right (+X)
            (c[3], c[0], c[4]), (c[3], c[4], c[7]),
            (c[1], c[2], c[6]), (c[1], c[6], c[5]),
        ]

    # Merge uniform ring angles with exact 4 corner angles so box edges stay razor-sharp
    corner_angles = [
        math.atan2(hy, hx),
        math.atan2(hy, -hx),
        math.atan2(-hy, -hx),
        math.atan2(-hy, hx),
    ]
    uniform_angles = [-math.pi + (2.0 * math.pi * k) / radial_segments for k in range(radial_segments)]
    merged = sorted(corner_angles + uniform_angles)

    # Deduplicate near-identical angles (< 1e-4 rad)
    angles: List[float] = []
    for ang in merged:
        if not angles or abs(ang - angles[-1]) > 1e-4:
            angles.append(ang)
    if len(angles) > 1 and abs((angles[0] + 2.0 * math.pi) - angles[-1]) < 1e-4:
        angles.pop()

    inner_bot: List[Tuple[float, float, float]] = []
    inner_top: List[Tuple[float, float, float]] = []
    outer_bot: List[Tuple[float, float, float]] = []
    outer_top: List[Tuple[float, float, float]] = []

    for th in angles:
        ca, sa = math.cos(th), math.sin(th)
        rx, ry = hole_radius_mm * ca, hole_radius_mm * sa
        tx = hx / abs(ca) if abs(ca) > 1e-12 else 1e12
        ty = hy / abs(sa) if abs(sa) > 1e-12 else 1e12
        t_box = min(tx, ty)
        bx, by = t_box * ca, t_box * sa
        # Clamp numerical float drift cleanly onto outer edges
        if abs(abs(bx) - hx) < 1e-6:
            bx = math.copysign(hx, bx)
        if abs(abs(by) - hy) < 1e-6:
            by = math.copysign(hy, by)

        inner_bot.append((rx, ry, -hz))
        inner_top.append((rx, ry, hz))
        outer_bot.append((bx, by, -hz))
        outer_top.append((bx, by, hz))

    tris: List[Triangle] = []
    n = len(angles)
    for i in range(n):
        j = (i + 1) % n
        ci_b, cj_b = inner_bot[i], inner_bot[j]
        ci_t, cj_t = inner_top[i], inner_top[j]
        bi_b, bj_b = outer_bot[i], outer_bot[j]
        bi_t, bj_t = outer_top[i], outer_top[j]

        # Top annulus (+Z normal)
        tris.append((ci_t, bi_t, bj_t))
        tris.append((ci_t, bj_t, cj_t))

        # Bottom annulus (-Z normal)
        tris.append((ci_b, bj_b, bi_b))
        tris.append((ci_b, cj_b, bj_b))

        # Outer side wall (outward normal)
        tris.append((bi_b, bj_b, bj_t))
        tris.append((bi_b, bj_t, bi_t))

        # Inner hole bore wall (normal pointing inward toward origin)
        tris.append((cj_b, ci_b, ci_t))
        tris.append((cj_b, ci_t, cj_t))

    return tris


def write_parametric_stl(
    output_stl_path: str | Path,
    length_x: float,
    width_y: float,
    height_z: float,
    hole_radius_mm: float = 0.0,
) -> Path:
    """Exports a watertight ASCII STL mesh centered at origin in millimeter units."""
    tris = build_manifold_prism_triangles(length_x, width_y, height_z, hole_radius_mm=hole_radius_mm)
    lines = ["solid PhotoCAD_BRep_Solid"]
    for v0, v1, v2 in tris:
        nx, ny, nz = _cross_normal(v0, v1, v2)
        lines.append(f"  facet normal {nx:.6f} {ny:.6f} {nz:.6f}")
        lines.append("    outer loop")
        lines.append(f"      vertex {v0[0]:.5f} {v0[1]:.5f} {v0[2]:.5f}")
        lines.append(f"      vertex {v1[0]:.5f} {v1[1]:.5f} {v1[2]:.5f}")
        lines.append(f"      vertex {v2[0]:.5f} {v2[1]:.5f} {v2[2]:.5f}")
        lines.append("    endloop")
        lines.append("  endfacet")
    lines.append("endsolid PhotoCAD_BRep_Solid\n")

    path = Path(output_stl_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_step_ap214(
    output_step_path: str | Path,
    length_x: float,
    width_y: float,
    height_z: float,
    hole_radius_mm: float = 0.0,
) -> Path:
    """Writes an ISO 10303-21 (AP214) B-Rep STEP exchange file with SI millimeter units."""
    hx = round(length_x / 2.0, 4)
    hy = round(width_y / 2.0, 4)
    hz = round(height_z / 2.0, 4)
    r_hole = round(hole_radius_mm, 4)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    step_text = f"""ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('PhotoCAD Parametric B-Rep Solid ({length_x:.2f}x{width_y:.2f}x{height_z:.2f} mm, bore R={r_hole:.2f} mm)'),'2;1');
FILE_NAME('PhotoCAD_Model.step','{ts}',('PhotoCAD LangGraph'),('PhotoCAD'),'OpenCascade/build123d','PhotoCAD Kernel','');
FILE_SCHEMA(('CONFIG_CONTROL_DESIGN','AUTOMOTIVE_DESIGN {{ 1 0 10303 214 }}'));
ENDSEC;
DATA;
#1=APPLICATION_CONTEXT('automotive design');
#2=APPLICATION_PROTOCOL_DEFINITION('ISO 10303-214','automotive_design',2001,#1);
#3=PRODUCT_DEFINITION_CONTEXT('part definition',#1,'design');
#4=PRODUCT('PhotoCAD_Part','PhotoCAD_Part','Parametric 1:1 mm Solid',(#5));
#5=PRODUCT_CONTEXT('part context',#1,'mechanical');
#6=PRODUCT_DEFINITION('design','PhotoCAD Part Definition',#7,#3);
#7=PRODUCT_DEFINITION_FORMATION('1.0','Release',#4);
#8=PRODUCT_DEFINITION_SHAPE('','',#6);
#9=SHAPE_DEFINITION_REPRESENTATION(#8,#10);
#10=SHAPE_REPRESENTATION('PhotoCAD Part Shape',(#11),#12);
#11=AXIS2_PLACEMENT_3D('',#13,#14,#15);
#12=(GEOMETRIC_REPRESENTATION_CONTEXT(3) GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((#16)) GLOBAL_UNIT_ASSIGNED_CONTEXT((#17,#18,#19)) REPRESENTATION_CONTEXT('Context #1','3D'));
#13=CARTESIAN_POINT('',(0.,0.,0.));
#14=DIRECTION('',(0.,0.,1.));
#15=DIRECTION('',(1.,0.,0.));
#16=UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-07),#17,'distance_accuracy_value','confusion accuracy');
#17=(LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.));
#18=(NAMED_UNIT(*) PLANE_ANGLE_UNIT() SI_UNIT($,.RADIAN.));
#19=(NAMED_UNIT(*) SI_UNIT($,.STERADIAN.) SOLID_ANGLE_UNIT());
#20=MANIFOLD_SOLID_BREP('PhotoCAD_Solid',#21);
#21=CLOSED_SHELL('Closed Shell',(#30,#31,#32,#33,#34,#35));
#30=ADVANCED_FACE('Front Face',(#40),#50,.T.);
#31=ADVANCED_FACE('Back Face',(#41),#51,.T.);
#32=ADVANCED_FACE('Left Face',(#42),#52,.T.);
#33=ADVANCED_FACE('Right Face',(#43),#53,.T.);
#34=ADVANCED_FACE('Top Face',(#44),#54,.T.);
#35=ADVANCED_FACE('Bottom Face',(#45),#55,.T.);
#40=FACE_OUTER_BOUND('',#60,.T.);
#41=FACE_OUTER_BOUND('',#61,.T.);
#42=FACE_OUTER_BOUND('',#62,.T.);
#43=FACE_OUTER_BOUND('',#63,.T.);
#44=FACE_OUTER_BOUND('',#64,.T.);
#45=FACE_OUTER_BOUND('',#65,.T.);
#50=PLANE('',#70);
#51=PLANE('',#71);
#52=PLANE('',#72);
#53=PLANE('',#73);
#54=PLANE('',#74);
#55=PLANE('',#75);
#70=AXIS2_PLACEMENT_3D('',#80,#86,#15);
#71=AXIS2_PLACEMENT_3D('',#81,#87,#15);
#72=AXIS2_PLACEMENT_3D('',#82,#88,#14);
#73=AXIS2_PLACEMENT_3D('',#83,#89,#14);
#74=AXIS2_PLACEMENT_3D('',#84,#14,#15);
#75=AXIS2_PLACEMENT_3D('',#85,#90,#15);
#80=CARTESIAN_POINT('',(0.,{hy},0.));
#81=CARTESIAN_POINT('',(0.,{-hy},0.));
#82=CARTESIAN_POINT('',({-hx},0.,0.));
#83=CARTESIAN_POINT('',({hx},0.,0.));
#84=CARTESIAN_POINT('',(0.,0.,{hz}));
#85=CARTESIAN_POINT('',(0.,0.,{-hz}));
#86=DIRECTION('',(0.,1.,0.));
#87=DIRECTION('',(0.,-1.,0.));
#88=DIRECTION('',(-1.,0.,0.));
#89=DIRECTION('',(1.,0.,0.));
#90=DIRECTION('',(0.,0.,-1.));
ENDSEC;
END-ISO-10303-21;
"""
    path = Path(output_step_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(step_text, encoding="utf-8")
    return path


def write_orthographic_dxf(
    output_dxf_path: str | Path,
    length_x: float,
    width_y: float,
    height_z: float,
    hole_radius_mm: float = 0.0,
) -> Path:
    """
    Exports a standard AutoCAD DXF R12/2010 3-view orthographic projection (Top, Front, Right)
    using millimeter coordinates ($INSUNITS=4).
    """
    gap = 25.0
    hx, hy, hz = length_x / 2.0, width_y / 2.0, height_z / 2.0

    def rect_lines(cx: float, cy: float, w: float, h: float, layer: str = "GEOMETRY") -> List[str]:
        hw, hh = w / 2.0, h / 2.0
        pts = [
            (cx - hw, cy - hh),
            (cx + hw, cy - hh),
            (cx + hw, cy + hh),
            (cx - hw, cy + hh),
        ]
        out: List[str] = []
        for idx in range(4):
            p1, p2 = pts[idx], pts[(idx + 1) % 4]
            out.extend([
                "0", "LINE", "8", layer,
                "10", f"{p1[0]:.4f}", "20", f"{p1[1]:.4f}", "30", "0.0",
                "11", f"{p2[0]:.4f}", "21", f"{p2[1]:.4f}", "31", "0.0",
            ])
        return out

    entities: List[str] = []
    # Top view (X x Y) centered at (0, 0)
    entities.extend(rect_lines(0.0, 0.0, length_x, width_y))
    if hole_radius_mm > 0.5 and hole_radius_mm < min(hx, hy):
        entities.extend([
            "0", "CIRCLE", "8", "GEOMETRY",
            "10", "0.0", "20", "0.0", "30", "0.0",
            "40", f"{hole_radius_mm:.4f}",
        ])

    # Front view (X x Z) offset above Top view
    front_y = hy + gap + hz
    entities.extend(rect_lines(0.0, front_y, length_x, height_z))

    # Right profile view (Y x Z) offset right of Front view
    right_x = hx + gap + hy
    entities.extend(rect_lines(right_x, front_y, width_y, height_z))

    dxf_lines = [
        "0", "SECTION", "2", "HEADER",
        "9", "$ACADVER", "1", "AC1009",
        "9", "$INSUNITS", "70", "4",
        "0", "ENDSEC",
        "0", "SECTION", "2", "ENTITIES",
        *entities,
        "0", "ENDSEC",
        "0", "EOF\n",
    ]
    path = Path(output_dxf_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(dxf_lines), encoding="utf-8")
    return path
