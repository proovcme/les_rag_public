"""W11.10 — спецификация (Ф9) → ВОР работ. Офлайн, без LLM."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.parquet_writer import save_parquet
from proxy.services.spec_to_bor_service import (
    generate_spec_bor,
    spec_rows_to_work_lines,
    work_verb,
)


def _spec(name, unit="шт", qty=1.0, **kw):
    row = {"doc_type": "SPEC", "name": name, "unit": unit, "qty": qty, "source_file": "spec.xlsx"}
    row.update(kw)
    return row


# ── словарь глаголов ──

def test_verb_cable_is_prokladka():
    assert work_verb("Кабель медный ВВГнг 3х1,5") == "Прокладка"
    assert work_verb("Провод ПВ-1") == "Прокладка"


def test_verb_equipment_is_montazh():
    assert work_verb("Светильник NOTOR78 LED") == "Монтаж"
    assert work_verb("Щит распределительный ЩР") == "Монтаж"
    assert work_verb("Лоток кабельный 200х50") == "Монтаж"


def test_verb_fasteners_is_ustanovka():
    assert work_verb("Коробка установочная") == "Установка"
    assert work_verb("Наконечник кабельный") == "Установка"


def test_verb_default_montazh():
    assert work_verb("Нечто непонятное X") == "Монтаж"


# ── свод работ ──

def test_work_name_format_and_qty_carry():
    lines = spec_rows_to_work_lines([_spec("Светильник LED", "шт", 280.0)])
    assert len(lines) == 1
    assert lines[0].name == "Монтаж: Светильник LED"
    assert lines[0].qty == pytest.approx(280.0)
    assert lines[0].unit == "шт"


def test_cable_in_meters_prokladka():
    lines = spec_rows_to_work_lines([_spec("Кабель ВВГнг 3х1,5", "м", 744.93)])
    assert lines[0].name == "Прокладка: Кабель ВВГнг 3х1,5"
    assert lines[0].unit == "м"
    assert lines[0].qty == pytest.approx(744.93)


def test_identical_works_summed():
    lines = spec_rows_to_work_lines([
        _spec("Светильник LED", "шт", 280.0),
        _spec("Светильник LED", "шт", 109.0),
    ])
    assert len(lines) == 1
    assert lines[0].qty == pytest.approx(389.0)


def test_noise_rows_skipped():
    lines = spec_rows_to_work_lines([
        _spec("1. Раздел освещение", "", None),
        _spec("2", "шт", 5.0),
        _spec("Розетка 220В", "шт", 7.0),
    ])
    assert [l.name for l in lines] == ["Установка: Розетка 220В"]


def test_qty_missing_tracked():
    lines = spec_rows_to_work_lines([_spec("Прибор учёта", "шт", None)])
    assert lines[0].qty is None
    assert lines[0].qty_missing_rows == 1


# ── полный цикл Parquet → xlsx ──

def test_generate_spec_bor_end_to_end(tmp_path):
    parquet_dir = tmp_path / "ds" / "_parquet"
    parquet_dir.mkdir(parents=True)
    rows = [
        _spec("Кабель ВВГнг 3х1,5", "м", 744.93),
        _spec("Светильник LED", "шт", 280.0),
        _spec("Коробка установочная", "шт", 60.0),
    ]
    save_parquet(rows, str(parquet_dir / "spec.parquet"))
    out = tmp_path / "out"
    res = generate_spec_bor("ds", storage_root=tmp_path, output_dir=out)
    assert res["bor_lines"] == 3
    names = {l["name"] for l in res["lines"]}
    assert "Прокладка: Кабель ВВГнг 3х1,5" in names
    assert "Монтаж: Светильник LED" in names
    assert "Установка: Коробка установочная" in names
    assert Path(res["xlsx_path"]).exists()


def test_uses_no_llm():
    import inspect

    import proxy.services.spec_to_bor_service as svc

    src = inspect.getsource(svc)
    for marker in ("import httpx", "import openai", "/api/chat", "completions"):
        assert marker not in src
