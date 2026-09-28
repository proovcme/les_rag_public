"""ADR-16 § 7, acceptance § 12: every counted price must have an owner.

The defect these tests close: a rate stored inside the installed norm card was
applied as if it came from the chosen ценовая база, so a workbook whose own
header said "no price basis applied" still reported a non-zero confirmed amount
and a complete position.  Since then the resolver asks who provided the number:
the chosen book, КАЦ or the operator own confirmation are owners; the card is a
labelled last resort that keeps the position a draft.
"""

from __future__ import annotations

import pytest

from proxy.services.lsr_workbook_adapter_service import (
    collect_lsr_card_prices,
    collect_lsr_price_gaps,
    describe_lsr_card_prices,
)
from proxy.services.rim_lsr_trace_service import (
    build_lsr_trace_from_visible_rows,
    build_position_trace,
)

CODE = "ГЭСН12-01-034-02"
LABOR = "1-100-36"
MATERIAL = "01.7.15.06-0111"
CARD_LABOR_RATE = 475.11
CARD_MATERIAL_RATE = 91385.06


class _Book:
    """The ценовая база the operator chose: exact lookup by resource code."""

    def __init__(self, prices: dict[str, float]) -> None:
        self._prices = dict(prices)

    def lookup(self, code: str):
        price = self._prices.get(str(code).strip())
        return None if price is None else {"price_current": price}


def _card_resources() -> list[dict[str, object]]:
    """The composition as the norm card carries it, rates included."""
    return [
        {
            "kind": "labor",
            "code": LABOR,
            "name": "Средний разряд работы 3.6",
            "unit": "чел.-ч",
            "per_unit": 10.0,
            "price": CARD_LABOR_RATE,
        },
        {
            "kind": "material",
            "code": MATERIAL,
            "name": "Гвозди строительные",
            "unit": "т",
            "per_unit": 0.002,
            "price": CARD_MATERIAL_RATE,
        },
    ]


def _position(**overrides) -> dict[str, object]:
    position = {"code": CODE, "qty": 1.0, "nr_pct": 0, "sp_pct": 0}
    position.update(overrides)
    return position


def _resource_rows(trace):
    return {
        str(row["columns"].get("2")): row
        for row in trace["rows"]
        if str(row.get("type") or "").startswith("resource_")
    }


def test_chosen_book_rate_wins_over_the_rate_stored_in_the_norm_card():
    """§ 7: the estimate is calculated in the basis the operator picked."""
    trace = build_position_trace(
        _position(resources=_card_resources()),
        pricebook=_Book({LABOR: 400.0, MATERIAL: 50000.0}),
    )
    rows = _resource_rows(trace)

    assert {code: row["source"] for code, row in rows.items()} == {
        LABOR: "fgis_current",
        MATERIAL: "fgis_current",
    }
    assert rows[MATERIAL]["columns"]["10"] == 50000.0
    assert rows[LABOR]["columns"]["10"] == 400.0
    # 10.0 × 400 + 0.002 × 50000 — the book's numbers, never the card's
    assert trace["summary"]["total"] == pytest.approx(4100.0)
    assert trace["summary"]["card_priced_resources"] == []
    assert not [flag for flag in trace["summary"]["flags"]
                if "карточк" in str(flag)]
    assert trace["summary"]["amount_status"] == "complete"
    assert trace["summary"]["full_amount"] == trace["summary"]["total"]


def test_rate_without_an_owner_is_applied_labeled_and_keeps_the_position_draft():
    """A card rate still computes; it does not make the position complete."""
    trace = build_position_trace(
        _position(resources=_card_resources()),
        pricebook=_Book({}),
    )
    rows = _resource_rows(trace)
    summary = trace["summary"]

    assert {row["source"] for row in rows.values()} == {"card_price"}
    assert {row["meta"]["price_action"] for row in rows.values()} == {
        "card_price_without_basis"
    }
    assert {item["code"] for item in summary["card_priced_resources"]} == {
        LABOR,
        MATERIAL,
    }
    assert summary["total"] == pytest.approx(
        round(10.0 * CARD_LABOR_RATE, 2) + round(0.002 * CARD_MATERIAL_RATE, 2)
    )
    assert summary["amount_status"] == "partial"
    assert summary["full_amount"] is None
    assert [
        reason
        for reason in summary["completeness_reasons"]
        if reason.startswith("card_price_without_basis:")
    ] == [
        f"card_price_without_basis:{LABOR}",
        f"card_price_without_basis:{MATERIAL}",
    ]


def test_price_confirmed_by_the_operator_beats_the_chosen_book():
    """An operator rate is the owner of its own number, above the book."""
    resources = [
        {
            "kind": "labor",
            "code": LABOR,
            "name": "Средний разряд работы 3.6",
            "unit": "чел.-ч",
            "per_unit": 10.0,
            "price": 550.0,
            "price_confirmed": True,
            "price_source_ref": "протокол совещания 12.09.2026",
        }
    ]
    trace = build_position_trace(
        _position(resources=resources),
        pricebook=_Book({LABOR: 400.0}),
    )
    row = _resource_rows(trace)[LABOR]

    assert row["source"] == "manual"
    assert row["meta"]["basis"] == "explicit_resource_price"
    assert row["columns"]["10"] == 550.0
    assert trace["summary"]["card_priced_resources"] == []
    assert trace["summary"]["amount_status"] == "complete"


def test_price_with_a_source_reference_is_attributed_without_the_flag():
    """``price_source_ref`` alone answers "who provided this number"."""
    resources = [
        {
            "kind": "material",
            "code": MATERIAL,
            "name": "Гвозди строительные",
            "unit": "т",
            "per_unit": 0.002,
            "price": 90000.0,
            "price_source_ref": "смета подрядчика, лист 4",
        }
    ]
    trace = build_position_trace(_position(resources=resources))
    row = _resource_rows(trace)[MATERIAL]

    assert row["source"] == "manual"
    assert trace["summary"]["card_priced_resources"] == []
    assert trace["summary"]["amount_status"] == "complete"


def test_kac_price_is_an_owner_and_counts_as_confirmed():
    """§ 7: a resource without a book price goes to КАЦ, and КАЦ is an owner."""
    lsr = build_lsr_trace_from_visible_rows(
        [
            {
                "source_row": "СКС!R9",
                "row_role": "material",
                "work_row": "СКС!R8",
                "title": "Лоток лестничный",
                "unit": "м.п",
                "quantity": 30,
            }
        ],
        kac_map={"Лоток лестничный": 100.0},
    )
    binding = lsr["row_bindings"][0]

    assert binding["readiness"]["prices_provided"] is True
    assert binding["readiness"]["price_from_norm_card"] is False
    assert lsr["summary"]["confirmed_amount"] == pytest.approx(3000.0)
    assert lsr["summary"]["preliminary_amount"] == pytest.approx(0.0)
    assert collect_lsr_card_prices(lsr) == []


def test_unowned_card_money_is_preliminary_and_named_in_every_channel():
    """§ 10: the header, the gap list and the sums tell one story."""
    lsr = build_lsr_trace_from_visible_rows(
        [
            {
                "source_row": "ВОР!R3",
                "row_role": "work",
                "basis": "ГЭСН 12-01-034-02",
                "title": "Устройство обрешетки",
                "quantity": "61",
                "unit": "м2",
                "norm_status": "EXACT",
            }
        ]
    )
    summary = lsr["summary"]
    named = collect_lsr_card_prices(lsr)
    gaps = [
        item
        for item in collect_lsr_price_gaps(lsr)
        if item["price_action"] == "card_price_without_basis"
    ]

    assert named and gaps
    assert len(gaps) == len(named)
    assert {item["code"] for item in named} >= {MATERIAL}
    assert all(item["position_code"] == CODE for item in gaps)
    assert all("из карточки нормы" in item["action"] for item in gaps)
    assert all("Подтвердите" in item["action"] for item in gaps)
    # money is visible in the document but is not confirmed money
    assert summary["total"] == pytest.approx(11813.04)
    assert summary["confirmed_amount"] == pytest.approx(0.0)
    assert summary["preliminary_amount"] == pytest.approx(summary["total"])
    assert summary["result_status"] == "priced_partial"


def test_header_note_names_the_card_resource_and_the_rows_it_priced():
    """§ 7 / § 10: the sentence says which resource, at which rate, on which rows.

    Two shapes failed on real data: the label was read from a key the collected
    items do not carry, so the header rendered an empty resource name; and one
    rate that repeated across two ВОР rows read as the same money existing twice.
    """
    lsr = build_lsr_trace_from_visible_rows(
        [
            {
                "source_row": f"ВОР!R{number}",
                "row_role": "work",
                "basis": "ГЭСН 12-01-034-02",
                "title": "Устройство обрешетки",
                "quantity": "61",
                "unit": "м2",
                "norm_status": "EXACT",
            }
            for number in (3, 4)
        ]
    )
    note = describe_lsr_card_prices(collect_lsr_card_prices(lsr))

    assert "не из ценовой базы, а из карточки нормы" in note
    assert "черновиком" in note
    # the resource is named by what the operator recognises, with its rate
    assert "ОТ(ЗТ) средний разряд 2,5 — 475.11 руб." in note
    assert "Краны башенные, г/п 8 т (91.05.01-017) — 865.44 руб." in note
    # one rate applied to two rows is stated once, and both rows are named
    assert note.count("ОТ(ЗТ) средний разряд 2,5") == 1
    assert "ВОР!R3, ВОР!R4" in note
    # the header lists what fits and says how much it left out
    assert "показаны 6 из" in note
    assert "строк с ценой из карточки нормы всего: 2" in note
    assert ".." not in note


def test_header_note_labels_a_resource_that_has_no_name_at_all():
    """A nameless resource degrades to a placeholder, never to a blank label."""
    note = describe_lsr_card_prices(
        [
            {
                "kind": "material",
                "code": "",
                "name": "",
                "unit": "шт",
                "price": 1800.0,
                "locator": "ВОР!R7",
            }
        ]
    )

    assert "ресурс — 1800 руб./шт, строки ВОР!R7" in note
    assert ".." not in note
    assert " ; " not in note
