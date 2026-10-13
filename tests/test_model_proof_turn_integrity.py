"""Proof replies update named decisions without losing the rest of a packet."""
import json

import pytest

from proxy.services import chat_evidence_application_service as service
from proxy.services.openai_compatible_transport_service import InferenceResponse
from tests.test_model_rag_sheet_evidence_reads import _native, _run_sheet
from tests.test_norm_card_proof_request_930 import SECOND_NORM_ANSWER


def test_partial_proof_reply_preserves_unmentioned_source_decisions():
    previous = [
        {"source_row": "Other!R7", "row_role": "work", "quantity": 4, "title": "A"},
        {"source_row": "Other!R19", "row_role": "work", "quantity": 6, "title": "B"},
    ]
    changed = dict(previous[0], quantity=9)
    rows, parsed = service.rows_after_proof_round(
        parsed_rows=[changed], previous_rows=previous, chunks=[])
    assert parsed
    assert [(r["source_row"], r["quantity"]) for r in rows] == [("Other!R7", 9), ("Other!R19", 6)]
    assert previous[0]["quantity"] == 4


def test_partial_proof_reply_preserves_other_operations_on_same_source():
    previous = [
        {"source_row": "S!R2", "row_role": "work", "operation_id": "op_a", "quantity": 2},
        {"source_row": "S!R2", "row_role": "work", "operation_id": "op_b", "quantity": 3},
    ]
    rows, parsed = service.rows_after_proof_round(
        parsed_rows=[dict(previous[0], quantity=7)], previous_rows=previous, chunks=[])
    assert parsed
    assert [(r["operation_id"], r["quantity"]) for r in rows] == [("op_a", 7), ("op_b", 3)]


def test_proof_update_without_identity_does_not_choose_between_operations():
    previous = [
        {"source_row": "S!R2", "row_role": "work", "operation_id": "op_a", "quantity": 2},
        {"source_row": "S!R2", "row_role": "work", "operation_id": "op_b", "quantity": 3},
    ]
    diagnostics = []
    rows, parsed = service.rows_after_proof_round(
        parsed_rows=[{"source_row": "S!R2", "row_role": "work", "quantity": 7}],
        previous_rows=previous, chunks=[], diagnostics=diagnostics, authored_answer="literal ambiguous reply")
    assert not parsed
    assert rows == previous
    assert diagnostics[0]["proposal"]["quantity"] == 7
    assert diagnostics[0]["raw_answer"] == "literal ambiguous reply"


def test_unique_source_role_update_preserves_application_identity_revision():
    previous = [{"source_row": "S!R2", "row_role": "work", "operation_id": "op_a",
                 "revision": 3, "revision_origin": "model", "quantity": 2}]
    rows, parsed = service.rows_after_proof_round(
        parsed_rows=[{"source_row": "S!R2", "row_role": "work", "quantity": 7}],
        previous_rows=previous, chunks=[])
    assert parsed and rows[0]["quantity"] == 7
    assert rows[0]["operation_id"] == "op_a"
    assert rows[0]["revision"] == 3


def test_duplicate_new_operation_is_a_preserved_conflicting_proposal():
    diagnostics = []
    rows, parsed = service.rows_after_proof_round(
        parsed_rows=[{"source_row": "S!R8", "row_role": "work", "operation_id": "new", "quantity": 2},
                     {"source_row": "S!R8", "row_role": "work", "operation_id": "new", "quantity": 9}],
        previous_rows=[], chunks=[], diagnostics=diagnostics, authored_answer="both authored rows")
    assert parsed and len(rows) == 1 and rows[0]["quantity"] == 2
    assert diagnostics[0]["proposal"]["quantity"] == 9
    assert diagnostics[0]["code"] == "MODEL_PROOF_UPDATE_IDENTITY_AMBIGUOUS"


@pytest.mark.asyncio
async def test_native_read_continuation_retains_proof_question_and_prior_table(tmp_path, monkeypatch):
    run = await _run_sheet(
        tmp_path, monkeypatch, reads=False, group_char_budget=7000,
        distinct_norms=True, final_answer=SECOND_NORM_ANSWER,
        proof_replies=[
            InferenceResponse(text="", tool_calls=(_native("read_norm_card", evidence_ref="Q2.H1"),),
                              finish_reason="tool_calls", usage={}),
            InferenceResponse(text=SECOND_NORM_ANSWER, tool_calls=(), finish_reason="stop", usage={}),
        ])
    question = str(run.requests[2].messages[-1]["content"])
    continuation = "\n".join(str(m["content"]) for m in run.requests[3].messages)
    assert question.splitlines()[0] in continuation
    assert "| S!R3 | work |" in continuation
    assert run.exact_reads
    assert not run.responses
