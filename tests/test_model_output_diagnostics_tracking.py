"""Ordinary model output is neutral telemetry, separate from validation failures."""

from types import SimpleNamespace
import asyncio

import pytest

from proxy.routers import diagnostics, runtime
from proxy.services import chat_evidence_application_service as application
from tests.test_model_rag_sheet_evidence_reads import _run_sheet


@pytest.mark.asyncio
async def test_actual_model_first_chat_tracks_neutral_output_without_validation_failure(tmp_path, monkeypatch):
    captured = []
    original = application.EvidenceRuntimeDeps

    def capture_runtime(**kwargs):
        runtime = original(**kwargs)
        captured.append(runtime.state)
        return runtime

    monkeypatch.setattr(application, "EvidenceRuntimeDeps", capture_runtime)
    run = await _run_sheet(tmp_path, monkeypatch, reads=False)

    assert run.result["crag_status"] == "MODEL_OUTPUT"
    state, = captured
    assert state.crag_stats.get("model_output", 0) == 1
    assert state.crag_stats.get("unvalidated", 0) == 0
    assert state.crag_stats["verified"] == state.crag_stats["hallucination"] == 0
    assert state.chat_metrics["crag_fail"] == 0
    assert state.chat_metrics.get("crag_pass", 0) == 0
    assert sum(state.crag_stats.values()) == 1


@pytest.mark.asyncio
async def test_existing_metrics_route_accepts_additive_neutral_counter(monkeypatch):
    async def collection(_name):
        return SimpleNamespace(points_count=1)

    class Database(_ProbeDatabase):
        def execute(self, _sql):
            return SimpleNamespace(fetchone=lambda: (1,), fetchall=lambda: [])

    state = SimpleNamespace(
        backend=SimpleNamespace(collection_name="fixture", aclient=SimpleNamespace(get_collection=collection)),
        metrics_cache={}, crag_stats={"verified": 0, "no_data": 0, "hallucination": 0,
                                      "unvalidated": 0, "model_output": 7},
        chat_metrics={"latency_search": [], "latency_gen": [], "tokens": []},
        error_counts={}, llm_concurrency=1, llm_semaphore=asyncio.Semaphore(1),
    )
    monkeypatch.setattr(runtime, "_state", state)
    monkeypatch.setattr(runtime.sqlite3, "connect", lambda *a, **kw: Database())
    monkeypatch.setattr(runtime, "rag_runtime_config", lambda: {"profile": "fixture"})

    payload = await runtime.get_metrics()

    assert payload["pipeline"]["total_requests"] == 7
    assert payload["pipeline"]["crag_verified_rate"] == 0
    assert payload["pipeline"]["crag_unvalidated_rate"] == 0
    assert payload["pipeline"]["crag_halluc_rate"] == 0


class _ProbeClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def get(self, _url):
        return SimpleNamespace(status_code=200, raise_for_status=lambda: None, json=lambda: {
            "result": {"collections": [{"name": "fixture"}], "points_count": 1},
            "main_model": {"path": "fixture", "loaded": True}, "embed_model": {"loaded": True},
            "models": [{"name": "fixture"}],
        })


class _ProbeDatabase:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, _sql):
        return SimpleNamespace(fetchone=lambda: (1,))


@pytest.mark.asyncio
@pytest.mark.parametrize("stats,status,percent", [
    ({"model_output": 7}, "warn", "0%"),
    ({"model_output": 1000, "verified": 4}, "warn", "100%"),
    ({"model_output": 1000, "verified": 7, "hallucination": 1}, "ok", "88%"),
    ({"model_output": 1000, "unvalidated": 5}, "err", "0%"),
    ({"model_output": 1000, "hallucination": 5}, "err", "0%"),
    ({"model_output": 1000, "verified": 2, "unvalidated": 3}, "warn", "40%"),
    ({"model_output": 1000, "verified": 7, "unvalidated": 3}, "ok", "70%"),
])
async def test_diagnostics_model_output_is_counted_but_excluded_from_quality_thresholds(
    monkeypatch, stats, status, percent,
):
    monkeypatch.setattr(diagnostics, "_state", diagnostics.DiagnosticsRouterState(stats, 0.0))
    monkeypatch.setattr(diagnostics.httpx, "AsyncClient", lambda *a, **kw: _ProbeClient())
    monkeypatch.setattr(diagnostics.sqlite3, "connect", lambda *a, **kw: _ProbeDatabase())
    monkeypatch.setattr(diagnostics.socket, "create_connection", lambda *a, **kw: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(diagnostics.psutil, "virtual_memory", lambda: SimpleNamespace(percent=10, used=1, total=2))
    monkeypatch.setattr(diagnostics.psutil, "cpu_percent", lambda **kw: 1.0)
    monkeypatch.setattr(diagnostics.psutil, "disk_usage", lambda *a: SimpleNamespace(percent=10, free=1024**3))
    monkeypatch.setattr(diagnostics.os, "getenv", lambda key, default=None: "mlx" if key == "LES_LLM_PROVIDER" else default)
    monkeypatch.setattr(diagnostics, "rag_collection_name", lambda: "fixture")
    monkeypatch.setattr(diagnostics, "rag_meta_db_path", lambda: "fixture-unused")
    monkeypatch.setattr(diagnostics, "rag_runtime_config", lambda: {"profile": "fixture", "collection": "fixture"})

    result = await diagnostics.run_diagnostics(_internal=object())

    crag = next(check for check in result["checks"] if check["name"] == "Т.О.С.К.А. статистика")
    assert crag["status"] == status
    assert f"M:{stats['model_output']}" in crag["value"] and f"({percent} verified)" in crag["value"]
    assert "MODEL_OUTPUT" in crag["message"] and "не доказательство качества" in crag["message"]
    if stats == {"model_output": 7}:
        assert "нет проверяемых ответов" in crag["message"]
    assert result["err_count"] == (1 if status == "err" else 0)
