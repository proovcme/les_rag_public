# -*- coding: utf-8
"""Regression: a work quantity must bind to its header column, not a neighbor.

Guard against the general failure "wrong quantity from an adjacent numeric
column" and the loss of header evidence. Everything keys on structure and cell
content only - no sheet name, row number, or known cipher is assumed.
"""
from __future__ import annotations

from proxy.services import attachment_source_catalog_service as service
from proxy.services.attachment_source_catalog_service import (
    compare_model_row_to_catalog,
    load_tabular_source_catalog,
    quantity_candidates,
)


def _write(tmp_path, header, data_rows):
    from openpyxl import Workbook

    path = tmp_path / "ВОР decoy.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Лист1"
    ws.append(header)
    for row in data_rows:
        ws.append(row)
    wb.save(path)
    return path


def test_quantity_binds_to_header_column_not_adjacent_mass(tmp_path):
    path = _write(
        tmp_path,
        ["№", "Наименование", "Ед.изм.", "Кол-во", "Масса, т"],
        [[1, "Монтаж шкафа", "шт", 4, 0.35]],
    )
    catalog = load_tabular_source_catalog(path)
    row = catalog.lookup("Лист1!R2")

    # Header evidence is now present in the model-facing line.
    assert "[Кол-во]" in row.line and "[Масса, т]" in row.line
    # The candidate set is narrowed to the true quantity column, not the mass.
    assert quantity_candidates(row) == (4.0,)

    # A model that keeps the correct quantity passes; one that grabs the
    # adjacent mass column is flagged rather than silently accepted.
    assert compare_model_row_to_catalog(
        {"source_row": "Лист1!R2", "quantity": 4, "unit": "шт"}, catalog
    ) == []
    errors = compare_model_row_to_catalog(
        {"source_row": "Лист1!R2", "quantity": 0.35, "unit": "шт"}, catalog
    )
    assert any("source_quantity_mismatch" in e for e in errors)


def test_ambiguous_quantity_column_is_not_guessed(tmp_path):
    # Two quantity-looking headers -> no single quantity column -> fall back to
    # every non-sequence number instead of fabricating one binding.
    path = _write(
        tmp_path,
        ["№", "Наименование", "Кол-во", "Объем"],
        [[1, "Работа", 4, 9]],
    )
    catalog = load_tabular_source_catalog(path)
    row = catalog.lookup("Лист1!R2")
    assert row.header_quantity is None
    assert {4.0, 9.0} <= set(quantity_candidates(row))


def test_sheet_without_header_keeps_legacy_candidates(tmp_path):
    path = _write(
        tmp_path,
        ["1", "Монтаж шкафа", "шт", 4],
        [[2, "Прокладка кабеля", "м", 120]],
    )
    catalog = load_tabular_source_catalog(path)
    # Row 1 is numeric-heavy; the point is only that no crash occurs and the
    # data row still yields its quantities.
    row = catalog.lookup("Лист1!R2")
    assert 120.0 in quantity_candidates(row)
