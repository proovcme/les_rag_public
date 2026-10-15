"""Regression for build 942: a truncated attachment frame must say what did not reach the model.

Measured today on the real customer file `ВОР.xlsx` (10 sheets, 463 non-empty rows) through the
product's own transport function:

    max_chars=18000 → truncated=True, frame stops inside лист «ВК» at row R10;
    sheets ПТ, СКС, СКУД, СОУЭ, ЭОМ, ОВиК are not delivered at all,
    and the only thing the frame says about it is one generic sentence.

Nothing in the frame tells the model or the operator that ~289 source rows exist and were simply
not transported. That is exactly how an absent-from-context row gets reported as absent-from-source,
and it is why the big-ВОР acceptance gate could never account for all original positions: the task
requires «Все листы/страницы и поддерживаемые типы документов учитываются» and forbids declaring a
gap before it is proven that the available source really lacks the data.

The fix is visibility only: the limit stays, the rows are not invented, no norm and no position is
chosen by code. Every sheet of the document must appear in the accounting block with delivered vs
actual non-empty row counts.
"""
from __future__ import annotations

import warnings

import openpyxl
import pytest

from proxy.routers import datasets


def _book(path, sheets: dict[str, int]) -> None:
    warnings.filterwarnings("ignore")
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        ws.append(["№ п/п", "Наименование работ", "Ед.изм.", "Кол-во"])
        for index in range(1, rows + 1):
            ws.append([f"{name}.{index}", f"Работа {name} {index}", "м", index])
    wb.save(path)
    wb.close()


@pytest.fixture()
def three_sheets(tmp_path):
    path = tmp_path / "three.xlsx"
    _book(path, {"АР": 4, "ВК": 5, "ОВиК": 6})
    return path


def test_every_sheet_is_accounted_when_the_frame_overflows(three_sheets):
    text, truncated = datasets._format_tabular_attachment_context(
        three_sheets, "three.xlsx", max_chars=320)
    assert truncated, "the tiny limit must still truncate; the fix is not to raise it"
    for sheet, total in (("АР", 5), ("ВК", 6), ("ОВиК", 7)):
        assert f"«{sheet}»" in text, f"лист {sheet} вообще не поименован в усечённом frame"
        assert f"из {total}" in text, f"для листа {sheet} не названо фактическое число строк"
    assert "не доставлялось" in text
    assert "не означает отсутствие данных в исходном файле" in text


def test_undelivered_sheets_are_named_with_zero_delivered(three_sheets):
    """The failure mode is a sheet the model never sees at all while the file has the rows."""
    text, truncated = datasets._format_tabular_attachment_context(
        three_sheets, "three.xlsx", max_chars=320)
    assert "передано 0 из" in text, "ни один лист не помечен как полностью недоставленный"


def test_the_full_frame_does_not_claim_a_gap_it_has_no_reason_to_claim(three_sheets):
    text, truncated = datasets._format_tabular_attachment_context(
        three_sheets, "three.xlsx", max_chars=200000)
    assert truncated is False
    assert "не доставлялось" not in text
    assert "АР!R1" in text and "ОВиК!R7" in text


def test_csv_rows_are_accounted_the_same_way(tmp_path):
    path = tmp_path / "rows.csv"
    path.write_text("№;Наименование;Ед;Кол-во\n"
                    + "\n".join(f"{i};Работа {i};м;{i}" for i in range(1, 21)),
                    encoding="utf-8")
    text, truncated = datasets._format_tabular_attachment_context(
        path, "rows.csv", max_chars=240)
    assert truncated
    assert "передано" in text and "из 21" in text
