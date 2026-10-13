"""Durable request survives failed first packaging, resume, and repricing."""
import copy

import pytest

from proxy.services.workbook_research_job_service import WorkbookResearchJobService
from proxy.services.lsr_workbook_adapter_service import (
    explicit_estimate_pricebook,
    requested_price_basis,
)
from proxy.services.chat_evidence_application_service import (
    task_document_price_basis,
    workbook_packaging_args,
    workbook_packaging_tool,
    workbook_packaging_lineage,
    workbook_model_question,
)


def identity(service, question, source="a" * 64):
    return service.identity(
        session_id="s", attachment_id="read_doc", source_sha256=source,
        dataset_ids=["norms"], profile_revision_id="factory", model_identity="35b",
        question=question,
    )


def test_no_decisions_first_turn_still_preserves_request_after_restart(tmp_path):
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    question = "Собери ЛСР, Санкт-Петербург, цены 3 квартал 2026"
    first = service.begin_or_resume(identity(service, question), task_context={
        "original_question": question, "price_basis": requested_price_basis(question),
    })
    assert first["accepted_rows"] == []
    restarted = WorkbookResearchJobService(tmp_path / "meta.db")
    continuation = restarted.begin_or_resume(identity(restarted, "Продолжи"), task_context={
        "original_question": "Продолжи", "price_basis": {},
    })
    assert continuation["task_context"]["original_question"] == question
    basis = task_document_price_basis(continuation)
    args = workbook_packaging_args(
        packaging_tool="build_lsr_workbook", attachment_id="read_doc",
        question="Продолжи", decisions=[], operator_overrides={},
        document_price_basis=basis,
    )
    selected = explicit_estimate_pricebook(
        requested_book="", operator_book="", region_text="", question_text="Продолжи",
        source_text="", source_name="", pricebooks=["sankt-peterburg_3kv2026"],
        document_basis=args["document_price_basis"],
    )
    assert selected["pricebook"] == "sankt-peterburg_3kv2026"
    assert selected["requested_region"] == "Санкт-Петербург"


def test_new_price_period_cannot_reuse_old_book(tmp_path):
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    first_q = "Москва, цены 3 квартал 2026"
    service.begin_or_resume(identity(service, first_q), task_context={
        "original_question": first_q, "price_basis": requested_price_basis(first_q),
    })
    q = "Пересчитай на 4 квартал 2026"
    job = service.begin_or_resume(identity(service, q), task_context={
        "original_question": q, "price_basis": requested_price_basis(q),
    })
    basis = task_document_price_basis(job, {
        "pricebook": "moskva_3kv2026", "region": "Москва", "quarter": "3 квартал 2026",
    })
    assert basis["region"] == "Москва"
    assert basis["quarter"] == "4 квартал 2026"
    assert not basis["pricebook"]
    selected = explicit_estimate_pricebook(
        requested_book="", operator_book="", region_text="", question_text=q,
        source_text="", source_name="", pricebooks=["moskva_3kv2026"], document_basis=basis,
    )
    assert not selected["pricebook"]
    assert selected["requested_quarter"] == "4:2026"


def test_replacement_attachment_does_not_inherit_price_request(tmp_path):
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    q = "Москва, цены 3 квартал 2026"
    service.begin_or_resume(identity(service, q), task_context={
        "original_question": q, "price_basis": requested_price_basis(q),
    })
    replaced = service.begin_or_resume(identity(service, "Собери ЛСР", "b" * 64))
    assert task_document_price_basis(replaced) == {}


def test_vor_target_survives_remark_restart_and_plain_resume(tmp_path):
    tools = ["build_vor_workbook", "build_lsr_workbook"]
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    service.begin_or_resume(identity(service, "Собери ВОР"), task_context={
        "original_question": "Собери ВОР", "artifact_intent": "vor",
    })
    service.begin_or_resume(identity(service, "Исправь объёмы"), task_context={
        "original_question": "Исправь объёмы", "artifact_intent": "both",
    })
    restarted = WorkbookResearchJobService(tmp_path / "meta.db")
    resumed = restarted.begin_or_resume(identity(restarted, "Продолжи"), task_context={
        "original_question": "Продолжи", "artifact_intent": "both",
    })
    assert workbook_packaging_tool(tools, "Продолжи", task_context=resumed["task_context"]) == ["build_vor_workbook"]


def test_explicit_lsr_conversion_changes_target_for_later_resume(tmp_path):
    tools = ["build_vor_workbook", "build_lsr_workbook"]
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    service.begin_or_resume(identity(service, "Собери ВОР"), task_context={
        "original_question": "Собери ВОР", "artifact_intent": "vor",
    })
    converted = service.begin_or_resume(identity(service, "Собери ЛСР из ВОР"), task_context={
        "original_question": "Собери ЛСР из ВОР", "artifact_intent": "lsr",
    })
    assert converted["task_context"]["original_question"] == "Собери ВОР"
    resumed = service.begin_or_resume(identity(service, "Продолжи"), task_context={
        "original_question": "Продолжи", "artifact_intent": "both",
    })
    assert workbook_packaging_tool(tools, "Продолжи", task_context=resumed["task_context"]) == ["build_lsr_workbook"]
    assert workbook_packaging_tool(tools, "Собери ВОР", task_context=resumed["task_context"]) == ["build_vor_workbook"]


def test_legacy_task_without_target_uses_original_operator_request():
    assert workbook_packaging_tool(["build_vor_workbook", "build_lsr_workbook"], "Продолжи",
        task_context={"original_question": "Собери ВОР по проекту"}) == ["build_vor_workbook"]


def test_model_continuation_receives_original_task_and_current_user_message():
    original = "Собери ВОР по проекту, отдельно материалы и необходимые работы"
    question = workbook_model_question("Продолжи", {"task_context": {"original_question": original, "artifact_intent": "vor"}})
    assert original in question and "Продолжи" in question and "vor" in question
    assert workbook_model_question(original, {"task_context": {"original_question": original}}) == original
    assert workbook_model_question("Собери ЛСР", None) == "Собери ЛСР"


@pytest.mark.parametrize("prefix,suffix", [
    ("", "\n"), ("", "\r\n"), (" \t", ""), (" \t", "\r\n"), ("\u00a0", "\u00a0"),
])
def test_same_task_with_boundary_whitespace_keeps_literal_current_without_resume_wrapper(prefix, suffix):
    original = "Собери ВОР по проекту Ω\nМатериалы и работы отдельно"
    current = prefix + original + suffix
    job = {"task_context": {"original_question": original, "artifact_intent": "vor",
                            "price_basis": {"region": "Санкт-Петербург"}}}
    before = copy.deepcopy(job)

    result = workbook_model_question(current, job)

    assert result.encode("utf-8") == current.encode("utf-8")
    assert job == before
    # A legacy saved task may carry the padding instead of the current request.
    padded_job = {"task_context": {"original_question": current}}
    assert workbook_model_question(original, padded_job) == original


@pytest.mark.parametrize("current", [
    "Собери ЛСР\nМатериалы отдельно",
    "собери ВОР\nМатериалы отдельно",
    "Материалы отдельно\nСобери ВОР",
    "Собери  ВОР\nМатериалы отдельно",
])
def test_changed_task_content_still_keeps_original_and_literal_current(current):
    original = "Собери ВОР\nМатериалы отдельно"
    current = " \t" + current + "\r\n"
    job = {"task_context": {"original_question": original, "artifact_intent": "vor"}}
    before = copy.deepcopy(job)

    result = workbook_model_question(current, job)

    assert f"Исходное задание пользователя:\n{original}\n\n" in result
    assert f"Текущее сообщение пользователя:\n{current}\n\n" in result
    assert '"artifact_intent": "vor"' in result
    assert job == before


def test_model_continuation_sees_new_effective_price_request_after_repricing(tmp_path):
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    original = "Собери ЛСР, Санкт-Петербург, цены 3 квартал 2026"
    service.begin_or_resume(identity(service, original), task_context={"original_question": original,
        "price_basis": requested_price_basis(original), "artifact_intent": "lsr"})
    changed = "Пересчитай, Москва, 4 квартал 2026"
    service.begin_or_resume(identity(service, changed), task_context={"original_question": changed,
        "price_basis": requested_price_basis(changed)})
    resumed = service.begin_or_resume(identity(service, "Продолжи"), task_context={"original_question": "Продолжи"})
    question = workbook_model_question("Продолжи", resumed)
    assert original in question and "Москва" in question and "4 квартал 2026" in question
    assert "имеют приоритет" in question


def test_model_correction_keeps_source_and_exact_cards_together_with_original_task():
    from proxy.services.chat_evidence_application_service import govern_inference_messages, packet_evidence_text
    from proxy.services.model_execution_preset_service import ModelExecutionPreset
    preset = ModelExecutionPreset(preset_id="test", model_family="test", input_token_limit=2500,
        generation_reserve_tokens=200, safety_reserve_tokens=100, normal_tool_count=3, max_tools=5,
        max_batch_items=5, parallel_read_limit=1, reasoning_enabled=False, source_chain=("test",))
    original = "Собери ВОР с раздельными материалами и работами"
    current = "Исправь единицы и объёмы"
    question = workbook_model_question(current, {"task_context": {"original_question": original}})
    messages, packet = govern_inference_messages(preset=preset, profile_prefix="Инженер",
        request_payload=question, required_evidence=["Лист!R2: Изделие | шт | 25", "Q1.H1: Полная карточка источника"])
    text = str(messages)
    assert original in text and current in text
    assert "Лист!R2: Изделие | шт | 25" in packet_evidence_text(packet)
    assert "Q1.H1: Полная карточка источника" in packet_evidence_text(packet)


def test_new_review_chains_parent_without_replaying_an_older_jobs_file(tmp_path):
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    first = service.begin_or_resume(identity(service, "Собери ВОР"))
    service.record_packet(first["job_id"], sheet="Лист", packet_locators=["Лист!R2"],
        accepted_rows=[{"source_row": "Лист!R2", "row_role": "work", "title": "Монтаж"}],
        evidence=[], remaining=[])
    service.record_packaging(first["job_id"], tool="build_vor_workbook", revision_id="rev_previous", draft=False)
    service.finish(first["job_id"], status="complete")
    review = service.begin_or_resume(identity(service, "Уточни объёмы"))
    previous = [event for event in service.list_events_with_lineage(review["job_id"])
                if event["job_id"] != review["job_id"]]
    parents, settled = workbook_packaging_lineage(service.list_events(review["job_id"]),
        durable_decisions=True, prior_events=previous)
    assert parents == {"build_vor_workbook": "rev_previous"}
    assert settled == {}
    service.record_packaging(review["job_id"], tool="build_vor_workbook", revision_id="rev_changed",
        draft=False, parent_revision_id="rev_previous")
    parents, settled = workbook_packaging_lineage(service.list_events(review["job_id"]),
        durable_decisions=True, prior_events=previous)
    assert parents == {"build_vor_workbook": "rev_changed"}
    assert settled == {"build_vor_workbook": "rev_previous"}


def test_equivalent_basis_does_not_change_packaging_identity():
    previous = {
        "pricebook": "sankt-peterburg_3kv2026", "region": "Город Санкт-Петербург",
        "quarter": "3 квартал 2026 г.", "binding": "Санкт-Петербург 3 квартал 2026",
        "revision_id": "rev_original",
    }
    job = {"task_context": {"price_basis": requested_price_basis(
        "Санкт-Петербург, цены 3 квартал 2026"
    )}}
    assert task_document_price_basis(job, previous) == previous


def test_custom_profile_receives_workbook_contract_without_mutating_snapshot():
    from proxy.services.chat_evidence_application_service import overlay_tabular_estimator_snapshot
    original = {"mode": "estimator", "skill_text": "Правила пользователя", "tools": []}
    effective = overlay_tabular_estimator_snapshot(original)
    assert original["skill_text"] == "Правила пользователя"
    assert effective["skill_text"].startswith("Правила пользователя")
    assert "Не заканчивай монтажную ЛСР одной поставкой" in effective["skill_text"]
    assert effective["effective_skill_modules"][0]["sha256"]
    again = overlay_tabular_estimator_snapshot(effective)
    assert again["skill_text"] == effective["skill_text"]


def test_packet_rows_survive_optional_evidence_pressure(tmp_path):
    from openpyxl import Workbook
    from proxy.services.attachment_source_catalog_service import load_tabular_source_catalog
    from proxy.services.chat_evidence_application_service import (
        govern_inference_messages, selector_evidence_payload, packet_evidence_text,
    )
    from proxy.services.model_execution_preset_service import ModelExecutionPreset

    path = tmp_path / "Большой ВОР.xlsx"
    book = Workbook()
    for index in range(2):
        sheet = book.active if index == 0 else book.create_sheet()
        sheet.title = f"Раздел {index + 1}"
        sheet.append(["Наименование работ", "Ед. изм.", "Количество"])
        for n in range(160):
            sheet.append([f"Монтаж элемента {n} " + "длинное описание " * 4, "шт", n + 1])
    book.save(path)
    catalog = load_tabular_source_catalog(path)
    assert len("\n".join(catalog.interleaved_row_lines())) > 18000
    preset = ModelExecutionPreset(
        preset_id="test", model_family="test", input_token_limit=2500,
        generation_reserve_tokens=200, safety_reserve_tokens=100,
        normal_tool_count=3, max_tools=5, max_batch_items=5,
        parallel_read_limit=1, reasoning_enabled=False, source_chain=("test",),
    )
    seen = set()
    for locator in catalog.work_locators():
        row = catalog.lookup(locator)
        source = selector_evidence_payload(
            attachment_context="обрезанный текст", rendered_context="",
            source_catalog=catalog, sheet=row.sheet, remaining_work=[locator],
        )
        _, packet = govern_inference_messages(
            preset=preset, profile_prefix="Сметчик", request_payload="Собери ЛСР",
            required_evidence=source, evidence=["Большая карточка " * 5000],
        )
        visible = packet_evidence_text(packet)
        assert row.line in visible  # full content, not merely a locator
        assert "Раздел 1" in visible and "Раздел 2" in visible
        assert packet.omissions
        seen.add(locator)
    assert len(seen) == 320
