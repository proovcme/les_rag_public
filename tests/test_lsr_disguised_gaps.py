"""Task § 11: results that look finished but are not, measured on the real path.

Each test below reproduces one of the deceptions the acceptance list names, on
the same services the customer's chat uses:

* № 6 a known price must not hide a missing work, rate, НР or СП;
* № 7 a specification must not turn into mounting operations, and one item must
  not be paid twice under two supply roles;
* № 8 «демонтаж» must not be delivered as «монтаж», and pieces must not be
  rescaled into the norm's unit.

The recurring shape of the defect is the same: an amount existed, a status said
"bound", and nothing in the document said which professional question is still
open.  These tests fail if the question disappears again.

№ 9 (the artifact survives a restart and a repeat does not duplicate it) is
detected in ``test_packaging_recovery_service.py`` and in
``test_workbook_tool_service.py``
(``test_retry_returns_completed_revision_without_running_adapter_twice``,
``test_parent_revision_creates_correction_without_overwriting_first``).
"""

from __future__ import annotations

import pytest

from tests.lsr_citation_support import cited, cited_snapshot, issued_norm_metadata

from proxy.services import gesn_service
from proxy.services.lsr_result_readiness_service import (
    build_lsr_result_readiness,
    format_lsr_readiness_notice,
)
from proxy.services.lsr_workbook_adapter_service import (
    collect_lsr_action_conflicts,
    collect_lsr_price_gaps,
    collect_lsr_workbook_gaps,
)
from proxy.services.rim_lsr_trace_service import (
    build_lsr_trace,
    build_lsr_trace_from_visible_rows,
    build_position_trace,
    norm_action_conflict,
)

DEMONTADE_NORM = "ГЭСНм11-04-028-01"


class _Book:
    """A ценовая база the operator chose: exact lookup by resource code."""

    def __init__(self, prices: dict[str, float]) -> None:
        self._prices = dict(prices)
        self.region = "Санкт-Петербург"
        self.quarter = "2 квартал 2026"

    def lookup(self, code: str):
        price = self._prices.get(str(code).strip())
        return None if price is None else {"price_current": price}


def _legacy_demontade_card(**overrides) -> dict[str, object]:
    """``DEMONTADE_NORM`` as a card that writes its own numbers.

    A card from the canonical base (data/smeta_base/les_smeta_base.sqlite) states the
    composition and nothing else: this card's own labour row is «Средний разряд работы
    3,8» (1-100-38) at 0,22 чел.-ч, it carries no price and no ``nr_pct``/``sp_pct``, and
    the catalog of ГЭСНм:11 holds two rules so it resolves nothing.  The rate and the two
    accrual percentages below are therefore numbers this test writes onto the card — round
    and its own, not the money of any region's ценовая база and not the excluded demo
    seed's, which production no longer merges into the read path.  Serving them as explicit
    card data is what keeps both defect guards below about ownership rather than about a
    missing card.

    The name is the installing wording this test needs for the reversal half of the first
    guard below; the second guard passes the base card's own name
    («Включение в аппаратуру разъемов штепсельных…»), which names no action at all and so
    leaves the accrual question the only open one.
    """
    card = {
        "code": DEMONTADE_NORM,
        "name": "Монтаж розеток, патч-панелей и штепсельных разъемов",
        "unit": "шт",
        "nr_pct": 109,
        "sp_pct": 57,
        "resources": [
            {
                "kind": "labor",
                "code": "1-100-38",
                "name": "Средний разряд работы 3,8",
                "unit": "чел.-ч",
                "per_unit": 0.22,
                "price": 500.0,
            }
        ],
    }
    card.update(overrides)
    return card


def _install_card(monkeypatch, card: dict[str, object]) -> None:
    """Serve ``card`` for its own шифр, keep the canonical base for every other code."""
    real_get_norm = gesn_service.get_norm
    card = dict(card, _source_sha256=issued_norm_metadata(card, synthetic=True)["normative_base_sha256"])

    def _get_norm(code, *args, **kwargs):
        if str(code or "").strip() == str(card["code"]):
            if kwargs.get("expected_base_sha256"):
                assert kwargs["expected_base_sha256"] == card["_source_sha256"]
            return dict(card)
        return real_get_norm(code, *args, **kwargs)

    monkeypatch.setattr(gesn_service, "get_norm", _get_norm)


#: The unpatched reader, taken at import time before any test can stub it.
_CANONICAL_GET_NORM = gesn_service.get_norm


def _use_canonical_base(monkeypatch) -> None:
    """Put the verified norm base back on the read path after `_install_card`.

    Both halves of the НР/СП rule are pinned below, and which one the product prints
    depends only on what the read card states: percentages of its own
    (``nr_sp_without_basis``) or nothing at all, which is every canonical base card
    (``nr_sp_unresolved``).  A stub left installed would hide the second spelling.
    """

    monkeypatch.setattr(gesn_service, "get_norm", _CANONICAL_GET_NORM)


def _gap_kinds(readiness: dict, dimension: str) -> list[str]:
    return [
        str(gap.get("kind") or "")
        for gap in (readiness.get("dimensions") or {}).get(dimension, {}).get("gaps") or []
    ]


def _dismantling_row(**overrides) -> dict[str, object]:
    row = {
        "source_row": "ВОР!R5",
        "row_role": "work",
        "title": "Демонтаж розетки",
        "basis": "ГЭСНм 11-04-028-01",
        "norm_code": DEMONTADE_NORM,
        "quantity": 10,
        "unit": "шт",
        "norm_status": "EXACT",
    }
    row.update(overrides)
    # «EXACT» is the model's claim; the record of the card it cited is what
    # readiness and the money gate accept as its basis (§ 3).
    return cited_snapshot(row)


def test_the_reversal_is_read_from_the_two_texts_that_are_already_in_the_row():
    """The check names opposite words; it never rewrites a cipher."""
    card = {"name": "Монтаж розеток, патч-панелей и штепсельных разъемов"}

    conflict = norm_action_conflict("Демонтаж розетки", card)

    assert (conflict["row_action"], conflict["norm_action"]) == ("демонтаж", "монтаж")
    assert "код норму не подменяет" in conflict["message"]
    # both directions of the same pair are the same contradiction
    assert norm_action_conflict("Монтаж розетки", {"name": "Демонтаж розеток"})
    # agreement, silence and ambiguity name nothing at all
    assert norm_action_conflict("Монтаж розетки", card) == {}
    assert norm_action_conflict("Розетка", card) == {}
    assert norm_action_conflict("Установка и демонтаж розетки", card) == {}
    assert norm_action_conflict("Демонтаж розетки", None) == {}


def test_a_dismantling_row_priced_by_an_installing_norm_stays_an_open_question(monkeypatch):
    """§ 11 № 8: the money is shown, the applicability claim is not."""
    # the chosen card names «монтаж» and prices its own labour row — both of those are
    # card data now (`_legacy_demontade_card()` above); the row's own words stay the real
    # half of the contradiction
    _install_card(monkeypatch, _legacy_demontade_card())
    lsr = build_lsr_trace_from_visible_rows([_dismantling_row()])
    binding = lsr["row_bindings"][0]
    summary = lsr["summary"]

    assert binding["status"] == "bound"
    assert binding["action_conflict"]["norm_action"] == "монтаж"
    assert binding["readiness"]["applicability_substantiated"] is False
    assert binding["readiness"]["norm_applicability_ok"] is False
    # the amount stays visible, and it is preliminary money.  2 926,00 = the card's own
    # 0,22 чел.-ч × 10 шт × its own 500,00 руб./чел.-ч = 1 100,00 прямые, plus НР 109 %
    # and СП 57 % of that ФОТ (1 199,00 + 627,00) — the two percentages the same card
    # prints, because the accrual catalog (config/domain/nr_sp_catalog.json) holds two
    # rules for ГЭСНм:11 and the fail-closed catalog refuses to choose between them.
    assert summary["total"] == pytest.approx(2926.0)
    assert summary["confirmed_amount"] == pytest.approx(0.0)
    assert summary["preliminary_amount"] == pytest.approx(2926.0)
    assert summary["result_status"] == "priced_partial"
    assert [
        flag for flag in summary["flags"] if "противоречие операции" in str(flag)
    ]
    conflicts = collect_lsr_action_conflicts(lsr)
    assert [item["locator"] for item in conflicts] == ["ВОР!R5"]

    readiness = build_lsr_result_readiness(
        packaged=True,
        rows=[_dismantling_row()],
        missing=[],
        pricing_status=summary["result_status"],
        norm_conflicts=conflicts,
        # § 4: the count is read off the revision's own projection.
        row_projection=lsr["row_projection"],
        calculated_positions=1,
        confirmed_amount=summary["confirmed_amount"],
        preliminary_amount=summary["preliminary_amount"],
    )
    assert "reversed_action" in _gap_kinds(readiness, "norms")
    notice = format_lsr_readiness_notice(readiness, filename="LSR.xlsx")
    assert "демонтаж" in notice and "монтаж" in notice and "ВОР!R5" in notice
    assert readiness["dimensions"]["prices"]["complete"] is False


def test_a_row_naming_both_actions_is_not_read_as_a_contradiction():
    """A row naming both actions is ambiguous, and ambiguity is not a conflict."""
    lsr = build_lsr_trace_from_visible_rows(
        [_dismantling_row(title="Установка и демонтаж розетки")]
    )
    binding = lsr["row_bindings"][0]

    assert "action_conflict" not in binding
    assert binding["readiness"]["applicability_substantiated"] is True
    assert collect_lsr_action_conflicts(lsr) == []


def test_a_volume_in_pieces_is_not_rescaled_into_the_norm_unit():
    """§ 8 / § 11 № 8: шт → 100 м² needs an authored factor, never a guess."""
    rows = [
        _dismantling_row(title="Устройство обрешетки", basis="ГЭСН 12-01-034-02",
                         norm_code="ГЭСН12-01-034-02", unit="шт")
    ]
    lsr = build_lsr_trace_from_visible_rows(rows)
    binding = lsr["row_bindings"][0]

    assert binding["status"] == "needs_input"
    assert binding["quantity_trace"]["status"] == "needs_input"
    assert "conversion_factor" in binding["quantity_trace"]["message"]
    assert binding["readiness"]["volume_verified"] is False
    assert lsr["summary"]["calculated_positions"] == 0
    assert lsr["summary"]["confirmed_amount"] == pytest.approx(0.0)

    # the readiness card keeps the row open and says why in the operator's own
    # terms: no internal status token, and no instruction to "close the norms"
    # in a document whose norms dimension is already reported as complete (§ 10)
    missing = collect_lsr_workbook_gaps(lsr)
    readiness = build_lsr_result_readiness(
        packaged=True,
        rows=rows,
        missing=missing,
        pricing_status=lsr["summary"]["result_status"],
        # § 4: the count is read off the revision's own projection.
        row_projection=lsr["row_projection"],
        calculated_positions=0,
    )
    notice = format_lsr_readiness_notice(readiness, filename="LSR.xlsx")

    assert readiness["estimate_complete"] is False
    assert readiness["gap_states"]["calculation_incomplete"]["count"] == 1
    assert readiness["dimensions"]["norms"]["complete"] is True
    assert readiness["dimensions"]["prices"]["complete"] is False
    assert "ВОР!R5" in notice and "пересчёт" in notice
    assert "needs_input" not in notice
    assert "закройте нормы" not in notice


def test_a_confirmed_material_price_does_not_hide_a_missing_work_norm():
    """§ 11 № 6: real money on one row cannot close another row's question."""
    rows = [
        {
            "source_row": "СКС!R8",
            "row_role": "work",
            "title": "Монтаж лотка лестничного",
            "quantity": 120,
            "unit": "м",
            "norm_status": "NEEDS_RESEARCH",
        },
        {
            "source_row": "СКС!R8",
            "row_role": "material",
            "title": "Лоток лестничный 300х100",
            "quantity": 120,
            "unit": "м",
            "work_row": "СКС!R8",
        },
    ]
    lsr = build_lsr_trace_from_visible_rows(
        rows,
        confirmed_data={
            "СКС!R8": {
                "row_role": "material",
                "confirmed_price": 100.0,
                "price_source": "договорная цена 15.09.2026",
            }
        },
    )
    summary = lsr["summary"]
    by_role = {str(b.get("row_role")): b for b in lsr["row_bindings"]}

    # the operator's price is honoured ...
    assert summary["confirmed_amount"] == pytest.approx(12000.0)
    # ... and the work row is still open, in the sums and in the words
    assert summary["result_status"] == "priced_partial"
    assert any("NEEDS_RESEARCH" in str(flag) for flag in summary["flags"])
    assert by_role["work"]["readiness"]["norm_selected"] is False
    assert by_role["work"]["readiness"]["position_calculated"] is False
    assert by_role["material"]["readiness"]["prices_provided"] is True

    readiness = build_lsr_result_readiness(
        packaged=True,
        rows=rows,
        missing=[],
        pricing_status=summary["result_status"],
        # § 4: the count is read off the revision's own projection.
        row_projection=lsr["row_projection"],
        calculated_positions=summary["calculated_positions"],
        confirmed_amount=summary["confirmed_amount"],
        preliminary_amount=summary["preliminary_amount"],
    )
    assert "needs_research" in _gap_kinds(readiness, "norms")
    assert readiness["dimensions"]["norms"]["complete"] is False
    assert readiness["dimensions"]["coverage"]["complete"] is True


def test_a_specification_without_operations_asks_for_the_operation_layer():
    """§ 5 / § 11 № 7: supply lines never invent a mounting norm."""
    rows = [
        {"source_row": "СКС!R3", "row_role": "material", "title": "Кабель ВВГнг 3х2,5",
         "quantity": 300, "unit": "м"},
        {"source_row": "СКС!R4", "row_role": "material", "title": "Саморез 4,8х16",
         "quantity": 120, "unit": "шт"},
    ]
    lsr = build_lsr_trace_from_visible_rows(rows)
    summary = lsr["summary"]

    assert summary["kind_counts"]["material"] == 2
    assert summary["kind_counts"]["work"] == 0
    assert summary["selected_norms"] == 0
    assert summary["selected_norm_ciphers"] == 0
    assert all(binding.get("code") in (None, "") for binding in lsr["row_bindings"])
    assert all(
        binding["readiness"]["norm_selected"] is not True
        for binding in lsr["row_bindings"]
    )

    readiness = build_lsr_result_readiness(
        packaged=True,
        rows=rows,
        missing=[],
        pricing_status=summary["result_status"],
        catalog_work_count=2,
        catalog_locators=["СКС!R3", "СКС!R4"],
        # § 4: the count is read off the revision's own projection.
        row_projection=lsr["row_projection"],
        calculated_positions=summary["calculated_positions"],
    )
    assert "missing_work_layer" in _gap_kinds(readiness, "norms")


def test_one_item_in_two_supply_roles_is_named_and_not_paid_twice():
    """§ 11 № 7: a conflict between roles is shown, never resolved by a guess."""
    rows = [
        {"source_row": "СКС!R9", "row_role": "material", "title": "Саморез 4,8х16",
         "quantity": 40, "unit": "шт", "work_row": "СКС!R8"},
        {"source_row": "СКС!R9", "row_role": "equipment", "title": "Саморез 4,8х16",
         "quantity": 40, "unit": "шт", "work_row": "СКС!R8"},
    ]
    lsr = build_lsr_trace_from_visible_rows(rows)
    summary = lsr["summary"]

    assert summary["confirmed_amount"] == pytest.approx(0.0)
    assert any("двойной учёт" in str(flag) for flag in summary["flags"])
    assert all(
        binding["readiness"]["conflicts_ok"] is False
        for binding in lsr["row_bindings"]
    )
    assert all(
        binding["readiness"]["double_count_conflict"] is True
        for binding in lsr["row_bindings"]
    )


def test_a_confirmation_addressed_to_a_row_prices_only_the_row_it_names():
    """§ 10: one locator, two operations - an unaddressed price stays ambiguous."""
    rows = [
        {"source_row": "СКС!R9", "row_role": "material", "title": "Лоток 300",
         "quantity": 10, "unit": "м", "work_row": "СКС!R8", "operation_id": "lotok"},
        {"source_row": "СКС!R9", "row_role": "equipment", "title": "Лоток 300",
         "quantity": 10, "unit": "м", "work_row": "СКС!R8", "operation_id": "lotok2"},
    ]
    lsr = build_lsr_trace_from_visible_rows(
        rows, confirmed_data={"СКС!R9": {"confirmed_price": 50.0}}
    )

    assert all(
        binding["readiness"]["conflicts_ok"] is False for binding in lsr["row_bindings"]
    )
    assert lsr["summary"]["confirmed_amount"] == pytest.approx(0.0)


def test_a_priced_labour_class_does_not_hide_the_missing_machinist_rate():
    """§ 7 / § 11 № 6: one class of rate answered is not the position answered."""
    trace = build_position_trace(
        {
            "code": DEMONTADE_NORM,
            "name": "Монтаж розетки",
            "qty": 1.0,
            "nr_pct": 0,
            "sp_pct": 0,
            "resources": [
                {"kind": "labor", "code": "1-100-36", "name": "ОТ рабочая",
                 "unit": "чел.-ч", "per_unit": 1.0, "price": 500.0},
                {"kind": "machinist", "code": "2-200-01", "name": "ОТм машинист",
                 "unit": "чел.-ч", "per_unit": 1.0},
            ],
        },
        pricebook=_Book({"1-100-36": 500.0}),
    )
    summary = trace["summary"]

    assert [flag for flag in summary["flags"] if "ЗПМ" in str(flag)]
    assert summary["completeness_reasons"] == ["price_missing:2-200-01"]
    assert summary["amount_status"] == "partial"
    assert summary["full_amount"] is None


def _owned_price_position(**overrides) -> dict[str, object]:
    """A position in which every resource price already has an owner.

    Nothing is missing except the owner of НР/СП, so a document built from it
    tests the readiness card and the chat notice rather than the position trace:
    § 11 № 6 has to hold where the customer reads it, not only inside the sum.
    """
    position = {
        "code": DEMONTADE_NORM,
        "name": "Монтаж розетки",
        "unit": "шт",
        "qty": 10,
        "resources": [
            {"kind": "labor", "code": "1-100-36", "name": "ОТ электромонтажник",
             "unit": "чел.-ч", "per_unit": 4.5, "price": 150.0,
             "price_confirmed": True,
             "price_source_ref": "протокол совещания 12.09.2026"},
            {"kind": "material", "code": "101-0103", "name": "Розетка",
             "unit": "шт", "per_unit": 1.0, "price": 200.0,
             "price_confirmed": True,
             "price_source_ref": "договорная цена 15.09.2026"},
        ],
    }
    position.update(overrides)
    return position


def _row_for(position: dict[str, object], *, locator: str = "ВОР!R5") -> dict[str, object]:
    """The authored ВОР row behind a position: a real cipher, EXACT, own units."""
    return cited({
        "source_row": locator,
        "row_role": "work",
        "title": str(position.get("name") or ""),
        "basis": str(position.get("code") or ""),
        "norm_code": str(position.get("code") or ""),
        "quantity": position.get("qty"),
        "unit": str(position.get("unit") or ""),
        "norm_status": "EXACT",
    })


def test_owned_resource_prices_do_not_close_a_position_without_an_accrual_owner(monkeypatch):
    """§ 11 № 6: the document asks about НР/СП even when no price is missing.

    ГЭСНм:11 carries two catalog rules, so the fail-closed catalog refuses to
    pick one and the percentages printed in the norm card are applied without an
    owner.  The money is real and stays visible; what must disappear is the claim
    that the estimate is complete.

    The same question is pinned twice, because the product spells it two ways: a card
    that states percentages («nr_sp_without_basis») and a card of the verified base,
    which states none («nr_sp_unresolved»).  Both leave the position open; only the
    second is what the installed base gives today.
    """
    # the card prints 109 % / 57 % as its own accrual rates (a base card prints none);
    # the name here is the base card's own, so nothing but the accrual owner is open.
    # The ambiguity itself is real base-catalog data, not a stub.
    _install_card(
        monkeypatch,
        _legacy_demontade_card(
            name="Включение в аппаратуру разъемов штепсельных, "
            "количество контактов в разъеме: до 14 шт."
        ),
    )
    lsr = build_lsr_trace([_owned_price_position()])
    summary = lsr["summary"]
    gaps = collect_lsr_price_gaps(lsr)

    # every resource has an owner, so the accrual rate is the only open question
    assert [gap["price_action"] for gap in gaps] == ["nr_sp_without_basis"]
    assert gaps[0]["resource"] == f"НР и СП ({DEMONTADE_NORM})"
    assert gaps[0]["required_source"].startswith("нормативное основание")
    assert summary["total"] > 0.0
    assert summary["amount_status"] == "partial"
    assert summary["full_amount"] is None

    rows = [_row_for(_owned_price_position())]
    readiness = build_lsr_result_readiness(
        packaged=True,
        rows=rows,
        missing=[],
        pricing_status=summary["result_status"],
        price_gaps=gaps,
        calculated_positions=1,
        confirmed_amount=summary["total"],
        preliminary_amount=0.0,
    )
    dimensions = readiness["dimensions"]
    # the two dimensions that really are closed stay closed
    assert dimensions["coverage"]["complete"] is True
    assert dimensions["norms"]["complete"] is True
    assert dimensions["file"]["status"] == "ready"
    # and the document is not announced as a finished estimate
    assert dimensions["prices"]["complete"] is False
    assert readiness["estimate_complete"] is False
    notice = format_lsr_readiness_notice(readiness, filename="LSR.xlsx")
    assert "НР (109 %) и СП (57 %)" in notice
    assert "из карточки нормы" in notice and "черновиком" in notice
    assert DEMONTADE_NORM in notice

    # a repeated cipher asks the same question once: a 300-line ВОР of one
    # operation must not bury the operator under 300 identical lines
    twice = build_lsr_trace([
        _owned_price_position(source_row="ВОР!R5"),
        _owned_price_position(source_row="ВОР!R6"),
    ])
    repeated = build_lsr_result_readiness(
        packaged=True,
        rows=[
            _row_for(_owned_price_position(), locator="ВОР!R5"),
            _row_for(_owned_price_position(), locator="ВОР!R6"),
        ],
        missing=[],
        pricing_status=twice["summary"]["result_status"],
        price_gaps=collect_lsr_price_gaps(twice),
        calculated_positions=2,
    )
    assert len(collect_lsr_price_gaps(twice)) == 2
    assert repeated["dimensions"]["prices"]["gap_count"] == 1
    assert repeated["estimate_complete"] is False

    # The production shape of the same hole: a card of the verified base prints no НР/СП
    # at all, so nothing is "taken off the card without basis" — the accrual is simply
    # unresolved, the catalog of ГЭСНм:11 keeps two rules and refuses to pick one, and the
    # document still asks.  Same fixture, same money, other spelling of the same question.
    _use_canonical_base(monkeypatch)
    real = build_lsr_trace([_owned_price_position()])
    real_summary = real["summary"]
    real_gaps = collect_lsr_price_gaps(real)

    assert [gap["price_action"] for gap in real_gaps] == ["nr_sp_unresolved"]
    assert real_gaps[0]["resource"] == f"НР и СП ({DEMONTADE_NORM})"
    assert real_gaps[0]["required_source"].startswith("нормативное основание")
    assert real["sections"][0]["positions"][0]["summary"]["nr_sp_ownership"] == {
        "label": "nr_sp_unresolved",
        "nr_pct": None,
        "sp_pct": None,
        "nr_source": "",
        "sp_source": "",
        "catalog_status": "ambiguous",
        "basis": "",
        "rule_id": "",
    }
    assert real_summary["total"] > 0.0
    assert real_summary["amount_status"] == "partial"
    assert real_summary["full_amount"] is None

    real_readiness = build_lsr_result_readiness(
        packaged=True,
        rows=rows,
        missing=[],
        pricing_status=real_summary["result_status"],
        price_gaps=real_gaps,
        calculated_positions=1,
        confirmed_amount=real_summary["total"],
        preliminary_amount=0.0,
    )
    # the same dimensions answer the same way, and the notice names the hole in the
    # words the product really prints for an unresolved accrual
    assert real_readiness["dimensions"]["coverage"]["complete"] is True
    assert real_readiness["dimensions"]["norms"]["complete"] is True
    assert real_readiness["dimensions"]["prices"]["complete"] is False
    assert real_readiness["estimate_complete"] is False
    real_notice = format_lsr_readiness_notice(real_readiness, filename="LSR.xlsx")
    assert "начисления НР (нет) и СП (нет) не определены" in real_notice
    assert "нормативное основание не выбрано, в карточке нормы ставки нет" in real_notice
    assert "Подходящих правил в каталоге: 2 — нужно одно" in real_notice
    assert "Расчёт без НР и СП не становится полной сметой" in real_notice
    assert DEMONTADE_NORM in real_notice
    assert "109 %" not in real_notice


def test_an_explicit_accrual_choice_closes_the_same_document():
    """The second direction: the operator's own rates own the number.

    Without this half the first test would only prove that the readiness card can
    block forever.  An explicit НР/СП is a decision with an owner, so the same
    resources and the same cipher produce a complete estimate.
    """
    position = _owned_price_position(nr_pct=100, sp_pct=60)
    lsr = build_lsr_trace([position])
    summary = lsr["summary"]

    assert collect_lsr_price_gaps(lsr) == []
    assert summary["flags"] == []
    assert summary["result_status"] == "priced_final"
    assert summary["full_amount"] == summary["total"]

    readiness = build_lsr_result_readiness(
        packaged=True,
        rows=[_row_for(position)],
        missing=[],
        pricing_status=summary["result_status"],
        price_gaps=[],
        calculated_positions=1,
        confirmed_amount=summary["total"],
        preliminary_amount=0.0,
    )
    assert readiness["dimensions"]["prices"]["complete"] is True
    assert readiness["estimate_complete"] is True
    assert format_lsr_readiness_notice(readiness, filename="LSR.xlsx").startswith(
        "ЛСР собрана."
    )
