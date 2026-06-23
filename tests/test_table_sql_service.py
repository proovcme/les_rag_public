"""Группируемая агрегация по parquet (Ц6): sum/count по полю, фильтр, group-by, белый список."""

from __future__ import annotations

from pathlib import Path

import pytest

from proxy.services.table_sql_service import aggregate


def _make_ds(root: Path, ds: str, rows: list[dict]) -> None:
    import pandas as pd

    pdir = root / ds / "_parquet"
    pdir.mkdir(parents=True)
    pd.DataFrame(rows).to_parquet(pdir / "t.parquet", index=False)


ROWS = [
    {"section": "Раздел 1", "name": "Кабель ВВГ", "code": "01", "qty": 10, "amount": 100.0},
    {"section": "Раздел 1", "name": "Лоток", "code": "02", "qty": 5, "amount": 200.0},
    {"section": "Раздел 2", "name": "Кабель НЮМ", "code": "03", "qty": 3, "amount": 50.0},
]


@pytest.fixture()
def store(tmp_path: Path) -> Path:
    _make_ds(tmp_path, "ds1", ROWS)
    return tmp_path


def test_group_by_section_sum(store: Path):
    r = aggregate(["ds1"], field="amount", op="sum", group_by="section", storage_root=store)
    by = {x["group"]: x["value"] for x in r["rows"]}
    assert by == {"Раздел 1": 300.0, "Раздел 2": 50.0}
    assert r["total"] == 350.0
    assert r["rows"][0]["group"] == "Раздел 1"      # отсортировано по убыванию


def test_total_no_group(store: Path):
    r = aggregate(["ds1"], field="amount", op="sum", storage_root=store)
    assert r["total"] == 350.0 and r["rows"] == []


def test_contains_filter(store: Path):
    r = aggregate(["ds1"], field="amount", op="sum", contains="кабель", storage_root=store)
    assert r["total"] == 150.0                       # только «Кабель …» строки


def test_count(store: Path):
    assert aggregate(["ds1"], op="count", storage_root=store)["total"] == 3


def test_whitelist_guards(store: Path):
    with pytest.raises(ValueError):
        aggregate(["ds1"], field="amount; DROP", op="sum", storage_root=store)
    with pytest.raises(ValueError):
        aggregate(["ds1"], field="amount", op="evil", storage_root=store)
    with pytest.raises(ValueError):
        aggregate(["ds1"], field="amount", group_by="name; --", storage_root=store)


def test_no_parquet(tmp_path: Path):
    assert aggregate(["missing"], field="amount", storage_root=tmp_path)["total"] is None


# --- Фолбэк на raw_row: типизированные qty/amount/section null → число берётся из raw_row ---

def _make_raw(qty, amount, qty_key="Коли-\nчество", section_val=None, raw_extra=None):
    import json as _json

    raw = {qty_key: qty, "Сумма, руб": amount, "Наименование": "Кабель"}
    if section_val is not None:
        raw["Раздел"] = section_val
    if raw_extra:
        raw.update(raw_extra)
    return {"doc_type": "SPEC", "section": None, "name": "Кабель", "code": "01",
            "qty": None, "amount": None, "raw_row": _json.dumps(raw, ensure_ascii=False)}


RAW_ROWS = [
    _make_raw("10", "100,50", section_val="Раздел А"),   # qty/amount/section только в raw_row
    _make_raw("5", "200", section_val="Раздел А"),
    _make_raw("3", "1 019,39", section_val="Раздел Б"),  # русский формат «1 019,39»
]


@pytest.fixture()
def raw_store(tmp_path: Path) -> Path:
    _make_ds(tmp_path, "raw1", RAW_ROWS)
    return tmp_path


def test_raw_row_qty_sum_total(raw_store: Path):
    # qty-колонка null, число «10/5/3» лежит в raw_row под ключом «Коли- чество» (PDF-перенос).
    r = aggregate(["raw1"], field="qty", op="sum", storage_root=raw_store)
    assert r["total"] == 18.0
    assert r["count"] == 3


def test_raw_row_amount_sum_total(raw_store: Path):
    # amount-колонка null, «100,50/200/1 019,39» (рус. формат) из raw_row.
    r = aggregate(["raw1"], field="amount", op="sum", storage_root=raw_store)
    assert r["total"] == 1319.89


def test_raw_row_section_group(raw_store: Path):
    # section-колонка null → группировка по «Раздел» из raw_row, суммы qty из raw_row.
    r = aggregate(["raw1"], field="qty", op="sum", group_by="section", storage_root=raw_store)
    by = {x["group"]: x["value"] for x in r["rows"]}
    assert by == {"Раздел А": 15.0, "Раздел Б": 3.0}


def test_raw_row_does_not_override_typed(tmp_path: Path):
    # Если типизированная qty НЕ пуста — берём её, raw_row не перетирает.
    rows = [{"doc_type": "SPEC", "name": "X", "qty": 7, "amount": None,
             "raw_row": '{"Количество": 999}'}]
    _make_ds(tmp_path, "mix", rows)
    r = aggregate(["mix"], field="qty", op="sum", storage_root=tmp_path)
    assert r["total"] == 7.0
