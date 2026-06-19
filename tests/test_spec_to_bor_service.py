"""W11.10 — спецификация (Ф9) → ВОР работ. Офлайн, без LLM."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.parquet_writer import save_parquet
from proxy.services.spec_to_bor_service import (
    generate_spec_bor,
    is_spec_to_bor_query,
    spec_rows_to_work_lines,
    work_verb,
)


def test_is_spec_to_bor_query_word_boundary():
    # «повороты» содержит подстроку «вор» — НЕ должно триггерить канал ВОР
    assert is_spec_to_bor_query("Собери спецификацию лотков 200х50, повороты, крышки") is False
    assert is_spec_to_bor_query("спецификация светильников, забор, творог") is False
    # легитимные «ВОР из спецификации» — должны
    assert is_spec_to_bor_query("сделай ВОР из спецификации формы 9") is True
    assert is_spec_to_bor_query("ведомость объёмов работ из спецификации") is True


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
    res = generate_spec_bor("ds", storage_root=tmp_path, output_dir=out, decompose=False)  # v1
    assert res["bor_lines"] == 3 and res["mode"] == "simple"
    names = {l["name"] for l in res["lines"]}
    assert "Прокладка: Кабель ВВГнг 3х1,5" in names
    assert "Монтаж: Светильник LED" in names
    assert "Установка: Коробка установочная" in names
    assert Path(res["xlsx_path"]).exists()


def test_generate_spec_bor_v2_decompose(tmp_path):
    parquet_dir = tmp_path / "ds" / "_parquet"
    parquet_dir.mkdir(parents=True)
    rows = [
        _spec("Кабель ВВГнг 3х1,5", "м", 744.93, section="ЭОМ"),
        _spec("Светильник LED", "шт", 280.0, section="ЭОМ"),
    ]
    save_parquet(rows, str(parquet_dir / "spec.parquet"))
    res = generate_spec_bor("ds", storage_root=tmp_path, output_dir=tmp_path / "out")  # decompose=default
    assert res["mode"] == "decompose"
    assert res["bor_lines"] > 2                # позиции декомпозированы в набор работ
    assert Path(res["xlsx_path"]).exists()     # xlsx с графами ГОСТ 21.111


def test_uses_no_llm():
    import inspect

    import proxy.services.spec_to_bor_service as svc

    src = inspect.getsource(svc)
    for marker in ("import httpx", "import openai", "/api/chat", "completions"):
        assert marker not in src


# ── v2: декомпозиция (методика ГОСТ 21.111) ──

from proxy.services.spec_to_bor_service import (  # noqa: E402
    _decompose,
    spec_rows_to_work_lines_v2,
    work_lines_to_xlsx,
)


def test_decompose_cable_into_works():
    works, note = _decompose("кабель ВВГнг 3х2,5")
    assert "Разметка трассы" in works and any("Прокладка" in w for w in works)
    assert "конц" in note  # доп. работы по числу концов — в примечании


def test_decompose_device_install_connect():
    works, _ = _decompose("щит распределительный ЩР-1")
    assert any("Установка" in w for w in works) and "Подключение" in works


def test_v2_one_position_many_works_qty_inherited():
    rows = [_spec("кабель ВВГнг 3х2,5", unit="м", qty=1003.0, section="ЭОМ", mark="Э-1")]
    lines = spec_rows_to_work_lines_v2(rows)
    # одна позиция → несколько работ, у каждой объём = кол-ву позиции
    assert len(lines) >= 2
    for l in lines:
        assert l.unit == "м" and l.qty == 1003.0
        assert l.chertezh == "Э-1" and l.section == "ЭОМ"
        assert "поз" in l.note or "спецификац" in l.note


def test_v2_groups_and_sums_same_work():
    rows = [
        _spec("кабель А", unit="м", qty=100.0, section="ЭОМ"),
        _spec("кабель Б", unit="м", qty=50.0, section="ЭОМ"),
    ]
    lines = spec_rows_to_work_lines_v2(rows)
    razm = [l for l in lines if l.work.startswith("Разметка трассы")]
    assert len(razm) == 1 and razm[0].qty == 150.0  # свод одинаковой работы


def test_v2_xlsx_has_gost_columns(tmp_path):
    rows = [_spec("извещатель ИП-212", unit="шт", qty=85.0, section="АУПС")]
    lines = spec_rows_to_work_lines_v2(rows)
    out = tmp_path / "vor.xlsx"
    n = work_lines_to_xlsx(lines, out, title="ВОР тест")
    assert out.exists() and n == len(lines)
    import openpyxl
    ws = openpyxl.load_workbook(out).active
    hdr = [ws.cell(row=2, column=c).value for c in range(1, 7)]
    assert hdr == ["№", "Наименование работ", "Ед. изм.", "Кол-во", "Ссылка на чертёж", "Примечание"]
