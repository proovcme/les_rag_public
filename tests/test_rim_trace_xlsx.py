"""Тест рендерера РИМ-трассы в XLSX по форме Приложения 4 к 421/пр (форма ГРАНД-Сметы; handoff #2).

Рендерер из ГОТОВОЙ трассы, не калькулятор → числа те же, что в build_position_trace.
Эталон ГЭСН12-01-034-02 @ 0.61 → summary.total == 11813.04 (тот же, что сервис/endpoint-тесты).
"""

import asyncio
from pathlib import Path

from proxy.services import lsr_assembly_service as la
from proxy.services import rim_lsr_trace_service as rim
from proxy.services import rim_trace_xlsx_service as rim_xlsx


def _trace():
    book = la._resolve_book(None)
    return rim.build_position_trace(
        {"code": "ГЭСН12-01-034-02", "qty": 0.61}, pricebook=book, k_ozp=1.0, k_em=1.0
    )


def test_render_produces_valid_xlsx(tmp_path):
    import openpyxl

    trace = _trace()
    out = rim_xlsx.render_trace_xlsx(trace, tmp_path / "trace.xlsx")
    assert out.exists() and out.stat().st_size > 0
    ws = openpyxl.load_workbook(out).active
    assert "ЛСР" in ws.title or "Прил" in ws.title
    # итог позиции из summary отрендерен (рендер не теряет/не пересчитывает число)
    vals = [c.value for row in ws.iter_rows() for c in row]
    assert trace["summary"]["total"] in vals


def test_appendix4_header_and_graphs_present(tmp_path):
    import openpyxl

    out = rim_xlsx.render_trace_xlsx(_trace(), tmp_path / "t.xlsx")
    txt = " ".join(str(c.value) for row in openpyxl.load_workbook(out).active.iter_rows() for c in row if c.value)
    # форма Приложения 4: шапка ГРАНД + графы + свод
    assert "Приложение № 4" in txt and "ЛОКАЛЬНЫЙ СМЕТНЫЙ РАСЧЁТ" in txt and "Сметная стоимость" in txt
    assert "Обоснование" in txt and "Наименование работ и затрат" in txt
    assert "Всего по позиции" in txt and "ОТ(ЗТ)" in txt and "ЭМ" in txt


def test_endpoint_export_returns_download():
    from proxy.routers.lsr import RimTraceRequest, lsr_rim_trace_export

    res = asyncio.run(
        lsr_rim_trace_export(
            RimTraceRequest(position={"code": "ГЭСН12-01-034-02", "qty": 0.61}), _user=object()
        )
    )
    assert res["code"] == "ГЭСН12-01-034-02"
    assert res["summary"]["total"] == 11813.04  # эталон, тот же что сервис-тест
    assert res["download"].startswith("/api/lsr/download?path=rim_trace_")
    assert Path(res["path"]).exists()
