"""VOR export describes authored operations without demanding LSR norm/price fields."""
from __future__ import annotations

import copy
import json

import pytest

from proxy.services import chat_evidence_application_service as service
from proxy.services import model_lsr_result_contract as contract
from proxy.services.lsr_norm_quality_gate_service import lsr_result_table_instruction


VOR_CORE = ("source_row", "row_role", "work_row", "title", "unit", "quantity", "open_gap")
VOR_PROOF_FIELDS = ("coverage", "covered_by_work_id", "evidence_refs")
VOR_FIELDS = VOR_CORE + VOR_PROOF_FIELDS
LSR_REQUIRED = ("source_row", "row_role", "work_row", "title", "unit", "quantity",
                "norm_code", "norm_status", "open_gap", "evidence_refs")


def _declared_fields(instruction, kind):
    marker = f"Поля {kind}: "
    if kind == "ВОР" and marker not in instruction:
        marker = "КОНТРАКТ ВОР — только при artifact_kind: vor\n"
    return tuple(instruction.split(marker, 1)[1].split(". ", 1)[0].split(", "))


@pytest.mark.parametrize("factory", [contract.model_lsr_result_field_instruction, lsr_result_table_instruction])
def test_shared_export_instruction_keeps_vor_core_separate_from_required_lsr_fields(factory):
    instruction = factory()
    assert _declared_fields(instruction, "ВОР") == VOR_FIELDS == contract.VOR_RESULT_FIELDS
    assert _declared_fields(instruction, "ЛСР") == LSR_REQUIRED == contract.BASE_FIELDS
    assert "Для ВОР нормы, цены и поля norm_code/norm_status не обязательны" in instruction
    assert "Не ставь MISSING и не меняй известную работу на unresolved лишь из-за отсутствия нормы или цены" in instruction
    assert "Исходные основания ВОР укажи через source_row" in instruction
    assert "evidence_refs добавляй, когда ссылаешься на показанное основание" in instruction
    assert "Для ЛСР все перечисленные поля обязательны" in instruction
    assert "Правила нормы, её ресурсов и цен далее относятся к ЛСР либо к добровольно заявленным в ВОР нормам/ценам" in instruction
    assert "Поля строки: " not in instruction  # old unconditional ten-field obligation


@pytest.mark.parametrize("format_name", ["json", "markdown", "text"])
def test_export_contract_all_formats_keep_selected_norm_and_lsr_rules(format_name):
    instruction = contract.model_lsr_result_field_instruction(include_examples=True)
    assert contract.model_lsr_result_examples()[format_name] in instruction
    assert 'Без указания формата предпочти компактный JSON {"rows":[...]}; допустимы Markdown или текст' in instruction
    required = instruction.split("Для каждой выбранной нормы обязательно верни ", 1)[1].split(". ", 1)[0]
    assert tuple(required.split(", ")) == contract.SELECTED_NORM_FIELDS
    for rule in ("norm_code дословно копируй целиком вместе с конечным вариантом",
                 "Масштаб измерителя нормы код применяет один раз", "resource_code", "nr_sp_rule_id",
                 "Коммерческая confirmed_price требует цитаты суммы, единицы и price_source",
                 "expected_revision", "conversion_source"):
        assert rule in instruction
    assert contract.BASE_FIELDS == LSR_REQUIRED
    assert set(contract.SELECTED_NORM_FIELDS).isdisjoint(contract.OPTIONAL_FIELDS)


def test_workbook_profile_keeps_literal_bound_profile_skill_and_conditional_operation_scope():
    profile = {"mode": "estimator", "prompt_text": "LITERAL IMMUTABLE PROFILE Ω",
               "skill_text": "LITERAL IMMUTABLE SKILL Ω", "revision_id": "literal:revision:19"}
    before = copy.deepcopy(profile)
    prompt = service.profile_system_prompt(profile, strict=False, purpose="workbook_result")
    assert prompt.startswith(profile["prompt_text"]) and profile["skill_text"] in prompt
    assert "Для ЛСР пустые ценовые колонки не мешают сборке" in prompt
    assert "Для ВОР нормы и цены не являются условием создания работ и объёмов" in prompt
    assert "При подборе нормы для ЛСР или добровольно для ВОР" in prompt
    assert service._WORKBOOK_RESULT_CARRIER_INSTRUCTION in prompt
    assert profile == before


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
@pytest.mark.parametrize("kind", ["vor", "lsr"])
async def test_actual_model_declared_export_wire_contains_conditional_common_contract(monkeypatch, tmp_path, variant, kind):
    from tests.test_model_no_source_card_read_contract import _run_no_source

    query = json.dumps({"artifact_kind": kind, "queries": ["literal model card search"]})
    run = await _run_no_source(monkeypatch, tmp_path, final_text="No authored rows.",
                               query_text=query, variant=variant)
    assert len(run["requests"]) == 2
    messages = str(run["requests"][1].messages)
    shared = contract.model_lsr_result_field_instruction()
    if kind == "vor":
        assert contract.model_vor_result_field_instruction() in messages
        assert shared not in messages
        assert "Нормы и цены для ВОР не обязательны" in messages
    else:
        assert shared in messages
        assert _declared_fields(shared, "ВОР") == VOR_FIELDS == contract.VOR_RESULT_FIELDS
        assert _declared_fields(shared, "ЛСР") == LSR_REQUIRED
        assert "Для ВОР нормы и цены не являются условием создания работ и объёмов" in messages
    assert "LITERAL READ PROFILE Ω" in messages and "LITERAL READ SKILL Ω" in messages
    # The model declaration remains authoritative; neither the instruction nor
    # code infers the export kind from words or changes selected norm decisions.
    target = run["result"]["retrieval_trace"]["artifact_target"]
    assert target["status"] == "declared" and target["artifact_kind"] == kind
    assert not run["executions"]
