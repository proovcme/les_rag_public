# -*- coding: utf-8
"""§3 (23.09): the ЛСР result must present the four distinct not-ready states as separate,
labelled buckets and must never turn a genuine zero amount into "unknown".  A reader must
not be able to mistake the empty XLSX formula cache for zero calculated works — the
application's calculated_positions is the authoritative figure."""
from __future__ import annotations

from tests.lsr_citation_support import cited_all

from proxy.services.lsr_result_readiness_service import build_lsr_result_readiness


def _rows():
    # The work row carries the citation record the application stores for it (§ 3).
    return cited_all([
        {"source_row": "СКС!R2", "row_role": "work",
         "norm_code": "ГЭСН12-01-034-02", "norm_status": "EXACT"},
        {"source_row": "СКС!R3", "row_role": "work", "norm_code": "", "norm_status": "MISSING"},
    ])


def test_gap_states_expose_the_named_buckets():
    readiness = build_lsr_result_readiness(
        packaged=True,
        rows=_rows(),
        missing=["price_missing:ГЭСН12-01-034-02"],
        pricing_status="priced_partial",
        catalog_work_count=2,
        calculated_positions=1,
        confirmed_amount=0.0,
        preliminary_amount=500.0,
    )
    states = readiness["gap_states"]
    # Since build 815 the not-ready states are five: a cipher that IS written but
    # has no evidence behind it is kept apart from "no norm at all" (ADR-16 § 6).
    assert set(states) == {
        "norm_missing",
        "norm_unsubstantiated",
        "price_missing",
        "calculation_incomplete",
        "formula_cache_uncached",
    }
    # one work has no confirmed norm
    assert states["norm_missing"]["count"] >= 1
    # a chosen cipher without cited evidence is its own state, never folded into
    # norm_missing nor silently counted as applicable
    assert states["norm_unsubstantiated"]["count"] == 0
    assert "применимость" in states["norm_unsubstantiated"]["meaning"]
    # one resource has no price, but its norm is kept
    assert states["price_missing"]["count"] >= 1
    # 2 works, only 1 calculated -> 1 position still unpriced by the calculator
    assert states["calculation_incomplete"]["count"] == 1
    # the authoritative figure for totals is the app count, not the XLSX cache
    assert states["formula_cache_uncached"]["authoritative"] == "calculated_positions"


def test_genuine_zero_amount_is_not_dropped():
    readiness = build_lsr_result_readiness(
        packaged=True,
        rows=_rows(),
        pricing_status="priced_partial",
        catalog_work_count=2,
        calculated_positions=2,
        confirmed_amount=0.0,
        preliminary_amount=1000.0,
    )
    counts = readiness["counts"]
    # a real 0.0 confirmed amount must survive as 0.0, not vanish as "unknown"
    assert counts["confirmed_amount"] == 0.0
    # with all works calculated there is no incomplete-calculation bucket
    assert readiness["gap_states"]["calculation_incomplete"]["count"] == 0


def test_absent_calculated_count_is_reported_as_unknown():
    readiness = build_lsr_result_readiness(
        packaged=True,
        rows=_rows(),
        pricing_status="priced_partial",
        catalog_work_count=2,
        calculated_positions=-1,
    )
    # -1 means the app did not pass a count: neither a number nor a false zero
    assert "calculated_positions" not in readiness["counts"]
    assert readiness["gap_states"]["calculation_incomplete"]["count"] is None
