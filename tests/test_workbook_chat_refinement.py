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
