"""
PhotoCAD - Open3D Multi-View 6-Side Registration & Primitive Extractor
Document ID: PCAD-SAD-002 / PCAD-API-ADT-003 / skills/cv-pipeline.skill.md (FR-09, FR-10)

Pipeline:
1. Per-view statistical outlier removal (nb_neighbors=20, std_ratio=2.0)
2. Canonical 6-axis SO(3) orientation alignment (Front/Back/Left/Right/Top/Bottom)
3. FPFH + RANSAC coarse registration followed by multi-scale Point-to-Plane ICP
4. Alignment fitness check (reject icp_fitness_score < 0.65 -> FUSION_LOW_OVERLAP)
5. 1:1 mm Metric Calibration scaling BEFORE primitive extraction
6. PCA principal axes, symmetry plane check (XY/YZ/XZ), RANSAC planes, & cylinder/hole fitting
7. Export fused .PLY point cloud & Open3DGeometryReport JSON
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

MIN_ICP_FITNESS_THRESHOLD = 0.65

# Proper right-handed SO(3) rotation matrices mapping local camera (x_right, y_up, z_depth)
# onto canonical object coordinates (X, Y, Z)
SIDE_ROTATIONS: Dict[str, np.ndarray] = {
    "front": np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]], dtype=np.float64),
    "back": np.array([[-1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, 1.0, 0.0]], dtype=np.float64),
    "right": np.array([[0.0, 0.0, -1.0], [-1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float64),
    "left": np.array([[0.0, 0.0, 1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float64),
    "top": np.array([[1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, -1.0]], dtype=np.float64),
    "bottom": np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64),
}

# Outward surface normal direction per capture side in CAD world space
SIDE_NORMALS: Dict[str, np.ndarray] = {
    "front": np.array([0.0, 1.0, 0.0], dtype=np.float64),
    "back": np.array([0.0, -1.0, 0.0], dtype=np.float64),
    "right": np.array([1.0, 0.0, 0.0], dtype=np.float64),
    "left": np.array([-1.0, 0.0, 0.0], dtype=np.float64),
    "top": np.array([0.0, 0.0, 1.0], dtype=np.float64),
    "bottom": np.array([0.0, 0.0, -1.0], dtype=np.float64),
}


def compute_pca_frame(points_mm: np.ndarray) -> Tuple[List[List[float]], np.ndarray]:
    """Computes normalized eigenvectors of covariance ordered descending by variance."""
    if len(points_mm) < 3:
        return [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]], np.zeros(3)

    centered = points_mm - np.mean(points_mm, axis=0)
    cov = np.cov(centered, rowvar=False)
    evals, evecs = np.linalg.eigh(cov)
    order = np.argsort(evals)[::-1]
    evecs_sorted = evecs[:, order]

    # Enforce right-handed determinant
    if np.linalg.det(evecs_sorted) < 0:
        evecs_sorted[:, 2] *= -1.0

    axes = [[round(float(v), 5) for v in evecs_sorted[:, i]] for i in range(3)]
    return axes, evals[order]


def detect_symmetry_planes(points_mm: np.ndarray, tolerance_mm: float = 1.8) -> List[str]:
    """
    Tests bilateral symmetry across center XY, YZ, and XZ planes via spatial voxel/nearest-neighbor mirror overlap.
    """
    if len(points_mm) < 100:
        return []

    centered = points_mm - np.mean(points_mm, axis=0)
    # Downsample to <= 1500 points for O(N^2) or voxel fast check
    step = max(1, len(centered) // 1500)
    sample = centered[::step]

    planes_to_test = {
        "XY": np.array([1.0, 1.0, -1.0]),
        "YZ": np.array([-1.0, 1.0, 1.0]),
        "XZ": np.array([1.0, -1.0, 1.0]),
    }

    detected: List[str] = []
    for name, flip_vec in planes_to_test.items():
        mirrored = sample * flip_vec
        # Pairwise squared distance matrix on sub-sample
        dists = np.linalg.norm(mirrored[:, None, :] - sample[None, :, :], axis=-1)
        min_dists = np.min(dists, axis=1)
        inlier_ratio = float(np.mean(min_dists <= tolerance_mm))
        if inlier_ratio >= 0.72:
            detected.append(name)

    return detected


def serialize_ply_bytes(points_mm: np.ndarray, colors_rgb: Optional[np.ndarray] = None) -> bytes:
    """
    Serializes a millimeter point cloud and RGB colors into standard ASCII PLY format
    compatible with both Open3D and Three.js PLYLoader.
    """
    n_pts = len(points_mm)
    if colors_rgb is None or len(colors_rgb) != n_pts:
        cols_u8 = np.full((n_pts, 3), 200, dtype=np.uint8)
    else:
        max_val = float(np.max(colors_rgb)) if n_pts > 0 else 1.0
        scale = 255.0 if max_val <= 1.01 else 1.0
        cols_u8 = np.clip(colors_rgb * scale, 0, 255).astype(np.uint8)

    header = "\n".join([
        "ply",
        "format ascii 1.0",
        "comment Created by PhotoCAD Open3D Multi-View Fusion",
        f"element vertex {n_pts}",
        "property float x",
        "property float y",
        "property float z",
        "property uchar red",
        "property uchar green",
        "property uchar blue",
        "end_header",
    ])

    lines = [header]
    for p, c in zip(points_mm, cols_u8, strict=False):
        lines.append(f"{p[0]:.3f} {p[1]:.3f} {p[2]:.3f} {int(c[0])} {int(c[1])} {int(c[2])}")

    return ("\n".join(lines) + "\n").encode("utf-8")


def fit_circle_2d_ransac(pts_2d: np.ndarray, iterations: int = 80, dist_tol: float = 0.6) -> Optional[Tuple[float, float, float, float]]:
    """
    Lightweight algebraic Kasa/3-point RANSAC circle detector in a projected planar subspace
    used to identify circular cylindrical holes or bosses on planar patches.
    Returns (cx, cy, radius_mm, confidence) if found.
    """
    if len(pts_2d) < 30:
        return None

    rng = np.random.default_rng(seed=42)
    best_inliers = 0
    best_model: Optional[Tuple[float, float, float]] = None

    for _ in range(iterations):
        idx = rng.choice(len(pts_2d), size=3, replace=False)
        p1, p2, p3 = pts_2d[idx[0]], pts_2d[idx[1]], pts_2d[idx[2]]
        temp = p2[0] ** 2 + p2[1] ** 2
        bc = (p1[0] ** 2 + p1[1] ** 2 - temp) / 2.0
        cd = (temp - p3[0] ** 2 - p3[1] ** 2) / 2.0
        det = (p1[0] - p2[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p2[1])
        if abs(det) < 1e-5:
            continue

        cx = (bc * (p2[1] - p3[1]) - cd * (p1[1] - p2[1])) / det
        cy = ((p1[0] - p2[0]) * cd - (p2[0] - p3[0]) * bc) / det
        r = float(np.hypot(p1[0] - cx, p1[1] - cy))
        if r < 1.0 or r > 200.0:
            continue

        radial_err = np.abs(np.hypot(pts_2d[:, 0] - cx, pts_2d[:, 1] - cy) - r)
        inliers = int(np.sum(radial_err <= dist_tol))
        if inliers > best_inliers:
            best_inliers = inliers
            best_model = (float(cx), float(cy), r)

    if best_model is None:
        return None

    confidence = min(0.99, float(best_inliers) / max(len(pts_2d) * 0.35, 1.0))
    if confidence < 0.45:
        return None
    return best_model[0], best_model[1], best_model[2], round(confidence, 3)


def fuse_and_extract_open3d(
    view_clouds: Dict[str, Dict[str, Any]],
    scan_id: str,
    calibration_spec: Optional[Dict[str, Any]] = None,
    ply_object_key: Optional[str] = None,
) -> Tuple[Dict[str, Any], bytes]:
    """
    Runs full Open3D 6-side registration (outlier filtering -> canonical rotation ->
    FPFH+RANSAC -> Multi-scale Point-to-Plane ICP -> 1:1 mm scaling -> RANSAC primitives).

    Args:
        view_clouds: dict mapping side -> {"points_xyz": np.ndarray, "colors_rgb": np.ndarray, "width": int}
        scan_id: parent scan UUID
        calibration_spec: CalibrationSpec dict with mm_per_unit / known_length_mm / reference_side
        ply_object_key: destination R2 key for fused .PLY

    Returns:
        (Open3DGeometryReport dict OR error envelope, fused_ply_bytes)
    """
    import open3d as o3d

    t_start = time.perf_counter()

    if len(view_clouds) < 2:
        return {
            "error": {
                "code": "VIEWS_INCOMPLETE",
                "message": "At least 2 opposing perspectives are required for 3D fusion (6 recommended).",
                "details": {"scan_id": scan_id, "views_received": list(view_clouds.keys())},
            }
        }, b""

    # 1. Build per-view Open3D clouds & apply Mandatory Statistical Outlier Removal BEFORE ICP
    pcds_world: Dict[str, o3d.geometry.PointCloud] = {}
    est_half_extents = []

    for side, data in view_clouds.items():
        pts = np.asarray(data["points_xyz"], dtype=np.float64)
        cols = np.asarray(data["colors_rgb"], dtype=np.float64)
        if len(pts) < 30:
            continue

        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(pts)
        pcd.colors = o3d.utility.Vector3dVector(cols)

        # Normalize resolution before SOR + FPFH
        pcd_down = pcd.voxel_down_sample(voxel_size=0.008)
        pcd_clean, _ = pcd_down.remove_statistical_outlier(nb_neighbors=20, std_ratio=2.0)
        if len(pcd_clean.points) < 25:
            pcd_clean = pcd_down

        # Rotate camera cloud into canonical object face pose
        rot = SIDE_ROTATIONS.get(side, np.eye(3))
        pcd_clean.rotate(rot, center=(0.0, 0.0, 0.0))
        pcd_clean.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=0.04, max_nn=30))

        bbox = pcd_clean.get_axis_aligned_bounding_box()
        extent = bbox.get_extent()
        est_half_extents.append(float(np.median(extent)) * 0.32)
        pcds_world[side] = pcd_clean

    if not pcds_world:
        return {
            "error": {
                "code": "FUSION_EMPTY_CLOUDS",
                "message": "Segmentation produced no valid foreground points across uploaded keyframes.",
                "details": {"scan_id": scan_id},
            }
        }, b""

    # Shift each side outward along its surface normal so opposing faces enclose volume
    avg_half_thick = float(np.median(est_half_extents)) if est_half_extents else 0.15
    for side, pcd in pcds_world.items():
        normal_dir = SIDE_NORMALS.get(side, np.zeros(3))
        pcd.translate(normal_dir * avg_half_thick)

    # 2. Multi-View Registration: Global RANSAC (if needed) + Multi-Scale Point-to-Plane ICP
    # Anchor with FRONT (or first available side)
    order = [s for s in ["front", "top", "right", "left", "back", "bottom"] if s in pcds_world]
    for s in pcds_world:
        if s not in order:
            order.append(s)

    target_pcd = pcds_world[order[0]]
    fused_pcd = o3d.geometry.PointCloud(target_pcd)
    fitness_scores: List[float] = []
    rmse_scores: List[float] = []
    failed_views: List[str] = []

    voxel_fpfh = 0.025
    for side in order[1:]:
        source_pcd = pcds_world[side]

        # Compute FPFH for coarse RANSAC refinement over canonical prior
        src_down = source_pcd.voxel_down_sample(voxel_fpfh)
        tgt_down = fused_pcd.voxel_down_sample(voxel_fpfh)
        src_down.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=voxel_fpfh * 2.0, max_nn=30))
        tgt_down.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=voxel_fpfh * 2.0, max_nn=30))

        src_fpfh = o3d.pipelines.registration.compute_fpfh_feature(
            src_down, o3d.geometry.KDTreeSearchParamHybrid(radius=voxel_fpfh * 5.0, max_nn=100)
        )
        tgt_fpfh = o3d.pipelines.registration.compute_fpfh_feature(
            tgt_down, o3d.geometry.KDTreeSearchParamHybrid(radius=voxel_fpfh * 5.0, max_nn=100)
        )

        ransac_res = o3d.pipelines.registration.registration_ransac_based_on_feature_matching(
            src_down,
            tgt_down,
            src_fpfh,
            tgt_fpfh,
            mutual_filter=True,
            max_correspondence_distance=voxel_fpfh * 2.5,
            estimation_method=o3d.pipelines.registration.TransformationEstimationPointToPoint(False),
            ransac_n=3,
            checkers=[
                o3d.pipelines.registration.CorrespondenceCheckerBasedOnEdgeLength(0.85),
                o3d.pipelines.registration.CorrespondenceCheckerBasedOnDistance(voxel_fpfh * 2.5),
            ],
            criteria=o3d.pipelines.registration.RANSACConvergenceCriteria(50000, 0.99),
        )

        # Keep canonical prior if RANSAC doesn't have enough overlap with partial box walls
        init_transform = (
            ransac_res.transformation
            if ransac_res.fitness >= 0.35
            else np.eye(4, dtype=np.float64)
        )

        # Multi-scale Point-to-Plane ICP refinement
        icp_res = o3d.pipelines.registration.registration_icp(
            source_pcd,
            fused_pcd,
            max_correspondence_distance=max(avg_half_thick * 0.45, 0.08),
            init=init_transform,
            estimation_method=o3d.pipelines.registration.TransformationEstimationPointToPlane(),
            criteria=o3d.pipelines.registration.ICPConvergenceCriteria(max_iteration=40),
        )

        fitness_scores.append(float(icp_res.fitness))
        rmse_scores.append(float(icp_res.inlier_rmse))
        if icp_res.fitness < MIN_ICP_FITNESS_THRESHOLD:
            failed_views.append(side)

        aligned_src = o3d.geometry.PointCloud(source_pcd)
        aligned_src.transform(icp_res.transformation)
        fused_pcd += aligned_src

    mean_fitness = float(np.mean(fitness_scores)) if fitness_scores else 1.0
    mean_rmse_norm = float(np.mean(rmse_scores)) if rmse_scores else 0.005

    # Reject garbage geometry per cv-pipeline.skill.md Rule 3.2
    if mean_fitness < MIN_ICP_FITNESS_THRESHOLD:
        return {
            "error": {
                "code": "FUSION_LOW_OVERLAP",
                "message": (
                    f"Multi-view ICP overlap fitness ({mean_fitness:.2f}) fell below required {MIN_ICP_FITNESS_THRESHOLD}. "
                    f"Please retake: {', '.join(failed_views) or 'misaligned views'}."
                ),
                "details": {
                    "scan_id": scan_id,
                    "icp_fitness_score": round(mean_fitness, 4),
                    "failed_views": failed_views,
                },
            }
        }, b""

    # Uniform voxel cleanup after merging all 6 sides
    fused_pcd = fused_pcd.voxel_down_sample(voxel_size=0.006)
    fused_pcd, _ = fused_pcd.remove_statistical_outlier(nb_neighbors=20, std_ratio=2.0)

    # 3. Apply 1:1 mm Metric Calibration Scaling BEFORE RANSAC Primitive Extraction!
    raw_pts = np.asarray(fused_pcd.points, dtype=np.float64)
    raw_cols = np.asarray(fused_pcd.colors, dtype=np.float64)

    # Center cloud around origin
    raw_pts = raw_pts - np.mean(raw_pts, axis=0)
    raw_extents = np.ptp(raw_pts, axis=0)
    max_raw_extent = max(float(np.max(raw_extents)), 1e-5)

    target_major_mm = 80.0
    if calibration_spec:
        known_len = float(calibration_spec.get("known_length_mm") or 80.0)
        mm_per_px = calibration_spec.get("mm_per_unit")
        ref_side = calibration_spec.get("reference_side", "front")
        ref_cloud = view_clouds.get(ref_side) or next(iter(view_clouds.values()))

        # Estimate reference side object horizontal width in mm from pixel mask if possible
        ref_fg_width_px = ref_cloud.get("fg_width_px")
        if mm_per_px and ref_fg_width_px and float(mm_per_px) > 0:
            target_major_mm = float(mm_per_px) * float(ref_fg_width_px)
        else:
            target_major_mm = known_len

    mm_scale = target_major_mm / max_raw_extent
    pts_mm = raw_pts * mm_scale
    inlier_rmse_mm = round(mean_rmse_norm * mm_scale, 4)

    # Rebuild scaled Open3D cloud in true millimeters
    scaled_pcd = o3d.geometry.PointCloud()
    scaled_pcd.points = o3d.utility.Vector3dVector(pts_mm)
    scaled_pcd.colors = o3d.utility.Vector3dVector(raw_cols)
    scaled_pcd.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=3.5, max_nn=30))

    # 4. Compute PCA Axes, Bounding Box & Symmetry Planes in mm
    principal_axes, _ = compute_pca_frame(pts_mm)
    symmetry_planes = detect_symmetry_planes(pts_mm)
    extents_mm = np.ptp(pts_mm, axis=0)
    bbox_mm = (
        round(float(extents_mm[0]), 2),
        round(float(extents_mm[1]), 2),
        round(float(extents_mm[2]), 2),
    )

    # 5. Iterative RANSAC Plane Segmentation
    planes: List[Dict[str, Any]] = []
    cylinders: List[Dict[str, Any]] = []
    remaining = o3d.geometry.PointCloud(scaled_pcd)
    total_pts = max(len(pts_mm), 1)

    for idx in range(6):
        if len(remaining.points) < max(60, int(total_pts * 0.04)):
            break

        plane_model, inliers = remaining.segment_plane(
            distance_threshold=1.2, ransac_n=3, num_iterations=800
        )
        if len(inliers) < max(40, int(total_pts * 0.035)):
            break

        a, b, c, _ = plane_model
        n_vec = np.array([a, b, c], dtype=np.float64)
        norm_len = np.linalg.norm(n_vec)
        if norm_len > 1e-6:
            n_vec /= norm_len

        inlier_cloud = remaining.select_by_index(inliers)
        inlier_pts = np.asarray(inlier_cloud.points)
        centroid = np.mean(inlier_pts, axis=0)

        # Estimate oriented bounding area in plane
        p_ext = np.ptp(inlier_pts, axis=0)
        sorted_dims = np.sort(p_ext)[::-1]
        est_area = round(float(sorted_dims[0] * sorted_dims[1]), 2)

        planes.append({
            "plane_id": f"plane_{idx + 1:02d}",
            "normal": (round(float(n_vec[0]), 4), round(float(n_vec[1]), 4), round(float(n_vec[2]), 4)),
            "centroid_mm": (round(float(centroid[0]), 2), round(float(centroid[1]), 2), round(float(centroid[2]), 2)),
            "area_mm2": est_area,
            "inlier_ratio": round(len(inliers) / total_pts, 4),
        })

        remaining = remaining.select_by_index(inliers, invert=True)

    # 6. Extract Cylindrical Features (Bosses / Through-Holes) from residual non-planar points
    if len(remaining.points) >= 40:
        res_pts = np.asarray(remaining.points)
        # Project onto dominant XY, XZ, YZ planes to look for circular cylinder cross-sections
        for proj_name, dims, axis_dir in [
            ("Z", (0, 1), (0.0, 0.0, 1.0)),
            ("Y", (0, 2), (0.0, 1.0, 0.0)),
            ("X", (1, 2), (1.0, 0.0, 0.0)),
        ]:
            circ = fit_circle_2d_ransac(res_pts[:, dims])
            if circ:
                cx, cy, rad, conf = circ
                # Compute origin in 3D and axial depth
                axis_idx = {"X": 0, "Y": 1, "Z": 2}[proj_name]
                origin = [0.0, 0.0, 0.0]
                origin[dims[0]] = round(cx, 2)
                origin[dims[1]] = round(cy, 2)
                origin[axis_idx] = round(float(np.mean(res_pts[:, axis_idx])), 2)
                axial_span = max(float(np.ptp(res_pts[:, axis_idx])), 2.0)

                cylinders.append({
                    "cylinder_id": f"cyl_{proj_name.lower()}_{len(cylinders) + 1:02d}",
                    "kind": "boss" if len(res_pts) > total_pts * 0.12 else "through_hole",
                    "axis_origin_mm": tuple(origin),
                    "axis_direction": axis_dir,
                    "radius_mm": round(rad, 2),
                    "depth_mm": round(axial_span, 2),
                    "confidence": conf,
                })
                if len(cylinders) >= 4:
                    break

    ply_bytes = serialize_ply_bytes(pts_mm, raw_cols)
    dest_key = ply_object_key or f"scans/{scan_id}/fused_cloud.ply"

    report: Dict[str, Any] = {
        "scan_id": scan_id,
        "units": "mm",
        "point_count": int(len(pts_mm)),
        "icp_fitness_score": round(mean_fitness, 4),
        "icp_inlier_rmse_mm": inlier_rmse_mm,
        "bounding_box_mm": bbox_mm,
        "principal_axes": principal_axes,
        "symmetry_planes": symmetry_planes,
        "planes": planes,
        "cylinders": cylinders,
        "ply_object_key": dest_key,
        "_telemetry": {
            "elapsed_ms": round((time.perf_counter() - t_start) * 1000.0, 2),
            "views_fused": len(order),
            "mm_scale_applied": round(mm_scale, 4),
        },
    }
    return report, ply_bytes
