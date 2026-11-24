"""
Tests for PhotoCAD Cloud Tier Diagnostics Service
Document ID: PCAD-SAD-002
"""

import asyncio
from app.core.cloud_config import CloudHealthService

def test_database_connectivity():
    res = asyncio.run(CloudHealthService.check_database())
    assert res["status"] in ["connected", "degraded"]
    assert "tier" in res

def test_full_cloud_diagnostics():
    report = asyncio.run(CloudHealthService.get_full_diagnostics())
    assert "status" in report
    assert "cloud_tiers" in report
    assert "database_supabase" in report["cloud_tiers"]
    assert "cache_redis_upstash" in report["cloud_tiers"]
    assert "storage_cloudflare_r2" in report["cloud_tiers"]
    assert "compute_modal_gpu" in report["cloud_tiers"]
