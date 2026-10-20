"""Explicit transport choice preserves the canonical wire; defaults stay unchanged.

All HTTP is MockTransport. These tests establish no provider/model quality claim.
The missing request field was observed RED before productive implementation.
"""
from copy import deepcopy
from dataclasses import replace
import json

import httpx
import pytest

from proxy.services.model_wire_token_count_service import freetoken_count_payload, wire_sha256
from proxy.services.openai_compatible_transport_service import InferenceRequest, ModelTransportError
from tests.test_openai_compatible_transport_service import _resolved, _transport


SPECIFIC = {"type": "function", "function": {"name": "read_norm_card"}}
TOOLS = [{"type": "function", "function": {
    "name": "read_norm_card", "description": "Read a literal admitted reference",
    "parameters": {"type": "object", "properties": {"evidence_ref": {"type": "string"}},
                   "required": ["evidence_ref"], "additionalProperties": False},
}}]
MESSAGES = ({"role": "system", "content": "Literal system"},
            {"role": "user", "content": "Read an already chosen card: Q1.H1"})


def _request(**changes):
    return InferenceRequest(messages=MESSAGES, max_output_tokens=64, temperature=0.7,
                            tools=deepcopy(TOOLS), **changes)


def _model():
    return {"data": [{"id": "model-1", "root": "C:/fixture/model-1", "owned_by": "FreeToken", "created": 1}]}


def _stream_response():
    payload = {"model": "model-1", "choices": [{"delta": {"content": "literal"}, "finish_reason": "stop"}]}
    return httpx.Response(200, content=("data: " + json.dumps(payload) + "\n\ndata: [DONE]\n\n").encode())


@pytest.mark.asyncio
async def test_default_none_preserves_existing_openai_body_without_an_extra_wire_field(tmp_path):
    transport, client = _transport(tmp_path, lambda _: pytest.fail("body check must not send HTTP"))
    try:
        default = _request()
        explicit = _request(tool_choice=None)
        assert default.tool_choice is None and explicit.tool_choice is None
        expected = {"model": "model-1", "messages": list(MESSAGES), "max_tokens": 64,
                    "temperature": 0.7, "tools": TOOLS}
        assert transport._chat_body(_resolved(), default, stream=False) == expected
        assert transport._chat_body(_resolved(), explicit, stream=False) == expected
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("choice", ["auto", "none", "required", SPECIFIC], ids=["auto", "none", "required", "specific"])
async def test_explicit_choice_uses_identical_count_complete_and_stream_wire(tmp_path, choice):
    captured = []
    def handler(request):
        captured.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=_model())
        if request.url.path.endswith("count_tokens"):
            return httpx.Response(200, json={"input_tokens": 700})
        if json.loads(request.content).get("stream"):
            return _stream_response()
        return httpx.Response(200, json={"model": "model-1", "choices": [{"message": {"content": "literal"}, "finish_reason": "stop"}]})
    transport, client = _transport(tmp_path, handler)
    request = _request(tool_choice=deepcopy(choice))
    connection = _resolved(extension_type="freetoken")
    try:
        body = transport._chat_body(connection, request, stream=False)
        assert body["tool_choice"] == choice
        count = await transport.count_input_tokens(connection, request)
        assert count is not None and count.tokens == 700
        result = await transport.complete(connection, request)
        events = [event async for event in transport.stream(connection, request)]
        assert result.text == "literal" and any(event.text == "literal" for event in events)
        assert [item.url.path for item in captured] == ["/v1/models", "/v1/messages/count_tokens", "/v1/models",
                                                        "/v1/chat/completions", "/v1/chat/completions"]
        counted = json.loads(captured[1].content)
        completed, streamed = (json.loads(item.content) for item in captured[-2:])
        assert completed == body and completed["tool_choice"] == streamed["tool_choice"] == choice
        assert streamed == {**completed, "stream": True}
        assert counted == freetoken_count_payload(completed)
        assert count.wire_sha256 == wire_sha256(completed)
        expected_count_choice = ({"type": "tool", "name": "read_norm_card"} if isinstance(choice, dict)
                                 else {"type": "any" if choice == "required" else choice})
        assert counted["tool_choice"] == expected_count_choice
        assert request.tool_choice == choice and request.max_output_tokens == 64
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_specific_choice_is_isolated_from_mutation_of_the_callers_nested_dict(tmp_path):
    choice = deepcopy(SPECIFIC)
    request = _request(tool_choice=choice)
    choice["function"]["name"] = "caller_changed_name"
    choice["function"]["extra"] = "caller-only"
    choice["extra"] = True
    transport, client = _transport(tmp_path, lambda _: pytest.fail("body check must not send HTTP"))
    try:
        assert request.tool_choice == SPECIFIC
        assert transport._chat_body(_resolved(), request, stream=False)["tool_choice"] == SPECIFIC
    finally:
        await client.aclose()


@pytest.mark.parametrize("choice", [
    "", "AUTO", "anything", True, False, 0, [], {},
    {"type": "tool", "name": "read_norm_card"},
    {"type": "function"},
    {"function": {"name": "read_norm_card"}},
    {"type": "function", "function": {"name": ""}},
    {"type": "function", "function": {"name": 1}},
    {"type": "function", "function": {"name": "not_declared"}},
    {"type": "function", "function": {"name": " read_norm_card "}},
    {"type": "function", "function": {"name": "read_norm_card", "arguments": {}}},
    {"type": "function", "function": {"name": "read_norm_card"}, "extra": True},
])
def test_invalid_or_unknown_choice_is_rejected_when_request_is_constructed_before_http(choice):
    with pytest.raises(ValueError, match="(?i)tool_choice"):
        _request(tool_choice=choice)


def test_required_or_specific_choice_cannot_name_an_empty_tool_inventory():
    for choice in ("required", SPECIFIC):
        with pytest.raises(ValueError, match="(?i)tool_choice"):
            InferenceRequest(messages=MESSAGES, max_output_tokens=64, tool_choice=choice)
    for choice in (None, "auto", "none"):
        assert InferenceRequest(messages=MESSAGES, max_output_tokens=64, tool_choice=choice).tool_choice == choice


@pytest.mark.asyncio
@pytest.mark.parametrize("choice", ["none", "required", SPECIFIC], ids=["none", "required", "specific"])
@pytest.mark.parametrize("operation", ["count", "complete", "stream"])
async def test_nondefault_choice_on_native_ollama_fails_clearly_before_any_http(tmp_path, choice, operation):
    sent = []
    def forbidden(request):
        sent.append(request)
        pytest.fail("unsupported choice must fail before HTTP or fallback")
    transport, client = _transport(tmp_path, forbidden)
    connection = _resolved(chat_protocol="native_chat_v1", extension_type="ollama")
    request = _request(tool_choice=deepcopy(choice))
    try:
        with pytest.raises(ModelTransportError, match="TOOL_CHOICE_UNSUPPORTED_NATIVE_CHAT"):
            if operation == "count":
                await transport.count_input_tokens(connection, request)
            elif operation == "complete":
                await transport.complete(connection, request)
            else:
                [event async for event in transport.stream(connection, request)]
        assert sent == []
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["count", "complete", "stream"])
async def test_native_ollama_explicit_auto_keeps_the_default_omitted_choice(tmp_path, operation):
    bodies = []
    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        if request.url.path.endswith("/api/chat"):
            return httpx.Response(200, json={"model": "model-1", "message": {"role": "assistant", "content": "literal"},
                                             "done": True, "done_reason": "stop"})
        return _stream_response()
    transport, client = _transport(tmp_path, handler)
    connection = _resolved(chat_protocol="native_chat_v1", extension_type="ollama")
    try:
        for choice in (None, "auto"):
            request = _request(tool_choice=choice)
            if operation == "count":
                assert await transport.count_input_tokens(connection, request) is None
            elif operation == "complete":
                assert (await transport.complete(connection, request)).text == "literal"
            else:
                assert any(event.text == "literal" for event in [event async for event in transport.stream(connection, request)])
        if operation == "count":
            assert bodies == []
        else:
            assert len(bodies) == 2 and bodies[0] == bodies[1] and "tool_choice" not in bodies[0]
    finally:
        await client.aclose()
