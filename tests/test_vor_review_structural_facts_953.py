"""User review sees existing structural evidence, never application-selected works."""
from copy import deepcopy
import inspect
import json
from types import SimpleNamespace

import openpyxl
import pytest

from proxy.services import chat_evidence_application_service as app
from proxy.services.attachment_source_catalog_service import load_tabular_source_catalog
from proxy.services.openai_compatible_transport_service import InferenceResponse
from proxy.services.workbook_research_job_service import WorkbookResearchJobService
from tests import test_model_rag_sheet_evidence_reads as fixture


def _work(source="Отделка Ω!R2", operation_id="existing-work", **extra):
    return {"source_row": source, "operation_id": operation_id, "revision": 3,
            "row_role": "work", "title": "Авторская операция", "unit": "м²", "quantity": 12, **extra}


def _material(source="Отделка Ω!R3", parent="existing-work", **extra):
    return {"source_row": source, "operation_id": "existing-material", "revision": 2,
            "row_role": "material", "title": "Авторский материал", "unit": "м²", "quantity": 12,
            "work_row": parent, **extra}


def _review(packet, full, **kwargs):
    return app.model_rag_prior_page_context(
        [], [], review_rows=packet, review_instruction="Перепроверь работы и объёмы по исходнику",
        prior_artifact_kind="vor", full_result_rows=full, **kwargs)[0]


def _integrity(payload):
    return [issue for fact in payload["prior_result_structural_facts"]
            for issue in fact.get("vor_integrity", [])]


def _assert_authored_fields(payload, rows):
    projected = payload["prior_model_decisions"]
    assert len(projected) == len(rows)
    assert [{key: displayed[key] for key in original}
            for original, displayed in zip(rows, projected)] == rows


@pytest.mark.parametrize("parent", ["existing-work", "Отделка Ω!R2", "R2"])
def test_existing_work_outside_current_packet_prevents_a_false_link_warning(parent):
    work, material = _work(), _material(parent=parent)
    full = [work, material]
    before = deepcopy(full)
    payload = _review([material], full)
    assert _integrity(payload) == []
    assert payload["prior_result_structural_facts"] == []
    _assert_authored_fields(payload, [material])
    assert full == before


def test_review_reports_invalid_link_only_for_the_current_packet_without_changing_decisions():
    work = _work()
    material = _material(parent="missing-operation")
    other = _material("Другой лист!R8", parent="also-missing", operation_id="another-material")
    full, packet = [work, material, other], [material]
    before = deepcopy((full, packet))
    payload = _review(packet, full)
    facts = payload["prior_result_structural_facts"]
    assert len(facts) == 1
    assert facts[0]["source_row"] == material["source_row"]
    assert facts[0]["operation_id"] == material["operation_id"]
    assert facts[0]["vor_integrity"] == [{
        "code": "invalid_work_relationship",
        "reason": "Связь work_row не указывает на существующую строку работы (row_role=work) в результате.",
        "work_row": "missing-operation", "target_exists": False, "target_roles": [],
    }]
    _assert_authored_fields(payload, packet)
    assert (full, packet) == before
    assert "не предметные решения" in payload["evidence_continuation_instruction"]


def test_review_reports_missing_link_and_derived_measure_basis_with_existing_auditor():
    work = _work(calc_quantity=6, calc_unit="м²")
    material = _material(parent="")
    payload = _review([work, material], [work, material])
    assert {issue["code"] for issue in _integrity(payload)} == {
        "missing_calc_basis", "missing_work_relationship"}
    _assert_authored_fields(payload, [work, material])


def test_facts_for_two_operations_at_one_source_remain_attached_to_their_own_operation():
    valid = _work(operation_id="first-work")
    incomplete = _work(operation_id="second-work", quantity=None)
    payload = _review([valid, incomplete], [valid, incomplete])
    assert len(payload["prior_result_structural_facts"]) == 1
    fact = payload["prior_result_structural_facts"][0]
    assert fact["operation_id"] == "second-work"
    assert [x["code"] for x in fact["vor_integrity"]] == ["missing_work_quantity"]


@pytest.mark.parametrize("review_rows,instruction,kind", [
    (False, "", "vor"),
    (False, "Перепроверь", "vor"),
    (True, "", "vor"),
    (True, "Перепроверь", "lsr"),
    (True, "Перепроверь", ""),
])
def test_ordinary_continuation_and_other_document_types_keep_their_previous_context(
    review_rows, instruction, kind,
):
    rows = [_work(), _material(parent="missing-operation")]
    args = dict(review_rows=rows if review_rows else (), review_instruction=instruction)
    current = [] if review_rows else rows
    baseline, _ = app.model_rag_prior_page_context(current, [], **args)
    extended, _ = app.model_rag_prior_page_context(
        current, [], **args, prior_artifact_kind=kind, full_result_rows=rows)
    assert extended == baseline
    assert _integrity(extended) == []


def test_source_comparison_and_arithmetic_facts_coexist_without_coercing_source_or_model(tmp_path):
    source = tmp_path / "Объёмы Ω 'исходник'.xlsx"
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Отделка Ω"
    sheet.append(["Наименование", "Ед. изм.", "Количество"])
    sheet.append(["Исходная позиция", "м²", 12])
    book.save(source)
    book.close()
    catalog = load_tabular_source_catalog(source)
    row = _work(quantity=13, calc_quantity=999, calc_unit="м²",
                conversion_factor=0.5, conversion_source="13 × 0.5")
    before = json.dumps(row, ensure_ascii=False, sort_keys=True)
    payload = _review([row], [row], source_catalog=catalog)
    fact = payload["prior_result_structural_facts"][0]
    assert fact["source_comparison"]["source_quantity"] == 12
    assert fact["source_comparison"]["model_quantity"] == 13
    assert fact["source_comparison"]["errors"]
    assert "conversion_result_mismatch" in {issue["code"] for issue in fact["vor_integrity"]}
    assert catalog.lookup(row["source_row"]).header_quantity == 12
    assert json.dumps(row, ensure_ascii=False, sort_keys=True) == before
    _assert_authored_fields(payload, [row])


def test_explicit_zero_is_not_reported_as_a_missing_work_quantity_in_review():
    row = _work(quantity=0)
    payload = _review([row], [row])
    assert _integrity(payload) == []
    assert payload["prior_model_decisions"][0]["quantity"] == 0


def test_latest_accepted_work_revision_is_used_for_the_complete_review_result():
    older = _work(row_role="material", work_row="missing-operation")
    newer = _work(revision=4)
    material = _material()
    full = app.model_rag_existing_operation_rows([newer], [older, material])
    payload = _review([material], full)
    assert _integrity(payload) == []
    assert full[0] == newer


@pytest.mark.parametrize("calc_unit", ["м / комплект Ω", None, ""])
def test_replay_preserves_literal_or_explicitly_unknown_calculated_unit(calc_unit):
    row = _work(calc_quantity=7, calc_unit=calc_unit)
    before = deepcopy(row)
    payload, _ = app.model_rag_prior_page_context([row], [])
    projected = payload["prior_model_decisions"][0]
    assert "calc_unit" in projected
    assert projected["calc_unit"] == calc_unit
    _assert_authored_fields(payload, [row])
    assert row == before


def test_replay_does_not_invent_calculated_unit_when_the_model_did_not_supply_it():
    row = _work(calc_quantity=7)
    payload, _ = app.model_rag_prior_page_context([row], [])
    assert "calc_unit" not in payload["prior_model_decisions"][0]
    _assert_authored_fields(payload, [row])


@pytest.mark.asyncio
@pytest.mark.parametrize("query_kind", [None, "lsr"])
async def test_first_natural_review_shows_prior_vor_facts_without_forcing_the_new_document_kind(
    tmp_path, monkeypatch, query_kind,
):
    original_rows = [
        _work("S!R2", quantity=12, unit="m", operation_id=""),
        _material("S!R3", parent="not-a-work", quantity=3, unit="m", operation_id=""),
    ]
    run = await fixture._run_sheet(
        tmp_path, monkeypatch, reads=False,
        query_declaration=json.dumps({"artifact_kind": "vor", "queries": []}),
        final_answer=json.dumps({"artifact_kind": "vor", "rows": original_rows}),
    )
    store = WorkbookResearchJobService()
    original_job_id = run.result["retrieval_trace"]["workbook_research_job"]["job_id"]
    original = store.get(original_job_id)
    assert original["task_context"]["artifact_kind_declaration"]["artifact_kind"] == "vor"
    previous = deepcopy(original["accepted_rows"])
    request = inspect.getclosurevars(run.resume_same_request).nonlocals["request"]
    request.req.question = "Перепроверь связи материалов с работами по замечанию инженера"
    declaration = {"queries": ["literal source check"]}
    if query_kind:
        declaration["artifact_kind"] = query_kind
    result_kind = query_kind or "vor"
    reviewed = [{**row, "expected_revision": row["revision"]} for row in previous]
    if result_kind == "lsr":
        for row in reviewed:
            row.update(norm_code="", norm_status="MISSING", gap_reason="no_suitable_candidate",
                       open_gap="Модель не выбрала норму", evidence_refs=["Q1.H1"])
    run.responses.extend([
        InferenceResponse(text=json.dumps(declaration), tool_calls=(), finish_reason="stop", usage={}),
        InferenceResponse(text=json.dumps({"artifact_kind": result_kind, "rows": reviewed}),
                          tool_calls=(), finish_reason="stop", usage={}),
    ])
    old_requests = len(run.requests)
    result = await run.resume_same_request()
    review_requests = run.requests[old_requests:]
    assert len(review_requests) == 2 and not run.responses
    for model_request in review_requests:
        delivered = json.dumps(model_request.messages, ensure_ascii=False)
        assert "invalid_work_relationship" in delivered
        assert "not-a-work" in delivered
        assert previous[1]["operation_id"] in delivered
        assert "vor_integrity" in delivered
    assert result["retrieval_trace"]["chat_refinement"]["status"] == "reviewing"
    assert result["retrieval_trace"]["artifact_target"]["artifact_kind"] == result_kind
    assert run.executions[-1][0]["tool"] == "build_" + result_kind + "_workbook"
    assert store.get(original_job_id)["accepted_rows"] == previous


def test_prior_vor_kind_survives_new_lsr_target_pause_and_plain_continuation(tmp_path):
    database = tmp_path / "review-state.db"
    store = WorkbookResearchJobService(database)

    def identity(question):
        return store.identity(session_id="same-document", attachment_id="attachment",
            source_sha256="a" * 64, dataset_ids=[], profile_revision_id="literal-profile",
            model_identity="same-model", question=question)

    def declaration(kind):
        return {"status": "declared", "artifact_kind": kind, "declarations": [kind], "errors": []}

    locators = ["Отделка Ω!R2", "Отделка Ω!R3"]
    original = store.begin_or_resume(identity("Собери ВОР"), source_locators=locators)
    store.record_packet(original["job_id"], sheet="Отделка Ω", packet_locators=locators,
        accepted_rows=[_work(), _material(parent="not-a-work")], evidence=[], remaining=[])
    store.record_artifact_kind(original["job_id"], declaration=declaration("vor"))
    store.finish(original["job_id"], status="complete")
    remark = "Перепроверь исходные работы и подготовь ЛСР"
    review = store.begin_or_resume(identity(remark), source_locators=locators)
    review = app.begin_workbook_chat_review(store, review, remark, locators)
    event = store.list_events(review["job_id"], "locators_reopened")[-1]
    assert json.loads(json.dumps(event))["payload"]["chat_review"]["prior_artifact_kind"] == "vor"
    prior_rows = deepcopy(store.chat_review_context(review["job_id"])["prior_rows"])
    store.record_artifact_kind(review["job_id"], declaration=declaration("lsr"))
    store.pause(review["job_id"], remaining=locators, phase="model_query_generation_pending")

    reopened_store = WorkbookResearchJobService(database)
    resumed = reopened_store.begin_or_resume(identity("Продолжи"), source_locators=locators)
    context = app.workbook_chat_review_context(reopened_store, resumed)
    assert resumed["task_context"]["model_artifact_kind"] == "lsr"
    assert context["prior_artifact_kind"] == "vor"
    assert context["prior_rows"] == prior_rows
    payload, _ = app.model_rag_prior_page_context([], [],
        review_rows=context["prior_rows"], review_instruction=context["message"],
        prior_artifact_kind=context["prior_artifact_kind"], full_result_rows=context["prior_rows"])
    assert {issue["code"] for issue in _integrity(payload)} == {"invalid_work_relationship"}
    assert reopened_store.get(resumed["job_id"])["task_context"]["model_artifact_kind"] == "lsr"
    assert reopened_store.chat_review_context(resumed["job_id"])["prior_rows"] == prior_rows


def test_legacy_review_without_prior_kind_uses_known_saved_declaration_without_changing_it():
    legacy = {"prior_rows": [_work()], "message": "Перепроверь"}
    reader = SimpleNamespace(chat_review_context=lambda _job_id: deepcopy(legacy))
    job = {"job_id": "legacy-review", "task_context": {"artifact_kind_declaration": {
        "status": "declared", "artifact_kind": "vor"}}}
    before = deepcopy(job)
    context = app.workbook_chat_review_context(reader, job)
    assert context == {**legacy, "prior_artifact_kind": "vor"}
    assert job == before
