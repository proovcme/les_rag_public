"""The completed model document owns its type; search proposals are provisional."""
import copy
import json
import pytest

from proxy.services.model_lsr_result_contract import decode_model_artifact_kind, update_model_artifact_kind
from tests import test_model_rag_sheet_evidence_reads as sheet_fixture
from tests.test_model_rag_sheet_evidence_reads import _run_sheet


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
@pytest.mark.parametrize("shape", ["markdown", "json_tail"])
async def test_terminal_document_type_supersedes_search_proposal(tmp_path, monkeypatch, variant, shape):
    if shape == "json_tail":
        def answer(*, refs=("Q1.H1", "Q2.H1")):
            rows = [{"source_row": locator, "row_role": "material", "title": name, "unit": "m",
                     "quantity": quantity, "resource_code": code, "evidence_refs": [ref]}
                    for locator, name, quantity, code, ref in (
                        ("S!R2", "Cable A", 12, sheet_fixture.RESOURCE_A, refs[0]),
                        ("S!R3", "Cable B", 3, sheet_fixture.RESOURCE_B, refs[1]))]
            for row in rows:
                row["supply_resource_match"] = {"source_title": row["title"], "resource_code": row["resource_code"],
                    "decision": "yes", "reason": "The authored product matches the literal fixture resource.",
                    "source_refs": list(row["evidence_refs"])}
            return "```json\n" + json.dumps({"rows": rows, "artifact_kind": "lsr"}) + "\n```"
        monkeypatch.setattr(sheet_fixture, "_answer", answer)
    run = await _run_sheet(tmp_path, monkeypatch, reads=True, variant=variant,
        query_declaration='{"artifact_kind":"vor","queries":["S!R2 — Cable A","S!R3 — Cable B"]}')
    assert len(run.executions) == 1
    call, receipt = run.executions[0]
    assert call["tool"] == "build_lsr_workbook"
    assert receipt["artifact"]["download_url"]
    assert len(call["args"]["decisions"]) == 2
    assert not run.responses
    assert len(run.requests) == 4, "target handoff must not add inference"
    target = run.result["retrieval_trace"]["artifact_target"]
    assert target["artifact_kind"] == "lsr" and target["status"] == "declared"
    assert target["authority"] == "result"
    assert target["query_declaration"]["artifact_kind"] == "vor"
    queries = run.result["retrieval_trace"]["model_query_outputs"]
    assert queries[0]["artifact_kind_declaration"]["artifact_kind"] == "vor"
    if variant == "B1_CANDIDATE":
        from proxy.services.workbook_research_job_service import WorkbookResearchJobService
        job = WorkbookResearchJobService().get(run.result["retrieval_trace"]["workbook_research_job"]["job_id"])
        assert job["task_context"]["artifact_kind_declaration"] == target
        assert job["task_context"]["model_artifact_kind"] == "lsr"


def declaration(kind):
    return decode_model_artifact_kind("artifact_kind: " + kind)


def test_initial_proposal_can_be_stored_without_prior_state():
    assert update_model_artifact_kind(None, declaration("vor"), phase="query")["authority"] == "query"


def test_conflicting_search_proposals_do_not_change_completed_result():
    proposal = update_model_artifact_kind(None, declaration("vor"), phase="query")
    proposal = update_model_artifact_kind(proposal, declaration("lsr"), phase="query")
    assert proposal["status"] == "conflict"
    completed = update_model_artifact_kind(proposal, declaration("lsr"), phase="result")
    assert completed["status"] == "declared" and completed["artifact_kind"] == "lsr"
    assert completed["query_declaration"]["status"] == "conflict"


@pytest.mark.parametrize("current", ["artifact_kind: vor\nartifact_kind: lsr", "artifact_kind: lsr\nartifact_kind: lsr", '```json\n{"rows":[],"artifact_kind":"lsr","artifact_kind":"lsr"}\n```'])
def test_duplicate_target_inside_completed_result_stays_blocked(current):
    proposal = update_model_artifact_kind(None, declaration("lsr"), phase="query")
    completed = update_model_artifact_kind(proposal, decode_model_artifact_kind(current), phase="result")
    assert completed["status"] == "conflict" and not completed["artifact_kind"]


def test_conflicting_completed_packets_stay_blocked():
    first = update_model_artifact_kind(None, declaration("vor"), phase="result")
    second = update_model_artifact_kind(first, declaration("lsr"), phase="result")
    assert second["status"] == "conflict" and not second["artifact_kind"]


def test_late_query_proposal_does_not_replace_saved_completed_target():
    first = update_model_artifact_kind(None, declaration("lsr"), phase="result")
    proposal = update_model_artifact_kind(first, declaration("vor"), phase="query")
    assert proposal["artifact_kind"] == "lsr" and proposal["authority"] == "result"
    assert proposal["query_declaration"]["artifact_kind"] == "vor"


def test_unclassified_historical_target_is_not_reinterpreted_as_provisional():
    saved = declaration("vor")
    original = copy.deepcopy(saved)
    restored = update_model_artifact_kind(None, saved, phase="restore")
    current = update_model_artifact_kind(restored, declaration("lsr"), phase="result")
    assert current["status"] == "conflict"
    assert saved == original


def test_restore_completed_target_supersedes_current_query_proposal():
    saved = update_model_artifact_kind(None, declaration("lsr"), phase="result")
    original = copy.deepcopy(saved)
    proposal = update_model_artifact_kind(None, declaration("vor"), phase="query")
    restored = update_model_artifact_kind(proposal, saved, phase="restore")
    assert restored["artifact_kind"] == "lsr" and restored["authority"] == "result"
    assert restored["query_declaration"]["artifact_kind"] == "vor"
    assert saved == original


def test_missing_final_declaration_keeps_existing_proposal():
    proposal = update_model_artifact_kind(None, declaration("vor"), phase="query")
    assert update_model_artifact_kind(proposal, decode_model_artifact_kind("No declaration"), phase="result") == proposal


@pytest.mark.asyncio
@pytest.mark.parametrize("query_kind", ["vor", "lsr"])
async def test_final_vor_with_specification_resource_code_does_not_enter_financial_proof(
    tmp_path, monkeypatch, query_kind,
):
    rows = [
        {"source_row": "S!R2", "row_role": "work", "title": "Install Cable A", "unit": "m",
         "quantity": 12, "open_gap": ""},
        {"source_row": "S!R3", "row_role": "material", "work_row": "S!R2", "title": "Cable B",
         "unit": "m", "quantity": 3, "resource_code": sheet_fixture.RESOURCE_B, "evidence_refs": ["Q2.H1"]},
    ]
    run = await _run_sheet(tmp_path, monkeypatch, reads=False, variant="B1_CANDIDATE",
        query_declaration=json.dumps({"artifact_kind": query_kind,
            "queries": ["S!R2 — Cable A", "S!R3 — Cable B"]}),
        final_answer=json.dumps({"artifact_kind": "vor", "rows": rows}))

    assert len(run.requests) == 2 and not run.responses
    assert len(run.executions) == 1 and run.executions[0][0]["tool"] == "build_vor_workbook"
    saved = run.executions[0][0]["args"]["decisions"]
    assert len(saved) == len(rows)
    assert [{key: row[key] for key in authored} for row, authored in zip(saved, rows)] == rows
    assert not run.result["retrieval_trace"].get("resource_group_proof_requests")
    target = run.result["retrieval_trace"]["artifact_target"]
    assert target["artifact_kind"] == "vor" and target["authority"] == "result"


@pytest.mark.asyncio
async def test_final_lsr_after_vor_proposal_still_requests_unsubstantiated_supply_proof(tmp_path, monkeypatch):
    from proxy.services.openai_compatible_transport_service import InferenceResponse

    rows = [{"source_row": source, "row_role": "material", "title": title, "unit": "m",
             "quantity": quantity, "norm_code": "", "resource_code": code, "evidence_refs": [ref]}
            for source, title, quantity, code, ref in (
                ("S!R2", "Cable A", 12, sheet_fixture.RESOURCE_A, "Q1.H1"),
                ("S!R3", "Cable B", 3, sheet_fixture.RESOURCE_B, "Q2.H1"))]
    authored = json.dumps({"artifact_kind": "lsr", "rows": rows})
    run = await _run_sheet(tmp_path, monkeypatch, reads=False, variant="B1_CANDIDATE",
        query_declaration=json.dumps({"artifact_kind": "vor", "queries": ["S!R2 — Cable A", "S!R3 — Cable B"]}),
        final_answer=authored,
        proof_replies=[InferenceResponse(text=authored, tool_calls=(), finish_reason="stop", usage={})])

    assert len(run.requests) == 3 and not run.responses
    proofs = run.result["retrieval_trace"]["resource_group_proof_requests"]
    assert len(proofs) == 1 and proofs[0]["requested_supply_matches"] == 2
    assert proofs[0]["reason"] == "supply_resource_match_unsubstantiated"
    assert proofs[0]["answer_parsed"] is True
    assert len(run.executions) == 1 and run.executions[0][0]["tool"] == "build_lsr_workbook"
    target = run.result["retrieval_trace"]["artifact_target"]
    assert target["artifact_kind"] == "lsr" and target["authority"] == "result"
