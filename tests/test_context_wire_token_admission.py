"""Whole-wire token admission, independent of professional model decisions."""
import hashlib
import json
from types import SimpleNamespace

import pytest

from proxy.services.context_governor_service import (
    ContextCandidate, ContextGovernor, ContextKind, ContextObject, ContextRequiredSectionOverflow,
)
from proxy.services.model_execution_preset_service import ModelExecutionPreset
from proxy.services.chat_evidence_application_service import govern_model_read_messages_bound


def _preset():
    return ModelExecutionPreset("wire-test", "fixture", 1000, 200, 100, 1, 5, 6, 1, False, ("fixture",))


def _required(body):
    return [ContextCandidate(ContextKind.REQUEST, (ContextObject("request:current", body),), True)]


def test_bound_wire_count_admits_required_frame_that_conservative_estimator_rejects():
    candidate = _required("literal input " * 300)
    governor = ContextGovernor(_preset())
    with pytest.raises(ContextRequiredSectionOverflow):
        governor.pack(candidate)
    packet = governor.pack(candidate, count_messages_tokens=lambda messages: 600,
                           token_count_source="bound-tokenizer")
    assert packet.input_budget_tokens == 700
    assert packet.included_tokens == 600
    assert packet.token_count_source == "bound-tokenizer"
    assert packet.as_messages() == [{"role": "user", "content": candidate[0].objects[0].payload}]


def test_measured_required_overflow_keeps_original_window_and_reserves():
    with pytest.raises(ContextRequiredSectionOverflow) as caught:
        ContextGovernor(_preset()).pack(_required("small text"), count_messages_tokens=lambda messages: 701)
    assert caught.value.required_tokens == 701
    assert caught.value.budget == 700
    assert caught.value.object_ids == ("request:current",)


@pytest.mark.parametrize("binding,expected", [
    ({}, ""),
    ({"status": "fallback", "connection_revision_id": "conn:r8"}, ""),
    ({"status": "counted", "connection_revision_id": "conn:r8"}, "conn:r8"),
    ({"status": "counted", "connection_revision_id": 8}, ""),
])
def test_only_measured_packets_pin_generation_connection(binding, expected):
    from dataclasses import replace
    from proxy.services.chat_evidence_application_service import measured_connection_revision
    packet = ContextGovernor(_preset()).pack(_required("literal input"))
    assert measured_connection_revision(replace(packet, token_count_binding=binding)) == expected


def test_rejected_optional_probe_does_not_replace_final_admitted_token_count():
    candidates = _required("required") + [ContextCandidate(
        ContextKind.EVIDENCE, (ContextObject("fits", "fitting body"), ContextObject("large", "large body")))]
    def count(messages):
        text = json.dumps(messages)
        return 900 if "large body" in text else 500 if "fitting body" in text else 200
    packet = ContextGovernor(_preset()).pack(candidates, count_messages_tokens=count)
    assert packet.included_tokens == 500
    assert packet.omissions[0].object_ids == ("large",)
    assert "fitting body" in packet.as_messages()[0]["content"]
    assert "large body" not in packet.as_messages()[0]["content"]


@pytest.mark.asyncio
async def test_bound_read_frame_counts_each_wire_once_including_tools_without_double_reserve():
    requests = {}
    async def count(messages):
        wire = json.dumps(messages, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha256(wire.encode()).hexdigest()
        assert digest not in requests
        requests[digest] = wire
        return SimpleNamespace(tokens=600, source="bound-tokenizer", model_id="actual-model",
                               connection_revision_id="conn:r8", wire_sha256=digest)
    body = "whole original attachment " * 100
    messages, packet, inventory, bodies = await govern_model_read_messages_bound(
        count_messages=count, preset=_preset(), profile_prefix="literal profile",
        request_payload="literal question", source_context=[body], chunks=[],
        native_tools=[{"type": "function", "function": {"name": "read", "description": "schema " * 1000}}],
    )
    assert body in messages[-1]["content"]
    assert packet.input_budget_tokens == 700
    assert packet.included_tokens == 600
    assert packet.provider_payload_tokens == 0
    assert packet.token_count_binding["model_id"] == "actual-model"
    assert packet.token_count_binding["distinct_count_requests"] == len(requests) == 1
    assert inventory == bodies == []


@pytest.mark.asyncio
async def test_unavailable_counter_preserves_conservative_stop_without_dropping_input():
    async def unavailable(messages):
        return None
    with pytest.raises(ContextRequiredSectionOverflow):
        await govern_model_read_messages_bound(
            count_messages=unavailable, preset=_preset(), profile_prefix="profile",
            request_payload="question", source_context=["whole original attachment " * 300], chunks=[],
        )


@pytest.mark.asyncio
async def test_unavailable_counter_is_explicit_on_a_fitting_frame():
    async def unavailable(messages):
        return None
    messages, packet, _, _ = await govern_model_read_messages_bound(
        count_messages=unavailable, preset=_preset(), profile_prefix="profile",
        request_payload="question", source_context=["whole original attachment"], chunks=[],
    )
    assert packet.token_count_source == "conservative_chars_per_two"
    assert packet.token_count_binding["status"] == "fallback"
    assert "whole original attachment" in messages[-1]["content"]


@pytest.mark.asyncio
async def test_counter_cancellation_propagates_without_a_fallback_frame():
    import asyncio
    async def cancelled(messages):
        raise asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await govern_model_read_messages_bound(
            count_messages=cancelled, preset=_preset(), profile_prefix="profile",
            request_payload="question", source_context=["whole original attachment"], chunks=[],
        )


@pytest.mark.asyncio
async def test_exact_wire_admission_keeps_native_call_reply_ids_and_literal_arguments():
    from proxy.services.context_governor_service import NativeToolCall, NativeToolExchange, NativeToolReply
    exchange = NativeToolExchange(
        (NativeToolCall("literal-provider-id", "read_source", '{ "source_row" : "PDF!R4" }'),),
        (NativeToolReply("literal-provider-id", "read_source", "literal tool result with full source"),),
        assistant_content="literal assistant text",
    )
    seen = []
    async def count(messages):
        seen.append(messages)
        return SimpleNamespace(tokens=450, source="bound-tokenizer", model_id="actual-model",
                               connection_revision_id="conn:r8", wire_sha256="a" * 64)
    messages, packet, _, _ = await govern_model_read_messages_bound(
        count_messages=count, preset=_preset(), profile_prefix="profile", request_payload="question",
        source_context=["whole original attachment"], chunks=[], native_exchanges=(exchange,),
    )
    assert packet.included_tokens == 450
    assert seen == [messages]
    assert messages[-2:] == exchange.as_messages()
    assert messages[-2]["tool_calls"][0]["function"]["arguments"] == '{ "source_row" : "PDF!R4" }'


@pytest.mark.asyncio
@pytest.mark.parametrize("changed_field", ["model_id", "connection_revision_id", "model_identity_sha256"])
async def test_changed_count_owner_discards_cached_required_frame(changed_field):
    requests = []
    async def count(messages):
        requests.append(messages)
        owner = {"model_id": "actual-model", "connection_revision_id": "conn:r8",
                 "model_identity_sha256": "a" * 64}
        if len(requests) == 2:
            owner[changed_field] = "b" * 64 if changed_field == "model_identity_sha256" else "changed"
        return SimpleNamespace(tokens=100 if len(requests) == 1 else 1000,
                               source="bound-tokenizer", wire_sha256=str(len(requests)) * 64, **owner)
    messages, packet, _, _ = await govern_model_read_messages_bound(
        count_messages=count, preset=_preset(), profile_prefix="profile", request_payload="question",
        source_context=["whole original attachment"], chunks=[], dialogue=["optional"],
    )
    assert len(requests) == 2
    assert packet.token_count_binding == {"status": "fallback", "reason": "bound_counter_identity_changed",
                                          "source": "conservative_chars_per_two"}
    assert packet.token_count_source == "conservative_chars_per_two"
    assert packet.included_tokens != 100
    assert "whole original attachment" in messages[-1]["content"]
    assert "optional" in messages[-1]["content"]


@pytest.mark.asyncio
async def test_changed_count_identity_keeps_conservative_required_overflow_visible():
    from proxy.services.chat_evidence_application_service import model_read_capacity_trace
    requests = []
    async def count(messages):
        requests.append(messages)
        return SimpleNamespace(tokens=100 if len(requests) == 1 else 1000, source="bound-tokenizer",
                               model_id="actual-model", connection_revision_id="conn:r8",
                               wire_sha256=str(len(requests)) * 64,
                               model_identity_sha256=("a" if len(requests) == 1 else "b") * 64)
    with pytest.raises(ContextRequiredSectionOverflow) as caught:
        await govern_model_read_messages_bound(
            count_messages=count, preset=_preset(), profile_prefix="profile", request_payload="question",
            source_context=["whole original attachment " * 300], chunks=[], dialogue=["optional"],
        )
    assert len(requests) == 2
    trace = model_read_capacity_trace(caught.value, purpose="fixture")
    assert trace["required_tokens"] > trace["budget"] == 700
    assert trace["token_count_source"] == "conservative_chars_per_two:bound_counter_identity_changed"
    assert "source-required:0" in caught.value.object_ids


@pytest.mark.asyncio
async def test_stable_count_owner_binding_uses_final_cached_frame_not_last_optional_probe():
    requests = []
    async def count(messages):
        requests.append(messages)
        wire = json.dumps(messages, ensure_ascii=False, sort_keys=True)
        return SimpleNamespace(tokens=500 if len(requests) == 1 else 1000, source="bound-tokenizer",
                               model_id="actual-model", connection_revision_id="conn:r8",
                               wire_sha256=hashlib.sha256(wire.encode()).hexdigest(),
                               model_identity_sha256="a" * 64)
    messages, packet, _, _ = await govern_model_read_messages_bound(
        count_messages=count, preset=_preset(), profile_prefix="profile", request_payload="question",
        source_context=["whole original attachment"], chunks=[], dialogue=["rejected optional"],
    )
    assert len(requests) == 2
    assert requests[0] == messages != requests[-1]
    assert packet.included_tokens == packet.token_count_binding["input_tokens"] == 500
    assert packet.token_count_binding["wire_sha256"] == hashlib.sha256(
        json.dumps(messages, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    assert packet.token_count_binding["model_identity_sha256"] == "a" * 64
    assert packet.token_count_binding["distinct_count_requests"] == 2


@pytest.mark.asyncio
async def test_counter_await_failure_propagates_without_a_fallback_frame():
    async def failing(messages):
        raise RuntimeError("counter fixture failure")
    with pytest.raises(RuntimeError, match="counter fixture failure"):
        await govern_model_read_messages_bound(
            count_messages=failing, preset=_preset(), profile_prefix="profile", request_payload="question",
            source_context=["whole original attachment"], chunks=[],
        )
