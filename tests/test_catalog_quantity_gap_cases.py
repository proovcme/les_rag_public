# -*- coding: utf-8
"""Gap regressions for header-bound quantity (established-but-unusable value and
multi-table governing header). Content/structure only — no sheet name, row
number or known cipher is assumed."""
from __future__ import annotations

from proxy.services.attachment_source_catalog_service import (
    CatalogCell,
    _cell_number,
    compare_model_row_to_catalog,
    load_tabular_source_catalog,
    quantity_candidates,
)


def _write(tmp_path, rows):
    from openpyxl import Workbook

    path = tmp_path / "ВОР gap.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Лист1"
    for r in rows:
        ws.append(r)
    wb.save(path)
    return path


def test_empty_quantity_column_is_unconfirmed_not_guessed(tmp_path):
    path = _write(
        tmp_path,
        [["№", "Наименование", "Ед.изм.", "Кол-во"],
         [7, "Работа без количества", "шт", None]],
    )
    cat = load_tabular_source_catalog(path)
    row = cat.lookup("Лист1!R2")
    assert row.quantity_column_known is True
    assert row.header_quantity is None
    # Never fall back to the neighbour sequence number 7.
    assert quantity_candidates(row) == ()
    errors = compare_model_row_to_catalog(
        {"source_row": "Лист1!R2", "quantity": 7, "unit": "шт"}, cat
    )
    assert any("source_quantity_unconfirmed" in e for e in errors)


def test_formula_without_computed_value_is_unconfirmed(tmp_path):
    path = _write(
        tmp_path,
        [["№", "Наименование", "Ед.изм.", "Кол-во"],
         [3, "Кабель силовой", "м", "=10+20"]],
    )
    cat = load_tabular_source_catalog(path)
    row = cat.lookup("Лист1!R2")
    assert row.quantity_column_known is True
    assert row.header_quantity is None
    assert quantity_candidates(row) == ()


def test_cell_number_prefers_cached_formula_result():
    resolved = CatalogCell("D2", 4, "=10+20", "=10+20", "f", "General",
                           formula="=10+20", cached_formula_value=30)
    unresolved = CatalogCell("D3", 4, "=10+20", "=10+20", "f", "General",
                             formula="=10+20", cached_formula_value=None)
    assert _cell_number(resolved) == 30.0
    assert _cell_number(unresolved) is None


def test_two_tables_with_reordered_columns_bind_governing_header(tmp_path):
    path = _write(
        tmp_path,
        [["№", "Наименование", "Ед.изм.", "Кол-во"],     # table A header (Кол-во = col4)
         [1, "Работа А", "м", 10],
         [None, None, None, None],
         ["Кол-во", "Наименование", "Ед.изм.", "№"],      # table B header (Кол-во = col1)
         [50, "Работа Б", "м", 2]],
    )
    cat = load_tabular_source_catalog(path)
    a = cat.lookup("Лист1!R2")
    b = cat.lookup("Лист1!R5")
    assert a.header_quantity == 10.0 and quantity_candidates(a) == (10.0,)
    assert b.header_quantity == 50.0 and quantity_candidates(b) == (50.0,)
    assert "[Кол-во]" in b.line and "50 [Кол-во]" in b.line
