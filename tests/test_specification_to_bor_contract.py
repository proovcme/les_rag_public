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


def test_specification_to_bor_spec_is_not_estimate():
    assert "Спецификация не является сметой" in SKILL_TEXT
    assert "не подбирать ГЭСН до построения ВОР" in SKILL_TEXT


def test_specification_to_bor_separates_work_and_supply():
    pack = smeta_estimator_role_pack()
    mode = pack["chain_modes"]["specification_to_bor"]

    assert mode["hard_rules"]["separate_work_and_supply"] is True
    assert "supply_item" in mode["line_roles"]
    assert "work_item" in mode["line_roles"]
    assert "connection_item" in mode["line_roles"]
    assert "testing_item" in mode["line_roles"]
    assert "Поставка не заменяет работы" in SKILL_TEXT


def test_specification_to_bor_preserves_parent_child():
    pack = smeta_estimator_role_pack()
    mode = pack["chain_modes"]["specification_to_bor"]

    assert mode["hard_rules"]["preserve_parent_child_hierarchy"] is True
    assert "parent_quantity" in mode["required_trace_fields"]
    assert "qty_per_parent" in mode["required_trace_fields"]
    assert "parent/child структура не теряется" in SKILL_TEXT


def test_specification_to_bor_multiplies_child_by_parent():
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


def test_specification_to_bor_parent_not_paid_twice():
    pack = smeta_estimator_role_pack()

    assert pack["chain_modes"]["specification_to_bor"]["hard_rules"]["parent_header_not_paid_twice"] is True
    assert "Родительскую строку нельзя автоматически считать второй раз" in SKILL_TEXT


def test_specification_to_bor_missing_quantity_not_one():
    trace = build_quantity_trace(
        work_title="Монтаж изделия",
        source_item="изделие без количества",
        source_unit="шт",
    )

    assert trace["status"] == "missing_quantity"
    assert trace["bor_quantity"] is None
    assert trace["bor_quantity"] != 1
    assert smeta_estimator_role_pack()["chain_modes"]["specification_to_bor"]["hard_rules"]["missing_quantity_is_not_one"]


def test_specification_to_bor_missing_price_not_zero():
    pack = smeta_estimator_role_pack()

    assert pack["hard_rules"]["missing_price_is_not_zero"] is True
    assert pack["chain_modes"]["specification_to_bor"]["hard_rules"]["missing_price_is_not_zero"] is True
    assert "не превращать отсутствующую цену в `0`" in SKILL_TEXT


def test_specification_to_bor_visible_answer_has_bor_table():
    assert "№ | Раздел | Работа | Ед. | Кол-во | Основание из спецификации | Статус" in SKILL_TEXT
    assert "№ | Позиция поставки | Ед. | Кол-во | Источник | Статус цены" in SKILL_TEXT


def test_bor_to_norm_candidate_table_contract():
    pack = smeta_estimator_role_pack()
    mode = pack["chain_modes"]["bor_to_norm_candidate_table"]

    assert mode["hard_rules"]["build_normable_bor_before_rim_pricing"] is True
    assert mode["hard_rules"]["one_source_work_can_split_to_many_norms"] is True
    assert mode["hard_rules"]["candidate_norm_is_not_final_selection"] is True
    assert mode["hard_rules"]["excel_roundtrip_can_confirm_or_reject_candidates"] is True
    assert "candidate_norm_code" in mode["required_fields"]
    assert "norm_quantity" in mode["required_fields"]
    assert "confirmed_by_user" in mode["applicability_statuses"]
    assert "ВОР -> нормируемая ВОР -> таблица подбора норм" in SKILL_TEXT
    assert "Одна строка исходной ВОР может обоснованно разложиться на несколько ГЭСН" in SKILL_TEXT


def test_bor_to_norm_candidate_table_columns_visible():
    pack = smeta_estimator_role_pack()

    assert "№ ВОР" in pack["norm_candidate_table_columns"]
    assert "Исходная работа" in pack["norm_candidate_table_columns"]
    assert "Нормируемая работа" in pack["norm_candidate_table_columns"]
    assert "Код ГЭСН" in pack["norm_candidate_table_columns"]
    assert "Статус применимости" in pack["norm_candidate_table_columns"]
    assert "удаляет лишние ГЭСН" in SKILL_TEXT
    assert "Расчёт РИМ/ЛСР выполняется только по подтверждённым" in SKILL_TEXT


def test_smeta_visible_language_avoids_internal_terms():
    assert "Не проговаривать запреты" in SKILL_TEXT
    assert "таблица подбора норм" in SKILL_TEXT
    assert "исходные параметры" in SKILL_TEXT
    assert "расчётная проверка" in SKILL_TEXT


def test_specification_to_bor_unit_conversion_trace():
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
    assert trace["source_unit"] == "кг"
    assert trace["bor_unit"] == "т"


def test_specification_to_bor_role_pack_has_no_examples_or_case_constants():
    text = json.dumps(smeta_estimator_role_pack(), ensure_ascii=False).lower()

    assert "minimal_example" not in text
    assert "столп" not in text
    assert "пьедестал" not in text
    assert "664711" not in text
