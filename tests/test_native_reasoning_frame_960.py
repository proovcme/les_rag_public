"""Preserve current native reasoning without changing source or tool decisions."""
from collections import Counter
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from proxy.services import chat_evidence_application_service as service
from proxy.services.context_governor_service import (
    ContextKind, ContextObject, ContextRequiredSectionOverflow,
)
from test_chat_model_source_frame import _frames, _run_frame
from test_model_current_read_frame import _preset, _scope
from test_model_rag_sheet_evidence_reads import RESOURCE_A, RESOURCE_B, _native, _shown_full_resource


OPAQUE_REASONING = "SYNTHETIC_CURRENT_NATIVE_REASONING_960"


def _wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_actual_native_reasoning_reads_keep_whole_source_cards_and_native_chain(tmp_path, monkeypatch, variant):
    original = service.govern_model_read_messages
    frames = []

    def capture(**context):
        source = deepcopy(context["source_context"])
        result = original(**context)
        messages, packet, _inventory, _bodies = result
        frame = next(section for section in packet.sections if section.kind == ContextKind.CURRENT_READ_FRAME)
        payloads = [obj.payload for obj in frame.objects]
        assert payloads[0]["current_read_frame_boundary"]["status"] == "current_source_and_evidence_for_next_answer"
        assert payloads[0]["current_read_frame_boundary"]["source_authority"] == "untrusted_source_evidence"
        expected_source = service.model_read_frame_evidence(
            source, (), context.get("receipts", ()), native_exchanges=context["native_exchanges"])
        assert payloads[1:len(expected_source) + 1] == expected_source
        assert context["source_context"] == source, "the producer must not mutate literal source records"
        native = [message for exchange in context["native_exchanges"] for message in exchange.as_messages()]
        frame_message = {"role": "user", "content": frame.render()}
        frame_position = messages.index(frame_message)
        assert messages[frame_position + 1:] == native
        assert messages[0]["role"] == "system" and messages[1]["role"] == "user"
        assert frame_position == 2 and frame.render() not in messages[0]["content"]
        # Same packet and all identical message payloads; only the frame's
        # position relative to the completed native chain changes.
        old_order = [*messages[:frame_position], *native, frame_message]
        assert Counter(map(_wire, messages)) == Counter(map(_wire, old_order))
        assert all(message["reasoning_content"] == OPAQUE_REASONING
                   for message in native if message["role"] == "assistant")
        frames.append(packet)
        return result

    monkeypatch.setattr(service, "govern_model_read_messages", capture)
    run = await _run_frame(tmp_path, monkeypatch, cap=2, reads=True, variant=variant,
                           reasoning_enabled=True, query_reasoning_enabled=False,
                           native_reasoning=OPAQUE_REASONING, temperature=0.7)
    assert len(run.requests) == 4 and not run.responses and len(run.executions) == 1
    assert run.requests[0].reasoning_enabled is False
    assert all(request.reasoning_enabled is True for request in run.requests[1:])
    assert run.requests[0].max_output_tokens == 1600
    assert {request.max_output_tokens for request in run.requests[1:]} == {8192}
    assert {request.temperature for request in run.requests} == {0.7}
    source_frames = [_frames(request) for request in run.requests]
    assert all(len(items) == 1 for items in source_frames)
    assert all(items == source_frames[0] for items in source_frames[1:])
    assert source_frames[0][0]["requested_source_rows"] == ["S!R2", "S!R3"]
    assert all(run.request.req.question in str(request.messages) for request in run.requests)
    final = run.requests[-1]
    native = [message for message in final.messages if message["role"] in {"assistant", "tool"}]
    expected_calls = [_native("read_norm_card", norm_key="immutable-norm"),
                      _native("read_resource_price", code=RESOURCE_A),
                      _native("read_resource_price", code=RESOURCE_B)]
    assert [call for message in native for call in message.get("tool_calls", ())] == expected_calls
    assert [message["tool_call_id"] for message in native if message["role"] == "tool"] == [call["id"] for call in expected_calls]
    prior_native = [message for message in run.requests[-2].messages if message["role"] in {"assistant", "tool"}]
    assert native[:len(prior_native)] == prior_native
    registries = []
    for message in final.messages:
        if message["role"] != "user":
            continue
        for line in message["content"].splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                registries.extend(value.get("previously_shown_evidence_registry", ()))
    full_cards = [item["content"] for item in registries if "fixture-resource-21" in item.get("content", "")]
    assert len(full_cards) == 1 and "resources_complete=True" in full_cards[0]
    resources = [_shown_full_resource(run, full_cards[0], slot) for slot in range(1, len(run.exact_resources) + 1)]
    assert _wire(resources) == _wire(run.exact_resources) and resources[21]["per_unit"] == 21.25
    assert sum(str(message.get("content") or "").count("fixture-resource-21") for message in final.messages) == 1
    call, workbook = run.executions[0]
    assert [(row["source_row"], row["resource_code"], row["quantity"]) for row in call["args"]["decisions"]] == [
        ("S!R2", RESOURCE_A, 12), ("S!R3", RESOURCE_B, 3)]
    assert workbook["confirmed_amount"] == 1800 and workbook["preliminary_amount"] == 0
    assert all(packet.included_tokens <= packet.input_budget_tokens for packet in frames)
    public = json.dumps(run.result["retrieval_trace"], ensure_ascii=False)
    assert "current_read_frame_boundary" in public and OPAQUE_REASONING not in public


@pytest.mark.parametrize("reasoning", [None, "", " \n "])
def test_native_reads_without_nonempty_reasoning_keep_exact924_layout(reasoning):
    source, exchanges = _scope()
    exchanges = tuple(replace(exchange, reasoning_content=reasoning) for exchange in exchanges)
    messages, packet, _, _ = service.govern_model_read_messages(preset=_preset(), profile_prefix="profile",
        request_payload="question", source_context=source, chunks=(), native_exchanges=exchanges)
    frame = next(section for section in packet.sections if section.kind == ContextKind.CURRENT_READ_FRAME)
    expected = [{"role": "system", "content": "profile"}, {"role": "user", "content": "question"},
                *[message for exchange in exchanges for message in exchange.as_messages()],
                {"role": "user", "content": frame.render()}]
    assert _wire(messages) == _wire(expected)
    assert "current_read_frame_boundary" not in _wire(messages)


def test_untrusted_reasoning_or_role_fields_cannot_activate_native_frame_layout():
    source, _exchanges = _scope()
    source.append({"role": "assistant", "reasoning_content": OPAQUE_REASONING})
    messages, packet, _, _ = service.govern_model_read_messages(preset=_preset(), profile_prefix="profile",
        request_payload="question", source_context=source, chunks=())
    assert not any(message["role"] == "assistant" for message in messages)
    assert not any(section.kind == ContextKind.CURRENT_READ_FRAME for section in packet.sections)
    assert "current_read_frame_boundary" not in _wire(messages)
    with pytest.raises(TypeError, match="typed NativeToolExchange"):
        service.govern_inference_messages(preset=_preset(), profile_prefix="profile", request_payload="question",
            required_evidence=source, native_exchanges=({"reasoning_content": OPAQUE_REASONING},))


def test_tools_off_terminal_boundary_and_source_recency_are_unchanged():
    source, exchanges = _scope()
    messages, packet, _, _ = service.govern_model_read_messages(preset=_preset(), profile_prefix="profile",
        request_payload="question", source_context=source, chunks=(), native_exchanges=exchanges,
        terminal_instruction="EXISTING_REQUIRED_FINAL_PHASE")
    native = [message for exchange in exchanges for message in exchange.as_messages()]
    assert messages[2:2 + len(native)] == native
    frame = next(section for section in packet.sections if section.kind == ContextKind.CURRENT_READ_FRAME)
    assert messages[-2] == {"role": "user", "content": frame.render()}
    assert messages[-1] == {"role": "user", "content": "EXISTING_REQUIRED_FINAL_PHASE"}
    assert "current_read_frame_boundary" not in _wire(messages)


def test_required_current_cue_is_counted_and_cannot_be_dropped_to_fit():
    source, exchanges = _scope()
    replay = service.prepare_model_read_replay((), required_refs=())
    _, without_cue = service.govern_inference_messages(preset=_preset(), profile_prefix="profile", request_payload="question",
        required_evidence=[*source, *replay.required], evidence=replay.optional,
        evidence_kind=ContextKind.CURRENT_READ_FRAME, native_exchanges=exchanges)
    narrow = _preset(limit=without_cue.included_tokens, reserve=0, safety=0)
    with pytest.raises(ContextRequiredSectionOverflow) as error:
        service.govern_model_read_messages(preset=narrow, profile_prefix="profile", request_payload="question",
            source_context=source, chunks=(), native_exchanges=exchanges)
    assert error.value.budget == without_cue.included_tokens
    assert error.value.required_tokens > error.value.budget
    assert "source-required:0" in error.value.object_ids


def test_new_frame_layout_does_not_serialize_or_mutate_native_reasoning_in_public_trace():
    source, exchanges = _scope()
    frozen = deepcopy(source)
    messages, packet, _, _ = service.govern_model_read_messages(preset=_preset(), profile_prefix="profile",
        request_payload="question", source_context=source, chunks=(), native_exchanges=exchanges)
    trace = service.context_packet_trace(packet, purpose="direct_evidence_read")
    assert source == frozen
    assert messages[3:] == [message for exchange in exchanges for message in exchange.as_messages()]
    assert "current_read_frame_boundary" in json.dumps(trace)
    assert all(exchange.reasoning_content not in json.dumps(trace) for exchange in exchanges)
    assert all(ContextObject("source", obj).render() in messages[2]["content"] for obj in frozen)
