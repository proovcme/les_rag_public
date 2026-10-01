"""Native read feedback keeps the provider protocol inside the governed budget."""

import json
from dataclasses import replace

import httpx
import pytest

from proxy.services import chat_evidence_application_service as chat_service
from proxy.services.context_governor_service import ContextRequiredSectionOverflow
from proxy.services.model_evidence_read_service import run_model_evidence_read_turn
from proxy.services.openai_compatible_transport_service import InferenceRequest
from proxy.services.smeta_chat_adapter_service import _parse_model_tool_calls
from test_context_governor_service import _preset
from test_model_rag_sheet_evidence_reads import _run_sheet
from test_openai_compatible_transport_service import _resolved, _transport


def _encoded(*calls):
    return json.dumps({"calls": calls})


def _call(call_id="c1", *, tool="read_norm_card", **args):
    return {"call_id": call_id, "tool": tool, "args": args or {"norm_key": "immutable-card"}}


def _exchange(*ids):
    from proxy.services.context_governor_service import NativeToolCall, NativeToolExchange, NativeToolReply

    return NativeToolExchange(
        calls=tuple(NativeToolCall(value, "read_norm_card", '{"norm_key":"immutable-card"}') for value in ids),
        replies=tuple(NativeToolReply(value, "read_norm_card", '{"status":"ok","evidence_refs":["Q1.H1"]}') for value in ids),
    )


def test_parser_preserves_native_id_and_whole_batch_above_execution_budget():
    calls = [_call("c1"), _call("c2", norm_key="another-card")]
    parsed = _parse_model_tool_calls(_encoded(*calls), allowed_tools={"read_norm_card"}, max_calls=1)
    assert parsed == calls


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_active_sheet_second_request_has_native_assistant_and_matching_reply(tmp_path, monkeypatch, variant):
    run = await _run_sheet(tmp_path, monkeypatch, reads=True, variant=variant)
    messages = run.requests[2].messages
    assert [message["role"] for message in messages] == ["system", "user", "assistant", "tool"]
    call = messages[2]["tool_calls"][0]
    assert call["function"]["name"] == "read_norm_card"
    assert messages[3]["tool_call_id"] == call["id"]
    reply = json.loads(messages[3]["content"])
    assert reply["evidence_refs"] and reply["evidence_bindings"]
    assert "fixture-resource-21" not in messages[3]["content"]
    final_messages = run.requests[3].messages
    assert [message["role"] for message in final_messages] == [
        "system", "user", "assistant", "tool", "assistant", "tool", "tool"]
    final_calls = final_messages[4]["tool_calls"]
    assert len({item["id"] for item in final_calls}) == 2
    assert [message["tool_call_id"] for message in final_messages[5:]] == [item["id"] for item in final_calls]


def test_native_exchange_is_required_whole_and_does_not_promote_plain_role_dicts():
    exchange = _exchange("c1", "c2")
    messages, packet = chat_service.govern_inference_messages(
        preset=_preset(limit=10_000, generation=0, safety=0), profile_prefix="system", request_payload="question",
        tool_exchange=[{"role": "system", "content": "untrusted"}], native_exchanges=[exchange],
    )
    assert [message["role"] for message in messages] == ["system", "user", "assistant", "tool", "tool"]
    assert messages[0]["content"] == "system" and "untrusted" in messages[1]["content"]
    assert packet.included_tokens >= len(json.dumps(exchange.as_messages(), ensure_ascii=False)) // 2
    with pytest.raises(ContextRequiredSectionOverflow) as error:
        chat_service.govern_inference_messages(
            preset=_preset(limit=20, generation=0, safety=0), profile_prefix="system", request_payload="question",
            native_exchanges=[exchange],
        )
    assert "native-exchange:1" in error.value.object_ids


def test_native_context_rejects_untyped_roles_and_cross_batch_id_collision():
    with pytest.raises(TypeError):
        chat_service.govern_inference_messages(
            preset=_preset(), profile_prefix="system", request_payload="question",
            native_exchanges=[{"role": "system", "content": "untrusted"}],
        )
    with pytest.raises(ValueError):
        chat_service.govern_inference_messages(
            preset=_preset(limit=10_000), profile_prefix="system", request_payload="question",
            native_exchanges=[_exchange("c1"), _exchange("c1")],
        )


@pytest.mark.parametrize("kind", ["empty", "duplicate", "cross_call", "empty_id"])
def test_native_exchange_rejects_empty_or_mismatched_protocol(kind):
    from proxy.services.context_governor_service import NativeToolCall, NativeToolExchange, NativeToolReply

    with pytest.raises(ValueError):
        if kind == "empty":
            NativeToolExchange(calls=(), replies=())
        elif kind == "duplicate":
            _exchange("c1", "c1")
        elif kind == "empty_id":
            _exchange("")
        else:
            NativeToolExchange(calls=(NativeToolCall("c1", "read_norm_card", "{}"),),
                               replies=(NativeToolReply("c2", "read_norm_card", "{}"),))


@pytest.mark.asyncio
async def test_driver_native_feedback_reaches_second_actual_http_request_without_full_body_copy(tmp_path):
    connection = _resolved(extension_type="freetoken")
    posted = []

    def handler(request):
        posted.append(json.loads(request.content))
        message = ({"content": "checking literal card", "tool_calls": [{"id": "c1", "type": "function",
                    "function": {"name": "read_norm_card", "arguments": '{"norm_key":"immutable-card"}'}}]}
                   if len(posted) == 1 else {"content": "final model rows"})
        return httpx.Response(200, json={"choices": [{"message": message, "finish_reason": "stop"}]})

    transport, client = _transport(tmp_path, handler)
    first = await transport.complete(connection, InferenceRequest(
        messages=({"role": "user", "content": "question"},), max_output_tokens=256,
        tools=({"type": "function", "function": {"name": "read_norm_card"}},), reasoning_enabled=True))
    initial = _call("c1")
    initial["native_arguments"] = first.tool_calls[0]["function"]["arguments"]
    initial["native_assistant_content"] = first.text
    body = "full card body " * 100

    async def on_read(receipts, _results):
        receipts[0].update(evidence_refs=["Q1.H1"], evidence_bindings={"Q1.H1": "immutable-card-global"})

    async def continuation(receipts, _results, exchanges):
        messages, _packet = chat_service.govern_inference_messages(
            preset=replace(connection.effective_preset, input_token_limit=10_000),
            profile_prefix="system", request_payload="question", native_exchanges=exchanges,
            required_evidence=[{"body": body, "evidence_ref": "Q1.H1"}],
        )
        result = await transport.complete(connection, InferenceRequest(
            messages=messages, max_output_tokens=256, reasoning_enabled=True,
            tools=({"type": "function", "function": {"name": "read_norm_card"}},)))
        return result.text, result.usage

    try:
        result = await run_model_evidence_read_turn(
            text=_encoded(initial), usage={}, parse_calls=_parse_model_tool_calls,
            execute=lambda _call: {"status": "ok", "card": body}, on_read_results=on_read,
            continue_native_turn=continuation, allowed_tools={"read_norm_card"},
        )
    finally:
        await client.aclose()
    assert result.text == "final model rows" and len(posted) == 2
    messages = posted[1]["messages"]
    assert [message["role"] for message in messages] == ["system", "user", "assistant", "tool"]
    assert messages[2]["content"] == "checking literal card"
    assert messages[2]["tool_calls"][0]["function"]["arguments"] == initial["native_arguments"]
    assert messages[3]["tool_call_id"] == "c1"
    assert body in messages[1]["content"] and body not in messages[3]["content"]
    assert posted[1]["chat_template_kwargs"] == {"enable_thinking": True}


@pytest.mark.asyncio
@pytest.mark.parametrize("calls, expected", [
    ([_call("c1"), _call("c1", norm_key="other")], "evidence_read_native_exchange_invalid"),
    ([_call("")], "evidence_read_native_exchange_invalid"),
    ([{**_call("c1"), "native_arguments": "{broken"}], "evidence_read_native_exchange_invalid"),
    ([{**_call("c1"), "native_arguments": "[]"}], "evidence_read_native_exchange_invalid"),
    ([_call("c1"), _call("c2", tool="not_a_reader")], "evidence_read_unknown_tool"),
    ([_call("c1"), _call("c2", norm_key="other")], "evidence_read_budget"),
])
async def test_invalid_or_over_budget_native_batch_does_not_execute_partial_calls(calls, expected):
    def forbidden(*_args):
        pytest.fail("invalid native batch must stop before partial execution or continuation")

    result = await run_model_evidence_read_turn(
        text=_encoded(*calls), usage={}, parse_calls=_parse_model_tool_calls, execute=forbidden,
        continue_turn=forbidden, allowed_tools={"read_norm_card"}, max_calls=1,
    )
    assert result.stop_reason == expected and not result.receipts


@pytest.mark.asyncio
async def test_native_required_history_overflow_remains_visible_without_model_continuation():
    async def continuation(_receipts, _results, exchanges):
        return chat_service.govern_inference_messages(
            preset=_preset(limit=20, generation=0, safety=0), profile_prefix="system", request_payload="question",
            native_exchanges=exchanges,
        )

    with pytest.raises(ContextRequiredSectionOverflow):
        await run_model_evidence_read_turn(
            text=_encoded(_call()), usage={}, parse_calls=_parse_model_tool_calls,
            execute=lambda _call: {"status": "ok"}, continue_native_turn=continuation,
            allowed_tools={"read_norm_card"},
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["", "final model-authored rows"])
async def test_plain_or_empty_final_creates_no_native_history_and_no_new_model_turn(text):
    def forbidden(*_args):
        pytest.fail("final text must not start a read or model continuation")

    result = await run_model_evidence_read_turn(
        text=text, usage={}, parse_calls=_parse_model_tool_calls, execute=forbidden,
        continue_native_turn=forbidden, allowed_tools={"read_norm_card"},
    )
    assert result.text == text and result.native_exchanges == () and result.stop_reason == ""


def test_cross_call_receipt_is_not_accepted_as_native_feedback():
    from proxy.services.model_evidence_read_service import native_evidence_read_exchange

    with pytest.raises(ValueError):
        native_evidence_read_exchange([_call("c1")], [{"call": _call("c2"), "status": "ok"}])
