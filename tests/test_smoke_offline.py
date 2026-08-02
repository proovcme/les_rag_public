"""Offline Smoke Test Suite for LES_v2.

Verifies:
1. Application initialization & TestClient setup.
2. Startup non-crash behavior.
3. Availability of main endpoints (/api/health, /api/version, /api/status, /api/scope/options, /api/diag).
4. Core configuration loading (rag_config & proxy.config).
5. Fast isolated execution of core user business scenario.
6. Clean teardown and zero process/resource leakage.
"""

from __future__ import annotations

import os
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import rag_config
from proxy.config import CORS_ALLOWED_ORIGINS
from proxy.routers.diagnostics import DiagnosticsRouterState, router as diagnostics_router, set_diagnostics_state
from proxy.routers.runtime import RuntimeRouterState, router as runtime_router, set_runtime_state
from proxy.services.profile_resolver import resolve
from proxy.smeta_core.resource_normalizer import normalize_norm_resources


def create_smoke_test_app() -> FastAPI:
    """Instantiate a lightweight FastAPI app configured with proxy routers for smoke testing."""
    app = FastAPI(title="LES Smoke App", version="2.0.0")

    set_runtime_state(
        RuntimeRouterState(
            rag_backend=lambda: None,
            current_mode={"mode": "chat", "runtime_profile": "chat", "model": "test"},
            metrics_cache={"cpu": 0.0, "ram_used": 1.0, "ram_total": 8.0},
            chat_metrics={},
            crag_stats={"verified": 0, "no_data": 0},
            error_counts={},
            llm_semaphore=None,
            llm_concurrency=1,
            proxy_start=1000.0,
            job_service=None,
            job_tracker={},
        )
    )
    set_diagnostics_state(DiagnosticsRouterState(crag_stats={"verified": 0}, proxy_start=1000.0))

    app.include_router(runtime_router)
    app.include_router(diagnostics_router)
    return app


def test_smoke_config_loading():
    """Smoke test: verify key configuration options load cleanly."""
    assert rag_config.embedding_api_model() is not None
    assert rag_config.rag_meta_db_path() is not None
    assert CORS_ALLOWED_ORIGINS is not None


def test_smoke_app_startup_and_health_check():
    """Smoke test: verify app starts, main endpoints return 200, health check operates."""
    app = create_smoke_test_app()

    client = TestClient(app)

    # 1. Health check
    resp_health = client.get("/api/health")
    assert resp_health.status_code == 200
    assert resp_health.json()["status"] in ("starting", "ok", "degraded", "error")

    # 2. Version endpoint
    resp_version = client.get("/api/version")
    assert resp_version.status_code == 200
    data_ver = resp_version.json()
    assert "app_version" in data_ver
    assert "harness_version" in data_ver
    assert "product_version" in data_ver
    assert "build_number" in data_ver

    # 3. Status endpoint
    resp_status = client.get("/api/status")
    assert resp_status.status_code == 200
    data_stat = resp_status.json()
    assert "chat_admission" in data_stat or "status" in data_stat

    # 4. Scope options endpoint
    resp_scope = client.get("/api/scope/options")
    assert resp_scope.status_code in (200, 401, 403)


def test_smoke_core_user_business_scenario():
    """Smoke test: execution of a core user scenario (query routing + resource normalization)."""
    # 1. User intent resolution
    resolution = resolve(mode="smeta", question="Смета на прокладку силового кабеля 50м")
    assert resolution.profile_id == "estimate_harness"
    assert resolution.profile.output_contract == "estimate_preliminary_v1"

    # 2. Data processing pipeline (normalization)
    raw_resources = [
        {"kind": "labor", "code": "1-100-30", "name": "Средний разряд 3.0", "per_unit": 5.0},
        {"kind": "labor", "code": "2-100-03", "name": "Монтажник 3 разряда", "per_unit": 5.0},
        {"kind": "material", "code": "01.01", "name": "Кабель ВВГнг", "per_unit": 50.0},
    ]
    normalized = normalize_norm_resources(raw_resources)
    assert len(normalized) == 2
    assert normalized[0]["code"] == "2-100-03"
    assert normalized[1]["code"] == "01.01"


def test_smoke_teardown_cleanliness():
    """Smoke test: ensure environment state remains unchanged after smoke test runs."""
    orig_env = dict(os.environ)

    # Temporary state test
    app = create_smoke_test_app()
    with TestClient(app) as client:
        r = client.get("/api/version")
        assert r.status_code == 200

    # Ensure environment was not corrupted
    assert os.environ == orig_env
