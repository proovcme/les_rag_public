"""Unread XLSX metadata cannot masquerade as a complete cell-only source."""

import openpyxl
from openpyxl.comments import Comment
import pytest

from proxy.services.attachment_source_catalog_service import (
    compare_model_row_to_catalog,
    load_tabular_source_catalog,
)


def _workbook():
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Исходный лист"
    sheet.append(["Наименование", "Ед. изм.", "Количество"])
    sheet.append(["Исходная операция", "м2", 12])
    return workbook, sheet


def _catalog(workbook, tmp_path):
    source = tmp_path / "Дополнения «проект» и 'кавычка'.xlsx"
    workbook.save(source)
    workbook.close()
    before = source.read_bytes()
    catalog = load_tabular_source_catalog(source)
    assert source.read_bytes() == before
    return catalog


@pytest.mark.parametrize("coordinate", ["A2", "D8"])
def test_comment_on_populated_or_empty_cell_is_explicit_unread_scope(tmp_path, coordinate):
    workbook, sheet = _workbook()
    sheet[coordinate].comment = Comment("Условия: два слоя, толщина 30 мм", "Source")
    catalog = _catalog(workbook, tmp_path)
    assert catalog.extraction_complete is False
    assert catalog.extraction_warnings == ("xlsx_unread_content:Исходный лист:cell_comments",)
    assert [row.locator for row in catalog.rows] == ["Исходный лист!R1", "Исходный лист!R2"]
    assert catalog.work_locators() == ["Исходный лист!R2"]
    assert catalog.lookup("Исходный лист!R2").header_quantity == 12
    assert "Условия: два слоя" not in "\n".join(row.line for row in catalog.rows)
    assert compare_model_row_to_catalog({"source_row": "Исходный лист!R2", "unit": "м2", "quantity": 12},
                                        catalog) == ["source_extraction_incomplete:Исходный лист!R2"]


def test_hidden_sheet_comments_are_reported_once_without_reading_or_repeating_text(tmp_path):
    workbook, sheet = _workbook()
    hidden = workbook.create_sheet("Скрытые условия")
    hidden.sheet_state = "hidden"
    hidden["A1"].comment = Comment("Скрытые исходные условия", "Source")
    hidden["B2"].comment = Comment("Ещё один комментарий", "Source")
    catalog = _catalog(workbook, tmp_path)
    assert catalog.extraction_complete is False
    assert catalog.extraction_warnings == ("xlsx_unread_content:Скрытые условия:cell_comments",)
    assert catalog.work_locators() == ["Исходный лист!R2"]
    assert "Скрытые условия:cell_comments" in catalog.manifest_text()


@pytest.mark.parametrize("part_name", ["oddHeader", "evenHeader", "firstHeader", "oddFooter", "evenFooter", "firstFooter"])
@pytest.mark.parametrize("position", ["left", "center", "right"])
def test_nonempty_printed_header_or_footer_is_visible_unread_scope(tmp_path, part_name, position):
    workbook, sheet = _workbook()
    getattr(getattr(sheet, part_name), position).text = "Условие исходного документа"
    catalog = _catalog(workbook, tmp_path)
    assert catalog.extraction_complete is False
    assert catalog.extraction_warnings == (f"xlsx_unread_content:Исходный лист:{part_name}",)
    assert len(catalog.rows) == 2 and catalog.work_locators() == ["Исходный лист!R2"]
    assert catalog.lookup("Исходный лист!R2").values == ("Исходная операция", "м2", "12")


def test_empty_header_formatting_and_no_comments_keep_complete_extraction(tmp_path):
    workbook, sheet = _workbook()
    sheet.oddHeader.center.font = "Arial,Bold"
    sheet.oddHeader.center.size = 12
    sheet.firstFooter.left.text = ""
    catalog = _catalog(workbook, tmp_path)
    assert catalog.extraction_complete is True
    assert catalog.extraction_warnings == ()
    assert catalog.work_locators() == ["Исходный лист!R2"]
