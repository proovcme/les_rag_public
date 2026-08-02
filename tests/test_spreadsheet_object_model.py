from pathlib import Path

from openpyxl import Workbook

from proxy.services.spreadsheet_object_model import (
    SPREADSHEET_OBJECT_SCHEMA,
    formula_dependency_stub,
    workbook_overview,
)


def test_workbook_overview_returns_typed_sheets():
    root = Path(__file__).resolve().parents[1] / "outputs" / "_pytest_spreadsheet"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "book.xlsx"
    wb = Workbook()
    sheet = wb.active
    sheet.title = "Объёмы"
    sheet["A1"] = "Позиция"
    sheet["B1"] = "Кол-во"
    sheet["A2"] = "Монтаж"
    sheet["B2"] = "=C2+D2"
    sheet["C2"] = 1
    sheet["D2"] = 3
    wb.create_sheet("Ставки")
    wb.save(path)

    overview = workbook_overview(path, sample_rows=2)

    assert overview["schema"] == SPREADSHEET_OBJECT_SCHEMA
    assert overview["kind"] == "workbook_overview"
    assert overview["sheet_count"] == 2
    names = [sheet["name"] for sheet in overview["sheets"]]
    assert names == ["Объёмы", "Ставки"]
    sample = overview["sheets"][0]["sample_rows"]
    assert sample[1][1]["address"] == "B2"
    assert sample[1][1]["raw_value"] == "=C2+D2"
    assert overview["provenance"]["parser"] == "openpyxl.read_only"
    path.unlink(missing_ok=True)


def test_formula_dependency_stub_extracts_refs():
    card = formula_dependency_stub("=SUM(Ставки!B7,J38:J40)", sheet="Итого")
    assert card["schema"] == SPREADSHEET_OBJECT_SCHEMA
    assert "Ставки!B7" in card["depends_on"]
    assert "Итого!J38:J40" in card["depends_on"]
    assert card["evaluated"] is False
