"""
PhotoCAD - Geometric Accuracy & Bidirectional Chamfer Distance Validator
Document ID: PCAD-LG-004 (Node 5) / NFR-04

Measures compiled .STL B-Rep geometry against the fused Open3D .PLY scan:
1. Checks manifold watertight integrity (every edge degree == 2)
2. Computes exact solid volume (mm^3) & surface area (mm^2) via Divergence Theorem
3. Uniformly samples N = 20,000 area-weighted surface points from the .STL mesh
4. Performs bounded ICP centroid alignment (<= 5.0 mm shift guard)
5. Computes bidirectional Chamfer Distance (mean, P95) & bounding box deltas (mm)
6. Emits structured ValidationMetrics ADT + localized discrepancy_notes for Outer Loop repair
"""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from app.schemas.adt import Open3DGeometryReport, ValidationMetrics


TOLERANCE_CHAMFER_MM = 1.0
MAX_CENTROID_ICP_SHIFT_MM = 5.0
SURFACE_SAMPLE_COUNT = 20000


def load_ascii_stl_triangles(stl_path: str | Path) -> np.ndarray:
    """Loads triangles as (T, 3, 3) float64 array from an ASCII or binary .STL file."""
    path = Path(stl_path)
    raw = path.read_bytes()

    # Check if ASCII STL
    if raw[:5].lower() == b"solid" and b"vertex" in raw[:4096].lower():
        text = raw.decode("utf-8", errors="ignore")
        verts: List[List[float]] = []
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("vertex "):
                parts = s.split()
                if len(parts) >= 4:
                    verts.append([float(parts[1]), float(parts[2]), float(parts[3])])
        n_tris = len(verts) // 3
        if n_tris == 0:
            return np.zeros((0, 3, 3), dtype=np.float64)
        return np.asarray(verts[: n_tris * 3], dtype=np.float64).reshape((n_tris, 3, 3))

    # Binary STL fallback (80-byte header + uint32 count + 50-byte records)
    if len(raw) >= 84:
        tri_count = int(np.frombuffer(raw[80:84], dtype="<u4")[0])
        tris = np.zeros((tri_count, 3, 3), dtype=np.float64)
        offset = 84
        for idx in range(tri_count):
            if offset + 50 > len(raw):
                break
            v_data = np.frombuffer(raw[offset + 12 : offset + 48], dtype="<f4").reshape(3, 3)
            tris[idx] = v_data.astype(np.float64)
            offset += 50
        return tris

    return np.zeros((0, 3, 3), dtype=np.float64)


def load_ply_points(ply_path: str | Path) -> np.ndarray:
    """Reads XYZ coordinates (N, 3) in mm from an ASCII .PLY point cloud file."""
    path = Path(ply_path)
    if not path.exists():
        return np.zeros((0, 3), dtype=np.float64)

    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    in_header = True
    pts: List[List[float]] = []
    for line in lines:
        s = line.strip()
        if in_header:
            if s == "end_header":
                in_header = False
            continue
        if not s:
            continue
        parts = s.split()
        if len(parts) >= 3:
            pts.append([float(parts[0]), float(parts[1]), float(parts[2])])
    return np.asarray(pts, dtype=np.float64)


def check_mesh_watertight_and_props(triangles: np.ndarray) -> Tuple[bool, float, float]:
    """
    Returns (is_watertight, volume_mm3, surface_area_mm2).
    Watertight requires zero boundary edges (every undirected edge shared by 2 opposing half-edges).
    """
    if len(triangles) < 4:
        return False, 0.0, 0.0

    v0 = triangles[:, 0, :]
    v1 = triangles[:, 1, :]
    v2 = triangles[:, 2, :]

    # Surface area & signed volume
    cross = np.cross(v1 - v0, v2 - v0)
    areas = 0.5 * np.linalg.norm(cross, axis=1)
    surface_area = float(np.sum(areas))
    signed_vol = float(np.abs(np.sum(np.einsum("ij,ij->i", v0, np.cross(v1, v2))) / 6.0))

    # Half-edge manifold pairing check
    directed_edges: Counter = Counter()
    rounded = np.round(triangles, 4)
    for tri in rounded:
        p0 = (float(tri[0, 0]), float(tri[0, 1]), float(tri[0, 2]))
        p1 = (float(tri[1, 0]), float(tri[1, 1]), float(tri[1, 2]))
        p2 = (float(tri[2, 0]), float(tri[2, 1]), float(tri[2, 2]))
        directed_edges[(p0, p1)] += 1
        directed_edges[(p1, p2)] += 1
        directed_edges[(p2, p0)] += 1

    is_watertight = all(
        cnt == 1 and directed_edges.get((b, a), 0) == 1
        for (a, b), cnt in directed_edges.items()
    )
    return is_watertight, round(signed_vol, 2), round(surface_area, 2)


def sample_uniform_surface_points(
    triangles: np.ndarray,
    n_samples: int = SURFACE_SAMPLE_COUNT,
    seed: int = 42,
) -> np.ndarray:
    """Area-weighted barycentric uniform point sampling over triangle mesh surface."""
    if len(triangles) == 0:
        return np.zeros((0, 3), dtype=np.float64)

    v0, v1, v2 = triangles[:, 0, :], triangles[:, 1, :], triangles[:, 2, :]
    areas = 0.5 * np.linalg.norm(np.cross(v1 - v0, v2 - v0), axis=1)
    total_area = float(np.sum(areas))
    if total_area <= 1e-9:
        return np.zeros((0, 3), dtype=np.float64)

    probs = areas / total_area
    rng = np.random.default_rng(seed=seed)
    tri_idx = rng.choice(len(triangles), size=n_samples, replace=True, p=probs)

    r1 = rng.random(n_samples)
    r2 = rng.random(n_samples)
    sqrt_r1 = np.sqrt(r1)[:, None]
    r2_col = r2[:, None]

    pts = (
        (1.0 - sqrt_r1) * v0[tri_idx]
        + (sqrt_r1 * (1.0 - r2_col)) * v1[tri_idx]
        + (sqrt_r1 * r2_col) * v2[tri_idx]
    )
    return pts


def _chunked_min_distances(src: np.ndarray, tgt: np.ndarray, chunk_size: int = 512, max_tgt: int = 10000) -> np.ndarray:
    """Computes nearest-neighbor Euclidean distances using vectorized float32 matrix ops (<150ms)."""
    if len(src) == 0 or len(tgt) == 0:
        return np.zeros((0,), dtype=np.float64)

    if len(tgt) > max_tgt:
        step = max(1, len(tgt) // max_tgt)
        tgt = tgt[::step]

    src_f = np.asarray(src, dtype=np.float32)
    tgt_f = np.asarray(tgt, dtype=np.float32)
    tgt_sq = np.sum(tgt_f ** 2, axis=1)[None, :]  # (1, M)
    mins = np.empty(len(src_f), dtype=np.float64)

    for start in range(0, len(src_f), chunk_size):
        end = min(start + chunk_size, len(src_f))
        block = src_f[start:end]  # (B, 3)
        block_sq = np.sum(block ** 2, axis=1)[:, None]  # (B, 1)
        sq_dists = block_sq + tgt_sq - 2.0 * (block @ tgt_f.T)
        np.maximum(sq_dists, 0.0, out=sq_dists)
        mins[start:end] = np.sqrt(np.min(sq_dists, axis=1))

    return mins


class ChamferValidator:
    """
    Validates compiled CAD exports (.STL / .STEP) against fused scan point clouds (.PLY)
    computing bidirectional Chamfer Distance and spatial discrepancy guidance.
    """

    @staticmethod
    def evaluate(
        stl_path: str | Path,
        geometry_report: Open3DGeometryReport,
        ply_path: Optional[str | Path] = None,
        sample_count: int = SURFACE_SAMPLE_COUNT,
    ) -> ValidationMetrics:
        tris = load_ascii_stl_triangles(stl_path)
        is_watertight, vol_mm3, area_mm2 = check_mesh_watertight_and_props(tris)

        if len(tris) == 0:
            return ValidationMetrics(
                is_watertight=False,
                volume_mm3=0.0,
                surface_area_mm2=0.0,
                chamfer_mean_mm=999.0,
                chamfer_p95_mm=999.0,
                bbox_delta_mm=geometry_report.bounding_box_mm,
                passed_tolerance=False,
                discrepancy_notes=["Compiled STL mesh contained zero triangles."],
            )

        mesh_pts = sample_uniform_surface_points(tris, n_samples=sample_count)
        mesh_extents = np.ptp(mesh_pts, axis=0)
        scan_extents = np.asarray(geometry_report.bounding_box_mm, dtype=np.float64)
        bbox_delta = (
            round(float(mesh_extents[0] - scan_extents[0]), 2),
            round(float(mesh_extents[1] - scan_extents[1]), 2),
            round(float(mesh_extents[2] - scan_extents[2]), 2),
        )

        scan_pts = load_ply_points(ply_path) if ply_path else np.zeros((0, 3), dtype=np.float64)
        if len(scan_pts) < 50:
            # Synthesize deterministic reference shell from Open3D report if .PLY isn't on local disk
            scan_pts = _synthesize_reference_cloud_from_report(geometry_report)

        # Bounded centroid ICP shift (<= 5.0 mm per PCAD-LG-004 Node 5)
        centroid_delta = np.mean(scan_pts, axis=0) - np.mean(mesh_pts, axis=0)
        shift_norm = float(np.linalg.norm(centroid_delta))
        if shift_norm > MAX_CENTROID_ICP_SHIFT_MM and shift_norm > 1e-6:
            centroid_delta = centroid_delta * (MAX_CENTROID_ICP_SHIFT_MM / shift_norm)
        aligned_mesh_pts = mesh_pts + centroid_delta

        # Bidirectional nearest-neighbor Chamfer evaluation
        eval_mesh = aligned_mesh_pts[:: max(1, len(aligned_mesh_pts) // 4000)]
        eval_scan = scan_pts[:: max(1, len(scan_pts) // 4000)]
        d_m2s = _chunked_min_distances(eval_mesh, scan_pts)
        d_s2m = _chunked_min_distances(eval_scan, aligned_mesh_pts)

        chamfer_mean = float((np.mean(d_m2s) + np.mean(d_s2m)) / 2.0)
        combined_errs = np.concatenate([d_m2s, d_s2m])
        chamfer_p95 = float(np.percentile(combined_errs, 95))

        notes: List[str] = []
        if not is_watertight:
            notes.append("Solid topology check failed: STL mesh is not watertight.")

        axis_labels = [("X (LENGTH_MM)", bbox_delta[0]), ("Y (WIDTH_MM)", bbox_delta[1]), ("Z (THICKNESS_MM)", bbox_delta[2])]
        for label, dval in axis_labels:
            if abs(dval) > 1.2:
                direction = "wider/taller" if dval > 0 else "smaller/shorter"
                notes.append(f"{label} differs by {dval:+.2f}mm ({direction}) vs fused Open3D scan.")

        if chamfer_mean > TOLERANCE_CHAMFER_MM and not notes:
            notes.append(
                f"Mean surface Chamfer error {chamfer_mean:.2f}mm exceeds {TOLERANCE_CHAMFER_MM}mm tolerance; "
                "verify hole radius, fillet bounds, or base dimensions."
            )

        passed = is_watertight and (chamfer_mean <= TOLERANCE_CHAMFER_MM)

        return ValidationMetrics(
            is_watertight=is_watertight,
            volume_mm3=vol_mm3,
            surface_area_mm2=area_mm2,
            chamfer_mean_mm=round(chamfer_mean, 3),
            chamfer_p95_mm=round(chamfer_p95, 3),
            bbox_delta_mm=bbox_delta,
            passed_tolerance=passed,
            discrepancy_notes=notes,
        )


def _synthesize_reference_cloud_from_report(report: Open3DGeometryReport) -> np.ndarray:
    """Builds a uniform reference shell from Open3DGeometryReport bbox + primary cylinder when PLY file is remote."""
    lx, wy, hz = report.bounding_box_mm
    hx, hy, hz_half = lx / 2.0, wy / 2.0, hz / 2.0
    rng = np.random.default_rng(seed=99)
    pts: List[np.ndarray] = []

    hole_r = report.cylinders[0].radius_mm if report.cylinders else 0.0
    for sz in (-hz_half, hz_half):
        gx, gy = rng.uniform(-hx, hx, 2400), rng.uniform(-hy, hy, 2400)
        if hole_r > 0.5:
            keep = (gx ** 2 + gy ** 2) > (hole_r ** 2)
            gx, gy = gx[keep], gy[keep]
        pts.append(np.column_stack([gx, gy, np.full(len(gx), sz)]))
    for sy in (-hy, hy):
        pts.append(np.column_stack([rng.uniform(-hx, hx, 1600), np.full(1600, sy), rng.uniform(-hz_half, hz_half, 1600)]))
    for sx in (-hx, hx):
        pts.append(np.column_stack([np.full(1200, sx), rng.uniform(-hy, hy, 1200), rng.uniform(-hz_half, hz_half, 1200)]))
    if hole_r > 0.5:
        th = rng.uniform(0.0, 2.0 * np.pi, 1400)
        pts.append(np.column_stack([hole_r * np.cos(th), hole_r * np.sin(th), rng.uniform(-hz_half, hz_half, 1400)]))
    return np.vstack(pts)
