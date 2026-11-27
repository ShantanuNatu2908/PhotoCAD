"""
PhotoCAD - Depth Anything V2 / DA3 Multi-View Depth & 3D Unprojection Worker
Document ID: PCAD-SAD-002 / skills/cv-pipeline.skill.md (FR-08)

Runs keyframe-only BF16/FP16 monocular/multi-view depth estimation on masked RGBA
keyframes and unprojects foreground object pixels into camera-space 3D point clouds.
"""

from __future__ import annotations

import io
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import numpy as np
from PIL import Image


DEFAULT_DA3_MODEL_ID = "depth-anything/DA3-BASE"
DEFAULT_DA2_MODEL_ID = "depth-anything/Depth-Anything-V2-Small-hf"


@dataclass
class ViewDepthCloud:
    """Partial 3D surface point cloud generated from a single masked perspective."""

    side: str
    points_xyz: np.ndarray       # (N, 3) float32 in local camera coordinates
    colors_rgb: np.ndarray       # (N, 3) float32 in [0.0, 1.0]
    focal_length_px: float
    depth_min: float
    depth_max: float
    depth_preview_png: bytes
    backend_used: str


def estimate_pinhole_intrinsics(width: int, height: int, fov_factor: float = 1.15) -> Tuple[float, float, float, float]:
    """
    Estimates standard mobile/webcam pinhole intrinsics (fx, fy, cx, cy)
    matching a typical ~47 deg vertical / ~60 deg horizontal FOV lens.
    """
    focal = float(max(width, height)) * fov_factor
    cx = float(width) / 2.0
    cy = float(height) / 2.0
    return focal, focal, cx, cy


def encode_depth_preview_png(depth_map: np.ndarray, alpha_mask: np.ndarray) -> bytes:
    """Renders a high-contrast pseudo-depth preview image masked to the foreground object."""
    fg = alpha_mask > 128
    vis = np.zeros_like(depth_map, dtype=np.uint8)
    if np.any(fg):
        fg_vals = depth_map[fg]
        d_min, d_max = float(np.min(fg_vals)), float(np.max(fg_vals))
        span = max(d_max - d_min, 1e-6)
        norm = ((depth_map - d_min) / span) * 255.0
        vis[fg] = np.clip(norm[fg], 25, 255).astype(np.uint8)

    buf = io.BytesIO()
    Image.fromarray(vis, mode="L").save(buf, format="PNG")
    return buf.getvalue()


def unproject_masked_depth(
    rgba_array: np.ndarray,
    depth_map: np.ndarray,
    stride: int = 2,
    working_distance: float = 1.0,
    relief_scale: float = 0.25,
) -> Tuple[np.ndarray, np.ndarray, float]:
    """
    Unprojects 2D masked foreground pixels into camera-space 3D coordinates (X, Y, Z).

    Because uncalibrated cameras view the part facing the center optical axis,
    we normalize inverse/disparity depth values across foreground pixels around `working_distance`
    so the local depth offset (camera-facing faces closer, recessed pockets deeper) aligns
    cleanly onto an object-centered coordinate frame before Open3D ICP refinement.

    Camera convention:
      +X -> right in image
      +Y -> up in image
      +Z -> away from camera (depth along viewing ray; surfaces closer to camera have smaller Z)
    """
    h, w = rgba_array.shape[:2]
    fx, fy, cx, cy = estimate_pinhole_intrinsics(w, h)

    alpha = rgba_array[:, :, 3]
    fg_mask = alpha > 128

    if not np.any(fg_mask):
        return np.zeros((0, 3), dtype=np.float32), np.zeros((0, 3), dtype=np.float32), fx

    # Subsample deterministically to ~15k-40k points per view for fast Open3D RANSAC/ICP (<15s SLA)
    sub_mask = fg_mask[::stride, ::stride]
    sub_depth = depth_map[::stride, ::stride].astype(np.float32)
    sub_rgb = rgba_array[::stride, ::stride, :3].astype(np.float32) / 255.0

    vs, us = np.where(sub_mask)
    if len(us) == 0:
        return np.zeros((0, 3), dtype=np.float32), np.zeros((0, 3), dtype=np.float32), fx

    us_px = us.astype(np.float32) * float(stride)
    vs_px = vs.astype(np.float32) * float(stride)
    raw_d = sub_depth[vs, us]

    # Depth Anything outputs disparity / inverse depth (larger value = closer to camera)
    # Convert to centered forward Z relief around 0, then add working_distance
    d_min, d_max = float(np.percentile(raw_d, 2)), float(np.percentile(raw_d, 98))
    span = max(d_max - d_min, 1e-5)
    norm_closeness = np.clip((raw_d - d_min) / span, 0.0, 1.0)  # 1 = closest to lens

    # Estimate apparent angular width of the foreground mask to keep XY aspect true
    u_span_px = float(np.max(us_px) - np.min(us_px))
    half_depth_span = (u_span_px / fx) * relief_scale * working_distance

    # Z offset relative to object center (closer points get negative local Z)
    z_local = (0.5 - norm_closeness) * half_depth_span
    z_world = working_distance + z_local

    # Perspective X, Y normalized around object center pixel
    x_cam = ((us_px - cx) / fx) * z_world
    y_cam = -((vs_px - cy) / fy) * z_world

    # Center partial cloud near its XY centroid so 6 orthogonal rotations overlap tightly at origin
    x_cam -= float(np.mean(x_cam))
    y_cam -= float(np.mean(y_cam))

    points = np.stack([x_cam, y_cam, z_local], axis=-1).astype(np.float32)
    colors = sub_rgb[vs, us].astype(np.float32)
    return points, colors, fx


class DepthEstimationWorker:
    """
    Stateful GPU wrapper executing Depth Anything 3 (DA3) or Depth Anything V2 (FP16/BF16)
    across 6 masked keyframes cleanly with zero persistent video cache.
    """

    def __init__(self, model_id: str = DEFAULT_DA2_MODEL_ID):
        self.model_id = model_id
        self._model = None
        self._processor = None
        self._backend = "uninitialized"

    def _load_model(self) -> None:
        if self._model is not None or self._backend == "shading_depth_fallback":
            return

        import torch

        device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.bfloat16 if device == "cuda" else torch.float32

        # Attempt 1: Depth Anything 3 (`depth_anything_3`) if installed in Modal image
        try:
            from depth_anything_3.api import DepthAnything3  # type: ignore

            self._model = DepthAnything3.from_pretrained(DEFAULT_DA3_MODEL_ID).to(device)
            self._model.eval()
            self._backend = "depth_anything_3"
            return
        except Exception:
            pass

        # Attempt 2: HuggingFace Transformers Depth Anything V2
        try:
            from transformers import AutoImageProcessor, AutoModelForDepthEstimation

            self._processor = AutoImageProcessor.from_pretrained(self.model_id)
            self._model = AutoModelForDepthEstimation.from_pretrained(
                self.model_id, torch_dtype=dtype
            ).to(device)
            self._model.eval()
            self._backend = "depth_anything_v2"
            return
        except Exception:
            self._backend = "shading_depth_fallback"

    def _predict_depth_map(self, rgba_array: np.ndarray) -> np.ndarray:
        import torch

        h, w = rgba_array.shape[:2]
        rgb_img = Image.fromarray(rgba_array[:, :, :3], mode="RGB")
        device = "cuda" if torch.cuda.is_available() else "cpu"

        if self._backend == "depth_anything_3":
            ctx = (
                torch.autocast(device_type="cuda", dtype=torch.bfloat16)
                if device == "cuda"
                else torch.no_grad()
            )
            with torch.inference_mode(), ctx:
                prediction = self._model.inference([rgb_img])
                depth = np.asarray(prediction.depth[0], dtype=np.float32)
            if depth.shape != (h, w):
                depth = np.asarray(
                    Image.fromarray(depth).resize((w, h), Image.Resampling.BILINEAR),
                    dtype=np.float32,
                )
            return depth

        if self._backend == "depth_anything_v2":
            inputs = self._processor(images=rgb_img, return_tensors="pt").to(device)
            ctx = (
                torch.autocast(device_type="cuda", dtype=torch.bfloat16)
                if device == "cuda"
                else torch.no_grad()
            )
            with torch.inference_mode(), ctx:
                outputs = self._model(**inputs)
                predicted_depth = outputs.predicted_depth

            interp = torch.nn.functional.interpolate(
                predicted_depth.unsqueeze(1).float(),
                size=(h, w),
                mode="bicubic",
                align_corners=False,
            )
            return interp.squeeze().cpu().numpy().astype(np.float32)

        # Fallback depth proxy if HuggingFace weights are unreachable offline:
        # Distance-transform + luminance height approximation strictly within foreground mask
        import cv2

        fg_u8 = (rgba_array[:, :, 3] > 128).astype(np.uint8)
        dist = cv2.distanceTransform(fg_u8, cv2.DIST_L2, 5)
        dist_norm = dist / max(float(np.max(dist)), 1.0)
        luma = (
            0.299 * rgba_array[:, :, 0]
            + 0.587 * rgba_array[:, :, 1]
            + 0.114 * rgba_array[:, :, 2]
        ) / 255.0
        return (0.75 * dist_norm + 0.25 * luma).astype(np.float32)

    def estimate_views_depth(
        self, masked_rgba_bytes: Dict[str, bytes], stride: int = 2
    ) -> Tuple[Dict[str, ViewDepthCloud], Dict[str, Any]]:
        """
        Estimates dense depth maps for all masked views and unprojects each into a
        partial camera-space 3D point cloud. Calls torch.cuda.empty_cache() after inference.
        """
        import torch

        t_start = time.perf_counter()
        self._load_model()

        clouds: Dict[str, ViewDepthCloud] = {}
        total_points = 0

        for side, png_bytes in masked_rgba_bytes.items():
            rgba_img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
            rgba_arr = np.asarray(rgba_img, dtype=np.uint8)

            depth_map = self._predict_depth_map(rgba_arr)
            # Adaptive stride to keep high-res 1080p scans bounded and fast
            effective_stride = max(stride, max(rgba_arr.shape[:2]) // 480)
            pts, cols, fx = unproject_masked_depth(rgba_arr, depth_map, stride=effective_stride)

            preview_png = encode_depth_preview_png(depth_map, rgba_arr[:, :, 3])
            fg_vals = depth_map[rgba_arr[:, :, 3] > 128]
            d_min = float(np.min(fg_vals)) if fg_vals.size > 0 else 0.0
            d_max = float(np.max(fg_vals)) if fg_vals.size > 0 else 0.0

            total_points += len(pts)
            clouds[side] = ViewDepthCloud(
                side=side,
                points_xyz=pts,
                colors_rgb=cols,
                focal_length_px=round(fx, 2),
                depth_min=round(d_min, 4),
                depth_max=round(d_max, 4),
                depth_preview_png=preview_png,
                backend_used=self._backend,
            )

        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        elapsed_ms = round((time.perf_counter() - t_start) * 1000.0, 2)
        telemetry = {
            "backend": self._backend,
            "model_id": DEFAULT_DA3_MODEL_ID if self._backend == "depth_anything_3" else self.model_id,
            "views_processed": len(clouds),
            "total_unprojected_points": total_points,
            "elapsed_ms": elapsed_ms,
        }
        return clouds, telemetry
