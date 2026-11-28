"""
Shared Pytest Isolation Fixtures
Prevents automated test runs from accidentally hitting live Gemini, Anthropic,
or Modal API quotas/endpoints when local `.env` contains real credentials.
"""

from __future__ import annotations

import pytest

from app.agents.llm_router import clear_model_cooldowns
from app.core.cloud_auth import clear_cloud_caches
from app.core.config import settings


@pytest.fixture(autouse=True)
def _isolate_live_cloud_keys(monkeypatch: pytest.MonkeyPatch):
    for var in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "", raising=False)
    clear_model_cooldowns()
    clear_cloud_caches()
    yield
    clear_model_cooldowns()
    clear_cloud_caches()
