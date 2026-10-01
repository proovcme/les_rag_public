"""A new remark is heard by the model; a plain resume keeps durable progress."""
import hashlib

import pytest

from proxy.services.chat_evidence_application_service import (
    begin_workbook_chat_review,
    workbook_chat_review_needed,
    compact_estimator_draft_rows,
    profile_system_prompt,
)
from proxy.services.workbook_research_job_service import WorkbookResearchJobService
from proxy.services import chat_evidence_application_service as application
from types import SimpleNamespace


def job():
    return {"continues_job_id": "parent", "accepted_rows": [{"source_row": "Лист 1!R14"}],
            "task_context": {"original_question": "Собери ЛСР, Москва, 3 квартал 2026"}}


@pytest.mark.parametrize("question", ["Продолжи", "Продолжить!", "continue",
    "Продолжи это же задание по тому же прикреплённому документу.",
    "Собери ЛСР, Москва, 3 квартал 2026"])
def test_plain_resume_does_not_restart_model_research(question):
    assert not workbook_chat_review_needed(question, job())


@pytest.mark.parametrize("question", ["Добери нормы", "Перепроверь позиции 14, 15",
    "Для первой работы изменились условия монтажа", "Продолжи, учти новое замечание"])
def test_freeform_remark_is_not_silently_repacked(question):
    assert workbook_chat_review_needed(question, job())


def test_estimator_response_contract_requests_every_applicability_flag_without_a_skill():
    prompt = profile_system_prompt({"mode": "estimator", "prompt_text": "Select with evidence", "skill_text": ""}, strict=False)
    for field in ("action_match", "object_match", "condition_match", "unit_compatible", "composition_covers"):
        assert field in prompt
    assert "unknown" in prompt


def test_previous_decisions_keep_all_five_flags_and_citations_for_the_normal_model_pass():
    row = {"source_row": "Лист!R14", "evidence_refs": ["Q1.H1"],
           "action_match": "yes", "object_match": "no", "condition_match": "unknown",
           "unit_compatible": "yes", "composition_covers": "no"}
    projected, = compact_estimator_draft_rows([row])
    assert all(projected[key] == value for key, value in row.items())


def test_legacy_parent_without_task_text_still_hears_a_new_remark():
    current = job()
    current["task_context"]["original_question"] = "Добери нормы"
    event = {"payload": {"parent_question_sha256": hashlib.sha256("Собери ЛСР".encode()).hexdigest()}}
    assert workbook_chat_review_needed("Добери нормы", current, [event])


def test_review_is_durable_without_model_planning_and_preserves_operator_data(tmp_path):
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    identity = service.identity(session_id="s", attachment_id="read_doc", source_sha256="a" * 64,
        dataset_ids=[], profile_revision_id="p", model_identity="35b", question="Добери нормы")
    current = service.begin_or_resume(identity)
    rows = [{"source_row": "Лист 1!R14", "title": "Первая работа", "row_role": "work"},
            {"source_row": "Лист 1!R15", "title": "Вторая работа", "row_role": "work"}]
    service.record_packet(current["job_id"], sheet="Лист 1", packet_locators=[r["source_row"] for r in rows],
                          accepted_rows=rows, evidence=[], remaining=[])
    service.record_overrides(current["job_id"], {"Лист 1!R14": {"confirmed_price": 123}})
    service.finish(current["job_id"], status="complete")
    saved_rows = service.get(current["job_id"])["accepted_rows"]
    reopened = begin_workbook_chat_review(service, current, "Добери нормы", ["Лист 1!R14", "Лист 1!R15"])
    assert reopened["accepted_rows"] == []
    assert reopened["remaining"] == ["Лист 1!R14", "Лист 1!R15"]
    assert reopened["operator_overrides"]["Лист 1!R14"]["confirmed_price"] == 123
    events = service.list_events(current["job_id"], "locators_reopened")
    assert events[-1]["payload"]["prior_rows"][0]["title"] == "Первая работа"
    assert events[-1]["payload"]["chat_review"]["decision_author"] == "user"
    assert events[-1]["payload"]["chat_review"]["review_scope"] == "document"
    assert events[-1]["payload"]["prior_rows"] == saved_rows
    repeated = job()
    assert not workbook_chat_review_needed("Добери нормы", repeated, events)


def _review_checkpoint(tmp_path):
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    def identity(question):
        return service.identity(session_id="review", attachment_id="read_review", source_sha256="b" * 64,
            dataset_ids=[], profile_revision_id="p", model_identity="35b", question=question)
    job = service.begin_or_resume(identity("Собери ВОР"))
    service.record_packet(job["job_id"], sheet="Схема", packet_locators=["Схема!R14", "Схема!R15"],
        accepted_rows=[{"source_row": "Схема!R14", "row_role": "work", "title": "Монтаж",
                        "evidence_refs": ["Q1.H1"], "evidence_bindings": {"Q1.H1": "saved-card"}},
                       {"source_row": "Схема!R15", "row_role": "material", "title": "Материал"}],
        evidence=[], remaining=[])
    service.finish(job["job_id"], status="complete")
    published = service.get(job["job_id"])["accepted_rows"]
    review = service.begin_or_resume(identity("Исправь объёмы по исходнику"))
    review = begin_workbook_chat_review(service, review, "Исправь объёмы по исходнику", ["Схема!R14", "Схема!R15"])
    assert review["accepted_rows"] == []
    return service, identity, review, published


def test_reopened_operation_can_keep_its_published_identity(tmp_path):
    service, _, review, published = _review_checkpoint(tmp_path)
    prior = service.list_events(review["job_id"], "locators_reopened")[-1]["payload"]["prior_rows"]
    changed = {**published[0], "title": "Уточнённый монтаж"}
    errors = application.validate_model_rag_result_structure([changed], [], expected_source_rows=1,
        validate_evidence_refs=False, existing_operation_rows=review["accepted_rows"], review_operation_rows=prior)
    assert not any("operation_" in error for error in errors)
    for bad, prefix in (({**changed, "operation_id": "invented"}, "unknown_operation_id:"),
                        ({**changed, "source_row": "Схема!R15"}, "operation_source_mismatch:")):
        errors = application.validate_model_rag_result_structure([bad], [], expected_source_rows=1,
            validate_evidence_refs=False, existing_operation_rows=[], review_operation_rows=prior)
        assert any(error.startswith(prefix) for error in errors)
    assert published[0]["title"] == "Монтаж"
    saved = service.record_packet(review["job_id"], sheet="Схема", packet_locators=["Схема!R14"],
        accepted_rows=[changed], evidence=[], remaining=["Схема!R15"])
    assert saved["accepted_rows"][0]["operation_id"] == published[0]["operation_id"]
    assert saved["accepted_rows"][0]["revision"] == published[0]["revision"] + 1
    assert len(saved["accepted_rows"]) == 1


def test_review_resume_retains_instruction_identity_and_exact_cited_card(tmp_path):
    service, identity, review, published = _review_checkpoint(tmp_path)
    resumed = service.begin_or_resume(identity("Продолжи"))
    assert resumed["continues_job_id"] == review["job_id"]
    assert service.list_events(resumed["job_id"], "locators_reopened") == []
    context = application.workbook_chat_review_context(service, resumed)
    assert context["prior_rows"] == published
    assert context["message"] == "Исправь объёмы по исходнику"
    card = SimpleNamespace(content="Полное прежнее доказательство", doc_id="card", doc_name="cards",
        meta={"global_evidence_id": "saved-card", "model_evidence_ref": "Q1.H1"})
    payload, retained = application.model_rag_prior_page_context([], [card], review_rows=context["prior_rows"],
        review_instruction=context["message"])
    assert payload["prior_model_decisions"][0]["operation_id"] == published[0]["operation_id"]
    assert payload["review_instruction"] == context["message"]
    assert retained == [card]
    assert payload["previously_shown_cited_evidence"][0]["content"] == card.content


def test_new_remark_during_partial_review_does_not_lose_unreviewed_baseline(tmp_path):
    service, identity, review, published = _review_checkpoint(tmp_path)
    service.record_packet(review["job_id"], sheet="Схема", packet_locators=["Схема!R14"],
        accepted_rows=[{**published[0], "title": "Исправленный монтаж"}], evidence=[], remaining=["Схема!R15"])
    next_review = service.begin_or_resume(identity("Также уточни материал"))
    begin_workbook_chat_review(service, next_review, "Также уточни материал", ["Схема!R14", "Схема!R15"])
    prior = service.list_events(next_review["job_id"], "locators_reopened")[-1]["payload"]["prior_rows"]
    assert len(prior) == 2
    assert prior[0]["title"] == "Исправленный монтаж"
    assert prior[1] == published[1]
    assert service.get(next_review["job_id"])["accepted_rows"] == []


def test_new_review_after_completed_result_does_not_restore_removed_old_operations(tmp_path):
    service, identity, review, published = _review_checkpoint(tmp_path)
    service.record_packet(review["job_id"], sheet="Схема", packet_locators=["Схема!R14", "Схема!R15"],
        accepted_rows=[published[0]], evidence=[], remaining=[])
    service.finish(review["job_id"], status="complete")
    next_review = service.begin_or_resume(identity("Проверь готовый результат"))
    begin_workbook_chat_review(service, next_review, "Проверь готовый результат", ["Схема!R14", "Схема!R15"])
    prior = service.chat_review_context(next_review["job_id"])["prior_rows"]
    assert len(prior) == 1
    assert prior[0]["operation_id"] == published[0]["operation_id"]


def test_operator_confirmations_survive_new_review_and_resume_job(tmp_path):
    service, identity, review, published = _review_checkpoint(tmp_path)
    service.record_overrides(review["job_id"], {"Схема!R14": {"confirmed_price": 12.5}})
    resumed = service.begin_or_resume(identity("Продолжи"))
    assert resumed["operator_overrides"]["Схема!R14"]["confirmed_price"] == 12.5
    reopened = begin_workbook_chat_review(service, resumed, "Уточни условия", ["Схема!R14", "Схема!R15"])
    assert reopened["operator_overrides"] == resumed["operator_overrides"]
