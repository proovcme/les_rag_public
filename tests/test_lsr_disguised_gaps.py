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

from tests.lsr_citation_support import cited

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
    return cited(row)


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


def test_a_dismantling_row_priced_by_an_installing_norm_stays_an_open_question():
    """§ 11 № 8: the money is shown, the applicability claim is not."""
    lsr = build_lsr_trace_from_visible_rows([_dismantling_row()])
    binding = lsr["row_bindings"][0]
    summary = lsr["summary"]

    assert binding["status"] == "bound"
    assert binding["action_conflict"]["norm_action"] == "монтаж"
    assert binding["readiness"]["applicability_substantiated"] is False
    assert binding["readiness"]["norm_applicability_ok"] is False
    # the amount stays visible, and it is preliminary money
    assert summary["total"] == pytest.approx(5985.0)
    assert summary["confirmed_amount"] == pytest.approx(0.0)
    assert summary["preliminary_amount"] == pytest.approx(5985.0)
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


def test_owned_resource_prices_do_not_close_a_position_without_an_accrual_owner():
    """§ 11 № 6: the document asks about НР/СП even when no price is missing.

    ГЭСНм:11 carries two catalog rules, so the fail-closed catalog refuses to
    pick one and the percentages printed in the norm card are applied without an
    owner.  The money is real and stays visible; what must disappear is the claim
    that the estimate is complete.
    """
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
