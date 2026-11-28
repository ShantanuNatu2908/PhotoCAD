"""
PhotoCAD - Shared Multimodal Image Encoding Utilities for LangGraph Nodes 1 & 3.
"""

from __future__ import annotations

import base64
import io
from typing import Dict, List

from PIL import Image

from app.core.config import settings


def encode_scan_thumbnails_b64(scan_id: str, max_px: int = 384) -> List[Dict[str, str]]:
    """Loads up to 6 captured view thumbnails as PNG base64 data URIs for multimodal VLMs."""
    out: List[Dict[str, str]] = []
    for side in ("front", "back", "left", "right", "top", "bottom"):
        masked = settings.PROCESSED_DIR / scan_id / f"{side}_masked.png"
        raw = settings.UPLOADS_DIR / scan_id / f"{side}.png"
        src = masked if masked.exists() else (raw if raw.exists() else None)
        if not src:
            continue
        try:
            with Image.open(src) as img:
                rgb = img.convert("RGB")
                rgb.thumbnail((max_px, max_px), Image.Resampling.BILINEAR)
                buf = io.BytesIO()
                rgb.save(buf, format="PNG")
                b64 = base64.b64encode(buf.getvalue()).decode("ascii")
                out.append({"side": side, "data_url": f"data:image/png;base64,{b64}"})
        except Exception:
            continue
    return out
