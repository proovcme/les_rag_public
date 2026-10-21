# -*- coding: utf-8
"""§3 (23.09): the ЛСР result presents the not-ready states as separate, labelled
buckets and never turns a genuine zero amount into "unknown".

Task 2026-09-29 § 4 changed which figure is authoritative.  ``calculated_positions``
counts positions of every role — a bound supply line is one of them — so «works минус
calculated_positions» was able to report zero unfinished works while a work row still
had no sum.  The revision's per-operation projection is the authority now: each work
answers «позиция полностью рассчитана» for itself, the reader subtracts nothing, and an
empty XLSX formula cache still cannot be mistaken for zero calculated works.
"""
from __future__ import annotations

from tests.lsr_citation_support import cited_all

from proxy.services.lsr_result_readiness_service import build_lsr_result_readiness
from proxy.services.rim_lsr_trace_service import row_projection


def _rows():
    # The work row carries the citation record the application stores for it (§ 3).
    return cited_all([
        {"source_row": "СКС!R2", "row_role": "work",
         "norm_code": "ГЭСН12-01-034-02", "norm_status": "EXACT"},
        {"source_row": "СКС!R3", "row_role": "work", "norm_code": "", "norm_status": "MISSING"},
    ])


def _operation(locator: str, *, role: str, calculated: bool | None, reasons=()):
    """One projected operation, built by the projection function itself.

    Going through :func:`row_projection` keeps this test honest about the field names
    the production revision writes instead of inventing a parallel shape (§ 10).
    """

    return row_projection({
        "row": locator,
        "row_role": role,
        "status": "bound",
        "readiness": {
            "position_calculated": calculated,
            "structure_calculated": True if calculated is not None else None,
            "known_amount_present": bool(calculated) if calculated is not None else None,
            "open_reasons": list(reasons),
        },
    })


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
        row_projection=[
            _operation("СКС!R2", role="work", calculated=True),
            _operation("СКС!R3", role="work", calculated=False,
                       reasons=["price_missing:ГЭСН12-01-034-02"]),
        ],
    )
    states = readiness["gap_states"]
    # A written cipher without evidence remains distinct from "no norm at all"
    # (ADR-16 § 6). Build 979 also keeps unresolved operation roles visible.
    assert set(states) == {
        "norm_missing",
        "norm_unsubstantiated",
        "role_unresolved",
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
    # Both source rows are explicitly works, so the separate role bucket is empty.
    assert states["role_unresolved"]["count"] == 0
    # one resource has no price, but its norm is kept
    assert states["price_missing"]["count"] >= 1
    # one work row answers «позиция полностью рассчитана — нет» on its own
    assert states["calculation_incomplete"]["count"] == 1
    # the authoritative figure is the per-operation projection, not a subtraction
    assert states["formula_cache_uncached"]["authoritative"] == "row_projection"


def test_genuine_zero_amount_is_not_dropped():
    readiness = build_lsr_result_readiness(
        packaged=True,
        rows=_rows(),
        pricing_status="priced_partial",
        catalog_work_count=2,
        calculated_positions=2,
        confirmed_amount=0.0,
        preliminary_amount=1000.0,
        row_projection=[
            _operation("СКС!R2", role="work", calculated=True),
            _operation("СКС!R3", role="work", calculated=True),
        ],
    )
    counts = readiness["counts"]
    # a real 0.0 confirmed amount must survive as 0.0, not vanish as "unknown"
    assert counts["confirmed_amount"] == 0.0
    # with all works calculated there is no incomplete-calculation bucket
    assert readiness["gap_states"]["calculation_incomplete"]["count"] == 0


def test_a_bound_supply_line_is_not_an_unfinished_work():
    """§ 4: a supply row cannot absorb a work row's open calculation.

    Two rows, one work and one material.  The material is priced, so exactly one
    position exists — and the old «works минус calculated_positions» answered that no
    work is unfinished.  The projection answers per operation: the work still has no
    sum.
    """
    rows = cited_all([
        {"source_row": "СКС!R2", "row_role": "work",
         "norm_code": "ГЭСН12-01-034-02", "norm_status": "EXACT"},
        {"source_row": "СКС!R3", "row_role": "material", "work_row": "СКС!R2",
         "title": "Лоток лестничный"},
    ])
    readiness = build_lsr_result_readiness(
        packaged=True,
        rows=rows,
        missing=["price_missing:ОТ(ЗТ) средний разряд 2,5"],
        pricing_status="priced_partial",
        catalog_work_count=1,
        calculated_positions=1,
        confirmed_amount=0.0,
        preliminary_amount=100.0,
        row_projection=[
            _operation("СКС!R2", role="work", calculated=False,
                       reasons=["price_missing:ОТ(ЗТ) средний разряд 2,5"]),
            _operation("СКС!R3", role="material", calculated=True),
        ],
    )
    assert readiness["gap_states"]["calculation_incomplete"]["count"] == 1
    counts = readiness["counts"]
    assert counts["works_projected"] == 1
    assert counts["works_with_calculated_position"] == 0
    assert counts["projected_operations"] == 2
    # the projection the readiness card counted from is the payload the API returns
    assert [item["locator"] for item in readiness["row_projection"]] == [
        "СКС!R2", "СКС!R3"
    ]


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
