"""
Unit & Failover Tests for Shared Multi-Model LLM Router & Accurate Modal Health Reporting.
All LLM/Modal calls are mocked so zero external API quota is consumed.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.llm_router import (
    clear_model_cooldowns,
    invoke_with_failover,
    is_model_cooled_down,
    resolve_active_gemini_label,
    resolve_gemini_model_chain,
)
from app.agents.nodes.synthesizer import cad_synthesizer_node
from app.core.cloud_auth import detect_active_pipeline_engines
from app.core.cloud_config import CloudHealthService
from app.schemas.adt import CSGFeatureTree, FeatureStep, Open3DGeometryReport


def test_deprecated_gemini_3_pro_resolves_to_live_gemini_flash(monkeypatch):
    monkeypatch.setenv("DEFAULT_LLM_MODEL", "gemini-3-pro")
    chain = resolve_gemini_model_chain()
    assert chain[0] == "gemini-3.5-flash"
    assert "gemini-3.1-flash-lite" in chain
    assert "gemini-3-pro" not in chain


def test_invoke_with_failover_skips_cooled_down_and_falls_back():
    clear_model_cooldowns()

    failing = MagicMock()
    failing.ainvoke = AsyncMock(side_effect=RuntimeError("400 Your credit balance is too low to access the Anthropic API."))

    working = MagicMock()
    working.ainvoke = AsyncMock(return_value=SimpleNamespace(content="OK"))

    candidates = [
        ("anthropic", "claude-sonnet-4-5-20250929", failing),
        ("gemini", "gemini-3.5-flash", working),
    ]

    result, used, err = asyncio.run(invoke_with_failover("ping", candidates))
    assert err is None
    assert used == "gemini:gemini-3.5-flash"
    assert result.content == "OK"
    assert is_model_cooled_down("anthropic", "claude-sonnet-4-5-20250929") is True

    # Subsequent calls immediately skip cooled-down Anthropic without invoking it again
    failing.ainvoke.reset_mock()
    working.ainvoke.reset_mock()
    result2, used2, _ = asyncio.run(invoke_with_failover("ping2", candidates))
    assert used2 == "gemini:gemini-3.5-flash"
    assert result2.content == "OK"
    failing.ainvoke.assert_not_called()


def test_resolve_active_gemini_label_skips_429_model(monkeypatch):
    monkeypatch.setenv("DEFAULT_LLM_MODEL", "gemini-3-pro")
    failing_429 = MagicMock()
    failing_429.ainvoke = AsyncMock(side_effect=RuntimeError("429 RESOURCE_EXHAUSTED quota exceeded"))
    ok_lite = MagicMock()
    ok_lite.ainvoke = AsyncMock(return_value=SimpleNamespace(content="OK"))

    asyncio.run(
        invoke_with_failover(
            "test",
            [
                ("gemini", "gemini-3.5-flash", failing_429),
                ("gemini", "gemini-3.1-flash-lite", ok_lite),
            ],
        )
    )
    assert resolve_active_gemini_label() == "gemini-3.1-flash-lite"


def test_synthesizer_fails_over_to_gemini_before_deterministic(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gem-key")
    tree = CSGFeatureTree(
        part_summary="Aerodynamic Chassis",
        coordinate_origin="center_bottom",
        global_parameters_mm={"LENGTH_MM": 200.0, "WIDTH_MM": 90.0, "THICKNESS_MM": 60.0},
        steps=[
            FeatureStep(
                step_index=1,
                operation="base_extrude",
                target_plane="XY",
                parameters_mm={"length": 200.0, "width": 90.0, "height": 60.0},
                rationale="Base prismatic solid",
            )
        ],
    )
    report = Open3DGeometryReport(
        scan_id="scn_failover_test",
        units="mm",
        point_count=3200,
        icp_fitness_score=0.9,
        icp_inlier_rmse_mm=0.25,
        bounding_box_mm=(200.0, 90.0, 60.0),
        principal_axes=[(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)],
        symmetry_planes=["YZ"],
        planes=[],
        cylinders=[],
        ply_object_key="cad_exports/scn_failover_test/fused_cloud.ply",
    )
    state = {
        "scan_id": "scn_failover_test",
        "geometry_report": report,
        "feature_tree": tree,
        "compile_retries": 0,
    }

    bad_anthropic = MagicMock()
    bad_anthropic.ainvoke = AsyncMock(side_effect=RuntimeError("credit balance is too low"))
    good_gemini = MagicMock()
    good_gemini.ainvoke = AsyncMock(
        return_value=SimpleNamespace(
            content="```python\nfrom build123d import BuildPart, Box\nLENGTH_MM = 200.0\nwith BuildPart() as part:\n    Box(200, 90, 60)\nRESULT_PART = part.part\n```"
        )
    )

    with patch(
        "app.agents.nodes.synthesizer.build_llm_candidates",
        return_value=[
            ("anthropic", "claude-sonnet-4-5-20250929", bad_anthropic),
            ("gemini", "gemini-3.5-flash", good_gemini),
        ],
    ):
        out = asyncio.run(cad_synthesizer_node(state))

    assert "RESULT_PART = part.part" in out["current_code"]
    assert "[gemini:gemini-3.5-flash]" in out["event_log"][0]["payload"]["message"]


def test_modal_not_deployed_reports_accurate_status_and_engines(monkeypatch):
    monkeypatch.setenv("MODAL_TOKEN_ID", "ak-test123")
    monkeypatch.setenv("MODAL_TOKEN_SECRET", "as-test456")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gem-key")
    monkeypatch.setenv("DEFAULT_LLM_MODEL", "gemini-3-pro")

    fake_modal = MagicMock()
    fake_modal.Function.from_name.side_effect = RuntimeError("App 'photocad-gpu' not found in environment 'main'")

    with patch.dict("sys.modules", {"modal": fake_modal}):
        diag = asyncio.run(CloudHealthService.get_full_diagnostics())

    assert diag["status"] == "partial"
    assert diag["cloud_tiers"]["compute_modal_gpu"]["status"] == "not_deployed"
    engines = diag["active_engines"]
    assert engines["cloud_gpu_ready"] == "false"
    assert engines["modal_tokens_set"] == "true"
    assert "Deploy Pending" in engines["segmentation"]
    assert "gemini-3.5-flash" in engines["llm_vlm"]

    fallback_engines = detect_active_pipeline_engines(execution_mode="zero_heat_dev_fallback")
    assert fallback_engines["cloud_gpu_ready"] == "false"
