"""Explicit derived volumes are arithmetic, never a replacement source fact."""

from copy import deepcopy
import json

import pytest

from proxy.services import gesn_service
from proxy.services.rim_lsr_trace_service import (
    _norm_qty_from_visible_row,
    build_lsr_trace_from_visible_rows,
    build_position_trace,
    positions_from_visible_lsr_rows,
)


CODE = "ГЭСНм08-02-409-09"
BASIS = "Authored source S!R2 and full norm card Q1.H1; repeated application"


def _row(**changes):
    return {
        "source_row": "S!R2", "operation_id": "authored-operation",
        "row_role": "work", "title": "Authored work", "norm_code": CODE,
        "quantity": 37.5, "unit": "м²", "conversion_source": BASIS,
        **changes,
    }


@pytest.mark.parametrize("source_qty,source_unit,derived,calc_unit,norm_unit,expected", [
    (37.5, "м²", 1.5, "100 м²", "100 м²", 1.5),
    (.375, "100 м²", 1.5, "100 м²", "100 м²", 1.5),
    (37.5, "м²", 150, "м²", "100 м²", 1.5),
    (0, "м²", 0, "100 м²", "100 м²", 0),
    (-37.5, "м²", -1.5, "100 м²", "100 м²", -1.5),
    (1, "м", 2, "км", "100 м", 20),
    (1, "м", 2, "1000 м", "км", 2),
    (1, "шт", 2, "1000 кг", "т", 2),
    (1, "шт", 2, "т", "100 кг", 20),
])
def test_explicit_calc_unit_scale_and_si_are_applied_exactly_once(
    source_qty, source_unit, derived, calc_unit, norm_unit, expected,
):
    row = _row(quantity=source_qty, unit=source_unit,
               calc_quantity=derived, calc_unit=calc_unit)
    original = deepcopy(row)
    quantity, trace = _norm_qty_from_visible_row(row, CODE, {"unit": norm_unit})
    assert quantity == pytest.approx(expected)
    assert (trace["source_quantity"], trace["source_unit"]) == (source_qty, source_unit)
    assert trace["calc_quantity"] == derived
    assert trace["calc_unit"] == calc_unit
    assert trace["norm_measure_factor"] > 0
    assert trace["calc_measure_factor"] > 0
    assert source_unit in trace["formula"] and calc_unit in trace["formula"]
    assert norm_unit in trace["formula"] and BASIS in trace["formula"]
    assert row == original


@pytest.mark.parametrize("derived_fields", [
    {"calc_quantity": 1.5},
    {"conversion_factor": .04},
    {"calc_quantity": 1.5, "conversion_factor": .04},
])
def test_incompatible_explicit_unit_is_an_authored_visible_gap(derived_fields):
    row = _row(calc_unit="шт", **derived_fields)
    original = deepcopy(row)
    quantity, trace = _norm_qty_from_visible_row(row, CODE, {"unit": "100 м²"})
    assert quantity is None
    assert trace["status"] == "needs_input"
    assert trace["invalid_field"] == "calc_unit"
    assert trace["calc_unit"] == "шт"
    assert "шт" in trace["message"] and "100 м²" in trace["message"]
    assert trace["source_quantity"] == 37.5 and trace["source_unit"] == "м²"
    assert row == original


@pytest.mark.parametrize("field,value", [("calc_quantity", 150), ("conversion_factor", 4)])
def test_omitted_calc_unit_preserves_the_legacy_norm_base_contract(field, value):
    # Legacy cited scalars are physical norm-base values, not source measures.
    row = _row(quantity=.375, unit="100 м²", **{field: value})
    expected = 1.5 if field == "calc_quantity" else .015
    quantity, trace = _norm_qty_from_visible_row(row, CODE, {"unit": "100 м²"})
    assert quantity == pytest.approx(expected)
    assert trace["source_quantity"] == .375 and trace["source_unit"] == "100 м²"


@pytest.mark.parametrize("derived,factor,expected", [
    (150, 4, 1.5), (150.005, 4, 1.50005),
    (0, 0, 0), (-150, -4, -1.5),
])
def test_agreeing_explicit_calculation_and_factor_preserve_signed_values(derived, factor, expected):
    row = _row(calc_quantity=derived, calc_unit="м²", conversion_factor=factor)
    original = deepcopy(row)
    quantity, trace = _norm_qty_from_visible_row(row, CODE, {"unit": "100 м²"})
    assert quantity == pytest.approx(expected)
    assert trace["calc_quantity"] == derived and trace["conversion_factor"] == factor
    assert trace["source_quantity"] == 37.5
    assert row == original


@pytest.mark.parametrize("derived,factor", [(150, 3), (0, 1), (-150, 4)])
@pytest.mark.parametrize("basis", [BASIS, ""])
def test_contradictory_calculation_never_silently_prefers_one_authored_scalar(derived, factor, basis):
    row = _row(calc_quantity=derived, calc_unit="м²", conversion_factor=factor,
               conversion_source=basis)
    original = deepcopy(row)
    quantity, trace = _norm_qty_from_visible_row(row, CODE, {"unit": "100 м²"})
    assert quantity is None
    assert trace["status"] == "needs_input"
    assert trace["invalid_field"] == "calc_quantity"
    assert trace["conversion_factor"] == factor and trace["calc_quantity"] == derived
    assert trace["expected_calc_quantity"] == 37.5 * factor
    assert "calc_quantity" in trace["message"] and "conversion_factor" in trace["message"]
    assert row == original


@pytest.mark.parametrize("field,value", [
    ("calc_quantity", "NaN"), ("calc_quantity", "Infinity"),
    ("conversion_factor", "-Infinity"), ("conversion_factor", "1e309"),
])
def test_nonfinite_derived_values_remain_authored_and_unpriced(field, value):
    row = _row(calc_unit="100 м²", **{field: value})
    original = deepcopy(row)
    quantity, trace = _norm_qty_from_visible_row(row, CODE, {"unit": "100 м²"})
    assert quantity is None and trace["status"] == "needs_input"
    assert trace["invalid_field"] == field and trace["authored_value"] == value
    assert row == original


@pytest.mark.parametrize("measure", ["0 м²", "0,0 м²"])
def test_explicit_calc_measure_must_have_positive_scale(measure):
    quantity, trace = _norm_qty_from_visible_row(
        _row(calc_quantity=150, calc_unit=measure), CODE, {"unit": "100 м²"},
    )
    assert quantity is None and trace["status"] == "needs_input"
    assert trace["invalid_field"] == "calc_unit"


def test_finite_authored_scalars_cannot_hide_overflow_in_their_consistency_check():
    row = _row(quantity=1e308, calc_quantity=1e308, conversion_factor=1e308, calc_unit="м²")
    quantity, trace = _norm_qty_from_visible_row(row, CODE, {"unit": "100 м²"})
    assert quantity is None and trace["status"] == "needs_input"
    assert trace["expected_calc_quantity"] is None


def test_explicit_calculated_measure_overflow_is_a_visible_gap():
    measure = str(10 ** 308) + " м²"
    row = _row(calc_quantity=2, calc_unit=measure)
    quantity, trace = _norm_qty_from_visible_row(row, CODE, {"unit": "100 м²"})
    assert quantity is None and trace["status"] == "needs_input"
    assert trace["source_quantity"] == 37.5 and trace["calc_quantity"] == 2


def test_nonfinite_explicit_measure_is_blocked_without_nonfinite_calculated_trace():
    measure = str(10 ** 309) + " м²"
    quantity, trace = _norm_qty_from_visible_row(
        _row(calc_quantity=2, calc_unit=measure), CODE, {"unit": "100 м²"},
    )
    assert quantity is None and trace["status"] == "needs_input"
    assert trace["calc_unit"] == measure
    json.dumps(trace, allow_nan=False)


def test_uncited_derived_values_do_not_replace_the_source_quantity():
    row = _row(calc_quantity=1.5, calc_unit="100 м²", conversion_source="")
    quantity, trace = _norm_qty_from_visible_row(row, CODE, {"unit": "100 м²"})
    assert quantity == .375
    assert trace["status"] == "unit_conversion"
    assert "calc_unit" not in trace and "calc_quantity" not in trace


def _synthetic_card(monkeypatch, unit="100 м²"):
    card = {
        "code": CODE, "name": "Authored work", "unit": unit,
        "resources": [
            {"kind": kind, "code": f"R-{index}", "name": kind,
             "unit": "чел.-ч" if kind in {"labor", "machinist"} else "шт",
             "per_unit": index, "price": index * 10}
            for index, kind in enumerate(("labor", "machine", "machinist", "material"), 1)
        ],
    }
    monkeypatch.setattr(gesn_service, "get_norm", lambda *_args, **_kwargs: deepcopy(card))
    return card


@pytest.mark.parametrize("fields,expected", [
    ({"calc_quantity": 1.5, "calc_unit": "100 м²"}, 1.5),
    ({"conversion_factor": 4, "calc_unit": "м²"}, 1.5),
    ({"conversion_factor": .04, "calc_unit": "100 м²"}, 1.5),
    ({"calc_quantity": 0, "calc_unit": "100 м²"}, 0),
    ({"calc_quantity": -1.5, "calc_unit": "100 м²"}, -1.5),
])
def test_derived_norm_quantity_multiplies_each_norm_resource_once(monkeypatch, fields, expected):
    card = _synthetic_card(monkeypatch)
    row = _row(**fields)
    original = deepcopy(row)
    result = build_lsr_trace_from_visible_rows([row])
    binding = result["row_bindings"][0]
    assert binding["position"]["qty"] == pytest.approx(expected)
    decisions = {item["kind"]: item for item in binding["resource_decisions"]}
    assert set(decisions) == {"labor", "machine", "machinist", "material"}
    for resource in card["resources"]:
        assert decisions[resource["kind"]]["qty"] == pytest.approx(resource["per_unit"] * expected)
    assert binding["source_quantity"] == 37.5 and binding["source_unit"] == "м²"
    assert binding["source_row"] == row == original


@pytest.mark.parametrize("fields", [
    {"calc_quantity": 150, "conversion_factor": 3, "calc_unit": "м²"},
    {"calc_quantity": 150, "calc_unit": "шт"},
])
def test_confirmed_position_price_cannot_make_invalid_derivation_green(monkeypatch, fields):
    _synthetic_card(monkeypatch)
    row = _row(**fields, confirmed_price=1000, price_kind="position_total",
               price_source="Operator authored quotation", decision_author="operator")
    original = deepcopy(row)
    result = build_lsr_trace_from_visible_rows([row])
    assert result["summary"]["positions_built"] == 0
    assert result["summary"]["confirmed_amount"] == 0
    assert result["summary"]["result_status"] == "norm_selection_required"
    binding = result["row_bindings"][0]
    assert binding["status"] == "needs_input"
    assert binding["source_row"] == row == original


@pytest.mark.parametrize("source_qty,source_unit,norm_unit,calc_qty,calc_unit,quote_unit,expected", [
    (37.5, "м²", "100 м²", 150, "м²", "100 м²", .375),
    (-37.5, "м²", "100 м²", -150, "м²", "100 м²", -.375),
    (0, "м²", "100 м²", 0, "м²", "100 м²", 0),
    (1.5, "100 м²", "100 м²", 600, "м²", "м²", 150),
    (1, "км", "100 м", 2000, "м", "м", 1000),
    (37.5, "м²", "100 м²", 150, "м²", "м²", 37.5),
])
def test_whole_work_unit_quote_uses_source_volume_not_repeated_norm_volume(
    monkeypatch, source_qty, source_unit, norm_unit, calc_qty, calc_unit, quote_unit, expected,
):
    _synthetic_card(monkeypatch, norm_unit)
    row = _row(quantity=source_qty, unit=source_unit, calc_quantity=calc_qty,
               calc_unit=calc_unit, confirmed_price=10, confirmed_by="operator",
               price_kind="unit_price", price_unit=quote_unit)
    original = deepcopy(row)
    position = positions_from_visible_lsr_rows([row])["positions"][0]
    assert position["confirmed_price_quantity"] == pytest.approx(expected)
    assert position["confirmed_price_attributed"] is True
    price_trace = build_position_trace(position)["summary"]["operator_price_trace"]
    assert price_trace["cost"] == pytest.approx(10 * expected)
    assert (price_trace["source_quantity"], price_trace["source_unit"]) == (source_qty, source_unit)
    assert position["quantity_trace"]["calc_quantity"] == calc_qty
    assert row == original


@pytest.mark.parametrize("explicit_calc_unit", [False, True])
def test_genuine_cited_cross_dimension_quote_keeps_legacy_calculation(monkeypatch, explicit_calc_unit):
    _synthetic_card(monkeypatch)
    row = _row(quantity=3, unit="уп", calc_quantity=24, conversion_factor=8,
               confirmed_price=10, confirmed_by="operator", price_kind="unit_price", price_unit="м²")
    if explicit_calc_unit:
        row["calc_unit"] = "м²"
    original = deepcopy(row)
    position = positions_from_visible_lsr_rows([row])["positions"][0]
    assert position["qty"] == .24
    assert position["confirmed_price_quantity"] == 24
    assert position["confirmed_price_quantity_trace"]["conversion_source"] == BASIS
    assert build_position_trace(position)["summary"]["operator_price_trace"]["cost"] == 240
    assert row == original


def test_cited_quote_can_convert_explicit_calc_unit_with_known_si(monkeypatch):
    _synthetic_card(monkeypatch, "т")
    row = _row(quantity=3, unit="уп", calc_quantity=24, calc_unit="кг",
               confirmed_price=10, confirmed_by="operator", price_kind="unit_price", price_unit="кг")
    original = deepcopy(row)
    position = positions_from_visible_lsr_rows([row])["positions"][0]
    assert position["qty"] == .024
    assert position["confirmed_price_quantity"] == 24
    assert position["confirmed_price_attributed"] is True
    assert row == original


def test_unrelated_quote_unit_cannot_reuse_the_norm_conversion(monkeypatch):
    _synthetic_card(monkeypatch)
    row = _row(calc_quantity=150, calc_unit="м²", confirmed_price=10,
               confirmed_by="operator", price_kind="unit_price", price_unit="кг")
    original = deepcopy(row)
    position = positions_from_visible_lsr_rows([row])["positions"][0]
    assert position["qty"] == 1.5
    assert position["confirmed_price_quantity"] is None
    assert position["confirmed_price_attributed"] is False
    assert position["confirmed_price_issue"] == "position_price_unit_conflict"
    assert row == original
