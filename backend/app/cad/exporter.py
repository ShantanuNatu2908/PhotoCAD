"""
PhotoCAD - Watertight B-Rep Mesh & Engineering CAD Exporters (.STL, .STEP, .DXF)
Document ID: PCAD-PRD-SRS-001 (FR-17, NFR-06) / skills/cad-kernel.skill.md

Provides:
1. Manifold watertight ASCII .STL exporter (box or prismatic bracket with circular through-bore)
2. Full ISO 10303-21 (STEP AP214) exchange solid exporter (1:1 mm) with complete
   VERTEX_POINT -> EDGE_CURVE -> EDGE_LOOP -> ADVANCED_FACE -> CLOSED_SHELL -> MANIFOLD_SOLID_BREP
   topology and zero dangling entity references (AutoCAD / Fusion 360 / SolidWorks ready)
3. AutoCAD DXF R12/2010 orthographic 3-view drawing exporter with LAYER table & $INSUNITS=4 (mm)
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

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
        c = [
            (-hx, -hy, -hz), (hx, -hy, -hz), (hx, hy, -hz), (-hx, hy, -hz),
            (-hx, -hy, hz), (hx, -hy, hz), (hx, hy, hz), (-hx, hy, hz),
        ]
        return [
            (c[0], c[2], c[1]), (c[0], c[3], c[2]),
            (c[4], c[5], c[6]), (c[4], c[6], c[7]),
            (c[0], c[1], c[5]), (c[0], c[5], c[4]),
            (c[2], c[3], c[7]), (c[2], c[7], c[6]),
            (c[3], c[0], c[4]), (c[3], c[4], c[7]),
            (c[1], c[2], c[6]), (c[1], c[6], c[5]),
        ]

    corner_angles = [
        math.atan2(hy, hx),
        math.atan2(hy, -hx),
        math.atan2(-hy, -hx),
        math.atan2(-hy, hx),
    ]
    uniform_angles = [-math.pi + (2.0 * math.pi * k) / radial_segments for k in range(radial_segments)]
    merged = sorted(corner_angles + uniform_angles)

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

        tris.append((ci_t, bi_t, bj_t))
        tris.append((ci_t, bj_t, cj_t))
        tris.append((ci_b, bj_b, bi_b))
        tris.append((ci_b, cj_b, bj_b))
        tris.append((bi_b, bj_b, bj_t))
        tris.append((bi_b, bj_t, bi_t))
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
    """
    Writes a referentially complete ISO 10303-21 (AP214) B-Rep STEP exchange solid
    with SI millimeter units and full VERTEX_POINT -> EDGE_CURVE -> EDGE_LOOP -> ADVANCED_FACE
    connectivity (zero unresolved entity IDs for AutoCAD / Fusion 360 / SolidWorks).
    """
    hx = round(max(length_x / 2.0, 0.5), 4)
    hy = round(max(width_y / 2.0, 0.5), 4)
    hz = round(max(height_z / 2.0, 0.5), 4)
    has_hole = hole_radius_mm > 0.5 and hole_radius_mm < min(hx, hy) * 0.85
    r_hole = round(hole_radius_mm, 4) if has_hole else 0.0
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    eid = 1
    entities: List[str] = []

    def add(def_str: str) -> int:
        nonlocal eid
        idx = eid
        entities.append(f"#{idx}={def_str};")
        eid += 1
        return idx

    # Context & SI Millimeter Units
    app_ctx = add("APPLICATION_CONTEXT('automotive design')")
    add(f"APPLICATION_PROTOCOL_DEFINITION('ISO 10303-214','automotive_design',2001,#{app_ctx})")
    pd_ctx = add(f"PRODUCT_DEFINITION_CONTEXT('part definition',#{app_ctx},'design')")
    p_ctx = add(f"PRODUCT_CONTEXT('part context',#{app_ctx},'mechanical')")
    prod = add(f"PRODUCT('PhotoCAD_Part','PhotoCAD_Part','Parametric 1:1 mm Solid',(#{p_ctx}))")
    pdf = add(f"PRODUCT_DEFINITION_FORMATION('1.0','Release',#{prod})")
    pdef = add(f"PRODUCT_DEFINITION('design','PhotoCAD Part Definition',#{pdf},#{pd_ctx})")
    pds = add(f"PRODUCT_DEFINITION_SHAPE('','',#{pdef})")

    orig_pt = add("CARTESIAN_POINT('',(0.,0.,0.))")
    dir_z = add("DIRECTION('',(0.,0.,1.))")
    dir_x = add("DIRECTION('',(1.,0.,0.))")
    dir_y = add("DIRECTION('',(0.,1.,0.))")
    dir_neg_z = add("DIRECTION('',(0.,0.,-1.))")
    dir_neg_x = add("DIRECTION('',(-1.,0.,0.))")
    dir_neg_y = add("DIRECTION('',(0.,-1.,0.))")

    world_ax = add(f"AXIS2_PLACEMENT_3D('',#{orig_pt},#{dir_z},#{dir_x})")
    len_unit = add("(LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.))")
    ang_unit = add("(NAMED_UNIT(*) PLANE_ANGLE_UNIT() SI_UNIT($,.RADIAN.))")
    sol_unit = add("(NAMED_UNIT(*) SI_UNIT($,.STERADIAN.) SOLID_ANGLE_UNIT())")
    uncert = add(f"UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-07),#{len_unit},'distance_accuracy_value','confusion accuracy')")
    geom_ctx = add(
        f"(GEOMETRIC_REPRESENTATION_CONTEXT(3) GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((#{uncert})) "
        f"GLOBAL_UNIT_ASSIGNED_CONTEXT((#{len_unit},#{ang_unit},#{sol_unit})) REPRESENTATION_CONTEXT('Context #1','3D'))"
    )

    # 8 Corner Vertices
    corner_coords = [
        (-hx, -hy, -hz), (hx, -hy, -hz), (hx, hy, -hz), (-hx, hy, -hz),
        (-hx, -hy, hz), (hx, -hy, hz), (hx, hy, hz), (-hx, hy, hz),
    ]
    v_ids: List[int] = []
    for cx, cy, cz in corner_coords:
        cp = add(f"CARTESIAN_POINT('',({cx},{cy},{cz}))")
        v_ids.append(add(f"VERTEX_POINT('',#{cp})"))

    # Helper to construct straight EDGE_CURVE between two corner vertices
    def make_edge(i0: int, i1: int, d_id: int) -> int:
        p0 = corner_coords[i0]
        cp0 = add(f"CARTESIAN_POINT('',({p0[0]},{p0[1]},{p0[2]}))")
        vec = add(f"VECTOR('',#{d_id},1.)")
        line = add(f"LINE('',#{cp0},#{vec})")
        return add(f"EDGE_CURVE('',#{v_ids[i0]},#{v_ids[i1]},#{line},.T.)")

    # 12 Edges of the rectangular prism
    e_bot = [
        make_edge(0, 1, dir_x),
        make_edge(1, 2, dir_y),
        make_edge(2, 3, dir_neg_x),
        make_edge(3, 0, dir_neg_y),
    ]
    e_top = [
        make_edge(4, 5, dir_x),
        make_edge(5, 6, dir_y),
        make_edge(6, 7, dir_neg_x),
        make_edge(7, 4, dir_neg_y),
    ]
    e_vert = [
        make_edge(0, 4, dir_z),
        make_edge(1, 5, dir_z),
        make_edge(2, 6, dir_z),
        make_edge(3, 7, dir_z),
    ]

    def make_face(name: str, edge_refs: List[Tuple[int, str]], plane_origin: Tuple[float, float, float], normal_id: int, ref_id: int, extra_bounds: List[int] | None = None) -> int:
        o_edges = [add(f"ORIENTED_EDGE('',*,*,#{e_id},{sense})") for e_id, sense in edge_refs]
        loop = add(f"EDGE_LOOP('',({','.join(f'#{oe}' for oe in o_edges)}))")
        bounds = [add(f"FACE_OUTER_BOUND('',#{loop},.T.)")]
        if extra_bounds:
            bounds.extend(extra_bounds)
        pt = add(f"CARTESIAN_POINT('',({plane_origin[0]},{plane_origin[1]},{plane_origin[2]}))")
        ax = add(f"AXIS2_PLACEMENT_3D('',#{pt},#{normal_id},#{ref_id})")
        pln = add(f"PLANE('',#{ax})")
        return add(f"ADVANCED_FACE('{name}',({','.join(f'#{b}' for b in bounds)}),#{pln},.T.)")

    # Optional cylindrical through-bore topology (Top/Bottom inner bounds + Cylindrical face)
    top_inner_bound: List[int] = []
    bot_inner_bound: List[int] = []
    cyl_faces: List[int] = []

    if has_hole:
        pt_top_seam = add(f"CARTESIAN_POINT('',({r_hole},0.,{hz}))")
        pt_bot_seam = add(f"CARTESIAN_POINT('',({r_hole},0.,{-hz}))")
        v_top_seam = add(f"VERTEX_POINT('',#{pt_top_seam})")
        v_bot_seam = add(f"VERTEX_POINT('',#{pt_bot_seam})")

        c_top_ctr = add(f"CARTESIAN_POINT('',(0.,0.,{hz}))")
        c_bot_ctr = add(f"CARTESIAN_POINT('',(0.,0.,{-hz}))")
        ax_top_c = add(f"AXIS2_PLACEMENT_3D('',#{c_top_ctr},#{dir_z},#{dir_x})")
        ax_bot_c = add(f"AXIS2_PLACEMENT_3D('',#{c_bot_ctr},#{dir_z},#{dir_x})")

        circ_top = add(f"CIRCLE('',#{ax_top_c},{r_hole})")
        circ_bot = add(f"CIRCLE('',#{ax_bot_c},{r_hole})")
        ec_top = add(f"EDGE_CURVE('',#{v_top_seam},#{v_top_seam},#{circ_top},.T.)")
        ec_bot = add(f"EDGE_CURVE('',#{v_bot_seam},#{v_bot_seam},#{circ_bot},.T.)")

        seam_vec = add(f"VECTOR('',#{dir_neg_z},1.)")
        seam_line = add(f"LINE('',#{pt_top_seam},#{seam_vec})")
        ec_seam = add(f"EDGE_CURVE('',#{v_top_seam},#{v_bot_seam},#{seam_line},.T.)")

        oe_top_face = add(f"ORIENTED_EDGE('',*,*,#{ec_top},.F.)")
        loop_top_hole = add(f"EDGE_LOOP('',(#{oe_top_face}))")
        top_inner_bound.append(add(f"FACE_BOUND('',#{loop_top_hole},.T.)"))

        oe_bot_face = add(f"ORIENTED_EDGE('',*,*,#{ec_bot},.T.)")
        loop_bot_hole = add(f"EDGE_LOOP('',(#{oe_bot_face}))")
        bot_inner_bound.append(add(f"FACE_BOUND('',#{loop_bot_hole},.T.)"))

        oe_cyl_1 = add(f"ORIENTED_EDGE('',*,*,#{ec_top},.T.)")
        oe_cyl_2 = add(f"ORIENTED_EDGE('',*,*,#{ec_seam},.T.)")
        oe_cyl_3 = add(f"ORIENTED_EDGE('',*,*,#{ec_bot},.F.)")
        oe_cyl_4 = add(f"ORIENTED_EDGE('',*,*,#{ec_seam},.F.)")
        loop_cyl = add(f"EDGE_LOOP('',(#{oe_cyl_1},#{oe_cyl_2},#{oe_cyl_3},#{oe_cyl_4}))")
        bound_cyl = add(f"FACE_OUTER_BOUND('',#{loop_cyl},.T.)")
        cyl_surf = add(f"CYLINDRICAL_SURFACE('',#{world_ax},{r_hole})")
        cyl_faces.append(add(f"ADVANCED_FACE('Through Bore Surface',(#{bound_cyl}),#{cyl_surf},.F.)"))

    # 6 Outer Faces (all closed oriented edge loops)
    f_bot = make_face("Bottom Face", [(e_bot[3], ".F."), (e_bot[2], ".F."), (e_bot[1], ".F."), (e_bot[0], ".F.")], (0.0, 0.0, -hz), dir_neg_z, dir_x, extra_bounds=bot_inner_bound)
    f_top = make_face("Top Face", [(e_top[0], ".T."), (e_top[1], ".T."), (e_top[2], ".T."), (e_top[3], ".T.")], (0.0, 0.0, hz), dir_z, dir_x, extra_bounds=top_inner_bound)
    f_front = make_face("Front Face", [(e_bot[0], ".T."), (e_vert[1], ".T."), (e_top[0], ".F."), (e_vert[0], ".F.")], (0.0, -hy, 0.0), dir_neg_y, dir_x)
    f_right = make_face("Right Face", [(e_bot[1], ".T."), (e_vert[2], ".T."), (e_top[1], ".F."), (e_vert[1], ".F.")], (hx, 0.0, 0.0), dir_x, dir_y)
    f_back = make_face("Back Face", [(e_bot[2], ".T."), (e_vert[3], ".T."), (e_top[2], ".F."), (e_vert[2], ".F.")], (0.0, hy, 0.0), dir_y, dir_neg_x)
    f_left = make_face("Left Face", [(e_bot[3], ".T."), (e_vert[0], ".T."), (e_top[3], ".F."), (e_vert[3], ".F.")], (-hx, 0.0, 0.0), dir_neg_x, dir_neg_y)

    all_faces = [f_front, f_back, f_left, f_right, f_top, f_bot] + cyl_faces
    shell = add(f"CLOSED_SHELL('Closed Shell',({','.join(f'#{fid}' for fid in all_faces)}))")
    solid = add(f"MANIFOLD_SOLID_BREP('PhotoCAD_Solid',#{shell})")
    shape_rep = add(f"ADVANCED_BREP_SHAPE_REPRESENTATION('PhotoCAD Part Shape',(#{solid},#{world_ax}),#{geom_ctx})")
    add(f"SHAPE_DEFINITION_REPRESENTATION(#{pds},#{shape_rep})")

    step_text = "\n".join([
        "ISO-10303-21;",
        "HEADER;",
        f"FILE_DESCRIPTION(('PhotoCAD Parametric B-Rep Solid ({length_x:.2f}x{width_y:.2f}x{height_z:.2f} mm, bore R={r_hole:.2f} mm)'),'2;1');",
        f"FILE_NAME('PhotoCAD_Model.step','{ts}',('PhotoCAD LangGraph'),('PhotoCAD'),'OpenCascade/build123d','PhotoCAD Kernel','');",
        "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 }'));",
        "ENDSEC;",
        "DATA;",
        *entities,
        "ENDSEC;",
        "END-ISO-10303-21;\n",
    ])

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
    Exports an AutoCAD DXF drawing (Top, Front, Right orthographic projections)
    with explicit LAYER table (`GEOMETRY` & `DIMENSIONS`) and $INSUNITS=4 (Millimeters).
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
    entities.extend(rect_lines(0.0, 0.0, length_x, width_y, layer="GEOMETRY"))
    if hole_radius_mm > 0.5 and hole_radius_mm < min(hx, hy):
        entities.extend([
            "0", "CIRCLE", "8", "GEOMETRY",
            "10", "0.0", "20", "0.0", "30", "0.0",
            "40", f"{hole_radius_mm:.4f}",
        ])

    # Front view (X x Z) above Top view
    front_y = hy + gap + hz
    entities.extend(rect_lines(0.0, front_y, length_x, height_z, layer="GEOMETRY"))

    # Right profile view (Y x Z) right of Front view
    right_x = hx + gap + hy
    entities.extend(rect_lines(right_x, front_y, width_y, height_z, layer="GEOMETRY"))

    # Add TEXT annotation block on ANNOTATIONS layer in mm
    entities.extend([
        "0", "TEXT", "8", "ANNOTATIONS",
        "10", f"{-hx:.4f}", "20", f"{-hy - 12.0:.4f}", "30", "0.0",
        "40", "3.5",
        "1", f"PHOTOCAD 1:1 MM | {length_x:.2f} x {width_y:.2f} x {height_z:.2f} mm",
    ])

    dxf_lines = [
        "0", "SECTION", "2", "HEADER",
        "9", "$ACADVER", "1", "AC1009",
        "9", "$INSUNITS", "70", "4",
        "9", "$MEASUREMENT", "70", "1",
        "0", "ENDSEC",
        "0", "SECTION", "2", "TABLES",
        "0", "TABLE", "2", "LAYER", "70", "2",
        "0", "LAYER", "2", "GEOMETRY", "70", "0", "62", "7", "6", "CONTINUOUS",
        "0", "LAYER", "2", "ANNOTATIONS", "70", "0", "62", "4", "6", "CONTINUOUS",
        "0", "ENDTAB",
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


def write_mesh_stl(
    output_stl_path: str | Path,
    vertices_mm: List[List[float]],
    triangles_idx: List[List[int]],
) -> Path:
    """Exports an arbitrary 2-manifold sculpted triangle mesh as ASCII .STL in 1:1 millimeters."""
    lines = ["solid PhotoCAD_Sculpted_Solid"]
    for i0, i1, i2 in triangles_idx:
        v0 = (float(vertices_mm[i0][0]), float(vertices_mm[i0][1]), float(vertices_mm[i0][2]))
        v1 = (float(vertices_mm[i1][0]), float(vertices_mm[i1][1]), float(vertices_mm[i1][2]))
        v2 = (float(vertices_mm[i2][0]), float(vertices_mm[i2][1]), float(vertices_mm[i2][2]))
        nx, ny, nz = _cross_normal(v0, v1, v2)
        lines.append(f"  facet normal {nx:.6f} {ny:.6f} {nz:.6f}")
        lines.append("    outer loop")
        lines.append(f"      vertex {v0[0]:.5f} {v0[1]:.5f} {v0[2]:.5f}")
        lines.append(f"      vertex {v1[0]:.5f} {v1[1]:.5f} {v1[2]:.5f}")
        lines.append(f"      vertex {v2[0]:.5f} {v2[1]:.5f} {v2[2]:.5f}")
        lines.append("    endloop")
        lines.append("  endfacet")
    lines.append("endsolid PhotoCAD_Sculpted_Solid\n")

    path = Path(output_stl_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_faceted_hull_step(
    output_step_path: str | Path,
    vertices_mm: List[List[float]],
    triangles_idx: List[List[int]],
    length_x: float,
    width_y: float,
    height_z: float,
) -> Path:
    """
    Writes a referentially complete ISO 10303-21 (AP214) CLOSED_SHELL B-Rep STEP file
    across a sculpted triangle mesh (AutoCAD / Fusion 360 / SolidWorks importable, 1:1 mm).
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    eid = 1
    entities: List[str] = []

    def add(def_str: str) -> int:
        nonlocal eid
        idx = eid
        entities.append(f"#{idx}={def_str};")
        eid += 1
        return idx

    app_ctx = add("APPLICATION_CONTEXT('automotive design')")
    add(f"APPLICATION_PROTOCOL_DEFINITION('ISO 10303-214','automotive_design',2001,#{app_ctx})")
    pd_ctx = add(f"PRODUCT_DEFINITION_CONTEXT('part definition',#{app_ctx},'design')")
    p_ctx = add(f"PRODUCT_CONTEXT('part context',#{app_ctx},'mechanical')")
    prod = add(f"PRODUCT('PhotoCAD_Part','PhotoCAD_Part','Sculpted 1:1 mm Solid',(#{p_ctx}))")
    pdf = add(f"PRODUCT_DEFINITION_FORMATION('1.0','Release',#{prod})")
    pdef = add(f"PRODUCT_DEFINITION('design','PhotoCAD Sculpted Definition',#{pdf},#{pd_ctx})")
    pds = add(f"PRODUCT_DEFINITION_SHAPE('','',#{pdef})")

    orig_pt = add("CARTESIAN_POINT('',(0.,0.,0.))")
    dir_z = add("DIRECTION('',(0.,0.,1.))")
    dir_x = add("DIRECTION('',(1.,0.,0.))")
    world_ax = add(f"AXIS2_PLACEMENT_3D('',#{orig_pt},#{dir_z},#{dir_x})")
    len_unit = add("(LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.))")
    ang_unit = add("(NAMED_UNIT(*) PLANE_ANGLE_UNIT() SI_UNIT($,.RADIAN.))")
    sol_unit = add("(NAMED_UNIT(*) SI_UNIT($,.STERADIAN.) SOLID_ANGLE_UNIT())")
    uncert = add(f"UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-07),#{len_unit},'distance_accuracy_value','confusion accuracy')")
    geom_ctx = add(
        f"(GEOMETRIC_REPRESENTATION_CONTEXT(3) GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((#{uncert})) "
        f"GLOBAL_UNIT_ASSIGNED_CONTEXT((#{len_unit},#{ang_unit},#{sol_unit})) REPRESENTATION_CONTEXT('Context #1','3D'))"
    )

    v_cp_ids: List[int] = []
    v_pt_ids: List[int] = []
    for vx, vy, vz in vertices_mm:
        cp = add(f"CARTESIAN_POINT('',({vx:.4f},{vy:.4f},{vz:.4f}))")
        v_cp_ids.append(cp)
        v_pt_ids.append(add(f"VERTEX_POINT('',#{cp})"))

    edge_cache: dict[Tuple[int, int], int] = {}

    def get_edge(a: int, b: int) -> Tuple[int, str]:
        u, v = (a, b) if a < b else (b, a)
        sense = ".T." if a < b else ".F."
        cached = edge_cache.get((u, v))
        if cached is not None:
            return cached, sense
        pa, pb = vertices_mm[u], vertices_mm[v]
        dx, dy, dz = pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2]
        mag = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
        d_id = add(f"DIRECTION('',({dx / mag:.6f},{dy / mag:.6f},{dz / mag:.6f}))")
        vec_id = add(f"VECTOR('',#{d_id},1.)")
        line_id = add(f"LINE('',#{v_cp_ids[u]},#{vec_id})")
        ec_id = add(f"EDGE_CURVE('',#{v_pt_ids[u]},#{v_pt_ids[v]},#{line_id},.T.)")
        edge_cache[(u, v)] = ec_id
        return ec_id, sense

    face_ids: List[int] = []
    for i0, i1, i2 in triangles_idx:
        p0, p1, p2 = vertices_mm[i0], vertices_mm[i1], vertices_mm[i2]
        nx, ny, nz = _cross_normal((p0[0], p0[1], p0[2]), (p1[0], p1[1], p1[2]), (p2[0], p2[1], p2[2]))
        rx, ry, rz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
        rm = math.sqrt(rx * rx + ry * ry + rz * rz) or 1.0
        n_dir = add(f"DIRECTION('',({nx:.6f},{ny:.6f},{nz:.6f}))")
        r_dir = add(f"DIRECTION('',({rx / rm:.6f},{ry / rm:.6f},{rz / rm:.6f}))")
        ax_id = add(f"AXIS2_PLACEMENT_3D('',#{v_cp_ids[i0]},#{n_dir},#{r_dir})")
        pln_id = add(f"PLANE('',#{ax_id})")

        e0, s0 = get_edge(i0, i1)
        e1, s1 = get_edge(i1, i2)
        e2, s2 = get_edge(i2, i0)
        oe0 = add(f"ORIENTED_EDGE('',*,*,#{e0},{s0})")
        oe1 = add(f"ORIENTED_EDGE('',*,*,#{e1},{s1})")
        oe2 = add(f"ORIENTED_EDGE('',*,*,#{e2},{s2})")
        loop_id = add(f"EDGE_LOOP('',(#{oe0},#{oe1},#{oe2}))")
        bound_id = add(f"FACE_OUTER_BOUND('',#{loop_id},.T.)")
        face_ids.append(add(f"ADVANCED_FACE('',(#{bound_id}),#{pln_id},.T.)"))

    shell = add(f"CLOSED_SHELL('Closed Shell',({','.join(f'#{fid}' for fid in face_ids)}))")
    solid = add(f"MANIFOLD_SOLID_BREP('PhotoCAD_Solid',#{shell})")
    shape_rep = add(f"ADVANCED_BREP_SHAPE_REPRESENTATION('PhotoCAD Part Shape',(#{solid},#{world_ax}),#{geom_ctx})")
    add(f"SHAPE_DEFINITION_REPRESENTATION(#{pds},#{shape_rep})")

    step_text = "\n".join([
        "ISO-10303-21;",
        "HEADER;",
        f"FILE_DESCRIPTION(('PhotoCAD Sculpted B-Rep Solid ({length_x:.2f}x{width_y:.2f}x{height_z:.2f} mm)'),'2;1');",
        f"FILE_NAME('PhotoCAD_Model.step','{ts}',('PhotoCAD LangGraph'),('PhotoCAD'),'OpenCascade/build123d','PhotoCAD Kernel','');",
        "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 }'));",
        "ENDSEC;",
        "DATA;",
        *entities,
        "ENDSEC;",
        "END-ISO-10303-21;\n",
    ])

    path = Path(output_step_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(step_text, encoding="utf-8")
    return path


def write_silhouette_dxf(
    output_dxf_path: str | Path,
    contours_2d: dict,
    length_x: float,
    width_y: float,
    height_z: float,
    hole_radius_mm: float = 0.0,
) -> Path:
    """Exports real 3-view orthographic silhouette outlines (Top XY, Front XZ, Right YZ) in 1:1 mm DXF."""
    gap = max(25.0, min(length_x, width_y) * 0.25)
    hx, hy, hz = length_x / 2.0, width_y / 2.0, height_z / 2.0
    entities: List[str] = []

    def poly_lines(pts_norm: List[Tuple[float, float]], cx: float, cy: float, sx: float, sy: float) -> None:
        if len(pts_norm) < 3:
            pts_norm = [(-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)]
        n = len(pts_norm)
        for i in range(n):
            p1 = pts_norm[i]
            p2 = pts_norm[(i + 1) % n]
            entities.extend([
                "0", "LINE", "8", "GEOMETRY",
                "10", f"{cx + p1[0] * sx:.4f}", "20", f"{cy + p1[1] * sy:.4f}", "30", "0.0",
                "11", f"{cx + p2[0] * sx:.4f}", "21", f"{cy + p2[1] * sy:.4f}", "31", "0.0",
            ])

    # Top View (XY) at (0, 0)
    poly_lines(contours_2d.get("xy", []), 0.0, 0.0, length_x, width_y)
    if hole_radius_mm > 0.5 and hole_radius_mm < min(hx, hy):
        entities.extend([
            "0", "CIRCLE", "8", "GEOMETRY",
            "10", "0.0", "20", "0.0", "30", "0.0",
            "40", f"{hole_radius_mm:.4f}",
        ])

    # Front View (XZ) above Top View
    front_y = hy + gap + hz
    poly_lines(contours_2d.get("xz", []), 0.0, front_y, length_x, height_z)

    # Right View (YZ) right of Front View
    right_x = hx + gap + hy
    poly_lines(contours_2d.get("yz", []), right_x, front_y, width_y, height_z)

    entities.extend([
        "0", "TEXT", "8", "ANNOTATIONS",
        "10", f"{-hx:.4f}", "20", f"{-hy - 12.0:.4f}", "30", "0.0",
        "40", "3.5",
        "1", f"PHOTOCAD SCULPTED 1:1 MM | {length_x:.2f} x {width_y:.2f} x {height_z:.2f} mm",
    ])

    dxf_lines = [
        "0", "SECTION", "2", "HEADER",
        "9", "$ACADVER", "1", "AC1009",
        "9", "$INSUNITS", "70", "4",
        "9", "$MEASUREMENT", "70", "1",
        "0", "ENDSEC",
        "0", "SECTION", "2", "TABLES",
        "0", "TABLE", "2", "LAYER", "70", "2",
        "0", "LAYER", "2", "GEOMETRY", "70", "0", "62", "7", "6", "CONTINUOUS",
        "0", "LAYER", "2", "ANNOTATIONS", "70", "0", "62", "4", "6", "CONTINUOUS",
        "0", "ENDTAB",
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
