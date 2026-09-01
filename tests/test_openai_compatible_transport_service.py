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
