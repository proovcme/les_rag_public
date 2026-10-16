"""Known XLSX metadata is read literally; unsupported parts remain incomplete."""

import json
import openpyxl
from openpyxl.comments import Comment
import pytest

from proxy.services.attachment_source_catalog_service import (
    compare_model_row_to_catalog,
    load_tabular_source_catalog,
)
from proxy.services.model_source_frame_service import build_model_source_frame


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


def _metadata(catalog):
    return [row for row in catalog.rows if row.classification_reason == "xlsx_literal_metadata"]


@pytest.mark.parametrize("coordinate", ["A2", "D8"])
def test_comment_on_populated_or_empty_cell_is_literal_source_context(tmp_path, coordinate):
    workbook, sheet = _workbook()
    sheet[coordinate].comment = Comment("Условия: два слоя, толщина 30 мм", "Source")
    catalog = _catalog(workbook, tmp_path)
    assert catalog.extraction_complete is True and catalog.extraction_warnings == ()
    assert [row.locator for row in catalog.rows if row.excel_row] == ["Исходный лист!R1", "Исходный лист!R2"]
    assert catalog.work_locators() == ["Исходный лист!R2"]
    assert catalog.lookup("Исходный лист!R2").header_quantity == 12
    metadata = _metadata(catalog)
    assert len(metadata) == 1 and metadata[0].row_classification == "note"
    body = json.loads(metadata[0].values[0])
    assert body["text"] == "Условия: два слоя, толщина 30 мм"
    assert body["author"] == "Source" and body["coordinate"] == coordinate
    assert catalog.lookup(metadata[0].locator) == metadata[0]
    assert metadata[0].locator in build_model_source_frame(catalog, ["Исходный лист!R2"]).reference_locators
    assert compare_model_row_to_catalog({"source_row": "Исходный лист!R2", "unit": "м2", "quantity": 12}, catalog) == []


def test_hidden_sheet_comments_are_read_once_without_repeating_text(tmp_path):
    workbook, sheet = _workbook()
    hidden = workbook.create_sheet("Скрытые условия")
    hidden.sheet_state = "hidden"
    hidden["A1"].comment = Comment("Скрытые исходные условия", "Source")
    hidden["B2"].comment = Comment("Ещё один комментарий", "Source")
    catalog = _catalog(workbook, tmp_path)
    assert catalog.extraction_complete is True and catalog.extraction_warnings == ()
    assert catalog.work_locators() == ["Исходный лист!R2"]
    metadata = _metadata(catalog)
    assert len(metadata) == 2 and all(row.hidden_sheet for row in metadata)
    assert {(json.loads(row.values[0])["coordinate"], json.loads(row.values[0])["text"]) for row in metadata} == {
        ("A1", "Скрытые исходные условия"), ("B2", "Ещё один комментарий")}
    assert all(catalog.lookup(row.locator) == row for row in metadata)
    assert all(row.locator not in catalog.work_locators() for row in metadata)


@pytest.mark.parametrize("part_name", ["oddHeader", "evenHeader", "firstHeader", "oddFooter", "evenFooter", "firstFooter"])
@pytest.mark.parametrize("position", ["left", "center", "right"])
def test_nonempty_printed_header_or_footer_is_full_literal_reference(tmp_path, part_name, position):
    workbook, sheet = _workbook()
    getattr(getattr(sheet, part_name), position).text = "Условие исходного документа"
    catalog = _catalog(workbook, tmp_path)
    assert catalog.extraction_complete is True and catalog.extraction_warnings == ()
    assert catalog.work_locators() == ["Исходный лист!R2"]
    assert catalog.lookup("Исходный лист!R2").values == ("Исходная операция", "м2", "12")
    metadata = _metadata(catalog)
    assert len(catalog.rows) == 3 and len(metadata) == 1
    body = json.loads(metadata[0].values[0])
    assert next(part["literal"] for part in body["parts"] if part["kind"] == part_name).endswith("Условие исходного документа")
    assert body["literal_xml"] and catalog.lookup(metadata[0].locator) == metadata[0]
    assert metadata[0].locator in build_model_source_frame(catalog, ["Исходный лист!R2"]).reference_locators


def test_empty_header_formatting_and_no_comments_keep_complete_extraction(tmp_path):
    workbook, sheet = _workbook()
    sheet.oddHeader.center.font = "Arial,Bold"
    sheet.oddHeader.center.size = 12
    sheet.firstFooter.left.text = ""
    catalog = _catalog(workbook, tmp_path)
    assert catalog.extraction_complete is True
    assert catalog.extraction_warnings == ()
    assert catalog.work_locators() == ["Исходный лист!R2"]
    assert not _metadata(catalog)
