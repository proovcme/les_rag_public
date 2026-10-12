"""Literal quotation proofs never upgrade an unattributed model price."""

from types import SimpleNamespace

import pytest

from proxy.services.model_price_provenance_service import price_evidence_check
from proxy.services.rim_lsr_trace_service import build_lsr_trace_from_visible_rows


def _row(**extra):
    return {"source_row": "S!R2", "row_role": "material", "title": "Authored supply", "unit": "m",
            "quantity": 3, "confirmed_price": 25, "price_source": "quote.pdf", "evidence_refs": ["Q1.H1"], **extra}


def _chunk(content="Supply: price 25.00 RUB per m", **meta):
    return SimpleNamespace(content=content, doc_name="quote.pdf",
                           meta={"global_evidence_id": "actual-quote", **meta})


def _check(row, chunks):
    return price_evidence_check(row, chunks, {"Q1.H1": "actual-quote"})


def _complete(check):
    return all(check[key] is True for key in (
        "price_in_refs", "unit_in_refs", "source_in_refs", "optional_context_in_refs",
    ))


def test_no_model_price_has_no_price_check():
    assert _check({"evidence_refs": ["Q1.H1"]}, [_chunk()]) is None


@pytest.mark.parametrize("delivery,body_status", [("prepared", "full"), ("delivered", "deferred_capacity")])
def test_retained_raw_price_with_only_inventory_admitted_cannot_confirm_quote(delivery, body_status):
    chunk = _chunk(model_delivery_status=delivery, body_status=body_status,
                   model_inventory_delivery_status="delivered",
                   price_evidence={"price": 25, "unit": "m"})
    check = _check(_row(), [chunk])
    assert not _complete(check)
    trace = build_lsr_trace_from_visible_rows([{**_row(), "_price_evidence_check": check,
                                               "evidence_bindings": {"Q1.H1": "actual-quote"}}])
    assert trace["summary"]["confirmed_amount"] == 0
    assert trace["summary"]["preliminary_amount"] == 75
    chunk.meta.update(model_delivery_status="delivered", body_status="full")
    assert _complete(_check(_row(), [chunk]))


@pytest.mark.parametrize("amount,literal", [
    (25, "25"), (25, "25,00"), (1234.56, "1 234,56"), (1234.56, "1\u202f234,56"),
    (1234.56, "1,234.56"), (1234.56, "1.234,56"), (1234567, "1,234,567"), (0, "0,00"),
])
def test_locale_formatted_literal_quoted_amounts(amount, literal):
    assert _complete(_check(_row(confirmed_price=amount), [_chunk(f"Quoted price: {literal} RUB per m")]))


@pytest.mark.parametrize("chunk,row_extra", [
    (_chunk("Supply: price 50.00 RUB per m"), {}),
    (_chunk("Supply: unit m; no quote amount"), {}),
    (_chunk("Supply: price 25.00 RUB; unit is absent"), {}),
    (_chunk("Supply: price 25.00 RUB per m2"), {}),
    (_chunk("Supply: price 25.00 RUB per m/s"), {}),
    (_chunk(), {"price_source": "remembered-other.pdf"}),
    (_chunk(norm_code="08-02-409-09"), {}),
    (SimpleNamespace(content="Price 25 per m", doc_name="smeta_norm_cards.v1",
                     meta={"global_evidence_id": "actual-quote"}), {"price_source": "smeta_norm_cards.v1"}),
])
def test_absent_conflicting_or_norm_card_facts_do_not_confirm_model_price(chunk, row_extra):
    row = _row(**row_extra)
    check = _check(row, [chunk])
    assert not _complete(check)
    trace = build_lsr_trace_from_visible_rows([{**row, "_price_evidence_check": check,
                                               "evidence_bindings": {"Q1.H1": "actual-quote"}}])
    assert trace["summary"]["confirmed_amount"] == 0
    assert trace["summary"]["preliminary_amount"] == 75
    assert trace["row_bindings"][0]["position"]["resources"][0]["price"] == row["confirmed_price"]


def test_foreign_document_or_forged_binding_cannot_create_quote_proof():
    row = _row(evidence_refs=["Q9.H9"])
    assert not _complete(_check(row, [_chunk()]))
    assert not _complete(price_evidence_check(_row(), [_chunk()], {"Q1.H1": "forged-identity"}))


def test_different_evidence_chunks_cannot_jointly_create_one_quote():
    chunks = [_chunk("Only price 25 RUB"), _chunk("Unit m; amount absent")]
    assert not _complete(_check(_row(), chunks))


@pytest.mark.parametrize("typed,authored", [
    ({"price": 50, "unit": "m"}, {}),
    ({"price": 25, "unit": "kg"}, {}),
    ({"price": 25, "unit": "m", "currency": "USD"}, {"price_currency": "RUB"}),
    ({"price": 25, "unit": "m", "vat": 10}, {"price_vat": 20}),
    ({"price": 25, "unit": "m", "period": "2026-Q2"}, {"price_period": "2026-Q3"}),
    ({"price": 25, "unit": "m"}, {"price_currency": "RUB"}),
])
def test_typed_quote_row_is_authoritative_for_literal_field_conflicts(typed, authored):
    chunk = _chunk("Price 25 RUB per m; VAT 20%; period 2026-Q3", price_evidence=typed)
    assert not _complete(_check(_row(**authored), [chunk]))


def test_optional_authored_period_cannot_be_invented_from_document_date():
    assert not _complete(_check(_row(price_period="2026-Q3"), [_chunk()]))


def test_sentence_punctuation_does_not_remove_literal_amount_or_unit():
    assert _complete(_check(_row(), [_chunk("Amount: 25. Unit: m.")]))


@pytest.mark.parametrize("amount", [1234, 1.234])
def test_single_separator_grouping_requires_an_explicit_typed_quote_value(amount):
    row = _row(confirmed_price=amount)
    assert not _complete(_check(row, [_chunk("Amount: 1,234 RUB per m")]))
    assert _complete(_check(row, [_chunk("Amount: 1,234 RUB per m", price_evidence={"price": amount, "unit": "m"})]))


def test_malformed_explicit_quote_payload_does_not_fall_back_to_prose():
    assert not _complete(_check(_row(), [_chunk(price_evidence="invalid quote payload")]))


def test_real_cited_commercial_quote_calculates_without_operator_impersonation():
    row = _row(confirmed_price=1234.56, price_currency="RUB", price_vat=20, price_period="2026-Q3")
    chunk = _chunk("Supply: price 1 234,56 RUB per m; VAT 20%; period 2026-Q3", price_evidence={
        "price": 1234.56, "unit": "m", "currency": "RUB", "vat": 20, "period": "2026-Q3",
    })
    check = _check(row, [chunk])
    assert _complete(check)
    trace = build_lsr_trace_from_visible_rows([{**row, "_price_evidence_check": check,
                                               "evidence_bindings": {"Q1.H1": "actual-quote"}}])
    assert trace["summary"]["confirmed_amount"] == 3703.68
    assert trace["summary"]["preliminary_amount"] == 0
    assert trace["row_bindings"][0]["readiness"]["operator_confirmed_price"] is False


@pytest.mark.parametrize("role", ["material", "equipment"])
def test_normless_commercial_quote_does_not_require_a_normative_snapshot(monkeypatch, role):
    from proxy.services import gesn_service
    from proxy.services.chat_evidence_application_service import bind_row_evidence_ids

    def no_norm_lookup(*args, **kwargs):
        pytest.fail("a quoted supply must not acquire a normative dependency")

    monkeypatch.setattr(gesn_service, "get_norm", no_norm_lookup)
    row = _row(row_role=role, norm_code="")
    decisions = bind_row_evidence_ids([row], [_chunk(model_evidence_ref="Q1.H1")])
    assert "_evidence_check" not in decisions[0]
    trace = build_lsr_trace_from_visible_rows(decisions)
    assert trace["summary"]["confirmed_amount"] == 75
    assert trace["summary"]["preliminary_amount"] == 0
    assert trace["row_bindings"][0]["status"] == "bound"


def test_actual_operator_confirmation_bypasses_failed_model_quote_check():
    row = _row(price_source="operator", _price_evidence_check={"price_in_refs": False})
    trace = build_lsr_trace_from_visible_rows([row], confirmed_data={"S!R2": {"confirmed_price": 25}})
    assert trace["summary"]["confirmed_amount"] == 75


@pytest.mark.parametrize("kind", ["position_total", "invalid", None])
def test_explicit_non_unit_supply_price_kind_preserves_the_candidate_without_confirming_it(kind):
    row = _row(price_kind=kind)
    check = _check(row, [_chunk()])
    assert _complete(check)
    trace = build_lsr_trace_from_visible_rows([{**row, "_price_evidence_check": check,
                                               "evidence_bindings": {"Q1.H1": "actual-quote"}}])
    summary = trace["sections"][0]["positions"][0]["summary"]
    assert summary["known_amount"] == 75
    assert summary["full_amount"] is None
    assert "supply_price_kind_conflict" in summary["completeness_reasons"]
    assert trace["row_bindings"][0]["position"]["resources"][0]["price"] == 25
    assert trace["summary"]["confirmed_amount"] == 0


def test_supply_explicit_unit_price_and_absent_kind_keep_the_canonical_contract():
    for row in [_row(), _row(price_kind="unit_price")]:
        trace = build_lsr_trace_from_visible_rows([{**row, "_price_evidence_check": _check(row, [_chunk()]),
                                                   "evidence_bindings": {"Q1.H1": "actual-quote"}}])
        assert trace["summary"]["confirmed_amount"] == 75


@pytest.mark.parametrize("kind,expected", [("unit_price", 1200), ("position_total", 100), (None, None)])
def test_work_commercial_price_requires_its_explicit_meaning_and_uses_source_quantity(monkeypatch, kind, expected):
    from proxy.services import rim_lsr_trace_service as service

    monkeypatch.setattr(service.gesn_service, "get_norm", lambda _: {
        "code": "ГЭСНм08-02-409-09", "name": "Authored work", "unit": "100 м", "resources": [], "nr": 0, "sp": 0,
    })
    row = _row(row_role="work", title="Authored work", unit="м", quantity=12, confirmed_price=100,
               norm_code="ГЭСНм08-02-409-09", norm_status="EXACT", price_kind=kind)
    chunk = _chunk("Commercial price: 100 RUB per м")
    check = _check(row, [chunk])
    assert _complete(check)
    trace = service.build_lsr_trace_from_visible_rows([{**row, "_price_evidence_check": check,
                                                       "evidence_bindings": {"Q1.H1": "actual-quote"}}])
    summary = trace["sections"][0]["positions"][0]["summary"]
    assert summary["full_amount"] == expected
    assert trace["summary"]["confirmed_amount"] == (expected or 0)
    if kind is None:
        assert "position_price_kind_unknown:ГЭСНм08-02-409-09" in summary["completeness_reasons"]
        assert summary["known_amount"] == 12  # the previous candidate is preserved, never confirmed
    else:
        assert summary["operator_price_trace"]["qty"] == (12 if kind == "unit_price" else 1)


def test_work_unit_quote_conflict_keeps_its_authored_price_preliminary(monkeypatch):
    from proxy.services import rim_lsr_trace_service as service

    monkeypatch.setattr(service.gesn_service, "get_norm", lambda _: {
        "code": "ГЭСНм08-02-409-09", "name": "Authored work", "unit": "м", "resources": [], "nr": 0, "sp": 0,
    })
    row = _row(row_role="work", title="Authored work", unit="м", quantity=12, confirmed_price=100,
               norm_code="ГЭСНм08-02-409-09", norm_status="EXACT", price_kind="unit_price", price_unit="kg")
    check = _check(row, [_chunk("Commercial price: 100 RUB per kg")])
    assert _complete(check)
    trace = service.build_lsr_trace_from_visible_rows([{**row, "_price_evidence_check": check,
                                                       "evidence_bindings": {"Q1.H1": "actual-quote"}}])
    summary = trace["sections"][0]["positions"][0]["summary"]
    assert summary["known_amount"] == 1200
    assert summary["full_amount"] is None
    assert "position_price_unit_conflict:ГЭСНм08-02-409-09" in summary["completeness_reasons"]


def test_explicit_typed_price_meaning_cannot_be_relabelled_by_the_model():
    check = _check(_row(price_kind="unit_price"), [_chunk(price_evidence={
        "price": 25, "unit": "m", "price_kind": "position_total",
    })])
    assert check["optional_context_in_refs"] is False
