import json

import pytest

from proxy.services import model_lsr_result_contract as contract
from proxy.services.lsr_norm_quality_gate_service import lsr_result_table_instruction


@pytest.mark.parametrize("action,basis", [("add", "explicit"), ("replace", "explicit"),
                                        ("add", "source_work"), ("replace", "target_norm")])
def test_resource_quantity_instruction_matches_the_actual_binding_contract(action, basis):
    from proxy.smeta_core.contracts import ResourceBinding
    binding = ResourceBinding(work_id="source-operation", selected_by="model", action=action,
        resource_name="Literal shown resource", unit="kg", quantity=2,
        quantity_basis=basis, target_resource_code="shown-target")
    instruction = contract.model_lsr_resource_decision_instruction()
    assert binding.quantity_basis in instruction
    assert "target_norm только для replace, source_work только для add" in instruction
    assert "полный физический расход" in instruction


@pytest.mark.parametrize("status", ["keep_all_confirmed", "actions_confirmed", "unresolved"])
def test_resource_review_instruction_exposes_real_review_statuses(status):
    from proxy.smeta_core.contracts import ResourceReview
    review = ResourceReview(work_id="source-operation", selected_by="model", status=status,
        reason="Literal source comparison", labor_status="confirmed", labor_reason="Shown labor",
        machine_status="not_present", material_status="unresolved")
    instruction = contract.model_lsr_resource_decision_instruction()
    assert review.status in instruction
    assert "confirmed/not_present/unresolved/rejected" in instruction
    assert "labor_reason/machine_reason/material_reason" in instruction


def test_selected_norm_facts_are_required_and_not_in_optional_fields():
    instruction = contract.model_lsr_result_field_instruction()
    required_clause = instruction.split("Для каждой выбранной нормы обязательно верни ", 1)[1].split(". ", 1)[0]

    assert all(field in required_clause for field in (*contract.MATCH_FIELDS, "coverage"))
    assert not set(contract.SELECTED_NORM_FIELDS) & set(contract.OPTIONAL_FIELDS)
    assert "resource_code" in instruction and "nr_sp_rule_id" in instruction
    assert "unknown" in instruction and "конкретный вопрос в open_gap" in instruction


def test_all_format_examples_preserve_the_same_authored_fields():
    examples = contract.model_lsr_result_examples()
    json_row = json.loads(examples["json"])["rows"][0]
    table_lines = examples["markdown"].splitlines()
    fields = [value.strip() for value in table_lines[0].strip("|").split("|")]
    values = [value.strip() for value in table_lines[2].strip("|").split("|")]
    table_row = dict(zip(fields, values))
    text_row = dict(line.split(": ", 1) for line in examples["text"].splitlines())

    assert table_row == json_row == text_row
    assert set(contract.BASE_FIELDS + contract.SELECTED_NORM_FIELDS).issubset(json_row)
    assert json_row["nr_sp_rule_id"] == ""
    assert json_row["open_gap"].endswith("?")


def test_result_table_contract_allows_delta_and_ordinary_text_without_weaker_flags():
    shared = contract.model_lsr_result_field_instruction()
    instruction = lsr_result_table_instruction(sheet_clause="SHEET ", remaining_clause=" REMAINING")

    assert shared in instruction
    assert instruction.startswith("SHEET ") and instruction.endswith(" REMAINING")
    assert "обычным текстом" in instruction
    assert "JSON не обязателен" in instruction
    assert "Не выводи JSON" not in instruction
    assert "неизменённые строки prior_model_decisions повторять не обязательно" in instruction
    assert "expected_revision из её revision в prior_model_decisions" in instruction
    assert "или base_revision" in instruction
    assert "Не назначай свои ID и новый revision" in instruction
    assert "набор source_row результата точно равен" not in instruction


def test_format_hints_do_not_contradict_empty_cell_transport_or_force_markdown():
    instruction = lsr_result_table_instruction()

    assert "не перечисляй пустые поля" not in instruction
    assert "Если выбран Markdown" in instruction
    assert "сохраняй пустую ячейку" in instruction
    assert "предпочти JSON rows" in instruction
    assert "JSON не обязателен" in instruction
    assert "пояснение пиши в coverage, не вместо признака" in instruction
    assert "Неприменимые поля не выводи" not in instruction
    assert "Не объявляй неприменимые необязательные колонки" in instruction
