import asyncio

import pytest
from fastapi import HTTPException

from proxy.routers import runtime


class FakeBackend:
    async def health(self):
        return True


class DegradedBackend(FakeBackend):
    async def health_snapshot(self):
        return {
            "status": "degraded",
            "totals": {"files": 801, "indexed_files": 3, "pending_files": 798},
            "datasets": [],
        }


@pytest.fixture()
def runtime_state(request):
    previous = runtime._state
    current_mode = {"mode": "rag", "model": "old"}
    backend = getattr(request, "param", FakeBackend())
    runtime.set_runtime_state(
        runtime.RuntimeRouterState(
            rag_backend=backend,
            current_mode=current_mode,
            metrics_cache={},
            chat_metrics={"latency_search": [], "latency_gen": [], "tokens": []},
            crag_stats={"verified": 0, "no_data": 0, "hallucination": 0},
            error_counts={},
            llm_semaphore=asyncio.Semaphore(2),
            llm_concurrency=2,
            proxy_start=0.0,
        )
    )
    yield current_mode
    runtime._state = previous


@pytest.mark.asyncio
async def test_health_uses_configured_backend(runtime_state):
    response = await runtime.health()

    assert response["status"] == "ok"
    assert response["backend"] == "qdrant_llama"
    assert response["embedding"]["collection"]


@pytest.mark.asyncio
@pytest.mark.parametrize("runtime_state", [DegradedBackend()], indirect=True)
async def test_health_reports_degraded_rag_index(runtime_state):
    response = await runtime.health()

    assert response["status"] == "degraded"
    assert response["rag"]["totals"]["pending_files"] == 798


@pytest.mark.asyncio
async def test_mode_roundtrip_mutates_shared_state(runtime_state):
    assert await runtime.get_mode() == {"mode": "rag", "model": "old"}

    updated = await runtime.set_mode(runtime.ModeRequest(mode="code", model="coder"), _admin=object())

    assert updated == {"mode": "code", "model": "coder"}
    assert runtime_state == {"mode": "code", "model": "coder"}


@pytest.mark.asyncio
async def test_indexing_mode_sets_priority_and_pauses_chat(runtime_state):
    response = await runtime.set_indexing_mode(
        runtime.IndexingModeRequest(
            enabled=True,
            reason="night batch",
            unload_models=False,
            dataset_priority_order=["NTD_FIRE_Index", "NTD_OTHER_Index"],
        ),
        _admin=object(),
    )

    assert response["active"] is True
    assert response["runtime_profile"] == "INDEX_LIGHT"
    assert runtime_state["mode"] == "indexing"
    assert runtime_state["runtime_profile"] == "INDEX_LIGHT"
    assert runtime_state["chat_generation"] == "paused"
    assert response["dataset_priority_order"] == ["NTD_FIRE_Index", "NTD_OTHER_Index"]


@pytest.mark.asyncio
async def test_indexing_mode_can_return_to_chat(runtime_state):
    await runtime.set_indexing_mode(
        runtime.IndexingModeRequest(enabled=True, unload_models=False),
        _admin=object(),
    )

    response = await runtime.set_indexing_mode(
        runtime.IndexingModeRequest(enabled=False, reason="workday", unload_models=False),
        _admin=object(),
    )

    assert response["active"] is False
    assert response["runtime_profile"] == "CHAT"
    assert runtime_state["mode"] == "chat"
    assert runtime_state["runtime_profile"] == "CHAT"
    assert runtime_state["chat_generation"] == "allowed"


@pytest.mark.asyncio
async def test_indexing_mode_reports_runtime_admission(runtime_state, monkeypatch):
    monkeypatch.setenv("LES_CHAT_MIN_FREE_GB", "8.0")
    monkeypatch.setenv("LES_CHAT_MAX_SWAP_PCT", "60.0")
    runtime.get_runtime_state().metrics_cache.update({"ram_free_gb": 5.0, "swap_pct": 86.0})

    response = await runtime.get_indexing_mode()

    assert response["chat_generation_allowed"] is False
    assert response["chat_admission"]["status_code"] == 503
    assert response["memory_state"]["state"] == "CRITICAL"
    assert "swap_pct=86.0 > 60.0" in response["chat_generation_reason"]


@pytest.mark.asyncio
async def test_status_includes_embedding_trace(runtime_state):
    response = await runtime.get_status()

    assert response["embedding"]["profile"]
    assert response["embedding"]["meta_db"]


@pytest.mark.asyncio
async def test_status_includes_chat_admission(runtime_state, monkeypatch):
    class FakeDispatcher:
        def reindex_status_payload(self):
            return {"running": False}

    monkeypatch.setattr(runtime, "dispatcher_for_state", lambda state: FakeDispatcher())

    response = await runtime.get_status()

    assert response["chat_admission"]["allowed"] is True
    assert response["runtime_profile"] == "CHAT"
    assert response["memory_state"]["state"] in {"UNKNOWN", "GREEN"}


@pytest.mark.asyncio
async def test_status_reports_effective_chat_state_for_cloud_during_indexing(runtime_state, monkeypatch):
    class FakeDispatcher:
        def reindex_status_payload(self):
            return {"running": True}

    monkeypatch.setattr(runtime, "dispatcher_for_state", lambda state: FakeDispatcher())
    monkeypatch.setenv("LES_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "key")
    runtime_state.clear()
    runtime_state.update({"mode": "indexing", "runtime_profile": "INDEX_LIGHT", "chat_generation": "paused"})

    response = await runtime.get_status()

    assert response["raw_mode"]["chat_generation"] == "paused"
    assert response["mode"]["chat_generation"] == "allowed"
    assert response["mode"]["indexing_chat_policy"]["reason"] == "cloud_provider"
    assert response["chat_admission"]["allowed"] is True


def test_openai_provider_status_defaults_to_gpt_model(monkeypatch):
    monkeypatch.setenv("LES_LLM_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.setenv("LLM_MODEL", "mlx-community/Qwen3.5-4B-MLX-4bit")

    status = runtime._provider_status()

    assert status["provider"] == "openai"
    assert status["model"] == "gpt-4.1"


@pytest.mark.asyncio
async def test_chat_admission_counts_active_dispatcher_reindex(runtime_state, monkeypatch):
    class FakeDispatcher:
        def reindex_status_payload(self):
            return {"running": True}

    monkeypatch.setattr(runtime, "dispatcher_for_state", lambda state: FakeDispatcher())

    admission = runtime.chat_admission_for_state(runtime.get_runtime_state())

    assert admission.allowed is False
    assert admission.active_jobs == 1
    assert admission.status_code == 409


@pytest.mark.asyncio
async def test_dispatcher_status_endpoint_uses_dispatcher(runtime_state, monkeypatch):
    class FakeDispatcher:
        def status_payload(self):
            return {"component": "runtime_dispatcher", "actions": {"can_start": True}}

    monkeypatch.setattr(runtime, "dispatcher_for_state", lambda state: FakeDispatcher())

    response = await runtime.runtime_dispatcher_status(_admin=object())

    assert response["component"] == "runtime_dispatcher"
    assert response["actions"]["can_start"] is True


@pytest.mark.asyncio
async def test_dispatcher_start_endpoint_returns_payload(runtime_state, monkeypatch):
    class FakeDispatcher:
        def start_reindex(self, **kwargs):
            return {"status": "started", "datasets": kwargs["datasets"]}

    monkeypatch.setattr(runtime, "dispatcher_for_state", lambda state: FakeDispatcher())

    response = await runtime.runtime_dispatcher_reindex_start(
        runtime.DispatcherReindexRequest(datasets=["NTD_FIRE_Index"], unload_between_docs=False),
        _admin=object(),
    )

    assert response == {"status": "started", "datasets": ["NTD_FIRE_Index"]}


@pytest.mark.asyncio
async def test_dispatcher_pause_endpoint_maps_dispatcher_error(runtime_state, monkeypatch):
    class FakeDispatcher:
        def pause_reindex(self, **kwargs):
            raise runtime.DispatcherError(409, "not running")

    monkeypatch.setattr(runtime, "dispatcher_for_state", lambda state: FakeDispatcher())

    with pytest.raises(HTTPException) as exc:
        await runtime.runtime_dispatcher_reindex_pause(
            runtime.DispatcherPauseRequest(),
            _admin=object(),
        )

    assert exc.value.status_code == 409
    assert exc.value.detail["message"] == "not running"


@pytest.mark.asyncio
async def test_dispatcher_route_changes_status_endpoint(runtime_state, monkeypatch):
    class FakeDispatcher:
        def route_change_status_payload(self):
            return {"running": False, "total": 3}

    monkeypatch.setattr(runtime, "dispatcher_for_state", lambda state: FakeDispatcher())

    response = await runtime.runtime_dispatcher_route_changes_status(_admin=object())

    assert response == {"running": False, "total": 3}


@pytest.mark.asyncio
async def test_dispatcher_route_changes_start_endpoint(runtime_state, monkeypatch):
    class FakeDispatcher:
        def start_route_change_reindex(self, **kwargs):
            return {"status": "dry_run_started", "dry_run": kwargs["dry_run"], "source_root": kwargs["source_root"]}

    monkeypatch.setattr(runtime, "dispatcher_for_state", lambda state: FakeDispatcher())

    response = await runtime.runtime_dispatcher_route_changes_start(
        runtime.DispatcherRouteChangeRequest(source_root="RAG_Content", dry_run=True),
        _admin=object(),
    )

    assert response == {"status": "dry_run_started", "dry_run": True, "source_root": "RAG_Content"}
