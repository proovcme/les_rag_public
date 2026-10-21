"""A retained quote is not money until its quantity and price units agree."""

from copy import deepcopy

import pytest

from proxy.services import rim_lsr_trace_service as service


def _row(**extra):
    return {
        "source_row": "S!R2", "row_role": "material", "title": "Authored supply",
        "quantity": 50, "unit": "п.м.", "resource_code": "authored-resource",
        "confirmed_price": 298.72, "price_unit": "м2", "price_kind": "unit_price",
        "price_source": "quote.pdf", "evidence_refs": ["Q1.H1"],
        "evidence_bindings": {"Q1.H1": "quote-identity"},
        "_price_evidence_check": {
            "price_in_refs": True, "unit_in_refs": True,
            "source_in_refs": True, "optional_context_in_refs": True,
        },
        **extra,
    }


def _calculated(trace):
    return trace["sections"][0]["positions"][0]


@pytest.mark.parametrize("role", ["material", "equipment"])
@pytest.mark.parametrize("attributed", [True, False])
def test_supply_area_quote_cannot_multiply_a_length_even_preliminarily(role, attributed):
    row = _row(row_role=role)
    if not attributed:
        row["_price_evidence_check"]["price_in_refs"] = False
    # A nested resource proposal does not convert its owning supply quantity.
    row["resource_bindings"] = [{
        "quantity": 15.71, "unit": "м2", "conversion_source": "nested area formula",
    }]
    original = deepcopy(row)
    trace = service.build_lsr_trace_from_visible_rows([row])

    assert trace["summary"]["known_amount"] == 0
    assert trace["summary"]["preliminary_amount"] == 0
    assert trace["summary"]["confirmed_amount"] == 0
    calculated = _calculated(trace)
    assert calculated["summary"]["resource_decisions"][0]["cost"] is None
    assert calculated["summary"]["resource_decisions"][0]["price_action"] == "model_price_unit_conflict"
    assert calculated["summary"]["resource_decisions"][0]["quoted_price"] == 298.72
    assert calculated["summary"]["full_amount"] is None
    assert row == original
    retained = trace["row_bindings"][0]
    assert retained["source_row"] == original
    assert retained["position"]["resources"][0]["price"] == 298.72
    assert retained["position"]["resources"][0]["price_unit"] == "м2"
    assert retained["position"]["source_quantity"] == 50
    assert retained["position"]["source_unit"] == "п.м."


@pytest.mark.parametrize("quantity,source_unit,price_unit,extra,expected,priced_qty", [
    (50, "п.м.", "м", {}, 14936, 50),
    (50, "шт", "100 шт", {}, 149.36, .5),
    (.5, "100 шт", "шт", {}, 14936, 50),
    (1, "т", "кг", {}, 298720, 1000),
    (50, "п.м.", "м2", {"calc_quantity": 15.71, "conversion_source": "authored area formula"}, 4692.89, 15.71),
    (50, "п.м.", "м2", {"conversion_factor": .3142, "conversion_source": "authored area formula"}, 4692.89, 15.71),
])
def test_compatible_scale_and_explicit_area_conversions_are_calculated_once(
    quantity, source_unit, price_unit, extra, expected, priced_qty,
):
    row = _row(quantity=quantity, unit=source_unit, price_unit=price_unit, **extra)
    row["supply_resource_match"] = {
        "source_title": row["title"], "resource_code": row["resource_code"],
        "decision": "yes", "reason": "The cited quote covers the authored supply; its quantity conversion is stated separately.",
        "source_refs": list(row["evidence_refs"]),
    }
    original = deepcopy(row)
    trace = service.build_lsr_trace_from_visible_rows([row])
    assert trace["summary"]["known_amount"] == expected
    assert trace["summary"]["confirmed_amount"] == expected
    position = trace["row_bindings"][0]["position"]
    assert position["qty"] == priced_qty
    assert position["source_quantity"] == quantity
    assert position["source_unit"] == source_unit
    assert position["resources"][0]["price_unit"] == price_unit
    assert row == original


def test_valid_conversion_does_not_upgrade_an_unsubstantiated_quote():
    row = _row(calc_quantity=15.71, conversion_source="authored area formula")
    row["_price_evidence_check"]["price_in_refs"] = False
    trace = service.build_lsr_trace_from_visible_rows([row])
    assert trace["summary"]["known_amount"] == 4692.89
    assert trace["summary"]["confirmed_amount"] == 0


def test_work_norm_conversion_is_not_borrowed_for_a_different_quote_dimension(monkeypatch):
    _work_norm(monkeypatch, "м2")
    row = _row(row_role="work", norm_code="ГЭСН20-01-001-01", norm_status="EXACT",
               calc_quantity=15.71, conversion_source="authored area formula", price_unit="кг")
    trace = service.build_lsr_trace_from_visible_rows([row])
    assert trace["summary"]["known_amount"] == 0
    assert trace["summary"]["confirmed_amount"] == 0


def test_rejected_work_quote_does_not_remove_valid_norm_resource_subtotals(monkeypatch):
    monkeypatch.setattr(service.gesn_service, "get_norm", lambda _: {
        "code": "ГЭСН20-01-001-01", "name": "Authored work", "unit": "м",
        "resources": [{"kind": "material", "code": "norm-resource", "name": "Norm material",
                       "unit": "шт", "per_unit": 2, "price": 10}],
        "nr": 0, "sp": 0,
    })
    row = _row(row_role="work", norm_code="ГЭСН20-01-001-01", norm_status="EXACT")
    trace = service.build_lsr_trace_from_visible_rows([row])
    assert trace["summary"]["known_amount"] == 1000
    assert trace["summary"]["mat"] == 1000
    assert trace["summary"]["direct"] == 1000
    assert _calculated(trace)["summary"]["operator_price_trace"]["cost"] is None
    assert _calculated(trace)["summary"]["resource_reference_only"] is False


@pytest.mark.parametrize("extra", [
    {"calc_quantity": 15.71}, {"conversion_factor": .3142},
    {"calc_quantity": "not a number", "conversion_source": "authored formula"},
])
def test_uncited_or_invalid_conversion_does_not_create_a_supply_amount(extra):
    trace = service.build_lsr_trace_from_visible_rows([_row(**extra)])
    assert trace["summary"]["known_amount"] == 0
    assert trace["summary"]["confirmed_amount"] == 0


def _work_norm(monkeypatch, unit):
    monkeypatch.setattr(service.gesn_service, "get_norm", lambda _: {
        "code": "ГЭСН20-01-001-01", "name": "Authored work", "unit": unit,
        "resources": [], "nr": 0, "sp": 0,
    })


@pytest.mark.parametrize("kind,expected", [("unit_price", 0), ("position_total", 298.72), ("unknown", 0)])
def test_work_incompatible_unit_quote_is_not_a_product_but_position_total_is_a_total(monkeypatch, kind, expected):
    _work_norm(monkeypatch, "м")
    row = _row(row_role="work", norm_code="ГЭСН20-01-001-01", norm_status="EXACT", price_kind=kind)
    trace = service.build_lsr_trace_from_visible_rows([row])
    assert trace["summary"]["known_amount"] == expected
    assert trace["summary"]["confirmed_amount"] == expected
    quote = _calculated(trace)["summary"]["operator_price_trace"]
    assert quote["price"] == 298.72
    assert quote["cost"] == (expected if kind == "position_total" else None)


def test_work_quote_uses_explicit_norm_compatible_area_conversion(monkeypatch):
    _work_norm(monkeypatch, "100 м2")
    row = _row(row_role="work", norm_code="ГЭСН20-01-001-01", norm_status="EXACT",
               calc_quantity=15.71, conversion_source="authored area formula")
    trace = service.build_lsr_trace_from_visible_rows([row])
    assert trace["summary"]["confirmed_amount"] == 4692.89
    quote = _calculated(trace)["summary"]["operator_price_trace"]
    assert quote["qty"] == 15.71
    assert quote["unit"] == "м2"

