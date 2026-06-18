"""W11.4 — сверка количеств между типами документов (ВОР↔КС-2↔смета↔ИД).

Офлайн, без LLM и живых сервисов: pure-функции + полный цикл на синтетике Parquet.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.parquet_writer import save_parquet
from proxy.services.reconcile_service import (
    _row_qty,
    aggregate_positions,
    collect_rows_by_doc_type,
    reconcile_datasets,
    reconcile_sources,
)


def _row(doc_type, name, unit="м", qty=None, **kw) -> dict:
    row = {"doc_type": doc_type, "name": name, "unit": unit, "qty": qty}
    row.update(kw)
    return row


def _by_name(result, name):
    return next(r for r in result["rows"] if r["name"] == name)


# ── выбор количества (qty-приоритет + fallback по полям объёма) ──

def test_row_qty_prefers_qty():
    assert _row_qty({"qty": 10.0, "work_done": 99.0}) == 10.0


def test_row_qty_falls_back_to_work_done():
    assert _row_qty({"qty": None, "work_done": 7.5}) == 7.5


def test_row_qty_none_when_no_numbers():
    assert _row_qty({"qty": None, "work_done": None}) is None


# ── агрегация одного источника ──

def test_aggregate_sums_same_position():
    agg = aggregate_positions([
        _row("SMETA", "Кабель ВВГнг 3х1,5", qty=10.0),
        _row("SMETA", "кабель ввгнг 3х1,5", qty=5.0),
    ])
    assert len(agg) == 1
    entry = next(iter(agg.values()))
    assert entry["qty"] == pytest.approx(15.0)


def test_aggregate_keeps_longest_name():
    agg = aggregate_positions([
        _row("SMETA", "Кабель", qty=1.0),
        _row("SMETA", "Кабель", qty=1.0),
    ])
    assert next(iter(agg.values()))["name"] == "Кабель"


# ── сверка: согласие количеств ──

def test_match_when_quantities_agree():
    res = reconcile_sources({
        "SMETA": [_row("SMETA", "Кабель ВВГ 3х1,5", qty=15030.72)],
        "VEDOMOST": [_row("VEDOMOST", "Кабель ВВГ 3х1,5", qty=15030.72)],
        "KS2": [_row("KS2", "Кабель ВВГ 3х1,5", qty=None, work_done=15030.72)],
    })
    row = _by_name(res, "Кабель ВВГ 3х1,5")
    assert row["status"] == "match"
    assert set(row["present"]) == {"SMETA", "VEDOMOST", "KS2"}
    assert row["max_delta"] == 0.0


def test_mismatch_flagged_when_quantities_differ():
    res = reconcile_sources({
        "SMETA": [_row("SMETA", "Лоток кабельный", "м", qty=100.0)],
        "KS2": [_row("KS2", "Лоток кабельный", "м", work_done=85.0)],
    })
    row = _by_name(res, "Лоток кабельный")
    assert row["status"] == "mismatch"
    assert row["max_delta"] == pytest.approx(15.0)
    assert row["delta_pct"] == pytest.approx(15.0)
    assert res["totals"]["mismatch"] == 1


def test_relative_tolerance_absorbs_rounding():
    # 0,5 % расхождения < допуска 1 % → считается сходящимся
    res = reconcile_sources({
        "SMETA": [_row("SMETA", "Труба ВГП", "м", qty=1000.0)],
        "KS2": [_row("KS2", "Труба ВГП", "м", qty=1005.0)],
    })
    assert _by_name(res, "Труба ВГП")["status"] == "match"


def test_gap_when_missing_in_some_sources():
    res = reconcile_sources({
        "SMETA": [_row("SMETA", "Щит ВРУ", "шт", qty=2.0), _row("SMETA", "Автомат C16", "шт", qty=10.0)],
        "KS2": [_row("KS2", "Щит ВРУ", "шт", qty=2.0)],
    })
    # Автомат C16 есть в смете, нет в КС-2 → пробел
    assert _by_name(res, "Автомат C16")["status"] == "gap"
    assert _by_name(res, "Щит ВРУ")["status"] == "match"
    assert res["totals"]["gap"] == 1


def test_position_only_in_one_of_several_is_gap():
    # есть в смете, нет в КС-2 → пробел (ключевой сигнал для ГИП), не «single»
    res = reconcile_sources({
        "SMETA": [_row("SMETA", "Только в смете", "шт", qty=1.0)],
        "KS2": [_row("KS2", "Только в КС-2", "шт", qty=1.0)],
    })
    assert _by_name(res, "Только в смете")["status"] == "gap"
    assert _by_name(res, "Только в КС-2")["status"] == "gap"
    assert res["totals"]["gap"] == 2


def test_single_only_when_one_doc_type():
    res = reconcile_sources({"SMETA": [_row("SMETA", "Одинокая позиция", "шт", qty=1.0)]})
    assert _by_name(res, "Одинокая позиция")["status"] == "single"


def test_unit_mismatch_does_not_cluster():
    res = reconcile_sources({
        "SMETA": [_row("SMETA", "Кабель", "м", qty=100.0)],
        "KS2": [_row("KS2", "Кабель", "шт", qty=5.0)],
    })
    # разные единицы → две отдельные позиции, обе только в одном источнике → пробел
    statuses = sorted(r["status"] for r in res["rows"])
    assert statuses == ["gap", "gap"]


def test_name_containment_clusters_across_sources():
    res = reconcile_sources({
        "SMETA": [_row("SMETA", "Кабель ВВГнг", "м", qty=500.0)],
        "VEDOMOST": [_row("VEDOMOST", "Кабель ВВГнг-LS 3х2,5 ГОСТ", "м", qty=500.0)],
    })
    assert len(res["rows"]) == 1
    assert res["rows"][0]["status"] == "match"


# ── полный цикл по датасетам (Parquet → сверка → xlsx) ──

def _make_parquet(tmp_path: Path, dataset_id: str, rows: list[dict]) -> None:
    parquet_dir = tmp_path / dataset_id / "_parquet"
    parquet_dir.mkdir(parents=True)
    full_rows = []
    for r in rows:
        base = {k: None for k in ("qty", "work_done", "work_since_start", "work_volume")}
        base.update({"doc_type": "", "name": "", "unit": "", "source_file": "x.xlsx"})
        base.update(r)
        full_rows.append(base)
    save_parquet(full_rows, str(parquet_dir / f"{dataset_id}.parquet"))


def test_collect_rows_by_doc_type_groups(tmp_path):
    _make_parquet(tmp_path, "ds", [
        _row("SMETA", "Поз A", qty=1.0),
        _row("KS2", "Поз A", qty=1.0),
        _row("SMETA", "", qty=9.0),  # без имени — отбрасывается
    ])
    by_type = collect_rows_by_doc_type("ds", storage_root=tmp_path)
    assert set(by_type) == {"SMETA", "KS2"}
    assert len(by_type["SMETA"]) == 1


def test_reconcile_datasets_end_to_end_xlsx(tmp_path):
    _make_parquet(tmp_path, "smeta_ds", [_row("SMETA", "Кабель 3х1,5", qty=15030.72)])
    _make_parquet(tmp_path, "ks2_ds", [_row("KS2", "Кабель 3х1,5", qty=None, work_done=14000.0)])
    out_dir = tmp_path / "out"
    res = reconcile_datasets(["smeta_ds", "ks2_ds"], storage_root=tmp_path, output_dir=out_dir)
    row = _by_name(res, "Кабель 3х1,5")
    assert row["status"] == "mismatch"
    assert row["qty_by_source"]["SMETA"] == pytest.approx(15030.72)
    assert row["qty_by_source"]["KS2"] == pytest.approx(14000.0)
    xlsx = Path(res["xlsx_path"])
    assert xlsx.exists()


def test_reconcile_by_dataset_axis(tmp_path):
    # два документа ОДНОГО типа (обе ведомости) сравниваются по оси датасета, а не схлопываются
    _make_parquet(tmp_path, "vor", [_row("VEDOMOST", "Коробка установочная", "шт", qty=395.0)])
    _make_parquet(tmp_path, "akt", [_row("VEDOMOST", "Коробка установочная", "шт", qty=60.0)])
    res = reconcile_datasets(
        ["vor", "akt"], storage_root=tmp_path, by="dataset",
        dataset_names={"vor": "ВОР", "akt": "Акт"},
    )
    assert set(res["doc_types"]) == {"ВОР", "Акт"}  # ось = датасет, ярлыки из имён
    row = _by_name(res, "Коробка установочная")
    assert row["status"] == "mismatch"
    assert row["qty_by_source"]["ВОР"] == 395.0
    assert row["qty_by_source"]["Акт"] == 60.0


def test_reconcile_by_doctype_default_collapses(tmp_path):
    # по умолчанию (doc_type) две ведомости схлопываются в один источник → single
    _make_parquet(tmp_path, "vor", [_row("VEDOMOST", "Коробка", "шт", qty=395.0)])
    _make_parquet(tmp_path, "akt", [_row("VEDOMOST", "Коробка", "шт", qty=60.0)])
    res = reconcile_datasets(["vor", "akt"], storage_root=tmp_path)
    assert res["doc_types"] == ["VEDOMOST"]
    assert _by_name(res, "Коробка")["status"] == "single"


def test_reconcile_uses_no_llm():
    """ADR-11: сервис сверки не зовёт LLM/HTTP."""
    import inspect

    import proxy.services.reconcile_service as rec

    source = inspect.getsource(rec)
    for marker in ("import httpx", "import openai", "import requests", "/api/chat", "completions"):
        assert marker not in source, f"LLM/HTTP-маркер '{marker}' в reconcile_service"
