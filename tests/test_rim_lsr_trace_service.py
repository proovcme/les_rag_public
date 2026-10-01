"""РИМ-трасса ЛСР: графы 2-12, цены ФГИС ЦС и итог позиции."""

from __future__ import annotations

from proxy.services.rim_lsr_trace_service import (
    build_lsr_trace,
    build_lsr_trace_from_visible_rows,
    build_position_trace,
    positions_from_visible_lsr_rows,
)


CODE = "ГЭСН12-01-034-02"


def test_mounting_norm_never_prices_an_explicit_supply_or_header(monkeypatch):
    from proxy.services import gesn_service
    calls = []
    monkeypatch.setattr(gesn_service, "get_norm", lambda *args: calls.append(args))
    for role in ("material", "equipment", "header"):
        row = {"source_row": "S!R7", "row_role": role, "norm_code": CODE, "norm_status": "EXACT",
               "title": "Authored item", "unit": "м²", "quantity": 61}
        bound = positions_from_visible_lsr_rows([row])
        assert not bound["positions"]
        binding = bound["row_bindings"][0]
        assert binding["status"] == "role_norm_conflict"
        assert binding["code"] == CODE and binding["row_role"] == role
        assert binding["source_row"] == row
    assert not calls


def test_model_accrual_rule_reaches_calculation_without_invented_default(monkeypatch):
    from proxy.services import gesn_service
    norm = {"code": "ГЭСНм08-02-409-09", "name": "Прокладка труб", "unit": "100 м", "resources": []}
    monkeypatch.setattr(gesn_service, "get_norm", lambda *_args, **_kwargs: norm)
    source = {"source_row": "СКС!R69", "title": "Прокладка труб", "unit": "м", "quantity": 1200,
              "norm_code": norm["code"], "row_role": "work", "nr_sp_rule_id": "nrsp-49.3"}
    position = positions_from_visible_lsr_rows([source])["positions"][0]
    assert position["nr_sp_rule_id"] == "nrsp-49.3"
    assert position["code"] == source["norm_code"] and position["qty"] == 12
    summary = build_position_trace(position)["summary"]
    assert summary["nr_sp_ownership"]["rule_id"] == "nrsp-49.3"
    assert (summary["nr_pct"], summary["sp_pct"]) == (97, 51)
    assert "nr_sp_unresolved" not in summary["completeness_reasons"]
    for rule_id, expected_status in [("", "ambiguous"), ("nrsp-1.1", "rejected")]:
        row = {**source, "nr_sp_rule_id": rule_id}
        other = positions_from_visible_lsr_rows([row])["positions"][0]
        gap = build_position_trace(other)["summary"]
        assert gap["nr_sp_ownership"]["catalog_status"] == expected_status
        assert "nr_sp_unresolved" in gap["completeness_reasons"]
        assert gap["nr_pct"] is None and gap["sp_pct"] is None


# ── эталон позиции: карточка основной базы + детерминированная ценовая книга ──
#
# Семя `config/domain/gesn_seed.yaml` больше не участвует в production-расчёте
# (`proxy/services/gesn_service.py::_merged_norms` merged только canonical-базу
# и оверлей ФГИС), а база цен не несёт вовсе.  Карточка `ГЭСН12-01-034-02`
# (source `structured_sqlite`, единица «100 м2») даёт нормативные расходы:
#   labor     1-100-25 «Средний разряд работы 2.5»  12,94 чел.-ч
#   machine   91.05.01-017 кран башенный 8 т         0,97 маш.-ч
#   machine   91.05.05-015 кран автомобильный 16 т   0,01 маш.-ч
#   machine   91.14.02-001 бортовой автомобиль 5 т   0,03 маш.-ч
#   machinist «Затраты труда машинистов», без шифра  1,01 маш.-ч (ФСЭМ → 4-100-*)
#   material  01.7.15.06-0111 гвозди строительные    0,0015 т
#   material  11.1.03.01-0076 бруски обрезные         0,4 м3
# Цены ниже — строки установленной книги `sankt-peterburg_2kv2026` (замер:
# `stage_b/live_830/gold_rebaseline_830.json`), зафиксированные здесь, чтобы
# тесты не зависели от того, какая книга лежит у оператора.
GOLD_QTY = 0.61
GOLD_PRICES = {
    "1-100-25": (507.56, "чел.-ч"),
    "91.05.01-017": (1048.03, "маш.-ч"),
    "91.05.05-015": (1644.26, "маш.-ч"),
    "91.14.02-001": (570.54, "маш.-ч"),
    # водители машинистов, на которые ФСЭМ детализирует строку «Затраты труда
    # машинистов» 1,01 маш.-ч при наличии выбранной книги
    "4-100-040": (596.61, "чел.-ч"),
    "4-100-060": (801.41, "чел.-ч"),
    "01.7.15.06-0111": (85761.36, "т"),
    # 11.1.03.01-0076 «Бруски обрезные…» в книге отсутствует намеренно: этой
    # строки нет в установленной книге, поэтому ресурс остаётся названной дырой.
    #
    # Две строки той же книги для второй эталонной позиции — карточка
    # «ГЭСНм08-03-575-01» (электромонтаж, «шт»), которую проверяет
    # tests/test_lsr_assembly_service.py: замер `data/price_base/sankt-peterburg_2kv2026.parquet`
    # (у болтов `price_current` пустой, а `price_current_eff` = 174,93 × 1,08 = 188,92 —
    # ровно то, что отдаёт движок сборки по полю `price_current_eff`).
    "1-100-42": (614.42, "чел.-ч"),
    "01.7.15.03-0042": (188.92, "кг"),
}

# Каждый эталонный иток — сумма строк карточки × цены книги, проверенная вручную:
GOLD_OZP = 4006.37        # 12,94 × 0,61 = 7,8934 чел.-ч × 507,56
GOLD_MACHINE = 640.59     # 0,5917×1048,03 + 0,0061×1644,26 + 0,0183×570,54
GOLD_ZPM = 490.00         # 0,0183×596,61 + 0,0061×801,41 + 0,5917×801,41
GOLD_EM = 1130.59         # ЭМ = машинам 640,59 + ЗПМ 490,00
GOLD_MAT = 78.47          # 0,0015 × 0,61 = 0,000915 т × 85 761,36
GOLD_DIRECT = 5215.43     # 4006,37 + 1130,59 + 78,47
GOLD_FOT = 4496.37        # ОЗП 4006,37 + ЗПМ 490,00
GOLD_NR = 4901.04         # ФОТ × 109 % (правило каталога nrsp-12, «Приказ 812/пр п.12»)
GOLD_SP = 2562.93         # ФОТ × 57 %  (правило каталога nrsp-12, «Приказ 774/пр п.12»)
GOLD_TOTAL = 12679.40     # прямые 5215,43 + НР 4901,04 + СП 2562,93
GOLD_LABOR_QTY = 7.8934
GOLD_MACHINIST_QTY = 0.6161
GOLD_HOLE = "price_missing:11.1.03.01-0076"

# Без выбранной книги позиция обязана сойтись в нуль и назвать каждую дыру:
# семь строк карточки, семь вопросов оператору (замер `no_book` в
# `stage_b/live_830/gold_rebaseline_830.json`).
NO_BASIS_REASONS = [
    "price_missing:91.14.02-001",
    "price_missing:91.05.05-015",
    "price_missing:91.05.01-017",
    "price_missing:Затраты труда машинистов",
    "price_missing:1-100-25",
    "price_missing:01.7.15.06-0111",
    "price_missing:11.1.03.01-0076",
]


class _Book:
    """Детерминированная ценовая книга: та же форма, что в `test_lsr_price_ownership`.

    `lookup(code)` отвечает строкой книги целиком, с «unit» — `_resolve_price_trace`
    сверяет единицу строки с единицей ресурса (`book_price_unit_conflict`), и книга,
    отвечающая только ценой, этого check не изображает.

    Поле `price_current_eff` дублирует `price_current`, как это делает настоящая
    конвертация `fgis_price_service` (текущая цена, иначе база × индекс): рутинный
    движок сборки ЛСР читает именно его, а РИМ-трасса — `price_current`.  Один
    двойник с обоими полями заведомо даёт двум движкам одну и ту же сумму на одной
    и той же книге (см. `tests/test_lsr_assembly_service.py`).
    """

    def __init__(self) -> None:
        self._prices = dict(GOLD_PRICES)

    def lookup(self, code: str):
        hit = self._prices.get(str(code).strip())
        if hit is None:
            return None
        return {
            "price_current": hit[0],
            "price_current_eff": hit[0],
            "unit": hit[1],
        }


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


def test_equivalent_source_measures_produce_identical_money_without_double_scaling():
    """61 m² and 0.61 hundreds of m² are the same physical work volume."""
    for quantity, unit in [(61, "м2"), (0.61, "100 м2"), (0.061, "1000 м²"), (6.1, "10 м²")]:
        authored = {"source_row": "R1", "row_role": "work", "title": "Same physical volume",
                    "norm_code": CODE, "quantity": quantity, "unit": unit}
        original = dict(authored)
        result = build_lsr_trace_from_visible_rows([authored], pricebook=_Book())
        assert result["summary"]["total"] == GOLD_TOTAL
        assert result["row_bindings"][0]["quantity_trace"]["norm_quantity"] == GOLD_QTY
        assert authored == original


def test_source_measure_multiplier_survives_si_conversion(monkeypatch):
    from proxy.services import gesn_service
    norm = {"code": CODE, "name": "Authored work", "unit": "т", "resources": []}
    monkeypatch.setattr(gesn_service, "get_norm", lambda *_args, **_kwargs: norm)
    authored = {"source_row": "R1", "row_role": "work", "title": "Authored work",
                "norm_code": CODE, "quantity": 1, "unit": "1000 кг"}
    position = positions_from_visible_lsr_rows([authored])["positions"][0]
    assert position["qty"] == 1
    assert position["quantity_trace"]["source_quantity"] == 1
    assert position["quantity_trace"]["source_unit"] == "1000 кг"


def test_source_measure_overflow_is_an_explicit_quantity_gap():
    from proxy.services.rim_lsr_trace_service import _norm_qty_from_visible_row
    quantity, trace = _norm_qty_from_visible_row(
        {"quantity": 2, "unit": str(10 ** 308) + " м"}, CODE, {"unit": "м"}
    )
    assert quantity is None
    assert trace["status"] == "needs_input"


def test_bad_numeric_row_preserves_good_row_calculation_and_gap():
    valid = {"source_row": "R1", "row_role": "work", "title": "First",
             "norm_code": CODE, "quantity": 61, "unit": "м2"}
    invalid = {**valid, "source_row": "R2", "conversion_factor": "305 м * 120 шт"}
    good = build_lsr_trace_from_visible_rows([valid], pricebook=_Book())
    combined = build_lsr_trace_from_visible_rows([valid, invalid], pricebook=_Book())
    assert combined["summary"]["total"] == good["summary"]["total"] > 0
    # The broken row is the only difference between the two revisions, so the one
    # surviving position is the gold one (base card rows × `_Book` prices).
    assert combined["summary"]["total"] == GOLD_TOTAL
    assert len(combined["row_bindings"]) == 2
    gap = combined["row_bindings"][1]
    assert gap["status"] == "needs_input"
    assert gap["source_row"] == invalid
    assert gap["quantity_trace"]["invalid_field"] == "conversion_factor"


def _rows_by_type(trace):
    return {row["type"]: row for row in trace["rows"]}


def test_rim_trace_from_base_norm_card_reproduces_gold_position():
    trace = build_position_trace({"code": CODE, "qty": GOLD_QTY}, pricebook=_Book())
    summary = trace["summary"]

    assert summary["flags"]
    # ADR-16 § 7 still bites, just on the other side of the card: the canonical base
    # carries no prices at all (0 of 63 673 labour rows), so nothing is counted from a
    # card and the only open flag is the resource the chosen book does not price.
    assert all(
        not str(flag).startswith("цена взята из карточки нормы") for flag in summary["flags"]
    )
    assert all("11.1.03.01-0076" in str(flag) for flag in summary["flags"])
    assert summary["card_priced_resources"] == []
    assert summary["amount_status"] == "partial"
    assert summary["full_amount"] is None
    assert summary["completeness_reasons"] == [GOLD_HOLE]
    assert summary["ozp"] == GOLD_OZP
    assert summary["em"] == GOLD_EM
    assert summary["mat"] == GOLD_MAT
    assert summary["direct"] == GOLD_DIRECT
    assert summary["fot"] == GOLD_FOT
    assert summary["nr"] == GOLD_NR
    assert summary["sp"] == GOLD_SP
    assert summary["total"] == GOLD_TOTAL
    # нормативные чел.-ч (в шапку многопозиционной формы) — те же, что в групп-строках
    assert summary["labor_qty"] == GOLD_LABOR_QTY
    assert summary["machinist_qty"] == GOLD_MACHINIST_QTY

    rows = _rows_by_type(trace)
    assert rows["work"]["columns"]["2"] == CODE
    assert rows["work"]["columns"]["4"] == "100 м2"
    assert rows["work"]["columns"]["7"] == 0.61
    assert rows["group_labor"]["columns"]["7"] == GOLD_LABOR_QTY
    assert rows["group_labor"]["columns"]["12"] == GOLD_OZP
    assert rows["group_machine"]["columns"]["12"] == GOLD_EM
    assert rows["group_machinist"]["columns"]["12"] == GOLD_ZPM
    assert rows["group_material"]["columns"]["12"] == GOLD_MAT
    # итог позиции — сумма напечатанных колонок, а не отдельное число калькулятора:
    # прямые = ОЗП+ЭМ+М, ФОТ = ОЗП+ЗПМ, всего = прямые+НР+СП
    assert rows["direct_total"]["columns"]["12"] == round(GOLD_OZP + GOLD_EM + GOLD_MAT, 2)
    assert rows["fot"]["columns"]["12"] == round(GOLD_OZP + GOLD_ZPM, 2)
    assert rows["position_total"]["columns"]["12"] == round(GOLD_DIRECT + GOLD_NR + GOLD_SP, 2)
    assert rows["nr"]["source"] == "Пр/812"
    assert rows["sp"]["source"] == "Пр/774"


def test_base_norm_card_without_a_chosen_book_totals_zero_and_names_every_hole():
    """The intended honest outcome of the new contract: 0, and seven named questions.

    The canonical base carries no prices (labour, machine and material rows alike), so
    a position calculated from a base card and no ценовая книга must not invent a sum:
    it lands on 0.0, stays ``partial``, and lists one ``price_missing:<шифр>`` reason per
    card row with the operator question that closes it.
    """
    summary = build_position_trace({"code": CODE, "qty": GOLD_QTY})["summary"]

    assert summary["total"] == 0.0
    assert summary["direct"] == 0.0
    assert summary["ozp"] == 0.0
    assert summary["em"] == 0.0
    assert summary["mat"] == 0.0
    assert summary["nr"] == 0.0
    assert summary["sp"] == 0.0
    assert summary["amount_status"] == "partial"
    assert summary["full_amount"] is None
    assert summary["card_priced_resources"] == []
    assert summary["completeness_reasons"] == NO_BASIS_REASONS
    # нормативные количества при этом не теряются: их даёт карточка, а не книга
    assert summary["labor_qty"] == GOLD_LABOR_QTY
    assert summary["machinist_qty"] == GOLD_MACHINIST_QTY
    questions = [str(flag) for flag in summary["flags"]]
    assert any(flag.startswith("нужна ставка ОЗП: Средний разряд работы 2.5 (1-100-25)")
               for flag in questions)
    assert any(flag.startswith("нужен КАЦ: Гвозди строительные (01.7.15.06-0111)")
               for flag in questions)
    assert any(flag.startswith("нужна цена эксплуатации машины: Краны башенные")
               for flag in questions)
    assert any(flag.startswith("нужна ставка ЗПМ: Затраты труда машинистов (—)")
               for flag in questions)
    assert len(questions) == len(NO_BASIS_REASONS)


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
    trace = build_position_trace(
        {"code": CODE, "qty": GOLD_QTY}, pricebook=_Book(), k_ozp=1.15, k_em=1.15
    )
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
    # each raised column is the uncoefficiented gold sum × 1,15 (7,8934×1,15 чел.-ч ×
    # 507,56 = 4607,33; 640,59×1,15 = 736,68; 490,00×1,15 = 563,50)
    assert summary["ozp"] == 4607.33
    assert summary["machine"] == 736.68
    assert summary["zpm"] == 563.50
    assert summary["ozp"] > GOLD_OZP
    assert summary["machine"] > GOLD_MACHINE
    assert summary["zpm"] > GOLD_ZPM
    # material takes no ОЗП/ЭМ coefficient, so it stays the gold 0,000915 т × 85 761,36
    assert summary["mat"] == GOLD_MAT
    assert summary["total"] == 14569.55
    assert summary["total"] > GOLD_TOTAL


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
    # ADR-16 § 7 on card-carried rates: an explicit resource line with a `price` but
    # no chosen book still travels through the `card_price` / `card_price_without_basis`
    # labelling.  The rule (3) re-baseline keeps that label check alive on data which
    # still triggers it, so the route is not silently retired when the demo seed
    # becomes test-only.  Every one of the three surviving labour rows was priced
    # from the norm card, so the position's amount is preliminary and each row is
    # named by its code both in ``card_priced_resources`` and in the operator flags.
    # Because the card is marked ``_source_kind == "seed_yaml"``, the engine also
    # raises the demo-seed integrity flag («норма взята из демо-семени…») alongside
    # them — a second, orthogonal ADR-16 § 7 check on the same resource line.
    summary = trace["summary"]
    assert {item["code"] for item in summary["card_priced_resources"]} == {
        "2-100-02", "2-100-03", "2-100-04",
    }
    assert summary["amount_status"] == "partial"
    assert summary["full_amount"] is None
    card_flags = [str(flag) for flag in summary["flags"]
                  if str(flag).startswith("цена взята из карточки нормы")]
    assert {flag.rsplit("(", 1)[1].rstrip(")") for flag in card_flags} == {
        "2-100-02", "2-100-03", "2-100-04",
    }
    assert "норма взята из демо-семени (LES_GESN_SEED_ENABLED/path), не из базы" in [
        str(flag) for flag in summary["flags"]
    ]
    assert "normative_source_demo_seed" in summary["completeness_reasons"]
    card_reasons = {
        str(reason).split(":", 1)[1]
        for reason in summary["completeness_reasons"]
        if str(reason).startswith("card_price_without_basis:")
    }
    assert card_reasons == {"2-100-02", "2-100-03", "2-100-04"}


def test_build_lsr_trace_multi_position_sections_and_grand_total():
    # две gold-позиции в двух разделах → общий итог = 2× эталон; итоги разделов и свод — Σ позиций
    positions = [
        {"code": CODE, "qty": 0.61, "section": "Раздел 1. Кровля"},
        {"code": CODE, "qty": 0.61, "section": "Раздел 2. Прочее"},
    ]
    lsr = build_lsr_trace(positions, pricebook=_Book(), name="Кровля и прочее")

    assert lsr["name"] == "Кровля и прочее"
    assert lsr["summary"]["positions"] == 2
    # Grouping into sections introduces no new problem: the only flags are the one
    # resource the chosen book does not price (11.1.03.01-0076), one per position.
    assert lsr["summary"]["flags"]
    assert all("11.1.03.01-0076" in str(flag) for flag in lsr["summary"]["flags"])
    assert lsr["summary"]["total"] == 25358.80  # 2 × 12 679,40 — gold позиции сохранён
    # свод суммирует позиции (прямые/ФОТ/НР/СП) — числа считает код, не LLM
    assert lsr["summary"]["direct"] == round(2 * GOLD_DIRECT, 2)
    assert lsr["summary"]["fot"] == round(2 * GOLD_FOT, 2)
    assert lsr["summary"]["nr"] == round(2 * GOLD_NR, 2)
    assert lsr["summary"]["sp"] == round(2 * GOLD_SP, 2)
    assert lsr["summary"]["labor_qty"] == round(2 * GOLD_LABOR_QTY, 6)

    secs = lsr["sections"]
    assert [s["section"] for s in secs] == ["Раздел 1. Кровля", "Раздел 2. Прочее"]
    assert secs[0]["total"] == GOLD_TOTAL and secs[1]["total"] == GOLD_TOTAL
    # каждый раздел несёт полные трассы позиций (для рендера формы)
    assert len(secs[0]["positions"]) == 1
    assert secs[0]["positions"][0]["summary"]["total"] == GOLD_TOTAL


def test_build_lsr_trace_groups_same_section_contiguously():
    # позиции одного раздела, вперемешку с другим, группируются → 2 раздела, не 3
    positions = [
        {"code": CODE, "qty": 0.61, "section": "A"},
        {"code": CODE, "qty": 0.61, "section": "B"},
        {"code": CODE, "qty": 0.61, "section": "A"},
    ]
    lsr = build_lsr_trace(positions, pricebook=_Book())

    assert [s["section"] for s in lsr["sections"]] == ["A", "B"]
    assert len(lsr["sections"][0]["positions"]) == 2
    assert lsr["sections"][0]["total"] == round(2 * GOLD_TOTAL, 2)
    assert lsr["summary"]["total"] == round(3 * GOLD_TOTAL, 2)


def test_build_lsr_trace_default_section_when_unspecified():
    # без поля section → один раздел «Без раздела», свод = одна позиция
    lsr = build_lsr_trace([{"code": CODE, "qty": 0.61}], pricebook=_Book())
    assert [s["section"] for s in lsr["sections"]] == ["Без раздела"]
    assert lsr["summary"]["total"] == GOLD_TOTAL


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
        pricebook=_Book(),
        name="Видимые строки",
    )

    assert lsr["summary"]["result_status"] == "priced_partial"
    assert lsr["summary"]["input_rows"] == 1
    assert lsr["summary"]["bound_rows"] == 1
    assert lsr["summary"]["total"] == GOLD_TOTAL
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
    draft = build_lsr_trace_from_visible_rows([row], pricebook=_Book(), name="Видимые строки")
    confirmed = build_lsr_trace_from_visible_rows(
        [{**row, "confirmed_price": 20000.0, "price_source": "operator"}],
        pricebook=_Book(),
        name="Видимые строки",
    )

    assert draft["summary"]["result_status"] == "priced_partial"
    assert draft["summary"]["confirmed_amount"] == 0.0
    assert draft["summary"]["preliminary_amount"] == GOLD_TOTAL

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
        pricebook=_Book(),
        name="Видимые строки",
    )

    assert lsr["summary"]["result_status"] == "priced_partial"
    assert lsr["summary"]["norms_status"] == "model_norms_partial"
    assert lsr["summary"]["bound_rows"] == 1
    assert lsr["summary"]["total"] == GOLD_TOTAL
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
        pricebook=_Book(),
        name="Видимые строки",
    )

    # A terminal EXACT status settles the norm question only.  The rates behind this
    # total belong to the chosen book, and ADR-16 § 7 keeps a position whose resource
    # list still contains a named price hole out of a final document.
    assert lsr["summary"]["result_status"] == "priced_partial"
    assert lsr["summary"]["norms_status"] == "model_norms_selected"
    assert lsr["summary"]["total"] == GOLD_TOTAL
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
    alone = build_lsr_trace_from_visible_rows([good], pricebook=_Book())
    combined = build_lsr_trace_from_visible_rows([good, bad], pricebook=_Book())
    assert combined["summary"]["total"] == alone["summary"]["total"] > 0
    # only the gated row is missing from the money: one gold position survives
    assert combined["summary"]["total"] == GOLD_TOTAL
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


def test_equivalent_measure_passes_real_catalog_adapter_and_money_trace(tmp_path, monkeypatch):
    from openpyxl import Workbook
    from proxy.services import attachment_source_catalog_service as catalog_module
    from proxy.services import lsr_workbook_adapter_service as adapter_module

    path = tmp_path / "Объёмы с масштабом.xlsx"
    wb = Workbook()
    wb.active.append(["Наименование", "Ед. изм.", "Количество"])
    wb.active.append(["Устройство обрешетки", "м²", 61])
    wb.save(path)
    catalog = catalog_module.load_tabular_source_catalog(path)
    monkeypatch.setattr(catalog_module, "load_catalog_from_attachment_id", lambda _: catalog)
    for qty, unit in [(61, "м2"), (0.61, "100 м2"), (0.061, "1000 м²")]:
        row = {"source_row": "Sheet!R2", "title": "Устройство обрешетки", "row_role": "work",
               "quantity": qty, "unit": unit, "norm_code": CODE, "nr_sp_rule_id": "nrsp-12"}
        assert catalog_module.compare_model_row_to_catalog(row, catalog) == []
        adapter_module._attach_catalog_facts([row], "read_test")
        trace = build_lsr_trace_from_visible_rows([row], pricebook=_Book())
        assert trace["row_bindings"][0]["status"] == "bound"
        assert trace["summary"]["total"] == GOLD_TOTAL
        assert row["quantity"] == qty and row["unit"] == unit

    wrong = {"source_row": "Sheet!R2", "title": "Монтаж обрешетки", "row_role": "work",
             "quantity": 61, "unit": "м", "norm_code": CODE}
    adapter_module._attach_catalog_facts([wrong], "read_test")
    assert build_lsr_trace_from_visible_rows([wrong], pricebook=_Book())["row_bindings"][0]["status"] == "unconfirmed_quantity"


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
        ],
        pricebook=_Book(),
    )
    header = next(item for item in lsr["row_bindings"] if item["row"] == "СКС!R1")
    assert header["status"] == "structure_accounted"
    assert header["readiness"]["header_row"] is True
    assert header["readiness"]["operation_defined"] is True
    assert header["readiness"]["norm_selected"] is None
    assert lsr["summary"]["kind_counts"]["header"] == 1
    # a heading adds no flag; the only flags name the one resource the chosen book
    # does not price (11.1.03.01-0076), one per calculated position
    assert lsr["summary"]["result_status"] == "priced_partial"
    assert not [flag for flag in lsr["summary"]["flags"] if "СКС!R1" in str(flag)]
    assert lsr["summary"]["flags"]
    assert all("11.1.03.01-0076" in str(flag) for flag in lsr["summary"]["flags"])
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
        ],
        pricebook=_Book(),
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
    assert lsr["summary"]["preliminary_amount"] == GOLD_TOTAL
    assert lsr["summary"]["result_status"] == "priced_partial"


def test_stage_v_exact_work_without_a_chosen_price_basis_stays_preliminary():
    """Every readiness base of an EXACT work row, and where its money lands.

    The norm and volume questions, and the structure of the calculation, are settled
    by the row itself.  The price question is not: the canonical base card states no
    prices at all, so with no ценовая книга and no confirmation the position carries
    no money whatsoever — every counted resource is a named hole (ADR-16 § 7,
    acceptance § 12 "no false complete status").  The priced counterpart is
    ``test_rim_trace_from_base_norm_card_reproduces_gold_position``, the confirmed
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
    # position is built from the card rows, but no rate has an owner, so there is no
    # known amount either — the row is not «полностью рассчитана».
    assert readiness["structure_calculated"] is True
    assert readiness["known_amount_present"] is False
    assert readiness["position_calculated"] is False
    assert readiness["prices_provided"] is False
    assert readiness["price_from_norm_card"] is False
    assert readiness["price_ok"] is False
    # the open questions are the card's seven rows, each named by its шифр
    assert readiness["open_reasons"] == NO_BASIS_REASONS
    assert lsr["summary"]["total"] == 0.0
    assert lsr["summary"]["confirmed_amount"] == 0.0
    assert lsr["summary"]["preliminary_amount"] == 0.0
    assert lsr["summary"]["selected_norms"] == 1
    assert lsr["summary"]["positions_built"] == 1
    assert lsr["summary"]["calculated_positions"] == 0
    assert lsr["summary"]["result_status"] == "priced_partial"
    # the structure survives the missing prices: нормативные quantities are printed
    position = lsr["sections"][0]["positions"][0]["summary"]
    assert position["labor_qty"] == GOLD_LABOR_QTY
    assert position["machinist_qty"] == GOLD_MACHINIST_QTY


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
        ],
        pricebook=_Book(),
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
    # «цены=нет» is the honest wording now: the chosen book prices every card row but
    # one, and no rate is applied from the card, so there is nothing to call «не по базе».
    assert "цены=нет" in text
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
    assert "price_missing:11.1.03.01-0076" in block
    assert "нужен КАЦ" in block


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
