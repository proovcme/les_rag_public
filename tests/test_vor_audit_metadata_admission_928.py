"""A producer marker cannot certify incomplete or malformed audit fragments."""
from __future__ import annotations

import json

import openpyxl
import pytest

from proxy.services import attachment_source_catalog_service as service


def _source(tmp_path, fragments):
    source = tmp_path / "ВОР 'Ω'.xlsx"
    workbook = openpyxl.Workbook()
    main = workbook.active
    main.title = "ВОР"
    main.append(["Исходная форма"])
    main.append([])
    main.append(["Наименование", "Ед. изм.", "Количество"])
    main.append(["Авторская работа", "м", 12])
    audit = workbook.create_sheet("Решения модели")
    audit.append([service.VOR_MODEL_AUDIT_SCHEMA])
    audit.append(["Дословные авторские поля"])
    audit.append(list(service.VOR_MODEL_AUDIT_HEADERS))
    for part, literal in fragments:
        audit.append(["ВОР!R4", part, "JSON: " + literal])
    workbook.save(source)
    workbook.close()
    return source


@pytest.mark.parametrize("fragments", [
    [("Фрагмент 1/999", '{"operation_id":"op-literal"}')],
    [("Фрагмент 1/1", "not-json")],
    [("Фрагмент 1/2", "{"), ("Фрагмент 2/3", "}")],
    [("Фрагмент 1/2", "{"), ("Фрагмент 1/2", "}")],
    [("Фрагмент 2/2", "}"), ("Фрагмент 1/2", "{")],
    [("Фрагмент 1/3", "{"), ("Фрагмент 3/3", "}")],
    [("Фрагмент 1/1", "[]")],
    [("Фрагмент 1/1", '{"operation_id":"first","operation_id":"second"}')],
])
def test_exact_marker_does_not_certify_missing_parts_or_invalid_json(tmp_path, fragments):
    catalog = service.load_tabular_source_catalog(_source(tmp_path, fragments))

    assert catalog.lookup("Решения модели!R4").classification_reason != "application_authored_decision_audit"
    assert not catalog.extraction_complete
    assert "vor_model_audit_invalid:Решения модели" in catalog.extraction_warnings
    literals = [cell.raw_value for row in catalog.rows if row.sheet == "Решения модели"
                for cell in row.cells if cell.column == 3]
    assert literals[-1] == "JSON: " + fragments[-1][1]
    assert any(fragments[-1][1] in line for line in service.catalog_sheet_pack_lines(catalog, "ВОР"))


def test_complete_long_fragments_are_reference_context_without_changing_literal_fields(tmp_path):
    decision = {"operation_id": "op-literal", "covered_by_work_id": "op-parent",
                "quantity_formula": "6 * 2", "literal": "a  b\nΩ" * 20000}
    serialized = json.dumps(decision, ensure_ascii=False, separators=(",", ":"))
    pieces = [serialized[index:index + 32000] for index in range(0, len(serialized), 32000)]
    catalog = service.load_tabular_source_catalog(_source(
        tmp_path, [(f"Фрагмент {part}/{len(pieces)}", value) for part, value in enumerate(pieces, 1)],
    ))

    assert catalog.extraction_complete and catalog.extraction_warnings == ()
    assert catalog.work_locators() == ["ВОР!R4"]
    audit_rows = [row for row in catalog.rows if row.sheet == "Решения модели" and row.excel_row >= 4]
    assert all(row.classification_reason == "application_authored_decision_audit" for row in audit_rows)
    assert json.loads("".join(row.values[2][len("JSON: "):] for row in audit_rows)) == decision
    assert any("quantity_formula" in line and "covered_by_work_id" in line
               for line in service.catalog_sheet_pack_lines(catalog, "ВОР", ["ВОР!R4"]))
