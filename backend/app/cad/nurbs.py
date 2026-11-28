"""
PhotoCAD C2 B-spline surface patches (nurbs-surfaces.skill.md).

Fits clamped cubic tensor-product B-spline patches to the six principal face
groups of an already watertight visual hull. The authoritative watertight B-Rep
remains the faceted AP214 shell emitted by `exporter.py`; this module emits
patch geometry (and an OPEN_SHELL STEP *representation* of it) for smooth-surface
interop. It never replaces the closed shell with unvalidated trimmed surfaces.

All control points are millimetres (1:1). Knot vectors are dimensionless.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

DEGREE = 3
DEFAULT_CONTROL_POINTS = 6
MAX_DEVIATION_MM = 0.5
DEVIATION_RATIO = 0.01
MIN_FACE_VERTICES = 4

_SIDE_LABELS = {
    (0, False): "left", (0, True): "right",
    (1, False): "front", (1, True): "back",
    (2, False): "bottom", (2, True): "top",
}


def clamped_knots(n_control: int, degree: int = DEGREE) -> List[float]:
    """Open uniform (clamped) knot vector; interior knots have multiplicity 1."""
    if n_control <= degree:
        raise ValueError("control point count must exceed the spline degree")
    interior = n_control - degree - 1
    return (
        [0.0] * (degree + 1)
        + [(i + 1) / (interior + 1) for i in range(interior)]
        + [1.0] * (degree + 1)
    )


def basis(index: int, degree: int, t: float, knots: Sequence[float]) -> float:
    """Cox-de Boor basis function N_{index,degree}(t)."""
    control_points = len(knots) - degree - 1
    if t >= knots[-1]:
        return 1.0 if index == control_points - 1 else 0.0
    if t < knots[0]:
        return 0.0
    if degree == 0:
        return 1.0 if knots[index] <= t < knots[index + 1] else 0.0
    span = knots[index + degree] - knots[index]
    left = 0.0
    if span > 1e-12:
        left = (t - knots[index]) / span * basis(index, degree - 1, t, knots)
    span_next = knots[index + degree + 1] - knots[index + 1]
    right = 0.0
    if span_next > 1e-12:
        right = (knots[index + degree + 1] - t) / span_next * basis(index + 1, degree - 1, t, knots)
    return left + right


@dataclass
class BsplinePatch:
    """One clamped cubic tensor-product surface patch, control points in mm."""

    side: str
    control_points: List[List[float]]
    u_knots: List[float]
    v_knots: List[float]
    degree_u: int = DEGREE
    degree_v: int = DEGREE

    @property
    def grid_shape(self) -> Tuple[int, int]:
        return (len(self.u_knots) - self.degree_u - 1, len(self.v_knots) - self.degree_v - 1)

    def evaluate(self, u: float, v: float) -> List[float]:
        nu, nv = self.grid_shape
        bu = [basis(i, self.degree_u, u, self.u_knots) for i in range(nu)]
        bv = [basis(j, self.degree_v, v, self.v_knots) for j in range(nv)]
        point = np.zeros(3, dtype=float)
        for i in range(nu):
            for j in range(nv):
                point += bu[i] * bv[j] * np.asarray(self.control_points[i * nv + j], dtype=float)
        return point.tolist()

    def to_dict(self) -> Dict[str, Any]:
        """JSON-serialisable patch data for `visual_hull.json` / LangGraph state."""
        return {
            "side": self.side,
            "degree_u": self.degree_u,
            "degree_v": self.degree_v,
            "control_points_mm": self.control_points,
            "u_knots": self.u_knots,
            "v_knots": self.v_knots,
            "grid_shape": list(self.grid_shape),
        }


def is_c2(patch: BsplinePatch) -> bool:
    """C2 continuity requires degree 3 and multiplicity-1 interior knots."""
    if patch.degree_u != DEGREE or patch.degree_v != DEGREE:
        return False
    for knots in (patch.u_knots, patch.v_knots):
        if len(knots) != len(set(knots)) + 2 * DEGREE:
            return False
        if sorted(knots) != list(knots):
            return False
        if knots[: DEGREE + 1] != [0.0] * (DEGREE + 1):
            return False
        if knots[-(DEGREE + 1):] != [1.0] * (DEGREE + 1):
            return False
        interior = knots[DEGREE + 1: -(DEGREE + 1)]
        if len(set(interior)) != len(interior):
            return False
    return True


@dataclass
class SurfaceFitResult:
    """Result of fitting smooth patches to a faceted, manifold hull."""

    patches: List[BsplinePatch] = field(default_factory=list)
    surface_mode: str = "faceted_fallback"
    max_deviation_mm: float = 0.0
    reason: Optional[str] = None


def _deviation(
    patch: BsplinePatch,
    samples: np.ndarray,
    params: np.ndarray,
) -> float:
    evaluated = np.asarray([patch.evaluate(float(u), float(v)) for u, v in params], dtype=float)
    return float(np.max(np.linalg.norm(evaluated - samples, axis=1))) if len(samples) else 0.0


def _fit_one_patch(
    side: str,
    samples: np.ndarray,
    params: np.ndarray,
    n_control: int,
) -> BsplinePatch:
    """Least-squares tensor-product fit; deterministic for a given sample order."""
    knots = clamped_knots(n_control)
    nu = nv = n_control
    rows = np.zeros((len(params), nu * nv), dtype=float)
    for row, (u, v) in enumerate(params):
        bu = np.asarray([basis(i, DEGREE, float(u), knots) for i in range(nu)])
        bv = np.asarray([basis(j, DEGREE, float(v), knots) for j in range(nv)])
        rows[row] = np.outer(bu, bv).reshape(-1)
    solved, *_ = np.linalg.lstsq(rows, samples, rcond=None)
    return BsplinePatch(
        side=side,
        control_points=[[float(x), float(y), float(z)] for x, y, z in solved],
        u_knots=list(knots),
        v_knots=list(knots),
    )


def fit_surface_patches(
    vertices_mm: Sequence[Sequence[float]],
    triangles_idx: Sequence[Sequence[int]],
    dimensions_mm: Sequence[float],
    n_control: int = DEFAULT_CONTROL_POINTS,
) -> SurfaceFitResult:
    """Fits up to six face-group patches; falls back when deviation is unbounded."""
    vertices = np.asarray(vertices_mm, dtype=float)
    triangles = np.asarray(triangles_idx, dtype=int)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or len(triangles) < MIN_FACE_VERTICES:
        return SurfaceFitResult(reason="insufficient manifold geometry")

    dimension_array = np.asarray(dimensions_mm, dtype=float)
    diagonal = float(np.linalg.norm(dimension_array)) if dimension_array.size == 3 else float(np.max(vertices))
    tolerance = max(MAX_DEVIATION_MM, DEVIATION_RATIO * diagonal)

    edges = vertices[triangles[:, 1]] - vertices[triangles[:, 0]]
    other = vertices[triangles[:, 2]] - vertices[triangles[:, 0]]
    normals = np.cross(edges, other)
    axes = np.argmax(np.abs(normals), axis=1)
    signs = normals[np.arange(len(triangles)), axes] >= 0

    patches: List[BsplinePatch] = []
    max_deviation = 0.0
    for (axis, positive), label in _SIDE_LABELS.items():
        selected = triangles[(axes == axis) & (signs == positive)]
        if len(selected) < 2:
            continue
        indices = np.unique(selected.reshape(-1))
        if len(indices) < MIN_FACE_VERTICES:
            continue
        planar_axes = [a for a in range(3) if a != axis]
        samples = vertices[indices]
        plane_min = samples[:, planar_axes].min(axis=0)
        plane_span = samples[:, planar_axes].max(axis=0) - plane_min
        if np.any(plane_span <= 1e-9):
            continue
        params = (samples[:, planar_axes] - plane_min) / plane_span
        params = np.clip(params, 0.0, 1.0)

        patch = _fit_one_patch(label, samples, params, n_control)
        if not is_c2(patch):
            return SurfaceFitResult(reason=f"{label} patch is not C2-continuous")
        deviation = _deviation(patch, samples, params)
        if not np.isfinite(deviation) or deviation > tolerance:
            return SurfaceFitResult(
                reason=f"{label} patch deviation {deviation:.3f} mm exceeds {tolerance:.3f} mm",
                max_deviation_mm=float(deviation) if np.isfinite(deviation) else 0.0,
            )
        patches.append(patch)
        max_deviation = max(max_deviation, deviation)

    if len(patches) < 4:
        return SurfaceFitResult(
            reason=f"only {len(patches)} stable face groups (need at least 4)",
            max_deviation_mm=max_deviation,
        )
    return SurfaceFitResult(
        patches=patches,
        surface_mode="c2_bspline",
        max_deviation_mm=max_deviation,
        reason=None,
    )


def knot_multiplicities(knots: Sequence[float]) -> List[int]:
    """AP214 B_SPLINE_SURFACE_WITH_KNOTS multiplicity array."""
    return [count for _, count in sorted(Counter(round(float(k), 9) for k in knots).items())]


def render_patches_as_step_entities(patches: Sequence[BsplinePatch]) -> str:
    """Renders patch definitions as an AP214 OPEN_SHELL representation.

    This is intentionally OPEN_SHELL: only `exporter.py`'s faceted AP214 body is a
    verified CLOSED_SHELL. Consumers that require a watertight solid keep using
    the authoritative STEP file; this representation carries the C2 surfaces.
    """
    lines = [
        "ISO-10303-21;",
        "HEADER;",
        "FILE_DESCRIPTION(('PhotoCAD C2 B-spline surface patches'),'2;1');",
        "FILE_NAME('photocad_patches.step','2026-01-01T00:00:00',('PhotoCAD'),('PhotoCAD'),'', '','');",
        "FILE_SCHEMA(('AUTOMOTIVE_DESIGN'));",
        "ENDSEC;",
        "DATA;",
    ]
    next_id = 1
    face_ids: List[str] = []

    def add(entity: str) -> str:
        nonlocal next_id
        reference = f"#{next_id}"
        lines.append(f"{reference}={entity};")
        next_id += 1
        return reference

    for patch in patches:
        point_ids = [
            add("CARTESIAN_POINT('',({:.6f},{:.6f},{:.6f}))".format(*point))
            for point in patch.control_points
        ]
        surface_id = add(
            "B_SPLINE_SURFACE_WITH_KNOTS('{}',{},{},({}),.UNSPECIFIED.,.F.,.F.,.F.,"
            "({}),({}),({}),({}),.UNSPECIFIED.)".format(
                patch.side,
                patch.degree_u,
                patch.degree_v,
                ",".join(point_ids),
                ",".join(str(value) for value in knot_multiplicities(patch.u_knots)),
                ",".join(str(value) for value in knot_multiplicities(patch.v_knots)),
                ",".join(f"{knot:.9f}" for knot in sorted(set(round(k, 9) for k in patch.u_knots))),
                ",".join(f"{knot:.9f}" for knot in sorted(set(round(k, 9) for k in patch.v_knots))),
            )
        )
        face_ids.append(add(f"ADVANCED_FACE('{patch.side}',(),#{surface_id[1:]},.T.)"))

    if face_ids:
        add(f"OPEN_SHELL('PhotoCAD C2 Patches',({','.join(face_ids)}))")
    lines.extend(["ENDSEC;", "END-ISO-10303-21;"])
    return "\n".join(lines)
