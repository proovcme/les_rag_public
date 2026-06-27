"""Импортёр базы ГЭСН-2022: выгрузка (xlsx flat / blocks) → Parquet → get_norm/expand.

Фикстуры строят мини-выгрузки (как `test_fgis_price_service` строит мини-«Сплит-форму»),
проверяют оба layout, нормализацию kind/кода и чтение базы сервисом поверх семени.
Эталонный gold (`test_gesn_service`) не трогаем — там семя без базы.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.gesn_import import (
    RESOURCE_FIELDS,
    build_gesn_parquet,
    parse_blocks,
    parse_flat,
)

# ── flat: одна строка на ресурс, явная шапка ─────────────────────────
FLAT_HEADERS = [
    "norm_code", "norm_name", "norm_unit", "kind",
    "per_unit", "resource_code", "resource_name", "resource_unit", "price",
]
FLAT_DATA = [
    ("ГЭСН08-02-001-01", "Кладка стен из кирпича", "1 м3", "labor", 4.2, "", "Рабочие, разряд 3,2", "чел.-ч", 510.0),
    ("ГЭСН08-02-001-01", "Кладка стен из кирпича", "1 м3", "machine", 0.18, "91.05.01-017", "Краны башенные 8 т", "маш.-ч", 865.44),
    ("ГЭСН08-02-001-01", "Кладка стен из кирпича", "1 м3", "machinist", 0.18, "", "ОТм краны 8 т", "чел.-ч", 750.17),
    ("ГЭСН08-02-001-01", "Кладка стен из кирпича", "1 м3", "material", 0.39, "04.3.01.09-0102", "Кирпич керамический", "1000 шт", 18500.0),
]


def _make_flat_xlsx(path: Path) -> None:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Выгрузка ресурсной части ГЭСН-2022"])      # строка-примечание над шапкой
    ws.append(FLAT_HEADERS)
    for rec in FLAT_DATA:
        ws.append(list(rec))
    wb.save(path)


# ── blocks: норма-блоками (русские метки категорий) ──────────────────
def _make_blocks_csv(path: Path) -> None:
    import csv

    rows = [
        ["ГЭСН08-02-001-02", "Кладка перегородок из кирпича", "100 м2", "", ""],
        ["", "Затраты труда рабочих", "чел.-ч", "5.5", ""],
        ["", "Машины и механизмы", "Краны башенные 8 т", "0.2", "91.05.01-017"],
        ["", "Материалы", "Раствор кладочный", "8.1", "04.3.01.21-0001"],
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows(rows)


@pytest.fixture()
def flat_xlsx(tmp_path: Path) -> Path:
    p = tmp_path / "gesn_flat.xlsx"
    _make_flat_xlsx(p)
    return p


@pytest.fixture()
def blocks_csv(tmp_path: Path) -> Path:
    p = tmp_path / "gesn_blocks.csv"
    _make_blocks_csv(p)
    return p


# ── парсеры ──────────────────────────────────────────────────────────
def test_parse_flat_normalizes(flat_xlsx: Path):
    from tools.gesn_import import _read_rows

    recs = parse_flat(_read_rows(flat_xlsx))
    assert len(recs) == 4
    assert all(set(RESOURCE_FIELDS) == set(r) for r in recs)
    kinds = {r["kind"] for r in recs}
    assert kinds == {"labor", "machine", "machinist", "material"}
    mat = next(r for r in recs if r["kind"] == "material")
    assert mat["per_unit"] == 0.39
    assert mat["resource_code"] == "04.3.01.09-0102"


def test_parse_blocks_kind_from_label(blocks_csv: Path):
    from tools.gesn_import import _read_rows

    recs = parse_blocks(_read_rows(blocks_csv))
    assert {r["norm_code"] for r in recs} == {"ГЭСН08-02-001-02"}
    by_kind = {r["kind"]: r for r in recs}
    assert by_kind["labor"]["per_unit"] == 5.5
    assert by_kind["machine"]["resource_code"] == "91.05.01-017"
    assert by_kind["material"]["per_unit"] == 8.1


# ── полный конвейер: выгрузка → parquet → сервис ─────────────────────
def test_import_to_parquet_and_read(flat_xlsx: Path, tmp_path: Path):
    from proxy.services import gesn_service as gs

    out = tmp_path / "gesn2022.parquet"
    summary = build_gesn_parquet(flat_xlsx, out, layout="flat")
    assert summary["norms"] == 1
    assert summary["resources"] == 4
    assert Path(summary["parquet"]).exists()

    gs.load_base_norms.cache_clear()
    norm = gs.get_norm("ГЭСН08-02-001-01", base_path=str(out))
    assert norm is not None
    assert norm["unit"] == "1 м3"
    assert len(norm["resources"]) == 4

    # expand × объём (per_unit × qty)
    lines = gs.expand_position("гэсн08-02-001-01", 2.0, base_path=str(out))   # регистр-норм
    assert lines is not None and len(lines) == 4
    labor = next(l for l in lines if l["kind"] == "labor")
    assert round(labor["qty"], 4) == 8.4              # 4.2 × 2
    assert labor["price"] == 510.0
    mat = next(l for l in lines if l["kind"] == "material")
    assert mat["code"] == "04.3.01.09-0102"


def test_base_type_prevents_gesn_gesnm_collision(tmp_path: Path):
    """Одинаковый номер нормы в ГЭСН и ГЭСНм не должен схлопываться в один ресурсный блок."""
    import pandas as pd

    from proxy.services import gesn_service as gs

    rows = [
        {
            **{f: None for f in RESOURCE_FIELDS},
            "norm_code": "38-01-001-01",
            "norm_name": "Возведение плотин каменно-набросных",
            "norm_unit": "1000 м3",
            "kind": "machine",
            "per_unit": 3.0,
            "resource_code": "91.05.01-017",
            "resource_name": "Краны башенные",
            "resource_unit": "маш.-ч",
            "base_type": "ГЭСН",
            "norm_key": "ГЭСН:38-01-001-01",
        },
        {
            **{f: None for f in RESOURCE_FIELDS},
            "norm_code": "38-01-001-01",
            "norm_name": "Листовые конструкции массой свыше 0,5 т",
            "norm_unit": "т",
            "kind": "labor",
            "per_unit": 91.8,
            "resource_code": "1-100-40",
            "resource_name": "Средний разряд работы 4,0",
            "resource_unit": "чел.-ч",
            "base_type": "ГЭСНм",
            "norm_key": "ГЭСНм:38-01-001-01",
        },
    ]
    out = tmp_path / "gesn_collision.parquet"
    pd.DataFrame(rows, columns=list(RESOURCE_FIELDS)).to_parquet(out, index=False)

    gs.load_base_norms.cache_clear()
    construction = gs.get_norm("ГЭСН38-01-001-01", base_path=str(out))
    metal = gs.get_norm("ГЭСНм38-01-001-01", base_path=str(out))
    bare = gs.get_norm("38-01-001-01", base_path=str(out))

    assert construction is not None and "плотин" in construction["name"]
    assert metal is not None and "Листовые конструкции" in metal["name"]
    assert bare is not None and bare["key"] == "ГЭСН:38-01-001-01"

    lines = gs.expand_position("ГЭСНм38-01-001-01", 2.0, base_path=str(out))
    assert lines == [{
        "kind": "labor",
        "name": "Средний разряд работы 4,0",
        "unit": "чел.-ч",
        "qty": 183.6,
        "code": "1-100-40",
    }]


def test_base_merges_under_seed(flat_xlsx: Path, tmp_path: Path):
    """База дополняет семя; эталон семени остаётся (семя побеждает по коду)."""
    from proxy.services import gesn_service as gs

    out = tmp_path / "gesn2022.parquet"
    build_gesn_parquet(flat_xlsx, out, layout="flat")
    gs.load_base_norms.cache_clear()

    codes = {n["code"].upper().replace(" ", "") for n in gs.list_norms(base_path=str(out))}
    assert "ГЭСН08-02-001-01" in codes                 # из базы
    assert "ГЭСН12-01-034-02" in codes                 # из семени
    # эталон семени читается так же, как без базы
    etalon = gs.get_norm("ГЭСН12-01-034-02", base_path=str(out))
    assert etalon is not None and etalon["unit"] == "100 м2"


def test_missing_base_falls_back_to_seed(tmp_path: Path):
    """Базы нет → load_base_norms пуст, get_norm работает на семени."""
    from proxy.services import gesn_service as gs

    gs.load_base_norms.cache_clear()
    missing = tmp_path / "nope.parquet"
    assert gs.load_base_norms(str(missing)) == {}
    assert gs.get_norm("ГЭСН12-01-034-02", base_path=str(missing)) is not None
