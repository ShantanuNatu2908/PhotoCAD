"""
PhotoCAD - Shared Multi-Model LLM Router & Failover Helper
Provides ordered Gemini + Anthropic fallback with per-(provider, model) cooldown
tracking so dead models (e.g. 404), exhausted billing (e.g. Anthropic credit low),
or transient 429 limits never waste API quota or break the 5-node CAD pipeline.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional, Tuple

from app.core.cloud_auth import is_valid_secret
from app.core.config import settings

# Map stale/deprecated placeholder names (such as .env.example's legacy hint) to live Gemini 3.x models.
GEMINI_MODEL_ALIASES: Dict[str, str] = {
    "gemini-3-pro": "gemini-3.5-flash",
    "gemini-pro": "gemini-3.5-flash",
}

GEMINI_FALLBACK_CHAIN: Tuple[str, ...] = (
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
)

ANTHROPIC_FALLBACK_CHAIN: Tuple[str, ...] = (
    "claude-sonnet-4-5-20250929",
)

# Maps (provider, model_name) -> monotonic epoch seconds until retry is permitted
_MODEL_COOLDOWN_UNTIL: Dict[Tuple[str, str], float] = {}


def clear_model_cooldowns() -> None:
    """Clears cached model unavailability windows (primarily for deterministic unit tests)."""
    _MODEL_COOLDOWN_UNTIL.clear()


def is_model_cooled_down(provider: str, model: str) -> bool:
    until = _MODEL_COOLDOWN_UNTIL.get((provider, model), 0.0)
    if until <= 0.0:
        return False
    if time.monotonic() >= until:
        _MODEL_COOLDOWN_UNTIL.pop((provider, model), None)
        return False
    return True


def record_model_failure(provider: str, model: str, err_text: str) -> None:
    """Applies targeted cooldown windows to prevent hammering broken or billing-exhausted endpoints."""
    low = (err_text or "").lower()
    if "404" in low or "not_found" in low or "not found" in low:
        ttl = 1800.0
    elif "credit balance" in low or "billing" in low or "api_key_invalid" in low or "invalid x-api-key" in low:
        ttl = 1800.0
    elif "429" in low or "resource_exhausted" in low or "rate limit" in low or "quota" in low:
        ttl = 300.0
    else:
        ttl = 30.0
    _MODEL_COOLDOWN_UNTIL[(provider, model)] = time.monotonic() + ttl


def _dedup_keep_order(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items:
        clean = (item or "").strip()
        if clean and clean not in seen:
            seen.add(clean)
            out.append(clean)
    return out


def resolve_gemini_model_chain(override_env: Optional[str] = None) -> List[str]:
    """Resolves ordered Gemini candidates from env overrides + live 3.x/2.x fallback chain."""
    raw_override = os.getenv(override_env, "") if override_env else ""
    raw_default = os.getenv("DEFAULT_LLM_MODEL", "") or settings.DEFAULT_LLM_MODEL or "gemini-3.5-flash"

    ordered: List[str] = []
    for raw in (raw_override, raw_default):
        clean = raw.strip()
        if not clean:
            continue
        ordered.append(GEMINI_MODEL_ALIASES.get(clean, clean))

    ordered.extend(GEMINI_FALLBACK_CHAIN)
    return _dedup_keep_order(ordered)


def resolve_active_gemini_label() -> str:
    """Returns the top non-cooled-down Gemini model ID for status diagnostics."""
    for model in resolve_gemini_model_chain():
        if not is_model_cooled_down("gemini", model):
            return model
    return resolve_gemini_model_chain()[0]


def is_anthropic_cooled_down() -> bool:
    return all(is_model_cooled_down("anthropic", m) for m in ANTHROPIC_FALLBACK_CHAIN)


def build_llm_candidates(
    override_env: Optional[str] = None,
    temperature: float = 0.1,
    structured_schema: Any = None,
    prefer_anthropic: bool = False,
) -> List[Tuple[str, str, Any]]:
    """
    Constructs prioritized runnable LLM candidates across configured providers.
    Skips cooled-down models to protect API rate limits and credit balances.
    """
    gemini_key = settings.GEMINI_API_KEY or os.getenv("GEMINI_API_KEY", "")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    llm: Any

    gemini_entries: List[Tuple[str, str, Any]] = []
    if is_valid_secret(gemini_key, "your-gemini"):
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI

            for model_name in resolve_gemini_model_chain(override_env):
                if is_model_cooled_down("gemini", model_name):
                    continue
                llm = ChatGoogleGenerativeAI(
                    model=model_name,
                    google_api_key=gemini_key,
                    temperature=temperature,
                )
                if structured_schema is not None:
                    llm = llm.with_structured_output(structured_schema)
                gemini_entries.append(("gemini", model_name, llm))
        except Exception:
            pass

    anthropic_entries: List[Tuple[str, str, Any]] = []
    if is_valid_secret(anthropic_key, "your-anthropic"):
        try:
            from langchain_anthropic import ChatAnthropic

            for model_name in ANTHROPIC_FALLBACK_CHAIN:
                if is_model_cooled_down("anthropic", model_name):
                    continue
                llm = ChatAnthropic(  # type: ignore[call-arg]
                    model=model_name,
                    api_key=anthropic_key,  # type: ignore[arg-type]
                    temperature=temperature,
                )
                if structured_schema is not None:
                    llm = llm.with_structured_output(structured_schema)
                anthropic_entries.append(("anthropic", model_name, llm))
        except Exception:
            pass

    if prefer_anthropic:
        return anthropic_entries + gemini_entries
    return gemini_entries + anthropic_entries


async def invoke_with_failover(
    prompt_or_messages: Any,
    candidates: List[Tuple[str, str, Any]],
) -> Tuple[Optional[Any], Optional[str], Optional[str]]:
    """
    Invokes LLM candidates sequentially until one succeeds.
    Returns `(result, "provider:model", last_error)`.
    """
    last_error: Optional[str] = None
    for provider, model_name, runnable in candidates:
        if is_model_cooled_down(provider, model_name):
            continue
        try:
            res = await runnable.ainvoke(prompt_or_messages)
            return res, f"{provider}:{model_name}", None
        except Exception as exc:
            err_str = str(exc)
            last_error = f"{provider}:{model_name} -> {err_str[:180]}"
            record_model_failure(provider, model_name, err_str)
    return None, None, last_error
