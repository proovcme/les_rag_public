"""The model declares a mixed-request artifact; code never picks its purpose."""
import json
import inspect

import pytest

from proxy.services import chat_evidence_application_service as app
from proxy.services import model_lsr_result_contract as contract
from proxy.services.workbook_research_job_service import WorkbookResearchJobService
from tests.test_model_rag_sheet_evidence_reads import _run_sheet
from tests import test_model_rag_sheet_evidence_reads as fixture


TOOLS = ["build_vor_workbook", "build_lsr_workbook", "search_sources"]
MIXED = "Составь ВОР по документу, чтобы потом подготовить смету"
REVERSE = "По ВОР собери ЛСР"


@pytest.mark.parametrize("question", [MIXED, REVERSE])
def test_mixed_mentions_keep_both_capabilities_without_default_target(question):
    assert app.workbook_artifact_intent(question) == "both"
    assert set(app.prioritize_workbook_tools(TOOLS, workbook_phase=True, question=question)) == set(TOOLS)
    assert app.workbook_packaging_tool(TOOLS, question) == []


@pytest.mark.parametrize("raw,kind", [
    ('{"artifact_kind":"vor","rows":[]}', "vor"),
    ('```json\n{"artifact_kind":"lsr","rows":[]}\n```', "lsr"),
    ("artifact_kind: vor\n\nModel-authored table", "vor"),
])
def test_literal_artifact_declaration_in_same_result(raw, kind):
    parser = getattr(contract, "decode_model_artifact_kind", None)
    assert callable(parser)
    result = parser(raw)
    assert result["status"] == "declared" and result["artifact_kind"] == kind


@pytest.mark.parametrize("raw", [
    '{"artifact_kind":"vor","artifact_kind":"lsr","rows":[]}',
    '{"artifact_kind":"vor","artifact_kind":"vor","rows":[]}',
    'artifact_kind: vor\nartifact_kind: lsr',
    'artifact_kind: vor\n```json\n{"artifact_kind":"lsr","rows":[]}\n```',
    '{"artifact_kind":"unknown","rows":[]}',
    '{"artifact_kind":[],"queries":[]}',
    '{"artifact_kind":{},"queries":[]}',
    '{"artifact_kind":"vor","rows":[',
])
def test_ambiguous_invalid_or_incomplete_declaration_never_selects_a_target(raw):
    parser = getattr(contract, "decode_model_artifact_kind", None)
    assert callable(parser)
    result = parser(raw)
    assert result["status"] in {"conflict", "invalid"}
    assert result["artifact_kind"] == ""


def test_nested_row_and_prose_are_not_artifact_declarations():
    parser = getattr(contract, "decode_model_artifact_kind", None)
    assert callable(parser)
    assert parser('The requested ВОР becomes input for ЛСР')['status'] == "missing"
    assert parser('{"rows":[{"artifact_kind":"lsr"}]}')["status"] == "missing"


def test_duplicate_target_does_not_discard_unique_authored_rows():
    row = {"source_row": "S!R2", "row_role": "material", "title": "Literal item", "unit": "m", "quantity": 12}
    raw = '{"artifact_kind":"vor","artifact_kind":"lsr","rows":[' + json.dumps(row) + ']}'
    assert contract.decode_model_result_rows(raw) == [row]


def test_declared_target_survives_restart_and_plain_continuation(tmp_path):
    store = WorkbookResearchJobService(tmp_path / "meta.db")
    def identity(service, question):
        return service.identity(session_id="own", attachment_id="read_doc", source_sha256="a" * 64,
                                dataset_ids=["norms"], profile_revision_id="r1", model_identity="model", question=question)
    job = store.begin_or_resume(identity(store, MIXED), task_context={"original_question": MIXED, "artifact_intent": "both"})
    recorder = getattr(store, "record_artifact_kind", None)
    assert callable(recorder)
    recorder(job["job_id"], declaration={"status": "declared", "artifact_kind": "vor", "declarations": ["vor"], "errors": []})
    restarted = WorkbookResearchJobService(tmp_path / "meta.db")
    resumed = restarted.begin_or_resume(identity(restarted, "Продолжи"), task_context={"original_question": "Продолжи", "artifact_intent": "both"})
    assert resumed["task_context"]["model_artifact_kind"] == "vor"
    assert app.workbook_packaging_tool(TOOLS, "Продолжи", task_context=resumed["task_context"]) == ["build_vor_workbook"]
    assert "model_artifact_kind" in app.workbook_model_question("Продолжи", resumed)
    # A different immutable source must not inherit the model's target.
    replaced = restarted.begin_or_resume(restarted.identity(session_id="own", attachment_id="read_doc", source_sha256="b" * 64,
        dataset_ids=["norms"], profile_revision_id="r1", model_identity="model", question="Продолжи"))
    assert not replaced["task_context"].get("model_artifact_kind")


def _model_fixture(monkeypatch, *, question, declaration):
    original_answer, original_run = fixture._answer, app.run_chat_evidence_application
    def answer(**kwargs):
        body = original_answer(**kwargs)
        # The fixture's default LSR declaration is replaced by this model turn.
        body = body.removeprefix("artifact_kind: lsr\n")
        return (declaration + "\n" if declaration else "") + body
    async def run(request, *args, **kwargs):
        if request.req.question != "Продолжи":
            request.req.question = question + "; Санкт-Петербург, 3 квартал 2026"
        return await original_run(request, *args, **kwargs)
    monkeypatch.setattr(fixture, "_answer", answer)
    monkeypatch.setattr(app, "run_chat_evidence_application", run)


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
@pytest.mark.parametrize("question,kind", [(MIXED, "vor"), (REVERSE, "lsr")])
async def test_model_target_drives_real_packaging_without_another_model_turn(tmp_path, monkeypatch, variant, question, kind):
    _model_fixture(monkeypatch, question=question, declaration="artifact_kind: " + kind)
    run = await _run_sheet(tmp_path, monkeypatch, reads=False, variant=variant)
    assert len(run.requests) == 2 and not run.responses
    assert len(run.executions) == 1
    call, receipt = run.executions[0]
    assert call["tool"] == "build_" + kind + "_workbook"
    assert [(row["source_row"], row["quantity"]) for row in call["args"]["decisions"]] == [("S!R2", 12), ("S!R3", 3)]
    assert receipt.get("artifact", {}).get("revision_id")


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
@pytest.mark.parametrize("declaration", ["", "artifact_kind: vor\nartifact_kind: lsr"])
async def test_undeclared_or_conflicting_target_keeps_rows_and_visible_packaging_pending(tmp_path, monkeypatch, variant, declaration):
    _model_fixture(monkeypatch, question=MIXED, declaration=declaration)
    run = await _run_sheet(tmp_path, monkeypatch, reads=False, variant=variant)
    assert len(run.requests) == 2 and not run.responses
    assert run.executions == []
    result = run.result["retrieval_trace"]["model_result"]
    assert result["row_count"] == 2 and result["packaging_status"] == "pending"
    assert "ВОР или ЛСР" in run.result["answer"]
    if variant == "B1_CANDIDATE":
        job = WorkbookResearchJobService().get(run.result["retrieval_trace"]["workbook_research_job"]["job_id"])
        assert len(job["accepted_rows"]) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_model_declared_vor_empty_queries_uses_source_without_rrf_or_repair(tmp_path, monkeypatch, variant):
    _model_fixture(monkeypatch, question=MIXED, declaration="artifact_kind: vor")
    run = await _run_sheet(tmp_path, monkeypatch, reads=False, variant=variant,
                           query_declaration='{"artifact_kind":"vor","queries":[]}')
    assert len(run.requests) == 2 and not run.responses
    assert not run.queries and not run.exact_reads
    assert run.executions[0][0]["tool"] == "build_vor_workbook"
    assert len(run.executions) == 1 and run.executions[0][1].get("artifact", {}).get("revision_id")
    assert [(r["source_row"], r["quantity"]) for r in run.executions[0][0]["args"]["decisions"]] == [("S!R2", 12), ("S!R3", 3)]
    if variant == "B1_CANDIDATE":
        job = WorkbookResearchJobService().get(run.result["retrieval_trace"]["workbook_research_job"]["job_id"])
        assert job["task_context"]["model_artifact_kind"] == "vor"


def test_structured_queries_preserve_literals_and_lsr_empty_is_not_a_no_search_choice():
    response = app.read_model_query_response('{"artifact_kind":"lsr","queries":["Literal original query A","Literal original query B"]}')
    assert [q.text for q in response["queries"]] == ["Literal original query A", "Literal original query B"]
    assert not response["intentional_empty"]
    assert not app.read_model_query_response('{"artifact_kind":"lsr","queries":[]}')["intentional_empty"]


def test_fresh_engineer_correction_can_resolve_prior_ambiguous_target(tmp_path):
    store = WorkbookResearchJobService(tmp_path / "meta.db")
    def start(question):
        return store.begin_or_resume(store.identity(session_id="own", attachment_id="read_doc", source_sha256="a" * 64,
            dataset_ids=["norms"], profile_revision_id="r1", model_identity="model", question=question),
            task_context={"original_question": question, "artifact_intent": "both"})
    original = start(MIXED)
    store.record_artifact_kind(original["job_id"], declaration={"status": "conflict", "artifact_kind": "", "declarations": ["vor", "lsr"], "errors": ["ARTIFACT_KIND_AMBIGUOUS"]})
    corrected = start("Исправь тип результата по моему замечанию")
    corrected = store.record_artifact_kind(corrected["job_id"], declaration={"status": "declared", "artifact_kind": "vor", "declarations": ["vor"], "errors": []})
    assert app.workbook_packaging_tool(TOOLS, "Продолжи", task_context=corrected["task_context"]) == ["build_vor_workbook"]
    events = store.list_events_with_lineage(corrected["job_id"])
    assert any(e["event_type"] == "model_artifact_kind" and e["payload"]["status"] == "conflict" for e in events)


@pytest.mark.parametrize("value", [[], {}, None, 2, True])
def test_malformed_query_target_is_rejected_without_an_exception(value):
    result = app.read_model_query_response(json.dumps({"artifact_kind": value, "queries": []}))
    assert result["artifact_kind_declaration"]["status"] == "invalid"
    assert not result["intentional_empty"]


@pytest.mark.asyncio
async def test_plain_continuation_cannot_silently_change_saved_model_target(tmp_path, monkeypatch):
    _model_fixture(monkeypatch, question=MIXED, declaration="artifact_kind: vor")
    run = await _run_sheet(tmp_path, monkeypatch, reads=True, partial_final=True)
    assert len(run.executions) == 1 and run.executions[0][0]["tool"] == "build_vor_workbook"
    request = inspect.getclosurevars(run.resume_same_request).nonlocals["request"]
    request.req.question = "Продолжи"
    result = await run.corrected_source_row("S!R3")  # this model turn explicitly declares LSR
    assert len(run.executions) == 1  # no conflicting second workbook
    assert result["retrieval_trace"]["artifact_target"]["status"] == "conflict"
    assert result["retrieval_trace"]["model_result"]["packaging_status"] == "pending"
    job = WorkbookResearchJobService().get(result["retrieval_trace"]["workbook_research_job"]["job_id"])
    assert [(r["source_row"], r["quantity"]) for r in job["accepted_rows"]] == [("S!R2", 12), ("S!R3", 3)]
    assert len(run.requests) == 8 and not run.responses
