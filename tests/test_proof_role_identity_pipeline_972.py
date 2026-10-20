"""A proof identity proposal stays pending through the ordinary sheet pipeline."""

import json

import pytest

from proxy.services.openai_compatible_transport_service import InferenceResponse
from proxy.services.workbook_research_job_service import WorkbookResearchJobService
from tests.test_model_rag_sheet_evidence_reads import NORM_CODE_B, _run_sheet
from tests.test_norm_card_proof_request_930 import SECOND_NORM_ANSWER


@pytest.mark.asyncio
async def test_unaddressed_proof_role_change_preserves_work_and_durable_technical_pending(
        tmp_path, monkeypatch):
    # The first completed answer has two works and no application operation IDs.
    # A real norm-proof turn returns a different role without addressing either
    # operation. Only the provider responses are mocked; merge, store and visible
    # pending diagnostics use the ordinary sheet pipeline.
    proposed = {
        "source_row": "S!R2", "row_role": "unresolved", "title": "Literal changed-role proposal",
        "unit": "m", "quantity": 0, "norm_code": "", "resource_code": "",
        "evidence_refs": [], "coverage": "Literal proof explanation without an operation address",
    }
    proof_raw = json.dumps({"artifact_kind": "lsr", "rows": [proposed]}, ensure_ascii=False)
    run = await _run_sheet(
        tmp_path, monkeypatch, reads=False, group_char_budget=7000,
        distinct_norms=True, final_answer=SECOND_NORM_ANSWER,
        proof_replies=[InferenceResponse(text=proof_raw, tool_calls=(), finish_reason="stop", usage={})],
    )

    trace = run.result["retrieval_trace"]
    proof = trace["norm_card_proof_requests"][0]
    assert proof["answer_parsed"] is False and proof["model_reads_after_request"] == 0
    assert len(run.requests) == 3 and not run.responses
    diagnostics = trace["model_result_transport_diagnostics"]
    assert len(diagnostics) == 1
    diagnostic = diagnostics[0]
    assert diagnostic["code"] == "MODEL_PROOF_UPDATE_IDENTITY_AMBIGUOUS"
    assert diagnostic["source_row"] == "S!R2" and diagnostic["operation_id"] == ""
    assert diagnostic["proposal"] == proposed and diagnostic["raw_answer"] == proof_raw

    state = trace["workbook_research_job"]
    store = WorkbookResearchJobService()
    job = store.get(state["job_id"])
    assert state["status"] == job["status"] == "paused" and state["resumable"] is True
    assert job["status_dimensions"]["completeness"] == "partial" and "S!R2" in job["remaining"]
    assert len(job["accepted_rows"]) == 2, "the role proposal must not add a duplicate operation"
    assert [(row["source_row"], row["row_role"], row["title"], str(row["quantity"]), row["norm_code"])
            for row in job["accepted_rows"]] == [
        ("S!R2", "work", "Cable A", "12", NORM_CODE_B),
        ("S!R3", "work", "Cable B", "3", NORM_CODE_B),
    ]
    assert len({row["operation_id"] for row in job["accepted_rows"]}) == 2
    saved_proposals = job["unapplied_proposals"]
    assert len(saved_proposals) == 1
    assert saved_proposals[0]["proposal"] == proposed and saved_proposals[0]["raw_answer"] == proof_raw
    assert saved_proposals[0]["code"] == diagnostic["code"] and saved_proposals[0]["proposal_id"]

    held = job["held_packet"]
    assert held["model_result_transport_pending"] is True and not held.get("terminal_model_result_saved")
    pending = held["pending_model_result_packets"]
    assert len(pending) == 1 and pending[0]["model_result_transport_pending"] is True
    assert pending[0]["transport_diagnostics"] == diagnostics and "S!R2" in pending[0]["locators"]
    assert "технические ошибки передачи решения модели" in run.result["answer"]
    assert "неприменённые предложения" in run.result["answer"]

    # A fresh store instance and the durable event retain the literal proposal;
    # neither diagnostics nor restart turn it into an accepted operation.
    reopened = WorkbookResearchJobService(store.db_path).get(job["job_id"])
    assert reopened["accepted_rows"] == job["accepted_rows"]
    assert reopened["unapplied_proposals"] == saved_proposals and reopened["held_packet"] == held
    events = [event for event in store.events_after(job["job_id"])
              if event["event"] == "unapplied_model_proposals"]
    assert len(events) == 1 and events[0]["data"]["proposals"] == saved_proposals
