from pathlib import Path

from proxy.services import attachment_source_catalog_service as service


def test_pdf_markdown_catalog_has_stable_locators_and_only_work_rows(monkeypatch, tmp_path):
    source = tmp_path / "ВОР монтаж БАП.pdf"
    source.write_bytes(b"%PDF-fixture")
    markdown = """Ведомость объемов работ

| № пп | Наименование | Ед. изм. | Кол-во | Примечание |
| --- | --- | --- | --- | --- |
| 1 | 2 | 3 | 4 | 5 |
| Раздел 1. Демонтажные работы |  |  |  |  |
| 1 | Защитное укрытие | м² | 116 | Пленка |
| Раздел 2. Монтажные работы |  |  |  |  |
| 1 | Монтаж блока аварийного питания | шт. | 16 |  |
"""
    monkeypatch.setattr("backend.converter.convert_to_markdown", lambda _path: markdown)

    catalog = service.load_tabular_source_catalog(source)

    assert catalog is not None
    assert catalog.sheets == (("PDF", 6),)
    assert catalog.work_locators() == ["PDF!R4", "PDF!R6"]
    assert catalog.lookup("PDF!R6").section_context.startswith("Раздел 2")
    assert catalog.lookup("PDF!R2").row_classification == "header"


def test_markdown_table_parser_ignores_separator_and_prose():
    assert service._markdown_table_rows(
        "prose\n| A | B |\n| :--- | ---: |\n| x | 2 |\n"
    ) == [("A", "B"), ("x", "2")]
