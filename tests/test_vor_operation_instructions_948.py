"""VOR operations use a dedicated contract; model choices remain model-owned."""

import hashlib
import json

import pytest

from proxy.services.lsr_norm_quality_gate_service import lsr_result_table_instruction
from proxy.services.model_lsr_result_contract import (
    VOR_RESULT_FIELDS,
    decode_model_artifact_kind,
    decode_model_result_rows,
    model_lsr_result_field_instruction,
    model_vor_result_field_instruction,
)


def _strip_authorized_vor_field_list_delta(instruction):
    """Reverse only the three added VOR fields before checking old LSR bytes."""
    previous_fields = ("source_row", "row_role", "work_row", "title", "unit", "quantity", "open_gap")
    added_fields = ("coverage", "covered_by_work_id", "evidence_refs")
    assert VOR_RESULT_FIELDS[:len(previous_fields)] == previous_fields
    assert VOR_RESULT_FIELDS[len(previous_fields):] == added_fields
    current = "Поля ВОР: " + ", ".join(previous_fields + added_fields) + ". "
    previous = "Поля ВОР: " + ", ".join(previous_fields) + ". "
    assert instruction.count(current) == 1
    assert instruction.count(previous) == 0
    return instruction.replace(current, previous, 1)


def _strip_authorized_supply_match_980_delta(instruction):
    """Remove only the reviewed literal addition, keeping every old byte pin."""
    addition = (
        "Код расходника в монтажной норме не означает, что это исходное изделие поставки. "
        "Для прямой поставки material/equipment с resource_code отдельно верни supply_resource_match: "
        "{source_title, resource_code, decision, reason, source_refs}. "
        "source_title дословно повторяет title этой операции, resource_code — её выбранный код; "
        "source_refs — непустой список тех же ссылок, что evidence_refs этой операции, порядок неважен. "
        "decision: yes/no/unknown; reason — конкретное основание соответствия выбранного ресурса "
        "исходному изделию по его свойствам. Ты выбираешь и проверяешь это соответствие; "
        "цена кода и его наличие среди ресурсов нормы не доказывают соответствие изделию. "
        "При no/unknown или недостаточном основании сохрани строку, выбранный код и конкретный open_gap; "
        "сумма остаётся предварительной. Не подставляй произвольный ресурс ради снятия пробела. "
        "При изменении title, resource_code или evidence_refs пересмотри это утверждение явно; "
        "прежнее yes не подтверждает изменённый выбор. В Markdown или тексте передавай "
        "supply_resource_match как JSON-объект в одной ячейке или одноимённом поле. "
    )
    current_tail = "resource_review, supply_resource_match, resolves_proposal_id."
    previous_tail = "resource_review, resolves_proposal_id."
    assert instruction.count(addition) == 1
    assert instruction.count(current_tail) == 1
    previous = instruction.replace(addition, "", 1).replace(current_tail, previous_tail, 1)
    assert "supply_resource_match" not in previous
    return previous


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
def test_existing_lsr_instruction_changes_only_authorized967_968_clarifications(kind):
    instruction = lsr_result_table_instruction(artifact_kind=kind)
    previous_instruction = _strip_authorized_vor_field_list_delta(
        _strip_authorized_supply_match_980_delta(instruction))
    old_phrase = "nr_sp_rule_id выбирай из карточки по известным условиям; при неизвестных — "
    new_phrase = (
        "nr_sp_rule_id дословно копируй из rule_id внутри каталога по известным условиям; "
        "catalog_ref не ID правила; при неизвестных — "
    )
    assert instruction.count(new_phrase) == 1
    assert old_phrase not in instruction
    # Undo exactly the additional-operation clarification; keep the previous
    # byte pin, rather than accepting an unrelated new instruction wholesale.
    from proxy.services.model_lsr_result_contract import LSR_DESCRIBED_OPTIONAL_FIELDS, OPTIONAL_FIELDS
    from proxy.services.model_lsr_result_contract import LSR_DERIVED_VOLUME_INSTRUCTION
    old968_rule = (
        "Для кратности всей нормы calc_quantity/calc_unit — расчётный эквивалент, формула — conversion_source. "
        "Для начисляемой добавочной нормы covered_by_work_id не задавай. "
    )
    stale_rule = ('Если работа составная, можно добавить norm_components как JSON-список '
                  '{"norm_code", "evidence_refs"}; иначе оставь ячейку пустой. ')
    assert instruction.count(LSR_DERIVED_VOLUME_INSTRUCTION) == 1
    assert stale_rule not in instruction
    previous_fields = tuple(field for field in OPTIONAL_FIELDS if field != "supply_resource_match")
    numeric_tail = ", ".join(field for field in previous_fields if field not in LSR_DESCRIBED_OPTIONAL_FIELDS)
    previous_tail = ", ".join(field for field in OPTIONAL_FIELDS
                              if field != "supply_resource_match"
                              and field not in LSR_DESCRIBED_OPTIONAL_FIELDS - {"norm_components"})
    assert previous_instruction.count(numeric_tail) == 1
    anchor = "Лучше честный MISSING, чем случайный шифр из выдачи."
    assert instruction.count(anchor) == 1
    before_components = previous_instruction.replace(LSR_DERIVED_VOLUME_INSTRUCTION, old968_rule, 1).replace(numeric_tail, previous_tail, 1)
    before_components = before_components.replace(anchor, stale_rule + anchor, 1)
    assert hashlib.sha256(before_components.encode("utf-8")).hexdigest() == (
        "8c64fc2bd26b07eb2a3eb99b9a11cff6d61fb7585c12a05d237982acde2f83c5"
    )
    # Undo the two literal authorized967/968 additions; every other byte stays
    # pinned to the original948 contract instead of accepting a new whole text.
    from proxy.services.model_lsr_result_contract import LSR_DERIVED_VOLUME_INSTRUCTION, LSR_SOURCE_VOLUME_INSTRUCTION, LSR_DESCRIBED_OPTIONAL_FIELDS, OPTIONAL_FIELDS
    assert instruction.count(LSR_DERIVED_VOLUME_INSTRUCTION) == 1
    before_repetition_clarification = before_components.replace(old968_rule, "", 1)
    current_tail = previous_tail
    old_tail = ", ".join(field for field in previous_fields if field not in {"resource_bindings", "calc_unit"})
    assert before_repetition_clarification.count(current_tail) == 1
    before_repetition_clarification = before_repetition_clarification.replace(current_tail, old_tail, 1)
    assert hashlib.sha256(before_repetition_clarification.encode("utf-8")).hexdigest() == (
        "be98cbccdebbdcbe4df6669bfe2206c0b191a5046a79c84f42d4e9ce17152918"
    )
    before_nrsp_clarification = before_repetition_clarification.replace(new_phrase, old_phrase, 1)
    assert before_nrsp_clarification.count(old_phrase) == 1
    assert new_phrase not in before_nrsp_clarification
    assert hashlib.sha256(before_nrsp_clarification.encode("utf-8")).hexdigest() == (
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
