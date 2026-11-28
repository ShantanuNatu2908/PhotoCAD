"""C2 B-spline surface patch tests (nurbs-surfaces.skill.md)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np

from app.cad.nurbs import (
    BsplinePatch,
    clamped_knots,
    fit_surface_patches,
    is_c2,
    render_patches_as_step_entities,
)
from app.cad.visual_hull import carve_visual_hull_from_views


def box_mesh(length=80.0, width=50.0, height=30.0):
    x, y, z = length / 2, width / 2, height
    vertices = [
        [-x, -y, 0.0], [x, -y, 0.0], [x, y, 0.0], [-x, y, 0.0],
        [-x, -y, z], [x, -y, z], [x, y, z], [-x, y, z],
    ]
    triangles = [
        [0, 2, 1], [0, 3, 2],          # bottom
        [4, 5, 6], [4, 6, 7],          # top
        [0, 1, 5], [0, 5, 4],          # front (-Y)
        [1, 2, 6], [1, 6, 5],          # right (+X)
        [2, 3, 7], [2, 7, 6],          # back (+Y)
        [3, 0, 4], [3, 4, 7],          # left (-X)
    ]
    return vertices, triangles


def _edge_counts(triangles):
    counts = Counter()
    for a, b, c in triangles:
        for edge in ((a, b), (b, c), (c, a)):
            counts[tuple(sorted(edge))] += 1
    return counts


def test_clamped_knot_vector_is_open_uniform_and_c2():
    knots = clamped_knots(6)
    assert knots == [0.0, 0.0, 0.0, 0.0, 1 / 3, 2 / 3, 1.0, 1.0, 1.0, 1.0]
    patch = BsplinePatch(
        side="top",
        control_points=[[0.0, 0.0, 0.0]] * 36,
        u_knots=knots,
        v_knots=knots,
    )
    assert is_c2(patch)
    assert patch.grid_shape == (6, 6)


def test_fit_six_face_groups_with_bounded_deviation():
    vertices, triangles = box_mesh()
    assert set(_edge_counts(triangles).values()) == {2}, "source hull must be watertight"

    result = fit_surface_patches(vertices, triangles, (80.0, 50.0, 30.0))
    assert result.surface_mode == "c2_bspline"
    assert len(result.patches) == 6
    assert {patch.side for patch in result.patches} == {
        "front", "back", "left", "right", "top", "bottom"
    }
    assert all(is_c2(patch) for patch in result.patches)
    assert result.max_deviation_mm <= 0.5
    # Every control point stays in millimetre space within the part envelope.
    for patch in result.patches:
        for x, y, z in patch.control_points:
            assert -41.0 <= x <= 41.0
            assert -26.0 <= y <= 26.0
            assert -1.0 <= z <= 31.0


def test_patch_evaluate_is_deterministic_and_step_entities_are_ap214():
    vertices, triangles = box_mesh()
    result = fit_surface_patches(vertices, triangles, (80.0, 50.0, 30.0))
    patch = result.patches[0]
    assert patch.evaluate(0.25, 0.75) == patch.evaluate(0.25, 0.75)

    step = render_patches_as_step_entities(result.patches)
    assert step.startswith("ISO-10303-21;")
    assert "AUTOMOTIVE_DESIGN" in step
    assert step.count("B_SPLINE_SURFACE_WITH_KNOTS") == 6
    assert step.count("CARTESIAN_POINT") == 6 * 36
    assert "OPEN_SHELL" in step
    # Honest boundary: this representation never claims a verified CLOSED_SHELL.
    assert "CLOSED_SHELL" not in step


def test_insufficient_geometry_falls_back_to_faceted_shell():
    vertices, triangles = box_mesh()
    result = fit_surface_patches(vertices[:4], triangles[:2], (80.0, 50.0, 30.0))
    assert result.surface_mode == "faceted_fallback"
    assert result.reason
    assert result.patches == []


def test_opt_in_smooth_surfaces_writes_patch_metadata(tmp_path: Path):
    from PIL import Image

    def solid_png() -> bytes:
        array = np.full((120, 160, 3), 25, dtype=np.uint8)
        array[25:95, 25:135] = (210, 215, 220)
        import io

        buffer = io.BytesIO()
        Image.fromarray(array, "RGB").save(buffer, format="PNG")
        return buffer.getvalue()

    views = {side: solid_png() for side in ["front", "back", "left", "right", "top", "bottom"]}
    hull_path = tmp_path / "hull.json"
    result = carve_visual_hull_from_views(
        "nurbs_optin_test",
        views,
        {"mode": "known_dimension", "known_length_mm": 80.0, "mm_per_unit": 0.5},
        hull_output_path=hull_path,
        smooth_surfaces=True,
    )
    assert result["surface_mode"] in {"c2_bspline", "faceted_fallback"}
    payload = json.loads(hull_path.read_text(encoding="utf-8"))
    assert "surface_mode" in payload
    assert payload["surface_mode"] == result["surface_mode"]
