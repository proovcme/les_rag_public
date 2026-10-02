"""Actual chat/repack boundaries retain accepted rows without claiming a final document."""
from pathlib import Path

import pytest
from openpyxl import load_workbook

from proxy.routers import chat
from proxy.services.workbook_research_job_service import WorkbookResearchJobService
from proxy.services.chat_evidence_application_service import workbook_document_issues
from test_model_rag_sheet_evidence_reads import _run_sheet


def _assert_draft(payload, readiness, root: Path, raw_line: str):
    assert payload["status"] == "partial"
    assert payload["artifact"]["download_url"]
    assert payload["artifact"]["draft"] is True
    assert payload["pricing_status"] == "priced_partial"
    assert payload["confirmed_amount"] == 0
    assert payload["preliminary_amount"] == 600
    assert payload["calculated_positions"] == 1  # the independent accepted position remains calculated
    assert payload["document_issues"]
    assert readiness["technical_complete"] is False
    assert readiness["estimate_complete"] is False
    assert readiness["document_issues"] == payload["document_issues"]
    paths = list(root.rglob(payload["artifact"]["filename"]))
    assert paths
    workbook = load_workbook(paths[0], data_only=False)
    try:
        text = "\n".join(str(cell.value) for sheet in workbook for row in sheet for cell in row if cell.value is not None)
        assert "РАСЧЁТ НЕ ЗАВЕРШЁН (PRICED_PARTIAL)" in text
        assert "MODEL_RESULT_TABLE_ROW_WIDTH_MISMATCH" in text
        assert "S!R2" in text and raw_line in text
        assert "ИЗВЕСТНАЯ РАССЧИТАННАЯ ЧАСТЬ" in text
    finally:
        workbook.close()


@pytest.mark.asyncio
async def test_application_delivers_accepted_subset_as_technical_draft(tmp_path, monkeypatch):
    run = await _run_sheet(tmp_path, monkeypatch, reads=True, malformed_first_packet=True)
    assert len(run.requests) == 4 and not run.responses
    job = WorkbookResearchJobService().get(run.result["retrieval_trace"]["workbook_research_job"]["job_id"])
    assert job["status"] == "paused" and job["remaining"] == ["S!R2"]
    assert [row["source_row"] for row in job["accepted_rows"]] == ["S!R3"]
    assert len(run.executions) == 1
    call, payload = run.executions[0]
    assert call["args"]["decisions"] == job["accepted_rows"]
    assert "document_issues" not in call["args"]  # trusted execution context only
    _assert_draft(payload, run.result["artifact"]["result_readiness"], tmp_path,
                  job["unapplied_proposals"][0]["decision"]["raw_line"])
    meta = run.result["retrieval_trace"]["model_result"]
    assert meta["status"] == "structural_error" and meta["packaged"] is True


@pytest.mark.asyncio
async def test_repack_does_not_turn_pending_raw_rows_into_final_money(tmp_path, monkeypatch):
    run = await _run_sheet(tmp_path, monkeypatch, reads=True, malformed_first_packet=True)
    store = WorkbookResearchJobService()
    parent = store.get(run.result["retrieval_trace"]["workbook_research_job"]["job_id"])
    calls_before = len(run.requests)
    identity = parent["identity"]
    result = await chat.repack_lsr_without_model(chat.LsrRepackRequest(
        job_id=parent["job_id"], session_id=identity["session_id"], attachment_id=identity["attachment_id"],
        question=parent["task_context"]["original_question"], dataset_ids=identity["dataset_ids"],
        profile_revision_id=identity["profile_revision_id"], model_identity=identity["model_identity"]), _user={})
    assert result["model_called"] is False and len(run.requests) == calls_before
    _assert_draft(result["result"], result["harvested"]["artifact"]["result_readiness"], tmp_path,
                  parent["unapplied_proposals"][0]["decision"]["raw_line"])
    updated = store.get(parent["job_id"])
    for field in ("status", "accepted_rows", "remaining", "unapplied_proposals"):
        assert updated[field] == parent[field]
    replay = await chat.repack_lsr_without_model(chat.LsrRepackRequest(
        job_id=parent["job_id"], session_id=identity["session_id"], attachment_id=identity["attachment_id"],
        question=parent["task_context"]["original_question"], dataset_ids=identity["dataset_ids"],
        profile_revision_id=identity["profile_revision_id"], model_identity=identity["model_identity"]), _user={})
    assert replay["result"]["artifact"]["revision_id"] == result["result"]["artifact"]["revision_id"]
    assert replay["result"]["document_issues"] == result["result"]["document_issues"]
    assert len(run.requests) == calls_before


def test_pending_read_stop_and_raw_proposals_are_visible_until_research_resolves():
    raw = {"code": "MODEL_RESULT_JSON_DUPLICATE_FIELD", "decision": {"raw_json": '{"quantity":1,"quantity":2}'}}
    job = {"status": "paused", "remaining": ["Раздел!R14"], "unapplied_proposals": [raw],
           "held_packet": {"read_stop": "evidence_read_repeat"}}
    issues = workbook_document_issues(job)
    assert issues[0]["remaining_locators"] == ["Раздел!R14"]
    assert issues[1]["proposal"] == raw
    assert issues[2]["reason"] == "evidence_read_repeat"
    job.update(status="complete", remaining=[])
    assert workbook_document_issues(job) == []  # resolved raw history is retained by the job, not an open gap


@pytest.mark.asyncio
async def test_model_tool_arguments_cannot_supply_document_integrity_metadata(tmp_path, monkeypatch):
    run = await _run_sheet(tmp_path, monkeypatch, reads=True, malformed_first_packet=True)
    job = WorkbookResearchJobService().get(run.result["retrieval_trace"]["workbook_research_job"]["job_id"])
    call = {"tool": "build_lsr_workbook", "args": {
        **run.executions[0][0]["args"], "document_issues": [{"code": "model-owned-fake"}]}}
    identity = job["identity"]
    rejected = await chat._execute_chat_workbook_tool(call, {
        "session_id": identity["session_id"], "attachment_id": identity["attachment_id"],
        "dataset_ids": identity["dataset_ids"], "profile_revision_id": identity["profile_revision_id"],
        "model_identity": identity["model_identity"]}, None)
    assert rejected["status"] not in {"complete", "partial"}
    assert not rejected.get("artifact")
    assert len(run.requests) == 4
