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
