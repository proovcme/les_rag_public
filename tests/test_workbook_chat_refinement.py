"""A new remark is heard by the model; a plain resume keeps durable progress."""
import hashlib
import json

import pytest

from proxy.services.chat_evidence_application_service import (
    parse_workbook_chat_review,
    workbook_chat_review_needed,
    workbook_chat_review_rows,
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


def test_review_scope_is_model_owned_and_exact_not_a_domain_heuristic():
    plan = parse_workbook_chat_review(json.dumps({
        "revisit_locators": ["Лист 1!R14", "Лист 1!R14"], "message": "Перепроверю эту работу",
    }), ["Лист 1!R14", "Другой!R15"])
    assert plan["revisit_locators"] == ["Лист 1!R14"]
    with pytest.raises(ValueError, match="UNKNOWN_ROW"):
        parse_workbook_chat_review('{"revisit_locators":["R99"],"message":"review"}', ["R14"])
    with pytest.raises(ValueError, match="INVALID"):
        parse_workbook_chat_review('{"revisit_locators":[],"message":"ok","norm_code":"invented"}', [])


def test_empty_scope_explains_ambiguity_without_opening_any_row():
    plan = parse_workbook_chat_review('```json\n{"revisit_locators":[],"message":"Уточните номер раздела"}\n```', ["R14"])
    assert plan["revisit_locators"] == []
    assert plan["message"] == "Уточните номер раздела"


def test_legacy_parent_without_task_text_still_hears_a_new_remark():
    current = job()
    current["task_context"]["original_question"] = "Добери нормы"
    event = {"payload": {"parent_question_sha256": hashlib.sha256("Собери ЛСР".encode()).hexdigest()}}
    assert workbook_chat_review_needed("Добери нормы", current, [event])


def test_large_review_inventory_keeps_all_rows_and_links_without_card_body_duplication():
    rows = [{"source_row": f"Раздел!R{i}", "title": "Монтаж оборудования",
             "quantity": 2, "unit": "шт", "row_role": "work", "norm_code": "ГЭСНм10-01-001-01",
             "work_row": "Раздел!R1", "object_match": "unknown",
             "_evidence_check": {"body": "card text " * 2000}} for i in range(1, 401)]
    projected = workbook_chat_review_rows(rows)
    assert len(projected) == 400
    assert projected[399]["source_row"] == "Раздел!R400"
    assert projected[399]["norm_code"] == rows[399]["norm_code"]
    assert projected[399]["work_row"] == "Раздел!R1"
    assert "_evidence_check" not in projected[399]
    assert len(json.dumps(projected, ensure_ascii=False)) < 110000


def test_review_plan_is_durable_and_preserves_prior_decisions_and_operator_data(tmp_path):
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
    note = {"request_sha256": hashlib.sha256("Добери нормы".encode()).hexdigest(),
            "message": "Пересмотр выбран моделью", "decision_author": "model"}
    reopened = service.reopen_locators(current["job_id"], ["Лист 1!R14"], chat_review=note)
    assert [r["source_row"] for r in reopened["accepted_rows"]] == ["Лист 1!R15"]
    assert reopened["remaining"] == ["Лист 1!R14"]
    assert reopened["operator_overrides"]["Лист 1!R14"]["confirmed_price"] == 123
    events = service.list_events(current["job_id"], "locators_reopened")
    assert events[-1]["payload"]["prior_rows"][0]["title"] == "Первая работа"
    assert events[-1]["payload"]["chat_review"] == note
    repeated = job()
    assert not workbook_chat_review_needed("Добери нормы", repeated, events)
