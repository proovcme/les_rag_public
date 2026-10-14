"""Explicit conversion literals must mean the same thing at every RIM step."""

from copy import deepcopy

import pytest

from proxy.services import gesn_service
from proxy.services.rim_lsr_trace_service import positions_from_visible_lsr_rows


CODE = "ГЭСНм08-02-409-09"


@pytest.fixture
def norm(monkeypatch):
    card = {"code": CODE, "name": "Authored work", "unit": "100 м", "resources": []}
    monkeypatch.setattr(gesn_service, "get_norm", lambda *_args, **_kwargs: deepcopy(card))
    return card


@pytest.mark.parametrize("field, authored, expected", [
    ("calc_quantity", "1e3", 10),
    ("calc_quantity", "1E+3", 10),
    ("calc_quantity", "1,5e2", 1.5),
    ("calc_quantity", "1 000,25", 10.0025),
    ("calc_quantity", "1\u00a0000,25", 10.0025),
    ("conversion_factor", "1e-2", .01),
    ("conversion_factor", "2,5e-1", .25),
    ("conversion_factor", "0", 0),
])
def test_cited_literal_matches_numeric_value_without_double_norm_scaling(norm, field, authored, expected):
    row = {"source_row": "Sheet!R2", "operation_id": "work-2", "row_role": "work",
           "norm_code": CODE, "quantity": 100, "unit": "м", field: authored,
           "conversion_source": "Explicit source of conversion"}
    original = deepcopy(row)
    literal = positions_from_visible_lsr_rows([row])
    numeric = positions_from_visible_lsr_rows([{**row, field: float(authored.replace(" ", "").replace("\u00a0", "").replace(",", "."))}])
    assert len(literal["positions"]) == len(numeric["positions"]) == 1
    assert literal["positions"][0]["qty"] == pytest.approx(expected)
    assert literal["positions"][0]["qty"] == numeric["positions"][0]["qty"]
    binding = literal["row_bindings"][0]
    assert binding["quantity_trace"]["status"] == "cited_" + field
    assert binding["quantity_trace"][field] == numeric["row_bindings"][0]["quantity_trace"][field]
    assert binding["source_row"] == original == row
    assert binding["quantity_trace"]["source_quantity"] == 100


@pytest.mark.parametrize("field", ["calc_quantity", "conversion_factor"])
@pytest.mark.parametrize("authored", ["1/100", "3.2*2", "1e309", "NaN", "Infinity", "10 м"])
def test_invalid_cited_scalar_keeps_raw_and_does_not_price_it_or_drop_sibling(norm, field, authored):
    good = {"source_row": "Sheet!R2", "operation_id": "good", "row_role": "work",
            "norm_code": CODE, "quantity": 100, "unit": "м"}
    bad = {**good, "source_row": "Sheet!R3", "operation_id": "bad", field: authored,
           "conversion_source": "Explicit source of conversion"}
    original = deepcopy([good, bad])
    result = positions_from_visible_lsr_rows([good, bad])
    assert len(result["positions"]) == 1
    assert result["positions"][0]["qty"] == 1
    assert len(result["row_bindings"]) == 2
    binding = result["row_bindings"][1]
    assert binding["status"] == "needs_input"
    assert binding["quantity_trace"]["invalid_field"] == field
    assert binding["quantity_trace"]["authored_value"] == authored
    assert binding["source_row"] == bad
    assert [good, bad] == original
