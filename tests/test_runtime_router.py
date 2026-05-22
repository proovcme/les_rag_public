import asyncio

import pytest

from proxy.routers import runtime


class FakeBackend:
    async def health(self):
        return True


@pytest.fixture()
def runtime_state():
    previous = runtime._state
    current_mode = {"mode": "rag", "model": "old"}
    runtime.set_runtime_state(
        runtime.RuntimeRouterState(
            rag_backend=FakeBackend(),
            current_mode=current_mode,
            metrics_cache={},
            chat_metrics={"latency_search": [], "latency_gen": [], "tokens": []},
            crag_stats={"verified": 0, "no_data": 0, "hallucination": 0},
            error_counts={},
            llm_semaphore=asyncio.Semaphore(2),
            proxy_start=0.0,
        )
    )
    yield current_mode
    runtime._state = previous


@pytest.mark.asyncio
async def test_health_uses_configured_backend(runtime_state):
    assert await runtime.health() == {"status": "ok", "backend": "qdrant_llama"}


@pytest.mark.asyncio
async def test_mode_roundtrip_mutates_shared_state(runtime_state):
    assert await runtime.get_mode() == {"mode": "rag", "model": "old"}

    updated = await runtime.set_mode(runtime.ModeRequest(mode="code", model="coder"), _admin=object())

    assert updated == {"mode": "code", "model": "coder"}
    assert runtime_state == {"mode": "code", "model": "coder"}
