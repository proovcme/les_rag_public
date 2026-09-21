import json
import asyncio
import threading
from types import SimpleNamespace

import httpx
import pytest

from proxy.services.freetoken_cache_profile_service import (
    DEFAULT_FREETOKEN_CONTEXT_TOKENS,
    bounded_desired_kv,
    max_feasible_kv,
    probe_freetoken_cache,
    reconcile_freetoken_cache,
)


def test_active_cache_target_uses_bound_engine_despite_legacy_ollama():
    from proxy.services.freetoken_cache_profile_service import cache_alignment_target
    legacy = SimpleNamespace(requires_cache_alignment=False, model='qwen9b')
    bound = SimpleNamespace(extension_type='freetoken', base_url='http://127.0.0.1:1919/v1', model_id='Qwen3.6-35B')
    assert cache_alignment_target(legacy, active_connection=bound) == (bound.base_url, bound.model_id)


def test_active_other_engine_never_mutates_unrelated_legacy_freetoken():
    from proxy.services.freetoken_cache_profile_service import cache_alignment_target
    legacy = SimpleNamespace(requires_cache_alignment=True)
    assert cache_alignment_target(legacy, active_connection=SimpleNamespace(extension_type=None)) is None


def test_legacy_cache_target_is_preserved():
    from proxy.services.freetoken_cache_profile_service import cache_alignment_target
    legacy = SimpleNamespace(requires_cache_alignment=True, base_url='http://localhost:1919/v1', model='qwen9b')
    assert cache_alignment_target(legacy) == (legacy.base_url, legacy.model)


@pytest.mark.asyncio
async def test_cache_alignment_waits_for_running_generation():
    from proxy.services.freetoken_cache_profile_service import admitted_cache_call
    from proxy.services.runtime_admission import GenerationSlotTimeout

    semaphore = asyncio.Semaphore(1)
    calls = []
    await semaphore.acquire()
    try:
        with pytest.raises(GenerationSlotTimeout):
            await admitted_cache_call(
                lambda: calls.append('rebuild'), semaphore=semaphore,
                timeout_seconds=0.01,
            )
        assert calls == []
    finally:
        semaphore.release()
    assert await admitted_cache_call(
        lambda: 'ready', semaphore=semaphore, timeout_seconds=1,
    ) == 'ready'


@pytest.mark.asyncio
async def test_cancelled_cache_rebuild_keeps_generation_blocked_until_worker_finishes():
    from proxy.services.freetoken_cache_profile_service import admitted_cache_call

    started = asyncio.Event()
    finish = threading.Event()
    loop = asyncio.get_running_loop()
    semaphore = asyncio.Semaphore(1)

    def rebuild():
        loop.call_soon_threadsafe(started.set)
        assert finish.wait(5), 'test did not release the rebuild'
        return 'ready'

    task = asyncio.create_task(admitted_cache_call(
        rebuild, semaphore=semaphore, timeout_seconds=1,
    ))
    try:
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()  # Repeated cancellation must not release the GPU permit.
        await asyncio.sleep(0)
        assert semaphore.locked()
        assert not task.done()
    finally:
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
    assert not semaphore.locked()


_GEOMETRY = {
    "num_pages": 8226,
    "moe_cache_size": 900,
    "num_mamba_slots": 24,
    "num_swa_pages": 0,
    "cache_budget_bytes": 3376257433,
    "unit_bytes": {
        "kv_per_token": 20480,
        "moe_per_expert": 1775616,
        "mamba_per_slot": 64389120,
        "swa_per_token": 0,
    },
    "limits": {
        "moe_experts": {"min": 256, "max": 1901},
        "kv_tokens": {"min": 1, "max": 200000},
    },
}


def test_default_context_matches_factory_35b_window():
    assert DEFAULT_FREETOKEN_CONTEXT_TOKENS == 35000


def test_max_feasible_kv_keeps_minimum_moe():
    assert max_feasible_kv(_GEOMETRY) == 60651
    assert bounded_desired_kv(_GEOMETRY, 500000) == 60651
    assert bounded_desired_kv(_GEOMETRY, 30000) == 30000


def test_reconcile_rebuilds_oversized_request_to_feasible_ceiling():
    posted: list[dict] = []

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"state": "serving", "geometry": _GEOMETRY})
        posted.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "num_pages": 60651,
                "moe_cache_size": 256,
                "mamba_slots": 24,
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = reconcile_freetoken_cache(
            "http://127.0.0.1:1919/v1", 500000, client=client
        )

    assert result["status"] == "synchronized"
    assert result["requested_kv_tokens"] == 500000
    assert result["desired_kv_tokens"] == 60651
    assert result["effective_kv_tokens"] == 60651
    assert result["max_feasible_kv_tokens"] == 60651
    assert posted[0]["num_pages"] == 60651


def test_35b_legacy_window_lifts_to_factory_kv():
    from proxy.services.freetoken_cache_profile_service import desired_kv_for_answer_model

    assert desired_kv_for_answer_model("Qwen3.6-35B-A3B-NVFP4", 8253) == 35000
    assert desired_kv_for_answer_model("Qwen3.6-35B-A3B-NVFP4", 35000) == 35000
    assert desired_kv_for_answer_model("qwen3.5:9b", 8253) == 8253


def test_align_rebuilds_35b_from_live_8k_window():
    from proxy.services.freetoken_cache_profile_service import align_freetoken_cache_for_turn

    posted: list[dict] = []
    methods: list[str] = []
    geometry = dict(_GEOMETRY)
    geometry["num_pages"] = 8214

    def handler(request):
        methods.append(request.method)
        if request.method == "GET":
            return httpx.Response(200, json={"state": "serving", "geometry": geometry})
        posted.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "num_pages": 35000,
                "moe_cache_size": 4375,
                "mamba_slots": 24,
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = align_freetoken_cache_for_turn(
            "http://127.0.0.1:1919/v1",
            model_id="Qwen3.6-35B-A3B-NVFP4",
            requested_kv=8253,
            allow_rebuild=True,
            client=client,
        )

    assert "POST" in methods
    assert posted[0]["num_pages"] == 35000
    assert result["status"] == "synchronized"
    assert result["effective_kv_tokens"] == 35000
    assert result["previous_effective_kv_tokens"] == 8214
    assert result["aligned_for"] == "qwen-35b-extended"


def test_align_without_rebuild_keeps_cramped_35b_visible():
    from proxy.services.freetoken_cache_profile_service import align_freetoken_cache_for_turn

    methods: list[str] = []
    geometry = dict(_GEOMETRY)
    geometry["num_pages"] = 8214

    def handler(request):
        methods.append(request.method)
        return httpx.Response(200, json={"state": "serving", "geometry": geometry})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = align_freetoken_cache_for_turn(
            "http://127.0.0.1:1919/v1",
            model_id="Qwen3.6-35B-A3B-NVFP4",
            requested_kv=8253,
            allow_rebuild=False,
            client=client,
        )

    assert methods == ["GET"]
    assert result["status"] == "too_small_for_35b"
    assert result["effective_kv_tokens"] == 8214
    assert result["desired_kv_tokens"] == 35000


def test_probe_reads_live_pages_without_rebuild():
    methods: list[str] = []

    def handler(request):
        methods.append(request.method)
        return httpx.Response(200, json={"state": "serving", "geometry": _GEOMETRY})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = probe_freetoken_cache(
            "http://127.0.0.1:1919/v1", 35000, client=client
        )

    assert methods == ["GET"]
    assert result["status"] == "mismatch"
    assert result["effective_kv_tokens"] == 8226
    assert result["desired_kv_tokens"] == 35000
    assert result["max_feasible_kv_tokens"] == 60651
