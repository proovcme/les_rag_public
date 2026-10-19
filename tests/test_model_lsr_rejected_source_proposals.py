"""Parsed source conflicts remain durable proposals rather than disappearing."""
from __future__ import annotations

import copy
from dataclasses import replace
import inspect
import json

import pytest

from proxy.services import chat_evidence_application_service as app
from proxy.services.workbook_research_job_service import WorkbookResearchJobService
from proxy.services.openai_compatible_transport_service import InferenceResponse
from tests.test_model_rag_sheet_evidence_reads import _run_sheet


def _rows(*, mixed=False):
    return [
        {"source_row": "S!R2", "row_role": "work", "title": "Authored derived operation A",
         "unit": "m2", "quantity": 15.71, "norm_code": "MISSING", "evidence_refs": [],
         "open_gap": "Literal model question A", "coverage": "Literal proposed derivation A"},
        {"source_row": "S!R3", "row_role": "work", "title": "Authored derived operation B",
         "unit": "m" if mixed else "m2", "quantity": 3 if mixed else 2.51,
         "norm_code": "MISSING", "evidence_refs": [], "open_gap": "Literal model question B"},
    ]


def _text(rows):
    return "Literal accompanying explanation.\n```json\n" + json.dumps(
        {"artifact_kind": "lsr", "rows": rows}, ensure_ascii=False) + "\n```"


@pytest.mark.asyncio
@pytest.mark.parametrize("mixed", [False, True])
async def test_source_rejections_are_saved_and_reported_without_rewriting_or_inference(tmp_path, monkeypatch, mixed):
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "jobs.sqlite"))
    authored = _rows(mixed=mixed)
    before = copy.deepcopy(authored)
    run = await _run_sheet(tmp_path, monkeypatch, reads=False, final_answer=_text(authored))
    trace = run.result["retrieval_trace"]
    store = WorkbookResearchJobService()
    job = store.get(trace["workbook_research_job"]["job_id"])
    proposals = job["unapplied_proposals"]
    assert len(proposals) == (1 if mixed else 2)
    for proposal, original in zip(proposals, before[:1 if mixed else 2], strict=True):
        assert {key: proposal["decision"][key] for key in original} == original
    assert all(item["code"] == "MODEL_RESULT_SOURCE_CONFLICT" for item in proposals)
    assert "source_quantity_mismatch:S!R2" in proposals[0]["errors"]
    assert "source_unit_mismatch:S!R2" in proposals[0]["errors"]
    assert job["status"] == "paused" and job["resumable"] is True
    assert "S!R2" in job["remaining"]
    assert job["held_packet"].get("terminal_model_result_saved") is not True
    assert len(run.requests) == 2 and not run.responses
    assert authored == before
    assert "source_quantity_mismatch:S!R2" in str(trace["model_result"])
    assert "таблица строк не получена" not in run.result["answer"]
    if mixed:
        assert [row["source_row"] for row in job["accepted_rows"]] == ["S!R3"]
        assert job["accepted_rows"][0]["quantity"] == 3
        assert len(run.executions) == 1
        call, exported = run.executions[0]
        assert [row["source_row"] for row in call["args"]["decisions"]] == ["S!R3"]
        assert call["args"]["draft"] is True
        assert exported["confirmed_amount"] == 0
        assert any(issue["code"] == "MODEL_PROPOSAL_UNAPPLIED"
                   and issue["proposal"]["decision"] == proposals[0]["decision"]
                   for issue in exported["document_issues"])
    else:
        assert job["accepted_rows"] == [] and run.executions == []
        assert trace["model_result"]["status"] == "structural_error"
        assert trace["model_result"]["proposed_row_count"] == 2
        assert trace["model_result"]["errors"] == [
            "source_quantity_mismatch:S!R2", "source_unit_mismatch:S!R2",
            "source_quantity_mismatch:S!R3", "source_unit_mismatch:S!R3"]


def test_source_proposal_projection_preserves_existing_unit_only_admission(tmp_path):
    from tests.test_model_vor_quantity_preservation import _catalog

    catalog = _catalog(tmp_path)
    row = {"source_row": "S!R2", "row_role": "work", "title": "Literal model decision",
           "quantity": 8, "unit": "m", "norm_code": "MISSING", "open_gap": "Unresolved unit"}
    errors = ["source_unit_mismatch:S!R2"]
    kept = app.sheet_pass_keep_rows([row], sheet="S", catalog=catalog, errors=errors, artifact_kind="lsr")
    assert kept == [row], "this patch must not broaden the existing quantity guard"
    assert app.sheet_pass_rejected_row_proposals(
        [row], kept_rows=kept, sheet="S", catalog=catalog, errors=errors,
        packet_locators=["S!R2"]) == []


@pytest.mark.parametrize("authored_locator", ["s!r2", 2, "source-file!R2"])
def test_proposal_scope_accepts_only_proven_locator_aliases_without_rewriting(tmp_path, authored_locator):
    from tests.test_model_vor_quantity_preservation import _catalog

    catalog = replace(_catalog(tmp_path), source_file_id="source-file")
    proposal = {"code": "MODEL_RESULT_SOURCE_CONFLICT",
                "decision": {"source_row": authored_locator, "quantity": 192,
                             "title": "Literal authored proposal"}}
    foreign = {"code": "MODEL_RESULT_SOURCE_CONFLICT",
               "decision": {"source_row": "foreign!R2", "quantity": 192}}
    job = {"status": "paused", "unapplied_proposals": [proposal, foreign]}
    before = copy.deepcopy(job)
    assert app.packet_source_conflict_proposals(
        job, catalog=catalog, packet_locators=["S!R2"]) == [proposal]
    assert app.packet_source_conflict_proposals(
        job, catalog=catalog, packet_locators=["S!R3"]) == []
    assert job == before


@pytest.mark.asyncio
async def test_source_guard_keeps_valid_sibling_and_preserves_only_refused_operation(tmp_path, monkeypatch):
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "jobs.sqlite"))
    first, second = _rows(mixed=True)
    same_source = {**first, "title": "Another authored operation on the same source", "quantity": 12, "unit": "m"}
    run = await _run_sheet(tmp_path, monkeypatch, reads=False, final_answer=_text([first, same_source, second]))
    job = WorkbookResearchJobService().get(run.result["retrieval_trace"]["workbook_research_job"]["job_id"])
    assert job["status"] == "paused"
    assert "S!R2" in job["remaining"]
    # The fixture source is S!R2 = 12 m. Its valid second operation must not
    # inherit the first operation's 15.71 m2 mismatch merely by sharing R2.
    assert [row["source_row"] for row in job["accepted_rows"]] == ["S!R2", "S!R3"]
    for accepted, original in zip(job["accepted_rows"], (same_source, second), strict=True):
        assert {key: accepted[key] for key in original} == original
        assert accepted["operation_id"]
    proposals = app.active_source_conflict_proposals(job)
    assert len(proposals) == 1
    assert {key: proposals[0]["decision"][key] for key in first} == first
    assert [item["decision"]["title"] for item in proposals] == [first["title"]]
    assert [item["decision"]["quantity"] for item in proposals] == [15.71]
    assert all("source_quantity_mismatch:S!R2" in item["errors"] for item in proposals)
    assert run.executions[0][0]["args"]["draft"] is True
    assert any(issue["code"] == "MODEL_PROPOSAL_UNAPPLIED" for issue in run.executions[0][1]["document_issues"])
    assert any(issue["code"] == "WORKBOOK_RESEARCH_INCOMPLETE"
               and "S!R2" in issue["remaining_locators"]
               for issue in run.executions[0][1]["document_issues"])


@pytest.mark.asyncio
@pytest.mark.parametrize("locator_spelling", ["canonical", "casefolded"])
async def test_explicit_resume_receives_rejected_decisions_and_keeps_audit_after_model_correction(
    tmp_path, monkeypatch, locator_spelling,
):
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "jobs.sqlite"))
    authored = _rows()
    if locator_spelling == "casefolded":
        for row in authored:
            row["source_row"] = row["source_row"].casefold()
    run = await _run_sheet(tmp_path, monkeypatch, reads=False, final_answer=_text(authored))
    store = WorkbookResearchJobService()
    job_id = run.result["retrieval_trace"]["workbook_research_job"]["job_id"]
    before = store.get(job_id)
    original_proposals = copy.deepcopy(before["unapplied_proposals"])
    request = inspect.getclosurevars(run.resume_same_request).nonlocals["request"]
    request.req.question = "Продолжи это же задание по тому же прикреплённому документу."
    corrected = _rows()
    for row, quantity in zip(corrected, (12, 3), strict=True):
        proposal = next(item for item in original_proposals
                        if str(item["decision"]["source_row"]).casefold() == row["source_row"].casefold())
        row.update(quantity=quantity, unit="m", resolves_proposal_id=proposal["proposal_id"])
    run.responses.extend([
        InferenceResponse(text=json.dumps({"artifact_kind": "lsr", "queries": [
            "S!R2 — Cable A", "S!R3 — Cable B"]}), tool_calls=(), finish_reason="stop", usage={}),
        InferenceResponse(text=_text(corrected), tool_calls=(), finish_reason="stop", usage={}),
    ])
    request_count = len(run.requests)
    resumed = await run.resume_same_request()
    new_requests = run.requests[request_count:]
    checkpoint_frames = []
    for inference in new_requests:
        for message in inference.messages:
            for line in str(message.get("content") or "").splitlines():
                try:
                    decoded = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(decoded, dict) and decoded.get("unapplied_model_proposals"):
                    checkpoint_frames.append(decoded)
    assert checkpoint_frames, "a resume must deliver the rejected authored rows and reasons to the same model"
    assert all(frame["source_conflict_origin"] == "application" for frame in checkpoint_frames)
    shown = checkpoint_frames[-1]["unapplied_model_proposals"]
    assert shown == original_proposals
    assert all(row["quantity"] not in (15.71, 2.51)
               for frame in checkpoint_frames for row in frame["prior_model_decisions"])
    after = store.get(resumed["retrieval_trace"]["workbook_research_job"]["job_id"])
    assert after["status"] == "complete" and after["remaining"] == []
    assert after["unapplied_proposals"] == original_proposals
    assert [(row["source_row"], row["quantity"], row["unit"]) for row in after["accepted_rows"]] == [
        ("S!R2", 12, "m"), ("S!R3", 3, "m")]
    assert app.active_source_conflict_proposals(after) == []
    assert len(new_requests) == 2 and run.responses == []
    assert resumed["retrieval_trace"]["model_result"]["packaged"] is True
    assert not any(issue["code"] == "MODEL_PROPOSAL_UNAPPLIED"
                   for issue in resumed["document_issues"])
