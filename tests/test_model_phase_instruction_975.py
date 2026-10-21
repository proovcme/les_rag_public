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
@pytest.mark.parametrize("kind,purpose,native_reads", [
    ("norm", "sheet_pass_norm_proof", False),
    ("resource_group", "sheet_pass_resource_group_proof", False),
    ("norm", "sheet_pass_norm_proof", True),
])
async def test_actual_sheet_proof_uses_its_existing_literal_request_as_separate_required_phase_975(
        tmp_path, monkeypatch, kind, purpose, native_reads):
    from proxy.services.workbook_research_job_service import WorkbookResearchJobService
    from tests.test_model_rag_sheet_evidence_reads import NORM_CODE, NORM_CODE_B
    from tests.test_explicit_norm_proof_read_973 import _native_read

    counted, cloud_checked, built_phases, saved_pending = [], [], [], []
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
    builder_name = ("resource_group_proof_request_message" if is_group
                    else "norm_card_proof_request_message")
    original_builder = getattr(app, builder_name)
    def observe_phase(*args, **kwargs):
        literal = original_builder(*args, **kwargs)
        if literal:
            built_phases.append(literal)
        return literal
    monkeypatch.setattr(app, builder_name, observe_phase)
    original_pending = WorkbookResearchJobService.record_pending_proof
    def observe_pending(self, job_id, **kwargs):
        saved_pending.append(deepcopy(kwargs["held_packet"]["pending_proof"]))
        return original_pending(self, job_id, **kwargs)
    monkeypatch.setattr(WorkbookResearchJobService, "record_pending_proof", observe_pending)

    answer = WORK_ANSWER if is_group else SECOND_NORM_ANSWER
    if native_reads:
        answer = ("artifact_kind: lsr\n\n"
            "| source_row | row_role | title | unit | quantity | norm_code | resource_code | evidence_refs |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
            f"| S!R2 | work | Literal A | m | 12 | {NORM_CODE} | — | Q1.H1 |\n"
            f"| S!R3 | work | Literal B | m | 3 | {NORM_CODE_B} | — | Q2.H1 |")
    replies = ([InferenceResponse(text="", tool_calls=(_native_read("Q1.H1", "proof-A"),),
                                  finish_reason="tool_calls", usage={}),
                InferenceResponse(text="", tool_calls=(_native_read("Q2.H1", "proof-B"),),
                                  finish_reason="tool_calls", usage={})] if native_reads else [])
    replies.append(InferenceResponse(text=answer, tool_calls=(), finish_reason="stop", usage={}))
    run = await _run_sheet(tmp_path, monkeypatch, reads=is_group, distinct_norms=not is_group,
        group_char_budget=None if is_group else 7000, final_answer=answer, wire_budget_bytes=300000,
        native_reasoning="SYNTHETIC_CURRENT_NATIVE_CHAIN_977" if native_reads else None,
        proof_replies=replies)
    frames = [frame for frame in run.result["retrieval_trace"]["context_governor"]["calls"]
              if _proof_payloads(frame)]
    proof_requests = run.requests[-len(replies):]
    assert len(frames) == len(proof_requests) == len(replies) and not run.responses
    assert frames[0]["purpose"] == purpose and len(built_phases) == 1
    literal_phase = built_phases[0]
    assert len(saved_pending) == 1
    assert saved_pending[0]["proof_request"] == literal_phase
    assert saved_pending[0]["proof_previous_model_answer"] == answer
    identity = saved_pending[0]["proof_operation_identity"]
    assert set(identity) == {"schema", "instruction", "operations"}
    assert identity["schema"] == "les.proof-operation-identities.v1"
    operations = identity["operations"]
    assert [item["source_row"] for item in operations] == ["S!R2", "S!R3"]
    assert len({item["operation_id"] for item in operations}) == 2
    assert all(item["identity_status"] == "uncommitted"
               and item["committed"] is False and "expected_revision" not in item
               for item in operations)
    for frame, request in zip(frames, proof_requests):
        assert _proof_payloads(frame) == [{"proof_previous_model_answer": answer,
                                         "proof_operation_identity": identity}], (
            "the prior answer remains complete data; the phase instruction has one trusted owner")
        phases = [section for section in frame["sections"] if section["kind"] == "phase_instruction"]
        assert len(phases) == 1 and phases[0]["items"] == 1
        assert sum(message == {"role": "user", "content": literal_phase}
                   for message in request.messages) == 1
        dispatched = _request_projection(request)
        assert dispatched in counted and dispatched in cloud_checked
        assert request.max_output_tokens == 8192
        assert all(section["kind"] != "terminal_request" for section in frame["sections"])
        assert json.dumps(answer, ensure_ascii=False) in "\n".join(
            str(message.get("content") or "") for message in request.messages)
    assert proof_requests[0].messages[-1] == {"role": "user", "content": literal_phase}
    if native_reads:
        for request in proof_requests[1:]:
            phase_index = next(index for index, message in enumerate(request.messages)
                               if message == {"role": "user", "content": literal_phase})
            native_indices = [index for index, message in enumerate(request.messages)
                              if message["role"] in {"assistant", "tool"}]
            assert native_indices and phase_index < min(native_indices)
        final_messages = proof_requests[-1].messages
        assert {message.get("tool_call_id") for message in final_messages
                if message["role"] == "tool"} == {"proof-A", "proof-B"}
        assert "fixture-resource-21" in str(final_messages)
        assert any(message.get("reasoning_content") == "SYNTHETIC_CURRENT_NATIVE_CHAIN_977"
                   for message in final_messages if message["role"] == "assistant")
    elif is_group:
        assert "fixture-resource-21" in str(proof_requests[0].messages)
    initial = next(frame for frame in run.result["retrieval_trace"]["context_governor"]["calls"]
                   if frame["purpose"] == "sheet_pass_answer")
    assert all(section["kind"] != "phase_instruction" for section in initial["sections"])
