# -*- coding: utf-8
"""Task 2026-09-29 § 4: one revision projection is the source of truth.

The § 4 contract is that the counters, the chat card and the delivered file answer the
same seven questions for the same operation, from one per-operation projection:

* the projection exists for every row the revision bound, keyed by the stable operation
  id the revision already carries;
* «сколько работ не рассчитано» is read off it — never by subtracting
  ``calculated_positions`` (which counts supply lines too) from the number of works;
* a row that has no such question (a heading, a resource line) answers «н/п» instead of
  the «нет» that would count it as an unfinished calculation;
* the payload is not cut at 80 rows, because a truncated list reads as completeness;
* the «Проверка» sheet fills its columns from the trace's own decisions and prints the
  open questions in its remarks block instead of leaving that section empty.
"""
from __future__ import annotations

import pytest
from openpyxl import load_workbook

from proxy.services import gesn_service
from proxy.services.lsr_result_readiness_service import build_lsr_result_readiness
from proxy.services.rim_lsr_trace_service import (
    OPERATION_QUESTIONS,
    OPERATION_READINESS_FIELDS,
    build_lsr_trace_from_visible_rows,
)
from proxy.services.rim_trace_xlsx_service import render_lsr_xlsx

HEADER_ROW = {"source_row": "ВОР!R1", "row_role": "header", "title": "Раздел 1"}
WORK_ROW = {
    "source_row": "ВОР!R2",
    "row_role": "work",
    "basis": "ГЭСН 12-01-034-02",
    "title": "Устройство обрешетки",
    "quantity": "61",
    "unit": "м2",
    "norm_status": "EXACT",
}
SUPPLY_ROW = {
    "source_row": "ВОР!R3",
    "row_role": "material",
    "work_row": "ВОР!R2",
    "title": "Лоток лестничный",
    "quantity": 30,
    "unit": "м.п",
}

WORK_CODE = "ГЭСН12-01-034-02"  # the cipher WORK_ROW cites, once the prefix is folded


def _legacy_card() -> dict[str, object]:
    """The card of ``WORK_CODE`` as a legacy card writes it: every row states its rate.

    The canonical base card of this cipher holds the consumptions, units and шифры below —
    they are its own rows — and no price at all (measured 0 of 63 673 labour rows in
    data/smeta_base/les_smeta_base.sqlite write one, and the machine and material rows
    carry none).  A position built from it therefore has nothing but holes, while this
    test is about the columns that state the *price decision* per resource.  The rates are
    round numbers this test writes for itself and the card is served to the calculator as
    explicit data, because the excluded demo seed (config/domain/gesn_seed.yaml) no longer
    reaches the read path on any production route.
    """
    return {
        "code": WORK_CODE,
        "name": "Устройство обрешетки с прозорами из брусков",  # the base card's own name
        "unit": "100 м2",  # the base card's own unit: 61 м2 of ВОР is 0,61 of it
        "resources": [
            {"kind": "labor", "code": "1-100-25", "name": "Средний разряд работы 2.5",
             "unit": "чел.-ч", "per_unit": 12.94, "price": 480.00},
            {"kind": "machine", "code": "91.05.01-017", "name": "Краны башенные, г/п 8 т",
             "unit": "маш.-ч", "per_unit": 0.97, "price": 900.00},
            {"kind": "machinist", "code": "", "name": "ОТм краны 8 т, разряд 6",
             "unit": "маш.-ч", "per_unit": 0.97, "price": 800.00},
            {"kind": "machine", "code": "91.05.05-015",
             "name": "Краны на автомобильном ходу, 16 т",
             "unit": "маш.-ч", "per_unit": 0.01, "price": 1700.00},
            {"kind": "machinist", "code": "", "name": "ОТм краны 16 т, разряд 6",
             "unit": "маш.-ч", "per_unit": 0.01, "price": 800.00},
            {"kind": "machine", "code": "91.14.02-001",
             "name": "Автомобили бортовые, г/п до 5 т",
             "unit": "маш.-ч", "per_unit": 0.03, "price": 600.00},
            {"kind": "machinist", "code": "", "name": "ОТм бортовые, разряд 4",
             "unit": "маш.-ч", "per_unit": 0.03, "price": 600.00},
            {"kind": "material", "code": "01.7.15.06-0111", "name": "Гвозди строительные",
             "unit": "т", "per_unit": 0.0015, "price": 90000.00},
        ],
    }


def _install_card(monkeypatch, card: dict[str, object]) -> None:
    """Serve ``card`` for its own шифр, keep the canonical base for every other code."""
    real_get_norm = gesn_service.get_norm

    def _get_norm(code, *args, **kwargs):
        if str(code or "").strip() == str(card["code"]):
            return dict(card)
        return real_get_norm(code, *args, **kwargs)

    monkeypatch.setattr(gesn_service, "get_norm", _get_norm)


def _trace(rows):
    return build_lsr_trace_from_visible_rows(rows)


def test_the_projection_answers_every_question_for_every_bound_row():
    lsr = _trace([HEADER_ROW, WORK_ROW, SUPPLY_ROW])
    projection = lsr["row_projection"]

    # one entry per bound row, in the order the file prints them
    assert [item["locator"] for item in projection] == [
        str(binding.get("row")) for binding in lsr["row_bindings"]
    ]
    for item in projection:
        # every one of the seven § 4 questions (and Directive 2.2's volume) is present,
        # so no consumer has to invent a missing answer
        assert set(OPERATION_READINESS_FIELDS) <= set(item)
    # identity: the stable operation id of the revision, not a row index
    by_locator = {item["locator"]: item for item in projection}
    assert by_locator["ВОР!R2"]["operation_id"].startswith("id:ВОР!R2:")
    assert by_locator["ВОР!R2"]["row_role"] == "work"
    assert by_locator["ВОР!R2"]["status"] == "bound"
    # the sheet and the readiness card read these same values
    assert by_locator["ВОР!R2"]["norm_selected"] is True
    assert by_locator["ВОР!R2"]["applicability_substantiated"] is True


def test_a_heading_or_resource_line_is_not_counted_as_an_unfinished_calculation():
    """§ 4: «заголовки не имеют применимости "нет" как дефекта; для них н/п»."""
    lsr = _trace([
        HEADER_ROW,
        {"source_row": "ВОР!R4", "row_role": "resource", "work_row": "ВОР!R2",
         "title": "Ресурс"},
    ])
    by_locator = {item["locator"]: item for item in lsr["row_projection"]}
    # The questions a heading and a resource line cannot answer: no cipher is chosen
    # by them, no position of their own is built, so no money of their own is open.
    not_their_question = {
        "norm_selected",
        "applicability_substantiated",
        "structure_calculated",
        "known_amount_present",
        "position_calculated",
    }
    assert not_their_question <= {name for name, _label, _meaning in OPERATION_QUESTIONS}
    for item in by_locator.values():
        assert item["row_role"] in {"header", "resource"}
        for name in not_their_question:
            assert item[name] is None, (item["row_role"], name)
        # What the row does answer stays answered: its source line reached the
        # revision, and its role is declared — «н/п» is only for absent questions.
        assert item["source_accounted"] is True
        assert item["operation_defined"] is True
    # a row whose questions are all «н/п» produces no remark at all
    assert not [
        blocker for blocker in (lsr.get("blockers") or [])
        if blocker["code"] in {"ВОР!R1", "ВОР!R4"}
    ]


def test_positions_built_and_positions_calculated_are_two_different_numbers():
    """Tracker #59: a position row of zeros was counted as a calculated position."""
    lsr = _trace([WORK_ROW, SUPPLY_ROW])
    summary = lsr["summary"]
    # the unpriced supply line and the norm-card-priced work are both positions…
    assert summary["positions_built"] == 2
    # …and neither has an amount its owner chose, so neither is fully calculated
    assert summary["calculated_positions"] == 0
    assert summary["confirmed_amount"] == 0.0
    # one priced, operator-confirmed line does move the counter
    priced = _trace([{**SUPPLY_ROW, "work_row": "ВОР!R3", "confirmed_price": 100,
                      "price_source": "operator", "confirmed_by": "operator"}])
    assert priced["summary"]["calculated_positions"] == 1
    assert priced["summary"]["positions_built"] == 1


def test_open_works_are_counted_per_operation_never_by_subtraction():
    """§ 4: 1 unfinished work + 1 finished supply line is one open work, not zero."""
    lsr = _trace([WORK_ROW, SUPPLY_ROW])
    readiness = build_lsr_result_readiness(
        packaged=True,
        rows=[WORK_ROW, SUPPLY_ROW],
        missing=[],
        pricing_status=lsr["summary"]["result_status"],
        # the old code read this pair as «2 positions for 1 work → nothing is open»
        calculated_positions=lsr["summary"]["calculated_positions"],
        row_projection=lsr["row_projection"],
    )
    counts = readiness["counts"]
    assert counts["works_projected"] == 1
    assert counts["works_with_calculated_position"] == 0
    assert readiness["gap_states"]["calculation_incomplete"]["count"] == 1
    assert readiness["row_projection"] == lsr["row_projection"]


def test_without_a_projection_the_number_is_unknown_instead_of_guessed():
    readiness = build_lsr_result_readiness(
        packaged=True,
        rows=[WORK_ROW, SUPPLY_ROW],
        missing=[],
        pricing_status="priced_partial",
        calculated_positions=2,
    )
    assert readiness["gap_states"]["calculation_incomplete"]["count"] is None
    assert "проекции" in readiness["gap_states"]["calculation_incomplete"]["meaning"] \
        or "проекцию" in readiness["gap_states"]["calculation_incomplete"]["meaning"]


def test_the_payload_is_not_cut_at_eighty_open_rows():
    """Tracker #56: a 120-row hole list must not arrive as 80 rows and look closed."""
    rows = [
        {
            "source_row": f"ВОР!R{index}",
            "row_role": "work",
            "title": f"Работа {index}",
            "quantity": 1,
            "unit": "м2",
            "norm_status": "MISSING",
        }
        for index in range(1, 121)
    ]
    readiness = build_lsr_result_readiness(
        packaged=True,
        rows=rows,
        missing=[f"price_missing:Ресурс {index}" for index in range(1, 121)],
        pricing_status="priced_partial",
        catalog_locators=[f"ВОР!R{index}" for index in range(1, 121)],
        row_projection=[
            {
                "locator": row["source_row"],
                "work_id": "",
                "operation_id": "",
                "row_role": "work",
                "status": "missing_norm",
                "open_reasons": [],
                **{name: None for name in OPERATION_READINESS_FIELDS},
                "position_calculated": False,
            }
            for row in rows
        ],
    )
    dimensions = readiness["dimensions"]
    assert len(dimensions["norms"]["gaps"]) == 120
    assert len(dimensions["prices"]["codes"]) == 120
    assert len(readiness["row_projection"]) == 120
    assert readiness["gap_states"]["calculation_incomplete"]["count"] == 120


def test_the_check_sheet_fills_its_columns_from_the_trace(monkeypatch, tmp_path):
    # the card of WORK_ROW prices its own rows, so the column has a price decision per
    # resource to print instead of one hole per resource — see `_legacy_card()` for where
    # these rates come from (the base card of this cipher carries no prices at all)
    _install_card(monkeypatch, _legacy_card())
    lsr = _trace([
        HEADER_ROW,
        {**WORK_ROW, "norm_status": "ANALOGUE_CANDIDATE"},
        SUPPLY_ROW,
    ])
    out = tmp_path / "lsr.xlsx"
    render_lsr_xlsx(lsr, out)
    review = load_workbook(out)["Проверка"]
    headers = [cell.value for cell in review[1]]
    rows = list(review.iter_rows(min_row=2, max_row=1 + len(lsr["row_bindings"])))

    def column(name: str, row):
        return str(row[headers.index(name)].value or "")

    work = next(row for row in rows if column("Строка", row) == "ВОР!R2")
    heading = next(row for row in rows if column("Строка", row) == "ВОР!R1")
    supply = next(row for row in rows if column("Строка", row) == "ВОР!R3")

    # the analogue's own unanswered match facts are printed, not left blank
    analogue = column("Ограничения аналога", work)
    assert "не проверено" in analogue and "совпадает ли действие" in analogue
    # the resources the calculator priced are named one per line, each with the
    # price fact that settled it (§ 4: filled from the trace, not invented)
    resources = column("Решения по ресурсам", work)
    lines = [line for line in resources.splitlines() if line.strip()]
    assert resources != "н/п"
    assert len(lines) >= 4
    assert all("цена" in line for line in lines)
    assert {line.split()[0] for line in lines} <= {"labor", "machine", "machinist", "material"}
    # with no ценовая база chosen every rate of this card is the card's own money
    # (the rates themselves come from the stub card, one line per priced resource)
    assert "цена из карточки нормы, основания нет" in resources
    # a heading answers «н/п» everywhere it has no question
    heading_readiness = column("Готовность строки", heading)
    assert "шифр выбран=н/п" in heading_readiness
    assert "расчёт структуры построен=н/п" in heading_readiness
    # an unpriced supply line is open on the amount, and says so
    supply_readiness = column("Готовность строки", supply)
    assert "известная стоимость есть=нет" in supply_readiness
    # § 4 / tracker #56: the file states the kind of the hole, not only that money
    # is missing — the operator's answer to «нужен КАЦ» is a КАЦ row, not a number.
    assert "нужен КАЦ" in column("Решения по ресурсам", supply)

    # § 4 / tracker #54, #60: the remarks block below the rows carries this revision's
    # open questions instead of standing empty.
    block = "\n".join(
        str(cell.value)
        for row in review.iter_rows(min_row=2 + len(lsr["row_bindings"]))
        for cell in row
        if cell.value not in (None, "")
    )
    assert "Общие замечания и незакрытые позиции" in block
    assert "ВОР!R2" in block and "ВОР!R3" in block
    assert "нет (структура собрана, не хватает цены" in block
    assert "ВОР!R1" not in block


def test_a_resource_priced_from_the_chosen_book_is_shown_as_priced(tmp_path):
    """§ 4 / tracker #54: the column distinguishes the price states it was given.

    The codes are taken from the calculator's own decisions instead of hardcoded, so
    the check follows the card the base holds today rather than a snapshot of it.
    One resource priced by the operator's book says «цена есть»; the rest keep their
    own hole, and the row is still not a calculated position.
    """

    class _ChosenBook:
        def __init__(self, prices: dict[str, float]) -> None:
            self._prices = dict(prices)

        def lookup(self, code: str):
            price = self._prices.get(str(code).strip())
            return None if price is None else {"price_current": price}

    probe = _trace([WORK_ROW])
    decisions = next(
        binding.get("resource_decisions") or []
        for binding in probe["row_bindings"]
        if binding.get("row") == "ВОР!R2"
    )
    coded = [item for item in decisions if item.get("code")]
    assert coded, "the norm card of this test prices at least one resource by code"
    chosen = coded[0]

    lsr = build_lsr_trace_from_visible_rows(
        [WORK_ROW], pricebook=_ChosenBook({str(chosen["code"]): 800.0})
    )
    out = tmp_path / "lsr.xlsx"
    render_lsr_xlsx(lsr, out)
    review = load_workbook(out)["Проверка"]
    headers = [cell.value for cell in review[1]]
    row = next(
        r for r in review.iter_rows(min_row=2, max_row=1 + len(lsr["row_bindings"]))
        if str(r[headers.index("Строка")].value) == "ВОР!R2"
    )
    lines = [
        line for line in str(row[headers.index("Решения по ресурсам")].value).splitlines()
        if line.strip()
    ]
    priced = [line for line in lines if "цена есть" in line]
    assert len(priced) == 1 and str(chosen["code"]) in priced[0]
    assert len(lines) > 1 and any("цена есть" not in line for line in lines)
    # the row keeps its own answers: money is known, the position is not closed
    readiness_cell = str(row[headers.index("Готовность строки")].value)
    assert "известная стоимость есть=да" in readiness_cell
    assert "позиция полностью рассчитана=нет" in readiness_cell


def test_every_open_question_reaches_the_delivered_file(tmp_path):
    """The remarks block states one line per open question of the same row."""
    lsr = _trace([SUPPLY_ROW])
    out = tmp_path / "lsr.xlsx"
    render_lsr_xlsx(lsr, out)
    review = load_workbook(out)["Проверка"]
    block = "\n".join(
        str(cell.value)
        for row in review.iter_rows(min_row=2)
        for cell in row
        if cell.value not in (None, "")
    )
    blockers = lsr.get("blockers") or []
    assert blockers
    for blocker in blockers:
        assert blocker["field"] in ("known_amount_present", "position_calculated")
        assert blocker["reason"].split(" (")[0] in block


def test_position_numbers_and_operation_links_survive_into_the_file(tmp_path):
    """§ 4: «проверить номера позиций и связь нескольких операций с одной строкой».

    Two operations are built on one source locator here (the same line quoted twice
    with different content), and a supply line hangs under a work.  The number the
    projection states must be the number the delivered document prints, and the link
    must be readable in the file — otherwise a remark about «строка ВОР!R5» points at
    nothing an operator can find.
    """
    twin_a = {"source_row": "ВОР!R5", "row_role": "work", "basis": "ГЭСН 12-01-034-02",
              "title": "Устройство обрешетки", "quantity": "10", "unit": "м2",
              "norm_status": "EXACT"}
    twin_b = {"source_row": "ВОР!R5", "row_role": "work", "basis": "ГЭСН 12-01-034-02",
              "title": "Обрешетка по другому участку", "quantity": "7", "unit": "м2",
              "norm_status": "EXACT"}
    lsr = build_lsr_trace_from_visible_rows([WORK_ROW, twin_a, twin_b, SUPPLY_ROW])
    projection = lsr["row_projection"]

    # one entry per operation, and the two operations of one locator stay distinct
    assert len(projection) == 4
    by_operation = {item["operation_id"]: item for item in projection}
    assert len(by_operation) == len(projection)
    twins = [item for item in projection if item["locator"] == "ВОР!R5"]
    assert len(twins) == 2
    assert {item["locator_operations"] for item in twins} == {2}
    assert len({item["position_no"] for item in twins}) == 2
    # the supply line states the operation it belongs to
    supply = next(item for item in projection if item["locator"] == "ВОР!R3")
    assert supply["parent_locator"] == "ВОР!R2"
    # numbers are continuous from 1 and unique — the same sequence the file prints
    numbers = sorted(item["position_no"] for item in projection if item["position_no"])
    assert numbers == list(range(1, len(numbers) + 1))

    out = tmp_path / "lsr.xlsx"
    render_lsr_xlsx(lsr, out)
    book = load_workbook(out)
    main = book[book.sheetnames[0]]
    printed = [
        cell.value for cell in main["A"]
        if isinstance(cell.value, int) and not isinstance(cell.value, bool)
    ]
    assert numbers == printed[: len(numbers)] and len(printed) >= len(numbers)

    review = book["Проверка"]
    headers = [cell.value for cell in review[1]]
    rows = list(review.iter_rows(min_row=2, max_row=1 + len(lsr["row_bindings"])))
    located = {
        str(r[headers.index("Строка")].value): r for r in rows
    }
    twin_rows = [r for r in rows if str(r[headers.index("Строка")].value) == "ВОР!R5"]
    assert len(twin_rows) == 2
    assert {str(r[headers.index("№ позиции")].value) for r in twin_rows} == {
        str(twins[0]["position_no"]), str(twins[1]["position_no"])
    }
    supply_link = str(located["ВОР!R3"][headers.index("Связь операций")].value)
    assert "относится к ВОР!R2" in supply_link
    twin_link = str(twin_rows[0][headers.index("Связь операций")].value)
    assert "на строке 2 операции" in twin_link


def test_a_finished_document_prints_a_full_calculation_and_no_open_remark(tmp_path):
    """§ 4: «завершённый — полноценный расчёт».

    The finished case is a supply line whose quantity the source row states and whose
    price the operator confirmed: every question that row has is answered «да», so the
    aggregate status and the per-row answers say the same thing (no consumer is left
    calling the same revision partial and complete), nothing is open in the remarks
    block, and the delivered ЛСР carries the arithmetic as a number.
    """
    finished = {**SUPPLY_ROW, "confirmed_price": 100, "price_source": "operator", "confirmed_by": "operator"}
    lsr = _trace([finished])
    summary = lsr["summary"]
    assert summary["result_status"] == "priced_final"
    # 30 «м.п» × 100 ₽ — the operator's price applied to the source quantity
    assert summary["confirmed_amount"] == pytest.approx(3000.0)
    assert summary["preliminary_amount"] == 0.0
    assert not (lsr.get("blockers") or [])
    assert not (lsr.get("warnings") or [])
    row = lsr["row_projection"][0]
    assert row["position_calculated"] is True
    assert row["prices_provided"] is True

    out = tmp_path / "lsr.xlsx"
    render_lsr_xlsx(lsr, out)
    book = load_workbook(out)
    main = book[book.sheetnames[0]]
    # the operator's price and the source quantity are literal cells; the totals above
    # them are live formulas (see the preview test for what that means on screen)
    money = [
        cell.value
        for r in main.iter_rows()
        for cell in r
        if isinstance(cell.value, (int, float)) and not isinstance(cell.value, bool)
    ]
    assert 100 in money and 30 in money
    totals = [
        cell.value
        for r in main.iter_rows()
        for cell in r
        if isinstance(cell.value, str) and cell.value.startswith("=SUM(")
    ]
    assert totals, "the delivered ЛСР carries no summed total row"
    assert summary["full_amount"] == pytest.approx(3000.0)

    review = book["Проверка"]
    headers = [cell.value for cell in review[1]]
    rows = list(review.iter_rows(min_row=2, max_row=1 + len(lsr["row_bindings"])))
    line = next(
        r for r in rows if str(r[headers.index("Строка")].value) == "ВОР!R3"
    )
    readiness_cell = str(line[headers.index("Готовность строки")].value)
    assert "позиция полностью рассчитана=да" in readiness_cell
    assert "известная стоимость есть=да" in readiness_cell
    assert "цены=да" in readiness_cell
    assert "=нет" not in readiness_cell
    # the remarks block states that this revision left no question open, instead of
    # standing empty the way an unproduced section would (§ 4: no fictitious
    # expertise — the line reports the file's own status).
    block = "\n".join(
        str(cell.value)
        for r in review.iter_rows(min_row=2 + len(lsr["row_bindings"]))
        for cell in r
        if cell.value not in (None, "")
    )
    assert "Общие замечания и незакрытые позиции" in block
    assert "открытых вопросов" in block
    assert "blocker" not in block and "warning" not in block


def test_an_unfinished_document_prints_reasons_and_preliminary_amounts(tmp_path):
    """§ 4: «незавершённый файл показывает понятные причины и предварительные суммы»."""
    lsr = _trace([SUPPLY_ROW])
    summary = lsr["summary"]
    assert summary["result_status"] == "priced_partial"
    assert summary["confirmed_amount"] == 0.0
    blockers = lsr.get("blockers") or []
    assert blockers
    out = tmp_path / "lsr.xlsx"
    render_lsr_xlsx(lsr, out)
    review = load_workbook(out)["Проверка"]
    block = "\n".join(
        str(cell.value)
        for row in review.iter_rows(min_row=2)
        for cell in row
        if cell.value not in (None, "")
    )
    for blocker in blockers:
        assert blocker["reason"].split(" (")[0] in block
    assert "нужен КАЦ" in block


def test_the_unit_the_operator_price_was_multiplied_by_reaches_the_file(tmp_path):
    """§ 4 / § 10: the price note is the calculator's own arithmetic and must be readable.

    A position is measured in the norm's unit («100 м2» here), while the source ВОР
    states its own (1 «м2»).  The flags the note travels in never reach the delivered
    file, so an operator who answered a price in the chat could not see which unit the
    sum used — the very place a flat price is off by that factor.  The note now travels
    on the row projection and is printed in the remarks block; the row's own answers
    stay what the readiness rules say they must be.
    """
    rows = [
        {"source_row": "ЛСР!R2", "row_role": "work", "basis": "ГЭСН 12-01-034-02",
         "title": "Устройство обрешетки", "quantity": "1", "unit": "м2",
         "norm_status": "EXACT", "confirmed_price": 100, "price_source": "operator", "confirmed_by": "operator"},
    ]
    lsr = build_lsr_trace_from_visible_rows(rows)
    summary = lsr["summary"]
    # 0.01 «100 м2» × 100 ₽ — the norm unit, not the source unit, and the file says so
    assert summary["confirmed_amount"] == pytest.approx(1.0)
    note_row = lsr["row_projection"][0]
    assert "«100 м2»" in note_row["price_note"]
    assert "1.0 «м2»" in note_row["price_note"]
    # the note explains a finished position, it does not reopen it
    assert note_row["position_calculated"] is True
    assert note_row["prices_provided"] is True

    out = tmp_path / "lsr.xlsx"
    render_lsr_xlsx(lsr, out)
    review = load_workbook(out)["Проверка"]
    block = "\n".join(
        str(cell.value)
        for row in review.iter_rows(min_row=2)
        for cell in row
        if cell.value not in (None, "")
    )
    assert "ЛСР!R2" in block
    assert "× 0.01 = 1.0 ₽" in block
    assert "если цена названа за исходную единицу" in block


def test_the_tabular_preview_shows_an_uncached_total_as_a_formula_not_as_empty(tmp_path):
    """§ 4: «формулы без кеша могут выглядеть пустыми» — проверено на самом просмотре.

    Older revisions contain live formulas without cached values. Preserve the
    preview fallback for those immutable files even though newly rendered workbooks
    also store the amounts already computed by the calculation trace.
    """
    from proxy.services.xlsx_preview_service import spreadsheet_preview

    lsr = _trace([{**SUPPLY_ROW, "confirmed_price": 100, "price_source": "operator", "confirmed_by": "operator"}])
    out = tmp_path / "lsr.xlsx"
    render_lsr_xlsx(lsr, out)

    cached = load_workbook(out, data_only=True)
    sheet = cached[cached.sheetnames[0]]
    total_row = next(
        row for row in range(1, sheet.max_row + 1)
        if str(sheet.cell(row=row, column=3).value or "").startswith("Всего по позиции")
    )
    assert sheet.cell(row=total_row, column=12).value == 3000.0
    cached.close()

    # An openpyxl round trip retains formulas and drops their numeric caches,
    # reproducing the format of revisions exported before build 889.
    legacy = load_workbook(out)
    legacy.save(out)
    legacy.close()
    cached = load_workbook(out, data_only=True)
    assert cached[cached.sheetnames[0]].cell(row=total_row, column=12).value is None
    cached.close()

    rows, note = spreadsheet_preview(out.read_bytes(), "xlsx")
    flat = "\n".join(str(value) for row in rows for value in row.values())
    assert "=SUM(" in flat, "the preview still hides the total behind an empty cell"
    assert "Итоговые ячейки показаны формулой" in note
    # the caption refuses to pass itself off as the arithmetic check (§ 4)
    assert "не по просмотр" in note


def test_a_normal_spreadsheet_preview_says_nothing_about_formulas(tmp_path):
    """The uncached-formula caption belongs only to files that have that hole."""
    from openpyxl import Workbook

    from proxy.services.xlsx_preview_service import spreadsheet_preview

    book = Workbook()
    sheet = book.active
    sheet.append(["№", "Сумма"])
    sheet.append([1, 3000.0])
    out = tmp_path / "plain.xlsx"
    book.save(out)

    rows, note = spreadsheet_preview(out.read_bytes(), "xlsx")
    assert rows and note == ""


def test_the_chat_history_projection_keeps_every_projected_row():
    """§ 4 / #56: the chat card counts from all rows, not from a page of them.

    The history projection bounds what each row says, never how many rows there are:
    a capped projection would silently change «сколько работ рассчитано».
    """
    from proxy.services.chat_evidence_application_service import (
        _HISTORY_ROW_FIELDS,
        safe_workbook_history_projection,
    )

    lsr = _trace([WORK_ROW, SUPPLY_ROW])
    payload = {
        "schema": "les.workbook_tool_result.v1",
        "tool": "build_lsr_workbook",
        "status": "partial",
        "calculated_positions": lsr["summary"]["calculated_positions"],
        "positions_built": lsr["summary"]["positions_built"],
        "row_projection": [
            dict(item, binding_message="x" * 4000) for item in lsr["row_projection"]
        ],
    }
    safe = safe_workbook_history_projection(payload)
    assert len(safe["row_projection"]) == len(lsr["row_projection"])
    assert safe["positions_built"] == lsr["summary"]["positions_built"]
    for row in safe["row_projection"]:
        assert set(row) <= set(_HISTORY_ROW_FIELDS)
        # identity and every answer survive the bound unchanged
        assert row["locator"]
        assert row["position_calculated"] is False
