"""ADR-16 § 7, acceptance § 12: every counted price must have an owner.

The defect these tests close: a rate stored inside the installed norm card was
applied as if it came from the chosen ценовая база, so a workbook whose own
header said "no price basis applied" still reported a non-zero confirmed amount
and a complete position.  Since then the resolver asks who provided the number:
the chosen book, КАЦ or the operator own confirmation are owners; the card is a
labelled last resort that keeps the position a draft.

The other half of ownership is the unit the owner priced.  ``PriceBook.lookup``
answers to a шифр alone, so a book row stating «кг» used to price a resource the
norm card gives in «л» — the amount carried the book's name and none of the
book's meaning (acceptance § 8, § 11 № 8).  Those cases are here too, because a
price without a unit is exactly as unowned as a price without a source.
"""

from __future__ import annotations

import pytest

from proxy.services import gesn_service
from proxy.services import rim_lsr_trace_service
from proxy.services.lsr_assembly_service import (
    _rejected_book_unit,
    _resource_price,
    compute_position,
)
from proxy.services.lsr_workbook_adapter_service import (
    collect_lsr_card_prices,
    collect_lsr_price_gaps,
    describe_lsr_card_prices,
)
from proxy.services.rim_lsr_trace_service import (
    BOOK_UNIT_CONFLICT_ACTION,
    build_lsr_trace_from_visible_rows,
    build_position_trace,
)

CODE = "ГЭСН12-01-034-02"
LABOR = "1-100-36"
MATERIAL = "01.7.15.06-0111"
# Rates a norm card states for itself.  This test writes them as round numbers on purpose:
# they are not the money of any region's ценовая база and not the excluded demo seed's, and
# every sum pinned below is the product of one of them and a consumption the base card
# really states, so a reader can re-multiply it on paper.
CARD_LABOR_RATE = 480.00
CARD_MATERIAL_RATE = 90000.00


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


# ── a card that prices its own rows, built as explicit data ───────────────────
#
# The canonical base card of ``CODE`` (data/smeta_base/les_smeta_base.sqlite) states the
# consumptions, units and тарифный шифры below — they are its own rows — and no price at
# all: measured 0 of 63 673 labour rows in the base write one, and its machine and material
# rows carry none either.  A card that prices its own rows is therefore a legacy card shape,
# and since the demo seed stopped being merged into the read path the tests hand that shape
# to the calculator as explicit data instead of reaching for
# config/domain/gesn_seed.yaml (which production no longer reads).  The rates are numbers
# this test chooses, round so each sum below re-multiplies on paper; they carry no authority
# beyond the branch they exist to exercise, and they are deliberately not the demo seed's
# amounts — those are named as artifacts in stage_b/live_830/seed_vs_base_reconcile_830.md.

CARD_MACHINE_RATE = 900.00          # краны башенные 8 т, руб./маш.-ч
CARD_MACHINIST_RATE_6 = 800.00      # ОТм 6 разряда, руб./чел.-ч
CARD_MACHINE_RATE_KAC16 = 1700.00   # краны на автомобильном ходу 16 т, руб./маш.-ч
CARD_MACHINIST_RATE_4 = 600.00      # ОТм 4 разряда, руб./чел.-ч
CARD_MACHINE_RATE_TRUCK = 600.00    # автомобили бортовые 5 т, руб./маш.-ч


def _legacy_card_resources() -> list[dict[str, object]]:
    """The composition of ``CODE`` with a rate written on every row.

    Quantities, units and шифры are the base card's own rows; the per-machine machinist
    lines are the legacy split shape (the base writes one aggregated «Затраты труда
    машинистов» row of 1,01 маш.-ч, these three add up to it).
    """
    return [
        {
            "kind": "labor",
            "code": "1-100-25",
            "name": "Средний разряд работы 2.5",  # the base card's own labour row
            "unit": "чел.-ч",
            "per_unit": 12.94,
            "price": CARD_LABOR_RATE,
        },
        {
            "kind": "machine",
            "code": "91.05.01-017",
            "name": "Краны башенные, г/п 8 т",
            "unit": "маш.-ч",
            "per_unit": 0.97,
            "price": CARD_MACHINE_RATE,
        },
        {
            "kind": "machinist",
            "code": "",
            "name": "ОТм краны 8 т, разряд 6",
            "unit": "маш.-ч",
            "per_unit": 0.97,
            "price": CARD_MACHINIST_RATE_6,
        },
        {
            "kind": "machine",
            "code": "91.05.05-015",
            "name": "Краны на автомобильном ходу, 16 т",
            "unit": "маш.-ч",
            "per_unit": 0.01,
            "price": CARD_MACHINE_RATE_KAC16,
        },
        {
            "kind": "machinist",
            "code": "",
            "name": "ОТм краны 16 т, разряд 6",
            "unit": "маш.-ч",
            "per_unit": 0.01,
            "price": CARD_MACHINIST_RATE_6,
        },
        {
            "kind": "machine",
            "code": "91.14.02-001",
            "name": "Автомобили бортовые, г/п до 5 т",
            "unit": "маш.-ч",
            "per_unit": 0.03,
            "price": CARD_MACHINE_RATE_TRUCK,
        },
        {
            "kind": "machinist",
            "code": "",
            "name": "ОТм бортовые, разряд 4",
            "unit": "маш.-ч",
            "per_unit": 0.03,
            "price": CARD_MACHINIST_RATE_4,
        },
        {
            "kind": "material",
            "code": MATERIAL,
            "name": "Гвозди строительные",
            "unit": "т",
            "per_unit": 0.0015,
            "price": CARD_MATERIAL_RATE,
        },
    ]


def _legacy_card(**overrides) -> dict[str, object]:
    """A norm card that writes its own numbers: the shape the resolver must label.

    ``_source_kind`` stays unset on purpose.  The card is a legacy card handed to the
    calculator as data, not the demo seed, so the position is not quarantined as demo
    material either and the only open question stays the ownership of its money.
    """
    card = {
        "code": CODE,
        "name": "Устройство обрешетки с прозорами из брусков",  # the base card's own name
        "unit": "100 м2",  # the base card's own unit: 61 м2 of ВОР is 0,61 of it
        "resources": _legacy_card_resources(),
    }
    card.update(overrides)
    return card


def _install_card(monkeypatch, card: dict[str, object]) -> None:
    """Serve ``card`` for its own шифр, keep the canonical base for every other code."""
    real_get_norm = gesn_service.get_norm

    def _get_norm(code, *args, **kwargs):
        if str(code or "").strip() == str(card["code"]):
            return dict(card)
        return real_get_norm(code, *args, **kwargs)

    monkeypatch.setattr(gesn_service, "get_norm", _get_norm)


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


def test_unowned_card_money_is_preliminary_and_named_in_every_channel(monkeypatch):
    """§ 10: the header, the gap list and the sums tell one story."""
    # the card of CODE that states its own rates, served in place of the priceless base
    # card — see `_legacy_card()` above for where each of its numbers comes from
    _install_card(monkeypatch, _legacy_card())
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
    # money is visible in the document but is not confirmed money.  12 015,84 = прямые
    # 4 914,28 (ОЗП 7,8934 чел.-ч × 480,00 + машины 553,88 + ЗПМ 489,22 по своим тарифам +
    # гвозди 0,000915 т × 90 000,00 — all the stub card's own rates) + НР 109 % и СП 57 % of
    # ФОТ 4 278,05, which the single ГЭСН:12 rule of the accrual catalog
    # (config/domain/nr_sp_catalog.json) owns — so the card money is the only hole here.
    assert summary["total"] == pytest.approx(12015.84)
    assert summary["confirmed_amount"] == pytest.approx(0.0)
    assert summary["preliminary_amount"] == pytest.approx(summary["total"])
    assert summary["result_status"] == "priced_partial"


def test_header_note_names_the_card_resource_and_the_rows_it_priced(monkeypatch):
    """§ 7 / § 10: the sentence says which resource, at which rate, on which rows.

    Two shapes failed on real data: the label was read from a key the collected
    items do not carry, so the header rendered an empty resource name; and one
    rate that repeated across two ВОР rows read as the same money existing twice.
    """
    # the same eight card-owned rates, applied to two ВОР rows of one operation
    _install_card(monkeypatch, _legacy_card())
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
    # the resource is named by what the operator recognises, with its rate.  The ОЗП label
    # carries the тарифный шифр the card row itself states (1-100-25), so the operator can
    # see which book row would own the money.
    assert "Средний разряд работы 2.5 (1-100-25) — 480,00 руб." in note
    assert "Краны башенные, г/п 8 т (91.05.01-017) — 900,00 руб." in note
    # one rate applied to two rows is stated once, and both rows are named
    assert note.count("Средний разряд работы 2.5") == 1
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

    assert "ресурс — 1 800,00 руб./шт, строки ВОР!R7" in note
    assert ".." not in note
    assert " ; " not in note


CARD_ACCRUAL_CODE = "ГЭСНм11-04-028-01"  # ГЭСНм:11 keeps two catalog rules
CATALOG_ACCRUAL_CODE = "ГЭСН12-01-034-02"  # ГЭСН:12 has exactly one catalog rule


def _accrual_card() -> dict[str, object]:
    """The card of ``CARD_ACCRUAL_CODE`` that prints its own НР/СП percentages.

    A base card carries no ``nr_pct``/``sp_pct`` at all, so the unowned accrual rates are
    written into the card here as explicit data — the pair 100 %/40 % is a number this test
    chooses, while the card's name and unit stay the base card's own.  What stays real base
    data is the point of the test — the catalog of ГЭСНм:11 holds two rules, so the
    fail-closed catalog refuses to pick either and nobody owns the card's percentages.
    """
    return _legacy_card(
        code=CARD_ACCRUAL_CODE,
        name="Включение в аппаратуру разъемов штепсельных, количество контактов в разъеме: до 14 шт.",
        unit="шт",
        resources=[],
        nr_pct=100,
        sp_pct=40,
    )


def _owned_labor_resources() -> list[dict[str, object]]:
    """Labour whose rate has an owner, so НР/СП are the only open question."""
    return [
        {
            "kind": "labor",
            "code": LABOR,
            "name": "Средний разряд работы 3.6",
            "unit": "чел.-ч",
            "per_unit": 10.0,
            "price": 400.0,
            "price_confirmed": True,
            "price_source_ref": "протокол совещания 12.09.2026",
        }
    ]


def test_accrual_rate_read_off_the_norm_card_keeps_the_position_draft(monkeypatch):
    """§ 11 № 6: known resource prices must not mask НР/СП without an owner.

    ГЭСНм:11 carries two catalog rules, so the fail-closed catalog refuses to
    choose.  The percentages printed inside the card still produce money — a
    draft is not a zero — but nobody owns them, so the position stays partial
    and the operator is told which two numbers are unowned.
    """
    # the card that prints 100 % / 40 % as its own — see `_accrual_card()` above for why
    # those two numbers have to be card data now instead of base-card data
    _install_card(monkeypatch, _accrual_card())
    trace = build_position_trace(
        {"code": CARD_ACCRUAL_CODE, "qty": 1.0, "resources": _owned_labor_resources()}
    )
    summary = trace["summary"]
    ownership = summary["nr_sp_ownership"]

    assert ownership["catalog_status"] == "ambiguous"
    assert ownership["nr_source"] == "norm_card"
    assert ownership["sp_source"] == "norm_card"
    assert ownership["label"] == "nr_sp_without_basis"
    assert (ownership["nr_pct"], ownership["sp_pct"]) == (100.0, 40.0)
    assert (summary["nr_pct"], summary["sp_pct"]) == (100.0, 40.0)
    assert summary["total"] > 0.0
    assert summary["amount_status"] == "partial"
    assert summary["full_amount"] is None
    assert summary["completeness_reasons"] == ["nr_sp_without_basis"]
    assert [
        flag for flag in summary["flags"]
        if "НР/СП" in str(flag) and "карточк" in str(flag)
    ]


def test_accrual_rate_needs_a_rule_or_the_operator_and_both_close_the_position():
    """Both directions: a unique catalog rule and an explicit choice are owners."""
    from_catalog = build_position_trace(
        {"code": CATALOG_ACCRUAL_CODE, "qty": 1.0, "resources": _owned_labor_resources()}
    )
    by_operator = build_position_trace(
        {
            "code": CARD_ACCRUAL_CODE,
            "qty": 1.0,
            "nr_pct": 100,
            "sp_pct": 60,
            "resources": _owned_labor_resources(),
        }
    )

    assert by_operator["summary"]["nr_sp_ownership"]["nr_source"] == "explicit"
    for trace in (from_catalog, by_operator):
        summary = trace["summary"]
        assert summary["nr_sp_ownership"]["label"] == ""
        assert summary["completeness_reasons"] == []
        assert summary["amount_status"] == "complete"
        assert summary["full_amount"] == summary["total"]


def test_a_card_price_the_operator_is_asked_about_is_printed_as_a_sum():
    """The question names the number it wants confirmed, so it has to be readable.

    ``:g`` rendered a multi-million card price as ``1.23457e+06`` and dropped a
    kopeck off ``91385.06`` into ``91385.1`` (installed build 0.31.89, live case
    B0_camenka).  A figure the operator must confirm or replace cannot be an
    approximation of the one the document carries.
    """
    trace = {
        "sections": [
            {
                "positions": [
                    {
                        "code": CODE,
                        "name": "Устройство покрытий",
                        "rows": [
                            {
                                "name": "Материал из карточки",
                                "meta": {"price_action": "card_price_without_basis"},
                                "columns": {
                                    2: MATERIAL,
                                    3: "Материал из карточки",
                                    4: "т",
                                    7: 12.5,
                                    10: 1_234_567.89,
                                },
                            },
                            {
                                "name": "Мелкий ресурс",
                                "meta": {"price_action": "card_price_without_basis"},
                                "columns": {
                                    2: LABOR,
                                    3: "Мелкий ресурс",
                                    4: "ч",
                                    7: 1,
                                    10: 91385.06,
                                },
                            },
                        ],
                    }
                ]
            }
        ]
    }

    actions = [
        item["action"]
        for item in collect_lsr_price_gaps(trace)
        if item["price_action"] == "card_price_without_basis"
    ]

    assert len(actions) == 2
    assert not any("e+0" in action for action in actions)
    assert any("1 234 567,89 руб./т" in action for action in actions)
    assert any("91 385,06 руб./ч" in action for action in actions)

    # the header tells the same story as the question (§ 10: one set of sums)
    note = describe_lsr_card_prices(
        [
            {
                "kind": "material",
                "code": MATERIAL,
                "name": "Материал из карточки",
                "unit": "т",
                "price": 1_234_567.89,
                "locator": "ВОР!R9",
            }
        ]
    )
    assert "1 234 567,89 руб." in note
    assert "e+0" not in note


# ── § 8, § 11 № 8: a book price is a price for the unit the row states ────────

SOLVENT = "14.5.09.11-0102"
SOLVENT_RATE = 60.6


class _UnitBook:
    """Chosen ценовая база that answers with the whole row, unit included.

    ``PriceBook.lookup`` really returns the split-form record, so the fixture has
    to carry the unit too — the shape of this fixture is what hid the defect.
    """

    def __init__(self, rows: dict[str, dict[str, object]]) -> None:
        self._rows = dict(rows)
        self.region = "Санкт-Петербург"
        self.quarter = "2 квартал 2026 г."

    def lookup(self, code: str):
        return self._rows.get(str(code).strip())


def _solvent(unit: str, **overrides) -> dict[str, object]:
    resource = {
        "kind": "material",
        "code": SOLVENT,
        "name": "Уайт-спирит",
        "unit": unit,
        "per_unit": 1.0,
    }
    resource.update(overrides)
    return resource


def _book(*, unit: str, price: float = SOLVENT_RATE) -> _UnitBook:
    return _UnitBook({SOLVENT: {"price_current": price, "price_current_eff": price, "unit": unit}})


def _one_material(book, resource: dict[str, object]) -> dict[str, object]:
    return build_position_trace(_position(resources=[resource]), pricebook=book)


def test_a_book_row_that_prices_the_cipher_in_another_unit_prices_nothing():
    """Reading the шифр is not reading the unit it costs (§ 8, § 11 № 8).

    On the installed build the book was consulted by шифр alone and the row's own
    unit was never compared with the resource's
    (``stage_b/live_818/markup_price_path.json`` reads exactly like that).  The
    base at hand carried no disagreeing row — 135 rows read, 0 of them naming
    another unit (``stage_b/live_818/book_unit_gap.json``) — so this test fixes
    the rule rather than one repaired example.
    """
    trace = _one_material(_book(unit="кг"), _solvent("л"))
    row = _resource_rows(trace)[SOLVENT]
    summary = trace["summary"]

    assert row["source"] == BOOK_UNIT_CONFLICT_ACTION
    assert row["meta"]["price_action"] == BOOK_UNIT_CONFLICT_ACTION
    assert row["meta"]["price_book_unit"] == "кг"
    # No money, and no zero either: the check itself is the result.  An applied
    # price always writes графа 10, so a missing key is the absence of a number.
    assert row["columns"].get("10") is None
    assert row["columns"].get("12") is None
    assert summary["total"] == pytest.approx(0.0)
    assert summary["amount_status"] != "complete"
    assert summary["full_amount"] is None
    assert summary["completeness_reasons"] == [f"price_missing:{SOLVENT}"]
    notes = [str(flag) for flag in summary["flags"]]
    assert any("кг" in flag and "л" in flag and "не применена" in flag for flag in notes)
    # and the operator is not sent to look for a price the book already carries
    assert not any("нужен КАЦ" in flag for flag in notes)


def test_the_question_asks_about_the_unit_the_position_counts_in():
    """§ 7 / § 10: the gap list and the readiness card ask the same question."""
    book = _book(unit="кг")
    position = _one_material(book, _solvent("л"))
    gaps = collect_lsr_price_gaps(
        {"sections": [{"positions": [position]}]},
        pricebook=book,
        pricebook_name="sankt-peterburg_2kv2026",
    )

    assert len(gaps) == 1
    gap = gaps[0]
    assert gap["price_action"] == BOOK_UNIT_CONFLICT_ACTION
    assert gap["unit"] == "л"
    assert gap["code"] == SOLVENT
    assert gap["position_code"] == CODE
    assert "«кг»" in gap["action"] and "«л»" in gap["action"]
    assert "Подтвердите единицу" in gap["action"]
    assert "Отсутствие цены не отменяет норму" in gap["action"]
    assert "Санкт-Петербург" in gap["action"]
    # the required source names the unit, not a price the book already has
    assert gap["required_source"] == "цена за единицу ресурса в позиции"


def test_the_same_unit_or_a_row_without_a_unit_prices_exactly_as_before():
    """The guard must not invent holes: an equal unit and an unstated one are usable."""
    for book_unit in ("л", "л.", "1 л", ""):
        trace = _one_material(_book(unit=book_unit), _solvent("л"))
        row = _resource_rows(trace)[SOLVENT]
        summary = trace["summary"]

        assert row["source"] == "fgis_current", book_unit
        assert row["meta"]["price_action"] == "", book_unit
        assert row["columns"]["10"] == pytest.approx(SOLVENT_RATE), book_unit
        assert summary["completeness_reasons"] == [], book_unit
        assert summary["full_amount"] == pytest.approx(SOLVENT_RATE), book_unit
        assert not [flag for flag in summary["flags"] if "не применена" in str(flag)]


def test_a_norm_factor_unit_next_to_its_plain_form_is_a_question_not_a_product():
    """§ 8 converts with a formula written into the trace; a ×100 guess is not one."""
    trace = _one_material(_book(unit="100 м3"), _solvent("м3"))
    row = _resource_rows(trace)[SOLVENT]
    summary = trace["summary"]

    assert row["meta"]["price_action"] == BOOK_UNIT_CONFLICT_ACTION
    assert row["meta"]["price_book_unit"] == "100 м3"
    assert summary["total"] == pytest.approx(0.0)
    assert summary["full_amount"] is None


def test_a_rejected_book_row_does_not_delete_the_money_the_card_already_had():
    """§ 7 ladder: the book is skipped, so a card rate still shows — labelled."""
    trace = _one_material(_book(unit="кг"), _solvent("л", price=91.5))
    row = _resource_rows(trace)[SOLVENT]
    summary = trace["summary"]
    notes = [str(flag) for flag in summary["flags"]]

    assert row["source"] == "card_price"
    assert row["meta"]["price_action"] == "card_price_without_basis"
    assert row["meta"]["price_book_unit"] == "кг"
    assert summary["total"] == pytest.approx(91.5)
    assert summary["full_amount"] is None
    assert any("карточк" in flag for flag in notes)
    assert any("не применена" in flag for flag in notes)


def test_both_lsr_engines_refuse_the_same_book_row():
    """§ 10: one rule, or one document hands out two sums.

    The legacy assembly engine serves ``/api/lsr`` and the MCP tool while the РИМ
    trace serves the workbook, and both read the same ценовую базу.
    """
    resource = {
        "kind": "material",
        "code": SOLVENT,
        "name": "Уайт-спирит",
        "unit": "л",
        "qty": 1.0,
    }

    assert _rejected_book_unit(resource, _book(unit="кг")) == "кг"
    assert _resource_price(resource, _book(unit="кг"), {}) == (None, "missing")
    assert _rejected_book_unit(resource, _book(unit="л")) == ""
    assert _resource_price(resource, _book(unit="л"), {}) == (SOLVENT_RATE, "fgis")
    # an explicit rate never reaches the book, so there is nothing to reconcile
    assert _rejected_book_unit({**resource, "price": 1.0}, _book(unit="кг")) == ""
    # and the rule itself has exactly one implementation
    from proxy.services import lsr_assembly_service

    assert lsr_assembly_service.book_price_unit_conflict is (
        rim_lsr_trace_service.book_price_unit_conflict
    )


def test_the_legacy_engine_asks_about_the_unit_instead_of_a_price_it_already_has():
    """``/api/lsr`` names a missing КАЦ only when nothing was found at all.

    A refused book row is a different hole: the base has the number, states it in
    another unit, and the position has to say which of the two the operator owes
    (§ 7: a gap is shown as it is; § 11 № 8: units are not silently swapped).
    """
    position = {
        "code": CODE,
        "qty": 1.0,
        "resources": [
            {"kind": "material", "code": SOLVENT, "name": "Уайт-спирит", "unit": "л", "qty": 1.0}
        ],
    }

    refused = compute_position(dict(position), pricebook=_book(unit="кг"))
    priced = refused["resources"][0]
    notes = [str(flag) for flag in refused["flags"]]

    assert priced["price_used"] is None
    assert priced["price_action"] == BOOK_UNIT_CONFLICT_ACTION
    assert any("кг" in flag and "л" in flag and "не применена" in flag for flag in notes)
    assert not any("нужен КАЦ" in flag for flag in notes)
    assert refused["base"]["mat"] == pytest.approx(0.0)

    # a row stating the same unit prices exactly as it did before the rule existed
    matched = compute_position(dict(position), pricebook=_book(unit="л"))
    assert matched["resources"][0]["price_source"] == "fgis"
    assert matched["base"]["mat"] == pytest.approx(SOLVENT_RATE)
