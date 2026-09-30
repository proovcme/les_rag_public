"""Тест рендерера РИМ-трассы в XLSX по форме Приложения 3 к 421/пр.

Рендерер из ГОТОВОЙ трассы, не калькулятор → проверяется форма: графы 1-12, шапка РИМ,
подписи итога, лист «Проверка».

Every number this file pins is written down below and recomputable on paper: the resource
composition of ``ГЭСН12-01-034-02`` as the canonical base card states it (its own шифры,
units and consumptions) and rates the test itself chooses.  A base card carries no prices at
all — measured 0 of 63 673 labour rows write one, and its machine and material rows carry
none — so the card-price branch is reachable only when the test hands the calculator a card
that states a rate, and the book branch only when the test names the book's rows.  The rates
here are round on purpose; they are not the money of any region's real ценовая база and not
the excluded demo seed's either (11 813.04 / 11 998.07 are named as demo artifacts in
stage_b/live_830/seed_vs_base_reconcile_830.md and nothing below reproduces them).

Позиция закрывается книгой: ставка труда берётся из строки 1-100-25, каждая цена имеет
владельца, и форма подписывает итог «Всего по позиции».  Черновик проверяется отдельно: та
же позиция книгой, в которой строки тарифа нет, считает труд ставкой самой карточки, ставка
помечается ``card_price_without_basis``, а итог остаётся «Известная стоимость позиции».
"""

import asyncio
from pathlib import Path

from proxy.services import lsr_assembly_service as la
from proxy.services import rim_lsr_trace_service as rim
from proxy.services import rim_trace_xlsx_service as rim_xlsx


CODE = "ГЭСН12-01-034-02"
CARD_NAME = "Устройство обрешетки с прозорами из брусков"  # the base card's own name
CARD_UNIT = "100 м2"  # the base card's own unit
QTY = 1.0  # one unit of the card: every expectation below is a per-unit product
NR_PCT, SP_PCT = 109, 57  # the ГЭСН:12 pair of config/domain/nr_sp_catalog.json

# Rates the chosen ценовая база holds for the card's own шифры (test-authored, round).
BOOK_PRICES = {
    "1-100-25": 500.00,            # Средний разряд работы 2.5, руб./чел.-ч
    "91.05.01-017": 900.00,        # Краны башенные 8 т, руб./маш.-ч
    "91.05.05-015": 1700.00,       # Краны на автомобильном ходу 16 т, руб./маш.-ч
    "91.14.02-001": 600.00,        # Автомобили бортовые 5 т, руб./маш.-ч
    "4-100-060": 800.00,           # ОТм 6 разряда, руб./чел.-ч
    "4-100-040": 600.00,           # ОТм 4 разряда, руб./чел.-ч
    "01.7.15.06-0111": 90000.00,   # Гвозди строительные, руб./т
    "11.1.03.01-0076": 25000.00,   # Бруски, руб./м3
}
# The rate the card itself states — the branch a base card cannot reach.
CARD_LABOR_RATE = 480.00

# Позиция, закрытая книгой выше:
#   ОЗП  6 470,00 = 12,94 чел.-ч × 500,00
#   ЭМ   1 710,00 = машины 908,00 (0,97×900 + 0,01×1700 + 0,03×600)
#                              + ЗПМ  802,00 (0,97×800 + 0,01×800 + 0,03×600)
#   М   10 135,00 = гвозди 0,0015×90 000 + бруски 0,4×25 000
#   прямые 18 315,00;  ФОТ 7 272,00 = ОЗП + ЗПМ
#   НР 7 926,48 (109 % от ФОТ) + СП 4 145,04 (57 % от ФОТ)  = итого 30 386,52
BASE_PRICED_TOTAL = 30386.52
# Тот же документ книгой без строки тарифа: труд считается ставкой карточки.
#   ОЗП  6 211,20 = 12,94 × 480,00, остальное как выше
#   прямые 18 056,20;  ФОТ 7 013,20;  НР 7 644,39 + СП 3 997,52 = итого 29 698,11
# Ровно тот же итог подписывает и закрытая форма, когда ставка получает владельца:
# право на число меняет подписи формы, а не деньги.
CARD_PRICED_TOTAL = 29698.11
DRAFT_TOTAL_LABEL = "Известная стоимость позиции"
DRAFT_SUMMARY_LABEL = "ИЗВЕСТНАЯ РАССЧИТАННАЯ ЧАСТЬ БЕЗ НДС"
COMPLETE_TOTAL_LABEL = "Всего по позиции"


def _resources(*, card_labor_rate=None, labor_owner=None):
    """The composition of ``CODE`` per 100 м2, as the canonical base card states it.

    The шифры, units and consumptions of the labour, machine and material rows are the base
    card's own (data/smeta_base/les_smeta_base.sqlite).  The machinist lines are the legacy
    split shape: the base writes a single aggregated «Затраты труда машинистов» row of
    1,01 маш.-ч, and these three add up to it, so the renderer is tested without letting the
    ФСЭМ detailer decide the money.  A base card states no rate, so ``card_labor_rate`` is
    what makes the card-price branch reachable at all.
    """
    labor = {"kind": "labor", "code": "1-100-25", "name": "Средний разряд работы 2.5",
             "unit": "чел.-ч", "per_unit": 12.94}
    if card_labor_rate is not None:
        labor["price"] = card_labor_rate
    if labor_owner:
        labor["price_source_ref"] = labor_owner
    return [
        labor,
        {"kind": "machine", "code": "91.05.01-017", "name": "Краны башенные, г/п 8 т",
         "unit": "маш.-ч", "per_unit": 0.97},
        {"kind": "machinist", "code": "4-100-060", "name": "ОТм 6 разряда",
         "unit": "чел.-ч", "per_unit": 0.97},
        {"kind": "machine", "code": "91.05.05-015",
         "name": "Краны на автомобильном ходу, г/п 16 т",
         "unit": "маш.-ч", "per_unit": 0.01},
        {"kind": "machinist", "code": "4-100-060", "name": "ОТм 6 разряда",
         "unit": "чел.-ч", "per_unit": 0.01},
        {"kind": "machine", "code": "91.14.02-001", "name": "Автомобили бортовые, г/п до 5 т",
         "unit": "маш.-ч", "per_unit": 0.03},
        {"kind": "machinist", "code": "4-100-040", "name": "ОТм 4 разряда",
         "unit": "чел.-ч", "per_unit": 0.03},
        {"kind": "material", "code": "01.7.15.06-0111", "name": "Гвозди строительные",
         "unit": "т", "per_unit": 0.0015},
        {"kind": "material", "code": "11.1.03.01-0076", "name": "Бруски",
         "unit": "м3", "per_unit": 0.4},
    ]


class _Book:
    """Выбранная ценовая база: точный поиск по шифру, строки — BOOK_PRICES выше."""

    def __init__(self, *without) -> None:
        self._prices = {
            code: price for code, price in BOOK_PRICES.items() if code not in without
        }

    def lookup(self, code):
        price = self._prices.get(str(code or "").strip())
        return None if price is None else {"price_current": price, "price_current_eff": price}


def _position(**overrides) -> dict:
    position = {
        "code": CODE, "name": CARD_NAME, "unit": CARD_UNIT, "qty": QTY,
        "nr_pct": NR_PCT, "sp_pct": SP_PCT,
    }
    position.update(overrides)
    return position


def _trace():
    """Позиция, закрытая выбранной книгой: каждая ставка имеет владельца."""
    return rim.build_position_trace(
        _position(resources=_resources()), pricebook=_Book(), k_ozp=1.0, k_em=1.0
    )


def _draft_trace():
    """Тот же документ книгой без строки тарифа: ОЗП остаётся ставкой карточки."""
    return rim.build_position_trace(
        _position(resources=_resources(card_labor_rate=CARD_LABOR_RATE)),
        pricebook=_Book("1-100-25"), k_ozp=1.0, k_em=1.0,
    )


def _lsr_trace():
    return rim.build_lsr_trace(
        [
            {**_position(), "section": "Раздел 1. Кровля"},
            {**_position(), "section": "Раздел 2. Прочее"},
        ],
        pricebook=_Book(),
        name="Смета на кровлю",
    )


def _draft_lsr_trace():
    def _draft_position(section):
        return {
            **_position(resources=_resources(card_labor_rate=CARD_LABOR_RATE)),
            "section": section,
        }

    return rim.build_lsr_trace(
        [_draft_position("Раздел 1. Кровля"), _draft_position("Раздел 2. Прочее")],
        pricebook=_Book("1-100-25"),
        name="Смета на кровлю",
    )


def _closed_trace():
    """Та же позиция, но ставка ОТ имеет источник, а не только карточку нормы.

    Черновик и закрытая позиция дают один и тот же денежный итог (``CARD_PRICED_TOTAL``):
    право на число меняет подписи формы, а не деньги.
    """
    return rim.build_position_trace(
        _position(resources=_resources(
            card_labor_rate=CARD_LABOR_RATE,
            labor_owner="ФГИС ЦС, 3кв2026, строка оплаты труда рабочих",
        )),
        pricebook=_Book("1-100-25"), k_ozp=1.0, k_em=1.0,
    )



def test_closed_position_is_named_by_the_completed_form(tmp_path):
    """Закрытая позиция подписывается «Всего по позиции», черновик — нет.

    Пара к test_render_produces_valid_xlsx: пока ставка ОТ не имеет источника,
    итог остаётся известной рассчитанной частью; та же сумма после закрытия
    цены получает полную форму, и деньги при этом не меняются.
    """
    import openpyxl

    trace = _closed_trace()
    assert trace["summary"]["completeness_reasons"] == []
    assert trace["summary"]["full_amount"] == CARD_PRICED_TOTAL
    assert trace["rows"][-1]["label"] == COMPLETE_TOTAL_LABEL
    out = rim_xlsx.render_trace_xlsx(trace, tmp_path / "closed.xlsx")
    ws = openpyxl.load_workbook(out).active
    txt = " ".join(str(c.value) for row in ws.iter_rows() for c in row if c.value)
    assert COMPLETE_TOTAL_LABEL in txt and DRAFT_TOTAL_LABEL not in txt
    assert "Сметная стоимость" in txt


def test_the_chosen_base_closes_the_labour_of_the_card(tmp_path):
    """Строка тарифа в книге → позиция перестаёт быть черновиком.

    Тот же документ и те же ресурсы, только книга держит строку 1-100-25: ОЗП
    считается 500,00 руб./чел.-ч из базы, итог получает подпись «Всего по
    позиции», и ни одна ставка карточки не числится деньгами без владельца.
    """
    import openpyxl

    trace = _trace()
    assert trace["summary"]["full_amount"] == BASE_PRICED_TOTAL
    assert trace["summary"]["ozp"] == 6470.00
    assert trace["summary"]["card_priced_resources"] == []
    assert trace["summary"]["amount_status"] == "complete"
    out = rim_xlsx.render_trace_xlsx(trace, tmp_path / "priced.xlsx")
    txt = " ".join(str(c.value) for row in openpyxl.load_workbook(out).active.iter_rows() for c in row if c.value)
    assert COMPLETE_TOTAL_LABEL in txt and DRAFT_TOTAL_LABEL not in txt
    assert "1-100-25" in txt


def test_render_produces_valid_xlsx(tmp_path):
    import openpyxl

    trace = _draft_trace()
    out = rim_xlsx.render_trace_xlsx(trace, tmp_path / "trace.xlsx")
    assert out.exists() and out.stat().st_size > 0
    ws = openpyxl.load_workbook(out).active
    assert "ЛСР" in ws.title or "Прил" in ws.title
    # XLSX теперь редактируемый: итог позиции — формула, immutable число остаётся в JSON trace.
    # Незакрытая ставка ОТ => черновик, и итог подписан как известная (рассчитанная) часть.
    total_row = next(row for row in ws.iter_rows() if row[2].value == DRAFT_TOTAL_LABEL)
    assert str(total_row[11].value).startswith("=SUM(")


def test_appendix3_rim_header_and_graphs_present(tmp_path):
    import openpyxl

    out = rim_xlsx.render_trace_xlsx(_draft_trace(), tmp_path / "t.xlsx")
    txt = " ".join(str(c.value) for row in openpyxl.load_workbook(out).active.iter_rows() for c in row if c.value)
    # форма Приложения 3: шапка РИМ + графы + свод
    assert "Приложение № 3" in txt and "ЛОКАЛЬНЫЙ СМЕТНЫЙ РАСЧЁТ" in txt and "Сметная стоимость" in txt
    assert "Обоснование" in txt and "Наименование работ и затрат" in txt
    assert "Индекс" in txt and "Сметная стоимость в текущем уровне цен всего" in txt
    # черновик не называет себя сметной стоимостью: шапка пишет «Стоимость
    # рассчитанной части», а итог позиции — «Известная стоимость позиции»
    assert "Стоимость рассчитанной части" in txt
    assert DRAFT_TOTAL_LABEL in txt and "ОТ(ЗТ)" in txt and "ЭМ" in txt
    assert "Составлен ресурсно-индексным методом (РИМ)" in txt


def test_missing_resource_price_stays_blank_in_editable_xlsx(tmp_path):
    import openpyxl

    trace = rim.build_position_trace({
        "code": "ГЭСН00-00-000-00",
        "name": "Тестовая работа",
        "unit": "шт",
        "qty": 1,
        "nr_pct": 0,
        "sp_pct": 0,
        "resources": [{
            "kind": "material", "code": "01.1", "name": "Материал без цены",
            "unit": "шт", "per_unit": 1,
        }],
    })
    out = rim_xlsx.render_trace_xlsx(trace, tmp_path / "missing-price.xlsx")
    ws = openpyxl.load_workbook(out, data_only=False).active
    row = next(row for row in ws.iter_rows() if row[2].value == "Материал без цены")
    assert row[9].value is None
    assert row[11].value is None


def test_xlsx_work_row_keeps_official_norm_title_and_source_description(tmp_path):
    import openpyxl

    trace = rim.build_position_trace({"code": CODE, "qty": 0.61, "name": "Фактическая работа из ВОР"})
    out = rim_xlsx.render_trace_xlsx(trace, tmp_path / "official-and-source.xlsx")
    ws = openpyxl.load_workbook(out).active
    work_row = next(row for row in ws.iter_rows() if row[1].value == CODE)
    assert str(work_row[2].value).endswith(" / Фактическая работа из ВОР")
    assert str(work_row[2].value) != "Фактическая работа из ВОР"


def test_endpoint_export_returns_download():
    """Эндпоинт отдаёт тот же расчёт, что сервис, и файл, который можно скачать.

    Деньги позиции, развёрнутой из канонической базы, зависят от установленной на
    машине книги (``_resolve_book(None)``), поэтому здесь сверяется контракт «эндпоинт
    = сервис», а сами суммы закреплены в сервисных тестах на детерминированной книге.
    """
    from proxy.routers.lsr import RimTraceRequest, lsr_rim_trace_export

    position = {"code": CODE, "qty": 0.61}
    res = asyncio.run(lsr_rim_trace_export(RimTraceRequest(position=position), _user=object()))
    service = rim.build_position_trace(position, pricebook=la._resolve_book(None))

    assert res["code"] == CODE
    assert res["summary"]["total"] == service["summary"]["total"]
    assert res["summary"]["amount_status"] == service["summary"]["amount_status"]
    assert res["download"].startswith("/api/lsr/download?path=rim_trace_")
    assert Path(res["path"]).exists()


def test_render_lsr_multi_position_form(tmp_path):
    import openpyxl

    lsr = _draft_lsr_trace()
    out = rim_xlsx.render_lsr_xlsx(lsr, tmp_path / "lsr.xlsx")
    assert out.exists() and out.stat().st_size > 0
    ws = openpyxl.load_workbook(out).active
    txt = " ".join(str(c.value) for row in ws.iter_rows() for c in row if c.value)
    # форма Приложения 3 + разделы + итоги разделов + общий свод
    assert "Приложение № 3" in txt and "ЛОКАЛЬНЫЙ СМЕТНЫЙ РАСЧЁТ" in txt
    assert "Раздел 1. Кровля" in txt and "Раздел 2. Прочее" in txt
    assert "Итого по разделу 1" in txt and "Итого по разделу 2" in txt
    # обе позиции черновые (ставка ОТ не имеет владельца), поэтому общий свод не
    # может называться «ВСЕГО по смете» — он подписан известной рассчитанной частью
    assert DRAFT_SUMMARY_LABEL in txt
    # общий итог — формула по позициям, а не застывшая константа.
    total_row = next(row for row in ws.iter_rows() if row[2].value == DRAFT_SUMMARY_LABEL)
    assert str(total_row[11].value).startswith("=SUM(")
    assert lsr["summary"]["total"] == 2 * CARD_PRICED_TOTAL


def test_render_lsr_priced_by_the_base_signs_the_completed_summary(tmp_path):
    """База закрыла труд → свод сметы подписывается «ВСЕГО по смете без НДС».

    Пара к черновику: те же две позиции, та же форма, только строка тарифа в
    книге есть — и документ получает подпись завершённого расчёта.
    """
    import openpyxl

    lsr = _lsr_trace()
    out = rim_xlsx.render_lsr_xlsx(lsr, tmp_path / "lsr-priced.xlsx")
    txt = " ".join(
        str(c.value) for row in openpyxl.load_workbook(out).active.iter_rows() for c in row if c.value
    )
    assert "ВСЕГО по смете без НДС" in txt and DRAFT_SUMMARY_LABEL not in txt
    assert lsr["summary"]["total"] == 2 * BASE_PRICED_TOTAL


def test_render_lsr_prints_all_twelve_graphs_on_one_page_width(tmp_path):
    import openpyxl

    out = rim_xlsx.render_lsr_xlsx(_lsr_trace(), tmp_path / "print-ready.xlsx")
    ws = openpyxl.load_workbook(out).active

    assert ws.page_setup.orientation == ws.ORIENTATION_LANDSCAPE
    assert str(ws.page_setup.paperSize) == str(ws.PAPERSIZE_A4)
    assert ws.page_setup.fitToWidth == 1
    assert ws.page_setup.fitToHeight == 0
    assert ws.sheet_properties.pageSetUpPr.fitToPage is True
    assert ws.print_area == f"'ЛСР РИМ'!$A$1:$L${ws.max_row}"
    assert ws.print_title_rows is not None


def test_render_lsr_single_section_omits_section_header(tmp_path):
    import openpyxl

    lsr = rim.build_lsr_trace(
        [_position(resources=_resources(card_labor_rate=CARD_LABOR_RATE))],
        pricebook=_Book("1-100-25"),
    )
    out = rim_xlsx.render_lsr_xlsx(lsr, tmp_path / "one.xlsx")
    txt = " ".join(str(c.value) for row in openpyxl.load_workbook(out).active.iter_rows() for c in row if c.value)
    # один безымянный раздел → без «Раздел 1», но общий свод есть; черновик
    # подписывается известной рассчитанной частью, а не «ВСЕГО по смете»
    assert "Раздел 1" not in txt
    assert DRAFT_SUMMARY_LABEL in txt
    assert DRAFT_TOTAL_LABEL in txt


def test_lsr_header_uses_passed_source_metadata_and_review_issues_are_readable(tmp_path):
    import openpyxl

    lsr = _lsr_trace()
    lsr["row_bindings"] = []
    lsr["blockers"] = [{"code": "norm_selection_required", "work_id": "w1", "reason": "нужен подбор нормы"}]
    lsr["warnings"] = ["Длинное профессиональное замечание, которое должно занимать широкую область листа"]
    out = rim_xlsx.render_lsr_xlsx(
        lsr,
        tmp_path / "meta-review.xlsx",
        meta={
            "object": "ВОР монтаж БАП П1 13.05",
            "stroika": "Не указано в исходной ВОР",
            "lsr_no": "б/н",
            "osnovanie": "ВОР монтаж БАП П1 13.05.pdf",
            "subject": "Санкт-Петербург",
            "price_level": "2 квартал 2026",
        },
    )
    wb = openpyxl.load_workbook(out)
    header_text = " ".join(str(cell.value) for row in wb["ЛСР РИМ"].iter_rows(max_row=15) for cell in row if cell.value)
    assert "read_" not in header_text
    assert "ВОР монтаж БАП П1 13.05.pdf" in header_text
    assert "Санкт-Петербург" in header_text
    review = wb["Проверка"]
    issue_row = next(row[0].row for row in review.iter_rows() if row[0].value == "warning")
    assert review.cell(issue_row, 4).value.startswith("Длинное профессиональное замечание")
    # the remark cell spans to the last column of the review grid, and that last column
    # is whatever the sheet's own header row ends at — § 4 added the identity columns
    # («№ позиции», «Связь операций»), so hard-coding a width here would only re-break
    # every time the check sheet states one more real fact.
    last_column_letter = openpyxl.utils.get_column_letter(
        max(cell.column for cell in review[1] if cell.value not in (None, ""))
    )
    assert (
        f"D{issue_row}:{last_column_letter}{issue_row}"
        in {str(value) for value in review.merged_cells.ranges}
    )
    assert review.column_dimensions["A"].width >= 20


def test_endpoint_lsr_trace_export_returns_download():
    from proxy.routers.lsr import LsrTraceRequest, lsr_multi_trace_export

    positions = [
        {"code": CODE, "qty": 0.61, "section": "Раздел 1"},
        {"code": CODE, "qty": 0.61, "section": "Раздел 2"},
    ]
    res = asyncio.run(
        lsr_multi_trace_export(LsrTraceRequest(positions=positions, name="Тест"), _user=object())
    )
    service = rim.build_lsr_trace(
        positions, pricebook=la._resolve_book(None), name="Тест"
    )

    assert res["name"] == "Тест"
    # контракт эндпоинта: он отдаёт расчёт сервиса, а не пересобирает его по-своему
    assert res["summary"]["total"] == service["summary"]["total"]
    assert res["summary"]["result_status"] == service["summary"]["result_status"]
    assert len(res["sections"]) == 2
    assert res["download"].startswith("/api/lsr/download?path=lsr_trace_")
    assert Path(res["path"]).exists()
def test_stage_d_lsr_header_shows_price_basis_note(tmp_path):
    import openpyxl

    lsr = _lsr_trace()
    lsr["row_bindings"] = []
    out = rim_xlsx.render_lsr_xlsx(
        lsr,
        tmp_path / "basis.xlsx",
        meta={
            "subject": "Санкт-Петербург",
            "price_level": "3 квартал 2026",
            "price_basis_match": "mismatch",
            "price_basis_note": (
                "Запрошена ценовая база «3 квартал 2026», фактически применена "
                "«2 квартал 2026 г.»."
            ),
        },
    )
    wb = openpyxl.load_workbook(out)
    header_text = " ".join(
        str(cell.value)
        for row in wb["ЛСР РИМ"].iter_rows(max_row=16)
        for cell in row
        if cell.value
    )
    assert "фактически применена" in header_text
    assert "Наименование субъекта РФ" in header_text
