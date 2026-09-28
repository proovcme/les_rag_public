"""Тест рендерера РИМ-трассы в XLSX по форме Приложения 3 к 421/пр.

Рендерер из ГОТОВОЙ трассы, не калькулятор → числа те же, что в build_position_trace.
Эталон ГЭСН12-01-034-02 @ 0.61 после полной детализации ОТм через ФСЭМ
(тот же trace, что сервис/endpoint-тесты) — см. EXPECTED_TOTAL ниже: сумма
пересобрана 28.09.2026 по компонентам и доказана каждой строкой трассы.
Позиция остаётся черновиком (ставка ОТ из карточки нормы помечена
card_price_without_basis), поэтому форма подписывает итог «Известная
стоимость позиции», а не «Всего по позиции».
"""

import asyncio
from pathlib import Path

from proxy.services import lsr_assembly_service as la
from proxy.services import rim_lsr_trace_service as rim
from proxy.services import rim_trace_xlsx_service as rim_xlsx


CODE = "ГЭСН12-01-034-02"
# Эталон пересобран 28.09.2026 и проверен по компонентам трассы (книга цен
# sankt-peterburg_2kv2026, правило начислений nrsp-12 = Приказ 812/пр п.12 и
# Приказ 774/пр п.12, НР 109 % и СП 57 % оба от ФОТ):
#   ОЗП 3750.23 (ОТ(ЗТ) 7.8934 чел.-ч × 475.11 руб./чел.-ч; ставка взята из
#                карточки нормы и помечена card_price_without_basis)
# + ЗПМ 490.00  (ОТм(ЗТм) fgis_current)                     = ФОТ 4240.23
# + ЭМ  640.59 (машины fgis_current, разделение по графе 8)
# + М    78.47 (гвозди fgis_base_index)                     = прямые 4959.29
# + НР 4621.85 + СП 2416.93 (оба от ФОТ)                    = итого 11998.07
# Прежний эталон 11896.35 записан в ba3d9e1e (11.07.2026) и не восстанавливается
# из подписанных компонентов текущей трассы; файл не входил в CURRENT_TESTS,
# поэтому расхождение не останавливало гейт.
EXPECTED_TOTAL = 11998.07
DRAFT_TOTAL_LABEL = "Известная стоимость позиции"
DRAFT_SUMMARY_LABEL = "ИЗВЕСТНАЯ РАССЧИТАННАЯ ЧАСТЬ БЕЗ НДС"
COMPLETE_TOTAL_LABEL = "Всего по позиции"


def _trace():
    book = la._resolve_book(None)
    return rim.build_position_trace(
        {"code": CODE, "qty": 0.61}, pricebook=book, k_ozp=1.0, k_em=1.0
    )


def _lsr_trace():
    book = la._resolve_book(None)
    positions = [
        {"code": CODE, "qty": 0.61, "section": "Раздел 1. Кровля"},
        {"code": CODE, "qty": 0.61, "section": "Раздел 2. Прочее"},
    ]
    return rim.build_lsr_trace(positions, pricebook=book, name="Смета на кровлю")


def _closed_trace():
    """Та же позиция, но ставка ОТ имеет источник, а не только карточку нормы.

    Черновик и закрытая позиция дают один и тот же денежный итог: право на
    число меняет подписи формы, а не деньги.
    """
    from proxy.services.gesn_service import get_norm

    resources = [dict(r) for r in (get_norm(CODE) or {}).get("resources") or []]
    for res in resources:
        if str(res.get("kind")) == "labor":
            res["price"] = 475.11
            res["price_source_ref"] = "ФГИС ЦС, 2кв2026, строка оплаты труда рабочих"
    return rim.build_position_trace(
        {"code": CODE, "qty": 0.61, "resources": resources},
        pricebook=la._resolve_book(None), k_ozp=1.0, k_em=1.0,
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
    assert trace["summary"]["full_amount"] == EXPECTED_TOTAL
    assert trace["rows"][-1]["label"] == COMPLETE_TOTAL_LABEL
    out = rim_xlsx.render_trace_xlsx(trace, tmp_path / "closed.xlsx")
    ws = openpyxl.load_workbook(out).active
    txt = " ".join(str(c.value) for row in ws.iter_rows() for c in row if c.value)
    assert COMPLETE_TOTAL_LABEL in txt and DRAFT_TOTAL_LABEL not in txt
    assert "Сметная стоимость" in txt


def test_render_produces_valid_xlsx(tmp_path):
    import openpyxl

    trace = _trace()
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

    out = rim_xlsx.render_trace_xlsx(_trace(), tmp_path / "t.xlsx")
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
    from proxy.routers.lsr import RimTraceRequest, lsr_rim_trace_export

    res = asyncio.run(
        lsr_rim_trace_export(
            RimTraceRequest(position={"code": CODE, "qty": 0.61}), _user=object()
        )
    )
    assert res["code"] == CODE
    assert res["summary"]["total"] == EXPECTED_TOTAL
    assert res["download"].startswith("/api/lsr/download?path=rim_trace_")
    assert Path(res["path"]).exists()


def test_render_lsr_multi_position_form(tmp_path):
    import openpyxl

    lsr = _lsr_trace()
    out = rim_xlsx.render_lsr_xlsx(lsr, tmp_path / "lsr.xlsx")
    assert out.exists() and out.stat().st_size > 0
    ws = openpyxl.load_workbook(out).active
    txt = " ".join(str(c.value) for row in ws.iter_rows() for c in row if c.value)
    # форма Приложения 3 + разделы + итоги разделов + общий свод
    assert "Приложение № 3" in txt and "ЛОКАЛЬНЫЙ СМЕТНЫЙ РАСЧЁТ" in txt
    assert "Раздел 1. Кровля" in txt and "Раздел 2. Прочее" in txt
    assert "Итого по разделу 1" in txt and "Итого по разделу 2" in txt
    # обе позиции черновые (ставка ОТ из карточки), поэтому общий свод не может
    # называться «ВСЕГО по смете» — он подписан известной рассчитанной частью
    assert DRAFT_SUMMARY_LABEL in txt
    # общий итог — формула по позициям, а не застывшая константа.
    total_row = next(row for row in ws.iter_rows() if row[2].value == DRAFT_SUMMARY_LABEL)
    assert str(total_row[11].value).startswith("=SUM(")
    assert lsr["summary"]["total"] == 2 * EXPECTED_TOTAL


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

    book = la._resolve_book(None)
    lsr = rim.build_lsr_trace([{"code": CODE, "qty": 0.61}], pricebook=book)
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
    # stage V added the "Готовность строки" column, so the review grid is 14 wide
    assert f"D{issue_row}:N{issue_row}" in {str(value) for value in review.merged_cells.ranges}
    assert review.column_dimensions["A"].width >= 20


def test_endpoint_lsr_trace_export_returns_download():
    from proxy.routers.lsr import LsrTraceRequest, lsr_multi_trace_export

    res = asyncio.run(
        lsr_multi_trace_export(
            LsrTraceRequest(
                positions=[
                    {"code": CODE, "qty": 0.61, "section": "Раздел 1"},
                    {"code": CODE, "qty": 0.61, "section": "Раздел 2"},
                ],
                name="Тест",
            ),
            _user=object(),
        )
    )
    assert res["name"] == "Тест"
    assert res["summary"]["total"] == 2 * EXPECTED_TOTAL
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
