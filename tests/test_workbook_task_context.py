"""Durable request survives failed first packaging, resume, and repricing."""
from proxy.services.workbook_research_job_service import WorkbookResearchJobService
from proxy.services.lsr_workbook_adapter_service import (
    explicit_estimate_pricebook,
    requested_price_basis,
)
from proxy.services.chat_evidence_application_service import (
    task_document_price_basis,
    workbook_packaging_args,
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
