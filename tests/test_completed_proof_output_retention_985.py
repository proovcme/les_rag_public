"""A completed unreadable proof is retained without replacing the earlier draft."""
from copy import deepcopy

import pytest
from openpyxl import load_workbook

from proxy.services import chat_evidence_application_service as app
from proxy.services.openai_compatible_transport_service import InferenceResponse
from proxy.services.workbook_research_job_service import WorkbookResearchJobService
from tests.test_model_rag_sheet_evidence_reads import (
    NORM_CODE, NORM_CODE_B, RESOURCE_A, _native, _run_sheet,
)
from tests.test_norm_card_proof_request_930 import SECOND_NORM_ANSWER
from tests.test_sheet_proof_context_admission_967 import WORK_ANSWER, _group_book


CODE = "MODEL_PROOF_RESULT_UNPARSED"
RAW = ('Проверка завершена.\r\nБуквальное пояснение «Ω»: цены прочитаны, '
       'но таблица не передана.\n  Не меняйте ранее выбранные строки.  ')
PACKET = ["S!R2", "S!R3"]


def _new_diagnostics(items):
    return [item for item in (items or ()) if item.get("code") == CODE]


def test_completed_unparsed_proof_retains_literal_output_and_scope_in_existing_diagnostic():
    previous = [{"source_row": "S!R2", "row_role": "work", "operation_id": "owned-operation",
                 "title": "Literal prior work", "unit": "m", "quantity": 12,
                 "norm_code": NORM_CODE, "evidence_refs": ["Q1.H1"]}]
    frozen = deepcopy(previous)
    diagnostics = []
    issued = {"proof_op_literal": {"source_row": "S!R2", "operation_id_present": False,
                                   "original_operation_id": None}}
    frozen_issued = deepcopy(issued)

    rows, parsed = app.rows_after_proof_round(
        parsed_rows=[], previous_rows=previous, chunks=[], diagnostics=diagnostics,
        authored_answer=RAW, purpose="sheet_pass_resource_group_proof", finish_reason="stop",
        packet_id="owned-proof-packet", packet_locators=PACKET, answer_complete=True,
        proof_operation_identities=issued,
    )

    assert parsed is False and rows == previous == frozen
    diagnostic, = _new_diagnostics(diagnostics)
    assert diagnostic["reason"] == "completed_proof_result_unparsed"
    assert diagnostic["raw_answer"] == RAW
    assert diagnostic["purpose"] == "sheet_pass_resource_group_proof"
    assert diagnostic["finish_reason"] == "stop"
    assert diagnostic["packet_id"] == "owned-proof-packet"
    assert diagnostic["packet_locators"] == PACKET
    assert diagnostic["proof_operation_identities"] == issued == frozen_issued
    assert diagnostic["proof_operation_identities"] is not issued
    assert "proposal" not in diagnostic, "unreadable prose must not become an invented row"


@pytest.mark.parametrize("text,finish_reason,complete", [
    ("", "stop", True),
    (" \r\n\t", "stop", True),
    (RAW, "length", False),
    (RAW, "tool_calls", False),
    (RAW, "function_call", False),
    (RAW, "length", True),
    (RAW, "tool_calls", True),
    (RAW, "function_call", True),
    (RAW, "stop", False),  # completed text is not established after read/context failure
])
def test_nonfinal_proof_does_not_invent_a_completed_output_failure(text, finish_reason, complete):
    previous = [{"source_row": "S!R2", "row_role": "work", "norm_code": NORM_CODE}]
    diagnostics = []
    rows, parsed = app.rows_after_proof_round(
        parsed_rows=[], previous_rows=previous, chunks=[], diagnostics=diagnostics,
        authored_answer=text, purpose="sheet_pass_norm_proof", finish_reason=finish_reason,
        packet_id="owned-proof-packet", packet_locators=PACKET, answer_complete=complete,
    )
    assert parsed is False and rows == previous
    assert _new_diagnostics(diagnostics) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,purpose,expected_calls,norm,refs", [
    ("norm", "sheet_pass_norm_proof", 3, NORM_CODE_B, ["Q2.H1"]),
    ("resource_group", "sheet_pass_resource_group_proof", 5, NORM_CODE, ["Q3.H1"]),
])
async def test_actual_completed_unparsed_proof_is_durable_pending_and_keeps_the_draft(
        tmp_path, monkeypatch, kind, purpose, expected_calls, norm, refs):
    is_group = kind == "resource_group"
    if is_group:
        _group_book(monkeypatch)
    prior_answer = WORK_ANSWER if is_group else SECOND_NORM_ANSWER
    run = await _run_sheet(
        tmp_path, monkeypatch, reads=is_group, distinct_norms=not is_group,
        group_char_budget=None if is_group else 7000, final_answer=prior_answer,
        proof_replies=[InferenceResponse(text=RAW, tool_calls=(), finish_reason="stop", usage={})],
    )

    trace = run.result["retrieval_trace"]
    diagnostics = _new_diagnostics(trace.get("model_result_transport_diagnostics"))
    diagnostic, = diagnostics
    assert diagnostic["raw_answer"] == RAW
    assert diagnostic["purpose"] == purpose and diagnostic["finish_reason"] == "stop"
    assert diagnostic["packet_locators"] == PACKET and diagnostic["packet_id"]
    assert len(run.requests) == expected_calls and not run.responses
    assert len([call for call in trace["actual_model_calls"]["calls"]
                if call["purpose"] == purpose]) == 1
    assert run.queries == ["S!R2 — Cable A", "S!R3 — Cable B"]
    frame, = [frame for frame in trace["context_governor"]["calls"] if frame["purpose"] == purpose]
    proof_context, = [obj["payload"]["proof_operation_identity"]
                      for section in frame["sections"] for obj in section.get("objects", ())
                      if isinstance(obj.get("payload"), dict)
                      and "proof_operation_identity" in obj["payload"]]
    issued = diagnostic["proof_operation_identities"]
    assert set(issued) == {operation["operation_id"] for operation in proof_context["operations"]}
    assert len(issued) == 2
    for operation in proof_context["operations"]:
        assert issued[operation["operation_id"]]["source_row"] == operation["source_row"]
    assert "query_hits" not in diagnostic and "native_exchanges" not in diagnostic

    store = WorkbookResearchJobService()
    job = store.get(trace["workbook_research_job"]["job_id"])
    assert job["status"] == "paused" and job["resumable"] is True
    assert set(job["remaining"]) == set(PACKET)
    expected = [("S!R2", "work", "Cable A", "m", "12", norm, refs),
                ("S!R3", "work", "Cable B", "m", "3", norm, refs)]
    assert [(row["source_row"], row["row_role"], row["title"], row["unit"], str(row["quantity"]),
             row["norm_code"], row["evidence_refs"]) for row in job["accepted_rows"]] == expected
    assert len({row["operation_id"] for row in job["accepted_rows"]}) == 2
    assert all(row["revision"] == 1 for row in job["accepted_rows"])
    assert all(not row.get("resource_bindings") for row in job["accepted_rows"])

    held = job["held_packet"]
    assert held["model_result_transport_pending"] is True
    assert not held.get("terminal_model_result_saved")
    pending, = held["pending_model_result_packets"]
    assert pending["model_result_transport_pending"] is True
    assert pending["locators"] == PACKET
    assert _new_diagnostics(pending["transport_diagnostics"]) == diagnostics
    projected, projected_diagnostics = app.model_rag_pending_result_projection([pending])
    assert projected == set(PACKET) and _new_diagnostics(projected_diagnostics) == diagnostics
    proposal, = _new_diagnostics(job["unapplied_proposals"])
    assert proposal["raw_answer"] == RAW and proposal["proposal_id"]
    assert proposal["packet_id"] == diagnostic["packet_id"]
    assert proposal["proof_operation_identities"] == issued

    # Reopening the store is the persistence boundary; no model call/replay is performed.
    reopened = WorkbookResearchJobService(store.db_path).get(job["job_id"])
    assert reopened["accepted_rows"] == job["accepted_rows"]
    assert reopened["held_packet"] == held
    assert reopened["unapplied_proposals"] == job["unapplied_proposals"]
    events = [event for event in store.events_after(job["job_id"])
              if event["event"] == "unapplied_model_proposals"]
    event, = events
    assert event["data"]["packet_locators"] == PACKET
    saved, = _new_diagnostics(event["data"]["proposals"])
    assert saved["raw_answer"] == RAW and saved["purpose"] == purpose
    assert saved["proof_operation_identities"] == issued

    assert len(run.executions) == 1, "the unchanged saved draft still has one packaging call"
    call, payload = run.executions[0]
    assert call["args"]["decisions"] == job["accepted_rows"]
    assert call["args"]["draft"] is True and payload["artifact"]["draft"] is True
    readiness = run.result["artifact"]["result_readiness"]
    assert readiness["technical_complete"] is False
    assert readiness["estimate_complete"] is False
    assert trace["model_result"]["status"] == "structural_error"
    assert prior_answer.rstrip() in run.result["answer"]
    assert any(issue["code"] == CODE for issue in payload["document_issues"])
    output, = tmp_path.rglob(payload["artifact"]["filename"])
    book = load_workbook(output, data_only=False)
    try:
        visible = "\n".join(str(cell.value) for sheet in book for row in sheet
                            for cell in row if cell.value is not None)
        assert "РАСЧЁТ НЕ ЗАВЕРШЁН" in visible and CODE in visible
        assert all(locator in visible for locator in PACKET)
    finally:
        book.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("text,finish_reason,native_calls", [
    ("", "stop", ()),
    (RAW, "length", ()),
    (RAW, "tool_calls", (_native("not_a_reader", code=RESOURCE_A),)),
])
async def test_actual_nonfinal_or_empty_proof_is_not_a_new_completed_output_failure(
        tmp_path, monkeypatch, text, finish_reason, native_calls):
    run = await _run_sheet(
        tmp_path, monkeypatch, reads=False, distinct_norms=True, group_char_budget=7000,
        final_answer=SECOND_NORM_ANSWER,
        proof_replies=[InferenceResponse(text=text, tool_calls=native_calls,
                                         finish_reason=finish_reason, usage={})],
    )
    trace = run.result["retrieval_trace"]
    assert len(run.requests) == 3 and not run.responses
    assert _new_diagnostics(trace.get("model_result_transport_diagnostics")) == []
    job = WorkbookResearchJobService().get(trace["workbook_research_job"]["job_id"])
    assert _new_diagnostics(job["unapplied_proposals"]) == []


@pytest.mark.asyncio
async def test_undispatched_context_overflow_is_not_a_completed_unparsed_proof(tmp_path, monkeypatch):
    # The established proof-overflow fixture: failure precedes dispatch, not parsing.
    answer = SECOND_NORM_ANSWER + "\n\n" + "literal previous-answer context " * 400
    run = await _run_sheet(
        tmp_path, monkeypatch, reads=False, distinct_norms=True, group_char_budget=7000,
        input_token_limit=24_000, final_answer=answer,
        proof_replies=[InferenceResponse(text=RAW, tool_calls=(), finish_reason="stop", usage={})],
    )
    trace = run.result["retrieval_trace"]
    assert len(run.requests) == 2 and len(run.responses) == 1
    assert trace["proof_context_failure"]["purpose"] == "sheet_pass_norm_proof"
    assert trace["context_governor"]["error"]["code"] == "CONTEXT_REQUIRED_SECTION_OVERFLOW"
    assert _new_diagnostics(trace.get("model_result_transport_diagnostics")) == []
    job = WorkbookResearchJobService().get(trace["workbook_research_job"]["job_id"])
    assert _new_diagnostics(job["unapplied_proposals"]) == []
