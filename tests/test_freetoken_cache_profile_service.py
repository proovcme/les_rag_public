import json

import httpx

from proxy.services.freetoken_cache_profile_service import (
    DEFAULT_FREETOKEN_CONTEXT_TOKENS,
    bounded_desired_kv,
    max_feasible_kv,
    probe_freetoken_cache,
    reconcile_freetoken_cache,
)


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
