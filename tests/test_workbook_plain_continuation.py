"""Explicit user resume can reach omitted source rows without reopening decisions."""
import inspect
import json

import pytest
import test_model_rag_sheet_evidence_reads as sheet_fixture

from proxy.services.workbook_research_job_service import WorkbookResearchJobService
from test_model_rag_sheet_evidence_reads import _run_sheet


def _assert_inherited_price_basis(child, parent):
    child_basis = child["task_context"]["price_basis"]
    parent_basis = parent["task_context"]["price_basis"]
    assert {key:value for key,value in child_basis.items() if key != "inherited_from"} == {
        key:value for key,value in parent_basis.items() if key != "inherited_from"}
    assert child_basis["inherited_from"] in {
        parent["document"]["final_revision_id"], parent["document"]["draft_revision_id"]}


@pytest.mark.asyncio
async def test_new_plain_request_reaches_only_source_without_an_accepted_decision(tmp_path, monkeypatch):
    run = await _run_sheet(tmp_path, monkeypatch, reads=True, partial_final=True)
    store = WorkbookResearchJobService()
    parent = store.get(run.result["retrieval_trace"]["workbook_research_job"]["job_id"])
    assert parent["remaining"] == ["S!R3"]
    assert [row["source_row"] for row in parent["accepted_rows"]] == ["S!R2"]
    assert store.terminal_packet_locators(parent["held_packet"]) == {"S!R2", "S!R3"}
    assert len(run.requests) == 4 and not run.responses
    # Idempotent replay of the original task remains model-free.
    await run.resume_same_request()
    assert len(run.requests) == 4
    request = inspect.getclosurevars(run.resume_same_request).nonlocals["request"]
    request.req.question = "Продолжи"
    before = len(run.requests)
    result = await run.corrected_source_row("S!R3")
    assert len(run.requests) == before + 4 and not run.responses
    first = run.requests[before]
    source_context = str(first.messages)
    assert "S!R3" in source_context
    passes = result["retrieval_trace"]["tool_loop"]["passes"]
    assert [packet["packet_locators"] for packet in passes] == [["S!R3"]]
    child = store.get(result["retrieval_trace"]["workbook_research_job"]["job_id"])
    assert child["continues_job_id"] == parent["job_id"]
    kept = [row for row in child["accepted_rows"] if row["source_row"] == "S!R2"]
    assert kept == parent["accepted_rows"]
    _assert_inherited_price_basis(child, parent)
    assert child["remaining"] == []
    assert "chat_refinement" not in result["retrieval_trace"]


@pytest.mark.asyncio
async def test_plain_request_preserves_settled_missing_norm_decisions_without_inference(tmp_path, monkeypatch):
    authored_rows = [{"source_row":locator, "row_role":"work", "title":title, "unit":"m",
                      "quantity":quantity, "norm_code":"", "norm_status":"MISSING",
                      "open_gap":"no_suitable_candidate", "evidence_refs":[]}
                     for locator,title,quantity in (("S!R2", "Cable A", 12), ("S!R3", "Cable B", 3))]
    monkeypatch.setattr(sheet_fixture, "_answer", lambda **_kwargs: json.dumps({"artifact_kind":"lsr", "rows":authored_rows}))
    run = await _run_sheet(tmp_path, monkeypatch, reads=False)
    store = WorkbookResearchJobService()
    parent = store.get(run.result["retrieval_trace"]["workbook_research_job"]["job_id"])
    assert parent["remaining"] == []
    assert all(row["norm_status"] == "MISSING" for row in parent["accepted_rows"])
    request = inspect.getclosurevars(run.resume_same_request).nonlocals["request"]
    request.req.question = "Продолжи"
    before = len(run.requests)
    result = await run.resume_same_request()
    assert len(run.requests) == before and not run.responses
    child = store.get(result["retrieval_trace"]["workbook_research_job"]["job_id"])
    assert child["continues_job_id"] == parent["job_id"]
    assert child["accepted_rows"] == parent["accepted_rows"]
    assert child["remaining"] == []
    _assert_inherited_price_basis(child, parent)
    assert "chat_refinement" not in result["retrieval_trace"]
