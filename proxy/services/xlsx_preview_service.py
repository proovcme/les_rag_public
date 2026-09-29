# -*- coding: utf-8
"""Tabular preview of a spreadsheet's bytes, honest about uncached formulas.

Task 2026-09-29 § 4 names this as its own check: «Проверить отображение в табличном
просмотре: формулы без кеша могут выглядеть пустыми; не заменять проверку арифметики
одного файла утверждением, что Excel-пользователь видит готовые цифры».

The delivered ЛСР writes every subtotal and total as a live formula
(``=SUM(L27,L29,L30)``) and marks the workbook for full recalculation on open, but it
stores no cached value beside the formula — that is how openpyxl writes formulas.  A
reader that asks for values only (``data_only=True``, which is exactly what a preview
table does) therefore gets an empty string in every money cell, and a user can read
that screen as «the document calculated nothing».  It did not.

So the preview shows the formula text where the cache is empty and states, in the same
screen, why the cell is a formula and that the arithmetic of the revision is verified
from its own calculation data — never from this view.  Nothing is recomputed here: the
note counts the cells it replaced, and the numbers stay in the trace and in Excel.
"""
from __future__ import annotations

import csv
import io
from typing import Any

__all__ = ["UNCACHED_FORMULA_NOTE", "spreadsheet_preview"]

#: Shown under the preview table when the file keeps formulas without cached values.
#: ``{count}`` is filled with the number of cells the preview had to print as formulas.
UNCACHED_FORMULA_NOTE = (
    "Итоговые ячейки показаны формулой, а не числом ({count} шт.): файл пересчитывает "
    "их в Excel/LibreOffice при открытии, сохранённого значения в них нет. Пустая клетка "
    "здесь — не отсутствующий расчёт: арифметику проверяют по расчётным данным этой "
    "ревизии, а не по просмотр."
)

_MAX_ROWS = 200


def _csv_table(data: bytes) -> list[list[str]]:
    text = data.decode("utf-8-sig", errors="replace")
    first_line = text.split("\n", 1)[0]
    reader = csv.reader(io.StringIO(text), delimiter=";" if ";" in first_line else ",")
    return [list(row) for row in reader]


def _xlsx_tables(data: bytes) -> tuple[list[list[str]], list[list[Any]]]:
    """(values-only grid, raw grid) of the active sheet — the raw one keeps formulas."""
    import openpyxl

    def grid(*, data_only: bool) -> list[list[Any]]:
        workbook = openpyxl.load_workbook(
            io.BytesIO(data), read_only=True, data_only=data_only
        )
        try:
            sheet = workbook.active
            return [list(row) for row in sheet.iter_rows(values_only=True)]
        finally:
            workbook.close()

    cached = grid(data_only=True)
    rows = [[("" if cell is None else str(cell)) for cell in row] for row in cached]
    if not any("" in row for row in rows):
        return rows, []
    return rows, grid(data_only=False)


def spreadsheet_preview(data: bytes, kind: str) -> tuple[list[dict[str, str]], str]:
    """(rows of the first sheet, note for the user) — ``([], "")`` when unparseable.

    The note is empty for every file whose values are readable as they are, so a caller
    that shows it only when non-empty stays silent on normal spreadsheets.
    """

    try:
        if kind == "csv":
            table: list[list[str]] = _csv_table(data)
            note = ""
        else:
            table, raw_table = _xlsx_tables(data)
            note = ""
            if raw_table:
                replaced = 0
                for row_index, raw_row in enumerate(raw_table):
                    if row_index >= len(table):
                        break
                    for column_index, raw_cell in enumerate(raw_row):
                        if column_index >= len(table[row_index]):
                            break
                        if table[row_index][column_index] != "":
                            continue
                        formula = str(raw_cell or "")
                        if formula.startswith("="):
                            table[row_index][column_index] = formula
                            replaced += 1
                if replaced:
                    note = UNCACHED_FORMULA_NOTE.format(count=replaced)
        if not table:
            return [], note
        headers = [str(header or f"col{index + 1}") for index, header in enumerate(table[0])]
        rows: list[dict[str, str]] = []
        for row in table[1 : _MAX_ROWS + 1]:
            values = (list(row) + [""] * len(headers))[: len(headers)]
            rows.append({headers[index]: values[index] for index in range(len(headers))})
        return rows, note
    except Exception:
        return [], ""
