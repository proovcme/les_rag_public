"""A material on one source must not conceal its rejected mounting operation."""
from __future__ import annotations

import copy
import inspect
import json

import pytest

from proxy.services import chat_evidence_application_service as app
from proxy.services.openai_compatible_transport_service import InferenceResponse
from proxy.services.workbook_research_job_service import WorkbookResearchJobService
from tests.test_model_rag_sheet_evidence_reads import _run_sheet


def _rows():
    rows = []
    for locator, quantity, area in (("S!R2", 12, 15.71), ("S!R3", 3, 2.51)):
        rows.extend([
            {"source_row": locator, "row_role": "material", "work_row": locator,
             "title": "Literal supplied item " + locator, "unit": "m", "quantity": quantity,
             "norm_code": "", "evidence_refs": [], "open_gap": "Price unresolved"},
            {"source_row": locator, "row_role": "work", "work_row": locator,
             "title": "Literal derived operation " + locator, "unit": "m2", "quantity": area,
             "norm_code": "MISSING", "evidence_refs": [], "open_gap": "Norm unresolved"},
        ])
    return rows


def _answer(rows):
    return json.dumps({"artifact_kind": "lsr", "rows": rows})


def _reply(text):
    return InferenceResponse(text=text, tool_calls=(), finish_reason="stop", usage={})


def _proposals(job):
    return app.active_source_conflict_proposals(job)


@pytest.mark.asyncio
async def test_material_neighbour_keeps_rejected_work_reachable_and_corrections_are_per_proposal(tmp_path, monkeypatch):
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "jobs.sqlite"))
    progress = []
    original_progress_counts = app.sheet_pass_progress_counts
    def measured_progress(**kwargs):
        result = original_progress_counts(**kwargs)
        progress.append(result)
        return result
    monkeypatch.setattr(app, "sheet_pass_progress_counts", measured_progress)
    authored = _rows()
    run = await _run_sheet(tmp_path, monkeypatch, reads=False, final_answer=_answer(authored))
    store = WorkbookResearchJobService()
    first = store.get(run.result["retrieval_trace"]["workbook_research_job"]["job_id"])
    assert first["status"] == "paused" and first["resumable"] is True
    assert first["remaining"] == ["S!R2", "S!R3"], "supplied material cannot close an unapplied work"
    assert [row["row_role"] for row in first["accepted_rows"]] == ["material", "material"]
    assert len(_proposals(first)) == 2 and len(run.requests) == 2 and run.responses == []
    assert {key: progress[-1][key] for key in ("completed", "total", "remaining", "prior_completed")} == {
        "completed": 0, "total": 2, "remaining": 2, "prior_completed": 0}
    original = copy.deepcopy(first["unapplied_proposals"])
    originals_by_source = {proposal["source_row"]: proposal["proposal_id"] for proposal in original}
    materials = copy.deepcopy(first["accepted_rows"])
    request = inspect.getclosurevars(run.resume_same_request).nonlocals["request"]
    request.req.question = "Продолжи это же задание по тому же прикреплённому документу."
    for locator, quantity in (("S!R2", 12), ("S!R3", 3)):
        corrected = next(copy.deepcopy(row) for row in authored
                         if row["source_row"] == locator and row["row_role"] == "work")
        corrected.update(unit="m", quantity=quantity,
                         resolves_proposal_id=originals_by_source[locator])
        run.responses.extend([
            _reply(json.dumps({"artifact_kind": "lsr", "queries": [locator + " literal query"]})),
            _reply(_answer([corrected])),
        ])
        before_requests = len(run.requests)
        resumed = await run.resume_same_request()
        current = store.get(resumed["retrieval_trace"]["workbook_research_job"]["job_id"])
        assert len(run.requests) == before_requests + 2 and run.responses == []
        shown_frames = [message.get("content", "") for inference in run.requests[before_requests:]
                        for message in inference.messages]
        assert any("resolves_proposal_id" in str(content) and originals_by_source[locator] in str(content)
                   for content in shown_frames)
        assert current["unapplied_proposals"] == original, "resolution is a receipt, not a rewrite of the proposal"
        assert [row for row in current["accepted_rows"] if row["row_role"] == "material"] == materials
        resolved = current["task_context"]["resolved_source_conflict_proposal_ids"]
        assert originals_by_source[locator] in resolved
        events = store.list_events_with_lineage(current["job_id"], "source_conflict_proposals_resolved")
        assert events[-1]["payload"]["origin"] == "application"
        assert events[-1]["payload"]["proposal_ids"] == [originals_by_source[locator]]
        if locator == "S!R2":
            assert {key: progress[-1][key] for key in ("completed", "total", "remaining", "prior_completed")} == {
                "completed": 1, "total": 2, "remaining": 1, "prior_completed": 0}
            assert current["status"] == "paused" and current["remaining"] == ["S!R3"]
            assert [proposal["source_row"] for proposal in _proposals(current)] == ["S!R3"]
            assert resolved == [originals_by_source["S!R2"]]
            assert run.executions[-1][0]["args"]["draft"] is True
        else:
            assert {key: progress[-1][key] for key in ("completed", "total", "remaining", "prior_completed")} == {
                "completed": 2, "total": 2, "remaining": 0, "prior_completed": 1}
            assert current["status"] == "complete" and current["remaining"] == []
            assert _proposals(current) == [] and len(current["accepted_rows"]) == 4
            assert set(resolved) == set(originals_by_source.values())
            assert not any(issue["code"] == "MODEL_PROPOSAL_UNAPPLIED" for issue in resumed["document_issues"])


def test_ambiguous_or_other_role_row_never_resolves_a_work_proposal():
    from proxy.services.workbook_research_job_service import source_conflict_resolutions

    decision = {"source_row": "S!R2", "row_role": "work", "quantity": 4, "unit": "m2"}
    proposal = {"proposal_id": "p1", "code": "MODEL_RESULT_SOURCE_CONFLICT", "decision": decision}
    material = {"source_row": "S!R2", "row_role": "material", "quantity": 12, "unit": "m"}
    work = {**decision, "quantity": 12, "unit": "m"}
    assert source_conflict_resolutions([proposal], [material], packet_locators=["S!R2"]) == []
    assert source_conflict_resolutions([proposal], [work], packet_locators=["S!R3"]) == []
    assert source_conflict_resolutions([proposal, {**proposal, "proposal_id": "p2"}], [work],
                                       packet_locators=["S!R2"]) == []
    assert source_conflict_resolutions([proposal], [work, {**work, "title": "Different operation"}],
                                       packet_locators=["S!R2"]) == []
    assert source_conflict_resolutions([proposal], [work], packet_locators=["S!R2"]) == []
    unrelated = {**work, "title": "Different unrelated operation"}
    assert source_conflict_resolutions([proposal], [unrelated], packet_locators=["S!R2"]) == []
    assert source_conflict_resolutions([proposal], [{**work, "resolves_proposal_id": "p1"}],
                                       packet_locators=["S!R2"]) == ["p1"]


@pytest.mark.parametrize("change", [
    {"resolves_proposal_id": "unknown"},
    {"source_row": "S!R3", "resolves_proposal_id": "p1"},
    {"row_role": "material", "resolves_proposal_id": "p1"},
])
def test_proposal_marker_cannot_resolve_unknown_foreign_or_other_role(change):
    from proxy.services.workbook_research_job_service import source_conflict_resolutions

    decision = {"source_row": "S!R2", "row_role": "work", "quantity": 4, "unit": "m2"}
    proposal = {"proposal_id": "p1", "code": "MODEL_RESULT_SOURCE_CONFLICT", "decision": decision}
    correction = {**decision, "quantity": 12, "unit": "m", **change}
    assert source_conflict_resolutions([proposal], [correction], packet_locators=["S!R2", "S!R3"]) == []


def test_explicit_operation_identity_cannot_be_replaced_by_a_marker():
    from proxy.services.workbook_research_job_service import source_conflict_resolutions

    decision = {"source_row": "S!R2", "row_role": "work", "operation_id": "op-original"}
    proposal = {"proposal_id": "p1", "code": "MODEL_RESULT_SOURCE_CONFLICT", "decision": decision}
    assert source_conflict_resolutions([proposal], [{**decision, "operation_id": "op-other",
        "resolves_proposal_id": "p1"}], packet_locators=["S!R2"]) == []
    assert source_conflict_resolutions([proposal], [decision], packet_locators=["S!R2"]) == ["p1"]
    assert source_conflict_resolutions([proposal], [{**decision, "resolves_proposal_id": "unknown"}],
                                       packet_locators=["S!R2"]) == []


@pytest.mark.parametrize("transport", ["json", "markdown", "block", "inline"])
def test_resolution_marker_survives_every_row_transport(transport):
    row = {"source_row": "S!R2", "row_role": "work", "title": "Authored operation",
           "quantity": 12, "unit": "m", "norm_code": "MISSING", "resolves_proposal_id": "p1"}
    if transport == "json":
        raw = _answer([row])
    elif transport == "markdown":
        raw = "\n".join(["| " + " | ".join(row) + " |",
                         "| " + " | ".join("---" for _ in row) + " |",
                         "| " + " | ".join(str(value) for value in row.values()) + " |"])
    else:
        raw = ("\n" if transport == "block" else " | ").join(
            f"{key}: {value}" for key, value in row.items())
    _, parsed = app.parse_model_rag_result(raw)
    assert parsed[0]["resolves_proposal_id"] == "p1"


def test_stale_operation_correction_does_not_resolve_its_proposal(tmp_path):
    from tests.test_model_result_packet_service import _begin

    store = WorkbookResearchJobService(tmp_path / "stale.sqlite")
    job = _begin(store)
    job = store.record_packet(job["job_id"], sheet="S", packet_locators=["S!R2"],
        accepted_rows=[{"source_row": "S!R2", "row_role": "work", "quantity": 12}], evidence=[])
    prior = job["accepted_rows"][0]
    proposal = {"proposal_id": "p1", "code": "MODEL_RESULT_SOURCE_CONFLICT",
                "decision": {**prior, "quantity": 15.71}}
    job = store.record_packet(job["job_id"], sheet="S", packet_locators=["S!R2"],
        accepted_rows=[{**prior, "quantity": 13, "expected_revision": 1}],
        unapplied_proposals=[proposal], evidence=[], enforce_packet_scope=True)
    saved = copy.deepcopy(job["unapplied_proposals"])
    job = store.record_packet(job["job_id"], sheet="S", packet_locators=["S!R2"],
        accepted_rows=[{**prior, "quantity": 14, "expected_revision": 1, "resolves_proposal_id": "p1"}],
        evidence=[], enforce_packet_scope=True)
    assert "p1" not in job["task_context"].get("resolved_source_conflict_proposal_ids", [])
    assert job["accepted_rows"][0]["quantity"] == 13
    assert job["unapplied_proposals"][:len(saved)] == saved


@pytest.mark.asyncio
@pytest.mark.parametrize("alias_kind", ["casefold", "integer", "source_file_id"])
async def test_admitted_source_alias_keeps_the_canonical_catalog_source_pending(tmp_path, monkeypatch, alias_kind):
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "jobs.sqlite"))
    rows = _rows()
    def final_answer(_requests):
        from proxy.services.attachment_source_catalog_service import load_tabular_source_catalog
        file_id = load_tabular_source_catalog(tmp_path / "source.xlsx").source_file_id
        for row in rows:
            if row["row_role"] == "work":
                coordinate = row["source_row"].split("!", 1)[1]
                row["source_row"] = (int(coordinate[1:]) if alias_kind == "integer" else
                                     file_id + "!" + coordinate if alias_kind == "source_file_id" else
                                     row["source_row"].casefold())
        return _answer(rows)
    run = await _run_sheet(tmp_path, monkeypatch, reads=False, final_answer=final_answer)
    job = WorkbookResearchJobService().get(run.result["retrieval_trace"]["workbook_research_job"]["job_id"])
    assert job["status"] == "paused"
    assert job["remaining"] == ["S!R2", "S!R3"]
    assert [proposal["decision"]["source_row"] for proposal in _proposals(job)] == [
        row["source_row"] for row in rows if row["row_role"] == "work"]
