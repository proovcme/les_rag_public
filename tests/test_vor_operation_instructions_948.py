"""VOR operations use a dedicated contract; model choices remain model-owned."""

import hashlib
import json

import pytest

from proxy.services.lsr_norm_quality_gate_service import lsr_result_table_instruction
from proxy.services.model_lsr_result_contract import (
    decode_model_artifact_kind,
    decode_model_result_rows,
    model_lsr_result_field_instruction,
    model_vor_result_field_instruction,
)


def test_only_explicit_vor_target_receives_dedicated_operation_contract():
    instruction = model_vor_result_field_instruction()
    assert lsr_result_table_instruction(artifact_kind="vor") == instruction
    assert len(instruction) < len(model_lsr_result_field_instruction())
    assert "самостоятельные технологические работы" in instruction
    assert "а не переписанную спецификацию" in instruction
    assert "Роль определяешь ты по смыслу" in instruction
    assert "ГОСТ, марка или артикул сами по себе" in instruction
    assert "Не добавляй монтаж каждому изделию автоматически" in instruction
    assert "несколько разных работ и материал" in instruction
    assert "с реальной связью с работой или конкретным вопросом" in instruction
    assert "реально существующую работу" in instruction
    assert "Неоднозначную связь оставь вопросом" in instruction


@pytest.mark.parametrize("kind", ["lsr", "both", "unknown", "VOR"])
def test_existing_lsr_instruction_is_byte_for_byte_unchanged(kind):
    instruction = lsr_result_table_instruction(artifact_kind=kind)
    assert hashlib.sha256(instruction.encode("utf-8")).hexdigest() == (
        "03ae9ba8a17f55be977790a6226790a690b6406fcc890e1228fa3570c1ad7826"
    )
    assert model_lsr_result_field_instruction() in instruction


def test_vor_contract_does_not_require_norm_status_matches_or_pricing():
    instruction = lsr_result_table_instruction(artifact_kind="vor")
    for field in ("norm_code", "norm_status", "EXACT", "MISSING", "nr_sp_rule_id",
                  "resource_review", "confirmed_price", "action_match", "composition_covers"):
        assert field not in instruction
    assert "Нормы и цены для ВОР не обязательны" in instruction
    assert "их отсутствие не превращает известную работу в unresolved" in instruction


def test_vor_quantity_instruction_distinguishes_unknown_zero_and_proven_derivation():
    instruction = model_vor_result_field_instruction()
    assert "Неизвестный quantity — null" in instruction
    assert "явный исходный ноль сохраняй как 0" in instruction
    assert "unit и quantity сохраняй из той же исходной строки" in instruction
    assert "проверяемой формулой" in instruction
    assert "исходными параметрами и их точным источником" in instruction
    assert "исходные unit/quantity не подменяй" in instruction
    assert "Не придумывай толщину, число сторон, площадь, вид отделки или расход" in instruction
    assert "назови конкретно недостающий параметр или решение" in instruction


def test_vor_preserves_stable_source_and_revision_contract_with_same_packet_clauses():
    instruction = lsr_result_table_instruction(artifact_kind="vor", sheet_clause="SHEET_SCOPE\n",
                                               remaining_clause="\nREMAINING_SCOPE")
    assert instruction == "SHEET_SCOPE\n" + model_vor_result_field_instruction() + "\nREMAINING_SCOPE"
    for token in ("source_row", "work_row", "operation_id", "prior_model_decisions",
                  "expected_revision", "base_revision", "новой оставь operation_id пустым"):
        assert token in instruction
    assert "при явном пересмотре — все предложенные прежние операции" in instruction
    assert "включая неизменённые с дословными предметными полями" in instruction
    assert "Текущий пакет — часть исходника" in instruction


@pytest.mark.parametrize("title,unit,quantity", [
    ("Устройство покрытия", "м²", 18.5),
    ("Прокладка трубопровода", "м", 0),
    ("Установка агрегата", "шт", None),
])
def test_vor_json_contract_accepts_different_sections_and_does_not_invent_quantities(title, unit, quantity):
    row = {"source_row": "Исходный лист!R17", "row_role": "work", "work_row": "",
           "title": title, "unit": unit, "quantity": quantity,
           "open_gap": "Уточнить количество по чертежу" if quantity is None else "",
           "operation_id": ""}
    raw = json.dumps({"artifact_kind": "vor", "rows": [row]}, ensure_ascii=False)
    assert decode_model_artifact_kind(raw)["artifact_kind"] == "vor"
    assert decode_model_result_rows(raw) == [row]


@pytest.mark.parametrize("format_name", ["json", "markdown"])
def test_announced_vor_formats_preserve_work_material_relationship_without_norm_fields(format_name):
    from proxy.services.chat_evidence_application_service import parse_model_rag_result

    rows = [
        {"source_row": "Другой лист!R4", "row_role": "work", "work_row": "",
         "title": "Выбранная моделью операция", "unit": "шт", "quantity": 2, "open_gap": "",
         "operation_id": "prior-operation", "expected_revision": 3},
        {"source_row": "Другой лист!R4", "row_role": "material", "work_row": "prior-operation",
         "title": "Исходное изделие", "unit": "шт", "quantity": 2, "open_gap": "",
         "operation_id": "", "expected_revision": ""},
    ]
    if format_name == "json":
        raw = json.dumps({"artifact_kind": "vor", "rows": rows}, ensure_ascii=False)
    else:
        fields = tuple(rows[0])
        raw = "artifact_kind: vor\n\n" + "\n".join([
            "| " + " | ".join(fields) + " |",
            "| " + " | ".join("---" for _ in fields) + " |",
            *("| " + " | ".join(str(row[field]) for field in fields) + " |" for row in rows),
        ])
    parsed = parse_model_rag_result(raw)
    assert parsed is not None
    assert [(row["source_row"], row["row_role"], row["quantity"], row["work_row"])
            for row in parsed[1]] == [
        ("Другой лист!R4", "work", 2, ""), ("Другой лист!R4", "material", 2, "prior-operation"),
    ]
    assert parsed[1][0]["operation_id"] == "prior-operation"
    assert parsed[1][0]["expected_revision"] == 3
    assert all("norm_code" not in row and "norm_status" not in row for row in parsed[1])
