"""An explicitly declared document target applies to its later literal row packets."""

from copy import deepcopy
import json

import pytest

from proxy.services import chat_evidence_application_service as app
from proxy.services.model_lsr_result_contract import decode_model_artifact_kind
from proxy.services.workbook_research_job_service import WorkbookResearchJobService
from tests.test_model_rag_sheet_evidence_reads import _run_sheet


ROW = {"source_row": "Sheet Ω!R4", "row_role": "work", "work_row": "",
       "title": "Авторская работа", "unit": "м²", "quantity": 28.6, "open_gap": ""}


def declaration(kind="vor", status="declared"):
    return {"status": status, "artifact_kind": kind, "declarations": [kind],
            "errors": [] if status == "declared" else ["ARTIFACT_KIND_AMBIGUOUS"]}


def render(rows, shape="markdown"):
    if shape == "block_text":
        return "\n\n".join("\n".join(f"{key}: {value}" for key, value in row.items()) for row in rows)
    if shape == "json_object":
        return json.dumps({"rows": rows}, ensure_ascii=False)
    if shape == "json_array":
        return json.dumps(rows, ensure_ascii=False)
    return ("| " + " | ".join(rows[0]) + " |\n| " + " | ".join("---" for _ in rows[0]) + " |\n"
            + "\n".join("| " + " | ".join(str(value) for value in row.values()) + " |" for row in rows))


@pytest.mark.parametrize("shape", ["markdown", "block_text", "json_object", "json_array"])
def test_missing_packet_metadata_uses_only_the_explicit_current_model_declaration(shape):
    raw = render([ROW], shape)
    target = declaration()
    before = deepcopy((ROW, target))
    diagnostics = []
    parsed = app.parse_model_rag_result(raw, model_declaration=target, diagnostics=diagnostics)
    assert parsed == (raw, [ROW]) and diagnostics == []
    assert decode_model_artifact_kind(raw)["status"] == "missing"
    assert (ROW, target) == before


@pytest.mark.parametrize("target", [None, {}, declaration(status="missing"),
    declaration(status="conflict"), declaration("lsr"), declaration(status="invalid")])
@pytest.mark.parametrize("shape", ["markdown", "block_text"])
def test_unknown_or_unresolved_current_target_never_defaults_a_normless_packet_to_vor(target, shape):
    raw = render([ROW], shape)
    assert app.parse_model_rag_result(raw, model_declaration=target) is None


@pytest.mark.parametrize("raw_declaration", ["artifact_kind: lsr\n", "artifact_kind: unknown\n",
    "artifact_kind: vor\nartifact_kind: lsr\n", "artifact_kind: vor\nartifact_kind: vor\n"])
def test_existing_vor_target_cannot_override_explicit_lsr_invalid_or_conflicting_packet(raw_declaration):
    raw = raw_declaration + render([ROW])
    assert app.parse_model_rag_result(raw, model_declaration=declaration()) is None


def test_explicit_current_result_type_still_supersedes_an_earlier_query_proposal():
    raw = "artifact_kind: vor\n" + render([ROW])
    assert app.parse_model_rag_result(raw, model_declaration=declaration("lsr")) == (raw, [ROW])


def source_rows():
    return [{**ROW, "source_row": locator, "title": title, "unit": "m", "quantity": qty}
            for locator, title, qty in [("S!R2", "Install Cable A", 12),
                                       ("S!R3", "Install Cable B", 3)]]


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_query_declared_vor_delivers_raw_normless_markdown_without_repeating_metadata(
        tmp_path, monkeypatch, variant):
    rows = source_rows()
    raw = render(rows)
    run = await _run_sheet(tmp_path, monkeypatch, reads=False, variant=variant,
        query_declaration='{"artifact_kind":"vor","queries":[]}', final_answer=raw)
    trace = run.result["retrieval_trace"]
    assert len(run.requests) == 2 and not run.responses
    assert trace["artifact_target"]["artifact_kind"] == "vor"
    assert trace["artifact_target"]["declarations"] == ["vor"]
    assert len(run.executions) == 1
    call, receipt = run.executions[0]
    assert call["tool"] == "build_vor_workbook" and receipt["artifact"]["download_url"]
    assert [(row["source_row"], row["quantity"]) for row in call["args"]["decisions"]] == [
        ("S!R2", 12), ("S!R3", 3)]
    assert all("norm_code" not in row for row in call["args"]["decisions"])
    assert trace["result_readiness"]["vor_complete"]
    assert "missing_evidence_ref" not in str(trace["model_result"])
    assert decode_model_artifact_kind(raw)["status"] == "missing"


@pytest.mark.asyncio
async def test_later_packets_keep_literal_rows_in_markdown_and_block_formats(tmp_path, monkeypatch):
    packet = 0

    def authored_reply(_requests):
        nonlocal packet
        packet += 1
        if packet == 1:
            return json.dumps({"artifact_kind": "vor", "rows": source_rows()})
        return render(source_rows(), "markdown" if packet == 2 else "block_text")

    run = await _run_sheet(tmp_path, monkeypatch, reads=False, packet_count=3,
        query_declaration='{"artifact_kind":"vor","queries":[]}', final_answer=authored_reply)
    trace = run.result["retrieval_trace"]
    assert len(run.requests) == 10 and not run.responses
    assert [p["parsed_rows"] for p in trace["tool_loop"]["passes"]] == [2, 2, 2]
    assert [p["kept_rows"] for p in trace["tool_loop"]["passes"]] == [2, 2, 2]
    assert [q["artifact_kind_declaration"]["status"] for q in trace["model_query_outputs"]] == [
        "declared", "missing", "missing"]
    assert trace["artifact_target"]["artifact_kind"] == "vor"
    assert trace["artifact_target"]["declarations"] == ["vor"]
    assert trace["result_readiness"]["vor_complete"]
    call, receipt = run.executions[0]
    assert receipt["artifact"]["download_url"] and len(call["args"]["decisions"]) == 6
    job = WorkbookResearchJobService().get(trace["workbook_research_job"]["job_id"])
    assert job["status"] == "complete" and job["remaining"] == []
    assert [(row["source_row"], row["quantity"]) for row in job["accepted_rows"]] == [
        (f"S!R{index}", 12 if index % 2 == 0 else 3) for index in range(2, 8)]


@pytest.mark.asyncio
async def test_later_explicit_conflicting_packet_does_not_inherit_or_choose_the_previous_vor(tmp_path, monkeypatch):
    packet = 0

    def authored_reply(_requests):
        nonlocal packet
        packet += 1
        if packet == 1:
            return json.dumps({"artifact_kind": "vor", "rows": source_rows()})
        return "artifact_kind: lsr\n" + render([{**row, "norm_code": ""} for row in source_rows()])

    run = await _run_sheet(tmp_path, monkeypatch, reads=False, packet_count=2,
        query_declaration='{"artifact_kind":"vor","queries":[]}', final_answer=authored_reply)
    trace = run.result["retrieval_trace"]
    assert trace["artifact_target"]["status"] == "conflict"
    assert trace["artifact_target"]["artifact_kind"] == ""
    assert trace["model_result"]["packaging_reason"] == "ARTIFACT_KIND_UNRESOLVED"
    assert run.executions == []
    assert trace["workbook_research_job"]["accepted_rows"] == 4
