"""Authored VOR work links are audited; operation meaning stays with the model."""
from copy import deepcopy
import json
from types import SimpleNamespace

import openpyxl
import pytest

from proxy.services import chat_evidence_application_service as app
from proxy.services.lsr_norm_quality_gate_service import lsr_result_table_instruction
from proxy.services.model_lsr_result_contract import model_vor_result_field_instruction
from proxy.services.vor_result_integrity_service import audit_vor_result_integrity
from proxy.services.workbook_tool_service import _default_vor_adapter


def _work(**values):
    return {"source_row": "Раздел Ω!R2", "operation_id": "op_first", "revision": 1,
            "row_role": "work", "title": "Авторская операция", "unit": "м²",
            "quantity": 12, "open_gap": "", **values}


@pytest.mark.parametrize("parent", ["SELECTED_CARD_CODE", "op_missing", "Раздел Ω!R99", "R99"])
def test_complete_work_with_explicit_missing_endpoint_is_not_a_complete_vor(parent):
    rows = [_work(work_row=parent)]
    before = deepcopy(rows)
    issues = audit_vor_result_integrity(rows)
    assert [issue["code"] for issue in issues] == ["invalid_work_relationship"]
    assert issues[0]["work_row"] == parent and issues[0]["target_exists"] is False
    readiness = app.build_vor_result_readiness(rows=rows, has_file=True,
        remaining_locators=[], catalog_work_count=1, model_errors=[])
    assert readiness["vor_complete"] is False
    assert readiness["row_integrity_issues"] == issues and readiness["open_questions"]
    assert rows == before


@pytest.mark.parametrize("fields", [{}, {"work_row": ""}, {"work_row": "—"},
    {"work_row": "Раздел Ω!R2"}, {"work_row": "R2"}, {"work_row": "op_first"}])
def test_independent_or_explicit_self_work_keeps_compatibility(fields):
    rows = [_work(**fields)]
    before = deepcopy(rows)
    assert audit_vor_result_integrity(rows) == []
    assert app.build_vor_result_readiness(rows=rows, has_file=True,
        remaining_locators=[], catalog_work_count=1, model_errors=[])["vor_complete"]
    assert rows == before


@pytest.mark.parametrize("parent", ["Другой лист Ω!R17", "op_prior_packet"])
def test_cross_packet_work_endpoint_uses_the_full_authored_result(parent):
    previous = _work(source_row="Другой лист Ω!R17", operation_id="op_prior_packet")
    current = _work(operation_id="op_current_packet", work_row=parent,
                    coverage="Авторское обоснование включения операции")
    rows = [previous, current]
    before = deepcopy(rows)
    assert audit_vor_result_integrity(rows) == []
    assert rows == before


def test_existing_catalog_alias_resolver_also_applies_to_an_explicit_work_endpoint():
    class Catalog:
        def lookup(self, value):
            if str(value).casefold() == "раздел ω!r2":
                return SimpleNamespace(locator="Раздел Ω!R2")
            return None

    rows = [_work(work_row="раздел ω!r2")]
    before = deepcopy(rows)
    assert audit_vor_result_integrity(rows, source_catalog=Catalog()) == []
    assert rows == before


def test_explicit_work_endpoint_must_be_an_existing_work_not_a_material():
    rows = [_work(work_row="op_supply"),
            {"source_row": "Раздел Ω!R3", "operation_id": "op_supply",
             "row_role": "material", "title": "Изделие", "quantity": 1,
             "unit": "шт", "work_row": "op_first"}]
    before = deepcopy(rows)
    issues = audit_vor_result_integrity(rows)
    assert len(issues) == 1 and issues[0]["code"] == "invalid_work_relationship"
    assert issues[0]["target_exists"] and issues[0]["target_roles"] == ["material"]
    assert rows == before


def test_equal_authored_quantities_on_distinct_source_layers_are_not_deduplicated():
    rows = [_work(title="Авторская операция слоя A", work_row="Раздел Ω!R2"),
            _work(source_row="Раздел Ω!R3", operation_id="op_second",
                  title="Авторская операция слоя B", work_row="Раздел Ω!R3")]
    before = deepcopy(rows)
    assert audit_vor_result_integrity(rows) == []
    assert rows == before


def test_next_existing_review_shows_the_structural_fact_without_replacing_the_decision():
    rows = [_work(work_row="MODEL_SELECTED_CARD_CODE")]
    before = deepcopy(rows)
    context, _ = app.model_rag_prior_page_context(rows, [], review_rows=rows,
        review_instruction="Проверь связи работ", prior_artifact_kind="vor", full_result_rows=rows)
    facts = context["prior_result_structural_facts"]
    assert len(facts) == 1
    assert facts[0]["vor_integrity"][0]["code"] == "invalid_work_relationship"
    assert context["prior_model_decisions"][0]["work_row"] == "MODEL_SELECTED_CARD_CODE"
    assert rows == before


@pytest.mark.asyncio
async def test_export_exposes_the_invalid_work_endpoint_and_keeps_the_literal_row(tmp_path):
    source, output = tmp_path / "Исходник 'Ω'.xlsx", tmp_path / "ВОР 'Ω'.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active.title = "Раздел Ω"
    workbook.active.append(["Наименование", "Ед. изм.", "Количество"])
    workbook.active.append(["Авторская операция", "м²", 12])
    workbook.save(source)
    workbook.close()
    row = _work(work_row="MODEL_SELECTED_CARD_CODE")
    before = deepcopy(row)
    result = await _default_vor_adapter(source, {"decisions": [row]}, output, lambda *_args: None)
    assert any(i["code"] == "invalid_work_relationship" for i in result["document_issues"])
    workbook = openpyxl.load_workbook(output, data_only=False)
    try:
        assert "НЕ ЗАВЕРШЁН" in workbook["ВОР"]["A2"].value
        assert "invalid_work_relationship" in str(list(workbook["Проверка"].values))
        exported = json.loads(workbook["Решения модели"]["C4"].value.removeprefix("JSON: "))
        assert exported == row == before
    finally:
        workbook.close()


def test_vor_operation_basis_contract_is_generic_and_keeps_lsr_scope_unchanged():
    instruction = model_vor_result_field_instruction()
    clauses = (
        "предмет, слой и технические признаки собственной исходной позиции",
        "Равенство количества и единицы у разных исходных позиций само по себе не доказывает дубль",
        "Объединение операций или включение одной в другую обоснуй в coverage",
        "Только вопрос, который мешает определить требуемые работы, их связи, единицы или объёмы",
        "будущей логистики или ценообразования не превращай в open_gap ВОР",
    )
    for clause in clauses:
        assert clause in instruction
        assert clause in lsr_result_table_instruction(artifact_kind="vor")
        assert clause not in lsr_result_table_instruction(artifact_kind="lsr")
    for case in ("Н3", "кассет", "сэндвич", "23,6", "Мельник", "БАП"):
        assert case not in instruction
    assert "Не добавляй монтаж каждому изделию автоматически" in instruction
    assert "Неоднозначную связь оставь вопросом" in instruction
