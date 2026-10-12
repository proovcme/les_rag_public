"""A price-book hit and a model's price claim are different from provenance."""

import pytest

from proxy.services.rim_lsr_trace_service import build_lsr_trace_from_visible_rows, positions_from_visible_lsr_rows


class Book:
    def lookup(self, code):
        return {"price_current": 100, "unit": "м"} if code == "selected-resource" else None


def _supply(role="material", **extra):
    return {"source_row": "S!R2", "row_role": role, "title": "Authored resource", "unit": "м", "quantity": 3,
            "resource_code": "selected-resource", **extra}


@pytest.mark.parametrize("role", ["material", "equipment"])
def test_book_hit_without_resource_selection_evidence_stays_preliminary(role):
    authored = _supply(role)
    trace = build_lsr_trace_from_visible_rows([authored], pricebook=Book())
    position = trace["sections"][0]["positions"][0]
    assert position["summary"]["known_amount"] == 300
    assert position["summary"]["full_amount"] is None
    assert "resource_selection_unsubstantiated" in position["summary"]["completeness_reasons"]
    assert trace["summary"]["confirmed_amount"] == 0
    assert trace["summary"]["preliminary_amount"] == 300
    assert trace["row_bindings"][0]["readiness"]["position_calculated"] is False
    assert trace["row_bindings"][0]["position"]["resources"][0]["code"] == authored["resource_code"]


def test_book_hit_with_resource_selection_evidence_remains_confirmed():
    trace = build_lsr_trace_from_visible_rows([_supply(evidence_refs=["Q1.H1"])], pricebook=Book())
    assert trace["summary"]["confirmed_amount"] == 300
    assert trace["summary"]["preliminary_amount"] == 0
    assert trace["row_bindings"][0]["position"]["evidence_refs"] == ["Q1.H1"]


def test_active_model_reference_without_immutable_binding_is_not_resource_proof():
    trace = build_lsr_trace_from_visible_rows([_supply(evidence_refs=["Q999.H1"], evidence_bindings={})], pricebook=Book())
    assert trace["summary"]["confirmed_amount"] == 0
    assert trace["summary"]["preliminary_amount"] == 300


@pytest.mark.parametrize("proof", [None, {}, {"code_in_refs": False}, {"code_in_refs": "true"}])
def test_bound_unrelated_reference_does_not_prove_the_selected_resource(proof):
    row = _supply(evidence_refs=["Q1.H1"], evidence_bindings={"Q1.H1": "immutable-card"},
                  _resource_evidence_check=proof)
    trace = build_lsr_trace_from_visible_rows([row], pricebook=Book())
    summary = trace["sections"][0]["positions"][0]["summary"]
    assert summary["known_amount"] == 300
    assert summary["full_amount"] is None
    assert "resource_selection_unsubstantiated" in summary["completeness_reasons"]
    assert trace["row_bindings"][0]["position"]["resources"][0]["code"] == row["resource_code"]


def test_literally_cited_selected_resource_keeps_confirmed_book_money():
    row = _supply(evidence_refs=["Q1.H1"], evidence_bindings={"Q1.H1": "immutable-card"},
                  _resource_evidence_check={"code_in_refs": True})
    trace = build_lsr_trace_from_visible_rows([row], pricebook=Book())
    assert trace["summary"]["confirmed_amount"] == 300
    assert trace["summary"]["preliminary_amount"] == 0


@pytest.mark.parametrize("price_source", ["—", "MISSING", "operator"])
def test_placeholder_or_self_claimed_price_source_is_not_an_owner(price_source):
    row = _supply(resource_code="", confirmed_price=25, price_source=price_source,
                  evidence_refs=["Q1.H2"], evidence_bindings={"Q1.H2": "real-source"})
    trace = build_lsr_trace_from_visible_rows([row])
    assert trace["summary"]["confirmed_amount"] == 0


def test_commercial_model_price_needs_an_immutable_source_binding():
    row = _supply(resource_code="", confirmed_price=25, price_source="invoice.pdf#page=2",
                  evidence_refs=["Q1.H2"], evidence_bindings={})
    trace = build_lsr_trace_from_visible_rows([row])
    assert trace["summary"]["confirmed_amount"] == 0
    cited = build_lsr_trace_from_visible_rows([{**row, "evidence_bindings": {"Q1.H2": "invoice-row"}}])
    assert cited["summary"]["confirmed_amount"] == 75


@pytest.mark.parametrize("price_source", [None, "", "operator"])
def test_model_price_claim_never_synthesizes_operator_confirmation(price_source):
    authored = _supply(resource_code="", confirmed_price=25)
    if price_source is not None:
        authored["price_source"] = price_source
    trace = build_lsr_trace_from_visible_rows([authored])
    resource = trace["row_bindings"][0]["position"]["resources"][0]
    assert resource["price"] == 25
    assert not resource.get("price_source_ref")
    assert trace["summary"]["confirmed_amount"] == 0
    assert trace["summary"]["preliminary_amount"] == 75


def test_actual_operator_overlay_keeps_confirmed_supply_money():
    trace = build_lsr_trace_from_visible_rows([_supply(resource_code="")],
                                            confirmed_data={"S!R2": {"confirmed_price": 25}})
    assert trace["summary"]["confirmed_amount"] == 75
    assert trace["summary"]["preliminary_amount"] == 0
    assert trace["row_bindings"][0]["position"]["resources"][0]["price_source_ref"] == "operator"


def test_explicit_commercial_price_needs_its_evidence_reference():
    price = _supply(resource_code="", confirmed_price=25, price_source="invoice.pdf#page=2")
    without = build_lsr_trace_from_visible_rows([price])
    with_source = build_lsr_trace_from_visible_rows([{**price, "evidence_refs": ["Q1.H2"]}])
    assert without["summary"]["confirmed_amount"] == 0
    assert with_source["summary"]["confirmed_amount"] == 75


def test_visible_kac_name_float_lookup_has_no_source_or_unit_proof():
    trace = build_lsr_trace_from_visible_rows([_supply(resource_code="", evidence_refs=["Q1.H2"])],
                                            kac_map={"Authored resource": 25})
    position = trace["sections"][0]["positions"][0]
    assert position["summary"]["known_amount"] == 75
    assert position["summary"]["full_amount"] is None
    assert any(reason.startswith("kac_without_source_unit:") for reason in position["summary"]["completeness_reasons"])
    assert trace["summary"]["confirmed_amount"] == 0
    assert trace["summary"]["preliminary_amount"] == 75


def test_work_price_is_preserved_without_fabricated_operator_source(monkeypatch):
    from proxy.services import rim_lsr_trace_service as service

    monkeypatch.setattr(service.gesn_service, "get_norm", lambda _: {"unit": "м", "resources": [], "nr": 0, "sp": 0})
    row = {"source_row": "S!R2", "row_role": "work", "title": "Authored work", "unit": "м", "quantity": 3,
           "norm_code": "ГЭСНм08-02-409-09", "norm_status": "EXACT", "confirmed_price": 25}
    position = positions_from_visible_lsr_rows([row])["positions"][0]
    assert position["confirmed_price"] == 25
    assert position["price_source"] == ""
    assert position["confirmed_price_attributed"] is False


@pytest.mark.parametrize("owner", ["model", "operator", "source"])
def test_whole_position_price_has_the_actual_owner_in_amount_and_trace(monkeypatch, owner):
    from proxy.services import rim_lsr_trace_service as service

    monkeypatch.setattr(service.gesn_service, "get_norm", lambda _: {
        "code": "ГЭСНм08-02-409-09", "name": "Authored work", "unit": "м", "resources": [], "nr": 0, "sp": 0,
    })
    row = {"source_row": "S!R2", "row_role": "work", "title": "Authored work", "unit": "м", "quantity": 3,
           "norm_code": "ГЭСНм08-02-409-09", "norm_status": "EXACT", "confirmed_price": 25,
           "evidence_refs": ["Q1.H1"]}
    overlay = None
    if owner == "operator":
        overlay = {"S!R2": {"confirmed_price": 25}}
    elif owner == "source":
        row["price_source"] = "invoice.pdf#page=2"
        row["price_kind"] = "unit_price"
    else:
        row["price_source"] = "operator"  # self-authored claim is not confirmation
    trace = build_lsr_trace_from_visible_rows([row], confirmed_data=overlay)
    summary = trace["sections"][0]["positions"][0]["summary"]
    expected_status = {
        "model": "position_price_without_basis", "operator": "operator_confirmed_position_price",
        "source": "source_confirmed_position_price",
    }[owner]
    assert summary["operator_price_trace"]["status"] == expected_status
    assert summary["known_amount"] == 75
    assert summary["full_amount"] == (None if owner == "model" else 75)
    assert trace["summary"]["confirmed_amount"] == (0 if owner == "model" else 75)
    assert trace["row_bindings"][0]["readiness"]["operator_confirmed_price"] is (owner == "operator")


def test_resource_evidence_does_not_override_an_incompatible_book_unit():
    class WrongUnitBook(Book):
        def lookup(self, code):
            return {"price_current": 100, "unit": "кг"}

    trace = build_lsr_trace_from_visible_rows([_supply(evidence_refs=["Q1.H1"])], pricebook=WrongUnitBook())
    assert trace["summary"]["confirmed_amount"] == 0
    assert trace["row_bindings"][0]["readiness"]["prices_provided"] is False


@pytest.mark.parametrize("book_unit", [None, ""])
def test_missing_book_unit_preserves_known_price_without_confirming_it(book_unit):
    class UnknownUnitBook(Book):
        def lookup(self, code):
            return {"price_current": 100, "unit": book_unit}

    trace = build_lsr_trace_from_visible_rows([_supply(evidence_refs=["Q1.H1"])], pricebook=UnknownUnitBook())
    summary = trace["sections"][0]["positions"][0]["summary"]
    assert summary["known_amount"] == 300
    assert summary["full_amount"] is None
    assert "book_price_unit_unknown:selected-resource" in summary["completeness_reasons"]
    assert trace["summary"]["confirmed_amount"] == 0
    assert trace["summary"]["preliminary_amount"] == 300


def test_low_level_legacy_book_without_unit_keeps_its_existing_contract():
    from proxy.services.rim_lsr_trace_service import build_lsr_trace

    class UnknownUnitBook(Book):
        def lookup(self, code):
            return {"price_current": 100}

    trace = build_lsr_trace([{"code": "", "qty": 3, "unit": "м", "nr_pct": 0, "sp_pct": 0,
                              "resources": [{"kind": "material", "name": "Legacy resource", "code": "selected-resource",
                                             "unit": "м", "per_unit": 1}]}], pricebook=UnknownUnitBook())
    assert trace["sections"][0]["positions"][0]["summary"]["full_amount"] == 300


def test_source_quantity_guard_precedes_both_book_and_operator_pricing():
    row = _supply(evidence_refs=["Q1.H1"], confirmed_price=25, confirmed_by="operator",
                  _catalog_source_values=["Authored resource", "м", ""],
                  _catalog_source_numbers=[], _catalog_source_quantity_known=True)
    # The exact current guard's persisted comparison is used here, not an invented
    # confirmation flag or an expectation that an operator price repairs volume.
    trace = build_lsr_trace_from_visible_rows([row], pricebook=Book())
    assert trace["row_bindings"][0]["status"] == "unconfirmed_quantity"
    assert trace["summary"]["confirmed_amount"] == 0
