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
    ALL_COLLECTION_PREFIXES,
    _existing_otdel_prefixes,
    _otdel_codes,
    _records_for_prefix,
    run,
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
        "documentTypeName": "ГЭСН",
        "documentName": "ГЭСН synthetic fixture",
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


def test_fgis_sibling_column_uses_its_own_name_and_common_meter():
    """Exact search returns one col metadata row but resource values for sibling norms."""
    cols = [{"number": "15-04-005-10", "name": "Окраска потолков", "meterName": "100 м2"}]
    parts = [
        {"NormTablePartId": 1, "NormTablePartParentId": None, "Name": "Затраты труда рабочих"},
        {
            "NormTablePartId": 2,
            "NormTablePartParentId": 1,
            "Name": "Средний разряд работы 3,0",
            "Cipher": "1-100-30",
            "UnitName": "чел.-ч",
            "NormTablePartNormValueList": [
                {"NormNumber": "15-04-005-09", "NormName": "Окраска стен", "Value": "10"},
                {"NormNumber": "15-04-005-10", "NormName": "Окраска потолков", "Value": "12"},
            ],
        },
    ]

    rows = parse_fgis_json([_make_record(parts=parts, cols=cols)])
    by_code = {row["norm_code"]: row for row in rows}

    assert by_code["15-04-005-09"]["norm_name"] == "Окраска стен"
    assert by_code["15-04-005-09"]["norm_unit"] == "100 м2"
    assert by_code["15-04-005-10"]["norm_name"] == "Окраска потолков"


def test_etalon_12_01_034_02_classification():
    """Эталон ТЗ: труд 12.94 (labor), краны 0.97/0.01, бортовой 0.03, гвозди 0.0015, бруски 0.4."""
    cols = [{"number": "12-01-034-02", "name": "Устройство обрешетки", "meterName": "100 м2"}]
    parts = [
        {"NormTablePartId": 1, "NormTablePartParentId": None, "Name": "ЗАТРАТЫ ТРУДА РАБОЧИХ, ВСЕГО:"},
        {"NormTablePartId": 2, "NormTablePartParentId": 1, "Name": "Средний разряд работы 2,5",
         "Cipher": "1-100-25", "UnitName": "чел.-ч",
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
    # код ресурса труда — тариф ФГИС ЦС, у машин/материалов — ресурсный код
    assert by_kind["labor"][0]["resource_code"] == "1-100-25"
    assert {r["resource_code"] for r in by_kind["material"]} == {"01.7.15.06-0111", "11.1.03.01-0076"}


# ── перечисление кодов / резюмируемость ──────────────────────────────
def test_otdel_codes_format():
    codes = _otdel_codes(12, otdel_max=5)
    assert codes == ["12-01", "12-02", "12-03", "12-04", "12-05"]


def test_full_import_scans_all_fgis_numeric_prefixes():
    assert ALL_COLLECTION_PREFIXES == tuple(range(1, 70))


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


def test_raw_cache_looks_complete_uses_prefix_floor(tmp_path: Path):
    import pandas as pd

    from tools.gesn_import import RESOURCE_FIELDS
    from tools import gesn_bulk_import as bulk

    rows = []
    for idx in range(5):
        rows.append(
            {
                **{f: None for f in RESOURCE_FIELDS},
                "norm_code": f"12-0{idx+1}-001-01",
                "kind": "labor",
                "per_unit": 1.0,
            }
        )
    path = tmp_path / "raw.parquet"
    pd.DataFrame(rows, columns=list(RESOURCE_FIELDS)).to_parquet(path, index=False)
    assert bulk.raw_cache_looks_complete(path, floor=5) is True
    assert bulk.raw_cache_looks_complete(path, floor=6) is False


def test_bulk_import_skips_cached_empty_otdels_without_fetch(monkeypatch, tmp_path: Path):
    from tools import gesn_bulk_import as bulk

    out = tmp_path / "raw.parquet"
    bulk._save_empty_otdel_prefixes(out, {"01-02"})
    calls: list[str] = []

    monkeypatch.setattr(bulk, "_otdel_codes", lambda *_a, **_k: ["01-01", "01-02", "01-03"])
    monkeypatch.setattr(bulk, "_existing_otdel_prefixes", lambda _path: {"01-01"})
    monkeypatch.setattr(
        bulk,
        "_fetch_with_retry",
        lambda prefix: calls.append(prefix) or [],
    )

    stats = bulk.run(sborniki=[1], out_path=out, rate=0, resume=True, flush_every=10)
    assert stats["otdels_skipped"] == 1
    assert stats["otdels_empty"] >= 1
    assert "01-02" not in calls
    assert "01-03" in calls


def test_gesn_update_skips_network_when_raw_cache_complete(tmp_path: Path, monkeypatch):
    from tools import gesn_update_from_fgis as updater

    calls: list[str] = []
    monkeypatch.setattr(updater.gesn_bulk_import, "raw_cache_looks_complete", lambda *_a, **_k: True)
    monkeypatch.setattr(updater.gesn_bulk_import, "_existing_otdel_prefixes", lambda *_a, **_k: {"01-01", "12-03"})
    monkeypatch.setattr(
        updater.gesn_bulk_import,
        "run",
        lambda **_: calls.append("download") or (_ for _ in ()).throw(AssertionError("must skip download")),
    )
    monkeypatch.setattr(updater, "build_unified", lambda **_: {"norm_keys": 2})
    monkeypatch.setattr(updater, "build_structured_base", lambda **_: {"norms": 2})
    monkeypatch.setattr(updater.build_smeta_service_rag, "build", lambda *_a, **_k: {"ok": True})
    monkeypatch.setattr(
        "proxy.smeta_core.base_registry.active_base",
        lambda: {"minimum_norms": 1},
    )

    result = updater.run_update(
        raw_out=tmp_path / "raw.parquet",
        unified_out=tmp_path / "unified.parquet",
        audit_out=tmp_path / "audit.json",
        structured_out=tmp_path / "base.sqlite",
        structured_manifest_out=tmp_path / "manifest.json",
        service_rag_out=tmp_path / "rag",
        status_out=tmp_path / "status.json",
    )
    assert calls == []
    assert result["download"]["resumed_complete"] is True
    assert result["download"]["otdels_skipped"] == 2


def test_bulk_import_flushes_departments_in_batches(monkeypatch, tmp_path: Path):
    records = [{"normTableJson": json.dumps([{"number": "01-01-001-01"}])}]
    rows = [{"norm_code": "ГЭСН01-01-001-01", "kind": "labor", "per_unit": 1.0}]
    writes = []

    monkeypatch.setattr("tools.gesn_bulk_import._otdel_codes", lambda *_a, **_k: ["01-01", "01-02", "01-03"])
    monkeypatch.setattr("tools.gesn_bulk_import._fetch_with_retry", lambda _prefix: records)
    monkeypatch.setattr("tools.gesn_bulk_import._records_for_prefix", lambda _prefix, _raw: records)
    monkeypatch.setattr("tools.gesn_bulk_import.parse_fgis_json", lambda _records: list(rows))
    monkeypatch.setattr(
        "tools.gesn_bulk_import.build_parquet",
        lambda batch, _path, append: writes.append(list(batch)) or {"resources": len(batch)},
    )

    result = run(
        sborniki=[1], out_path=tmp_path / "raw.parquet", rate=0,
        resume=False, flush_every=2,
    )

    assert result["otdels_done"] == 3
    assert [len(batch) for batch in writes] == [2, 1]
