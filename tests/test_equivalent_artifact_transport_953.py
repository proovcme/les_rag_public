"""Matching plain/JSON target labels do not prevent delivery of authored rows."""

import copy
import json

import pytest

from proxy.services.model_lsr_result_contract import decode_model_artifact_kind
from proxy.services.workbook_research_job_service import WorkbookResearchJobService
from tests import test_model_rag_sheet_evidence_reads as sheet_fixture
from tests.test_model_rag_sheet_evidence_reads import _run_sheet


@pytest.mark.parametrize("kind", ["vor", "lsr"])
@pytest.mark.parametrize("fenced", [False, True])
@pytest.mark.parametrize("label_first", [False, True])
def test_one_matching_plain_label_and_one_complete_json_keep_both_authored_declarations(
        kind, fenced, label_first):
    document = json.dumps({"artifact_kind": kind, "rows": []})
    if fenced:
        document = "```json\n" + document + "\n```"
    parts = ["artifact_kind: " + kind, document]
    if not label_first:
        parts.reverse()
    raw = "\n\n".join(parts)
    before = copy.deepcopy(raw)
    target = decode_model_artifact_kind(raw)
    assert target == {"status": "declared", "artifact_kind": kind,
                      "declarations": [kind, kind], "errors": []}
    assert raw == before


@pytest.mark.parametrize("raw", [
    '{"artifact_kind":"vor","artifact_kind":"vor","rows":[]}',
    'artifact_kind: vor\n{"artifact_kind":"vor","artifact_kind":"vor","rows":[]}',
    'artifact_kind: vor\n{"artifact_kind":"vor","rows":[],"rows":[]}',
    'artifact_kind: vor\n{"artifact_kind":"vor","rows":[{"quantity":1,"quantity":2}]}',
    'artifact_kind: vor\n{"artifact_kind":"vor","rows":[]}\n{"commentary":"note"}',
    '{"artifact_kind":"vor","rows":[]}\n{"artifact_kind":"vor","rows":[]}',
    'artifact_kind: vor\nartifact_kind: vor',
    'artifact_kind: vor\nartifact_kind: vor\n{"artifact_kind":"vor","rows":[]}',
    'artifact_kind: vor\n{"artifact_kind":"lsr","rows":[]}',
    'artifact_kind: lsr\n{"artifact_kind":"vor","rows":[]}',
    'artifact_kind: vor\n{"artifact_kind":"vor","rows":[',
    'artifact_kind: vor\n{"artifact_kind":"vor","rows":[]}trailing{',
    'artifact_kind: invalid\n{"artifact_kind":"invalid","rows":[]}',
    'artifact_kind: vor\n{"artifact_kind":[],"rows":[]}',
])
def test_repeated_keys_multiple_documents_conflicts_and_incomplete_json_stay_blocked(raw):
    target = decode_model_artifact_kind(raw)
    assert target["status"] in {"conflict", "invalid"}
    assert target["artifact_kind"] == ""
    assert target["errors"]


def _rows(*, invalid_derived=False):
    rows = [{"source_row": locator, "row_role": "work", "work_row": "", "title": title,
             "unit": "m", "quantity": quantity, "open_gap": ""}
            for locator, title, quantity in [("S!R2", "Install Cable A", 12),
                                             ("S!R3", "Install Cable B", 3)]]
    if invalid_derived:
        rows[0].update(calc_unit="m", calc_quantity=999, conversion_factor=0.5,
                       conversion_basis="Authored half of the stated source quantity")
    return rows


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_derived", [False, True])
async def test_real_three_packet_vor_keeps_matching_cross_form_target_and_integrity(
        tmp_path, monkeypatch, invalid_derived):
    packet_index = 0
    rows = _rows(invalid_derived=invalid_derived)
    original_rows = copy.deepcopy(rows)

    def authored_reply(_requests):
        nonlocal packet_index
        packet_index += 1
        prefix = "artifact_kind: vor\n\n" if packet_index == 3 else ""
        return prefix + json.dumps({"artifact_kind": "vor", "rows": rows})

    run = await _run_sheet(tmp_path, monkeypatch, reads=False, packet_count=3,
        query_declaration='{"artifact_kind":"vor","queries":[]}', final_answer=authored_reply)
    trace = run.result["retrieval_trace"]
    target = trace["artifact_target"]
    assert target["status"] == "declared" and target["artifact_kind"] == "vor"
    assert target["declarations"] == ["vor", "vor"]
    assert target["authority"] == "result"
    assert len(run.executions) == 1
    call, receipt = run.executions[0]
    assert call["tool"] == "build_vor_workbook"
    assert receipt["artifact"]["download_url"]
    assert len(call["args"]["decisions"]) == 6
    assert "missing_evidence_ref" not in str(trace["model_result"])
    assert "ЛСР собрана частично" not in run.result["answer"]
    assert trace["result_readiness"]["technical_complete"]
    assert trace["result_readiness"]["vor_complete"] is not invalid_derived
    if invalid_derived:
        assert "conversion_result_mismatch" in {
            issue["code"] for issue in trace["result_readiness"]["row_integrity_issues"]}
        assert {row["calc_quantity"] for row in call["args"]["decisions"]
                if row.get("calc_quantity") is not None} == {999}
    job = WorkbookResearchJobService().get(trace["workbook_research_job"]["job_id"])
    assert job["task_context"]["artifact_kind_declaration"] == target
    assert len(job["accepted_rows"]) == 6
    assert rows == original_rows
    assert not run.responses and len(run.requests) == 10


@pytest.mark.asyncio
async def test_conflicting_completed_packet_still_preserves_rows_without_picking_target(tmp_path, monkeypatch):
    packet_index = 0

    def authored_reply(_requests):
        nonlocal packet_index
        packet_index += 1
        kind = "lsr" if packet_index == 3 else "vor"
        rows = [{**row, "norm_code": ""} for row in _rows()]
        return "artifact_kind: " + kind + "\n" + json.dumps({"artifact_kind": kind, "rows": rows})

    run = await _run_sheet(tmp_path, monkeypatch, reads=False, packet_count=3,
        query_declaration='{"artifact_kind":"vor","queries":[]}', final_answer=authored_reply)
    trace = run.result["retrieval_trace"]
    assert trace["artifact_target"]["status"] == "conflict"
    assert not trace["artifact_target"]["artifact_kind"]
    assert run.executions == []
    assert trace["model_result"]["packaging_reason"] == "ARTIFACT_KIND_UNRESOLVED"
    assert trace["workbook_research_job"]["accepted_rows"] == 6


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_matching_forms_keep_lsr_prices_and_native_read_route(tmp_path, monkeypatch, variant):
    def authored_reply(*, refs=("Q1.H1", "Q2.H1")):
        rows = [{"source_row": locator, "row_role": "material", "title": title, "unit": "m",
                 "quantity": quantity, "norm_code": "", "resource_code": code,
                 "evidence_refs": [ref]}
                for locator, title, quantity, code, ref in [
                    ("S!R2", "Cable A", 12, sheet_fixture.RESOURCE_A, refs[0]),
                    ("S!R3", "Cable B", 3, sheet_fixture.RESOURCE_B, refs[1])]]
        return "artifact_kind: lsr\n" + json.dumps({"artifact_kind": "lsr", "rows": rows})

    monkeypatch.setattr(sheet_fixture, "_answer", authored_reply)
    run = await _run_sheet(tmp_path, monkeypatch, reads=True, variant=variant)
    assert len(run.requests) == 4 and not run.responses
    assert len(run.executions) == 1
    call, receipt = run.executions[0]
    assert call["tool"] == "build_lsr_workbook"
    assert receipt["artifact"]["download_url"]
    assert receipt["confirmed_amount"] == 1800 and receipt["preliminary_amount"] == 0
    assert receipt["price_basis"]["actual_book"] == sheet_fixture.BOOK
    target = run.result["retrieval_trace"]["artifact_target"]
    assert target["status"] == "declared" and target["artifact_kind"] == "lsr"
    assert target["declarations"] == ["lsr", "lsr"]
