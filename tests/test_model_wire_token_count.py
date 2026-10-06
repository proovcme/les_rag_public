from __future__ import annotations

from copy import deepcopy
import asyncio
from dataclasses import replace
import json

import httpx
import pytest

from proxy.services.model_connection_contracts import ConnectionLocality
from proxy.services.model_wire_token_count_service import (
    UnsupportedTokenCountWire, freetoken_count_payload, normalize_freetoken_count_wire,
)
from proxy.services.openai_compatible_transport_service import InferenceRequest
from test_openai_compatible_transport_service import _resolved, _transport


TOOLS = [{"type": "function", "function": {
    "name": "read_source", "description": "Read exact source", "parameters": {
        "type": "object", "properties": {"evidence_ref": {"type": "string"}}, "required": ["evidence_ref"],
    },
}}]
MESSAGES = [
    {"role": "system", "content": "Preserve all source evidence."},
    {"role": "user", "content": "ВОР: 3,5 м²; C:\\проект\\'файл'; источник целиком."},
    {"role": "assistant", "content": "", "tool_calls": [{
        "id": "call_A", "type": "function", "function": {
            "name": "read_source", "arguments": '{ "evidence_ref" : "Q1.H1", "literal": "люк" }',
        },
    }]},
    {"role": "tool", "tool_call_id": "call_A", "name": "read_source", "content": "Полная карточка\nprice=12,67"},
    {"role": "assistant", "content": "Need another exact source.", "tool_calls": [{
        "id": "call_B", "type": "function", "function": {"name": "read_source", "arguments": '{"evidence_ref":"Q2.H1"}'},
    }]},
    {"role": "tool", "tool_call_id": "call_B", "name": "read_source", "content": '{"literal":"Цена 18 200,00 ₽"}'},
]


def _request(messages=MESSAGES, **changes):
    return InferenceRequest(messages=messages, tools=TOOLS, max_output_tokens=16384, **changes)


def _model(model_id="model-1", root="C:/models/the-active-model"):
    return {"data": [{"id": model_id, "root": root, "owned_by": "FreeToken", "created": 19}]}


def _raw_body():
    return {"model": "model-1", "messages": deepcopy(MESSAGES), "tools": deepcopy(TOOLS),
            "max_tokens": 16384, "chat_template_kwargs": {"enable_thinking": False}}


def test_two_native_exchanges_preserve_literal_evidence_ids_arguments_and_schema():
    original = _raw_body()
    body = normalize_freetoken_count_wire(original)
    payload = freetoken_count_payload(body)
    assert original == _raw_body()  # Provider projection never rewrites stored protocol state.
    assert payload["model"] == original["model"]
    assert payload["system"] == MESSAGES[0]["content"]
    assert payload["messages"][0]["content"] == MESSAGES[1]["content"]
    first_call = payload["messages"][1]["content"][0]
    assert first_call == {"type": "tool_use", "id": "call_A", "name": "read_source",
                          "input": json.loads(MESSAGES[2]["tool_calls"][0]["function"]["arguments"])}
    assert payload["messages"][2]["content"] == [{"type": "tool_result", "tool_use_id": "call_A", "content": MESSAGES[3]["content"]}]
    assert payload["messages"][3]["content"][0] == {"type": "text", "text": MESSAGES[4]["content"]}
    assert payload["messages"][3]["content"][1]["id"] == "call_B"
    assert payload["messages"][4]["content"][0]["content"] == MESSAGES[5]["content"]
    assert payload["tools"] == [{"name": "read_source", "description": "Read exact source", "input_schema": TOOLS[0]["function"]["parameters"]}]
    assert body["chat_template_kwargs"] == {"enable_thinking": False, "thinking_mode": "disabled"}
    assert "name" not in body["messages"][3] and "content" not in body["messages"][2]
    assert body["messages"][3]["tool_call_id"] == MESSAGES[3]["tool_call_id"]


@pytest.mark.parametrize("mutation,reason", [
    (lambda b: b.update(response_format={"type": "json_schema"}), "unsupported_prompt_fields"),
    (lambda b: b["chat_template_kwargs"].update(unknown=True), "unsupported_template_kwargs"),
    (lambda b: b["messages"][1].update(content=[{"type": "image_url", "image_url": "private"}]), "unsupported_user_message"),
    (lambda b: b["messages"][2].update(reasoning_content="private thought"), "unsupported_assistant_message"),
    (lambda b: b["messages"][3].update(tool_call_id="wrong"), "unmatched_tool_reply"),
    (lambda b: b["messages"][2]["tool_calls"][0]["function"].update(arguments="[]"), "tool_arguments_object_required"),
    (lambda b: b["messages"][2]["tool_calls"][0]["function"].update(arguments="{broken"), "invalid_tool_arguments"),
    (lambda b: b["messages"][2]["tool_calls"][0]["function"].update(arguments='{"n":NaN}'), "unsupported_json_value"),
    (lambda b: b["tools"][0]["function"].update(strict=True), "unsupported_tool_schema"),
    (lambda b: b["messages"].pop(), "incomplete_tool_exchange"),
])
def test_unsupported_wire_is_rejected_before_silent_drop(mutation, reason):
    body = normalize_freetoken_count_wire(_raw_body())
    mutation(body)
    with pytest.raises(UnsupportedTokenCountWire, match=reason):
        freetoken_count_payload(body)


@pytest.mark.asyncio
async def test_count_uses_bound_model_credentials_peer_checks_and_no_generation(tmp_path):
    captured, peers = [], []
    def handler(request):
        captured.append(request)
        return httpx.Response(200, json=_model() if request.method == "GET" else {"input_tokens": 34123})
    transport, client = _transport(tmp_path, handler, environ={"OPENAI_API_KEY": "fixture-secret"},
                                   peer_verifier=lambda response, endpoint: peers.append((response.request.url, endpoint)))
    connection = _resolved(extension_type="freetoken", secret_ref="env:OPENAI_API_KEY")
    request = _request()
    try:
        result = await transport.count_input_tokens(connection, request)
        assert result is not None and result.tokens == 34123
        assert result.model_id == connection.model_id and result.connection_revision_id == connection.revision_id
        assert len(result.wire_sha256) == 64 and len(result.model_identity_sha256) == 64
        assert [r.url.path for r in captured] == ["/v1/models", "/v1/messages/count_tokens", "/v1/models"]
        assert len(peers) == 3 and all(endpoint is connection.endpoint for _, endpoint in peers)
        assert all(r.headers["Authorization"] == "Bearer fixture-secret" for r in captured)
        payload = json.loads(captured[1].content)
        assert payload == freetoken_count_payload(transport._chat_body(connection, request, stream=False))
        assert "max_tokens" not in payload and "stream" not in payload
        snapshot = json.dumps(transport.token_count_snapshot(), ensure_ascii=False)
        assert "fixture-secret" not in snapshot and MESSAGES[1]["content"] not in snapshot
        assert transport.token_count_snapshot()["status"] == "counted"
        assert request.messages[3]["name"] == "read_source"
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("reasoning", [False, True])
async def test_count_and_actual_freetoken_wire_use_same_thinking_broadcast(tmp_path, reasoning):
    bodies = []
    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json=_model())
        bodies.append((request.url.path, json.loads(request.content)))
        if request.url.path.endswith("count_tokens"):
            return httpx.Response(200, json={"input_tokens": 20})
        return httpx.Response(200, json={"choices": [{"message": {"content": "done"}}]})
    transport, client = _transport(tmp_path, handler)
    connection = _resolved(extension_type="freetoken")
    request = _request(reasoning_enabled=reasoning)
    try:
        await transport.count_input_tokens(connection, request)
        await transport.complete(connection, request)
        counted, sent = bodies[0][1], bodies[1][1]
        assert counted == freetoken_count_payload(sent)
        assert sent["chat_template_kwargs"] == {"enable_thinking": reasoning, "thinking_mode": "enabled" if reasoning else "disabled"}
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("connection_change", [{"extension_type": "ollama"}, {"locality": ConnectionLocality.REMOTE}])
async def test_unsupported_connection_does_not_send_counter_http(tmp_path, connection_change):
    transport, client = _transport(tmp_path, lambda _: pytest.fail("unsupported counter must not send HTTP"))
    try:
        assert await transport.count_input_tokens(replace(_resolved(extension_type="freetoken"), **connection_change), _request()) is None
        assert transport.token_count_snapshot()["reason"] == "local_token_counter_required"
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [None, {}, {"input_tokens": 0}, {"input_tokens": True}, {"input_tokens": -1}, {"input_tokens": "20"}])
async def test_missing_invalid_counter_returns_visible_conservative_fallback(tmp_path, response):
    captured = []
    def handler(request):
        captured.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=_model())
        return httpx.Response(404 if response is None else 200, json=response or {})
    transport, client = _transport(tmp_path, handler)
    try:
        assert await transport.count_input_tokens(_resolved(extension_type="freetoken"), _request()) is None
        assert transport.token_count_snapshot()["status"] == "fallback"
        assert all(not r.url.path.endswith("completions") for r in captured)
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("change_before", [False, True])
async def test_loaded_model_mismatch_or_change_never_admits_count(tmp_path, change_before):
    models_read = 0
    def handler(request):
        nonlocal models_read
        if request.method == "GET":
            models_read += 1
            return httpx.Response(200, json=_model("different" if change_before else "model-1", root="changed" if models_read == 2 else "initial"))
        return httpx.Response(200, json={"input_tokens": 20})
    transport, client = _transport(tmp_path, handler)
    try:
        assert await transport.count_input_tokens(_resolved(extension_type="freetoken"), _request()) is None
        assert "TOKEN_COUNT_MODEL" in transport.token_count_snapshot()["reason"]
        assert models_read == (1 if change_before else 2)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_freetoken_response_timestamp_does_not_claim_loaded_model_changed(tmp_path):
    models_read, requests = 0, []

    def handler(request):
        nonlocal models_read
        requests.append(request)
        if request.method == "GET":
            models_read += 1
            metadata = _model()
            metadata["data"][0]["created"] = 1791288290 + models_read
            return httpx.Response(200, json=metadata)
        return httpx.Response(200, json={"input_tokens": 34123})

    transport, client = _transport(tmp_path, handler)
    try:
        result = await transport.count_input_tokens(_resolved(extension_type="freetoken"), _request())
        assert result is not None and result.tokens == 34123
        assert transport.token_count_snapshot()["status"] == "counted"
        assert [request.url.path for request in requests] == [
            "/v1/models", "/v1/messages/count_tokens", "/v1/models"]
        assert json.loads(requests[1].content) == freetoken_count_payload(
            transport._chat_body(_resolved(extension_type="freetoken"), _request(), stream=False))
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("id", "other"), ("root", "another/model"),
                                        ("owned_by", "another-provider")])
async def test_stable_identity_change_still_rejects_count_despite_response_timestamp(tmp_path, field, value):
    models_read = 0

    def handler(request):
        nonlocal models_read
        if request.method == "GET":
            models_read += 1
            metadata = _model()
            metadata["data"][0]["created"] = models_read
            if models_read == 2:
                metadata["data"][0][field] = value
            return httpx.Response(200, json=metadata)
        return httpx.Response(200, json={"input_tokens": 34123})

    transport, client = _transport(tmp_path, handler)
    try:
        assert await transport.count_input_tokens(_resolved(extension_type="freetoken"), _request()) is None
        assert transport.token_count_snapshot()["status"] == "fallback"
        assert "TOKEN_COUNT_MODEL" in transport.token_count_snapshot()["reason"]
        assert models_read == 2
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["peer", "redirect", "too_large"])
async def test_count_reuses_transport_security_and_body_limit(tmp_path, failure):
    def handler(request):
        if failure == "redirect":
            return httpx.Response(302, headers={"Location": "https://outside.invalid"})
        if failure == "too_large":
            return httpx.Response(200, content=b"x" * 400)
        return httpx.Response(200, json=_model())
    def peer(response, endpoint):
        if failure == "peer":
            raise ValueError("UPSTREAM_PEER_REJECTED")
    transport, client = _transport(tmp_path, handler, body_limit=256, peer_verifier=peer)
    try:
        assert await transport.count_input_tokens(_resolved(extension_type="freetoken"), _request()) is None
        assert transport.token_count_snapshot()["status"] == "fallback"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_other_provider_wire_is_unchanged(tmp_path):
    transport, client = _transport(tmp_path, lambda _: pytest.fail("no HTTP"))
    connection = _resolved(extension_type="ollama")
    body = transport._chat_body(connection, _request(), stream=False)
    assert body["messages"][3]["name"] == "read_source"
    assert body["messages"][2]["content"] == ""
    assert "chat_template_kwargs" not in body
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("metadata", [{"data": []}, {"data": "not-a-list"}, {"data": ["not-a-mapping"]}, [], None])
async def test_malformed_model_metadata_falls_back_without_count_or_generation(tmp_path, metadata):
    captured = []
    def handler(request):
        captured.append(request)
        return httpx.Response(200, json=metadata)
    transport, client = _transport(tmp_path, handler)
    try:
        assert await transport.count_input_tokens(_resolved(extension_type="freetoken"), _request()) is None
        assert [r.url.path for r in captured] == ["/v1/models"]
        assert transport.token_count_snapshot()["reason"] == "TOKEN_COUNT_MODEL_METADATA_INVALID"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_counter_uses_bounded_request_timeout_even_with_long_chat_timeout(tmp_path):
    timeouts = []
    def handler(request):
        timeouts.append(request.extensions["timeout"])
        return httpx.Response(200, json=_model() if request.method == "GET" else {"input_tokens": 20})
    transport, client = _transport(tmp_path, handler)
    transport.timeout = 900
    try:
        assert await transport.count_input_tokens(_resolved(extension_type="freetoken"), _request()) is not None
        assert all(set(value.values()) == {15.0} for value in timeouts)
        assert transport.token_count_snapshot()["request_timeout_seconds"] == 15.0
        assert transport.token_count_snapshot()["operation_deadline_seconds"] == 15.0
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_counter_total_deadline_does_not_inherit_long_chat_wait(tmp_path):
    async def handler(request):
        await asyncio.Event().wait()
        pytest.fail("unreachable stalled metadata request")
    transport, client = _transport(tmp_path, handler)
    transport.timeout = 0.01
    try:
        async with asyncio.timeout(0.5):
            assert await transport.count_input_tokens(_resolved(extension_type="freetoken"), _request()) is None
        assert transport.token_count_snapshot()["reason"] == "TOKEN_COUNT_DEADLINE"
    finally:
        await client.aclose()
