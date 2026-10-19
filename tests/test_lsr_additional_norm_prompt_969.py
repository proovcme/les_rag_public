"""Additional norms must use a row shape the active calculator can compute."""
from copy import deepcopy
import json

import pytest

from proxy.services import model_lsr_result_contract as contract
from proxy.services.chat_evidence_application_service import sheet_pass_question_tail
from proxy.services.lsr_norm_quality_gate_service import lsr_result_table_instruction


ADDITIONAL_ROW_RULE = "Добавка — новая операция с norm_code/evidence_refs, без covered_by_work_id. "
UNCOMPUTED_COMPONENTS_RULE = "norm_components — аудит без расчёта. "


@pytest.mark.parametrize("carrier", ["shared", "direct", "sheet", "conditional"])
def test_actual_lsr_carriers_explain_additional_rows_and_literal_components(carrier):
    if carrier == "shared":
        text = contract.model_lsr_result_field_instruction()
    elif carrier == "direct":
        text = lsr_result_table_instruction(artifact_kind="lsr")
    elif carrier == "sheet":
        text = sheet_pass_question_tail("Literal request", sheet="S", sheet_index=1,
            sheet_count=1, remaining_work=["S!R2"], artifact_kind="lsr")
    else:
        text = lsr_result_table_instruction()
    assert text.count(ADDITIONAL_ROW_RULE) == 1
    assert text.count(UNCOMPUTED_COMPONENTS_RULE) == 1
    assert "Исходные unit и quantity сохраняй" in text
    assert "Кратность: calc_quantity/calc_unit" in text
    assert "формула: conversion_source" in text
    assert "без covered_by_work_id" in ADDITIONAL_ROW_RULE
    assert "можно добавить norm_components" not in text
    assert "операции оставь operation_id пустым" in text
    assert "norm_components" in contract.OPTIONAL_FIELDS
    assert "norm_components" in contract.LSR_DESCRIBED_OPTIONAL_FIELDS
    tail = ", ".join(field for field in contract.OPTIONAL_FIELDS
                     if field not in contract.LSR_DESCRIBED_OPTIONAL_FIELDS)
    assert "norm_components" not in tail
    assert tail + "." in text
    # Compare the full actual carrier against its exact original968 rendering;
    # source/budget fixtures are never enlarged to accommodate a new hint.
    old_rule = (
        "Для кратности всей нормы calc_quantity/calc_unit — расчётный эквивалент, формула — conversion_source. "
        "Для начисляемой добавочной нормы covered_by_work_id не задавай. "
    )
    old_tail = ", ".join(field for field in contract.OPTIONAL_FIELDS
                         if field not in contract.LSR_DESCRIBED_OPTIONAL_FIELDS - {"norm_components"})
    previous = text.replace(contract.LSR_DERIVED_VOLUME_INSTRUCTION, old_rule, 1).replace(tail, old_tail, 1)
    if carrier != "shared":
        stale = ('Если работа составная, можно добавить norm_components как JSON-список '
                 '{"norm_code", "evidence_refs"}; иначе оставь ячейку пустой. ')
        anchor = "Лучше честный MISSING, чем случайный шифр из выдачи."
        assert previous.count(anchor) == 1
        previous = previous.replace(anchor, stale + anchor, 1)
    assert len(text) <= len(previous)
    assert len(text.encode("utf-8")) <= len(previous.encode("utf-8"))
    from proxy.services.context_governor_service import conservative_token_estimate
    for ensure_ascii in (False, True):
        body = lambda value: json.dumps({"messages": [{"role": "user", "content": value}]},
                                        ensure_ascii=ensure_ascii, sort_keys=True, separators=(",", ":"))
        assert conservative_token_estimate(body(text)) <= conservative_token_estimate(body(previous))


def test_vor_instruction_does_not_receive_lsr_component_or_norm_requirements():
    text = lsr_result_table_instruction(artifact_kind="vor")
    assert ADDITIONAL_ROW_RULE not in text
    assert UNCOMPUTED_COMPONENTS_RULE not in text
    assert "norm_components" not in text
    assert "Нормы и цены для ВОР не обязательны" in text


def test_old_authored_components_remain_literal_without_generated_rows():
    literal_components = [{"norm_code": "literal additional choice", "quantity": 3,
                           "evidence_refs": ["Q2.H3"]}]
    row = {"source_row": "S!R2", "row_role": "work", "work_row": "", "title": "Authored work",
           "quantity": 7.5, "unit": "m2", "norm_code": "literal main choice",
           "norm_status": "ANALOGUE_CANDIDATE", "open_gap": "Unresolved literal condition",
           "evidence_refs": ["Q1.H2"], "norm_components": literal_components}
    original = deepcopy(row)
    decoded = contract.decode_model_result_rows(json.dumps({"artifact_kind": "lsr", "rows": [row]}))
    assert decoded == [original]
    assert row == original
    assert len(decoded) == 1
