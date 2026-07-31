from pathlib import Path

import openpyxl
import pytest

from proxy.services.rim_mapping_xlsx_service import (
    MAPPING_SHEET,
    read_mapping_xlsx,
    render_mapping_xlsx,
)


def _rows():
    return [
        {
            "mapping_row_id": "map-1",
            "work_id": "vor-001",
            "norm_key": "ГЭСНм:10-06-001-01",
            "norm_code": "10-06-001-01",
            "norm_title": "Прокладка кабеля",
            "norm_unit": "100 м",
            "norm_quantity": 4,
            "candidate_rank": 1,
            "selection_status": "selected",
            "selection_kind": "direct",
            "is_analog": False,
            "card_opened": True,
            "reason": "Карточка прочитана",
            "source_refs": ["spec.xlsx#row=14"],
            "edited_by": "model",
        }
    ]


def test_mapping_xlsx_round_trip_binds_session_and_vor(tmp_path):
    target = tmp_path / "mapping.xlsx"
    render_mapping_xlsx(
        _rows(),
        target,
        session_id="session-1",
        parent_revision_id="revision-1",
        vor_revision_id="vor-revision-1",
    )
    result = read_mapping_xlsx(
        target,
        expected_session_id="session-1",
        expected_vor_revision_id="vor-revision-1",
    )
    assert result["manifest"]["parent_revision_id"] == "revision-1"
    assert result["mapping_rows"] == _rows()
    with pytest.raises(ValueError, match="another session"):
        read_mapping_xlsx(
            target,
            expected_session_id="session-2",
            expected_vor_revision_id="vor-revision-1",
        )


def test_mapping_import_rejects_formula_cells(tmp_path):
    target = tmp_path / "mapping.xlsx"
    render_mapping_xlsx(
        _rows(),
        target,
        session_id="session-1",
        parent_revision_id="revision-1",
        vor_revision_id="vor-revision-1",
    )
    workbook = openpyxl.load_workbook(target)
    workbook[MAPPING_SHEET]["M2"] = "=HYPERLINK(\"https://example.invalid\")"
    workbook.save(target)
    workbook.close()
    with pytest.raises(ValueError, match="formulas are not allowed"):
        read_mapping_xlsx(
            target,
            expected_session_id="session-1",
            expected_vor_revision_id="vor-revision-1",
        )

