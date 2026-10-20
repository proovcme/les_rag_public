"""Upload preview, exact catalog and source frame preserve numeric zero.

Numeric zero must remain distinct from a blank source quantity across supported
header/column layouts. This does not select a norm or professional row role.
"""
from __future__ import annotations

import hashlib

import openpyxl
import pytest


@pytest.mark.parametrize(
    "headers,zero_row,blank_row,quantity_column,zero_preview,blank_preview",
    [
        (
            ["Наименование", "Ед. изм.", "Количество"],
            ["Measured zero", "шт", 0],
            ["Unspecified work", "шт", None],
            3,
            "S!R2: Measured zero | шт | 0",
            "S!R3: Unspecified work | шт",
        ),
        (
            ["№", "Наименование", "Ед. изм.", "Кол-во", "Источник"],
            [7, "Measured zero", "шт", 0, "source"],
            [8, "Unspecified work", "шт", None, "source"],
            4,
            "S!R2: 7 | Measured zero | шт | 0 | source",
            "S!R3: 8 | Unspecified work | шт | source",
        ),
        (
            ["Количество", "Примечание", "Наименование", "Ед. изм."],
            [0, "note", "Measured zero", "шт"],
            [None, "note", "Unspecified work", "шт"],
            1,
            "S!R2: 0 | note | Measured zero | шт",
            "S!R3: note | Unspecified work | шт",
        ),
    ],
    ids=["quantity-at-end", "numbered-shifted-quantity", "quantity-at-start"],
)
def test_upload_preview_and_source_frame_distinguish_numeric_zero_from_blank(
    tmp_path, headers, zero_row, blank_row, quantity_column, zero_preview, blank_preview,
):
    from proxy.routers.datasets import _format_tabular_attachment_context
    from proxy.services.attachment_source_catalog_service import (
        load_tabular_source_catalog,
        quantity_candidates,
        source_confirms_literal_zero_quantity,
    )
    from proxy.services.model_source_frame_service import (
        build_model_source_frame,
        render_model_source_frame,
    )

    path = tmp_path / "Literal zero and blank.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "S"
    for row in (headers, zero_row, blank_row):
        sheet.append(row)
    workbook.save(path)
    workbook.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()

    catalog = load_tabular_source_catalog(path)
    assert catalog is not None and catalog.extraction_complete
    zero, blank = catalog.lookup("S!R2"), catalog.lookup("S!R3")
    assert zero.quantity_column_known and zero.header_quantity == 0
    assert blank.quantity_column_known and blank.header_quantity is None
    assert quantity_candidates(zero) == (0.0,)
    assert quantity_candidates(blank) == ()
    assert source_confirms_literal_zero_quantity(catalog, "S!R2") is True
    assert source_confirms_literal_zero_quantity(catalog, "S!R3") is False
    quantity_cell = next(cell for cell in zero.cells if cell.column == quantity_column)
    assert type(quantity_cell.raw_value) in (int, float) and quantity_cell.raw_value == 0
    assert quantity_cell.display_value == "0"

    rendered = render_model_source_frame(
        build_model_source_frame(catalog, ["S!R2", "S!R3"])
    ).to_payload()
    shown = {row["source_row"]: row for row in rendered["shown_rows"]}
    assert shown["S!R2"]["header_quantity"] == 0
    assert shown["S!R3"]["header_quantity"] is None
    assert "0" in shown["S!R2"]["values"]

    preview = _format_tabular_attachment_context(path, path.name, max_chars=10000)
    assert preview is not None
    text, truncated = preview
    assert truncated is False
    # Hand-derived lines: zero is a real source value; blank remains absent.
    lines = text.splitlines()
    assert zero_preview in lines
    assert blank_preview in lines
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
