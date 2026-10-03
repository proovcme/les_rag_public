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


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_active_native_callbacks_do_not_repeat_tool_receipts_in_user_evidence(tmp_path, monkeypatch, variant):
    run = await _run_sheet(tmp_path, monkeypatch, reads=True, variant=variant)
    for request in run.requests[2:]:
        user = next(message["content"] for message in request.messages if message["role"] == "user")
        assert "model_requested_reads" not in user
        replies = [json.loads(message["content"]) for message in request.messages if message["role"] == "tool"]
        assert replies and all(reply["call"]["call_id"] and reply["evidence_bindings"] for reply in replies)
    assert len(run.executions) == 1 and not run.responses


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_active_native_capacity_stop_records_safe_actual_exception_facts(tmp_path, monkeypatch, variant):
    real_govern = chat_service.govern_inference_messages
    error = ContextRequiredSectionOverflow(object_ids=("profile:bound", "request:current", "source-required:0",
        "native-exchange:1", "private-body-do-not-persist"), budget=12000, required_tokens=14000)

    def governed(**kwargs):
        if kwargs.get("native_exchanges"):
            raise error
        return real_govern(**kwargs)

    monkeypatch.setattr(chat_service, "govern_inference_messages", governed)
    run = await _run_sheet(tmp_path, monkeypatch, reads=True, variant=variant)
    trace = run.result["retrieval_trace"]
    assert trace["tool_loop"]["evidence_read_stop"] == "evidence_read_capacity"
    diagnostic = trace["context_governor"]["error"]
    assert diagnostic["code"] == error.code
    assert diagnostic["budget"] == diagnostic["available_tokens"] == error.budget
    assert diagnostic["required_tokens"] == error.required_tokens
    assert diagnostic["overflow_tokens"] == 2000
    assert diagnostic["required_objects"] == 5
    assert diagnostic["required_section_object_counts"] == {
        "profile": 1, "request": 1, "source-required": 1, "native-exchange": 1, "other": 1}
    assert diagnostic["purpose"] == ("direct_evidence_read" if variant == "B0_DIRECT" else "sheet_pass_evidence_read")
    assert "private-body-do-not-persist" not in json.dumps(diagnostic)
    assert len(run.requests) == 2 and not run.executions


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
@pytest.mark.parametrize("request_fourth_read", [False, True])
async def test_three_native_reads_at_budget_allow_final_continuation_but_reject_fourth_read(request_fourth_read):
    calls = [_call(f"c{index}", norm_key=f"immutable-card-{index}") for index in range(1, 4)]
    fourth = _call("c4", norm_key="immutable-card-4")
    final_text = "\nModel-authored final rows\n| material | 12 | selected-code |\n"
    next_text = _encoded(fourth) if request_fourth_read else final_text
    executed, continued = [], []

    def execute(call):
        executed.append(call)
        return {"status": "ok", "source_ref": call["args"]["norm_key"]}

    def continuation(receipts, results, exchanges):
        continued.append((receipts, results, exchanges))
        assert len(receipts) == len(results) == 3
        assert len(exchanges) == 1
        assert [call.call_id for call in exchanges[0].calls] == ["c1", "c2", "c3"]
        assert [reply.call_id for reply in exchanges[0].replies] == ["c1", "c2", "c3"]
        return next_text, {"completion_tokens": 11}

    result = await run_model_evidence_read_turn(
        text=_encoded(*calls), usage={"completion_tokens": 7},
        parse_calls=_parse_model_tool_calls, execute=execute,
        continue_native_turn=continuation, allowed_tools={"read_norm_card"}, max_calls=3,
    )

    assert executed == calls
    assert len(continued) == 1
    assert len(result.receipts) == len(result.results) == len(result.seen_calls) == 3
    assert len(result.native_exchanges) == 1
    assert result.text == next_text
    assert result.usage == {"completion_tokens": 11}
    assert result.stop_reason == ("evidence_read_budget" if request_fourth_read else "")


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


@pytest.mark.asyncio
@pytest.mark.parametrize("mixed", [False, True])
async def test_repeated_native_read_replays_bound_receipt_once_without_reexecution(mixed):
    first = _call("first")
    repeated = _call("repeated")
    fresh = _call("fresh", norm_key="another-card")
    executed, frames, persisted_replays = [], [], []

    def execute(call):
        executed.append(call)
        return {"status": "ok"}

    def bind(receipts, results):
        for receipt in receipts:
            ref = "Q1.H1" if receipt["call"]["args"] == first["args"] else "Q2.H1"
            receipt.update(evidence_refs=[ref], evidence_bindings={ref: "immutable-" + ref})

    def continuation(receipts, results, exchanges):
        frames.append(exchanges)
        return (_encoded(repeated, fresh) if mixed else _encoded(repeated), {}) if len(frames) == 1 else ("final unchanged", {})

    result = await run_model_evidence_read_turn(
        text=_encoded(first), usage={}, parse_calls=_parse_model_tool_calls, execute=execute,
        on_read_results=bind, on_read_replays=lambda receipts: persisted_replays.extend(receipts),
        continue_native_turn=continuation, allowed_tools={"read_norm_card"},
    )
    assert result.text == "final unchanged" and result.stop_reason == ""
    assert executed == ([first, fresh] if mixed else [first])
    reply = json.loads(frames[-1][-1].replies[0].content)
    assert reply["call"]["call_id"] == "repeated"
    assert reply["evidence_bindings"] == {"Q1.H1": "immutable-Q1.H1"}
    assert reply["replayed_from_call_id"] == "first"
    assert len(persisted_replays) == 1
    assert len(result.native_exchanges) == 2


@pytest.mark.asyncio
async def test_native_cache_replay_is_bounded_and_keeps_budget():
    counts = {"execute": 0, "continue": 0}

    def execute(call):
        counts["execute"] += 1
        return {"status": "ok"}

    def continuation(*_args):
        counts["continue"] += 1
        return _encoded(_call("call-" + str(counts["continue"]))), {"completion_tokens": 3}

    result = await run_model_evidence_read_turn(
        text=_encoded(_call("initial")), usage={"completion_tokens": 2},
        parse_calls=_parse_model_tool_calls, execute=execute, continue_native_turn=continuation,
        allowed_tools={"read_norm_card"},
    )
    assert counts == {"execute": 1, "continue": 2}
    assert result.stop_reason == "evidence_read_repeat"
    assert result.extra_completion_tokens == 8
    assert len(result.receipts) == 2 and len(result.results) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
@pytest.mark.parametrize("repeats", [1, 2])
async def test_active_replay_reaches_final_or_pauses_with_precise_reason(tmp_path, monkeypatch, variant, repeats):
    from proxy.services.workbook_research_job_service import WorkbookResearchJobService

    run = await _run_sheet(tmp_path, monkeypatch, reads=True, variant=variant, native_repeats=repeats)
    trace = run.result["retrieval_trace"]
    assert len(run.exact_reads) == 1
    receipts = trace["tool_loop"]["evidence_reads"]
    replay = next(r for r in receipts if r.get("replayed_from_call_id"))
    assert replay["call"]["call_id"] == "repeated-0"
    assert replay["evidence_bindings"] == receipts[0]["evidence_bindings"]
    replies = [json.loads(m["content"]) for r in run.requests for m in r.messages
               if m.get("role") == "tool" and m.get("tool_call_id") == "repeated-0"]
    assert replies and replies[0]["evidence_bindings"] == receipts[0]["evidence_bindings"]
    if repeats == 1:
        assert len(run.executions) == 1 and not run.responses
        assert trace["model_result"]["packaged"] is True
    else:
        assert not run.executions
        assert trace["model_result"]["status"] == "technical_pending"
        assert trace["model_result"]["reason"] == "evidence_read_repeat"
        assert "не разобран как таблица" not in run.result["answer"]
        if variant == "B1_CANDIDATE":
            job = WorkbookResearchJobService().get(trace["workbook_research_job"]["job_id"])
            assert job["phase"] == "evidence_read_repeat" and job["accepted_rows"] == []
            saved = [r for rs in job["task_context"]["model_evidence_reads"].values() for r in rs]
            assert any(r.get("replayed_from_call_id") for r in saved)


@pytest.mark.asyncio
async def test_duplicate_native_calls_in_one_batch_read_once_but_reply_to_each_id():
    executed = []
    result = await run_model_evidence_read_turn(
        text=_encoded(_call("one"), _call("two")), usage={}, parse_calls=_parse_model_tool_calls,
        execute=lambda call: executed.append(call) or {"status": "missing"},
        continue_native_turn=lambda *args: ("final", {}), allowed_tools={"read_norm_card"}, max_calls=2,
    )
    assert len(executed) == 1 and result.stop_reason == ""
    assert [r.call_id for r in result.native_exchanges[0].replies] == ["one", "two"]
    assert all(json.loads(r.content)["status"] == "missing" for r in result.native_exchanges[0].replies)


@pytest.mark.asyncio
async def test_replay_does_not_bypass_call_budget():
    calls = [_call("one"), _call("two")]
    result = await run_model_evidence_read_turn(
        text=_encoded(calls[0]), usage={}, parse_calls=_parse_model_tool_calls,
        execute=lambda call: {"status": "ok"},
        continue_native_turn=lambda *args: (_encoded(calls[1]), {}), allowed_tools={"read_norm_card"}, max_calls=1,
    )
    assert result.stop_reason == "evidence_read_budget" and len(result.receipts) == 1


@pytest.mark.asyncio
async def test_resume_replays_saved_receipt_and_retains_repeat_guard_across_turns():
    from proxy.services.model_evidence_read_service import evidence_read_call_identity

    old = _call("old")
    prior = {"call": old, "status": "ok", "evidence_refs": ["Q9.H1"],
             "evidence_bindings": {"Q9.H1": "source-sha-bound"}}
    result = await run_model_evidence_read_turn(
        text=_encoded(_call("resumed")), usage={}, parse_calls=_parse_model_tool_calls,
        execute=lambda call: pytest.fail("resume must not re-execute a saved successful read"),
        continue_native_turn=lambda *args: ("final", {}), allowed_tools={"read_norm_card"},
        initial_receipts=[prior], seen_calls=[evidence_read_call_identity(old)],
    )
    assert result.text == "final" and result.receipts[-1]["replayed_from_call_id"] == "old"
    assert result.receipts[-1]["evidence_bindings"] == prior["evidence_bindings"]
    stopped = await run_model_evidence_read_turn(
        text=_encoded(_call("resumed-again")), usage={}, parse_calls=_parse_model_tool_calls,
        execute=lambda call: pytest.fail("repeat must stop"),
        continue_native_turn=lambda *args: pytest.fail("repeat must not start another generation"),
        allowed_tools={"read_norm_card"}, initial_receipts=result.receipts, seen_calls=result.seen_calls,
    )
    assert stopped.stop_reason == "evidence_read_repeat"


def test_cross_call_receipt_is_not_accepted_as_native_feedback():
    from proxy.services.model_evidence_read_service import native_evidence_read_exchange

    with pytest.raises(ValueError):
        native_evidence_read_exchange([_call("c1")], [{"call": _call("c2"), "status": "ok"}])
