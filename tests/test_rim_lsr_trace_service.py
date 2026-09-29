"""РИМ-трасса ЛСР: графы 2-12, цены ФГИС ЦС и итог позиции."""

from __future__ import annotations

from proxy.services.rim_lsr_trace_service import (
    build_lsr_trace,
    build_lsr_trace_from_visible_rows,
    build_position_trace,
    positions_from_visible_lsr_rows,
)


CODE = "ГЭСН12-01-034-02"


def test_invalid_conversion_does_not_fall_back_to_pricing_otherwise_valid_quantity():
    from proxy.services.rim_lsr_trace_service import _norm_qty_from_visible_row

    for field in ("conversion_factor", "calc_quantity"):
        row = {"quantity": 120, "unit": "м", "calc_quantity": 36600,
               "conversion_factor": 305, "conversion_source": "СКС!R17"}
        row[field] = "305 м * 120 шт"
        quantity, trace = _norm_qty_from_visible_row(row, CODE, {"unit": "100 м"})
        assert quantity is None
        assert trace["status"] == "needs_input"
        assert trace["invalid_field"] == field
        assert trace["authored_value"] == row[field]


def test_bad_numeric_row_preserves_good_row_calculation_and_gap():
    valid = {"source_row": "R1", "row_role": "work", "title": "First",
             "norm_code": CODE, "quantity": 61, "unit": "м2"}
    invalid = {**valid, "source_row": "R2", "conversion_factor": "305 м * 120 шт"}
    good = build_lsr_trace_from_visible_rows([valid])
    combined = build_lsr_trace_from_visible_rows([valid, invalid])
    assert combined["summary"]["total"] == good["summary"]["total"] > 0
    assert len(combined["row_bindings"]) == 2
    gap = combined["row_bindings"][1]
    assert gap["status"] == "needs_input"
    assert gap["source_row"] == invalid
    assert gap["quantity_trace"]["invalid_field"] == "conversion_factor"


def _rows_by_type(trace):
    return {row["type"]: row for row in trace["rows"]}


def test_rim_trace_from_gesn_seed_reproduces_gold_position():
    trace = build_position_trace({"code": CODE, "qty": 0.61})
    summary = trace["summary"]

    assert summary["flags"]
    assert all(
        str(flag).startswith("цена взята из карточки нормы") for flag in summary["flags"]
    )
    # ADR-16 § 7: the seed base carries its own rates.  Those numbers still
    # compute the estimate, but nobody chose them, so the position must be named
    # and must not report a complete amount.
    assert {item["name"] for item in summary["card_priced_resources"]}
    assert summary["amount_status"] == "partial"
    assert summary["full_amount"] is None
    assert summary["ozp"] == 3750.23
    assert summary["em"] == 992.40
    assert summary["mat"] == 83.62
    assert summary["direct"] == 4826.25
    assert summary["fot"] == 4208.91
    assert summary["nr"] == 4587.71
    assert summary["sp"] == 2399.08
    assert summary["total"] == 11813.04
    # нормативные чел.-ч (в шапку многопозиционной формы) — те же, что в групп-строках
    assert summary["labor_qty"] == 7.8934
    assert summary["machinist_qty"] > 0

    rows = _rows_by_type(trace)
    assert rows["work"]["columns"]["2"] == CODE
    assert rows["work"]["columns"]["4"] == "100 м2"
    assert rows["work"]["columns"]["7"] == 0.61
    assert rows["group_labor"]["columns"]["7"] == 7.8934
    assert rows["group_labor"]["columns"]["12"] == 3750.23
    assert rows["group_machine"]["columns"]["12"] == 992.4
    assert rows["group_machinist"]["columns"]["12"] == 458.68
    assert rows["group_material"]["columns"]["12"] == 83.62
    assert rows["nr"]["source"] == "Пр/812"
    assert rows["sp"]["source"] == "Пр/774"


def test_visible_rows_accept_colon_prefixed_norm_codes(monkeypatch):
    from proxy.services import gesn_service

    monkeypatch.setattr(
        gesn_service,
        "get_norm",
        lambda *_args, **_kwargs: {
            "code": "ГЭСНм08-03-575-01",
            "name": "Монтаж прибора или аппарата",
            "unit": "шт",
            "resources": [],
            "nr_pct": 0,
            "sp_pct": 0,
        },
    )
    trace = build_lsr_trace_from_visible_rows([
        {
            "basis": "ГЭСНм:08-03-575-01",
            "title": "Монтаж прибора или аппарата",
            "unit": "шт",
            "quantity": 1,
        }
    ])

    summary = trace["summary"]
    assert summary["bound_rows"] == 1
    assert trace["row_bindings"][0]["status"] == "bound"
    assert trace["sections"][0]["positions"][0]["code"] == "ГЭСНм08-03-575-01"


def test_visible_rows_accept_engineering_count_unit_aliases(monkeypatch):
    from proxy.services import gesn_service

    catalog = {
        "ГЭСНм08-03-575-01": {
            "code": "ГЭСНм08-03-575-01",
            "name": "Установка электротехнического аппарата",
            "unit": "шт",
            "resources": [],
            "nr_pct": 0,
            "sp_pct": 0,
        },
        "ГЭСН17-01-010-01": {
            "code": "ГЭСН17-01-010-01",
            "name": "Установка ревизионных люков",
            "unit": "100 шт",
            "resources": [],
            "nr_pct": 0,
            "sp_pct": 0,
        },
    }
    monkeypatch.setattr(
        gesn_service,
        "get_norm",
        lambda code, *args, **kwargs: catalog.get(str(code or "")),
    )
    trace = build_lsr_trace_from_visible_rows([
        {
            "basis": "ГЭСНм:08-03-575-01",
            "title": "Установка электротехнического аппарата",
            "unit": "компл",
            "quantity": 1,
        },
        {
            "basis": "ГЭСН:17-01-010-01",
            "title": "Установка ревизионных люков",
            "unit": "шт",
            "quantity": 10,
        },
    ])

    summary = trace["summary"]
    assert summary["bound_rows"] == 2
    assert trace["row_bindings"][0]["quantity_trace"]["status"] == "direct_from_row"
    assert trace["row_bindings"][1]["quantity_trace"]["status"] == "unit_conversion"
    assert trace["sections"][0]["positions"][0]["code"] == "ГЭСНм08-03-575-01"
    assert trace["sections"][0]["positions"][1]["code"] == "ГЭСН17-01-010-01"


def test_visible_rows_convert_piece_dimensions_to_area_norm_qty(monkeypatch):
    from proxy.services import gesn_service

    monkeypatch.setattr(
        gesn_service,
        "get_norm",
        lambda *_args, **_kwargs: {
            "code": "ГЭСН15-01-052-01",
            "name": "Разработка проема",
            "unit": "100 м2",
            "resources": [],
            "nr_pct": 0,
            "sp_pct": 0,
        },
    )
    guessed = build_lsr_trace_from_visible_rows([
        {
            "source_row": "PDF!R2",
            "basis": "ГЭСН:15-01-052-01",
            "title": "Разработка проема 400х400 мм",
            "unit": "шт",
            "quantity": 10,
            "row_role": "work",
        },
    ])
    binding = guessed["row_bindings"][0]
    assert binding["status"] == "needs_input"
    assert binding["code"] == "ГЭСН15-01-052-01"
    assert binding["quantity_trace"]["source_quantity"] == 10.0

    cited = build_lsr_trace_from_visible_rows([
        {
            "source_row": "PDF!R2",
            "basis": "ГЭСН:15-01-052-01",
            "title": "Разработка проема 400х400 мм",
            "unit": "шт",
            "quantity": 10,
            "conversion_factor": 0.16,
            "conversion_source": "400×400 мм = 0,16 м2",
            "row_role": "work",
        },
    ])
    assert cited["row_bindings"][0]["status"] == "bound"
    assert cited["row_bindings"][0]["position"]["qty"] == 0.016
    assert cited["row_bindings"][0]["quantity_trace"]["status"] == "cited_conversion_factor"


def test_rim_trace_applies_resource_coefficients_by_kind():
    trace = build_position_trace({"code": CODE, "qty": 0.61}, k_ozp=1.15, k_em=1.15)
    summary = trace["summary"]
    rows = _rows_by_type(trace)

    assert rows["coefficient"]["meta"] == {"k_ozp": 1.15, "k_em": 1.15}
    labor = next(row for row in trace["rows"] if row["type"] == "resource_labor")
    machine = next(row for row in trace["rows"] if row["type"] == "resource_machine")
    machinist = next(row for row in trace["rows"] if row["type"] == "resource_machinist")
    material = next(row for row in trace["rows"] if row["type"] == "resource_material")
    assert labor["columns"]["6"] == 1.15
    assert machine["columns"]["6"] == 1.15
    assert machinist["columns"]["6"] == 1.15
    assert material["columns"]["6"] == 1.0
    assert summary["ozp"] > 3750.23
    assert summary["machine"] > 533.72
    assert summary["zpm"] > 458.68
    assert summary["mat"] == 83.62
    assert summary["total"] > 11813.04


def test_rim_trace_preserves_fgis_current_vs_base_index_columns():
    class FakePriceBook:
        def lookup(self, code):
            return {
                "91.05.05-015": {
                    "price_current": 1663.18,
                    "price_base": 1167.7,
                    "index": None,
                    "price_current_eff": 1663.18,
                },
                "01.7.15.06-0111": {
                    "price_current": None,
                    "price_base": 70296.2,
                    "index": 1.3,
                    "price_current_eff": 91385.06,
                },
            }.get(code)

    trace = build_position_trace(
        {
            "code": "ГЭСН00-00-000-00",
            "name": "Тестовая работа",
            "unit": "шт",
            "qty": 2,
            "nr_pct": 0,
            "sp_pct": 0,
            "resources": [
                {"kind": "machine", "code": "91.05.05-015", "name": "Кран", "unit": "маш.-ч", "per_unit": 1},
                {"kind": "material", "code": "01.7.15.06-0111", "name": "Гвозди", "unit": "т", "per_unit": 0.001},
            ],
        },
        pricebook=FakePriceBook(),
    )

    machine = next(row for row in trace["rows"] if row["type"] == "resource_machine")
    material = next(row for row in trace["rows"] if row["type"] == "resource_material")

    assert machine["source"] == "fgis_current"
    assert machine["columns"]["10"] == 1663.18
    assert "8" not in machine["columns"]
    assert "9" not in machine["columns"]

    assert material["source"] == "fgis_base_index"
    assert material["columns"]["8"] == 70296.2
    assert material["columns"]["9"] == 1.3
    assert material["columns"]["10"] == 91385.06
    assert material["columns"]["12"] == 182.77
    assert trace["summary"]["direct"] == 3509.13


def test_missing_price_and_unresolved_resource_review_separate_known_and_full_amount():
    trace = build_position_trace({
        "code": "ГЭСН00-00-000-00",
        "name": "Тестовая аналоговая работа",
        "unit": "шт",
        "qty": 2,
        "nr_pct": 0,
        "sp_pct": 0,
        "resource_review_status": "unresolved",
        "resource_review_reason": "не проверен чужой материал",
        "resources": [
            {"kind": "material", "code": "01.1", "name": "Материал без цены", "unit": "шт", "per_unit": 1},
        ],
    })

    summary = trace["summary"]
    assert summary["known_amount"] == 0.0
    assert summary["full_amount"] is None
    assert summary["amount_status"] == "partial"
    assert "resource_review_unresolved" in summary["completeness_reasons"]
    assert any(str(reason).startswith("price_missing:") for reason in summary["completeness_reasons"])
    assert _rows_by_type(trace)["position_total"]["columns"]["3"] == "Известная стоимость позиции"


def test_explicit_empty_resource_revision_is_not_rehydrated_from_norm(monkeypatch):
    """An empty model revision is data, not a request to restore raw norm resources."""
    from proxy.services import gesn_service

    norm = {
        "code": "ГЭСНм08-02-409-09",
        "name": "Прокладка труб гофрированных",
        "unit": "100 м",
        "resources": [
            {"kind": "labor", "code": "1-100-36", "name": "Средний разряд", "unit": "чел.-ч", "per_unit": 15.2, "price": 500},
        ],
        "_source_kind": "seed_yaml",
    }
    monkeypatch.setattr(gesn_service, "get_norm", lambda *_args, **_kwargs: norm)

    trace = build_position_trace({
        "code": norm["code"], "qty": 1.6, "resources": [], "nr_pct": 0, "sp_pct": 0,
        "resource_review_status": "unresolved",
        "resource_review_reason": "модель не подтвердила компоненты",
    })

    assert not [row for row in trace["rows"] if str(row.get("type") or "").startswith("resource_")]
    assert trace["summary"]["labor_qty"] == 0
    assert trace["summary"]["known_amount"] == 0


def test_hydrated_norm_resources_are_labor_normalized_at_render_boundary(monkeypatch):
    """The final renderer must not add average, aggregate and grade detail together."""
    from proxy.services import gesn_service

    norm = {
        "code": "ГЭСНм08-02-409-09",
        "name": "Прокладка труб гофрированных",
        "unit": "100 м",
        "resources": [
            {"kind": "labor", "code": "1-100-36", "name": "Средний разряд работы 3.6", "unit": "чел.-ч", "per_unit": 15.2, "price": 500},
            {"kind": "labor", "code": "", "name": "ЗАТРАТЫ ТРУДА РАБОЧИХ, ВСЕГО: В ТОМ ЧИСЛЕ:", "unit": "чел.-ч", "per_unit": 15.6, "price": 500},
            {"kind": "labor", "code": "2-100-02", "name": "Рабочий 2 разряда", "unit": "чел.-ч", "per_unit": 0.02, "price": 500},
            {"kind": "labor", "code": "2-100-03", "name": "Рабочий 3 разряда", "unit": "чел.-ч", "per_unit": 10.75, "price": 500},
            {"kind": "labor", "code": "2-100-04", "name": "Рабочий 4 разряда", "unit": "чел.-ч", "per_unit": 4.83, "price": 500},
        ],
        "_source_kind": "seed_yaml",
    }
    monkeypatch.setattr(gesn_service, "get_norm", lambda *_args, **_kwargs: norm)

    trace = build_position_trace({"code": norm["code"], "qty": 1, "nr_pct": 0, "sp_pct": 0})

    labor_rows = [row for row in trace["rows"] if row.get("type") == "resource_labor"]
    assert [row["columns"]["2"] for row in labor_rows] == ["2-100-02", "2-100-03", "2-100-04"]
    assert trace["summary"]["labor_qty"] == 15.6
    assert trace["summary"]["ozp"] == 7800


def test_build_lsr_trace_multi_position_sections_and_grand_total():
    # две gold-позиции в двух разделах → общий итог = 2× эталон; итоги разделов и свод — Σ позиций
    positions = [
        {"code": CODE, "qty": 0.61, "section": "Раздел 1. Кровля"},
        {"code": CODE, "qty": 0.61, "section": "Раздел 2. Прочее"},
    ]
    lsr = build_lsr_trace(positions, name="Кровля и прочее")

    assert lsr["name"] == "Кровля и прочее"
    assert lsr["summary"]["positions"] == 2
    # Grouping into sections introduces no new problem: the only flags are the
    # ADR-16 § 7 card-price ones, one per resource whose rate nobody chose.
    assert lsr["summary"]["flags"]
    assert all(
        str(flag).startswith("цена взята из карточки нормы") for flag in lsr["summary"]["flags"]
    )
    assert lsr["summary"]["total"] == 23626.08  # 2 × 11813.04 — gold позиции сохранён
    # свод суммирует позиции (прямые/ФОТ/НР/СП) — числа считает код, не LLM
    assert lsr["summary"]["direct"] == round(2 * 4826.25, 2)
    assert lsr["summary"]["fot"] == round(2 * 4208.91, 2)
    assert lsr["summary"]["nr"] == round(2 * 4587.71, 2)
    assert lsr["summary"]["sp"] == round(2 * 2399.08, 2)
    assert lsr["summary"]["labor_qty"] == round(2 * 7.8934, 6)

    secs = lsr["sections"]
    assert [s["section"] for s in secs] == ["Раздел 1. Кровля", "Раздел 2. Прочее"]
    assert secs[0]["total"] == 11813.04 and secs[1]["total"] == 11813.04
    # каждый раздел несёт полные трассы позиций (для рендера формы)
    assert len(secs[0]["positions"]) == 1
    assert secs[0]["positions"][0]["summary"]["total"] == 11813.04


def test_build_lsr_trace_groups_same_section_contiguously():
    # позиции одного раздела, вперемешку с другим, группируются → 2 раздела, не 3
    positions = [
        {"code": CODE, "qty": 0.61, "section": "A"},
        {"code": CODE, "qty": 0.61, "section": "B"},
        {"code": CODE, "qty": 0.61, "section": "A"},
    ]
    lsr = build_lsr_trace(positions)

    assert [s["section"] for s in lsr["sections"]] == ["A", "B"]
    assert len(lsr["sections"][0]["positions"]) == 2
    assert lsr["sections"][0]["total"] == round(2 * 11813.04, 2)
    assert lsr["summary"]["total"] == round(3 * 11813.04, 2)


def test_build_lsr_trace_default_section_when_unspecified():
    # без поля section → один раздел «Без раздела», свод = одна позиция
    lsr = build_lsr_trace([{"code": CODE, "qty": 0.61}])
    assert [s["section"] for s in lsr["sections"]] == ["Без раздела"]
    assert lsr["summary"]["total"] == 11813.04


def test_positions_from_visible_lsr_rows_converts_physical_unit_to_norm_qty():
    bound = positions_from_visible_lsr_rows([
        {"basis": "ГЭСН 12-01-034-02", "title": "Устройство обрешетки", "quantity": "61", "unit": "м2"}
    ])

    assert bound["row_bindings"][0]["status"] == "bound"
    assert bound["positions"][0]["code"] == CODE
    assert bound["positions"][0]["qty"] == 0.61
    assert bound["row_bindings"][0]["quantity_trace"]["formula"] == "61.0 м2 × 1 / 100 = 0.61"


def test_positions_from_visible_lsr_rows_preserves_model_source_row():
    bound = positions_from_visible_lsr_rows([
        {
            "source_row": 42,
            "basis": "ГЭСН 12-01-034-02",
            "title": "Устройство обрешетки",
            "quantity": "61",
            "unit": "м2",
        }
    ])

    assert bound["positions"][0]["source_row"] == 42
    assert bound["row_bindings"][0]["row"] == 42


def test_lsr_trace_from_visible_rows_builds_priced_trace_from_selected_norms():
    lsr = build_lsr_trace_from_visible_rows(
        [
            {
                "basis": "ГЭСН 12-01-034-02",
                "title": "Устройство обрешетки",
                "quantity": "61",
                "unit": "м2",
                "section": "Кровля",
            }
        ],
        name="Видимые строки",
    )

    assert lsr["summary"]["result_status"] == "priced_partial"
    assert lsr["summary"]["input_rows"] == 1
    assert lsr["summary"]["bound_rows"] == 1
    assert lsr["summary"]["total"] == 11813.04
    assert lsr["sections"][0]["section"] == "Кровля"


class _ChosenBook:
    """A ценовая база the operator picked: exact lookup by resource code."""

    def __init__(self, prices: dict[str, float]) -> None:
        self._prices = dict(prices)

    def lookup(self, code: str):
        price = self._prices.get(str(code).strip())
        return None if price is None else {"price_current": price}


def test_resources_priced_from_the_chosen_book_are_confirmed_final():
    """The priced-final path ADR-16 § 7 requires: every counted rate is owned.

    Each resource resolves through the book the operator chose, so no rate is
    the norm card's own, no card-price flag appears, and the whole amount lands
    in ``confirmed_amount``.  The numbers come from the book, not from a card.
    """
    resources = [
        {"kind": "labor", "code": "1-100-36", "name": "Средний разряд работы 3.6",
         "unit": "чел.-ч", "per_unit": 10.0},
        {"kind": "material", "code": "01.7.15.06-0111", "name": "Гвозди строительные",
         "unit": "т", "per_unit": 0.001},
    ]
    book = _ChosenBook({"1-100-36": 500.0, "01.7.15.06-0111": 90000.0})

    lsr = build_lsr_trace(
        [{"code": CODE, "qty": 1.0, "resources": resources, "nr_pct": 0, "sp_pct": 0}],
        pricebook=book,
        name="База выбрана",
    )
    summary = lsr["summary"]
    position = lsr["sections"][0]["positions"][0]["summary"]

    assert [row["source"] for row in lsr["sections"][0]["positions"][0]["rows"]
            if row["type"].startswith("resource")] == ["fgis_current", "fgis_current"]
    assert position["card_priced_resources"] == []
    assert not [flag for flag in position["flags"]
                if str(flag).startswith("цена взята из карточки нормы")]
    assert position["amount_status"] == "complete"
    assert position["full_amount"] == position["total"]
    assert summary["result_status"] == "priced_final"
    # 10.0 чел.-ч × 500 + 0.001 т × 90000 — the book's numbers, by code
    assert position["total"] == 5090.0
    assert summary["total"] == 5090.0


def test_material_priced_from_the_chosen_book_is_confirmed_money():
    """The confirmed/preliminary split follows price ownership, not the number.

    The same 30 × 100 that the card fallback would leave preliminary counts as
    confirmed when the chosen book supplies the rate.
    """
    lsr = build_lsr_trace_from_visible_rows(
        [
            {
                "source_row": "СКС!R9",
                "row_role": "material",
                "work_row": "СКС!R8",
                "title": "Лоток лестничный",
                "resource_code": "01.7.15.06-0111",
                "unit": "м.п",
                "quantity": 30,
            }
        ],
        pricebook=_ChosenBook({"01.7.15.06-0111": 100.0}),
    )
    binding = lsr["row_bindings"][0]
    assert binding["readiness"]["prices_provided"] is True
    assert binding["readiness"]["price_from_norm_card"] is False
    assert lsr["summary"]["confirmed_amount"] == 3000.0
    assert lsr["summary"]["preliminary_amount"] == 0.0


def test_operator_confirmed_price_makes_the_position_money_confirmed_and_says_so():
    """An operator price is owned money plus its own visible provenance flag."""
    row = {
        "source_row": "PDF!R2",
        "row_role": "work",
        "basis": "ГЭСН 12-01-034-02",
        "title": "Устройство обрешетки",
        "quantity": "61",
        "unit": "м2",
        "norm_status": "EXACT",
    }
    draft = build_lsr_trace_from_visible_rows([row], name="Видимые строки")
    confirmed = build_lsr_trace_from_visible_rows(
        [{**row, "confirmed_price": 20000.0, "price_source": "operator"}],
        name="Видимые строки",
    )

    assert draft["summary"]["result_status"] == "priced_partial"
    assert draft["summary"]["confirmed_amount"] == 0.0
    assert draft["summary"]["preliminary_amount"] == 11813.04

    binding = confirmed["row_bindings"][0]
    assert binding["readiness"]["prices_provided"] is True
    assert binding["readiness"]["operator_confirmed_price"] is True
    # 0.61 (100 м2) × 20000 — the operator price, not the norm composition
    assert confirmed["summary"]["confirmed_amount"] == 12200.0
    assert confirmed["summary"]["preliminary_amount"] == 0.0
    assert [flag for flag in confirmed["summary"]["flags"]
            if "подтверждённой цене оператора" in str(flag)]


def test_named_needs_research_cipher_is_priced_but_not_final():
    lsr = build_lsr_trace_from_visible_rows(
        [
            {
                "source_row": "PDF!R18",
                "row_role": "work",
                "basis": "ГЭСН 12-01-034-02",
                "title": "Устройство обрешетки",
                "quantity": "61",
                "unit": "м2",
                "norm_status": "NEEDS_RESEARCH",
                "quality_message": "аналог, требуется ревизия",
            }
        ],
        name="Видимые строки",
    )

    assert lsr["summary"]["result_status"] == "priced_partial"
    assert lsr["summary"]["norms_status"] == "model_norms_partial"
    assert lsr["summary"]["bound_rows"] == 1
    assert lsr["summary"]["total"] == 11813.04
    assert lsr["row_bindings"][0]["status"] == "bound"
    assert lsr["row_bindings"][0]["norm_status"] == "NEEDS_RESEARCH"
    assert lsr["row_bindings"][0]["selection_kind"] == "analogue"


def test_needs_research_without_code_stays_unbound():
    lsr = build_lsr_trace_from_visible_rows(
        [
            {
                "source_row": "PDF!R21",
                "row_role": "work",
                "title": "Монтаж БАП",
                "quantity": "1",
                "unit": "шт",
                "norm_status": "NEEDS_RESEARCH",
            }
        ]
    )
    assert lsr["summary"]["bound_rows"] == 0
    assert lsr["row_bindings"][0]["status"] == "needs_research"


def test_terminal_exact_status_prices_without_independent_verifier():
    lsr = build_lsr_trace_from_visible_rows(
        [
            {
                "basis": "ГЭСН 12-01-034-02",
                "title": "Устройство обрешетки",
                "quantity": "61",
                "unit": "м2",
                "section": "Кровля",
                "norm_status": "EXACT",
            }
        ],
        name="Видимые строки",
    )

    # A terminal EXACT status settles the norm question only.  The rates behind
    # this total come from the norm card, and ADR-16 § 7 keeps an unowned rate
    # out of a final document.
    assert lsr["summary"]["result_status"] == "priced_partial"
    assert lsr["summary"]["norms_status"] == "model_norms_selected"
    assert lsr["summary"]["total"] == 11813.04
    assert lsr["row_bindings"][0]["status"] == "bound"
    assert lsr["row_bindings"][0]["quality_gate"] == "not_run"


def test_lsr_trace_from_visible_rows_keeps_unbound_rows_out_of_priced_final():
    lsr = build_lsr_trace_from_visible_rows(
        [
            {"basis": "ГЭСН 12-01-034-02", "title": "Устройство обрешетки", "quantity": "61", "unit": "м2"},
            {"title": "Работа без выбранной нормы", "quantity": "1", "unit": "шт"},
        ]
    )

    assert lsr["summary"]["result_status"] == "priced_partial"
    assert lsr["summary"]["bound_rows"] == 1
    assert lsr["summary"]["unbound_rows"] == 1
    assert lsr["row_bindings"][1]["status"] == "unresolved"


def test_unbound_lsr_placeholder_uses_blank_missing_price_not_zero():
    from proxy.smeta_core.contracts import WorkItem
    from proxy.smeta_core.lsr_renderer import _placeholder

    missing = _placeholder(
        WorkItem(work_id="row-2", title="Работа без нормы", quantity=1, unit="шт"),
        "norm_selection_required",
        "норма не выбрана",
    )

    assert missing["summary"]["total"] is None
    assert missing["rows"][0]["columns"]["12"] is None
    assert missing["rows"][1]["columns"]["12"] is None


def test_lsr_trace_from_visible_rows_does_not_bind_unknown_norm_code():
    lsr = build_lsr_trace_from_visible_rows(
        [{"basis": "ГЭСН 99-99-999-99", "title": "Неизвестная норма", "quantity": "1", "unit": "шт"}]
    )

    assert lsr["summary"]["result_status"] == "norm_selection_required"
    assert lsr["summary"]["bound_rows"] == 0
    assert lsr["summary"]["unbound_rows"] == 1
    assert lsr["row_bindings"][0]["status"] == "norm_not_found"


def test_explicit_norm_cell_does_not_select_code_from_rejected_prose():
    row = {
        "source_row": "Sheet!R34", "row_role": "work",
        "title": "Install tray", "unit": "м2", "quantity": 61,
        "norm_code": "Not suitable: ГЭСН12-01-034-02. Find another norm.",
        "norm_status": "yes",
    }
    trace = build_lsr_trace_from_visible_rows([row])
    assert trace["summary"]["bound_rows"] == 0
    assert trace["row_bindings"][0]["status"] == "norm_selection_required"
    assert trace["row_bindings"][0]["source_row"]["norm_code"] == row["norm_code"]


def test_cited_packaging_converts_to_piece_norm_qty(monkeypatch):
    from proxy.services import gesn_service

    monkeypatch.setattr(
        gesn_service,
        "get_norm",
        lambda *_args, **_kwargs: {
            "code": "ГЭСНм08-03-575-01",
            "name": "Монтаж аппарата",
            "unit": "шт",
            "resources": [],
            "nr_pct": 0,
            "sp_pct": 0,
        },
    )
    bound = positions_from_visible_lsr_rows([
        {
            "source_row": "СКС!R2",
            "basis": "ГЭСНм:08-03-575-01",
            "title": "Монтаж аппарата",
            "unit": "упак",
            "quantity": 2,
            "conversion_factor": 12,
            "conversion_source": "упаковка 12 шт",
            "row_role": "work",
        }
    ])

    assert bound["row_bindings"][0]["status"] == "bound"
    assert bound["positions"][0]["qty"] == 24
    assert bound["row_bindings"][0]["quantity_trace"]["source_quantity"] == 2.0
    assert bound["row_bindings"][0]["quantity_trace"]["status"] == "cited_conversion_factor"


def test_cited_mass_per_meter_converts_length_to_ton_norm(monkeypatch):
    from proxy.services import gesn_service

    monkeypatch.setattr(
        gesn_service,
        "get_norm",
        lambda *_args, **_kwargs: {
            "code": "ГЭСНм08-02-409-09",
            "name": "Прокладка кабеля",
            "unit": "т",
            "resources": [],
            "nr_pct": 0,
            "sp_pct": 0,
        },
    )
    without_source = positions_from_visible_lsr_rows([
        {
            "source_row": "СКС!R4",
            "basis": "ГЭСНм08-02-409-09",
            "title": "Кабель",
            "unit": "м",
            "quantity": 100,
            "row_role": "work",
        }
    ])
    assert without_source["row_bindings"][0]["status"] == "needs_input"
    assert without_source["row_bindings"][0]["code"] == "ГЭСНм08-02-409-09"

    cited = positions_from_visible_lsr_rows([
        {
            "source_row": "СКС!R4",
            "basis": "ГЭСНм08-02-409-09",
            "title": "Кабель",
            "unit": "м",
            "quantity": 100,
            "conversion_factor": 0.001,
            "conversion_source": "0,001 т/м по спецификации",
            "row_role": "work",
        }
    ])
    assert cited["row_bindings"][0]["status"] == "bound"
    assert cited["positions"][0]["qty"] == 0.1


def test_confirmed_overlay_fixes_one_row_without_rewriting_others():
    rows = [
        {
            "source_row": "A!R2",
            "basis": "ГЭСН 12-01-034-02",
            "title": "Обрешетка",
            "quantity": "61",
            "unit": "м2",
            "row_role": "work",
        },
        {
            "source_row": "A!R3",
            "basis": "ГЭСН 12-01-034-02",
            "title": "Обрешетка повтор",
            "quantity": "61",
            "unit": "м2",
            "row_role": "work",
        },
    ]
    lsr = build_lsr_trace_from_visible_rows(
        rows,
        confirmed_data={
            "A!R3": {
                "calc_quantity": 100,
                "conversion_source": "оператор: 100 м2",
            }
        },
    )
    by_row = {str(item["row"]): item for item in lsr["row_bindings"]}
    assert by_row["A!R2"]["position"]["qty"] == 0.61
    assert by_row["A!R3"]["position"]["qty"] == 1.0
    assert by_row["A!R2"]["code"] == CODE
    assert by_row["A!R3"]["code"] == CODE


def test_supply_row_excludes_gesn_materials_and_keeps_work_link(monkeypatch):
    from proxy.services import gesn_service

    monkeypatch.setattr(
        gesn_service,
        "get_norm",
        lambda *_args, **_kwargs: {
            "code": "ГЭСНм08-03-575-01",
            "name": "Монтаж",
            "unit": "шт",
            "resources": [
                {"kind": "labor", "name": "Монтажник", "unit": "чел.-ч", "per_unit": 1, "price": 100},
                {"kind": "material", "name": "Аппарат из нормы", "unit": "шт", "per_unit": 1, "price": 50},
            ],
            "nr_pct": 0,
            "sp_pct": 0,
        },
    )
    lsr = build_lsr_trace_from_visible_rows(
        [
            {
                "source_row": "СКС!R2",
                "basis": "ГЭСНм08-03-575-01",
                "title": "Монтаж шкафа",
                "unit": "шт",
                "quantity": 1,
                "row_role": "work",
                "nr_pct": 0,
                "sp_pct": 0,
            },
            {
                "source_row": "СКС!R3",
                "title": "Шкаф поставка",
                "unit": "шт",
                "quantity": 1,
                "row_role": "material",
                "work_row": "СКС!R2",
                "supply_kind": "supply",
                "confirmed_price": 1000,
                "price_source": "счёт",
            },
        ]
    )
    work = next(
        position
        for section in lsr["sections"]
        for position in section["positions"]
        if position.get("source_row") == "СКС!R2"
    )
    assert not [row for row in work["rows"] if row.get("type") == "resource_material"]
    resource = next(
        item for item in lsr["row_bindings"] if item.get("row") == "СКС!R3"
    )
    assert resource["status"] == "bound"
    assert resource["work_row"] == "СКС!R2"


# --- Stage Б: source quantity/unit are the calculation boundary ----------------


def _tray_source_stamp():
    # Факты исходника для СКС!R47: 30 м.п. лотка.
    return {
        "_catalog_source_values": [
            "1025",
            "Лестничный перфорированный кабельный лоток, длина секции 3000 мм",
            "Ostec",
            "м.п",
            "30",
        ],
        "_catalog_source_numbers": [30.0],
    }


def test_unconfirmed_unit_change_stays_visible_but_uncalculated():
    good = {
        "source_row": "СКС!R2",
        "row_role": "work",
        "title": "Монтаж шкафа",
        "norm_code": CODE,
        "quantity": 61,
        "unit": "м2",
    }
    bad = {
        "source_row": "СКС!R47",
        "row_role": "work",
        "title": "Монтаж лотка",
        "norm_code": CODE,
        "quantity": 30,
        "unit": "шт.",
        **_tray_source_stamp(),
    }
    alone = build_lsr_trace_from_visible_rows([good])
    combined = build_lsr_trace_from_visible_rows([good, bad])
    assert combined["summary"]["total"] == alone["summary"]["total"] > 0
    gap = next(b for b in combined["row_bindings"] if b["row"] == "СКС!R47")
    assert gap["status"] == "unconfirmed_quantity"
    payload = gap["quantity_gap"]
    assert payload["field"] == "unit"
    assert payload["authored_value"] == "шт."
    assert "м.п" in payload["source_value"]
    assert "conversion" in payload["needed"]
    # The row stays visible in the source echo and produces no position.
    assert gap["source_row"]["unit"] == "шт."
    assert "СКС!R47" not in {
        str(p.get("source_row"))
        for s in combined["sections"]
        for p in s["positions"]
    }


def test_cited_conversion_basis_allows_the_same_row_to_calculate():
    bad = {
        "source_row": "СКС!R47",
        "row_role": "work",
        "title": "Монтаж лотка",
        "norm_code": CODE,
        "quantity": 30,
        "unit": "шт.",
        **_tray_source_stamp(),
    }
    before = build_lsr_trace_from_visible_rows([bad])
    assert before["summary"]["bound_rows"] == 0
    fixed = dict(bad)
    fixed.update({"calc_quantity": 30, "conversion_source": "длина секции 3 м из исходника"})
    after = build_lsr_trace_from_visible_rows([fixed])
    assert after["summary"]["bound_rows"] == 1
    binding = next(b for b in after["row_bindings"] if b["row"] == "СКС!R47")
    assert binding["status"] == "bound"


def test_unconfirmed_quantity_change_blocks_material_but_matching_passes():
    stamp = {
        "_catalog_source_values": ["990", "Шкаф напольный 42U", "шт", "12"],
        "_catalog_source_numbers": [990.0],
    }
    changed = {
        "source_row": "СКС!R12",
        "row_role": "material",
        "title": "Шкаф",
        "quantity": 12,
        "unit": "шт",
        **stamp,
    }
    trace = build_lsr_trace_from_visible_rows([changed])
    assert trace["summary"]["bound_rows"] == 0
    binding = trace["row_bindings"][0]
    assert binding["status"] == "unconfirmed_quantity"
    assert binding["quantity_gap"]["field"] == "quantity"
    same = dict(changed, quantity=990)
    ok = build_lsr_trace_from_visible_rows([same])
    assert ok["summary"]["bound_rows"] == 1


def test_zero_quantity_is_not_missing_and_no_implicit_one():
    material_no_qty = {"source_row": "СКС!R20", "row_role": "material", "title": "Лоток", "unit": "м.п."}
    trace = build_lsr_trace_from_visible_rows([material_no_qty])
    assert trace["summary"]["bound_rows"] == 0
    assert trace["row_bindings"][0]["status"] == "missing_quantity"
    zero = {"source_row": "СКС!R21", "row_role": "material", "title": "Заглушка", "unit": "шт", "quantity": 0}
    zero_trace = build_lsr_trace_from_visible_rows([zero])
    assert zero_trace["summary"]["bound_rows"] == 1


def test_placeholder_unit_is_not_gated_against_source():
    row = {
        "source_row": "СКС!R4",
        "row_role": "unresolved",
        "title": "Раздел",
        "quantity": None,
        "unit": "-",
        "norm_status": "MISSING",
        "_catalog_source_values": ["982", 'Раздел 6.21 "СКС"'],
        "_catalog_source_numbers": [982.0],
    }
    trace = build_lsr_trace_from_visible_rows([row])
    assert trace["row_bindings"][0]["status"] == "missing_norm"


def test_adapter_stamps_catalog_facts_without_rewriting_model_cells(monkeypatch):
    from proxy.services import attachment_source_catalog_service as catalog_module
    from proxy.services import lsr_workbook_adapter_service as adapter_module

    class _CatRow:
        values = ("м.п", "30")
        numbers = (30.0,)
        excel_row = 47

    class _Cat:
        def lookup(self, _key):
            return _CatRow()

    monkeypatch.setattr(
        catalog_module, "load_catalog_from_attachment_id", lambda _aid: _Cat()
    )
    decisions = [{"source_row": "СКС!R47", "unit": "шт.", "quantity": 30}]
    snapshot = dict(decisions[0])
    adapter_module._attach_catalog_facts(decisions, "read_x")
    assert decisions[0]["unit"] == snapshot["unit"]
    assert decisions[0]["_catalog_source_values"] == ["м.п", "30"]
    assert decisions[0]["_catalog_source_numbers"] == [30.0]


# ---------------------------------------------------------------- stage V split states
def test_stage_v_header_row_is_accounted_without_norm_demand():
    """§6: headings/notes/subtotals are accounted and never demand a mounting norm."""
    lsr = build_lsr_trace_from_visible_rows(
        [
            {
                "source_row": "СКС!R1",
                "row_role": "header",
                "title": "Слаботочные системы. Раздел 1",
                "norm_status": "MISSING",
            },
            {
                "source_row": "СКС!R2",
                "row_role": "work",
                "basis": "ГЭСН 12-01-034-02",
                "title": "Устройство обрешетки",
                "quantity": 61,
                "unit": "м2",
                "norm_status": "EXACT",
            },
        ]
    )
    header = next(item for item in lsr["row_bindings"] if item["row"] == "СКС!R1")
    assert header["status"] == "structure_accounted"
    assert header["readiness"]["header_row"] is True
    assert header["readiness"]["operation_defined"] is True
    assert header["readiness"]["norm_selected"] is None
    assert lsr["summary"]["kind_counts"]["header"] == 1
    # a heading adds no flag; the only flags are the unowned norm-card rates
    assert lsr["summary"]["result_status"] == "priced_partial"
    assert not [flag for flag in lsr["summary"]["flags"] if "СКС!R1" in str(flag)]
    assert all(
        str(flag).startswith("цена взята из карточки нормы") for flag in lsr["summary"]["flags"]
    )
    from proxy.services.lsr_result_readiness_service import classify_norm_gap

    assert classify_norm_gap(header["source_row"]) == ""


def test_stage_v_bound_material_without_price_is_not_ready():
    """§6: ``bound`` must not read as 'position fully ready / price found'."""
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
        ]
    )
    binding = lsr["row_bindings"][0]
    assert binding["status"] == "bound"
    assert binding["readiness"]["norm_selected"] is None
    # § 4: an unpriced supply line is not a finished calculation.  Its structure is
    # accounted, its known amount is not, so the position answer is «нет» — and the
    # remark that goes into the file says which of the two is missing.
    assert binding["readiness"]["structure_calculated"] is True
    assert binding["readiness"]["known_amount_present"] is False
    assert binding["readiness"]["position_calculated"] is False
    assert binding["readiness"]["prices_provided"] is False
    assert lsr["summary"]["kind_counts"]["material"] == 1
    assert lsr["summary"]["confirmed_amount"] == 0.0
    assert lsr["summary"]["preliminary_amount"] >= 0.0
    assert lsr["summary"]["result_status"] != "priced_final"


def test_stage_v_bound_material_with_confirmed_price_is_confirmed():
    lsr = build_lsr_trace_from_visible_rows(
        [
            {
                "source_row": "СКС!R9",
                "row_role": "material",
                "work_row": "СКС!R9",
                "title": "Лоток лестничный",
                "unit": "м.п",
                "quantity": 30,
                "confirmed_price": 100,
                "price_source": "operator",
            }
        ]
    )
    binding = lsr["row_bindings"][0]
    assert binding["status"] == "bound"
    assert binding["readiness"]["prices_provided"] is True
    assert lsr["summary"]["confirmed_amount"] == 3000.0
    assert lsr["summary"]["preliminary_amount"] == 0.0


def test_stage_v_needs_research_bound_stays_preliminary_and_keeps_status():
    """§6: analogue/NEEDS_RESEARCH calculation is visible but separated from confirmed."""
    lsr = build_lsr_trace_from_visible_rows(
        [
            {
                "source_row": "PDF!R18",
                "row_role": "work",
                "basis": "ГЭСН 12-01-034-02",
                "title": "Устройство обрешетки",
                "quantity": "61",
                "unit": "м2",
                "norm_status": "NEEDS_RESEARCH",
                "quality_message": "аналог, требуется ревизия",
            }
        ]
    )
    binding = lsr["row_bindings"][0]
    assert binding["status"] == "bound"
    assert binding["norm_status"] == "NEEDS_RESEARCH"
    assert binding["readiness"]["norm_selected"] is True
    assert binding["readiness"]["applicability_substantiated"] is False
    # Directive 2.2: readiness bases are independent. NEEDS_RESEARCH fails
    # norm_applicability_ok, which is what keeps the position preliminary.
    # prices_provided now tracks only the price dimension.
    assert binding["readiness"]["norm_applicability_ok"] is False
    assert lsr["summary"]["confirmed_amount"] == 0.0
    assert lsr["summary"]["preliminary_amount"] == 11813.04
    assert lsr["summary"]["result_status"] == "priced_partial"


def test_stage_v_exact_work_without_a_chosen_price_basis_stays_preliminary():
    """Every readiness base of an EXACT work row, and where its money lands.

    The norm and volume questions, and the structure of the calculation, are settled
    by the row itself.  The price question is not: with no ценовая база and no
    confirmation, the rate is the norm card's, so the amount is preliminary rather
    than confirmed and the position is not «полностью рассчитана»
    (ADR-16 § 7, acceptance § 12 "no false complete status").  The confirmed
    counterpart is ``test_resources_priced_from_the_chosen_book_are_confirmed_final``.
    """
    lsr = build_lsr_trace_from_visible_rows(
        [
            {
                "source_row": "PDF!R2",
                "row_role": "work",
                "basis": "ГЭСН 12-01-034-02",
                "title": "Устройство обрешетки",
                "quantity": "61",
                "unit": "м2",
                "norm_status": "EXACT",
            }
        ]
    )
    binding = lsr["row_bindings"][0]
    readiness = binding["readiness"]
    assert readiness["operation_defined"] is True
    assert readiness["norm_selected"] is True
    assert readiness["applicability_substantiated"] is True
    assert readiness["volume_verified"] is True
    # § 4: the structure question and the money question have separate answers.  The
    # position is built and carries a known amount, but its prices belong to nobody,
    # so it is not «полностью рассчитана» and is not counted as a calculated position.
    assert readiness["structure_calculated"] is True
    assert readiness["known_amount_present"] is True
    assert readiness["position_calculated"] is False
    assert readiness["prices_provided"] == "не по базе"
    assert readiness["price_from_norm_card"] is True
    assert readiness["price_ok"] is False
    assert lsr["summary"]["confirmed_amount"] == 0.0
    assert lsr["summary"]["preliminary_amount"] == 11813.04
    assert lsr["summary"]["selected_norms"] == 1
    assert lsr["summary"]["positions_built"] == 1
    assert lsr["summary"]["calculated_positions"] == 0
    assert lsr["summary"]["result_status"] == "priced_partial"


def test_stage_v_counts_are_separate_per_kind():
    lsr = build_lsr_trace_from_visible_rows(
        [
            {"source_row": "A!R1", "row_role": "header", "title": "Раздел"},
            {
                "source_row": "A!R2",
                "row_role": "work",
                "basis": "ГЭСН 12-01-034-02",
                "title": "Работа",
                "quantity": 61,
                "unit": "м2",
                "norm_status": "EXACT",
            },
            {
                "source_row": "A!R3",
                "row_role": "material",
                "work_row": "A!R2",
                "title": "Материал",
                "unit": "шт",
                "quantity": 2,
            },
            {
                "source_row": "A!R4",
                "row_role": "resource",
                "work_row": "A!R2",
                "title": "Ресурс",
            },
        ]
    )
    counts = lsr["summary"]["kind_counts"]
    assert counts["header"] == 1
    assert counts["work"] == 1
    assert counts["material"] == 1
    assert counts["resource"] == 1
    assert lsr["summary"]["selected_norms"] == 1
    # § 4 / tracker #59: two position rows were built, none of them is fully
    # calculated, and the two numbers are reported separately instead of one
    # standing in for the other.
    assert lsr["summary"]["positions_built"] == 2
    assert lsr["summary"]["calculated_positions"] == 0
    # The projection states one role per locator, so a heading or a resource line is
    # never counted as an unfinished work (§ 4: «заголовки не имеют применимости
    # "нет" как дефекта»).
    assert [item["row_role"] for item in lsr["row_projection"]] == [
        "header", "work", "material", "resource"
    ]
    for role, item in zip(
        ("header", "work", "material", "resource"), lsr["row_projection"], strict=True
    ):
        if role in {"header", "resource"}:
            assert item["norm_selected"] is None
            assert item["position_calculated"] is None
            assert not [
                blocker for blocker in (lsr.get("blockers") or [])
                if blocker["code"] == item["locator"]
            ]


def test_stage_v_coverage_accounts_header_without_gap():
    from proxy.services.lsr_source_coverage_service import build_source_coverage

    coverage = build_source_coverage(
        catalog_locators=["A!R1", "A!R2"],
        rows=[
            {"source_row": "A!R1", "row_role": "заголовок", "title": "Раздел 1"},
            {
                "source_row": "A!R2",
                "row_role": "work",
                "norm_code": "ГЭСН12-01-034-02",
            },
        ],
    )
    assert coverage["complete"] is True
    assert coverage["accounted"] == 2
    assert coverage["gaps"] == []


def test_stage_v_renderer_writes_readiness_column(tmp_path):
    from proxy.services.rim_trace_xlsx_service import render_lsr_xlsx
    from openpyxl import load_workbook

    lsr = build_lsr_trace_from_visible_rows(
        [
            {"source_row": "A!R1", "row_role": "header", "title": "Раздел"},
            {
                "source_row": "A!R2",
                "row_role": "work",
                "basis": "ГЭСН 12-01-034-02",
                "title": "Работа",
                "quantity": 61,
                "unit": "м2",
                "norm_status": "EXACT",
            },
        ]
    )
    out = tmp_path / "lsr.xlsx"
    render_lsr_xlsx(lsr, out)
    review = load_workbook(out)["Проверка"]
    headers = [cell.value for cell in review[1]]
    assert "Готовность строки" in headers
    column = headers.index("Готовность строки") + 1
    rows = list(review.iter_rows(min_row=2))
    text = "\n".join(str(row[column - 1].value) for row in rows if row[column - 1].value)
    # § 4: the sheet prints the seven questions in one wording, and a heading answers
    # «н/п» where it has no question rather than «нет» as if it were a defect.
    assert "цены=не по базе" in text
    assert "шифр выбран=н/п" in text
    assert "применимость обоснована=н/п" in text
    assert "расчёт структуры построен=да" in text
    assert "известная стоимость есть=да" in text
    assert "позиция полностью рассчитана=нет" in text
    # § 4 (tracker #54, #60): the remarks block below the rows carries the open
    # questions of this same revision instead of being an empty section.
    block = "\n".join(
        str(cell.value)
        for row in rows
        for cell in row
        if cell.value not in (None, "")
    )
    assert "Общие замечания и незакрытые позиции" in block
    assert "позиция полностью рассчитана — нет" in block
    assert "карточки нормы" in block


def test_a_card_resource_identity_reaches_the_operator_without_markup():
    """Installed 0.31.89, case 3 of the installed-trace check.

    The КАЦ question read «нужен КАЦ: Уайт-спирит (14.5.09.<em>11-01</em>02)»,
    because the emphasis the norm card puts around the matched part of a шифр
    travelled with the resource identity into every operator surface.  A code
    with tags in it is a code no ценовая база contains, so the question could
    not be answered.  Only tags are removed here: digits, dots and dashes stay
    exactly as the card has them.
    """
    trace = build_position_trace(
        {
            "code": "ГЭСН00-00-000-00",
            "name": "Окраска поверхности",
            "unit": "м2",
            "qty": 1,
            "nr_pct": 0,
            "sp_pct": 0,
            "resources": [
                {
                    "kind": "material",
                    "code": "14.5.09.<em>11-01</em>02",
                    "name": "Уайт-спирит <em>очищенный</em>",
                    "unit": "<em>л</em>",
                    "per_unit": 1,
                },
            ],
        }
    )

    summary = trace["summary"]
    flags = [str(item) for item in summary.get("flags") or []]
    reasons = [str(item) for item in summary.get("completeness_reasons") or []]
    row = next(item for item in trace["rows"] if item["type"] == "resource_material")

    assert any(item.startswith("нужен КАЦ:") for item in flags)
    assert not any("<" in item or ">" in item for item in flags)
    assert "price_missing:14.5.09.11-0102" in reasons
    assert row["columns"]["2"] == "14.5.09.11-0102"
    assert row["columns"]["3"] == "Уайт-спирит очищенный"
    assert row["columns"]["4"] == "л"
