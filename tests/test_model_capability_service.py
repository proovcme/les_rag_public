from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import httpx
import pytest

import proxy.services.model_capability_service as model_capability_service
from proxy.services.model_capability_service import (
    CapabilityProbe,
    CapabilityProbeError,
    CapabilityRequirementError,
    require_capabilities,
)
from proxy.services.model_connection_contracts import (
    CapabilityName,
    CapabilityObservation,
    CapabilitySnapshot,
    CapabilityState,
    ConnectionLocality,
    ModelConnectionRevision,
)
from proxy.services.model_connection_registry_service import ModelConnectionRegistry


NOW = datetime(2026, 8, 28, 9, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,expected,detail", [
    ({"choices": [{"message": {"content": "ordinary answer"}, "finish_reason": "stop"}]}, CapabilityState.UNKNOWN, "http_accepted_no_tool_call"),
    ({"choices": [{"message": {"content": '{"calls":[{"tool":"les_capability_probe","args":{}}]}'}, "finish_reason": "stop"}]}, CapabilityState.UNKNOWN, "http_accepted_no_tool_call"),
    ({"choices": [{"message": {"tool_calls": [{"id": "c1", "type": "function", "function": {"name": "les_capability_probe", "arguments": "{}"}}]}, "finish_reason": "tool_calls"}]}, CapabilityState.SUPPORTED, "native_tool_call_observed"),
    ({"choices": [{"message": {"tool_calls": [{"id": "c1", "type": "function", "function": {"name": "wrong_tool", "arguments": "{}"}}]}, "finish_reason": "tool_calls"}]}, CapabilityState.UNKNOWN, "invalid_tool_call"),
    ({"choices": [{"message": {"tool_calls": [{"type": "function", "function": {"name": "les_capability_probe", "arguments": "{}"}}]}, "finish_reason": "tool_calls"}]}, CapabilityState.UNKNOWN, "invalid_tool_call"),
    ({"choices": [{"message": {"tool_calls": [{"id": "c1", "type": "function", "function": {"name": "les_capability_probe", "arguments": "[]"}}]}, "finish_reason": "tool_calls"}]}, CapabilityState.UNKNOWN, "invalid_tool_call"),
    ({"choices": [{"message": {"tool_calls": [{"id": "c1", "type": "function", "function": {"name": "les_capability_probe", "arguments": '{"unexpected":1}'}}]}, "finish_reason": "tool_calls"}]}, CapabilityState.UNKNOWN, "invalid_tool_call"),
    ({"choices": [{"message": {"tool_calls": [{"id": "c1", "type": "function", "function": {"name": "les_capability_probe", "arguments": "{}"}}]}, "finish_reason": "length"}]}, CapabilityState.UNKNOWN, "response_truncated"),
    (b"not json", CapabilityState.UNKNOWN, "invalid_json"),
])
async def test_tools_probe_requires_witnessed_native_call(payload, expected, detail):
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, content=payload) if isinstance(payload, bytes) else httpx.Response(200, json=payload)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        snapshot = await CapabilityProbe(client=client, resolver=lambda *_: ("127.0.0.1",),
            peer_verifier=_peer_ok, clock=lambda: NOW).probe(_connection(), requested={CapabilityName.TOOLS})
    observation = snapshot.observation(CapabilityName.TOOLS)
    assert observation.state is expected
    assert observation.detail == detail
    assert len(requests) == 1
    assert requests[0]["max_tokens"] >= 128
    assert "les_capability_probe" in requests[0]["messages"][0]["content"]
    assert "tool_choice" not in requests[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload,expected", [
    (404, {"error": {"message": "missing endpoint"}}, CapabilityState.UNKNOWN),
    (400, {"error": {"message": "bad request"}}, CapabilityState.UNKNOWN),
    (400, {"error": {"code": "tools_not_supported", "param": "tools"}}, CapabilityState.UNSUPPORTED),
])
async def test_tools_probe_generic_http_failure_is_not_tools_refusal(status, payload, expected):
    async with _client({("POST", "/v1/chat/completions"): (status, payload)}) as client:
        snapshot = await CapabilityProbe(client=client, resolver=lambda *_: ("127.0.0.1",),
            peer_verifier=_peer_ok, clock=lambda: NOW).probe(_connection(), requested={CapabilityName.TOOLS})
    assert snapshot.state(CapabilityName.TOOLS) is expected


@pytest.mark.parametrize("status", [200, 201, 204])
def test_legacy_tools_http_acceptance_is_unknown_in_public_projection_without_mutation(status):
    from proxy.routers.model_connections import _capabilities
    old = CapabilityObservation(CapabilityName.TOOLS, CapabilityState.SUPPORTED, "probe", NOW, f"http_{status}")
    snapshot = CapabilitySnapshot("cap:old", "conn:test:r1", (old,), NOW, NOW + timedelta(hours=1))
    public = _capabilities(snapshot)[0]
    assert public.state == "unknown"
    assert public.detail == "legacy_http_accepted_no_native_proof"
    assert snapshot.observation(CapabilityName.TOOLS) is old
    assert old.state is CapabilityState.SUPPORTED and old.detail == f"http_{status}"
    with pytest.raises(CapabilityRequirementError):
        require_capabilities(snapshot, {CapabilityName.TOOLS}, now=NOW)


@pytest.mark.asyncio
async def test_tools_probe_oversized_response_has_no_native_proof():
    payload = {"choices": [{"message": {"content": "private-text" * 50, "tool_calls": [
        {"type": "function", "function": {"name": "les_capability_probe", "arguments": "{}"}}]}, "finish_reason": "tool_calls"}]}
    async with _client({("POST", "/v1/chat/completions"): (200, payload)}) as client:
        snapshot = await CapabilityProbe(client=client, resolver=lambda *_: ("127.0.0.1",),
            peer_verifier=_peer_ok, clock=lambda: NOW, response_body_limit=64).probe(_connection(), requested={CapabilityName.TOOLS})
    assert snapshot.state(CapabilityName.TOOLS) is CapabilityState.UNKNOWN
    assert snapshot.observation(CapabilityName.TOOLS).detail == "response_too_large"
    assert "private-text" not in repr(snapshot)


@pytest.mark.parametrize("source", ["template_default", "operator_declaration"])
def test_advertised_tools_are_not_projected_as_witnessed_support(source):
    from proxy.routers.model_connections import _capabilities
    claim = CapabilityObservation(CapabilityName.TOOLS, CapabilityState.SUPPORTED, source, NOW, "template_claim")
    snapshot = CapabilitySnapshot("cap:claim", "conn:test:r1", (claim,), NOW, NOW + timedelta(hours=1))
    public = _capabilities(snapshot)[0]
    assert public.state == "unknown" and public.detail == "advertised_tools_unverified"
    assert snapshot.observation(CapabilityName.TOOLS) is claim
    with pytest.raises(CapabilityRequirementError):
        require_capabilities(snapshot, {CapabilityName.TOOLS}, now=NOW)


def test_witnessed_tools_still_satisfy_strict_requirement():
    proof = CapabilityObservation(CapabilityName.TOOLS, CapabilityState.SUPPORTED, "probe", NOW, "native_tool_call_observed")
    snapshot = CapabilitySnapshot("cap:witness", "conn:test:r1", (proof,), NOW, NOW + timedelta(hours=1))
    require_capabilities(snapshot, {CapabilityName.TOOLS}, now=NOW)


@pytest.mark.parametrize("source", ["operator_declaration", "template_default"])
def test_explicit_tools_unsupported_is_preserved_in_public_projection(source):
    from proxy.routers.model_connections import _capabilities
    refusal = CapabilityObservation(CapabilityName.TOOLS, CapabilityState.UNSUPPORTED, source, NOW, "tools_disabled")
    snapshot = CapabilitySnapshot("cap:refused", "conn:test:r1", (refusal,), NOW, NOW + timedelta(hours=1))
    public = _capabilities(snapshot)[0]
    assert public.state == "unsupported" and public.detail == "tools_disabled"
    assert snapshot.observation(CapabilityName.TOOLS) is refusal


def _connection(
    *,
    secret_ref: str | None = None,
    extension_type: str | None = None,
) -> ModelConnectionRevision:
    return ModelConnectionRevision(
        connection_id="conn:test",
        revision_id="conn:test:r1",
        revision_no=1,
        display_name="Test model",
        protocol="openai_compatible",
        base_url="http://127.0.0.1:1919/v1",
        model_id="qwen-test",
        locality=ConnectionLocality.LOOPBACK,
        requested_context_tokens=8192,
        secret_ref=secret_ref,
        extension_type=extension_type,
        enabled=True,
        created_at=NOW.isoformat(),
        created_by="admin:test",
    )


def _client(routes: dict[tuple[str, str], tuple[int, object]]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        status, payload = routes.get(
            (request.method, request.url.path),
            (404, {"error": "missing"}),
        )
        if isinstance(payload, bytes):
            return httpx.Response(status, content=payload)
        return httpx.Response(status, json=payload)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)


def _peer_ok(_response, _endpoint) -> None:
    return None


@pytest.mark.asyncio
async def test_probe_records_supported_unsupported_unknown_without_model_text() -> None:
    async with _client(
        {
            ("GET", "/v1/models"): (200, {"data": [{"id": "qwen-test"}]}),
            ("POST", "/v1/chat/completions"): (
                200,
                {"choices": [{"message": {"content": "sensitive-output"}}]},
            ),
            ("POST", "/v1/responses"): (404, {"error": "missing"}),
        }
    ) as client:
        snapshot = await CapabilityProbe(
            client=client,
            resolver=lambda _host, _port: ("127.0.0.1",),
            peer_verifier=_peer_ok,
            clock=lambda: NOW,
        ).probe(
            _connection(),
            requested={
                CapabilityName.MODELS,
                CapabilityName.CHAT_COMPLETIONS,
                CapabilityName.RESPONSES,
            },
        )

    assert snapshot.state(CapabilityName.CHAT_COMPLETIONS) is CapabilityState.SUPPORTED
    assert snapshot.state(CapabilityName.RESPONSES) is CapabilityState.UNSUPPORTED
    assert snapshot.state(CapabilityName.EMBEDDINGS) is CapabilityState.UNKNOWN
    assert snapshot.observation(CapabilityName.CHAT_COMPLETIONS).evidence_source == "probe"
    assert "sensitive-output" not in repr(snapshot)
    assert snapshot.transport_options == {"max_output_field": "max_tokens"}


@pytest.mark.asyncio
async def test_probe_records_native_chat_profile_only_after_live_probe() -> None:
    requests: list[tuple[str, str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        requests.append((request.method, request.url.path, body))
        if request.url.path == "/v1/chat/completions":
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
        if request.url.path == "/api/chat":
            return httpx.Response(200, json={"message": {"content": "ok"}, "done": True})
        if request.url.path == "/api/show":
            return httpx.Response(
                200,
                json={
                    "model_info": {"qwen35.context_length": 32768},
                    "details": {"parameter_size": "9B"},
                },
            )
        return httpx.Response(404, json={"error": "missing"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        snapshot = await CapabilityProbe(
            client=client,
            resolver=lambda _host, _port: ("127.0.0.1",),
            peer_verifier=_peer_ok,
            clock=lambda: NOW,
        ).probe(
            _connection(extension_type="ollama"),
            requested={CapabilityName.CHAT_COMPLETIONS},
        )

    assert snapshot.transport_options["chat_protocol"] == "native_chat_v1"
    assert snapshot.transport_options["observed_context_tokens"] == "32768"
    native = next(item for item in requests if item[1] == "/api/chat")
    assert native[2]["think"] is False
    show = next(item for item in requests if item[1] == "/api/show")
    assert show[2] == {"model": "qwen-test"}


@pytest.mark.asyncio
async def test_probe_follows_no_redirect_even_when_client_default_does() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/v1/models":
            return httpx.Response(302, headers={"location": "/internal"})
        return httpx.Response(200, json={"data": []})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
    ) as client:
        snapshot = await CapabilityProbe(
            client=client,
            resolver=lambda _host, _port: ("127.0.0.1",),
            peer_verifier=_peer_ok,
            clock=lambda: NOW,
        ).probe(_connection(), requested={CapabilityName.MODELS})

    assert calls == ["/v1/models"]
    assert snapshot.state(CapabilityName.MODELS) is CapabilityState.UNKNOWN
    assert snapshot.observation(CapabilityName.MODELS).detail == "redirect_rejected"


@pytest.mark.asyncio
async def test_probe_caps_response_body_without_retaining_it() -> None:
    async with _client({("GET", "/v1/models"): (200, b"x" * 129)}) as client:
        snapshot = await CapabilityProbe(
            client=client,
            resolver=lambda _host, _port: ("127.0.0.1",),
            peer_verifier=_peer_ok,
            clock=lambda: NOW,
            response_body_limit=128,
        ).probe(_connection(), requested={CapabilityName.MODELS})

    assert snapshot.state(CapabilityName.MODELS) is CapabilityState.UNKNOWN
    assert snapshot.observation(CapabilityName.MODELS).detail == "response_too_large"
    assert "xxxxxxxx" not in repr(snapshot)


@pytest.mark.asyncio
async def test_probe_does_not_decode_models_payload_without_lemonade_extension(
    monkeypatch,
) -> None:
    def unexpected_decode(_payload: object) -> object:
        raise AssertionError("non-Lemonade model payload must not be decoded")

    monkeypatch.setattr(model_capability_service.json, "loads", unexpected_decode)

    async with _client({("GET", "/v1/models"): (200, {"data": [{"id": "qwen-test"}]})}) as client:
        snapshot = await CapabilityProbe(
            client=client,
            resolver=lambda _host, _port: ("127.0.0.1",),
            peer_verifier=_peer_ok,
            clock=lambda: NOW,
        ).probe(_connection(), requested={CapabilityName.MODELS})

    assert snapshot.state(CapabilityName.MODELS) is CapabilityState.SUPPORTED


@pytest.mark.asyncio
@pytest.mark.parametrize('status,payload', [
    (404, {}), (200, {'model_name':'another-model','resolved_ctx_size':262144}),
    (200, {'model_name':'qwen-test','resolved_ctx_size':-1}),
    (200, b'not-json'), (200, b'x'*513), (302, {}),
])
async def test_lemonade_options_cannot_invent_capacity_from_unusable_response(status,payload):
    calls = []
    def handler(request):
        calls.append(request.url.path)
        if request.url.path == '/v1/models':
            return httpx.Response(200,json={'data':[dict(id='qwen-test',recipe='llamacpp',max_context_window=262144)]})
        if request.url.path == '/v1/models/qwen-test/options':
            if status == 302:
                return httpx.Response(302,headers={'Location':'/internal'})
            return httpx.Response(status,content=payload) if isinstance(payload,bytes) else httpx.Response(status,json=payload)
        raise AssertionError(f'Unexpected route {request.url.path}')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler),follow_redirects=True) as client:
        snapshot = await CapabilityProbe(client=client,resolver=lambda *_:('127.0.0.1',),
            peer_verifier=_peer_ok,response_body_limit=512).probe(
                _connection(extension_type='lemonade'),requested={CapabilityName.MODELS})
    assert 'observed_context_tokens' not in snapshot.transport_options
    assert snapshot.transport_options['observed_backend'] == 'llama_cpp'
    assert calls == ['/v1/models','/v1/models/qwen-test/options']


@pytest.mark.asyncio
async def test_probe_validates_connected_peer_before_consuming_stream() -> None:
    body_consumed = False
    peer_checks: list[bool] = []

    class ProbeStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            nonlocal body_consumed
            body_consumed = True
            yield b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
            yield b"data: [DONE]\n\n"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=ProbeStream())

    def peer_before_close(response: httpx.Response, _endpoint) -> None:
        peer_checks.append(body_consumed)
        if body_consumed:
            raise ValueError("peer metadata is no longer available after body consumption")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
    ) as client:
        snapshot = await CapabilityProbe(
            client=client,
            resolver=lambda _host, _port: ("127.0.0.1",),
            peer_verifier=peer_before_close,
            clock=lambda: NOW,
        ).probe(_connection(), requested={CapabilityName.STREAMING})

    assert peer_checks == [False]
    assert body_consumed is True
    assert snapshot.state(CapabilityName.STREAMING) is CapabilityState.SUPPORTED


def test_required_capability_rejects_stale_snapshot() -> None:
    snapshot = CapabilitySnapshot(
        snapshot_id="cap:stale",
        connection_revision_id="conn:test:r1",
        observations=(
            CapabilityObservation(
                capability=CapabilityName.CHAT_COMPLETIONS,
                state=CapabilityState.SUPPORTED,
                evidence_source="probe",
                observed_at=NOW - timedelta(days=2),
                detail="http_200",
            ),
        ),
        observed_at=NOW - timedelta(days=2),
        expires_at=NOW - timedelta(days=1),
        transport_options={},
    )

    with pytest.raises(CapabilityRequirementError, match="CAPABILITY_SNAPSHOT_STALE"):
        require_capabilities(snapshot, {CapabilityName.CHAT_COMPLETIONS}, now=NOW)


def test_template_default_cannot_authorize_tool_calling() -> None:
    snapshot = CapabilitySnapshot(
        snapshot_id="cap:template",
        connection_revision_id="conn:test:r1",
        observations=(
            CapabilityObservation(
                capability=CapabilityName.TOOLS,
                state=CapabilityState.SUPPORTED,
                evidence_source="template_default",
                observed_at=NOW,
                detail="template_claim",
            ),
        ),
        observed_at=NOW,
        expires_at=NOW + timedelta(hours=24),
        transport_options={},
    )

    with pytest.raises(CapabilityRequirementError, match="CAPABILITY_EVIDENCE_INSUFFICIENT"):
        require_capabilities(snapshot, {CapabilityName.TOOLS}, now=NOW)


def test_supported_fresh_probe_satisfies_requirement() -> None:
    snapshot = CapabilitySnapshot(
        snapshot_id="cap:fresh",
        connection_revision_id="conn:test:r1",
        observations=(
            CapabilityObservation(
                capability=CapabilityName.EMBEDDINGS,
                state=CapabilityState.SUPPORTED,
                evidence_source="probe",
                observed_at=NOW,
                detail="http_200",
            ),
        ),
        observed_at=NOW,
        expires_at=NOW + timedelta(hours=24),
        transport_options={},
    )

    require_capabilities(snapshot, {CapabilityName.EMBEDDINGS}, now=NOW)


@pytest.mark.asyncio
async def test_probe_and_store_persists_one_immutable_snapshot(tmp_path) -> None:
    registry = ModelConnectionRegistry(tmp_path / "meta.db")
    revision = registry.create_connection(
        display_name="Stored probe",
        base_url="http://127.0.0.1:1919/v1",
        model_id="qwen-test",
        locality=ConnectionLocality.LOOPBACK,
        requested_context_tokens=8192,
        secret_ref=None,
        extension_type=None,
        actor="admin:test",
    )
    async with _client({("GET", "/v1/models"): (200, {"data": []})}) as client:
        probe = CapabilityProbe(
            client=client,
            resolver=lambda _host, _port: ("127.0.0.1",),
            peer_verifier=_peer_ok,
            clock=lambda: NOW,
        )
        snapshot = await probe.probe_and_store(
            revision,
            requested={CapabilityName.MODELS},
            registry=registry,
            actor="admin:test",
        )

    assert registry.latest_capability_snapshot(revision.revision_id) == snapshot


@pytest.mark.asyncio
async def test_probe_rejects_empty_request_set() -> None:
    async with _client({}) as client:
        probe = CapabilityProbe(
            client=client,
            resolver=lambda _host, _port: ("127.0.0.1",),
            peer_verifier=_peer_ok,
            clock=lambda: NOW,
        )
        with pytest.raises(CapabilityProbeError, match="CAPABILITY_REQUEST_EMPTY"):
            await probe.probe(_connection(), requested=set())
