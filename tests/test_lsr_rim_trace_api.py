"""Тест endpoint POST /api/lsr/rim-trace (handoff Codex, шаг #1).

Тонкая обёртка над rim_lsr_trace_service.build_position_trace; контракт /assemble НЕ трогает.
Эталон тот же, что в test_rim_lsr_trace_service → summary.total == 11813.04 после полного ФСЭМ.
"""

import asyncio

from proxy.routers.lsr import LsrRowsTraceRequest, RimTraceRequest, lsr_multi_trace_from_rows, lsr_rim_trace


def _trace(**kw):
    return asyncio.run(lsr_rim_trace(RimTraceRequest(**kw), _user=object()))


def test_endpoint_matches_service_baseline():
    result = _trace(position={"code": "ГЭСН12-01-034-02", "qty": 0.61})
    assert result["code"] == "ГЭСН12-01-034-02"
    assert result["summary"]["total"] == 11813.04
    assert isinstance(result["rows"], list) and result["rows"]


def test_endpoint_applies_coefficients():
    base = _trace(position={"code": "ГЭСН12-01-034-02", "qty": 0.61})
    coef = _trace(position={"code": "ГЭСН12-01-034-02", "qty": 0.61}, k_ozp=1.15, k_em=1.15)
    assert coef["summary"]["total"] > base["summary"]["total"]


def test_endpoint_book_none_is_safe():
    # book не задан → pricebook=None → трасса всё равно строится (цены могут быть missing, но не crash)
    result = _trace(position={"code": "ГЭСН12-01-034-02", "qty": 0.61}, book=None)
    assert "summary" in result and "rows" in result


def test_endpoint_lsr_trace_from_visible_rows_converts_quantity_and_blocks_unbound():
    result = asyncio.run(
        lsr_multi_trace_from_rows(
            LsrRowsTraceRequest(
                rows=[
                    {"basis": "ГЭСН 12-01-034-02", "title": "Устройство обрешетки", "quantity": "61", "unit": "м2"},
                    {"title": "Строка без выбранной нормы", "quantity": "1", "unit": "шт"},
                ],
                name="Видимые строки",
            ),
            _user=object(),
        )
    )

    assert result["summary"]["total"] == 11813.04
    assert result["summary"]["result_status"] == "priced_partial"
    assert result["summary"]["bound_rows"] == 1
    assert result["summary"]["unbound_rows"] == 1
    accepted = result["coverage"][0]
    assert accepted["validation"]["physical_quantity"] == 61.0
    assert accepted["validation"]["norm_quantity"] == 0.61
