"""Active estimate prompts distinguish source quantities from norm/resource scales."""
from __future__ import annotations

import copy

import pytest

from proxy.services import chat_evidence_application_service as chat
from proxy.services.lsr_norm_quality_gate_service import (
    lsr_result_table_instruction,
    lsr_verifier_instruction,
)
from proxy.services.model_evidence_read_contract import MODEL_EVIDENCE_READ_INSTRUCTION
from proxy.services.model_lsr_result_contract import model_lsr_result_field_instruction


_MEASURE_RULE = "unit_compatible сравнивает физическую величину, а не масштаб измерителя"
_ONCE_RULE = "Масштаб измерителя нормы код применяет один раз"
_RESOURCE_RULE = "Не копируй числовой объём работы как расход ресурса с другой единицей"


def test_active_result_contract_explains_scale_without_changing_source_or_other_matches():
    instruction = model_lsr_result_field_instruction()
    assert _MEASURE_RULE in instruction
    for pair in ("м и 100 м", "м² и 100 м²", "шт и 100 шт"):
        assert pair in instruction
    assert "не подтверждает действие, объект, условия или состав" in instruction
    assert "Исходные unit и quantity сохраняй" in instruction
    assert _ONCE_RULE in instruction
    assert "не дели quantity" in instruction
    assert "не дублируй этот масштаб в calc_quantity/conversion_factor" in instruction
    assert "другой физической величине" in instruction and "conversion_source" in instruction
    assert instruction in lsr_result_table_instruction()


def test_resource_quantity_requires_card_consumption_or_proven_formula_not_relabelled_work():
    instruction = model_lsr_result_field_instruction()
    assert _RESOURCE_RULE in instruction
    assert "расход из полной карточки на её измеритель" in instruction
    assert "либо доказанную формулу и её источник" in instruction
    assert "площадь или длина не становится массой" in instruction
    # Existing READ contract remains the sole full-read policy, with no extra
    # compulsory inference when the displayed card already provides consumption.
    assert "Если расход выбранной нормы не показан, прочитай её через read_norm_card" in MODEL_EVIDENCE_READ_INSTRUCTION
    assert "при достаточном уже показанном содержании" in MODEL_EVIDENCE_READ_INSTRUCTION
    assert "повторное чтение не требуется" in MODEL_EVIDENCE_READ_INSTRUCTION


def test_active_scale_rule_agrees_with_legacy_diagnostic_without_reusing_its_verdicts():
    active = lsr_result_table_instruction()
    diagnostic = lsr_verifier_instruction()
    assert _MEASURE_RULE in active
    assert "unit_compatible=yes, если это тот же физический измеритель" in diagnostic
    assert "м² и 100 м2, шт и 100 шт" in diagnostic
    assert "norm_status — только закрытый токен: EXACT," in active
    assert "Не пиши EXACT_VERIFIED и ANALOGUE_VERIFIED" in active


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_actual_baseline_and_candidate_receive_scale_and_consumption_rules(tmp_path, monkeypatch, variant):
    from tests.test_model_rag_sheet_evidence_reads import _run_sheet

    run = await _run_sheet(tmp_path, monkeypatch, reads=True, variant=variant, temperature=0.65)
    assert not run.responses and len(run.requests) == 4 and len(run.executions) == 1
    before = copy.deepcopy(run.executions[0][0]["args"]["decisions"])
    for request in run.requests[1:]:
        delivered = "\n".join(str(message.get("content", "")) for message in request.messages)
        assert _MEASURE_RULE in delivered
        assert _ONCE_RULE in delivered
        assert _RESOURCE_RULE in delivered
        assert "Answer only from shown evidence." in delivered
        assert request.temperature == 0.65
    queries = "\n".join(str(message.get("content", "")) for message in run.requests[0].messages)
    assert _MEASURE_RULE not in queries, "norm decisions belong to the result phase"
    assert [(row["source_row"], row["unit"], row["quantity"]) for row in before] == [
        ("S!R2", "m", 12), ("S!R3", "m", 3),
    ]
    assert run.executions[0][0]["args"]["decisions"] == before
