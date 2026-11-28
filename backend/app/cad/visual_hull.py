"""
PhotoCAD - Multi-View Foreground Segmentation & 3D Volumetric Visual Hull Builder
Document ID: PCAD-SAD-002 / Phase 3-4 Upgrade

Reconstructs genuine 3D sculpted surface point clouds (.PLY), watertight manifold meshes (.STL),
2D orthographic contour blueprints (.DXF), and faceted closed-shell B-Rep solids (.STEP)
across 4 to 6 orthogonal camera/photo views using:
1. Studio matte vs cluttered-background GrabCut foreground isolation (+ YCrCb border skin stripping)
2. Euler interior circular hole detection (avoids fabricating nonexistent through-bores)
3. Automatic Top/Bottom orientation matching against Front/Side aspect ratios
4. 6-Axis Volumetric Voxel Visual Hull Carving + Non-Manifold Pinch Cleanup + Taubin Smoothing
"""

from __future__ import annotations

import io
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image


def extract_foreground_mask(rgb_arr: np.ndarray) -> Tuple[np.ndarray, int]:
    """
    Isolates the foreground object from handheld skin/fingers and either uniform studio backdrops
    or cluttered outdoor/desk backgrounds via border-clamped GrabCut + connected-component filtering.
    """
    h, w = rgb_arr.shape[:2]

    # 1. Strip border-connected human skin components (hands holding object)
    ycrcb = cv2.cvtColor(rgb_arr, cv2.COLOR_RGB2YCrCb)
    skin_u8 = cv2.inRange(ycrcb, np.array([40, 133, 77]), np.array([245, 173, 127]))
    num_s, s_labels, s_stats, _ = cv2.connectedComponentsWithStats(skin_u8, connectivity=8)
    hand_mask = np.zeros((h, w), dtype=bool)
    margin_x, margin_y = max(3, int(w * 0.03)), max(3, int(h * 0.03))
    for lbl in range(1, num_s):
        x, y, bw, bh, area = s_stats[lbl]
        if area < 25:
            continue
        if x <= margin_x or y <= margin_y or (x + bw) >= (w - margin_x) or (y + bh) >= (h - margin_y):
            hand_mask |= s_labels == lbl
    hand_suppressed = int(np.sum(hand_mask))

    # 2. Measure perimeter backdrop uniformity (ignoring hand/skin regions on border)
    pad = max(2, min(h, w) // 40)
    border_mask = np.zeros((h, w), dtype=bool)
    border_mask[:pad, :] = True
    border_mask[-pad:, :] = True
    border_mask[:, :pad] = True
    border_mask[:, -pad:] = True
    clean_border = rgb_arr[border_mask & (~hand_mask)]
    if len(clean_border) < 20:
        clean_border = rgb_arr[border_mask]

    bg_median = np.median(clean_border, axis=0)
    bg_std = float(np.mean(np.std(clean_border.astype(np.float32), axis=0)))

    if bg_std < 18.0:
        # Uniform studio backdrop or synthetic solid image
        color_dist = np.linalg.norm(rgb_arr.astype(np.float32) - bg_median.astype(np.float32), axis=-1)
        fg_mask = (color_dist > 20.0) & (~hand_mask)
    else:
        # Cluttered real-world background (outdoor, desk, scenery) -> downsampled GrabCut
        scale = min(1.0, 220.0 / float(max(h, w)))
        sw = max(32, int(round(w * scale)))
        sh = max(32, int(round(h * scale)))
        small_bgr = cv2.cvtColor(cv2.resize(rgb_arr, (sw, sh), interpolation=cv2.INTER_AREA), cv2.COLOR_RGB2BGR)
        small_hand = cv2.resize(hand_mask.astype(np.uint8), (sw, sh), interpolation=cv2.INTER_NEAREST) > 0

        gc_mask = np.full((sh, sw), cv2.GC_PR_BGD, dtype=np.uint8)
        bx, by = max(2, int(sw * 0.04)), max(2, int(sh * 0.04))
        cx0, cx1 = max(bx + 1, int(sw * 0.08)), min(sw - bx - 1, int(sw * 0.92))
        cy0, cy1 = max(by + 1, int(sh * 0.10)), min(sh - by - 1, int(sh * 0.90))
        gc_mask[cy0:cy1, cx0:cx1] = cv2.GC_PR_FGD
        gc_mask[:by, :] = cv2.GC_BGD
        gc_mask[-by:, :] = cv2.GC_BGD
        gc_mask[:, :bx] = cv2.GC_BGD
        gc_mask[:, -bx:] = cv2.GC_BGD
        gc_mask[small_hand] = cv2.GC_BGD

        bg_model = np.zeros((1, 65), np.float64)
        fg_model = np.zeros((1, 65), np.float64)
        try:
            cv2.grabCut(small_bgr, gc_mask, None, bg_model, fg_model, 4, cv2.GC_INIT_WITH_MASK)  # type: ignore[call-overload]
            fg_small = ((gc_mask == cv2.GC_FGD) | (gc_mask == cv2.GC_PR_FGD)).astype(np.uint8)
        except Exception:
            fg_small = np.ones((sh, sw), dtype=np.uint8)

        # Fallback if GrabCut over-trimmed or failed to isolate object
        cov = float(np.mean(fg_small))
        if cov < 0.04 or cov > 0.92:
            lab_small = cv2.cvtColor(small_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
            b_med = np.median(lab_small[:by, :, :].reshape(-1, 3), axis=0)
            dist_lab = np.linalg.norm(lab_small - b_med, axis=-1)
            thresh = float(np.percentile(dist_lab, 45))
            fg_small = (dist_lab > max(thresh, 14.0)).astype(np.uint8)
            fg_small[:by, :] = 0
            fg_small[-by:, :] = 0
            fg_small[:, :bx] = 0
            fg_small[:, -bx:] = 0

        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        fg_small = cv2.morphologyEx(fg_small, cv2.MORPH_CLOSE, kernel)
        fg_mask = cv2.resize(fg_small, (w, h), interpolation=cv2.INTER_NEAREST) > 0
        fg_mask &= ~hand_mask

    # Keep dominant foreground region + large nearby components (e.g., wheels/mirrors)
    fg_u8 = fg_mask.astype(np.uint8)
    n_lbl, lbls, stats, _ = cv2.connectedComponentsWithStats(fg_u8, connectivity=8)
    if n_lbl > 1:
        areas = stats[1:, cv2.CC_STAT_AREA]
        max_area = int(np.max(areas)) if len(areas) else 0
        cleaned = np.zeros((h, w), dtype=bool)
        for idx in range(1, n_lbl):
            if stats[idx, cv2.CC_STAT_AREA] >= max(36, int(max_area * 0.08)):
                cleaned |= lbls == idx
        fg_mask = cleaned

    if float(np.mean(fg_mask)) < 0.025:
        fg_mask = np.zeros((h, w), dtype=bool)
        fg_mask[int(h * 0.18) : int(h * 0.82), int(w * 0.18) : int(w * 0.82)] = True

    return fg_mask, hand_suppressed


def detect_interior_circular_hole(mask: np.ndarray) -> Optional[Tuple[float, float, float]]:
    """
    Checks whether a binary mask contains an authentic enclosed circular through-hole.
    Returns normalized (cx_norm in [-0.5..0.5], cy_norm in [-0.5..0.5], radius_ratio) or None.
    """
    ys, xs = np.where(mask)
    if len(xs) < 40:
        return None
    x0, x1 = int(np.min(xs)), int(np.max(xs))
    y0, y1 = int(np.min(ys)), int(np.max(ys))
    crop = mask[y0 : y1 + 1, x0 : x1 + 1].astype(np.uint8) * 255
    ch, cw = crop.shape
    if ch < 12 or cw < 12:
        return None

    contours, hierarchy = cv2.findContours(crop, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return None

    fg_area = max(float(np.sum(crop > 0)), 1.0)
    hier = hierarchy[0]
    for idx, cnt in enumerate(contours):
        # RETR_CCOMP: hierarchy[idx][3] >= 0 means it is a child interior hole inside an outer contour
        if hier[idx][3] < 0:
            continue
        area = float(cv2.contourArea(cnt))
        if area < fg_area * 0.015 or area > fg_area * 0.55:
            continue
        perim = float(cv2.arcLength(cnt, True))
        if perim <= 1e-4:
            continue
        circularity = (4.0 * math.pi * area) / (perim * perim)
        if circularity < 0.55:
            continue

        (hx_c, hy_c), rad_px = cv2.minEnclosingCircle(cnt)
        min_span = float(min(cw, ch))
        return (
            round(float(hx_c) / float(cw) - 0.5, 4),
            round(float(hy_c) / float(ch) - 0.5, 4),
            round(float(rad_px) / max(min_span, 1.0), 4),
        )
    return None


def extract_normalized_polygon(mask: np.ndarray, max_pts: int = 36) -> List[Tuple[float, float]]:
    """Extracts a simplified closed outer boundary polygon normalized into [-0.5..0.5, -0.5..0.5]."""
    ys, xs = np.where(mask)
    if len(xs) < 16:
        return [(-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)]

    x0, x1 = int(np.min(xs)), int(np.max(xs))
    y0, y1 = int(np.min(ys)), int(np.max(ys))
    crop = (mask[y0 : y1 + 1, x0 : x1 + 1].astype(np.uint8)) * 255
    ch, cw = crop.shape
    padded = cv2.copyMakeBorder(crop, 2, 2, 2, 2, cv2.BORDER_CONSTANT, value=0)
    contours, _ = cv2.findContours(padded, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return [(-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)]

    largest = max(contours, key=cv2.contourArea)
    perim = float(cv2.arcLength(largest, True))
    eps = max(0.012 * perim, 1.5)
    approx = cv2.approxPolyDP(largest, eps, True).reshape(-1, 2)
    while len(approx) > max_pts and eps < perim * 0.15:
        eps *= 1.35
        approx = cv2.approxPolyDP(largest, eps, True).reshape(-1, 2)

    pts: List[Tuple[float, float]] = []
    for px, py in approx:
        nx = ((float(px) - 2.0) / max(float(cw - 1), 1.0)) - 0.5
        ny = 0.5 - ((float(py) - 2.0) / max(float(ch - 1), 1.0))
        pts.append((round(max(-0.5, min(0.5, nx)), 4), round(max(-0.5, min(0.5, ny)), 4)))
    return pts if len(pts) >= 3 else [(-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)]


def _resize_mask_crop(mask: np.ndarray, target_w: int, target_h: int) -> np.ndarray:
    """Crops mask to its tight foreground bounding box and resizes to (target_w, target_h) bool grid."""
    ys, xs = np.where(mask)
    if len(xs) < 4:
        return np.ones((target_h, target_w), dtype=bool)
    crop = mask[int(np.min(ys)) : int(np.max(ys)) + 1, int(np.min(xs)) : int(np.max(xs)) + 1].astype(np.float32)
    resized = cv2.resize(crop, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
    return resized >= 0.45


def _resolve_non_manifold_pinches(occ: np.ndarray) -> np.ndarray:
    """
    Eliminates diagonal 2x2 checkerboard edge pinches across all XY, XZ, YZ planes so the outer
    boundary forms a strictly 2-manifold closed surface (every edge shared by exactly 2 triangles).
    """
    grid = occ.copy()
    nx, ny, nz = grid.shape
    for _ in range(12):
        changed = False
        # XY slices (edges along Z)
        a = grid[:-1, :-1, :]
        b = grid[1:, :-1, :]
        c = grid[:-1, 1:, :]
        d = grid[1:, 1:, :]
        p1 = a & d & (~b) & (~c)
        p2 = b & c & (~a) & (~d)
        if np.any(p1) or np.any(p2):
            grid[1:, :-1, :] |= p1
            grid[:-1, :-1, :] |= p2
            changed = True

        # XZ slices (edges along Y)
        a = grid[:-1, :, :-1]
        b = grid[1:, :, :-1]
        c = grid[:-1, :, 1:]
        d = grid[1:, :, 1:]
        p1 = a & d & (~b) & (~c)
        p2 = b & c & (~a) & (~d)
        if np.any(p1) or np.any(p2):
            grid[1:, :, :-1] |= p1
            grid[:-1, :, :-1] |= p2
            changed = True

        # YZ slices (edges along X)
        a = grid[:, :-1, :-1]
        b = grid[:, 1:, :-1]
        c = grid[:, :-1, 1:]
        d = grid[:, 1:, 1:]
        p1 = a & d & (~b) & (~c)
        p2 = b & c & (~a) & (~d)
        if np.any(p1) or np.any(p2):
            grid[:, 1:, :-1] |= p1
            grid[:, :-1, :-1] |= p2
            changed = True

        if not changed:
            break
    return grid


def _extract_smoothed_manifold_mesh(
    occ: np.ndarray,
    length_x: float,
    width_y: float,
    height_z: float,
    smooth_iters: int = 3,
) -> Tuple[List[List[float]], List[List[int]]]:
    """
    Extracts outward boundary quads of a pinch-free 3D boolean grid, performs Taubin smoothing
    preserving closed manifold topology, and returns (vertices_mm, triangles_idx).
    """
    clean = _resolve_non_manifold_pinches(occ)
    nx, ny, nz = clean.shape

    hx, hy, hz = length_x / 2.0, width_y / 2.0, height_z / 2.0
    dx = length_x / float(nx)
    dy = width_y / float(ny)
    dz = height_z / float(nz)

    vert_map: Dict[Tuple[int, int, int], int] = {}
    verts: List[List[float]] = []

    def vid(ix: int, iy: int, iz: int) -> int:
        key = (ix, iy, iz)
        existing = vert_map.get(key)
        if existing is not None:
            return existing
        idx = len(verts)
        vert_map[key] = idx
        verts.append([
            -hx + float(ix) * dx,
            -hy + float(iy) * dy,
            -hz + float(iz) * dz,
        ])
        return idx

    quads: List[Tuple[int, int, int, int]] = []
    for ix in range(nx):
        for iy in range(ny):
            for iz in range(nz):
                if not clean[ix, iy, iz]:
                    continue
                if ix == 0 or not clean[ix - 1, iy, iz]:
                    quads.append((vid(ix, iy, iz), vid(ix, iy, iz + 1), vid(ix, iy + 1, iz + 1), vid(ix, iy + 1, iz)))
                if ix == nx - 1 or not clean[ix + 1, iy, iz]:
                    quads.append((vid(ix + 1, iy, iz), vid(ix + 1, iy + 1, iz), vid(ix + 1, iy + 1, iz + 1), vid(ix + 1, iy, iz + 1)))
                if iy == 0 or not clean[ix, iy - 1, iz]:
                    quads.append((vid(ix, iy, iz), vid(ix + 1, iy, iz), vid(ix + 1, iy, iz + 1), vid(ix, iy, iz + 1)))
                if iy == ny - 1 or not clean[ix, iy + 1, iz]:
                    quads.append((vid(ix, iy + 1, iz), vid(ix, iy + 1, iz + 1), vid(ix + 1, iy + 1, iz + 1), vid(ix + 1, iy + 1, iz)))
                if iz == 0 or not clean[ix, iy, iz - 1]:
                    quads.append((vid(ix, iy, iz), vid(ix, iy + 1, iz), vid(ix + 1, iy + 1, iz), vid(ix + 1, iy, iz)))
                if iz == nz - 1 or not clean[ix, iy, iz + 1]:
                    quads.append((vid(ix, iy, iz + 1), vid(ix + 1, iy, iz + 1), vid(ix + 1, iy + 1, iz + 1), vid(ix, iy + 1, iz + 1)))

    # Build vertex adjacency for Taubin shrink-expand smoothing
    n_v = len(verts)
    adj: List[set] = [set() for _ in range(n_v)]
    for v0, v1, v2, v3 in quads:
        for u, w in ((v0, v1), (v1, v2), (v2, v3), (v3, v0)):
            adj[u].add(w)
            adj[w].add(u)

    coords = np.asarray(verts, dtype=np.float64)
    if smooth_iters > 0 and n_v > 0:
        for _ in range(smooth_iters):
            for factor in (0.40, -0.42):
                next_c = coords.copy()
                for vi, nbrs in enumerate(adj):
                    if nbrs:
                        mean_nbr = np.mean(coords[list(nbrs)], axis=0)
                        next_c[vi] = coords[vi] + factor * (mean_nbr - coords[vi])
                coords = next_c

        # Re-normalize bounding box strictly back to (length_x, width_y, height_z) after smoothing
        mins = np.min(coords, axis=0)
        maxs = np.max(coords, axis=0)
        ext = np.maximum(maxs - mins, 1e-6)
        target_ext = np.array([length_x, width_y, height_z], dtype=np.float64)
        center = (mins + maxs) / 2.0
        coords = ((coords - center) / ext) * target_ext

    tris: List[List[int]] = []
    for v0, v1, v2, v3 in quads:
        tris.append([v0, v1, v2])
        tris.append([v0, v2, v3])

    verts_out = [[round(float(x), 4), round(float(y), 4), round(float(z), 4)] for x, y, z in coords]
    return verts_out, tris


def carve_visual_hull_from_views(
    scan_id: str,
    view_images: Dict[str, Optional[bytes]],
    calibration_spec: Dict[str, Any],
    hull_output_path: Optional[Path] = None,
    smooth_surfaces: bool = False,
) -> Dict[str, Any]:
    """
    Extracts foreground silhouettes from 2..6 uploaded PNG views, derives true aspect-matched
    millimeter bounding dimensions, carves a 3D volumetric visual hull, and produces:
      - masked_pngs: RGBA masked image bytes per captured view
      - points_mm / colors_rgb: dense surface point cloud of carved 3D shape
      - dimensions_mm: (length_x, width_y, height_z)
      - fill_ratio: volumetric ratio vs bounding box (<0.86 => non-prismatic sculpted part)
      - detected_hole_radius_mm: real enclosed bore radius or 0.0
      - contours_2d: normalized polygons for xy / xz / yz
      - vertices_mm / triangles_idx: manifold smoothed STL/STEP geometry (for sculpted shapes)
    """
    masks: Dict[str, np.ndarray] = {}
    crops_rgb: Dict[str, np.ndarray] = {}
    view_aspects: Dict[str, float] = {}
    view_fg_sizes_px: Dict[str, Tuple[float, float]] = {}
    masked_pngs: Dict[str, bytes] = {}
    side_colors: Dict[str, np.ndarray] = {}

    for side in ["front", "back", "left", "right", "top", "bottom"]:
        raw = view_images.get(side)
        if not raw:
            continue
        arr = np.asarray(Image.open(io.BytesIO(raw)).convert("RGB"), dtype=np.uint8)
        h, w = arr.shape[:2]
        fg_mask, _ = extract_foreground_mask(arr)
        masks[side] = fg_mask

        rgba = np.zeros((h, w, 4), dtype=np.uint8)
        rgba[fg_mask, :3] = arr[fg_mask]
        rgba[fg_mask, 3] = 255
        out_buf = io.BytesIO()
        Image.fromarray(rgba, mode="RGBA").save(out_buf, format="PNG")
        masked_pngs[side] = out_buf.getvalue()

        ys, xs = np.where(fg_mask)
        x0, x1 = int(np.min(xs)), int(np.max(xs))
        y0, y1 = int(np.min(ys)), int(np.max(ys))
        fg_w = max(float(x1 - x0 + 1), 1.0)
        fg_h = max(float(y1 - y0 + 1), 1.0)
        view_fg_sizes_px[side] = (fg_w, fg_h)
        view_aspects[side] = fg_w / fg_h
        crops_rgb[side] = arr[y0 : y1 + 1, x0 : x1 + 1]
        side_colors[side] = np.mean(arr[fg_mask], axis=0) if np.any(fg_mask) else np.array([120.0, 180.0, 220.0])

    # Derive real 3D physical extents (length_x, width_y, height_z) from calibrated reference + orthographic aspects
    known_length = float(calibration_spec.get("known_length_mm") or 80.0)
    mm_per_px = calibration_spec.get("mm_per_unit")
    ref_side = str(calibration_spec.get("reference_side") or "front").lower()

    fb_aspects = [view_aspects[s] for s in ("front", "back") if s in view_aspects]
    lr_aspects = [view_aspects[s] for s in ("left", "right") if s in view_aspects]

    aspect_x_over_z = float(np.median(fb_aspects)) if fb_aspects else 1.6
    aspect_y_over_z = float(np.median(lr_aspects)) if lr_aspects else (aspect_x_over_z * 0.625)

    # Check if top/bottom view clarifies X vs Y ratio when only front/top or side/top uploaded
    top_aspect = view_aspects.get("top") or view_aspects.get("bottom")
    if top_aspect and not lr_aspects and fb_aspects:
        # Match best of 0° vs 90° top view relative to front X
        if abs(top_aspect - aspect_x_over_z) < 0.25 and "left" not in masks:
            aspect_y_over_z = max(0.3, aspect_x_over_z / max(top_aspect, 0.25))

    if ref_side in view_fg_sizes_px:
        ref_w_px, _ = view_fg_sizes_px[ref_side]
        if mm_per_px and float(mm_per_px) > 0:
            ref_span_mm = float(np.clip(ref_w_px * float(mm_per_px), 10.0, 5000.0))
        else:
            ref_span_mm = float(np.clip(known_length, 10.0, 5000.0))

        if ref_side in ("left", "right"):
            width_y = ref_span_mm
            height_z = max(8.0, width_y / max(aspect_y_over_z, 0.15))
            length_x = max(10.0, height_z * aspect_x_over_z)
        else:
            length_x = ref_span_mm
            height_z = max(8.0, length_x / max(aspect_x_over_z, 0.15))
            width_y = max(10.0, height_z * aspect_y_over_z)
    else:
        length_x = round(max(known_length, 15.0), 2)
        height_z = round(max(8.0, length_x / max(aspect_x_over_z, 0.15)), 2)
        width_y = round(max(10.0, height_z * aspect_y_over_z), 2)

    # Clamp extreme desktop bounding outliers gently while preserving true aspect ratio
    max_dim = max(length_x, width_y, height_z)
    if max_dim > 500.0:
        s_fac = 500.0 / max_dim
        length_x *= s_fac
        width_y *= s_fac
        height_z *= s_fac

    length_x = round(length_x, 2)
    width_y = round(width_y, 2)
    height_z = round(height_z, 2)

    # Determine adaptive 3D voxel grid resolution proportional to true extents
    base_res = 26
    nx = max(12, min(32, int(round(base_res * (length_x / max(length_x, width_y, height_z))))))
    ny = max(12, min(32, int(round(base_res * (width_y / max(length_x, width_y, height_z))))))
    nz = max(10, min(28, int(round(base_res * (height_z / max(length_x, width_y, height_z))))))

    # Project each available mask onto the canonical voxel grid
    votes = np.zeros((nx, ny, nz), dtype=np.int32)
    total_views = 0

    if "front" in masks:
        m = _resize_mask_crop(masks["front"], nx, nz)  # shape (nz, nx) top-down v=top..bottom
        m_xz = np.flip(m, axis=0).T  # (nx, nz), z increasing upward
        votes += m_xz[:, None, :]
        total_views += 1

    if "back" in masks:
        m = _resize_mask_crop(masks["back"], nx, nz)
        m_xz = np.flip(np.flip(m, axis=1), axis=0).T
        votes += m_xz[:, None, :]
        total_views += 1

    if "right" in masks:
        m = _resize_mask_crop(masks["right"], ny, nz)
        m_yz = np.flip(m, axis=0).T
        votes += m_yz[None, :, :]
        total_views += 1

    if "left" in masks:
        m = _resize_mask_crop(masks["left"], ny, nz)
        m_yz = np.flip(np.flip(m, axis=1), axis=0).T
        votes += m_yz[None, :, :]
        total_views += 1

    # Align TOP / BOTTOM orientation (0 deg vs 90 deg) against X/Y aspect
    expected_xy_ratio = length_x / max(width_y, 1.0)
    for t_side in ("top", "bottom"):
        if t_side not in masks:
            continue
        t_mask = masks[t_side]
        tw_px, th_px = view_fg_sizes_px[t_side]
        r_direct = tw_px / max(th_px, 1.0)
        r_rot = th_px / max(tw_px, 1.0)
        if abs(math.log(max(r_rot, 0.05) / max(expected_xy_ratio, 0.05))) < abs(
            math.log(max(r_direct, 0.05) / max(expected_xy_ratio, 0.05))
        ):
            t_mask = np.rot90(t_mask, k=1)
            crops_rgb[t_side] = np.rot90(crops_rgb[t_side], k=1)
        m_xy = _resize_mask_crop(t_mask, nx, ny)
        if t_side == "bottom":
            m_xy = np.flip(m_xy, axis=0)
        m_xy_grid = np.flip(m_xy, axis=0).T  # (nx, ny)
        votes += m_xy_grid[:, :, None]
        total_views += 1

    if total_views == 0:
        occ = np.ones((nx, ny, nz), dtype=bool)
    else:
        occ = votes == total_views
        # Relax slightly if harsh cross-perspective cropping carved < 6% volume
        if float(np.mean(occ)) < 0.06 and total_views >= 3:
            occ = votes >= (total_views - 1)
        if float(np.mean(occ)) < 0.03:
            occ = votes >= max(1, total_views // 2)

    # Detect genuine circular bores from top/bottom/front ONLY (never invent nonexistent bores)
    detected_hole_radius_mm = 0.0
    for bore_side in ("top", "bottom", "front"):
        if bore_side in masks:
            hole_info = detect_interior_circular_hole(masks[bore_side])
            if hole_info is not None:
                _, _, r_ratio = hole_info
                base_span = min(length_x, width_y) if bore_side in ("top", "bottom") else min(length_x, height_z)
                candidate_r = round(r_ratio * base_span, 2)
                if 0.6 <= candidate_r < min(length_x, width_y) * 0.42:
                    detected_hole_radius_mm = candidate_r
                    break

    fill_ratio = float(np.mean(occ))
    is_sculpted = fill_ratio < 0.86

    # Extract 2D silhouette polygons for DXF / build123d code synthesis
    contours_2d: Dict[str, List[Tuple[float, float]]] = {}
    if "top" in masks or "bottom" in masks:
        ts = "top" if "top" in masks else "bottom"
        t_src = masks[ts]
        tw_px, th_px = view_fg_sizes_px[ts]
        if abs(math.log(max(th_px / max(tw_px, 1.0), 0.05) / max(expected_xy_ratio, 0.05))) < abs(
            math.log(max(tw_px / max(th_px, 1.0), 0.05) / max(expected_xy_ratio, 0.05))
        ):
            t_src = np.rot90(t_src, k=1)
        contours_2d["xy"] = extract_normalized_polygon(t_src)
    if "front" in masks or "back" in masks:
        f_src = masks["front"] if "front" in masks else np.fliplr(masks["back"])
        contours_2d["xz"] = extract_normalized_polygon(f_src)
    if "right" in masks or "left" in masks:
        r_src = masks["right"] if "right" in masks else np.fliplr(masks["left"])
        contours_2d["yz"] = extract_normalized_polygon(r_src)

    # Extract manifold smoothed surface triangles + rich colored surface point cloud
    verts_mm, tris_idx = _extract_smoothed_manifold_mesh(occ, length_x, width_y, height_z, smooth_iters=3)

    # Build colored 3D surface point cloud via area-weighted sampling over manifold triangles
    v_arr = np.asarray(verts_mm, dtype=np.float32) if verts_mm else np.zeros((0, 3), dtype=np.float32)
    if len(tris_idx) > 0 and len(v_arr) > 0:
        t_arr = np.asarray(tris_idx, dtype=np.int32)
        tri_pts = v_arr[t_arr]  # (T, 3, 3)
        normals = np.cross(tri_pts[:, 1] - tri_pts[:, 0], tri_pts[:, 2] - tri_pts[:, 0])
        areas = 0.5 * np.linalg.norm(normals, axis=1)
        total_area = float(np.sum(areas))
        n_norms = np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-6)
        unit_n = normals / n_norms

        n_samples = 7200
        rng = np.random.default_rng(seed=2026)
        if total_area > 1e-9:
            probs = areas / total_area
            chosen_t = rng.choice(len(tri_pts), size=n_samples, replace=True, p=probs)
            r1 = np.sqrt(rng.random(n_samples))[:, None]
            r2 = rng.random(n_samples)[:, None]
            pts_cloud = (
                (1.0 - r1) * tri_pts[chosen_t, 0]
                + (r1 * (1.0 - r2)) * tri_pts[chosen_t, 1]
                + (r1 * r2) * tri_pts[chosen_t, 2]
            ).astype(np.float32)
            n_cloud = unit_n[chosen_t]
        else:
            pts_cloud = v_arr
            n_cloud = np.zeros((len(v_arr), 3), dtype=np.float32)

        # Sample RGB per 3D point directly from the dominant facing cropped photo
        cols_cloud = np.zeros((len(pts_cloud), 3), dtype=np.float32)
        hx, hy, hz = max(length_x / 2.0, 1.0), max(width_y / 2.0, 1.0), max(height_z / 2.0, 1.0)
        for idx in range(len(pts_cloud)):
            px, py, pz = pts_cloud[idx]
            nx_v, ny_v, nz_v = n_cloud[idx] if idx < len(n_cloud) else (0.0, 0.0, 1.0)
            ax, ay, az = abs(nx_v), abs(ny_v), abs(nz_v)

            if az >= ax and az >= ay and ("top" in crops_rgb or "bottom" in crops_rgb):
                use_side = "top" if (nz_v >= 0 and "top" in crops_rgb) or "bottom" not in crops_rgb else "bottom"
                img_c = crops_rgb[use_side]
                ch, cw = img_c.shape[:2]
                u = int(np.clip((px / (2 * hx) + 0.5) * (cw - 1), 0, cw - 1))
                v = int(np.clip((0.5 - py / (2 * hy)) * (ch - 1), 0, ch - 1))
                cols_cloud[idx] = img_c[v, u]
            elif ay >= ax and ("front" in crops_rgb or "back" in crops_rgb):
                use_side = "front" if (ny_v <= 0 and "front" in crops_rgb) or "back" not in crops_rgb else "back"
                img_c = crops_rgb[use_side]
                ch, cw = img_c.shape[:2]
                u = int(np.clip((px / (2 * hx) + 0.5) * (cw - 1), 0, cw - 1))
                v = int(np.clip((0.5 - pz / (2 * hz)) * (ch - 1), 0, ch - 1))
                cols_cloud[idx] = img_c[v, u]
            elif "right" in crops_rgb or "left" in crops_rgb:
                use_side = "right" if (nx_v >= 0 and "right" in crops_rgb) or "left" not in crops_rgb else "left"
                img_c = crops_rgb[use_side]
                ch, cw = img_c.shape[:2]
                u = int(np.clip((py / (2 * hy) + 0.5) * (cw - 1), 0, cw - 1))
                v = int(np.clip((0.5 - pz / (2 * hz)) * (ch - 1), 0, ch - 1))
                cols_cloud[idx] = img_c[v, u]
            else:
                cols_cloud[idx] = side_colors.get("front", np.array([60.0, 190.0, 230.0]))
    else:
        pts_cloud = np.zeros((120, 3), dtype=np.float32)
        cols_cloud = np.tile(np.array([60.0, 190.0, 230.0], dtype=np.float32), (120, 1))

    hull_data = {
        "scan_id": scan_id,
        "is_sculpted": bool(is_sculpted),
        "fill_ratio": round(fill_ratio, 3),
        "dimensions_mm": {"x": length_x, "y": width_y, "z": height_z},
        "detected_hole_radius_mm": detected_hole_radius_mm,
        "contours_2d": contours_2d,
        "vertices_mm": verts_mm if is_sculpted else [],
        "triangles_idx": tris_idx if is_sculpted else [],
        "surface_mode": "faceted_fallback",
    }
    if smooth_surfaces and is_sculpted and len(verts_mm) >= 4 and len(tris_idx) >= 4:
        # Opt-in C2 patches never replace the verified closed faceted shell.
        from app.cad.nurbs import fit_surface_patches

        fitted = fit_surface_patches(
            verts_mm, tris_idx, (length_x, width_y, height_z)
        )
        hull_data["surface_mode"] = fitted.surface_mode
        hull_data["nurbs_patches"] = [patch.to_dict() for patch in fitted.patches]
        hull_data["max_surface_deviation_mm"] = round(fitted.max_deviation_mm, 6)
        hull_data["surface_reason"] = fitted.reason
    if hull_output_path is not None:
        hull_output_path.parent.mkdir(parents=True, exist_ok=True)
        hull_output_path.write_text(json.dumps(hull_data), encoding="utf-8")

    return {
        "masked_pngs": masked_pngs,
        "points_mm": pts_cloud,
        "colors_rgb": cols_cloud,
        "dimensions_mm": (length_x, width_y, height_z),
        "detected_hole_radius_mm": detected_hole_radius_mm,
        "is_sculpted": is_sculpted,
        "fill_ratio": round(fill_ratio, 3),
        "contours_2d": contours_2d,
        "views_used": len(masks),
        "surface_mode": hull_data["surface_mode"],
        "max_surface_deviation_mm": hull_data.get("max_surface_deviation_mm"),
    }
