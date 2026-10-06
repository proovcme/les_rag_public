"""The documented native Ollama protocol must round-trip through our canonical exchange."""

from dataclasses import replace
import json

import httpx
import pytest

from proxy.services.context_governor_service import NativeToolCall, NativeToolExchange, NativeToolReply
from proxy.services.openai_compatible_transport_service import InferenceRequest, ModelTransportError
from test_openai_compatible_transport_service import _resolved, _transport


def _connection():
    return replace(_resolved(chat_protocol="native_chat_v1", extension_type="ollama"), model_id="gemma4:12b")


def _event(calls=(), *, content="", thinking=None, done=False):
    message = {"role": "assistant", "content": content}
    if calls:
        message["tool_calls"] = calls
    if thinking is not None:
        message["thinking"] = thinking
    return {"model": "gemma4:12b", "message": message, "done": done, "done_reason": "stop" if done else ""}


def _response(*events):
    return httpx.Response(200, content="\n".join(json.dumps(e, ensure_ascii=False) for e in events).encode("utf-8"))


def _call(name="read_norm_card", arguments=None, **extra):
    return {**extra, "function": {"index": 0, "name": name, "arguments": arguments if arguments is not None else {"evidence_ref": "Q1.H1"}}}


def _exchange(result):
    calls = tuple(NativeToolCall(call["id"], call["function"]["name"], json.dumps(call["function"]["arguments"], ensure_ascii=False)) for call in result.tool_calls)
    return NativeToolExchange(calls, tuple(NativeToolReply(call.call_id, call.name, f"whole body {i}: Ёж") for i, call in enumerate(calls)), result.text, result.reasoning_content)


@pytest.mark.asyncio
async def test_documented_native_calls_get_application_ids_and_two_followups(tmp_path):
    wires = []
    calls = [_call(), _call(arguments={"evidence_ref": "Q1.H1"})]

    def handler(request):
        wires.append(json.loads(request.content))
        if len(wires) < 3:
            return _response(_event(calls, content="  literal response\n", thinking="private\n"), _event(done=True))
        return _response(_event(content="final literal\n", done=True))

    transport, client = _transport(tmp_path, handler)
    initial = InferenceRequest(messages=({"role": "user", "content": "Read a card"},), max_output_tokens=64)
    try:
        first = await transport.complete(_connection(), initial)
        first_ids = [call["id"] for call in first.tool_calls]
        assert len(set(first_ids)) == 2
        assert all(value.startswith("les-native-") for value in first_ids)
        assert all(call["call_id_origin"] == "application/native_protocol_without_ids" for call in first.tool_calls)
        assert [call["function"] for call in first.tool_calls] == [call["function"] for call in calls]
        assert first.text == "  literal response\n" and first.reasoning_content == "private\n"
        assert first.finish_reason == "stop"
        first_exchange = _exchange(first)
        second = await transport.complete(_connection(), replace(initial, messages=(*initial.messages, *first_exchange.as_messages())))
        second_ids = [call["id"] for call in second.tool_calls]
        assert len(set(first_ids + second_ids)) == 4
        second_exchange = _exchange(second)
        final = await transport.complete(_connection(), replace(initial, messages=(*initial.messages, *first_exchange.as_messages(), *second_exchange.as_messages())))
        assert final.text == "final literal\n"
        for wire in wires[1:]:
            for message in wire["messages"]:
                if message["role"] == "assistant":
                    assert message["content"] == "  literal response\n"
                    assert message["thinking"] == "private\n"
                    assert "reasoning_content" not in message
                    assert all(isinstance(c["function"]["arguments"], dict) for c in message["tool_calls"])
                if message["role"] == "tool":
                    assert message["tool_name"] == "read_norm_card"
                    assert message["content"] in {"whole body 0: Ёж", "whole body 1: Ёж"}
                    assert "name" not in message
        assert [m["tool_call_id"] for m in wires[-1]["messages"] if m["role"] == "tool"] == first_ids + second_ids
        assert first_exchange.as_messages()[0]["tool_calls"][0]["function"]["arguments"] == first_exchange.calls[0].arguments
        assert "tool_choice" not in wires[0]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_native_supplied_id_is_not_replaced(tmp_path):
    raw = _call(id="provider-call-1", arguments={"source_row": "Лист!R4", "quantity": 0})
    transport, client = _transport(tmp_path, lambda _: _response(_event([raw], done=True)))
    try:
        result = await transport.complete(_connection(), InferenceRequest(messages=({"role": "user", "content": "q"},), max_output_tokens=32))
    finally:
        await client.aclose()
    assert result.tool_calls[0]["id"] == "provider-call-1"
    assert result.tool_calls[0]["call_id_origin"] == "provider"
    assert result.tool_calls[0]["function"] == raw["function"]


@pytest.mark.parametrize("arguments", ["not JSON", "[]", "null", [], None, 3])
def test_native_projection_rejects_invalid_arguments_before_request(arguments):
    from proxy.services.openai_compatible_transport_service import OpenAICompatibleTransport
    call = {"id": "call1", "type": "function", "function": {"name": "read_norm_card", "arguments": arguments}}
    request = InferenceRequest(messages=({"role": "assistant", "content": "", "tool_calls": [call]},), max_output_tokens=32)
    with pytest.raises(ModelTransportError, match="UPSTREAM_TOOL_CALLS_INVALID"):
        OpenAICompatibleTransport._native_chat_body(_connection(), request)


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [None, "call", {}, {"function": {}}, _call(arguments=[]), _call(id=3), _call(id=" ")])
async def test_native_response_rejects_malformed_calls_not_silent_drop(tmp_path, raw):
    transport, client = _transport(tmp_path, lambda _: _response(_event([raw], done=True)))
    try:
        with pytest.raises(ModelTransportError, match="UPSTREAM_TOOL_CALLS_INVALID"):
            await transport.complete(_connection(), InferenceRequest(messages=({"role": "user", "content": "q"},), max_output_tokens=32))
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_native_duplicate_provider_ids_fail_visible(tmp_path):
    transport, client = _transport(tmp_path, lambda _: _response(_event([_call(id="dup"), _call(id="dup")], done=True)))
    try:
        with pytest.raises(ModelTransportError, match="UPSTREAM_TOOL_CALLS_INVALID"):
            await transport.complete(_connection(), InferenceRequest(messages=({"role": "user", "content": "q"},), max_output_tokens=32))
    finally:
        await client.aclose()


def test_native_projection_keeps_raw_canonical_args_and_validates_reply_identity():
    from proxy.services.openai_compatible_transport_service import OpenAICompatibleTransport
    literal = ' { "source_row" : "Лист!R4", "quantity": 0 } '
    exchange = NativeToolExchange((NativeToolCall("c1", "read_source", literal),), (NativeToolReply("c1", "read_source", "Полный исходник"),), "literal\n", "private")
    messages = exchange.as_messages()
    wire = OpenAICompatibleTransport._native_chat_body(_connection(), InferenceRequest(messages=messages, max_output_tokens=32))
    assert messages[0]["tool_calls"][0]["function"]["arguments"] == literal
    assert wire["messages"][0]["tool_calls"][0]["function"]["arguments"] == json.loads(literal)
    assert wire["messages"][1] == {"role": "tool", "tool_call_id": "c1", "tool_name": "read_source", "content": "Полный исходник"}
    bad = [messages[0], {**messages[1], "name": "another_tool"}]
    with pytest.raises(ModelTransportError, match="NATIVE_TOOL_REPLY_INVALID"):
        OpenAICompatibleTransport._native_chat_body(_connection(), InferenceRequest(messages=bad, max_output_tokens=32))


@pytest.mark.asyncio
async def test_native_thinking_literal_is_separate_and_not_public_answer(tmp_path):
    transport, client = _transport(tmp_path, lambda _: _response(_event(content=" exact text\n", thinking="private "), _event(thinking="second\n", done=True)))
    try:
        result = await transport.complete(_connection(), InferenceRequest(messages=({"role": "user", "content": "q"},), max_output_tokens=32))
    finally:
        await client.aclose()
    assert result.text == " exact text\n"
    assert result.reasoning_content == "private second\n"
    assert "private" not in repr(result)


def test_native_thinking_survives_null_canonical_alias_and_conflict_is_visible():
    from proxy.services.openai_compatible_transport_service import OpenAICompatibleTransport
    message = {"role": "assistant", "content": "literal answer", "reasoning_content": None,
               "thinking": "whole native private state\n"}
    request = InferenceRequest(messages=(message,), max_output_tokens=32)
    wire = OpenAICompatibleTransport._native_chat_body(_connection(), request)
    assert wire["messages"] == [{"role": "assistant", "content": "literal answer", "thinking": message["thinking"]}]
    assert request.messages[0] == message
    conflicted = {**message, "reasoning_content": "a different private state"}
    with pytest.raises(ModelTransportError, match="UPSTREAM_REASONING_CONTENT_INVALID"):
        OpenAICompatibleTransport._native_chat_body(_connection(), replace(request, messages=(conflicted,)))
