"""A bounded native norm-proof read keeps model choices and literal provenance.

Only the existing proof round may require reading a model-selected admitted
pointer. The existing model read loop executes actual calls, including failed
reads; no code-selected norm, automatic read, verdict or outer retry is added.
"""
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
import json

import pytest

from proxy.services import chat_evidence_application_service as app
from proxy.services import model_research_tool_service as research
from proxy.services import norm_card_proof_service as proof
from proxy.services.model_evidence_read_contract import model_evidence_read_tool_schemas
from proxy.services.openai_compatible_transport_service import InferenceResponse
from proxy.services.workbook_research_job_service import WorkbookResearchJobService
from tests import test_model_norm_evidence_ref_reads as ref_fixture
from tests.test_model_rag_sheet_evidence_reads import NORM_CODE, NORM_CODE_B, _run_sheet
from tests.test_norm_card_proof_request_930 import SECOND_NORM_ANSWER


CHOICE = {"type": "function", "function": {"name": "read_norm_card"}}


@pytest.fixture
def registered(monkeypatch):
    """Use the existing real bind/Governor/delivery/register fixture, not flags."""
    monkeypatch.setattr(research.nr_sp_service, "model_candidates", lambda **kwargs: [])
    original = deepcopy(ref_fixture.IDENTITY)

    def make(**identity_changes):
        identity = {**original, "norm_key": "ГЭСН:99-01-001-01", "norm_code": NORM_CODE,
                    "normative_base_sha256": "b" * 64, **identity_changes}
        monkeypatch.setattr(ref_fixture, "CODE", identity["norm_code"])
        monkeypatch.setattr(ref_fixture, "IDENTITY", identity)
        reader, exact_calls = ref_fixture._service()
        chunks, receipt = ref_fixture._bound()
        # The reference is not admitted while it is merely prepared.
        reader.register_shown_norm_cards(chunks)
        ref_fixture._admit(chunks, receipt)
        reader.register_shown_norm_cards(chunks)
        ref = chunks[0].meta["model_evidence_ref"]
        return reader, chunks, ref, exact_calls
    return make


def chosen(chunks, ref, code=NORM_CODE):
    row = {"source_row": "S!R2", "row_role": "work", "work_row": "S!R2",
           "title": "Literal model operation", "unit": "m", "quantity": 12,
           "norm_code": code, "evidence_refs": [ref]}
    return app.bind_row_evidence_ids([row], chunks)[0]


def contract(rows, reader, *, chunks=(), purpose=proof.PROOF_PURPOSE,
             receipts=(), planned_refs=None, max_refs=6):
    return proof.proof_native_read_contract(
        rows, purpose=purpose, native_tools=model_evidence_read_tool_schemas(),
        admitted_refs=reader.admitted_norm_references(), chunks=chunks,
        receipts=receipts, planned_refs=planned_refs, max_refs=max_refs,
    )


def assert_default(result):
    assert result["tools"] == model_evidence_read_tool_schemas()
    assert result["tool_choice"] is None


def test_matching_admitted_selected_unread_reference_requires_one_exclusive_argument(registered):
    reader, chunks, ref, exact_calls = registered()
    rows = [chosen(chunks, ref)]
    before = deepcopy(rows)
    result = contract(rows, reader, chunks=chunks)
    assert result["planned_refs"] == (ref,)
    assert result["tool_choice"] == CHOICE
    assert len(result["tools"]) == 1
    function = result["tools"][0]["function"]
    assert function["name"] == "read_norm_card"
    assert function["parameters"] == {
        "type": "object", "properties": {"evidence_ref": {"type": "string", "enum": [ref]}},
        "required": ["evidence_ref"], "additionalProperties": False,
    }
    assert rows == before and exact_calls == [], "a contract must not execute a read or change a choice"
    exported = reader.admitted_norm_references()
    assert isinstance(exported, tuple) and len(exported) == 1
    exported[0]["norm_code"] = "changed copy"
    assert reader.admitted_norm_references()[0]["norm_code"] == NORM_CODE


@pytest.mark.parametrize("boundary", ["other-cipher", "unknown-ref", "empty-ref", "no-chosen-norm",
                                     "snapshot-conflict", "different-base", "different-key"])
def test_no_forcing_for_unproven_selected_identity(registered, boundary):
    reader, chunks, ref, exact_calls = registered()
    row = chosen(chunks, ref)
    if boundary == "other-cipher":
        row = chosen(chunks, ref, NORM_CODE_B)
    elif boundary == "unknown-ref":
        row["evidence_refs"] = ["Q999.H1"]
    elif boundary == "empty-ref":
        row["evidence_refs"] = []
    elif boundary == "no-chosen-norm":
        row["norm_code"] = ""
    elif boundary == "snapshot-conflict":
        row["_evidence_check"]["normative_snapshot_conflict"] = True
    elif boundary == "different-base":
        row["_evidence_check"]["normative_base_sha256"] = "c" * 64
    else:
        row["_evidence_check"]["norm_key"] = "ФЕР:99-01-001-01"
    before = deepcopy(row)
    result = contract([row], reader, chunks=chunks)
    assert_default(result)
    assert result["planned_refs"] == ()
    assert row == before and exact_calls == []


def test_same_alias_with_two_actually_admitted_editions_is_not_forceable(registered):
    reader, chunks, ref, exact_calls = registered()
    row = chosen(chunks, ref)
    other_reader, other_chunks, other_ref, _ = registered(edition="other-literal-edition")
    assert other_ref == ref
    reader.register_shown_norm_cards(other_chunks)
    assert len(reader.admitted_norm_references()) == 2
    assert_default(contract([row], reader, chunks=chunks))
    # A previous chosen row cannot silently borrow the same alias from another
    # edition/snapshot even if only that new pointer is currently registered.
    assert_default(contract([row], other_reader, chunks=chunks))
    assert exact_calls == []


@pytest.mark.parametrize("status", ["ok", "missing", "conflict"])
def test_every_actual_attempt_consumes_the_planned_reference_even_if_unread(registered, status):
    reader, chunks, ref, exact_calls = registered()
    row = chosen(chunks, ref)
    initial = contract([row], reader, chunks=chunks)
    receipt = {"call": {"call_id": "actual-native-id", "tool": "read_norm_card",
                        "args": {"evidence_ref": ref}}, "status": status}
    result = contract([row], reader, chunks=chunks, planned_refs=initial["planned_refs"], receipts=[receipt])
    assert_default(result)
    assert result["planned_refs"] == initial["planned_refs"]
    assert exact_calls == []


def test_actual_legacy_selector_attempt_uses_the_readers_literal_whitespace_rule(registered):
    reader, chunks, ref, _ = registered()
    rows = [chosen(chunks, ref)]
    initial = contract(rows, reader, chunks=chunks)
    receipt = {"call": {"tool": "read_norm_card", "args": {"norm_code": f" {NORM_CODE} "}},
               "status": "missing"}
    assert_default(contract(rows, reader, chunks=chunks, receipts=[receipt],
                            planned_refs=initial["planned_refs"]))


@pytest.mark.parametrize("purpose", ["sheet_pass_answer", "sheet_pass_evidence_read",
                                     "sheet_pass_resource_group_proof", "vor"])
def test_no_native_forcing_outside_the_norm_proof_round(registered, purpose):
    reader, chunks, ref, _ = registered()
    assert_default(contract([chosen(chunks, ref)], reader, chunks=chunks, purpose=purpose))
    assert_default(contract([chosen(chunks, ref)], reader, chunks=chunks, max_refs=0))


def _native_read(ref, call_id):
    return {"id": call_id, "type": "function", "function": {
        "name": "read_norm_card", "arguments": json.dumps({"evidence_ref": ref})}}


def _plain(value):
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _request_projection(request):
    return _plain({"messages": request.messages, "tools": request.tools,
        "tool_choice": getattr(request, "tool_choice", None), "max_output_tokens": request.max_output_tokens,
        "temperature": request.temperature, "reasoning_enabled": request.reasoning_enabled})


@pytest.mark.asyncio
async def test_two_selected_refs_missing_then_ok_restore_default_and_preserve_model_rows(
        tmp_path, monkeypatch):
    # Only provider responses and one exact-reader failure are controlled.
    # Admission, native exchanges, bounded loop, store and workbook path are real.
    original_pointer_read = research.ModelResearchToolService._read_norm_pointer
    attempted = []
    async def pointer_read(self, pointer, args, *, verify_source=False):
        attempted.append(dict(args))
        if args == {"evidence_ref": "Q1.H1"}:
            return self._missing("read_norm_card", "Literal fixture card temporarily unavailable")
        return await original_pointer_read(self, pointer, args, verify_source=verify_source)
    monkeypatch.setattr(research.ModelResearchToolService, "_read_norm_pointer", pointer_read)

    counted, cloud_checked = [], []
    original_runner = app.BoundModelChatRunner
    def runner(*, resolver, transport):
        async def count(selected, request):
            counted.append(_request_projection(request))
            return None  # Observe the actual request; existing conservative fallback stays in use.
        original_fit = transport.cloud_request_fits
        def fits(selected, request):
            cloud_checked.append(_request_projection(request))
            return original_fit(selected, request)
        transport.count_input_tokens, transport.cloud_request_fits = count, fits
        return original_runner(resolver=resolver, transport=transport)
    monkeypatch.setattr(app, "BoundModelChatRunner", runner)

    answer = ("artifact_kind: lsr\n\n"
        "| source_row | row_role | title | unit | quantity | norm_code | resource_code | evidence_refs |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
        f"| S!R2 | work | Literal A | m | 12 | {NORM_CODE} | — | Q1.H1 |\n"
        f"| S!R3 | work | Literal B | m | 3 | {NORM_CODE_B} | — | Q2.H1 |")
    run = await _run_sheet(tmp_path, monkeypatch, reads=False, distinct_norms=True,
        group_char_budget=7000, final_answer=answer, wire_budget_bytes=300000,
        proof_replies=[
            InferenceResponse(text="", tool_calls=(_native_read("Q1.H1", "proof-A"),), finish_reason="tool_calls", usage={}),
            InferenceResponse(text="", tool_calls=(_native_read("Q2.H1", "proof-B"),), finish_reason="tool_calls", usage={}),
            InferenceResponse(text=answer, tool_calls=(), finish_reason="stop", usage={}),
        ])
    assert len(run.requests) == 5 and not run.responses, "one existing proof round, no extra retry"
    assert getattr(run.requests[0], "tool_choice", None) is None
    normal = run.requests[1]
    assert getattr(normal, "tool_choice", None) is None and len(normal.tools) > 1
    first, second, final = run.requests[2:]
    assert first.tool_choice == second.tool_choice == CHOICE
    for request, expected in ((first, ["Q1.H1", "Q2.H1"]), (second, ["Q2.H1"])):
        assert len(request.tools) == 1
        parameters = request.tools[0]["function"]["parameters"]
        assert parameters["required"] == ["evidence_ref"] and parameters["additionalProperties"] is False
        assert parameters["properties"]["evidence_ref"]["enum"] == expected
    assert final.tool_choice is None and final.tools == normal.tools
    assert attempted == [{"evidence_ref": "Q1.H1"}, {"evidence_ref": "Q2.H1"}]
    assert {m.get("tool_call_id") for m in final.messages if m.get("role") == "tool"} == {"proof-A", "proof-B"}
    assert json.dumps(answer, ensure_ascii=False) in "\n".join(
        str(message.get("content") or "") for message in final.messages
    ), "restore the complete original answer in the serialized source context"
    for request in (first, second, final):
        dispatched = _request_projection(request)
        assert dispatched in counted, "count callback must receive the identical tools/choice/messages/output policy"
        assert dispatched in cloud_checked, "cloud admission must receive the identical tools/choice/messages/output policy"
    trace = run.result["retrieval_trace"]
    proof_record = trace["norm_card_proof_requests"]
    assert len(proof_record) == 1 and proof_record[0]["model_reads_after_request"] == 2
    assert proof_record[0]["read_statuses"] == ["missing", "ok"]
    job = WorkbookResearchJobService().get(trace["workbook_research_job"]["job_id"])
    assert [(row["source_row"], row["row_role"], row["norm_code"], row["quantity"]) for row in job["accepted_rows"]] == [
        ("S!R2", "work", NORM_CODE, 12), ("S!R3", "work", NORM_CODE_B, 3)]
    assert job["accepted_rows"][0]["_evidence_check"]["card_body_shown"] is False
    assert job["accepted_rows"][1]["_evidence_check"]["card_body_shown"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("counter_unavailable", [False, True])
async def test_forced_choice_reserves_conservative_capacity_without_an_actual_counter(counter_unavailable):
    """A fitting required frame cannot hide the additional provider choice bytes."""
    preset = app.ModelExecutionPreset("proof-edge", "fixture", 20_000, 100, 0,
                                     1, 6, 6, 1, False, ("test",))
    context = dict(profile_prefix="literal profile", request_payload="literal question",
                   source_context=["whole original source"], chunks=[],
                   native_tools=model_evidence_read_tool_schemas())
    async def unavailable(messages):
        return None
    counter = unavailable if counter_unavailable else None
    _, packet, _, _ = await app.govern_model_read_messages_bound(
        count_messages=counter, preset=preset, **context)
    # Set the actual input boundary from the ordinary frame, without duplicating
    # the Governor's object/separator estimate in the test.
    edge = replace(preset, input_token_limit=preset.input_token_limit -
                   (packet.input_budget_tokens - packet.included_tokens))
    _, fitting, _, _ = await app.govern_model_read_messages_bound(
        count_messages=counter, preset=edge, **context)
    assert fitting.included_tokens == fitting.input_budget_tokens
    with pytest.raises(app.ContextRequiredSectionOverflow):
        await app.govern_model_read_messages_bound(
            count_messages=counter, preset=edge, tool_choice=CHOICE, **context)


@pytest.mark.asyncio
async def test_exact_whole_wire_counter_does_not_reserve_choice_twice():
    async def count(messages):
        return SimpleNamespace(tokens=600, source="bound-tokenizer", model_id="actual-model",
                               connection_revision_id="conn:r8", wire_sha256="a" * 64)
    _, packet, _, _ = await app.govern_model_read_messages_bound(
        count_messages=count,
        preset=app.ModelExecutionPreset("proof-count", "fixture", 1000, 100, 0,
                                       1, 6, 6, 1, False, ("test",)),
        profile_prefix="literal profile", request_payload="literal question",
        source_context=["whole source"], chunks=[],
        native_tools=model_evidence_read_tool_schemas(), tool_choice=CHOICE)
    assert packet.input_budget_tokens == 900 and packet.included_tokens == 600
    assert packet.provider_payload_tokens == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("native_chat", [False, True])
async def test_ignored_choice_or_unsupported_protocol_keeps_literal_unread_rows(tmp_path, monkeypatch, native_chat):
    if native_chat:
        original_runner = app.BoundModelChatRunner
        def runner(*, resolver, transport):
            resolve = resolver.resolve
            def native_connection(*args, **kwargs):
                connection = resolve(*args, **kwargs)
                connection.capability_snapshot = SimpleNamespace(
                    transport_options={"chat_protocol": "native_chat_v1"})
                return connection
            resolver.resolve = native_connection
            return original_runner(resolver=resolver, transport=transport)
        monkeypatch.setattr(app, "BoundModelChatRunner", runner)
    run = await _run_sheet(tmp_path, monkeypatch, reads=False, distinct_norms=True,
        group_char_budget=7000, final_answer=SECOND_NORM_ANSWER,
        proof_replies=[InferenceResponse(text=SECOND_NORM_ANSWER, tool_calls=(),
                                        finish_reason="stop", usage={})])
    assert len(run.requests) == 3 and not run.responses and not run.exact_reads
    initial, final = run.requests[1:]
    if native_chat:
        assert final.tool_choice is None and final.tools == initial.tools
    else:
        assert final.tool_choice == CHOICE and len(final.tools) == 1
    trace = run.result["retrieval_trace"]
    requested = trace["norm_card_native_read_contracts"][0]
    assert requested["status"] == ("unsupported_native_chat_protocol" if native_chat else "requested")
    actual = next(call for call in trace["actual_model_calls"]["calls"]
                  if call["purpose"] == proof.PROOF_PURPOSE)
    assert actual["finish_reason"] == "stop" and actual["native_tool_call_identities"] == []
    assert actual["canonical_native_tools"].get("requested_tool_choice") == (None if native_chat else CHOICE)
    record = trace["norm_card_proof_requests"][0]
    assert record["model_reads_after_request"] == 0 and record["read_statuses"] == []
    job = WorkbookResearchJobService().get(trace["workbook_research_job"]["job_id"])
    assert [(row["source_row"], row["norm_code"], row["quantity"]) for row in job["accepted_rows"]] == [
        ("S!R2", NORM_CODE_B, 12), ("S!R3", NORM_CODE_B, 3)]
    assert all(row["_evidence_check"]["card_body_shown"] is False for row in job["accepted_rows"])
