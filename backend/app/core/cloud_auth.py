"""
PhotoCAD - Shared Cloud Credential & Engine Availability Diagnostics
Ensures CV workers, OpenCascade sandbox, and /health/cloud diagnostics evaluate
Modal tokens / ~/.modal.toml, Gemini, and Anthropic keys consistently.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

_MODAL_DEPLOY_CACHE: Optional[Tuple[float, bool]] = None


def set_modal_deploy_cache(deployed: bool) -> None:
    """Records live Modal `photocad-gpu` app availability for fast engine telemetry."""
    global _MODAL_DEPLOY_CACHE
    _MODAL_DEPLOY_CACHE = (time.monotonic(), bool(deployed))


def get_cached_modal_deployed(ttl_sec: float = 120.0) -> Optional[bool]:
    if _MODAL_DEPLOY_CACHE is None:
        return None
    ts, val = _MODAL_DEPLOY_CACHE
    if time.monotonic() - ts > ttl_sec:
        return None
    return val


def clear_cloud_caches() -> None:
    """Clears cached Modal deployment probes (primarily for tests)."""
    global _MODAL_DEPLOY_CACHE
    _MODAL_DEPLOY_CACHE = None


def is_valid_secret(value: str, *placeholders: str) -> bool:
    v = (value or "").strip()
    if not v:
        return False
    return not any(p in v for p in ("your-", *placeholders))


def is_modal_configured() -> bool:
    """True when MODAL_TOKEN_ID/SECRET env vars OR a local `modal setup` ~/.modal.toml profile exist."""
    tid = os.getenv("MODAL_TOKEN_ID", "")
    tsec = os.getenv("MODAL_TOKEN_SECRET", "")
    if is_valid_secret(tid) and is_valid_secret(tsec):
        return True

    toml_path = Path.home() / ".modal.toml"
    if toml_path.exists():
        try:
            text = toml_path.read_text(encoding="utf-8", errors="ignore")
            if "token_id" in text and "token_secret" in text:
                return True
        except Exception:
            pass
    return False


def detect_active_pipeline_engines(
    modal_deployed: Optional[bool] = None,
    execution_mode: Optional[str] = None,
) -> Dict[str, str]:
    """Reports which vision, LLM, and CAD kernel engines are currently enabled and actually reachable."""
    modal_tokens = is_modal_configured()
    gemini_ok = is_valid_secret(os.getenv("GEMINI_API_KEY", ""))
    anthropic_ok = is_valid_secret(os.getenv("ANTHROPIC_API_KEY", ""))

    if execution_mode == "zero_heat_dev_fallback":
        modal_live = False
    elif modal_deployed is not None:
        modal_live = bool(modal_deployed) and modal_tokens
    elif not modal_tokens:
        modal_live = False
    else:
        cached = get_cached_modal_deployed()
        modal_live = cached if cached is not None else True

    gemini_label = os.getenv("DEFAULT_LLM_MODEL", "gemini-3.5-flash")
    anthropic_active = anthropic_ok
    if gemini_ok:
        try:
            from app.agents.llm_router import (
                is_anthropic_cooled_down,
                resolve_active_gemini_label,
            )

            gemini_label = resolve_active_gemini_label()
            anthropic_active = anthropic_ok and not is_anthropic_cooled_down()
        except Exception:
            pass

    if gemini_ok and anthropic_active:
        llm_label = f"{gemini_label} + Claude Sonnet 4.5"
    elif gemini_ok:
        llm_label = f"{gemini_label} (Gemini Multimodal)"
    elif anthropic_ok:
        llm_label = "claude-sonnet-4-5"
    else:
        llm_label = "Deterministic Offline Rules (No LLM Key)"

    if modal_live:
        seg_label = "SAM 2.1 (Modal L4 BF16)"
        fusion_label = "Depth Anything + Open3D (Modal L4)"
        cad_label = "OpenCascade build123d (Modal gVisor)"
    elif modal_tokens:
        seg_label = "OpenCV GrabCut (Modal L4 Deploy Pending)"
        fusion_label = "Multi-View Visual Hull (Modal Pending)"
        cad_label = "AST Silhouette Compiler (Modal Pending)"
    else:
        seg_label = "OpenCV GrabCut (Local Fallback)"
        fusion_label = "Multi-View Visual Hull (Local Fallback)"
        cad_label = "AST Silhouette Compiler (Local Fallback)"

    return {
        "segmentation": seg_label,
        "depth_fusion": fusion_label,
        "llm_vlm": llm_label,
        "cad_kernel": cad_label,
        "cloud_gpu_ready": "true" if modal_live else "false",
        "modal_tokens_set": "true" if modal_tokens else "false",
        "multimodal_llm_ready": "true" if (gemini_ok or anthropic_ok) else "false",
    }
