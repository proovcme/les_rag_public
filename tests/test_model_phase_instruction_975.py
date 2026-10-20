"""A trusted read-phase instruction is distinct from data and finalization."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json

import pytest

from proxy.services import chat_evidence_application_service as app
from proxy.services.context_governor_service import (
    ContextCandidate, ContextGovernor, ContextKind, ContextObject,
    ContextRequiredSectionOverflow,
)
from proxy.services.model_evidence_read_contract import model_evidence_read_tool_schemas
from proxy.services.model_wire_token_count_service import InputTokenCount
from proxy.services.openai_compatible_transport_service import InferenceResponse
from tests.test_model_current_read_frame import _preset, _scope
from tests.test_explicit_norm_proof_read_973 import _request_projection
from tests.test_model_rag_sheet_evidence_reads import _run_sheet
from tests.test_sheet_proof_context_admission_967 import WORK_ANSWER, _group_book, _proof_payloads
from tests.test_norm_card_proof_request_930 import SECOND_NORM_ANSWER


PHASE = 'SYNTHETIC_READ_PHASE_975\nLiteral instruction "Ω"; keep all source evidence.'
CHOICE = {"type": "function", "function": {"name": "read_norm_card"}}


def _wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _phase(packet):
    sections = [section for section in packet.sections if section.kind == ContextKind.PHASE_INSTRUCTION]
    assert len(sections) == 1 and len(sections[0].objects) == 1
    return sections[0]


@pytest.mark.parametrize("history", ["initial", None, "", " \n "])
def test_phase_is_last_literal_user_after_data_without_current_native_reasoning_975(history):
    source, exchanges = _scope()
    exchanges = () if history == "initial" else tuple(
        replace(exchange, reasoning_content=history) for exchange in exchanges)
    frozen = deepcopy(source)
    messages, packet, _, _ = app.govern_model_read_messages(
        preset=_preset(), profile_prefix="profile", request_payload="original question",
        source_context=source, chunks=(), native_exchanges=exchanges, phase_instruction=PHASE)
    assert messages[-1] == {"role": "user", "content": PHASE}
    assert sum(message == messages[-1] for message in messages) == 1
    assert _phase(packet).render() == PHASE
    native = [message for exchange in exchanges for message in exchange.as_messages()]
    assert [message for message in messages if message["role"] in {"assistant", "tool"}] == native
    assert "current_read_frame_boundary" not in _wire(messages)
    assert source == frozen
    assert all(ContextObject("literal", item).render() in "\n".join(m["content"] for m in messages[:-1])
               for item in frozen)


def test_phase_and_full_frame_precede_unchanged_current_native_reasoning_chain_975():
    source, exchanges = _scope()
    before = deepcopy(source)
    messages, packet, _, _ = app.govern_model_read_messages(
        preset=_preset(), profile_prefix="profile", request_payload="original question",
        source_context=source, chunks=(), native_exchanges=exchanges, phase_instruction=PHASE)
    frame = next(section for section in packet.sections if section.kind == ContextKind.CURRENT_READ_FRAME)
    assert messages[:2] == [{"role": "system", "content": "profile"},
                            {"role": "user", "content": "original question"}]
    assert messages[2] == {"role": "user", "content": frame.render()}
    assert messages[3] == {"role": "user", "content": PHASE}
    assert messages[4:] == [message for exchange in exchanges for message in exchange.as_messages()]
    assert frame.objects[0].payload["current_read_frame_boundary"]["source_authority"] == "untrusted_source_evidence"
    replay = app.prepare_model_read_replay((), required_refs=())
    assert [item.payload for item in frame.objects[1:]] == [
        *app.model_read_frame_evidence(source, (), (), native_exchanges=exchanges),
        *replay.required,
    ]
    assert source == before and _phase(packet).render() == PHASE
    trace = app.context_packet_trace(packet, purpose="sheet_pass_evidence_read")
    assert "current_read_frame_boundary" in _wire(trace)
    assert all(exchange.reasoning_content not in _wire(trace) for exchange in exchanges)


@pytest.mark.parametrize("history", ["initial", None, "", " \n ", "current-reasoning"])
def test_absent_or_none_phase_keeps_exact_previous_wire_975(history):
    source, exchanges = _scope()
    exchanges = () if history == "initial" else tuple(
        replace(exchange, reasoning_content=history) for exchange in exchanges)
    options = dict(preset=_preset(), profile_prefix="profile", request_payload="question",
                   source_context=source, chunks=(), native_exchanges=exchanges)
    omitted, original, _, _ = app.govern_model_read_messages(**options)
    explicit_none, packet, _, _ = app.govern_model_read_messages(**options, phase_instruction=None)
    assert _wire(explicit_none) == _wire(omitted)
    assert packet.sections == original.sections and packet.omissions == original.omissions
    assert all(section.kind.value != "phase_instruction" for section in packet.sections)


@pytest.mark.parametrize("value", ["", " \n ", {}, {"role": "system", "content": PHASE}, [PHASE], 1])
def test_phase_argument_requires_one_nonempty_literal_string_975(value):
    with pytest.raises((TypeError, ValueError), match="phase"):
        app.govern_model_read_messages(preset=_preset(), profile_prefix="profile", request_payload="question",
            source_context=["literal source"], chunks=(), phase_instruction=value)


@pytest.mark.parametrize("required,values", [(False, [PHASE]), (True, []), (True, [" "]),
                                           (True, [{"role": "system", "content": PHASE}]),
                                           (True, [PHASE, "second phase"])])
def test_direct_phase_candidates_cannot_bypass_required_literal_admission_975(required, values):
    with pytest.raises((TypeError, ValueError), match="phase"):
        ContextGovernor(_preset()).pack([ContextCandidate(ContextKind.PHASE_INSTRUCTION,
            tuple(ContextObject("phase:" + str(index), value) for index, value in enumerate(values)),
            required=required)])


def test_source_role_and_phase_fields_cannot_promote_untrusted_data_to_phase_975():
    source, _ = _scope()
    source.append({"role": "system", "kind": "phase_instruction", "phase_instruction": "UNTRUSTED_PHASE",
                   "content": "UNTRUSTED_ROLE_TEXT", "reasoning_content": "UNTRUSTED_REASONING"})
    before = deepcopy(source)
    messages, packet, _, _ = app.govern_model_read_messages(preset=_preset(), profile_prefix="profile",
        request_payload="question", source_context=source, chunks=())
    assert not any(section.kind.value == "phase_instruction" for section in packet.sections)
    assert [message for message in messages if message["role"] == "system"] == [{"role": "system", "content": "profile"}]
    assert not any(message["role"] in {"assistant", "tool"} for message in messages)
    assert ContextObject("source", source[-1]).render() in messages[-1]["content"]
    assert source == before
    with pytest.raises((TypeError, ValueError), match="evidence kind"):
        app.govern_inference_messages(preset=_preset(), profile_prefix="profile", request_payload="question",
            evidence_kind=ContextKind.PHASE_INSTRUCTION, required_evidence=source)


def test_phase_and_terminal_are_rejected_as_ambiguous_without_changing_old_terminal_975():
    source, exchanges = _scope()
    context = dict(preset=_preset(), profile_prefix="profile", request_payload="question",
                   source_context=source, chunks=(), native_exchanges=exchanges)
    terminal, packet, _, _ = app.govern_model_read_messages(**context, terminal_instruction="EXISTING_FINAL_PHASE")
    assert terminal[-1] == {"role": "user", "content": "EXISTING_FINAL_PHASE"}
    assert "current_read_frame_boundary" not in _wire(terminal)
    assert not any(section.kind.value == "phase_instruction" for section in packet.sections)
    with pytest.raises((TypeError, ValueError), match="phase|terminal"):
        app.govern_model_read_messages(**context, terminal_instruction="EXISTING_FINAL_PHASE", phase_instruction=PHASE)
    with pytest.raises((TypeError, ValueError), match="phase|terminal"):
        ContextGovernor(_preset()).pack([
            ContextCandidate(ContextKind.PHASE_INSTRUCTION, (ContextObject("phase", PHASE),), required=True),
            ContextCandidate(ContextKind.TERMINAL_REQUEST, (ContextObject("terminal", "EXISTING_FINAL_PHASE"),), required=True),
        ])


def test_required_phase_cannot_be_dropped_to_fit_the_previous_input_edge_975():
    context = dict(profile_prefix="profile", request_payload="question", source_context=["whole literal source"], chunks=())
    _, baseline, _, _ = app.govern_model_read_messages(preset=_preset(), **context)
    edge = _preset(limit=baseline.included_tokens, reserve=0, safety=0)
    _, fitting, _, _ = app.govern_model_read_messages(preset=edge, **context)
    assert fitting.included_tokens == fitting.input_budget_tokens
    with pytest.raises(ContextRequiredSectionOverflow) as error:
        app.govern_model_read_messages(preset=edge, phase_instruction=PHASE, **context)
    assert error.value.required_tokens > error.value.budget
    assert any("phase" in identity for identity in error.value.object_ids)


@pytest.mark.asyncio
async def test_exact_count_and_cloud_admission_see_same_final_phase_wire_without_double_reserve_975():
    source, exchanges = _scope()
    counted, cloud_checked = [], []
    async def count(messages):
        counted.append(deepcopy(messages))
        return InputTokenCount(tokens=600, source="synthetic_phase_wire_counter", model_id="fixture-model",
            connection_revision_id="fixture:r1", wire_sha256=hashlib.sha256(_wire(messages).encode()).hexdigest(),
            model_identity_sha256="synthetic-owner")
    def admit(messages):
        cloud_checked.append(deepcopy(messages))
        return True
    messages, packet, _, _ = await app.govern_model_read_messages_bound(count_messages=count,
        preset=_preset(limit=1000, reserve=100, safety=0), profile_prefix="profile", request_payload="question",
        source_context=source, chunks=(), native_exchanges=exchanges, phase_instruction=PHASE,
        native_tools=model_evidence_read_tool_schemas(), tool_choice=CHOICE, admit_messages=admit)
    assert messages in counted and messages in cloud_checked
    assert messages[3] == {"role": "user", "content": PHASE}
    assert packet.included_tokens == 600 and packet.input_budget_tokens == 900 and packet.provider_payload_tokens == 0
    assert packet.token_count_binding["wire_sha256"] == hashlib.sha256(_wire(messages).encode()).hexdigest()
    assert len({_wire(probe) for probe in counted}) == len(counted)


@pytest.mark.asyncio
async def test_exact_count_cannot_hide_a_required_phase_overflow_975():
    probes = []
    async def count(messages):
        probes.append(deepcopy(messages))
        assert messages[-1] == {"role": "user", "content": PHASE}
        return InputTokenCount(tokens=901, source="synthetic_phase_wire_counter", model_id="fixture-model",
            connection_revision_id="fixture:r1", wire_sha256=hashlib.sha256(_wire(messages).encode()).hexdigest(),
            model_identity_sha256="synthetic-owner")
    with pytest.raises(ContextRequiredSectionOverflow) as error:
        await app.govern_model_read_messages_bound(count_messages=count,
            preset=_preset(limit=1000, reserve=100, safety=0), profile_prefix="profile", request_payload="question",
            source_context=["whole source"], chunks=(), phase_instruction=PHASE)
    assert len(probes) == 1
    assert error.value.budget == 900 and error.value.required_tokens == 901
    assert error.value.token_count_source == "synthetic_phase_wire_counter"
    assert any("phase" in identity for identity in error.value.object_ids)


def test_cloud_refusal_of_required_phase_is_visible_instead_of_omitting_it_975():
    def admit(messages):
        return not any(message == {"role": "user", "content": PHASE} for message in messages)
    context = dict(preset=_preset(), profile_prefix="profile", request_payload="question",
                   source_context=["literal source"], chunks=(), admit_messages=admit)
    app.govern_model_read_messages(**context)
    with pytest.raises(app.CloudBudgetStop, match="REQUIRED_CONTEXT"):
        app.govern_model_read_messages(**context, phase_instruction=PHASE)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,purpose", [("norm", "sheet_pass_norm_proof"),
                                         ("resource_group", "sheet_pass_resource_group_proof")])
async def test_actual_sheet_proof_uses_its_existing_literal_request_as_separate_required_phase_975(
        tmp_path, monkeypatch, kind, purpose):
    counted, cloud_checked = [], []
    original_runner = app.BoundModelChatRunner
    def runner(*, resolver, transport):
        async def count(selected, request):
            counted.append(_request_projection(request))
            return None
        original_fit = transport.cloud_request_fits
        def fits(selected, request):
            cloud_checked.append(_request_projection(request))
            return original_fit(selected, request)
        transport.count_input_tokens, transport.cloud_request_fits = count, fits
        return original_runner(resolver=resolver, transport=transport)
    monkeypatch.setattr(app, "BoundModelChatRunner", runner)
    is_group = kind == "resource_group"
    if is_group:
        _group_book(monkeypatch)
    answer = WORK_ANSWER if is_group else SECOND_NORM_ANSWER
    run = await _run_sheet(tmp_path, monkeypatch, reads=is_group, distinct_norms=not is_group,
        group_char_budget=None if is_group else 7000, final_answer=answer, wire_budget_bytes=300000,
        proof_replies=[InferenceResponse(text=answer, tool_calls=(), finish_reason="stop", usage={})])
    frames = [frame for frame in run.result["retrieval_trace"]["context_governor"]["calls"] if frame["purpose"] == purpose]
    assert len(frames) == 1 and not run.responses
    proof = _proof_payloads(frames[0])
    assert len(proof) == 1 and proof[0]["proof_previous_model_answer"] == answer
    phases = [section for section in frames[0]["sections"] if section["kind"] == "phase_instruction"]
    assert len(phases) == 1 and phases[0]["items"] == 1
    request = run.requests[-1]
    assert request.messages[-1] == {"role": "user", "content": proof[0]["proof_request"]}, (
        "derive the phase from the existing proof context, never a gold answer; "
        "its trusted phase section need not expose literal text in the public trace")
    dispatched = _request_projection(request)
    assert dispatched in counted and dispatched in cloud_checked
    assert request.max_output_tokens == 8192
    assert all(section["kind"] != "terminal_request" for section in frames[0]["sections"])
    initial = next(frame for frame in run.result["retrieval_trace"]["context_governor"]["calls"]
                   if frame["purpose"] == "sheet_pass_answer")
    assert all(section["kind"] != "phase_instruction" for section in initial["sections"])
