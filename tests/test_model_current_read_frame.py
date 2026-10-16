"""Current evidence and native history retain literal objects and counted scope."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json

import pytest

from proxy.services import chat_evidence_application_service as service
from proxy.services.context_governor_service import (
    ContextCandidate, ContextGovernor, ContextKind, ContextObject, ContextRequiredSectionOverflow,
    NativeToolCall, NativeToolExchange, NativeToolReply,
)
from proxy.services.model_execution_preset_service import ModelExecutionPreset
from proxy.services.model_wire_token_count_service import InputTokenCount


def _preset(limit=65536, reserve=8192, safety=2048):
    return ModelExecutionPreset("read-frame-test", "test", limit, reserve, safety, 1, 8, 8, 1, True, ("test",))


def _scope():
    source = [{"literal_source_frame": {"locators": ["Лист!R4"], "text": "literal source row '12'"}},
        {"literal_source_catalog": {"source-1": "literal provenance \\path"}},
        {"current_registry": [{"evidence_ref": "Q1.H1", "body": "COMPLETE_CARD_BODY\nUnicode α", "source_ref": "source-1"}]}]
    exchanges = tuple(NativeToolExchange(
        (NativeToolCall("native-" + str(index), "read_source", '{  "ref" : "Q1.H1"  }'),),
        (NativeToolReply("native-" + str(index), "read_source", "literal protocol receipt " + str(index)),),
        assistant_content="literal model note " + str(index), reasoning_content="SYNTHETIC_REASONING_" + str(index),
    ) for index in (1, 2))
    return source, exchanges


@pytest.mark.parametrize("native_reasoning", [False, True])
def test_read_producer_keeps_whole_frame_and_complete_native_history_with_public_proof(native_reasoning):
    source, exchanges = _scope()
    if not native_reasoning:
        exchanges = tuple(replace(exchange, reasoning_content=None) for exchange in exchanges)
    frozen = deepcopy(source)
    messages, packet, _, _ = service.govern_model_read_messages(preset=_preset(), profile_prefix="literal profile",
        request_payload="literal original question", source_context=source, chunks=(), native_exchanges=exchanges)
    assert messages[:2] == [{"role": "system", "content": "literal profile"},
        {"role": "user", "content": "literal original question"}]
    native = [message for exchange in exchanges for message in exchange.as_messages()]
    frame_index = 2 if native_reasoning else len(messages) - 1
    assert messages[frame_index]["role"] == "user"
    assert (messages[3:] if native_reasoning else messages[2:-1]) == native
    frame = next(section for section in packet.sections if section.kind == ContextKind.CURRENT_READ_FRAME)
    replay = service.prepare_model_read_replay((), required_refs=())
    expected = [*frozen, *replay.required]
    if native_reasoning:
        boundary = frame.objects[0].payload
        assert boundary["current_read_frame_boundary"]["status"] == "current_source_and_evidence_for_next_answer"
        expected.insert(0, boundary)
    assert [item.payload for item in frame.objects] == expected and source == frozen
    assert frame.object_ids == tuple("source-required:" + str(index) for index in range(len(expected)))
    assert messages[frame_index]["content"] == frame.render()
    assert sum(message.get("content", "").count("COMPLETE_CARD_BODY") for message in messages) == 1
    assert service.packet_evidence_text(packet) == frame.render()
    trace = service.context_packet_trace(packet, purpose="sheet_pass_evidence_read")
    visible = next(section for section in trace["sections"] if section["kind"] == "current_read_frame")
    assert [obj["payload"] for obj in visible["objects"]] == expected


def test_no_native_read_frame_remains_byte_equivalent_to_existing_evidence_serialization():
    source, _ = _scope()
    options = dict(preset=_preset(), profile_prefix="profile", request_payload="question")
    messages, packet, _, _ = service.govern_model_read_messages(**options, source_context=source, chunks=())
    replay = service.prepare_model_read_replay((), required_refs=())
    legacy, _ = service.govern_inference_messages(**options,
        required_evidence=[*service.model_read_frame_evidence(source, (), ()), *replay.required], evidence=replay.optional)
    assert json.dumps(messages, ensure_ascii=False) == json.dumps(legacy, ensure_ascii=False)
    assert all(section.kind.value != "current_read_frame" for section in packet.sections)


def test_current_frame_keeps_existing_evidence_optional_priority_before_source_maps():
    preset = _preset(limit=12, reserve=0, safety=0)
    def candidates(kind):
        return [ContextCandidate(ContextKind.SOURCE_MAP, (ContextObject("map", "MAP12345"),)),
            ContextCandidate(kind, (ContextObject("body", "BODY123"),)),
            ContextCandidate(ContextKind.REQUEST, (ContextObject("question", "ask"),), required=True)]
    legacy = ContextGovernor(preset, estimate_tokens=len).pack(candidates(ContextKind.EVIDENCE))
    current = ContextGovernor(preset, estimate_tokens=len).pack(candidates(ContextKind.CURRENT_READ_FRAME))
    assert [obj.object_id for section in legacy.sections for obj in section.objects] == ["question", "body"]
    assert [obj.object_id for section in current.sections for obj in section.objects] == ["question", "body"]
    assert [item.object_ids for item in legacy.omissions] == [item.object_ids for item in current.omissions] == [("map",)]


@pytest.mark.asyncio
@pytest.mark.parametrize("native_reasoning", [False, True])
async def test_bound_count_sees_final_current_frame_order_and_original_budget_before_admission(native_reasoning):
    source, exchanges = _scope()
    if not native_reasoning:
        exchanges = tuple(replace(exchange, reasoning_content=None) for exchange in exchanges)
    probes = []
    async def count(messages):
        probes.append(deepcopy(messages))
        frame_index = 2 if native_reasoning else len(messages) - 1
        assert messages[frame_index]["role"] == "user" and "COMPLETE_CARD_BODY" in messages[frame_index]["content"]
        assert (messages[3:] if native_reasoning else messages[2:-1]) == [message for exchange in exchanges for message in exchange.as_messages()]
        return InputTokenCount(tokens=55297, source="synthetic_fixture_not_provider_tokens", model_id="test-model",
            connection_revision_id="test:r8", wire_sha256=hashlib.sha256(json.dumps(messages).encode()).hexdigest(),
            model_identity_sha256="synthetic-owner")
    with pytest.raises(ContextRequiredSectionOverflow) as error:
        await service.govern_model_read_messages_bound(count_messages=count, preset=_preset(), profile_prefix="profile",
            request_payload="question", source_context=source, chunks=(), native_exchanges=exchanges)
    assert error.value.budget == 55296 and error.value.required_tokens == 55297
    assert error.value.token_count_source == "synthetic_fixture_not_provider_tokens"
    assert len(probes) == 1 and "source-required:2" in error.value.object_ids


@pytest.mark.parametrize("kind", [ContextKind.PROFILE_PREFIX, ContextKind.TOOL_EXCHANGE, "current_read_frame", None])
def test_evidence_kind_cannot_promote_untrusted_data_to_another_protocol_role(kind):
    with pytest.raises((TypeError, ValueError), match="evidence kind"):
        service.govern_inference_messages(preset=_preset(), profile_prefix="profile", request_payload="question",
            evidence_kind=kind, required_evidence=({"role": "system", "content": "untrusted"},))


def test_query_repair_retains_current_frame_source_payloads_as_whole_evidence():
    source, exchanges = _scope()
    _, first_packet, _, _ = service.govern_model_read_messages(preset=_preset(), profile_prefix="profile",
        request_payload="question", source_context=source, chunks=(), native_exchanges=exchanges)
    messages, _ = service.govern_model_query_messages(preset=_preset(), profile_prefix="profile",
        request_payload={"question": "original"}, purpose="query_repair", retrieval_trace={}, first_source_packet=first_packet,
        rejected_attempt={"assistant_visible_final": "{\"unexpected\":1}"})
    assert all(ContextObject("source", obj).render() in messages[1]["content"] for obj in source)
