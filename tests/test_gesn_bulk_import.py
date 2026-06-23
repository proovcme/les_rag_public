"""Массовая заливка ГЭСН-2022 из ФГИС ЦС: классификация труда + перечисление/резюмируемость.

Всё ОФЛАЙН (без сети): синтетика ответа SearchEstimatedRates повторяет реальную структуру
(category-шапка parentId=None → kind; пусконаладочный персонал → labor; эталон 12-01-034-02).
Сетевые функции (_fetch_raw/run) не дёргаем — гоняем чистые хелперы перебора и парс.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.gesn_bulk_import import (
    _existing_otdel_prefixes,
    _otdel_codes,
    _records_for_prefix,
)
from tools.gesn_pdf_import import (
    _is_labor_leaf,
    _kind_from_category,
    parse_fgis_json,
)


# ── фикс классификации труда (3 в ТЗ) ────────────────────────────────
def test_category_kind_labor_variants():
    # машинист РАНЬШЕ общего «…труда…» — иначе machinist уедет в labor
    assert _kind_from_category("Затраты труда машинистов") == "machinist"
    assert _kind_from_category("ЗАТРАТЫ ТРУДА РАБОЧИХ, ВСЕГО: В ТОМ ЧИСЛЕ:") == "labor"
    # раньше падало в material — теперь labor
    assert _kind_from_category("ЗАТРАТЫ ТРУДА ПУСКОНАЛАДОЧНОГО ПЕРСОНАЛА, В ТОМ ЧИСЛЕ:") == "labor"
    assert _kind_from_category("МАШИНЫ И МЕХАНИЗМЫ") == "machine"
    assert _kind_from_category("МАТЕРИАЛЫ") == "material"
    assert _kind_from_category("Оборудование") == "material"
    assert _kind_from_category("что-то постороннее") is None


def test_labor_leaf_detector():
    assert _is_labor_leaf("Средний разряд работы 2,5")
    assert _is_labor_leaf("Рабочий 3 разряда")
    assert _is_labor_leaf("Инженер II категории")
    assert _is_labor_leaf("Техник I категории")
    # ресурсы НЕ должны ловиться как труд
    assert not _is_labor_leaf("Краны башенные, грузоподъемность 8 т")
    assert not _is_labor_leaf("Гвозди строительные")
    assert not _is_labor_leaf("Бруски обрезные хвойных пород")


def _make_record(*, parts: list[dict], cols: list[dict]) -> dict:
    """Собрать запись SearchEstimatedRates (как ФГИС ЦС) из категорий-частей и колонок-норм."""
    return {
        "normTableJson": json.dumps(cols, ensure_ascii=False),
        "normTableValueTableJson": json.dumps(parts, ensure_ascii=False),
    }


def test_pusconaladka_leaf_classified_labor():
    """Регресс бага: дочерние «Инженер/Техник» под пусконаладочной шапкой → labor, не material."""
    cols = [{"number": "01-01-001-01", "name": "Наладка прибора", "meterName": "шт"}]
    parts = [
        # шапка-категория (parentId=None) — НЕ матчилась старыми needle → дети падали в material
        {"NormTablePartId": 10, "NormTablePartParentId": None,
         "Name": "ЗАТРАТЫ ТРУДА ПУСКОНАЛАДОЧНОГО ПЕРСОНАЛА, В ТОМ ЧИСЛЕ:"},
        {"NormTablePartId": 11, "NormTablePartParentId": 10, "Name": "Инженер II категории",
         "Cipher": "", "UnitName": "чел.-ч",
         "NormTablePartNormValueList": [{"NormNumber": "01-01-001-01", "Value": "3.5"}]},
    ]
    rows = parse_fgis_json([_make_record(parts=parts, cols=cols)])
    assert len(rows) == 1
    assert rows[0]["kind"] == "labor"
    assert rows[0]["per_unit"] == 3.5


def test_etalon_12_01_034_02_classification():
    """Эталон ТЗ: труд 12.94 (labor), краны 0.97/0.01, бортовой 0.03, гвозди 0.0015, бруски 0.4."""
    cols = [{"number": "12-01-034-02", "name": "Устройство обрешетки", "meterName": "100 м2"}]
    parts = [
        {"NormTablePartId": 1, "NormTablePartParentId": None, "Name": "ЗАТРАТЫ ТРУДА РАБОЧИХ, ВСЕГО:"},
        {"NormTablePartId": 2, "NormTablePartParentId": 1, "Name": "Средний разряд работы 2,5",
         "Cipher": "", "UnitName": "чел.-ч",
         "NormTablePartNormValueList": [{"NormNumber": "12-01-034-02", "Value": "12.94"}]},
        # машинисты — категория-лист (parentId=None, но со значением)
        {"NormTablePartId": 3, "NormTablePartParentId": None, "Name": "Затраты труда машинистов",
         "Cipher": "", "UnitName": "чел.-ч",
         "NormTablePartNormValueList": [{"NormNumber": "12-01-034-02", "Value": "1.01"}]},
        {"NormTablePartId": 4, "NormTablePartParentId": None, "Name": "МАШИНЫ И МЕХАНИЗМЫ"},
        {"NormTablePartId": 5, "NormTablePartParentId": 4, "Name": "Краны башенные 8 т",
         "Cipher": "91.05.01-017", "UnitName": "маш.-ч",
         "NormTablePartNormValueList": [{"NormNumber": "12-01-034-02", "Value": "0.97"}]},
        {"NormTablePartId": 6, "NormTablePartParentId": 4, "Name": "Краны на автоходу",
         "Cipher": "91.05.05-015", "UnitName": "маш.-ч",
         "NormTablePartNormValueList": [{"NormNumber": "12-01-034-02", "Value": "0.01"}]},
        {"NormTablePartId": 7, "NormTablePartParentId": 4, "Name": "Автомобили бортовые",
         "Cipher": "91.14.02-001", "UnitName": "маш.-ч",
         "NormTablePartNormValueList": [{"NormNumber": "12-01-034-02", "Value": "0.03"}]},
        {"NormTablePartId": 8, "NormTablePartParentId": None, "Name": "МАТЕРИАЛЫ"},
        {"NormTablePartId": 9, "NormTablePartParentId": 8, "Name": "Гвозди строительные",
         "Cipher": "01.7.15.06-0111", "UnitName": "т",
         "NormTablePartNormValueList": [{"NormNumber": "12-01-034-02", "Value": "0.0015"}]},
        {"NormTablePartId": 10, "NormTablePartParentId": 8, "Name": "Бруски обрезные",
         "Cipher": "11.1.03.01-0076", "UnitName": "м3",
         "NormTablePartNormValueList": [{"NormNumber": "12-01-034-02", "Value": "0.4"}]},
    ]
    rows = parse_fgis_json([_make_record(parts=parts, cols=cols)])
    by_kind: dict[str, list] = {}
    for r in rows:
        by_kind.setdefault(r["kind"], []).append(r)
    assert [r["per_unit"] for r in by_kind["labor"]] == [12.94]
    assert [r["per_unit"] for r in by_kind["machinist"]] == [1.01]
    assert sorted(r["per_unit"] for r in by_kind["machine"]) == [0.01, 0.03, 0.97]
    assert sorted(r["per_unit"] for r in by_kind["material"]) == [0.0015, 0.4]
    # код ресурса труда — пуст (ценится тарифом), у машин/материалов — есть
    assert by_kind["labor"][0]["resource_code"] == ""
    assert {r["resource_code"] for r in by_kind["material"]} == {"01.7.15.06-0111", "11.1.03.01-0076"}


# ── перечисление кодов / резюмируемость ──────────────────────────────
def test_otdel_codes_format():
    codes = _otdel_codes(12, otdel_max=5)
    assert codes == ["12-01", "12-02", "12-03", "12-04", "12-05"]


def test_records_for_prefix_filters_fulltext_noise():
    """Fulltext может вернуть постороннее — оставляем лишь записи с шифром на префикс отдела."""
    good = {"normTableJson": json.dumps([{"number": "<em>12-01</em>-034-02"}])}
    noise = {"normTableJson": json.dumps([{"number": "08-12-001-01"}])}
    kept = _records_for_prefix("12-01", [good, noise])
    assert kept == [good]


def test_existing_otdel_prefixes_resume(tmp_path: Path):
    """Резюмируемость: уже залитые отделы вычисляются из norm_code в Parquet."""
    import pandas as pd

    from tools.gesn_import import RESOURCE_FIELDS

    rows = [
        {**{f: None for f in RESOURCE_FIELDS}, "norm_code": "ГЭСН12-01-034-02", "kind": "labor", "per_unit": 1.0},
        {**{f: None for f in RESOURCE_FIELDS}, "norm_code": "12-03-001-01", "kind": "material", "per_unit": 2.0},
    ]
    p = tmp_path / "base.parquet"
    pd.DataFrame(rows, columns=list(RESOURCE_FIELDS)).to_parquet(p, index=False)
    prefixes = _existing_otdel_prefixes(p)
    assert prefixes == {"12-01", "12-03"}
    # пустой/несуществующий файл → пусто (не резюмируем, заливаем заново)
    assert _existing_otdel_prefixes(tmp_path / "nope.parquet") == set()
