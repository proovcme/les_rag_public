import asyncio

import pytest

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
    assert runtime_state["mode"] == "indexing"
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
    assert runtime_state["mode"] == "chat"
    assert runtime_state["chat_generation"] == "allowed"


@pytest.mark.asyncio
async def test_indexing_mode_reports_runtime_admission(runtime_state):
    runtime.get_runtime_state().metrics_cache.update({"ram_free_gb": 5.0, "swap_pct": 86.0})

    response = await runtime.get_indexing_mode()

    assert response["chat_generation_allowed"] is False
    assert response["chat_admission"]["status_code"] == 503
    assert "swap_pct=86.0 > 60.0" in response["chat_generation_reason"]


@pytest.mark.asyncio
async def test_status_includes_embedding_trace(runtime_state):
    response = await runtime.get_status()

    assert response["embedding"]["profile"]
    assert response["embedding"]["meta_db"]


@pytest.mark.asyncio
async def test_status_includes_chat_admission(runtime_state):
    response = await runtime.get_status()

    assert response["chat_admission"]["allowed"] is True
