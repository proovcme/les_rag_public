"""Explicit model headings stay non-work rows, including numeric zero cells."""
from __future__ import annotations

import copy
import json

import pytest

from proxy.services import chat_evidence_application_service as service
from proxy.services.attachment_source_catalog_service import load_tabular_source_catalog


@pytest.mark.parametrize("role", ["header", "заголовок", "раздел", "subtotal"])
@pytest.mark.parametrize("quantity", [0, 7])
def test_explicit_heading_role_wins_without_rewriting_authored_cells(role, quantity):
    row = {"source_row": "Source!R1", "row_role": role, "title": "Section Ω",
           "unit": "", "quantity": quantity, "norm_code": "", "coverage": ""}
    before = copy.deepcopy(row)
    assert service.model_rag_row_kind(row) == "section_header"
    assert row == before


def test_missing_role_does_not_turn_zero_quantity_into_an_inferred_heading():
    row = {"source_row": "Source!R2", "unit": "", "quantity": 0, "norm_code": ""}
    assert service.model_rag_row_kind(row) == "work"
    assert service.model_rag_row_kind({**row, "row_role": "work"}) == "work"


def test_model_json_heading_does_not_block_other_work_on_quantity_or_evidence(tmp_path):
    from tests.test_workbook_tool_service import _source_workbook

    source = _source_workbook(tmp_path / "Source with space Ω.xlsx")
    catalog = load_tabular_source_catalog(source)
    rows = [
        {"source_row": "Sheet!R1", "row_role": "header", "work_row": "",
         "title": "Model section title", "unit": "", "quantity": 0,
         "norm_code": "", "norm_status": "", "open_gap": "", "evidence_refs": []},
        {"source_row": "Sheet!R2", "row_role": "work", "work_row": "",
         "title": "Literal work", "unit": "м", "quantity": 12.5,
         "norm_code": "MISSING", "norm_status": "MISSING",
         "open_gap": "No applicable card selected by the model", "evidence_refs": []},
    ]
    raw = json.dumps({"artifact_kind": "lsr", "rows": rows}, ensure_ascii=False)
    parsed = service.parse_model_rag_result(raw)
    assert parsed is not None and parsed[1] == rows
    errors = service.validate_model_rag_result_structure(
        parsed[1], [], expected_source_rows=1, source_catalog=catalog)
    assert not any("Sheet!R1" in error for error in errors)
    assert not service.blocking_model_rag_result_errors(
        errors, work_row_count=1, artifact_kind="lsr")
    assert parsed[1] == rows


def test_explicit_work_volume_validation_is_still_blocking(tmp_path):
    from tests.test_workbook_tool_service import _source_workbook

    catalog = load_tabular_source_catalog(_source_workbook(tmp_path / "Source.xlsx"))
    row = {"source_row": "Sheet!R2", "row_role": "work", "title": "Literal work",
           "unit": "м", "quantity": 99, "norm_code": "MISSING", "evidence_refs": []}
    errors = service.validate_model_rag_result_structure(
        [row], [], expected_source_rows=1, source_catalog=catalog)
    assert "source_quantity_mismatch:Sheet!R2" in errors
    assert "source_quantity_mismatch:Sheet!R2" in service.blocking_model_rag_result_errors(
        errors, work_row_count=1, artifact_kind="lsr")
