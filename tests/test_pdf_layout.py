"""Тесты layout-aware извлечения PDF (Ц11, ADR-5).

Проверяем:
  • таблица из find_tables → markdown PIPE-таблица (`| .. | .. |`) — стыковка с Ц9;
  • двухколоночный лист читается в порядке колонок (левая раньше правой);
  • флаг LES_LAYOUT_PDF включает/выключает путь;
  • встройка в converter не ломает штатный парс (фолбэк) при сбое.
"""
import os
from pathlib import Path

import pytest

fitz = pytest.importorskip("fitz")

from backend import pdf_layout
from backend.pdf_layout import extract_layout_markdown, layout_pdf_enabled

REAL_PDF = Path(__file__).resolve().parents[1] / "data" / "gesn_pdf" / "gesn_12-01-034.pdf"


def _make_table_pdf(path: Path) -> None:
    """Синтетический PDF с расчерченной таблицей 3x3 (линии → find_tables)."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    cells = [
        ["Code", "Name", "Qty"],
        ["12-01-001", "Roof works", "100"],
        ["12-01-002", "Cover guard", "460"],
    ]
    x0, y0, cw, rh = 40, 40, 110, 30
    # Текст ячеек.
    for ri, row in enumerate(cells):
        for ci, val in enumerate(row):
            page.insert_text((x0 + ci * cw + 4, y0 + ri * rh + 18), val, fontsize=10)
    # Линии сетки (нужны pymupdf find_tables для распознавания таблицы).
    n_rows, n_cols = len(cells), len(cells[0])
    for ci in range(n_cols + 1):
        x = x0 + ci * cw
        page.draw_line((x, y0), (x, y0 + n_rows * rh))
    for ri in range(n_rows + 1):
        y = y0 + ri * rh
        page.draw_line((x0, y), (x0 + n_cols * cw, y))
    doc.save(str(path))
    doc.close()


def _make_two_column_pdf(path: Path) -> None:
    """Двухколоночный лист: левая колонка (LEFTBLOCK), правая (RIGHTBLOCK)."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=400)
    page.insert_text((40, 60), "LEFTBLOCK line one", fontsize=11)
    page.insert_text((40, 90), "LEFTBLOCK line two", fontsize=11)
    page.insert_text((360, 60), "RIGHTBLOCK line one", fontsize=11)
    page.insert_text((360, 90), "RIGHTBLOCK line two", fontsize=11)
    doc.save(str(path))
    doc.close()


def test_table_becomes_markdown_pipe(tmp_path):
    pdf = tmp_path / "table.pdf"
    _make_table_pdf(pdf)
    md = extract_layout_markdown(pdf)
    # Pipe-таблица: разделители столбцов и separator-строка.
    assert "|" in md
    assert md.count("|") >= 4, f"мало pipe-разделителей: {md!r}"
    assert "| --- |" in md or "---" in md
    # Содержательные ячейки на месте.
    assert "12-01-001" in md
    assert "Roof works" in md


def test_two_column_reading_order(tmp_path):
    pdf = tmp_path / "cols.pdf"
    _make_two_column_pdf(pdf)
    md = extract_layout_markdown(pdf)
    assert "LEFTBLOCK" in md and "RIGHTBLOCK" in md
    # Левая колонка читается раньше правой.
    assert md.index("LEFTBLOCK") < md.index("RIGHTBLOCK")


def test_flag_toggle(monkeypatch):
    monkeypatch.setenv("LES_LAYOUT_PDF", "off")
    assert layout_pdf_enabled() is False
    monkeypatch.setenv("LES_LAYOUT_PDF", "on")
    assert layout_pdf_enabled() is True
    monkeypatch.setenv("LES_LAYOUT_PDF", "1")
    assert layout_pdf_enabled() is True


def test_empty_or_garbage_table_rejected():
    """Слишком маленькая/пустая таблица не превращается в pipe (вернёт None)."""
    class _FakeTable:
        bbox = (0, 0, 10, 10)

        def __init__(self, rows):
            self._rows = rows

        def extract(self):
            return self._rows

    assert pdf_layout._table_to_markdown(_FakeTable([])) is None
    assert pdf_layout._table_to_markdown(_FakeTable([["a"]])) is None  # 1 строка
    # Одна колонка после чистки пустых → отклонить.
    assert pdf_layout._table_to_markdown(_FakeTable([["a", ""], ["b", ""]])) is None


@pytest.mark.parametrize("supplier", ["", "Производитель"])
def test_sparse_specification_keeps_header_quantity_column(tmp_path, monkeypatch, supplier):
    """Blank optional cells must not move a quantity under another header."""
    from proxy.services.attachment_source_catalog_service import (
        compare_model_row_to_catalog,
        load_tabular_source_catalog,
        quantity_candidates,
    )

    class Table:
        def extract(self):
            return [
                ["Поз.", "Наименование", "Тип", "Код", "Поставщик", "Ед. изм.", "Кол.", "Масса, кг", "Примечание"],
                *[[f"Раздел {i}", "", "", "", "", "", "", "", ""] for i in range(1, 7)],
                ["1.1", "Изделие А", "Тип А", "", supplier, "шт.", "25", "0.35", ""],
                ["1.2", "Изделие Б", "", "", "", "шт.", "14", "", ""],
            ]

    markdown = pdf_layout._table_to_markdown(Table())
    source = tmp_path / "Разреженная спецификация.pdf"
    source.write_bytes(b"%PDF-fixture")
    monkeypatch.setattr("backend.converter.convert_to_markdown", lambda _path: markdown)
    catalog = load_tabular_source_catalog(source)
    assert quantity_candidates(catalog.lookup("PDF!R8")) == (25.0,)
    assert quantity_candidates(catalog.lookup("PDF!R9")) == (14.0,)
    assert compare_model_row_to_catalog(
        {"source_row": "PDF!R8", "quantity": 25, "unit": "шт."}, catalog
    ) == []
    assert "source_quantity_mismatch:PDF!R8" in compare_model_row_to_catalog(
        {"source_row": "PDF!R8", "quantity": 0.35, "unit": "шт."}, catalog
    )


def test_sparse_pdf_grid_keeps_empty_cells_in_place(tmp_path):
    """Exercise the actual PDF table reader, including different empty columns."""
    from proxy.services.attachment_source_catalog_service import _markdown_table_rows

    doc = fitz.open()
    page = doc.new_page(width=640, height=330)
    grid = [
        ["Item", "Name", "Type", "Code", "Supplier", "Unit", "Qty", "Mass", "Note"],
        ["Section", "", "", "", "", "", "", "", ""],
        ["Section2", "", "", "", "", "", "", "", ""],
        ["Section3", "", "", "", "", "", "", "", ""],
        ["1.1", "Product A", "Type A", "", "Vendor", "pcs", "25", "0.35", ""],
        ["1.2", "Product B", "", "", "", "pcs", "14", "", ""],
    ]
    x0, y0, cw, rh = 30, 40, 65, 35
    for ri, row in enumerate(grid):
        for ci, value in enumerate(row):
            if value:
                page.insert_text((x0 + ci * cw + 3, y0 + ri * rh + 18), value, fontsize=8)
    for ci in range(10):
        page.draw_line((x0 + ci * cw, y0), (x0 + ci * cw, y0 + len(grid) * rh))
    for ri in range(len(grid) + 1):
        page.draw_line((x0, y0 + ri * rh), (x0 + 9 * cw, y0 + ri * rh))
    source = tmp_path / "sparse grid.pdf"
    doc.save(str(source))
    doc.close()
    rows = _markdown_table_rows(extract_layout_markdown(source))
    first = next(row for row in rows if row[0] == "1.1")
    second = next(row for row in rows if row[0] == "1.2")
    assert first[5:8] == ("pcs", "25", "0.35")
    assert second[5:8] == ("pcs", "14", "")


def test_converter_fallback_when_layout_raises(tmp_path, monkeypatch):
    """Если layout-парсер падает, converter._parse_pdf откатывается на штатный путь."""
    from backend import converter

    pdf = tmp_path / "plain.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Plain text PDF without any tables here. " * 8, fontsize=11)
    doc.save(str(pdf))
    doc.close()

    monkeypatch.setenv("LES_LAYOUT_PDF", "on")

    def _boom(*a, **k):
        raise RuntimeError("layout boom")

    monkeypatch.setattr("backend.pdf_layout.extract_layout_markdown", _boom)

    out = converter.convert_to_markdown(pdf)
    assert out and "Plain text PDF" in out


@pytest.mark.skipif(not REAL_PDF.exists(), reason="реальный GESN PDF недоступен")
def test_real_gesn_pdf_emits_pipe_tables():
    # Весь документ (детерминированно): per-page срез нестабилен из-за state-утечки fitz
    # при запуске после fallback-теста; прод-путь конвертера всегда обрабатывает весь PDF.
    md = extract_layout_markdown(REAL_PDF)
    assert md.strip()
    # Реальные ресурсные таблицы ГЭСН → плотные pipe-таблицы (стыковка с Ц9).
    assert md.count("|") >= 100
    # Коды ресурсов/норм в табличном виде.
    assert "12-01-002" in md
