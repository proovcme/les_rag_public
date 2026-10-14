from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib
import json
import sys
from types import SimpleNamespace

import httpx
import pytest

from proxy.services.model_connection_contracts import (
    CapabilityName, CapabilityObservation, CapabilitySnapshot, CapabilityState,
    ConnectionLocality, ConnectionRole,
)
from proxy.services.model_connection_registry_service import ModelConnectionRegistry
from proxy.services.model_connection_resolver_service import ModelConnectionResolver
from proxy.services.model_secret_service import EnvironmentSecretStore
from proxy.services.openai_compatible_transport_service import OpenAICompatibleTransport


NOW = datetime(2026, 10, 14, tzinfo=timezone.utc)


def _connection(registry, *, locality=ConnectionLocality.LOOPBACK, native=False,
                snapshot=True, stale=False, chat_options=None):
    base_url = {
        ConnectionLocality.LOOPBACK: "http://127.0.0.1:1919/v1",
        ConnectionLocality.PRIVATE_NETWORK: "http://192.168.1.42:1919/prefix/v1",
        ConnectionLocality.REMOTE: "https://cloud.example/v1",
    }[locality]
    revision = registry.create_connection(
        display_name="Assigned answer", base_url=base_url, model_id="assigned-35b",
        locality=locality, requested_context_tokens=8192, secret_ref=None,
        extension_type="ollama" if native else "freetoken", actor="test",
        chat_options=chat_options,
    )
    if snapshot:
        registry.save_capability_snapshot(CapabilitySnapshot(
            snapshot_id=f"cap:{revision.revision_id}",
            connection_revision_id=revision.revision_id,
            observations=(CapabilityObservation(
                capability=CapabilityName.CHAT_COMPLETIONS,
                state=CapabilityState.SUPPORTED, evidence_source="probe",
                observed_at=NOW - timedelta(hours=2), detail="http_200",
            ),),
            observed_at=NOW - timedelta(hours=2),
            expires_at=NOW - timedelta(hours=1) if stale else NOW + timedelta(hours=1),
            transport_options={"chat_protocol": "native_chat_v1" if native else "openai_chat_v1"},
        ), actor="test")
    registry.bind_role(ConnectionRole.ANSWER, revision.revision_id,
                       expected_binding_revision=None, actor="test")
    return revision


def _dependencies(tmp_path, handler):
    registry = ModelConnectionRegistry(tmp_path / "meta.db")
    secrets = EnvironmentSecretStore(tmp_path / ".env", environ={})
    resolver = ModelConnectionResolver(
        registry=registry, secret_store=secrets,
        address_resolver=lambda host, _port: (host,), clock=lambda: NOW,
        allow_private_http=True,
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    transport = OpenAICompatibleTransport(
        client=client, secret_store=secrets,
        peer_verifier=lambda _response, _endpoint: None,
    )
    return registry, resolver, transport, client


def _service():
    return importlib.import_module("proxy.services.model_warmup_service")


class _NoLegacyHTTP:
    def __init__(self, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        pass

    async def post(self, *_args, **_kwargs):
        pytest.fail("warmup must not load an unbound legacy model")


@pytest.mark.asyncio
async def test_startup_preserves_retrieval_and_reranker_then_warms_bound_answer(monkeypatch):
    from proxy import app
    calls = []

    async def retrieve(*_args, **_kwargs):
        calls.append("retrieval")

    async def rerank():
        calls.append("reranker")

    async def warmup():
        calls.append("answer")
        return {"status": "ok", "connection_revision_id": "assigned:r7"}

    async def no_sleep(_seconds):
        pass

    monkeypatch.setitem(sys.modules, "proxy.services.model_warmup_service",
                        SimpleNamespace(warmup_answer_model=warmup))
    monkeypatch.setattr(app, "rag_backend", SimpleNamespace(
        retrieve=retrieve, retrieve_native_hybrid=retrieve))
    monkeypatch.setattr(app, "_warmup_reranker", rerank)
    monkeypatch.setattr(app.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(httpx, "AsyncClient", _NoLegacyHTTP)
    monkeypatch.setenv("MLX_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("LLM_MODEL", "unbound-legacy-9b")

    await app._warmup_models()

    assert calls == ["retrieval", "reranker", "answer"]


@pytest.mark.asyncio
async def test_manual_warmup_uses_same_bound_answer_without_validator(monkeypatch):
    from proxy.routers import runtime
    calls = []
    receipt = {"status": "skipped", "code": "REMOTE_ANSWER_NOT_WARMED"}

    async def warmup():
        calls.append("answer")
        return receipt

    monkeypatch.setitem(sys.modules, "proxy.services.model_warmup_service",
                        SimpleNamespace(warmup_answer_model=warmup))
    monkeypatch.setattr(runtime, "get_runtime_state", lambda: object())
    monkeypatch.setattr(runtime, "chat_admission_for_state",
                        lambda _state: SimpleNamespace(allowed=True))
    monkeypatch.setattr(httpx, "AsyncClient", _NoLegacyHTTP)

    result = await runtime.warmup_models(_admin=object())

    assert calls == ["answer"]
    assert result == {"status": "done", "models": {"main": receipt}}


@pytest.mark.asyncio
@pytest.mark.parametrize("locality", [ConnectionLocality.LOOPBACK, ConnectionLocality.PRIVATE_NETWORK])
async def test_exact_local_binding_ignores_legacy_models_and_preserves_sampler(tmp_path, monkeypatch, locality):
    sent = []

    def handler(request):
        sent.append(request)
        return httpx.Response(200, json={"model": "assigned-35b", "choices": [
            {"message": {"content": "1"}, "finish_reason": "length"}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 1}})

    registry, resolver, transport, client = _dependencies(tmp_path, handler)
    revision = _connection(registry, locality=locality,
                           chat_options={"top_p": 0.8, "top_k": 20, "requested_output_tokens": 256})
    before = (tmp_path / "meta.db").read_bytes()
    monkeypatch.setenv("MLX_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("LLM_MODEL", "unbound-legacy-9b")
    monkeypatch.setenv("MLX_VAL_MODEL", "unbound-validator")
    try:
        receipt = await _service().warmup_answer_model(registry=registry, resolver=resolver, transport=transport)
    finally:
        await client.aclose()

    assert receipt["status"] == "ok"
    assert receipt["connection_revision_id"] == revision.revision_id
    assert len(sent) == 1
    assert str(sent[0].url) == revision.base_url + "/chat/completions"
    body = json.loads(sent[0].content)
    assert body["model"] == revision.model_id
    assert body["max_tokens"] == 1
    assert body["top_p"] == 0.8 and body["top_k"] == 20
    assert "tools" not in body and "response_format" not in body
    assert len(body["messages"]) == 1 and body["messages"][0]["role"] == "user"
    assert (tmp_path / "meta.db").read_bytes() == before


@pytest.mark.asyncio
async def test_native_local_binding_uses_official_chat_without_thinking(tmp_path):
    sent = []

    def handler(request):
        sent.append(request)
        return httpx.Response(200, content=json.dumps({
            "model": "assigned-35b", "message": {"role": "assistant", "content": "1"},
            "done": True, "done_reason": "length", "prompt_eval_count": 8, "eval_count": 1,
        }) + "\n")

    registry, resolver, transport, client = _dependencies(tmp_path, handler)
    revision = _connection(registry, native=True)
    try:
        receipt = await _service().warmup_answer_model(registry=registry, resolver=resolver, transport=transport)
    finally:
        await client.aclose()

    assert receipt["status"] == "ok" and len(sent) == 1
    assert str(sent[0].url) == "http://127.0.0.1:1919/api/chat"
    body = json.loads(sent[0].content)
    assert body["model"] == revision.model_id
    assert body["think"] is False and body["options"]["num_predict"] == 1


@pytest.mark.asyncio
async def test_remote_binding_skips_before_resolution_secrets_or_fallback(tmp_path, monkeypatch):
    registry, resolver, transport, client = _dependencies(tmp_path, lambda _request: pytest.fail("no cloud request"))
    _connection(registry, locality=ConnectionLocality.REMOTE, snapshot=False)
    monkeypatch.setattr(resolver, "resolve_revision", lambda *_args, **_kwargs: pytest.fail("remote resolution forbidden"))
    monkeypatch.setattr(resolver, "resolve_fallback", lambda *_args, **_kwargs: pytest.fail("no other model"))
    monkeypatch.setattr(resolver.secret_store, "resolve", lambda *_args: pytest.fail("no secret read"))
    try:
        receipt = await _service().warmup_answer_model(registry=registry, resolver=resolver, transport=transport)
    finally:
        await client.aclose()

    assert receipt["status"] == "skipped" and receipt["code"] == "REMOTE_ANSWER_NOT_WARMED"
    assert transport.cloud_budget_snapshot()["requests_sent"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["absent", "disabled", "missing_capabilities", "stale_capabilities"])
async def test_unavailable_binding_never_probes_mutates_or_loads_fallback(tmp_path, monkeypatch, state):
    registry, resolver, transport, client = _dependencies(tmp_path, lambda _request: pytest.fail("no inference"))
    if state != "absent":
        revision = _connection(registry, snapshot=state != "missing_capabilities", stale=state == "stale_capabilities")
        if state == "disabled":
            registry.revise_connection(revision.connection_id, expected_revision_id=revision.revision_id,
                                       enabled=False, actor="test")
    before = (tmp_path / "meta.db").read_bytes()
    monkeypatch.setattr(resolver, "resolve_fallback", lambda *_args, **_kwargs: pytest.fail("no fallback"))
    try:
        receipt = await _service().warmup_answer_model(registry=registry, resolver=resolver, transport=transport)
    finally:
        await client.aclose()

    assert receipt["status"] in {"skipped", "error"}
    assert (tmp_path / "meta.db").read_bytes() == before


@pytest.mark.asyncio
async def test_binding_changed_during_resolution_is_skipped_before_dispatch(tmp_path, monkeypatch):
    registry, resolver, transport, client = _dependencies(tmp_path, lambda _request: pytest.fail("stale model must not load"))
    revision = _connection(registry)
    resolve = resolver.resolve_revision

    def changed(*args, **kwargs):
        result = resolve(*args, **kwargs)
        newer = registry.revise_connection(revision.connection_id, expected_revision_id=revision.revision_id,
                                          model_id="newly-selected", actor="test")
        registry.bind_role(ConnectionRole.ANSWER, newer.revision_id,
                           expected_binding_revision=1, actor="test")
        return result

    monkeypatch.setattr(resolver, "resolve_revision", changed)
    try:
        receipt = await _service().warmup_answer_model(registry=registry, resolver=resolver, transport=transport)
    finally:
        await client.aclose()

    assert receipt["status"] == "skipped" and receipt["code"] == "ANSWER_BINDING_CHANGED"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["http", "malformed", "timeout"])
async def test_failed_warmup_does_not_claim_success_or_retry_other_model(tmp_path, monkeypatch, failure):
    sent = []

    def handler(request):
        sent.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("offline timeout", request=request)
        return httpx.Response(503, content=b"unavailable") if failure == "http" else httpx.Response(200, json={})

    registry, resolver, transport, client = _dependencies(tmp_path, handler)
    _connection(registry)
    monkeypatch.setattr(resolver, "resolve_fallback", lambda *_args, **_kwargs: pytest.fail("no fallback"))
    try:
        receipt = await _service().warmup_answer_model(registry=registry, resolver=resolver, transport=transport)
    finally:
        await client.aclose()

    assert receipt["status"] == "error" and len(sent) == 1
