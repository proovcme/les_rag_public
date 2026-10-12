from __future__ import annotations

from datetime import datetime, timedelta, timezone
import inspect
import json

import httpx
import pytest

from proxy.services.model_connection_contracts import (
    CapabilityName,
    CapabilityObservation,
    CapabilitySnapshot,
    CapabilityState,
    ConnectionLocality,
)
from proxy.services.model_connection_resolver_service import ResolvedModelConnection
from proxy.services.model_connection_security_service import ValidatedEndpoint
from proxy.services.model_execution_preset_service import (
    BackendCapacity,
    resolve_execution_preset,
)
from proxy.services.model_secret_service import EnvironmentSecretStore
from proxy.services.openai_compatible_transport_service import (
    InferenceRequest,
    ModelTransportError,
    OpenAICompatibleTransport,
)


NOW = datetime(2026, 8, 28, tzinfo=timezone.utc)


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", [None, "native_chat_v1"])
@pytest.mark.parametrize("state,source,detail", [
    (CapabilityState.UNKNOWN, "probe", "http_accepted_no_tool_call"),
    (CapabilityState.SUPPORTED, "template_default", "template_claim"),
    (CapabilityState.SUPPORTED, "operator_declaration", "operator_claim"),
    (CapabilityState.SUPPORTED, "probe", "http_201"),
    (CapabilityState.SUPPORTED, "probe", "http_204"),
])
async def test_unknown_optional_tools_preserve_primary_native_call_without_fallback(tmp_path, protocol, state, source, detail):
    from dataclasses import replace
    from proxy.services.canonical_route_service import BoundModelChatRunner, CanonicalRouteMode
    primary = _resolved(chat_protocol=protocol)
    observations = tuple(replace(item, state=state, evidence_source=source, detail=detail)
        if item.capability is CapabilityName.TOOLS else item for item in primary.capability_snapshot.observations)
    primary = replace(primary, capability_snapshot=replace(primary.capability_snapshot, observations=observations))
    bodies = []
    def handler(request):
        bodies.append(json.loads(request.content))
        call = {"id": "r10-call", "type": "function", "function": {"name": "search_sources", "arguments": "{}"}}
        return httpx.Response(200, json=({"message": {"tool_calls": [call]}, "done": True}
            if protocol else {"choices": [{"message": {"tool_calls": [call]}, "finish_reason": "tool_calls"}]}))
    class Resolver:
        def resolve(self, _role):
            return primary
        def resolve_fallback(self, *_):
            pytest.fail("UNKNOWN optional tools must not change the selected model route")
    transport, client = _transport(tmp_path, handler)
    tools = ({"type": "function", "function": {"name": "search_sources", "parameters": {"type": "object"}}},)
    try:
        result = await BoundModelChatRunner(resolver=Resolver(), transport=transport).complete(
            mode=CanonicalRouteMode.ACTIVE, request=InferenceRequest(messages=({"role": "user", "content": "Read"},),
                max_output_tokens=32, tools=tools), legacy_complete=lambda _: pytest.fail("no legacy route"))
    finally:
        await client.aclose()
    assert len(bodies) == 1 and bodies[0]["tools"] == list(tools)
    assert result.connection.revision_id == primary.revision_id and not result.fallback_used
    assert result.response.tool_calls[0]["function"]["name"] == "search_sources"


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", [None, "native_chat_v1"])
async def test_optional_tools_do_not_weaken_mandatory_chat_gate(tmp_path, protocol):
    from dataclasses import replace
    primary = _resolved(chat_protocol=protocol)
    observations = tuple(replace(item, state=CapabilityState.UNKNOWN)
        if item.capability in {CapabilityName.CHAT_COMPLETIONS, CapabilityName.TOOLS} else item
        for item in primary.capability_snapshot.observations)
    primary = replace(primary, capability_snapshot=replace(primary.capability_snapshot, observations=observations))
    transport, client = _transport(tmp_path, lambda _: pytest.fail("CHAT rejection must occur before sending"))
    try:
        with pytest.raises(ModelTransportError, match="CAPABILITY_REQUIRED: chat_completions"):
            await transport.complete(primary, InferenceRequest(messages=({"role": "user", "content": "Read"},),
                max_output_tokens=32, tools=({"type": "function", "function": {"name": "search_sources"}},)))
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", [None, "native_chat_v1"])
@pytest.mark.parametrize("source", ["operator_declaration", "template_default"])
async def test_explicit_tools_unsupported_prevents_optional_send(tmp_path, protocol, source):
    from dataclasses import replace
    primary = _resolved(chat_protocol=protocol)
    observations = tuple(replace(item, state=CapabilityState.UNSUPPORTED, evidence_source=source, detail="tools_disabled")
        if item.capability is CapabilityName.TOOLS else item for item in primary.capability_snapshot.observations)
    primary = replace(primary, capability_snapshot=replace(primary.capability_snapshot, observations=observations))
    transport, client = _transport(tmp_path, lambda _: pytest.fail("Explicit tools refusal must prevent sending"))
    try:
        with pytest.raises(ModelTransportError, match="CAPABILITY_REQUIRED: tools"):
            await transport.complete(primary, InferenceRequest(messages=({"role": "user", "content": "Read"},),
                max_output_tokens=32, tools=({"type": "function", "function": {"name": "search_sources"}},)))
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "io", "cancel", "retry"])
async def test_request_local_audit_captures_wire_body_without_headers(tmp_path, failure):
    import asyncio
    import hashlib
    from proxy.services.model_request_audit_service import ModelRequestAudit

    refs = []
    audit = ModelRequestAudit(directory=tmp_path, purpose="answer", refs=refs)
    sent = []

    async def handler(request):
        sent.append(request.content)
        if failure == "io":
            raise httpx.ConnectError("private upstream detail", request=request)
        if failure == "cancel":
            raise asyncio.CancelledError()
        if failure == "retry" and len(sent) == 1:
            return httpx.Response(502, content=b"System message must be at the beginning")
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = OpenAICompatibleTransport(client=client, secret_store=EnvironmentSecretStore(tmp_path / "unused.env"),
                                             peer_verifier=lambda *_: None)
        transport._headers = lambda _: {"Authorization": "Bearer SECRET_SENTINEL"}
        request = InferenceRequest(messages=({"role": "system", "content": "SYSTEM"},
                                             {"role": "user", "content": "FINAL"}),
                                   tools=({"type": "function", "function": {"name": "search_sources",
                                          "parameters": {"type": "object", "properties": {"q": {"type": "string"}}}}},),
                                   max_output_tokens=17, request_audit=audit)
        if failure == "io":
            with pytest.raises(ModelTransportError):
                await transport.complete(_resolved(), request)
        elif failure == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await transport.complete(_resolved(), request)
        else:
            assert (await transport.complete(_resolved(), request)).text == "ok"
    assert len(refs) == len(sent) == (2 if failure == "retry" else 1)
    for ref, wire in zip(refs, sent):
        assert (tmp_path / ref["body_file"]).read_bytes() == wire
        assert ref["sha256"] == hashlib.sha256(wire).hexdigest()
        assert ref["tool_choice"] == "omitted"
        assert ref["revision_id"] == "conn:c1:r1"
        assert "SECRET_SENTINEL" not in json.dumps(ref)
        assert "SECRET_SENTINEL" not in "".join(p.read_text() for p in tmp_path.iterdir())
    assert refs[-1]["status"] == {"io": "transport_error", "cancel": "cancelled"}.get(failure, "response_headers_observed")
    assert all("send_attempt" in p.read_text() for p in tmp_path.glob("*.send_attempt.json"))
    if failure == "retry":
        assert json.loads(sent[1])["messages"] == [{"role": "user", "content": "SYSTEM\n\nFINAL"}]


@pytest.mark.asyncio
async def test_request_audit_write_failure_does_not_retry_or_block_inference(tmp_path):
    from proxy.services.model_request_audit_service import ModelRequestAudit
    unavailable = tmp_path / "not-a-directory"
    unavailable.write_text("occupied")
    refs, sent = [], []
    async def handler(request):
        sent.append(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = OpenAICompatibleTransport(client=client, secret_store=EnvironmentSecretStore(tmp_path / "unused.env"), peer_verifier=lambda *_: None)
        result = await transport.complete(_resolved(), InferenceRequest(messages=({"role": "user", "content": "FINAL"},),
            max_output_tokens=17, request_audit=ModelRequestAudit(directory=unavailable, purpose="answer_read", refs=refs)))
    assert result.text == "ok" and len(sent) == 1
    assert refs[0]["status"] == "audit_unavailable"
    assert refs[0]["error_code"] == "MODEL_REQUEST_AUDIT_WRITE_FAILED"
    assert "sha256" not in refs[0] and "body_file" not in refs[0]


@pytest.mark.asyncio
async def test_request_body_audit_tracks_fallback_connection_and_native_body(tmp_path):
    from dataclasses import replace
    from proxy.services.model_request_audit_service import ModelRequestAudit
    from proxy.services.canonical_route_service import BoundModelChatRunner, CanonicalRouteMode
    refs, sent = [], []
    primary = _resolved()
    fallback = replace(_resolved(chat_protocol="native_chat_v1"), revision_id="conn:fallback:r2", model_id="fallback-model")
    class Resolver:
        def resolve(self, _role):
            return primary
        def resolve_fallback(self, _revision):
            return fallback
    async def handler(request):
        sent.append(request.content)
        if len(sent) == 1:
            raise httpx.ConnectError("upstream", request=request)
        return httpx.Response(200, content=b'{"message":{"content":"ok"},"done":true,"done_reason":"stop"}\n')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = OpenAICompatibleTransport(client=client, secret_store=EnvironmentSecretStore(tmp_path / "unused.env"), peer_verifier=lambda *_: None)
        runner = BoundModelChatRunner(resolver=Resolver(), transport=transport)
        result = await runner.complete(mode=CanonicalRouteMode.ACTIVE,
            request=InferenceRequest(messages=({"role": "user", "content": "FINAL"},), max_output_tokens=17,
                request_audit=ModelRequestAudit(directory=tmp_path, purpose="answer", refs=refs)),
            legacy_complete=lambda _: pytest.fail("no legacy call"))
    assert result.response.text == "ok" and result.fallback_used
    assert [ref["revision_id"] for ref in refs] == ["conn:c1:r1", "conn:fallback:r2"]
    assert [ref["status"] for ref in refs] == ["transport_error", "response_headers_observed"]
    assert json.loads(sent[1])["options"]["num_predict"] == 17
    assert json.loads(sent[1])["model"] == "fallback-model"
    assert all((tmp_path / ref["body_file"]).read_bytes() == wire for ref, wire in zip(refs, sent))


@pytest.mark.asyncio
async def test_streaming_audit_records_actual_stream_body(tmp_path):
    from proxy.services.model_request_audit_service import ModelRequestAudit
    refs, sent = [], []
    async def handler(request):
        sent.append(request.content)
        return httpx.Response(200, content=b'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = OpenAICompatibleTransport(client=client, secret_store=EnvironmentSecretStore(tmp_path / "unused.env"), peer_verifier=lambda *_: None)
        events = [event async for event in transport.stream(_resolved(max_output_field="max_completion_tokens"),
            InferenceRequest(messages=({"role": "user", "content": "READ"},), max_output_tokens=17,
                request_audit=ModelRequestAudit(directory=tmp_path, purpose="answer_read", refs=refs)))]
    assert events
    assert json.loads(sent[0])["stream"] is True
    assert json.loads(sent[0])["max_completion_tokens"] == 17
    assert (tmp_path / refs[0]["body_file"]).read_bytes() == sent[0]


@pytest.mark.parametrize("failed_event", ["prepared", "send_attempt", "response_headers_observed"])
def test_audit_event_failure_retains_written_body_and_safe_correlation(tmp_path, failed_event, monkeypatch):
    import hashlib
    from proxy.services.model_request_audit_service import ModelRequestAudit
    refs = []
    audit = ModelRequestAudit(directory=tmp_path, purpose="answer_read", refs=refs)
    write = audit._write
    def fail_event(filename, data):
        if filename.endswith("." + failed_event + ".json"):
            raise OSError("private disk failure detail")
        write(filename, data)
    monkeypatch.setattr(audit, "_write", fail_event)
    body = b'{"messages":[{"role":"user","content":"FINAL"}]}'
    ref = audit.prepare(body, revision_id="conn:actual:r2", model_id="actual-model")
    if failed_event != "prepared":
        audit.mark(ref, failed_event, http_status=200)
    assert ref["status"] == "audit_unavailable"
    assert ref["purpose"] == "answer_read" and ref["attempt"] == 1
    assert ref["revision_id"] == "conn:actual:r2" and ref["model_id"] == "actual-model"
    assert (tmp_path / ref["body_file"]).read_bytes() == body
    assert ref["sha256"] == hashlib.sha256(body).hexdigest()
    assert "http_status" not in ref
    assert not (tmp_path / (ref["receipt_id"] + "." + failed_event + ".json")).exists()
    assert "private disk failure detail" not in json.dumps(ref)


def test_audit_uuid_collision_never_overwrites_final_body(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from proxy.services import model_request_audit_service as service
    monkeypatch.setattr(service, "uuid4", lambda: SimpleNamespace(hex="forcedcollision"))
    refs = []
    audit = service.ModelRequestAudit(directory=tmp_path, purpose="answer", refs=refs)
    original = b'{"messages":[{"role":"user","content":"ORIGINAL"}]}'
    first = audit.prepare(original, revision_id="conn:r1", model_id="first")
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    second = audit.prepare(b'{"messages":[]}', revision_id="conn:r2", model_id="second")
    assert (tmp_path / first["body_file"]).read_bytes() == original
    assert all((tmp_path / name).read_bytes() == data for name, data in before.items())
    assert second["status"] == "audit_unavailable"
    assert second["revision_id"] == "conn:r2" and second["attempt"] == 2
    assert "sha256" not in second and "body_file" not in second


def _resolved(
    *,
    display_name: str = "Connection",
    secret_ref: str | None = None,
    max_output_field: str = "max_tokens",
    chat_protocol: str | None = None,
) -> ResolvedModelConnection:
    observations = tuple(
        CapabilityObservation(
            capability=capability,
            state=CapabilityState.SUPPORTED,
            evidence_source="probe",
            observed_at=NOW,
            detail="http_200",
        )
        for capability in (
            CapabilityName.CHAT_COMPLETIONS,
            CapabilityName.STREAMING,
            CapabilityName.TOOLS,
            CapabilityName.STRUCTURED_OUTPUT,
            CapabilityName.EMBEDDINGS,
        )
    )
    transport_options = {"max_output_field": max_output_field}
    if chat_protocol is not None:
        transport_options["chat_protocol"] = chat_protocol
    snapshot = CapabilitySnapshot(
        snapshot_id="cap:c1:r1",
        connection_revision_id="conn:c1:r1",
        observations=observations,
        observed_at=NOW,
        expires_at=NOW + timedelta(days=1),
        transport_options=transport_options,
    )
    endpoint = ValidatedEndpoint(
        canonical_base_url="http://127.0.0.1:1919/v1",
        locality=ConnectionLocality.LOOPBACK,
        host="127.0.0.1",
        port=1919,
        allowed_addresses=frozenset(),
    )
    return ResolvedModelConnection(
        connection_id="conn:c1",
        revision_id="conn:c1:r1",
        display_name=display_name,
        base_url=endpoint.canonical_base_url,
        model_id="model-1",
        locality=ConnectionLocality.LOOPBACK,
        requested_context_tokens=8192,
        secret_ref=secret_ref,
        extension_type=None,
        capability_snapshot=snapshot,
        endpoint=endpoint,
        effective_preset=resolve_execution_preset(
            BackendCapacity("connection", "model-1", 8192, True, "probe")
        ),
    )


def _transport(tmp_path, handler, *, environ=None, body_limit=32768, peer_verifier=None):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenAICompatibleTransport(
        client=client,
        secret_store=EnvironmentSecretStore(tmp_path / ".env", environ=environ or {}),
        peer_verifier=peer_verifier or (lambda _response, _endpoint: None),
        response_body_limit=body_limit,
    ), client


@pytest.mark.asyncio
@pytest.mark.parametrize("display_name", ["FreeToken", "Ollama", "Lemonade", "MLX", "Renamed"])
async def test_transport_behavior_does_not_depend_on_display_name(tmp_path, display_name):
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "model": "observed-model-1",
                "choices": [{"message": {"content": "Готово"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 1},
            },
        )

    transport, client = _transport(tmp_path, handler)
    try:
        result = await transport.complete(
            _resolved(display_name=display_name),
            InferenceRequest(
                messages=({"role": "user", "content": "test"},),
                max_output_tokens=64,
            ),
        )
    finally:
        await client.aclose()

    assert result.text == "Готово"
    assert result.model_id == "observed-model-1"
    assert requests[0].url.path.endswith("/v1/chat/completions")


@pytest.mark.asyncio
async def test_complete_preserves_tool_calls_auth_and_output_field(tmp_path):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [{
                    "message": {
                        "reasoning_content": "checked",
                        "tool_calls": [{
                            "id": "call-1",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": "{\"id\":1}"},
                        }],
                    },
                    "finish_reason": "tool_calls",
                }],
                "usage": {"total_tokens": 9},
            },
        )

    transport, client = _transport(
        tmp_path,
        handler,
        environ={"OPENAI_API_KEY": "secret-value"},
    )
    try:
        result = await transport.complete(
            _resolved(
                secret_ref="env:OPENAI_API_KEY",
                max_output_field="max_completion_tokens",
            ),
            InferenceRequest(
                messages=({"role": "user", "content": "test"},),
                max_output_tokens=21,
                tools=({"type": "function", "function": {"name": "read_file"}},),
            ),
        )
    finally:
        await client.aclose()

    assert captured["request"].headers["Authorization"] == "Bearer secret-value"
    assert captured["body"]["max_completion_tokens"] == 21
    assert "max_tokens" not in captured["body"]
    assert result.text == "checked"
    assert result.tool_calls[0]["function"]["name"] == "read_file"
    assert result.finish_reason == "tool_calls"


@pytest.mark.asyncio
async def test_complete_places_system_messages_before_conversation(tmp_path):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]},
        )

    transport, client = _transport(tmp_path, handler)
    try:
        await transport.complete(
            _resolved(),
            InferenceRequest(
                messages=(
                    {"role": "user", "content": "question"},
                    {"role": "system", "content": "policy"},
                    {"role": "assistant", "content": "prior"},
                    {"role": "system", "content": "evidence rules"},
                ),
                max_output_tokens=32,
            ),
        )
    finally:
        await client.aclose()

    assert [item["role"] for item in captured["body"]["messages"]] == [
        "system",
        "user",
        "assistant",
    ]
    assert captured["body"]["messages"][0]["content"] == "policy\n\nevidence rules"


@pytest.mark.asyncio
async def test_complete_uses_capability_selected_native_chat_without_reasoning(tmp_path):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "observed-model-1",
                "message": {"content": "ЛЕС", "thinking": ""},
                "done_reason": "stop",
                "prompt_eval_count": 10,
                "eval_count": 1,
            },
        )

    transport, client = _transport(tmp_path, handler)
    try:
        result = await transport.complete(
            _resolved(chat_protocol="native_chat_v1"),
            InferenceRequest(
                messages=({"role": "user", "content": "Ответь одним словом"},),
                max_output_tokens=64,
                temperature=0.0,
            ),
        )
    finally:
        await client.aclose()

    assert captured["path"] == "/api/chat"
    assert captured["body"]["think"] is False
    assert captured["body"]["options"] == {
        "num_predict": 64,
        "num_ctx": 8192,
        "temperature": 0.0,
    }
    assert result.text == "ЛЕС"
    assert result.finish_reason == "stop"
    assert result.usage == {"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11}


@pytest.mark.asyncio
async def test_native_complete_consumes_incremental_events_into_unchanged_answer(tmp_path):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        events = (
            {"model": "observed-model-1", "message": {"content": "Первая "}, "done": False},
            {"model": "observed-model-1", "message": {"content": "строка"}, "done": False},
            {
                "model": "observed-model-1",
                "message": {"content": ""},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 12,
                "eval_count": 2,
            },
        )
        return httpx.Response(
            200,
            content=b"".join(
                json.dumps(event, ensure_ascii=False).encode("utf-8") + b"\n"
                for event in events
            ),
            headers={"content-type": "application/x-ndjson"},
        )

    # The wire representation contains repeated per-event metadata and is much
    # larger than the model-authored text.  The configured response limit owns
    # semantic output, not native streaming protocol overhead.
    transport, client = _transport(tmp_path, handler, body_limit=64)
    try:
        result = await transport.complete(
            _resolved(chat_protocol="native_chat_v1"),
            InferenceRequest(
                messages=({"role": "user", "content": "Верни две части"},),
                max_output_tokens=64,
            ),
        )
    finally:
        await client.aclose()

    assert captured["body"]["stream"] is True
    assert result.text == "Первая строка"
    assert result.finish_reason == "stop"
    assert result.usage == {"prompt_tokens": 12, "completion_tokens": 2, "total_tokens": 14}


@pytest.mark.asyncio
async def test_complete_retries_without_system_role_for_restrictive_compatible_server(tmp_path):
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if any(item.get("role") == "system" for item in body["messages"]):
            return httpx.Response(502, json={"error": "System message must be at the beginning."})
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]},
        )

    transport, client = _transport(tmp_path, handler)
    try:
        result = await transport.complete(
            _resolved(),
            InferenceRequest(
                messages=(
                    {"role": "system", "content": "policy"},
                    {"role": "user", "content": "question"},
                ),
                max_output_tokens=32,
            ),
        )
    finally:
        await client.aclose()

    assert result.text == "ok"
    assert len(bodies) == 2
    assert [item["role"] for item in bodies[1]["messages"]] == ["user"]
    assert bodies[1]["messages"][0]["content"] == "policy\n\nquestion"


@pytest.mark.asyncio
async def test_stream_normalizes_text_deltas_and_finish(tmp_path):
    payload = (
        'data: {"model":"observed-stream-model","choices":[{"delta":{"reasoning":"one"}}]}\n\n'
        'data: {"model":"observed-stream-model","choices":[{"delta":{"content":" two"},"finish_reason":"stop"}]}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=payload, headers={"content-type": "text/event-stream"})

    transport, client = _transport(tmp_path, handler)
    try:
        events = [
            event
            async for event in transport.stream(
                _resolved(),
                InferenceRequest(
                    messages=({"role": "user", "content": "test"},),
                    max_output_tokens=10,
                ),
            )
        ]
    finally:
        await client.aclose()

    assert [event.text for event in events if event.kind == "text_delta"] == ["one", " two"]
    assert events[-1].kind == "finish"
    assert events[-1].finish_reason == "stop"
    assert {event.model_id for event in events} == {"observed-stream-model"}


@pytest.mark.asyncio
async def test_embeddings_are_returned_in_server_index_order(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/v1/embeddings")
        return httpx.Response(
            200,
            json={
                "model": "observed-model",
                "data": [
                    {"index": 1, "embedding": [2.0]},
                    {"index": 0, "embedding": [1.0]},
                ],
                "usage": {"prompt_tokens": 2},
            },
        )

    transport, client = _transport(tmp_path, handler)
    try:
        result = await transport.embed(_resolved(), ("first", "second"))
    finally:
        await client.aclose()

    assert result.vectors == ((1.0,), (2.0,))
    assert result.model_id == "observed-model"


@pytest.mark.asyncio
async def test_peer_is_checked_before_response_body_is_accepted(tmp_path):
    checked = []

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    def reject(response, endpoint):
        checked.append((response.status_code, endpoint.host))
        raise ValueError("CONNECTED_PEER_MISMATCH")

    transport, client = _transport(tmp_path, handler, peer_verifier=reject)
    try:
        with pytest.raises(ModelTransportError, match="CONNECTED_PEER_MISMATCH"):
            await transport.complete(
                _resolved(),
                InferenceRequest(messages=({"role": "user", "content": "x"},), max_output_tokens=1),
            )
    finally:
        await client.aclose()
    assert checked == [(200, "127.0.0.1")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "body_limit", "expected"),
    ((302, 32768, "UPSTREAM_REDIRECT_REJECTED"), (500, 4, "UPSTREAM_RESPONSE_TOO_LARGE")),
)
async def test_redirects_and_oversized_error_bodies_fail_closed(tmp_path, status, body_limit, expected):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=b"abcdefgh")

    transport, client = _transport(tmp_path, handler, body_limit=body_limit)
    try:
        with pytest.raises(ModelTransportError, match=expected):
            await transport.complete(
                _resolved(),
                InferenceRequest(messages=({"role": "user", "content": "x"},), max_output_tokens=1),
            )
    finally:
        await client.aclose()


def test_transport_source_has_no_engine_name_branches() -> None:
    source = inspect.getsource(OpenAICompatibleTransport).lower()
    assert not any(name in source for name in ("freetoken", "ollama", "lemonade", "mlx"))
