"""One invalid authored operation cannot reject a valid sibling source operation."""
from __future__ import annotations

import copy
from dataclasses import replace

import openpyxl
import pytest

from proxy.services import chat_evidence_application_service as app
from proxy.services.attachment_source_catalog_service import (
    compare_model_row_to_catalog,
    load_tabular_source_catalog,
)


@pytest.fixture
def catalog(tmp_path):
    path = tmp_path / "Shared source with separate operations.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active.title = "S"
    workbook.active.append(["Наименование", "Ед. изм.", "Количество"])
    workbook.active.append(["Authored source scope", "м2", 37.5])
    workbook.save(path)
    workbook.close()
    return load_tabular_source_catalog(path)


def _rows():
    return [
        {"source_row": "S!R2", "row_role": "work", "work_row": "S!R2",
         "title": "Literal base operation", "unit": "100 м2", "quantity": 0.375,
         "norm_code": "", "evidence_refs": [], "open_gap": "Literal model gap A",
         "coverage": "Literal model explanation A"},
        {"source_row": "S!R2", "row_role": "work", "work_row": "S!R2",
         "title": "Literal additional operation", "unit": "100 м2", "quantity": 1.5,
         "norm_code": "", "evidence_refs": [], "open_gap": "Literal model gap B",
         "coverage": "Literal model explanation B"},
    ]


def _validate(rows, catalog, **kwargs):
    return app.validate_model_rag_result_structure(
        rows, [], expected_source_rows=1, source_catalog=catalog,
        artifact_kind="lsr", **kwargs,
    )


@pytest.mark.parametrize("reverse", [False, True])
def test_shared_source_keeps_equivalent_base_and_saves_only_invalid_quantity(catalog, reverse):
    base, additional = _rows()
    rows = [additional, base] if reverse else [base, additional]
    before = copy.deepcopy(rows)
    assert compare_model_row_to_catalog(base, catalog) == []
    assert compare_model_row_to_catalog(additional, catalog) == ["source_quantity_mismatch:S!R2"]
    errors = _validate(rows, catalog)
    assert "source_quantity_mismatch:S!R2" in errors

    kept = app.sheet_pass_keep_rows(
        rows, sheet="S", catalog=catalog, errors=errors, artifact_kind="lsr",
    )
    assert kept == [base], "a different operation's quantity error must not reject this base"
    proposals = app.sheet_pass_rejected_row_proposals(
        rows, kept_rows=kept, sheet="S", catalog=catalog, errors=errors,
        packet_locators=["S!R2"],
    )
    assert len(proposals) == 1
    assert proposals[0]["decision"] == additional
    assert proposals[0]["errors"] == ["source_quantity_mismatch:S!R2"]
    assert rows == before
    assert kept[0]["quantity"] == 0.375 and kept[0]["unit"] == "100 м2"
    assert kept[0]["norm_code"] == "" and kept[0]["open_gap"] == "Literal model gap A"


def test_two_individually_invalid_quantities_both_remain_unapplied(catalog):
    rows = _rows()
    rows[0]["quantity"] = 0.5
    before = copy.deepcopy(rows)
    errors = _validate(rows, catalog)
    kept = app.sheet_pass_keep_rows(
        rows, sheet="S", catalog=catalog, errors=errors, artifact_kind="lsr",
    )
    assert kept == []
    proposals = app.sheet_pass_rejected_row_proposals(
        rows, kept_rows=kept, sheet="S", catalog=catalog, errors=errors,
        packet_locators=["S!R2"],
    )
    assert [proposal["decision"] for proposal in proposals] == before
    assert all(proposal["errors"] == ["source_quantity_mismatch:S!R2"] for proposal in proposals)
    assert rows == before


@pytest.mark.parametrize("guard", ["unknown_identity", "moved_identity", "duplicate", "tail", "foreign_source"])
def test_local_quantity_scope_does_not_relax_identity_duplicate_or_tail_guards(catalog, guard):
    base, additional = _rows()
    rows = [base, additional]
    drop = ""
    prior = []
    if guard == "unknown_identity":
        base["operation_id"] = "invented"
    elif guard == "moved_identity":
        base["operation_id"] = "known"
        prior = [{"operation_id": "known", "source_row": "S!R99", "row_role": "work"}]
    elif guard == "duplicate":
        rows.append(copy.deepcopy(base))
    elif guard == "tail":
        drop = "S!R2"
    else:
        base["source_row"] = "foreign!R2"
    before = copy.deepcopy(rows)
    errors = _validate(rows, catalog, existing_operation_rows=prior)
    kept = app.sheet_pass_keep_rows(
        rows, sheet="S", catalog=catalog, errors=errors,
        artifact_kind="lsr", drop_locator=drop,
    )
    assert kept == []
    assert rows == before
    if guard in {"unknown_identity", "moved_identity"}:
        proposals = app.sheet_pass_rejected_row_proposals(
            rows, kept_rows=kept, sheet="S", catalog=catalog, errors=errors,
            packet_locators=["S!R2"],
        )
        base_proposal = next(item for item in proposals if item["decision"] == base)
        assert "source_quantity_mismatch:S!R2" not in base_proposal["errors"], (
            "an independently blocked valid quantity must not inherit the sibling's error"
        )
        assert any("operation_id" in error or "operation_source_mismatch" in error
                   for error in base_proposal["errors"])


def test_other_source_rows_and_non_work_admission_are_unchanged(catalog):
    base, additional = _rows()
    material = {**base, "row_role": "material", "title": "Literal supply", "quantity": 1.5}
    errors = _validate([base, additional, material], catalog)
    kept = app.sheet_pass_keep_rows(
        [base, additional, material], sheet="S", catalog=catalog,
        errors=errors, artifact_kind="lsr",
    )
    assert kept == [base, material]


@pytest.mark.parametrize("unknown", [
    "source_quantity", "source_unit", "model_unit", "model_quantity",
    "string_quantity", "boolean_quantity", "fallback_quantity",
])
def test_explicit_quantity_error_stays_closed_without_proven_physical_equivalence(catalog, unknown):
    row = _rows()[0]
    source = catalog.lookup("S!R2")
    if unknown in {"source_quantity", "fallback_quantity"}:
        source = replace(source, header_quantity=None,
                         quantity_column_known=unknown == "source_quantity",
                         numbers=() if unknown == "source_quantity" else (37.5,))
    elif unknown == "source_unit":
        source = replace(source, column_headers=tuple(
            (column, label) for column, label in source.column_headers if column != 2))
    elif unknown == "model_unit":
        row.pop("unit")
        row["quantity"] = 37.5
    elif unknown == "model_quantity":
        row["quantity"] = None
    elif unknown == "string_quantity":
        row["quantity"] = "0.375"
    else:
        row["quantity"] = True
    catalog = replace(catalog, rows=tuple(source if item.locator == source.locator else item
                                         for item in catalog.rows))
    before = copy.deepcopy(row)
    error = "source_quantity_mismatch:S!R2"
    kept = app.sheet_pass_keep_rows(
        [row], sheet="S", catalog=catalog, errors=[error], artifact_kind="lsr",
    )
    assert kept == [], "absence of a row-local mismatch is not proof of equivalence"
    proposals = app.sheet_pass_rejected_row_proposals(
        [row], kept_rows=kept, sheet="S", catalog=catalog, errors=[error],
        packet_locators=["S!R2"],
    )
    assert len(proposals) == 1 and proposals[0]["errors"] == [error]
    assert proposals[0]["decision"] == before and row == before


def test_proven_header_zero_is_not_mistaken_for_absent_source_quantity(catalog):
    zero, invalid = _rows()
    zero.update(quantity=0, unit="м2")
    invalid.update(quantity=1, unit="м2")
    source = replace(catalog.lookup("S!R2"), header_quantity=0, numbers=(0,))
    catalog = replace(catalog, rows=tuple(source if item.locator == source.locator else item
                                         for item in catalog.rows))
    errors = _validate([zero, invalid], catalog)
    kept = app.sheet_pass_keep_rows(
        [zero, invalid], sheet="S", catalog=catalog, errors=errors, artifact_kind="lsr",
    )
    assert kept == [zero] and kept[0]["quantity"] == 0
