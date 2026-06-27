"""ФГИС ЦС ценовая база: парсинг «Сплит-формы» → Parquet → exact-match lookup.

Фикстура строит мини-«Сплит-форму» (строки-примечания, шапка, нумерация, данные),
повторяя структуру реальных файлов СПб. Проверяем оба механизма текущей цены
(база×индекс и прямая кол.8), снятие префикса базы и поиск по наименованию.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from proxy.services.fgis_price_service import (
    PriceBook,
    build_price_parquet,
    normalize_code,
    parse_split_form,
)

HEADERS = [
    "Код ресурса, услуги",
    "Наименование строительного ресурса, услуги",
    "Единица измерения",
    "Отпускная цена в уровне цен по состоянию на 01.01.2022",
    "Сметная цена в уровне цен по состоянию на 01.01.2022",
    "Номер группы однородных строительных ресурсов",
    "Наименование группы однородных строительных ресурсов",
    "Сметная цена в текущем уровне цен, руб.",
    "Индекс изменения сметной стоимости к группе",
]

# code, name, unit, release, base, group_no, group_name, current(col8), index
DATA = [
    ("91.05.01-017", "Краны башенные, грузоподъемность 8 т", "маш.-ч", 600.0, 622.62, "100", "Краны", "-", 1.39),
    ("91.05.05-015", "Краны на автомобильном ходу, 16 т", "маш.-ч", 1100.0, 1167.7, "100", "Краны", 1663.18, "-"),
    ("01.7.15.06-0111", "Гвозди строительные", "т", 68000.0, 70296.2, "511", "Метизы", "-", 1.3),
]


def _make_split_form(path: Path) -> None:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Сплит-форма индексов и сметных цен"])
    ws.append(["Наименование субъекта Российской Федерации", "Санкт-Петербург"])
    ws.append(["Наименование зоны субъекта Российской Федерации", "город Санкт-Петербург"])
    # абзац-примечание со словом «субъект» — НЕ должен попасть в регион
    ws.append(["1. Индексы по группам однородных строительных ресурсов субъекта…"])
    ws.append(HEADERS)
    ws.append([str(i) for i in range(1, 10)])  # строка нумерации колонок
    for rec in DATA:
        ws.append(list(rec))
    wb.save(path)


@pytest.fixture()
def split_form(tmp_path: Path) -> Path:
    path = tmp_path / "split.xlsx"
    _make_split_form(path)
    return path


def test_normalize_code_strips_base_prefix():
    assert normalize_code("ФСБЦ-11.1.03.01-0001") == "11.1.03.01-0001"
    assert normalize_code(" 91.05.01-017 ") == "91.05.01-017"
    assert normalize_code(None) == ""


def test_parse_split_form_finds_header_and_meta(split_form: Path):
    parsed = parse_split_form(split_form)
    assert parsed["meta"].get("subject") == "Санкт-Петербург"
    assert len(parsed["rows"]) == 3
    codes = {r["code"] for r in parsed["rows"]}
    assert "91.05.01-017" in codes


def test_current_price_base_times_index(split_form: Path, tmp_path: Path):
    out = tmp_path / "pb.parquet"
    summary = build_price_parquet(split_form, out, quarter="2 кв. 2025")
    assert summary["rows"] == 3
    assert summary["region"] == "Санкт-Петербург"

    pb = PriceBook.from_parquet(out)
    assert len(pb) == 3
    # база×индекс
    assert pb.lookup("91.05.01-017")["price_current_eff"] == 865.44
    assert pb.price("01.7.15.06-0111", method="index") == 91385.06
    assert pb.price("01.7.15.06-0111", method="base") == 70296.2


def test_current_price_direct_col8(split_form: Path, tmp_path: Path):
    out = tmp_path / "pb.parquet"
    build_price_parquet(split_form, out)
    pb = PriceBook.from_parquet(out)
    # прямая текущая цена из кол.8 (индекс «-»)
    assert pb.lookup("91.05.05-015")["price_current_eff"] == 1663.18


def test_lookup_prefix_and_miss(split_form: Path, tmp_path: Path):
    out = tmp_path / "pb.parquet"
    build_price_parquet(split_form, out)
    pb = PriceBook.from_parquet(out)
    # префикс базы снимается → тот же код
    assert pb.lookup("ФСБЦ-91.05.01-017")["code"] == "91.05.01-017"
    assert pb.lookup("99.99.99-999") is None


def test_search_by_name(split_form: Path, tmp_path: Path):
    out = tmp_path / "pb.parquet"
    build_price_parquet(split_form, out)
    pb = PriceBook.from_parquet(out)
    hits = pb.search("гвозди", limit=5)
    assert len(hits) == 1
    assert hits[0]["code"] == "01.7.15.06-0111"
