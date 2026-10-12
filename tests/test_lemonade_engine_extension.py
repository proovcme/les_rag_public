from dataclasses import FrozenInstanceError
import json
from types import SimpleNamespace

import httpx
import pytest

from extensions.lemonade.model_policy import evaluate_flash_attention_policy
from proxy.services.model_connection_contracts import ConnectionLocality
from proxy.services.model_engine_extension_service import (
    EngineExtensionError,
    EngineExtensionRegistry,
)


def _connection(
    *,
    base_url: str = "http://127.0.0.1:13305/api/v1",
    locality: ConnectionLocality = ConnectionLocality.LOOPBACK,
):
    return SimpleNamespace(
        revision_id="conn:lemonade:r1",
        extension_type="lemonade",
        base_url=base_url,
        locality=locality,
        model_id="Carnice-Qwen3.6-MoE-35B-A3B-IQ2_S",
    )


def _registry(client, *, addresses=("127.0.0.1",)):
    return EngineExtensionRegistry.with_read_only_defaults(
        client,
        address_resolver=lambda _host, _port: addresses,
        peer_verifier=lambda _response, _endpoint: None,
    )


def test_flash_attention_policy_is_immutable_and_preserves_other_args():
    decision = evaluate_flash_attention_policy(
        {
            "recipe": "llamacpp",
            "effective": {
                "llamacpp_args": "--temp 1.0 --flash-attn auto --top-p 0.95"
            },
        }
    )

    assert decision.eligible is True
    assert decision.reason_code == "change_required"
    assert decision.proposed_change == {
        "llamacpp_args": "--temp 1.0 --top-p 0.95 --flash-attn on"
    }
    with pytest.raises(FrozenInstanceError):
        decision.eligible = False
    with pytest.raises(TypeError):
        decision.proposed_change["llamacpp_args"] = "changed"


@pytest.mark.parametrize(
    ("recipe", "reason"),
    [("flm", "flm_not_supported"), ("vllm", "recipe_not_llamacpp")],
)
def test_flash_attention_policy_requires_factual_llamacpp(recipe, reason):
    decision = evaluate_flash_attention_policy(
        {"recipe": recipe, "effective": {"llamacpp_args": ""}}
    )

    assert decision.eligible is False
    assert decision.reason_code == reason
    assert decision.proposed_change == {}


@pytest.mark.asyncio
async def test_lemonade_engine_rejects_non_loopback_before_network():
    requested = []

    async def handler(request):
        requested.append(request)
        raise AssertionError("non-loopback operation must not reach network")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        registry = _registry(client, addresses=("10.0.0.8",))
        with pytest.raises(EngineExtensionError, match="LEMONADE_LOOPBACK_REQUIRED"):
            await registry.execute(
                _connection(
                    base_url="http://10.0.0.8:13305/api/v1",
                    locality=ConnectionLocality.PRIVATE_NETWORK,
                ),
                "flash_attention",
                {"persist": False},
                approval_ref="approval:preview",
            )

    assert requested == []


@pytest.mark.asyncio
async def test_lemonade_engine_rejects_unknown_operation_before_network():
    requested = []

    async def handler(request):
        requested.append(request)
        raise AssertionError("unknown operation must not reach network")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        registry = _registry(client)
        with pytest.raises(EngineExtensionError, match="EXTENSION_OPERATION_UNSUPPORTED"):
            await registry.execute(
                _connection(),
                "unload_everything",
                {},
                approval_ref="approval:exact",
            )

    assert requested == []


@pytest.mark.asyncio
async def test_lemonade_engine_rejects_flm_without_posting_options():
    methods = []

    async def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return httpx.Response(
            200,
            json={"recipe": "flm", "effective": {}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        registry = _registry(client)
        with pytest.raises(EngineExtensionError, match="FLASH_ATTENTION_FLM_NOT_SUPPORTED"):
            await registry.execute(
                _connection(),
                "flash_attention",
                {"persist": False},
                approval_ref="approval:preview",
            )

    assert methods == ["GET"]


@pytest.mark.asyncio
async def test_flash_attention_persist_requires_exact_dry_run_receipt_and_approval():
    calls: list[tuple[str, str, dict | None]] = []
    current = {
        "model_name": "Carnice-Qwen3.6-MoE-35B-A3B-IQ2_S",
        "recipe": "llamacpp",
        "saved": {"ctx_size": 32768},
        "effective": {"ctx_size": 32768, "llamacpp_args": "--temp 1.0"},
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = None
        if request.content:
            payload = json.loads(request.content.decode("utf-8"))
        calls.append((request.method, request.url.path, payload))
        effective = dict(current["effective"])
        if payload and "llamacpp_args" in payload:
            effective["llamacpp_args"] = payload["llamacpp_args"]
        return httpx.Response(200, json={**current, "effective": effective})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        registry = _registry(client)
        preview = await registry.execute(
            _connection(),
            "flash_attention",
            {"persist": False},
            approval_ref="approval:preview-request",
        )

        assert preview["status"] == "validated"
        assert preview["dry_run_receipt"]["dry_run"] is True
        assert preview["dry_run_receipt"]["approval_ref"].startswith(
            "approval:lemonade:flash_attention:"
        )
        assert calls == [
            ("GET", "/v1/models/Carnice-Qwen3.6-MoE-35B-A3B-IQ2_S/options", None),
            (
                "POST",
                "/v1/models/Carnice-Qwen3.6-MoE-35B-A3B-IQ2_S/options",
                {"llamacpp_args": "--temp 1.0 --flash-attn on", "dry_run": True},
            ),
        ]

        with pytest.raises(EngineExtensionError, match="APPROVAL_REFERENCE_MISMATCH"):
            await registry.execute(
                _connection(),
                "flash_attention",
                {"persist": True, "dry_run_receipt": preview["dry_run_receipt"]},
                approval_ref="approval:wrong",
            )
        assert len(calls) == 2

        result = await registry.execute(
            _connection(),
            "flash_attention",
            {"persist": True, "dry_run_receipt": preview["dry_run_receipt"]},
            approval_ref=preview["dry_run_receipt"]["approval_ref"],
        )

    assert result["status"] == "saved"
    assert result["approval_ref"] == preview["dry_run_receipt"]["approval_ref"]
    assert [payload for method, _path, payload in calls[-2:] if method == "POST"] == [
        {"llamacpp_args": "--temp 1.0 --flash-attn on", "dry_run": True},
        {"llamacpp_args": "--temp 1.0 --flash-attn on"},
    ]
