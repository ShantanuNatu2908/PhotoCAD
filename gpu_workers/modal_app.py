"""
PhotoCAD - Serverless Cloud GPU Worker on Modal
Document ID: PCAD-SAD-002 / skills/cv-pipeline.skill.md (FR-07..FR-10, NFR-02)

Houses:
1. SAM 2.1 (FP16/BF16) Hand & Background Removal (`segmentation.py`)
2. Depth Anything 3 / V2 (FP16/BF16) Dense Depth & Pose Unprojection (`depth_estimation.py`)
3. Open3D Multi-View Fusion (RANSAC + ICP) & Geometric Primitive Extraction (`fusion_open3d.py`)
"""

from __future__ import annotations

import base64
import time
from typing import Any, Dict, Optional

import modal

# 1. Define Modal App
app = modal.App("photocad-gpu")

# 2. Define Container Image with CUDA, PyTorch, Hugging Face, and Open3D
gpu_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("libgl1", "libglib2.0-0", "libgomp1")
    .pip_install(
        "torch>=2.4.0",
        "torchvision>=0.19.0",
        "transformers>=4.46.0",
        "huggingface-hub>=0.26.0",
        "numpy>=1.26.0",
        "scipy>=1.13.0",
        "pillow>=10.4.0",
        "opencv-python-headless>=4.10.0",
        "pydantic>=2.7.0",
        "open3d>=0.18.0",
        "httpx>=0.27.0",
    )
    .add_local_python_source("gpu_workers")
)

# 3. Mount Persistent Volume for Model Weights (Hugging Face cache)
model_cache_vol = modal.Volume.from_name("photocad-model-cache", create_if_missing=True)


def _fetch_bytes(url: str) -> bytes:
    """Downloads PNG bytes from a pre-signed URL or decodes a base64 data URI."""
    import httpx

    if url.startswith("data:image/"):
        _, b64_part = url.split(",", 1)
        return base64.b64decode(b64_part)

    with httpx.Client(timeout=20.0) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.content


def _upload_bytes(url: str, data: bytes, content_type: str) -> None:
    """Uploads generated artifacts (.PNG mask or .PLY cloud) to a pre-signed PUT URL."""
    import httpx

    with httpx.Client(timeout=30.0) as client:
        resp = client.put(url, content=data, headers={"Content-Type": content_type})
        resp.raise_for_status()


@app.function(
    image=gpu_image,
    gpu="L4",
    scaledown_window=60,
    volumes={"/root/.cache": model_cache_vol},
    timeout=60,
)
def health_check_gpu() -> Dict[str, Any]:
    """Tests remote Modal L4 GPU execution and returns device telemetry."""
    import torch

    cuda_available = torch.cuda.is_available()
    device_name = torch.cuda.get_device_name(0) if cuda_available else "CPU (Fallback)"
    allocated_vram_mb = (
        torch.cuda.memory_allocated(0) / (1024 * 1024) if cuda_available else 0.0
    )

    return {
        "status": "healthy",
        "service": "photocad-gpu-modal",
        "cuda_available": cuda_available,
        "device": device_name,
        "initial_vram_allocated_mb": round(allocated_vram_mb, 2),
        "target_gpu_tier": "NVIDIA L4",
    }


@app.function(
    image=gpu_image,
    gpu="L4",
    scaledown_window=60,
    volumes={"/root/.cache": model_cache_vol},
    timeout=180,
)
def run_sam_segmentation(
    keyframe_urls: Dict[str, str],
    mask_upload_urls: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Phase 3 Stage 1: Runs SAM 2.1 (BF16/FP16) hand & background segmentation on 6 keyframes.
    If `mask_upload_urls` are supplied, uploads clean RGBA PNGs directly to R2.
    """
    from gpu_workers.segmentation import Sam2SegmentationWorker

    raw_bytes = {side: _fetch_bytes(url) for side, url in keyframe_urls.items()}
    worker = Sam2SegmentationWorker()
    results, telemetry = worker.segment_keyframes(raw_bytes)

    masked_payload: Dict[str, Any] = {}
    for side, res in results.items():
        if mask_upload_urls and side in mask_upload_urls:
            _upload_bytes(mask_upload_urls[side], res.rgba_png_bytes, "image/png")

        masked_payload[side] = {
            "width": res.width,
            "height": res.height,
            "foreground_coverage": res.foreground_coverage,
            "hand_pixels_suppressed": res.hand_pixels_suppressed,
            "confidence_score": res.confidence_score,
            "backend_used": res.backend_used,
            "rgba_b64": base64.b64encode(res.rgba_png_bytes).decode("ascii")
            if not (mask_upload_urls and side in mask_upload_urls)
            else None,
        }

    return {"status": "completed", "telemetry": telemetry, "views": masked_payload}


@app.function(
    image=gpu_image,
    gpu="L4",
    scaledown_window=60,
    volumes={"/root/.cache": model_cache_vol},
    timeout=240,
)
def run_full_cv_pipeline(
    scan_id: str,
    keyframe_urls: Dict[str, str],
    calibration_spec: Optional[Dict[str, Any]] = None,
    mask_upload_urls: Optional[Dict[str, str]] = None,
    ply_upload_url: Optional[str] = None,
    ply_object_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    End-to-End Phase 3 Serverless L4 GPU Pipeline (Target < 15s SLA):
      Stage 1: SAM 2.1 Hand & Background Removal -> torch.cuda.empty_cache()
      Stage 2: Depth Anything (DA3 / DA-V2 FP16) Depth & Unprojection -> torch.cuda.empty_cache()
      Stage 3: Open3D Multi-View Registration (SOR -> RANSAC -> ICP -> Scale -> Primitives)
    """
    import io

    import numpy as np
    from PIL import Image

    from gpu_workers.depth_estimation import DepthEstimationWorker
    from gpu_workers.fusion_open3d import fuse_and_extract_open3d
    from gpu_workers.segmentation import Sam2SegmentationWorker

    t0 = time.perf_counter()

    # 0. Fetch all 6 uncompressed PNG keyframes
    raw_bytes = {side: _fetch_bytes(url) for side, url in keyframe_urls.items()}

    # 1. SAM 2.1 Masking
    sam_worker = Sam2SegmentationWorker()
    seg_results, sam_telemetry = sam_worker.segment_keyframes(raw_bytes)

    masked_rgba_bytes: Dict[str, bytes] = {}
    view_fg_widths: Dict[str, int] = {}
    masked_views_meta: Dict[str, Dict[str, Any]] = {}

    for side, res in seg_results.items():
        masked_rgba_bytes[side] = res.rgba_png_bytes
        if mask_upload_urls and side in mask_upload_urls:
            _upload_bytes(mask_upload_urls[side], res.rgba_png_bytes, "image/png")

        # Measure horizontal pixel span of foreground alpha for metric calibration
        alpha_arr = np.asarray(Image.open(io.BytesIO(res.mask_png_bytes)), dtype=np.uint8)
        cols_fg = np.where(np.any(alpha_arr > 128, axis=0))[0]
        fg_w = int(cols_fg[-1] - cols_fg[0]) if len(cols_fg) > 1 else res.width // 2
        view_fg_widths[side] = fg_w

        masked_views_meta[side] = {
            "width": res.width,
            "height": res.height,
            "foreground_coverage": res.foreground_coverage,
            "hand_pixels_suppressed": res.hand_pixels_suppressed,
            "confidence_score": res.confidence_score,
            "rgba_b64": base64.b64encode(res.rgba_png_bytes).decode("ascii")
            if not (mask_upload_urls and side in mask_upload_urls)
            else None,
        }

    # 2. Depth Anything Multi-View Depth & 3D Unprojection
    depth_worker = DepthEstimationWorker()
    depth_clouds, depth_telemetry = depth_worker.estimate_views_depth(masked_rgba_bytes)

    open3d_input: Dict[str, Dict[str, Any]] = {
        side: {
            "points_xyz": cloud.points_xyz,
            "colors_rgb": cloud.colors_rgb,
            "fg_width_px": view_fg_widths.get(side, 400),
        }
        for side, cloud in depth_clouds.items()
    }

    # 3. Open3D Registration & Primitive Extraction
    report_or_err, ply_bytes = fuse_and_extract_open3d(
        view_clouds=open3d_input,
        scan_id=scan_id,
        calibration_spec=calibration_spec,
        ply_object_key=ply_object_key,
    )

    if "error" in report_or_err:
        return {
            "status": "failed",
            "error": report_or_err["error"],
            "telemetry": {
                "sam": sam_telemetry,
                "depth": depth_telemetry,
                "total_elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            },
        }

    if ply_upload_url and ply_bytes:
        _upload_bytes(ply_upload_url, ply_bytes, "application/octet-stream")

    fusion_telemetry = report_or_err.pop("_telemetry", {})
    total_ms = round((time.perf_counter() - t0) * 1000.0, 2)

    return {
        "status": "completed",
        "geometry_report": report_or_err,
        "masked_views": masked_views_meta,
        "ply_b64": base64.b64encode(ply_bytes).decode("ascii") if not ply_upload_url else None,
        "telemetry": {
            "sam": sam_telemetry,
            "depth": depth_telemetry,
            "fusion": fusion_telemetry,
            "total_elapsed_ms": total_ms,
        },
    }


cad_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("libgl1", "libglib2.0-0", "libgomp1", "libxrender1")
    .pip_install("build123d>=0.8.0", "numpy>=1.26.0")
    .add_local_python_source("gpu_workers")
)


@app.function(
    image=cad_image,
    cpu=2.0,
    memory=2048,
    scaledown_window=60,
    timeout=45,
    block_network=True,
)
def run_build123d_sandbox(code: str) -> Dict[str, Any]:
    """Isolated Modal gVisor OpenCascade sandbox (`network blocked`, 2 vCPU, 2 GB RAM, 30s execution cap)."""
    from gpu_workers.cad_sandbox import run_build123d_in_subprocess

    return run_build123d_in_subprocess(code=code, timeout_sec=30)
