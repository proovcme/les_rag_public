"""One shared estimator skill keeps document formation separate from pricing."""
import hashlib
import inspect
import json
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace

import pytest

from proxy.services import chat_evidence_application_service as app
from proxy.services.chat_profile_service import _factory_contracts


SKILL_PATH = Path(__file__).resolve().parents[1] / "skills/smeta/references/rag-estimator.md"


def _skill():
    return SKILL_PATH.read_text(encoding="utf-8").strip()


def _point(number):
    return next(line for line in _skill().splitlines() if line.startswith(f"{number}. "))


def test_search_and_nrsp_requirements_have_document_scope_in_the_shared_skill():
    search = _point(2)
    assert search.startswith("2. Если для текущего документа нужен внешний поиск")
    assert "Для ВОР достаточный исходник не требует поиска норм и цен" in search
    assert "Для подбираемой нормы" in search
    nrsp = _point(8)
    assert nrsp.startswith("8. Для ЛСР или добровольно выбранной для ВОР нормы:")
    assert "В ВОР без выбранной нормы отсутствие НР/СП не является открытым вопросом" in nrsp
    assert "nr_sp_rule_id" in nrsp and "не подставляй процент или правило по памяти" in nrsp


def test_confirmed_zero_and_unknown_have_distinct_meanings_without_role_forcing():
    instruction = _point(7)
    assert "Подтверждённый нулевой объём сохраняй как 0" in instruction
    assert "сам по себе он не делает строку unresolved" in instruction
    assert "пояснение о невыполнении укажи в coverage" in instruction
    assert "неизвестный объём остаётся null" in instruction
    assert "open_gap — только нерешённый вопрос" in instruction


@pytest.mark.parametrize("artifact_kind", ["vor", "lsr", ""])
def test_factory_and_bound_result_prompts_use_the_same_scoped_professional_skill(artifact_kind):
    skill = _skill()
    assert _factory_contracts()["estimator"]["skill"].strip() == skill
    snapshot = {"mode": "estimator", "prompt_text": "Literal role Ω", "skill_text": skill,
                "model_policy": {"temperature": 0.15}, "tools": ["read_source"]}
    before = deepcopy(snapshot)
    bound = app.overlay_tabular_estimator_snapshot(snapshot)
    prompt = app.profile_system_prompt(bound, strict=False, purpose="workbook_result",
                                       artifact_kind=artifact_kind)
    assert prompt.count(skill) == 1
    assert "Literal role Ω" in prompt
    assert bound["model_policy"] == snapshot["model_policy"]
    assert snapshot == before
    assert bound["effective_skill_modules"][0]["sha256"] == hashlib.sha256(skill.encode()).hexdigest()


def test_instruction_keeps_model_authorship_no_automatic_installation_and_source_basis():
    skill = _skill()
    for rule in ("Не назначай автоматически отдельный монтаж каждому изделию",
                 "Один исходный locator может обосновывать несколько операций и изделие",
                 "с реальными связями", "Количество из исходника сохраняй",
                 "производный объём требует формулы и источника",
                 "Для выбранной нормы явно верни action_match, object_match, condition_match"):
        assert rule in skill


def test_exact_factory_managed_skill_is_replaced_only_for_the_turn_with_truthful_provenance():
    previous = "Bound historical factory skill Ω\nNo custom text."
    previous_sha = hashlib.sha256(previous.encode()).hexdigest()
    snapshot = {"mode": "estimator", "prompt_text": "Bound role Ω",
                "skill_revision_id": "factory:skill:estimator:base",
                "skill_text": previous, "skill_sha256": previous_sha,
                "model_policy": {"temperature": 0.2}, "tools": ["read_source"]}
    before = deepcopy(snapshot)
    effective = app.overlay_tabular_estimator_snapshot(snapshot)
    assert effective["skill_text"] == _skill()
    assert previous not in effective["skill_text"]
    assert snapshot == before
    assert effective["skill_revision_id"] == snapshot["skill_revision_id"]
    assert effective["skill_sha256"] == previous_sha, "the saved binding was not republished"
    assert effective["model_policy"] == snapshot["model_policy"]
    module = effective["effective_skill_modules"][0]
    assert module["source"] == "factory_managed_turn_overlay"
    assert module["sha256"] == hashlib.sha256(_skill().encode()).hexdigest()
    assert module["replaced_managed_skill_revision_id"] == snapshot["skill_revision_id"]
    assert module["replaced_managed_skill_sha256"] == previous_sha
    assert module["saved_snapshot_modified"] is False


@pytest.mark.parametrize("revision", ["user:skill:estimator:custom", "factory:skill:agent:base",
                                      "factory:skill:estimator:base:copy", "", None])
def test_custom_or_other_skill_provenance_never_triggers_a_factory_replacement(revision):
    custom = "Literal custom Ω: factory:skill:estimator:base\n# Сметчик: исходник → работы → ЛСР"
    snapshot = {"mode": "estimator", "prompt_text": "Custom role",
                "skill_revision_id": revision, "skill_text": custom,
                "skill_sha256": hashlib.sha256(custom.encode()).hexdigest()}
    before = deepcopy(snapshot)
    effective = app.overlay_tabular_estimator_snapshot(snapshot)
    assert effective["skill_text"] == custom + "\n\n" + _skill()
    assert snapshot == before
    module = effective["effective_skill_modules"][0]
    assert module["source"] == "tabular_attachment_estimator_path_v1"
    assert "replaced_managed_skill_revision_id" not in module
    assert "replaced_managed_skill_sha256" not in module


def test_custom_skill_that_already_contains_current_contract_is_preserved_literally():
    custom = "\tCustom before Ω\n\n" + _skill() + "\n\nCustom after Ω\t"
    snapshot = {"mode": "estimator", "skill_revision_id": "user:skill:custom", "skill_text": custom}
    before = deepcopy(snapshot)
    effective = app.overlay_tabular_estimator_snapshot(snapshot)
    assert effective["skill_text"] == custom
    assert effective["skill_text"].count(_skill()) == 1
    assert snapshot == before


@pytest.mark.asyncio
async def test_admitted_review_resolves_pending_before_the_packet_stall_guard(tmp_path, monkeypatch):
    """The real durable merge, rather than a retained baseline, decides progress."""
    from proxy.services.openai_compatible_transport_service import InferenceResponse
    from proxy.services.workbook_research_job_service import WorkbookResearchJobService
    from tests import test_model_rag_sheet_evidence_reads as fixture

    original_rows = [{"source_row": locator, "row_role": "work", "title": title,
                      "unit": "m", "quantity": quantity, "open_gap": ""}
                     for locator, title, quantity in [("S!R2", "Cable A", 12), ("S!R3", "Cable B", 3)]]
    query = json.dumps({"artifact_kind": "vor", "queries": []})
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=False,
        query_declaration=query, final_answer=json.dumps({"artifact_kind": "vor", "rows": original_rows}))
    store = WorkbookResearchJobService()
    original_id = run.result["retrieval_trace"]["workbook_research_job"]["job_id"]
    original = store.get(original_id)
    before = deepcopy(original["accepted_rows"])
    request = inspect.getclosurevars(run.resume_same_request).nonlocals["request"]
    request.req.question = "Учти замечание инженера и перепроверь документ"
    reviewed_rows = [{**{key: row[key] for key in (
        "source_row", "row_role", "title", "unit", "quantity", "operation_id")},
        "expected_revision": row["revision"]} for row in before]
    run.responses.extend([
        InferenceResponse(text=query, tool_calls=(), finish_reason="stop", usage={}),
        InferenceResponse(text=json.dumps({"artifact_kind": "vor", "rows": reviewed_rows}),
                          tool_calls=(), finish_reason="stop", usage={}),
    ])
    monkeypatch.setattr(app, "_ROW_PACKET_MAX_ATTEMPTS", 1)
    deferred = []
    original_defer = WorkbookResearchJobService.defer_locators

    def record_deferral(self, *args, **kwargs):
        deferred.append(kwargs)
        return original_defer(self, *args, **kwargs)

    monkeypatch.setattr(WorkbookResearchJobService, "defer_locators", record_deferral)
    result = await run.resume_same_request()
    trace = result["retrieval_trace"]
    reviewed = store.get(trace["workbook_research_job"]["job_id"])
    assert WorkbookResearchJobService.pending_research_locators(reviewed) == set()
    assert reviewed["remaining"] == []
    assert not deferred, "a durable admitted review must not be deferred as no progress"
    assert trace["tool_loop"]["passes"][-1]["newly_decided"] == 2
    assert not run.responses, "resolving the review must not buy another model cycle"
    assert store.get(original_id)["accepted_rows"] == before


def test_saved_applicability_prose_is_feedback_as_unknown_without_changing_authored_rows_or_quotes():
    prose = "Состав включает демонтаж и монтаж панелей"
    row = {"source_row": "PDF!R16", "operation_id": "authored-operation", "row_role": "work",
           "title": "Демонтаж потолка с сохранением", "quantity": 15, "unit": "м2",
           "norm_code": "ГЭСНр63-03-008-02", "norm_status": "EXACT_VERIFIED",
           "action_match": "yes", "object_match": "no", "condition_match": "unknown",
           "composition_covers": prose, "coverage": "Literal authored coverage Ω",
           "evidence_refs": ["Q51.H1"], "evidence_bindings": {"Q51.H1": "saved-card"}}
    card = SimpleNamespace(content="ГЭСНр63-03-008-02\n01. Демонтаж панелей.\n02. Монтаж панелей.",
                           doc_name="cards", doc_id="card", meta={
                               "global_evidence_id": "saved-card", "model_evidence_ref": "Q51.H1"})
    before = deepcopy(row)
    original_content = card.content
    payload, retained = app.model_rag_prior_page_context([row], [card])
    applicability = payload["prior_result_structural_facts"][0]["applicability_fields"]
    assert applicability["accepted_values"] == ["yes", "no", "unknown"]
    assert applicability["explanation_field"] == "coverage"
    assert applicability["fields"] == {
        "action_match": {"authored": "yes", "read_as": "yes"},
        "object_match": {"authored": "no", "read_as": "no"},
        "condition_match": {"authored": "unknown", "read_as": "unknown"},
        "unit_compatible": {"authored": None, "read_as": "missing"},
        "composition_covers": {"authored": prose, "read_as": "unknown"},
    }
    decision = payload["prior_model_decisions"][0]
    for field, value in before.items():
        assert decision[field] == value
    assert row == before and card.content == original_content and retained == [card]
    assert payload["previously_shown_cited_evidence"] == [{
        "ref": "Q51.H1", "global_evidence_id": "saved-card", "content": original_content}]
    instruction = payload["evidence_continuation_instruction"]
    assert "Контракт полей — yes/no/unknown" in instruction
    assert "пояснения состава и применимости указываются в coverage" in instruction


@pytest.mark.parametrize("norm_code, flags", [("", {"action_match": "unknown"}),
                                               ("—", {"composition_covers": "Состав включает"}),
                                               ("ГЭСН01-01-001-01", {})])
def test_no_applicability_feedback_without_selected_norm_and_authored_flags(norm_code, flags):
    row = {"source_row": "Документ Ω!R3", "row_role": "work", "title": "Исходная работа",
           "quantity": None, "unit": "м", "norm_code": norm_code, **flags}
    before = deepcopy(row)
    payload, retained = app.model_rag_prior_page_context([row], [])
    assert not any("applicability_fields" in fact for fact in payload["prior_result_structural_facts"])
    assert "applicability_fields" not in payload["evidence_continuation_instruction"]
    assert row == before and retained == []
    assert "open_gap" not in payload["prior_model_decisions"][0]


def _indexed_work(source="S!R2", operation_id="saved-parent-operation", **changes):
    return {"source_row": source, "operation_id": operation_id, "revision": 3,
            "row_role": "work", "title": "Сохранённая моделью работа Ω — исходное название",
            "unit": "м²", "quantity": 12, "norm_code": "MODEL-SELECTED", "norm_status": "CONFLICT",
            **changes}


def _work_index(payload):
    index = payload.get("accepted_work_index", {"columns": [], "records": []})
    return [dict(zip(index["columns"], values, strict=True)) for values in index["records"]]


def test_current_material_sees_exact_saved_parent_outside_its_packet_without_graph_or_quote_changes():
    parent = _indexed_work(quantity=0)
    material = {"source_row": "S!R15", "operation_id": "saved-material", "revision": 2,
                "row_role": "material", "title": "Авторский материал", "quantity": None, "unit": "м²",
                "work_row": "S!R2", "covered_by_work_id": parent["operation_id"],
                "evidence_refs": ["Q9.H4"], "evidence_bindings": {"Q9.H4": "literal-card"}}
    card = SimpleNamespace(content="Дословная карточка Ω\nНи название, ни количество не сокращены.",
                           doc_name="cards", doc_id="card", meta={
                               "global_evidence_id": "literal-card", "model_evidence_ref": "Q9.H4"})
    full = [parent, material]
    before = deepcopy(full)
    payload, retained = app.model_rag_prior_page_context([material], [card], full_result_rows=full)
    assert _work_index(payload) == [{key: parent[key] for key in payload["accepted_work_index"]["columns"]}]
    assert payload["prior_model_decisions"][0]["quantity"] is None
    assert payload["prior_model_decisions"][0]["work_row"] == "S!R2"
    assert payload["previously_shown_cited_evidence"][0]["content"] == card.content
    assert full == before and retained == [card]
    assert "пересмотр закрытых работ" in payload["accepted_work_index_scope"]
    assert "не является новой карточкой нормы" in payload["accepted_work_index_scope"]


def test_work_index_is_reference_only_and_omits_current_ids_and_non_work_roles():
    current = _indexed_work(revision=4)
    older_same_id = _indexed_work(revision=3, title="Устаревшее название текущей операции")
    same_anchor_other_work = _indexed_work(operation_id="another-work-at-same-source", quantity=None)
    non_works = [_indexed_work(f"S!R{index + 20}", operation_id=f"not-work-{role}", row_role=role)
                 for index, role in enumerate(["material", "equipment", "header", "unresolved"])]
    payload, _ = app.model_rag_prior_page_context([current], [],
        full_result_rows=[older_same_id, same_anchor_other_work, *non_works])
    assert [row["operation_id"] for row in _work_index(payload)] == [same_anchor_other_work["operation_id"]]
    assert _work_index(payload)[0]["quantity"] is None
    assert payload["prior_model_decisions"][0]["revision"] == 4
    assert "open_gap" not in payload["prior_model_decisions"][0]


def test_work_index_is_absent_without_full_result_or_without_other_explicit_works():
    row = _indexed_work()
    for full in ([], [row], [{**row, "row_role": "material"}]):
        payload, _ = app.model_rag_prior_page_context([row], [], full_result_rows=full)
        assert "accepted_work_index" not in payload
        assert "accepted_work_index_scope" not in payload


@pytest.mark.asyncio
async def test_fresh_later_packet_gets_accepted_work_index_even_without_same_packet_prior_rows(tmp_path, monkeypatch):
    from tests import test_model_rag_sheet_evidence_reads as fixture

    rows = [_indexed_work("S!R2", operation_id="", norm_code="", norm_status="", unit="m", quantity=12),
            _indexed_work("S!R3", operation_id="", norm_code="", norm_status="", unit="m", quantity=3)]
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=False, packet_count=2,
        query_declaration=json.dumps({"artifact_kind": "vor", "queries": []}),
        final_answer=json.dumps({"artifact_kind": "vor", "rows": rows}))
    # The first source packet has no saved work; the next query and answer do.
    assert "accepted_work_index" not in str(run.requests[0].messages)
    index_payloads = []
    for request in run.requests[2:]:
        for message in request.messages:
            for line in str(message["content"]).splitlines():
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict) and payload.get("accepted_work_index"):
                    index_payloads.append(payload)
    assert len(index_payloads) == len(run.requests) - 2, (
        "each later query, reader call and answer needs the accepted graph, not only same-packet replay")
    for payload in index_payloads:
        assert payload["prior_model_decisions"] == []
        indexed = _work_index(payload)
        assert [row["source_row"] for row in indexed] == ["S!R2", "S!R3"]
        assert all(row["operation_id"] for row in indexed)
        assert [row["quantity"] for row in indexed] == [12, 3]
    assert not run.responses


def test_318_literal_work_index_fits_query_and_answer_governors_at_observed_131k_context():
    from proxy.services.context_governor_service import ContextKind
    from proxy.services.model_execution_preset_service import ModelExecutionPreset

    title = 'Авторская работа Ω "дословно" по разделу, условия монтажа и расположение; ' * 4
    full = [_indexed_work(f"Раздел {index // 32}!R{index + 2}", operation_id=f"literal-operation-{index}",
                          title=title + str(index), quantity=0 if index == 0 else None if index == 1 else index / 10)
            for index in range(318)]
    before = deepcopy(full)
    payload, _ = app.model_rag_prior_page_context([], [], full_result_rows=full)
    preset = ModelExecutionPreset("observed-131k", "fixture", 131072, 16384, 2048,
                                  5, 6, 6, 1, False, ("observed_backend_capacity",))
    snapshot = {"mode": "estimator", "skill_text": _skill(), "prompt_text": "Инженер по исходным данным"}
    source = {"requested_source_rows": ["Новый раздел!R15"], "source_quantity_cells": [
        {"source_row": "Новый раздел!R15", "quantity": 12, "unit": "м²"}]}
    common = dict(preset=preset, request_payload={"question": "Собери ВОР"}, required_evidence=[source, payload])
    _, query_packet = app.govern_model_query_messages(retrieval_trace={}, purpose="query",
        profile_prefix=app.profile_system_prompt(snapshot, strict=False, purpose="query"), **common)
    _, answer_packet = app.govern_inference_messages(
        profile_prefix=app.profile_system_prompt(snapshot, strict=False, purpose="workbook_result",
                                                artifact_kind="vor"), **common)
    for packet in (query_packet, answer_packet):
        evidence = [obj.payload for section in packet.sections
                    if section.kind in {ContextKind.EVIDENCE, ContextKind.CURRENT_READ_FRAME}
                    for obj in section.objects]
        assert evidence == [source, payload]
        indexed = _work_index(evidence[1])
        assert len(indexed) == 318
        for row, original in zip(indexed, full, strict=True):
            assert row == {key: original[key] for key in payload["accepted_work_index"]["columns"]}
        assert not packet.omissions
    assert full == before
