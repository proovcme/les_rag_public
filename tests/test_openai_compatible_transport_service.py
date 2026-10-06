from __future__ import annotations

from datetime import datetime, timedelta, timezone
import inspect
import json
from dataclasses import replace

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
    CHAT_RESPONSE_BODY_LIMIT,
    InferenceRequest,
    ModelTransportError,
    OpenAICompatibleTransport,
)


NOW = datetime(2026, 8, 28, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_cloud_budget_stop_does_not_use_model_fallback(tmp_path, monkeypatch):
    from proxy.services.canonical_route_service import BoundModelChatRunner, CanonicalRouteMode
    from proxy.services.openai_compatible_transport_service import CloudBudgetStop
    monkeypatch.setenv("LES_CLOUD_TURN_TOKEN_BUDGET", "1")
    remote = replace(_resolved(max_output_field="max_completion_tokens"), locality=ConnectionLocality.REMOTE)
    class Resolver:
        def resolve(self, role):
            return remote
        def resolve_fallback(self, revision):
            pytest.fail("budget stop must not spend through another model")
    def handler(request):
        pytest.fail("budget denied before HTTP")
    transport, client = _transport(tmp_path, handler)
    try:
        with pytest.raises(CloudBudgetStop):
            await BoundModelChatRunner(resolver=Resolver(), transport=transport).complete(
                mode=CanonicalRouteMode.ACTIVE,
                request=InferenceRequest(messages=({"role": "user", "content": "test"},), max_output_tokens=32),
                legacy_complete=lambda _: pytest.fail("no legacy fallback"))
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_cloud_budget_counts_every_wire_attempt_and_stops_before_send(tmp_path, monkeypatch):
    from proxy.services.openai_compatible_transport_service import CloudBudgetStop
    monkeypatch.setenv("LES_CLOUD_TURN_TOKEN_BUDGET", "4000")
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}],
                                        "usage": {"prompt_tokens": 2800, "completion_tokens": 100}})
    transport, client = _transport(tmp_path, handler)
    remote = replace(_resolved(max_output_field="max_completion_tokens"), locality=ConnectionLocality.REMOTE)
    request = InferenceRequest(messages=({"role": "user", "content": "Кабель"},), max_output_tokens=512)
    try:
        await transport.complete(remote, request)
        with pytest.raises(CloudBudgetStop, match="CLOUD_TURN_TOKEN_BUDGET"):
            await transport.complete(remote, request)
        assert len(requests) == 1
        assert transport.cloud_budget_snapshot()["accounted_tokens"] == 2900
        snapshot = transport.cloud_budget_snapshot()
        assert snapshot["reported_tokens"] == 2900
        assert snapshot["unsettled_reservation_tokens"] == 0
        assert snapshot["last_attempt"]["number"] == 2
        assert snapshot["last_attempt"]["sent"] is False
        assert snapshot["last_attempt"]["reservation_tokens"] > snapshot["remaining_tokens"]
        assert "Кабель" not in json.dumps(snapshot, ensure_ascii=False)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_cloud_preflight_packs_optional_context_then_sends_same_wire(tmp_path, monkeypatch):
    from proxy.services.context_governor_service import ContextCandidate, ContextGovernor, ContextKind, ContextObject
    monkeypatch.setenv("LES_CLOUD_TURN_TOKEN_BUDGET", "5000")
    sent = []
    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}],
                                        "usage": {"prompt_tokens": 400, "completion_tokens": 12}})
    transport, client = _transport(tmp_path, handler)
    remote = replace(_resolved(max_output_field="max_completion_tokens"), locality=ConnectionLocality.REMOTE)
    required = ContextCandidate(ContextKind.REQUEST, (ContextObject("request", "Кабель 'тест' C:\\пример"),), required=True)
    optional = ContextCandidate(ContextKind.EVIDENCE, tuple(ContextObject(f"card:{i}", "Текст карточки " * 100) for i in range(4)))
    def request(messages):
        return InferenceRequest(messages=messages, max_output_tokens=128)
    try:
        governor = ContextGovernor(replace(remote.effective_preset, input_token_limit=100000))
        packet = governor.pack([required, optional],
            admit_messages=lambda messages: transport.cloud_request_fits(remote, request(messages)))
        assert packet.omissions and packet.omissions[0].reason == "wire_budget_exhausted"
        assert transport.cloud_budget_snapshot()["requests_sent"] == 0
        assert transport.cloud_budget_snapshot()["accounted_tokens"] == 0
        await transport.complete(remote, request(packet.as_messages()))
        assert len(sent) == 1 and sent[0]["messages"] == packet.as_messages()
        assert transport.cloud_budget_snapshot()["reported_tokens"] == 412
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_cloud_budget_keeps_reservation_without_usage_and_for_retry(tmp_path, monkeypatch):
    from proxy.services.openai_compatible_transport_service import CloudBudgetStop
    monkeypatch.setenv("LES_CLOUD_TURN_TOKEN_BUDGET", "2500")
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(502, content=b"System message must be at the beginning")
    transport, client = _transport(tmp_path, handler)
    remote = replace(_resolved(max_output_field="max_completion_tokens"), locality=ConnectionLocality.REMOTE)
    request = InferenceRequest(messages=({"role": "system", "content": "test"}, {"role": "user", "content": "test"}), max_output_tokens=512)
    try:
        with pytest.raises(CloudBudgetStop):
            await transport.complete(remote, request)
        assert len(requests) == 1
        assert transport.cloud_budget_snapshot()["requests_sent"] == 1
        snapshot = transport.cloud_budget_snapshot()
        assert snapshot["reported_tokens"] == 0
        assert snapshot["unsettled_reservation_tokens"] == snapshot["accounted_tokens"] > 0
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_cloud_budget_requires_total_output_cap_but_does_not_block_local(tmp_path, monkeypatch):
    from proxy.services.openai_compatible_transport_service import CloudBudgetStop
    monkeypatch.setenv("LES_CLOUD_TURN_TOKEN_BUDGET", "2000")
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    transport, client = _transport(tmp_path, handler)
    request = InferenceRequest(messages=({"role": "user", "content": "test"},), max_output_tokens=512)
    try:
        with pytest.raises(CloudBudgetStop, match="TOTAL_OUTPUT_CAP_REQUIRED"):
            await transport.complete(replace(_resolved(), locality=ConnectionLocality.REMOTE), request)
        await transport.complete(_resolved(), request)
        assert len(requests) == 1
        assert transport.cloud_budget_snapshot()["accounted_tokens"] == 0
    finally:
        await client.aclose()


def _resolved(
    *,
    display_name: str = "Connection",
    secret_ref: str | None = None,
    max_output_field: str = "max_tokens",
    chat_protocol: str | None = None,
    extension_type: str | None = None,
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
        extension_type=extension_type,
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
    assert "chat_template_kwargs" not in json.loads(requests[0].content)


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
    assert result.text == ""
    assert result.reasoning_content == "checked"
    assert "checked" not in repr(result)
    assert result.tool_calls[0]["function"]["name"] == "read_file"
    assert result.finish_reason == "tool_calls"


@pytest.mark.asyncio
@pytest.mark.parametrize("reasoning", [None, "", "  private protocol state\n", {"invalid": "object"}])
async def test_complete_reasoning_is_separate_literal_protocol_state(tmp_path, reasoning):
    def handler(_request):
        return httpx.Response(200, json={"choices": [{"message": {
            "content": "Visible answer", "reasoning_content": reasoning}}]})
    transport, client = _transport(tmp_path, handler)
    try:
        request = InferenceRequest(messages=({"role": "user", "content": "question"},), max_output_tokens=256)
        if isinstance(reasoning, dict):
            with pytest.raises(ModelTransportError, match="UPSTREAM_REASONING_CONTENT_INVALID"):
                await transport.complete(_resolved(), request)
        else:
            result = await transport.complete(_resolved(), request)
            assert result.reasoning_content == reasoning
            assert result.text == "Visible answer"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_preserved_reasoning_cannot_bypass_cloud_wire_budget(tmp_path, monkeypatch):
    from proxy.services.openai_compatible_transport_service import CloudBudgetStop
    monkeypatch.setenv("LES_CLOUD_TURN_TOKEN_BUDGET", "2500")
    transport, client = _transport(tmp_path, lambda _: pytest.fail("must stop before HTTP"))
    remote = replace(_resolved(max_output_field="max_completion_tokens"), locality=ConnectionLocality.REMOTE)
    assistant = {"role": "assistant", "content": "", "reasoning_content": "private" * 600,
                 "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "read", "arguments": "{}"}}]}
    request = InferenceRequest(messages=({"role": "user", "content": "question"}, assistant,
        {"role": "tool", "tool_call_id": "c1", "content": "ok"}), max_output_tokens=32)
    try:
        assert not transport.cloud_request_fits(remote, request)
        with pytest.raises(CloudBudgetStop):
            await transport.complete(remote, request)
        snapshot = transport.cloud_budget_snapshot()
        assert snapshot["requests_sent"] == 0
        assert "private" not in json.dumps(snapshot)
    finally:
        await client.aclose()


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

    assert [event.text for event in events if event.kind == "text_delta"] == [" two"]
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


@pytest.mark.asyncio
async def test_local_extension_complete_disables_thinking(tmp_path):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            },
        )

    transport, client = _transport(tmp_path, handler)
    try:
        await transport.complete(
            _resolved(extension_type="freetoken"),
            InferenceRequest(
                messages=({"role": "user", "content": "test"},),
                max_output_tokens=64,
            ),
        )
    finally:
        await client.aclose()

    assert captured["body"]["chat_template_kwargs"] == {"enable_thinking": False, "thinking_mode": "disabled"}


@pytest.mark.asyncio
async def test_non_local_extension_complete_does_not_add_thinking_kwargs(tmp_path):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            },
        )

    transport, client = _transport(tmp_path, handler)
    try:
        await transport.complete(
            _resolved(extension_type="ollama"),
            InferenceRequest(
                messages=({"role": "user", "content": "test"},),
                max_output_tokens=64,
            ),
        )
    finally:
        await client.aclose()

    assert "chat_template_kwargs" not in captured["body"]


def test_chat_complete_body_limit_is_wider_than_probe_default() -> None:
    assert CHAT_RESPONSE_BODY_LIMIT == 512 * 1024
    default_limit = inspect.signature(OpenAICompatibleTransport.__init__).parameters[
        "response_body_limit"
    ].default
    assert default_limit == 32_768
    assert CHAT_RESPONSE_BODY_LIMIT > default_limit


def test_transport_source_has_no_engine_name_branches() -> None:
    source = inspect.getsource(OpenAICompatibleTransport).lower()
    assert not any(name in source for name in ("freetoken", "ollama", "lemonade", "mlx"))
