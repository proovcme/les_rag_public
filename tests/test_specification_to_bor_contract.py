from __future__ import annotations

import json
from pathlib import Path

import pytest

from proxy.services.quantity_trace_service import (
    build_quantity_trace,
    convert_unit,
    multiply_parent_child_quantity,
    parse_ru_number,
)
from proxy.services.prompt_registry_service import smeta_estimator_role_pack


SKILL_TEXT = Path("skills/smeta/SKILL.md").read_text(encoding="utf-8")


def test_specification_is_a_valid_source_for_model_owned_vor():
    assert "Если ВОР нет, модель создаёт её из спецификации" in SKILL_TEXT
    assert "Спецификация даёт изделия и количества" in SKILL_TEXT


def test_model_owns_specification_decomposition_and_code_does_not_select_norms():
    assert "Модель делает смету" in SKILL_TEXT
    assert "Код только читает файлы" in SKILL_TEXT
    assert "Скрытого selector норм, операций или режима нет" in SKILL_TEXT


def test_model_submits_mapping_and_resource_actions_before_one_calculation_pass():
    assert "mapping и явные ресурсные действия сохраняются вместе" in SKILL_TEXT
    assert "после завершения моделью mapping он один раз считает и формирует XLSX" in SKILL_TEXT
    assert "Отдельного обязательного resource-review, impact-review или повторного допуска нет" in SKILL_TEXT


def test_specification_parent_child_quantity_is_code_calculated():
    assert multiply_parent_child_quantity("3", "0,4") == pytest.approx(1.2)
    trace = build_quantity_trace(
        work_title="Устройство бетонного основания",
        source_item="бетонное основание на 1 изделие",
        parent_quantity="3",
        qty_per_parent="0,4",
        source_unit="м3",
        bor_unit="м3",
    )
    assert trace["status"] == "parent_child_calculated"
    assert trace["bor_quantity"] == pytest.approx(1.2)
    assert trace["formula"] == "0.4 м3 × 3 = 1.2 м3"


def test_missing_quantity_is_not_invented_as_one():
    trace = build_quantity_trace(
        work_title="Монтаж изделия",
        source_item="изделие без количества",
        source_unit="шт",
    )
    assert trace["status"] == "missing_quantity"
    assert trace["bor_quantity"] is None


def test_missing_price_is_null_not_zero():
    pack = smeta_estimator_role_pack()
    assert "missing_price_is_null_not_zero" in pack["invariants"]
    assert "Missing price хранится только как `null`/пусто" in SKILL_TEXT


def test_quantity_unit_conversion_is_explicit_and_traceable():
    assert parse_ru_number("27,3") == pytest.approx(27.3)
    assert convert_unit(27.3, "кг", "т") == pytest.approx(0.0273)
    trace = build_quantity_trace(
        work_title="Монтаж металлических деталей",
        source_item="металлическая пластина",
        source_quantity="27,3",
        source_unit="кг",
        bor_unit="т",
    )
    assert trace["status"] == "unit_conversion"
    assert trace["bor_quantity"] == pytest.approx(0.0273)


def test_role_pack_has_no_case_constants_or_legacy_orchestration_contracts():
    pack = smeta_estimator_role_pack()
    text = json.dumps(pack, ensure_ascii=False).lower()
    assert "chain_modes" not in pack
    assert "hard_rules" not in pack
    assert "бап" not in text
    assert "столп" not in text
    assert "664711" not in text
