"""Тест endpoint POST /api/lsr/rim-trace (handoff Codex, шаг #1).

Тонкая обёртка над rim_lsr_trace_service.build_position_trace; контракт /assemble НЕ трогает.

Этот файл проверяет только контракт эндпоинта: он отдаёт ровно тот расчёт, что сервис, и
никоим образом не пересобирает его по-своему.  Суммы при этом закреплены не за установленной
на машине книгой, а за детерминированной ценовой книгой эталона из
``tests/test_rim_lsr_trace_service.py``: её строки — замер книги ``sankt-peterburg_2kv2026``
(``stage_b/live_830/gold_rebaseline_830.json``), зафиксированный в тесте, чтобы результат не
менялся от того, какая ценовая база лежит у оператора.  Разбор итога по подписанным
компонентам — там же, в ``GOLD_*``.

Позиция ``ГЭСН12-01-034-02`` при 0,61 по книге эталона:
    ОЗП 4 006,37 + ЭМ 1 130,59 + М 78,47 = прямые 5 215,43
    ФОТ 4 496,37 = ОЗП + ЗПМ 490,00;  НР 4 901,04 (109 %) + СП 2 562,93 (57 %)
    итого 12 679,40;  строка 11.1.03.01-0076 «Бруски» в книге отсутствует → дыра названа.
Та же позиция с k_озп = k_эм = 1,15 (коэффициент умножает количества ресурсов, ставки
остаются ставками книги): ОЗП 4 607,33 + ЭМ 1 300,18 + М 78,47 = прямые 5 985,98;
ФОТ 5 170,83 = ОЗП + ЗПМ 563,50; НР 5 636,20 + СП 2 947,37 → итого 14 569,55.
"""

import asyncio
from pathlib import Path

import pytest

from proxy.routers.lsr import (
    LsrRowsTraceRequest,
    RimTraceRequest,
    lsr_multi_trace_from_rows,
    lsr_rim_trace,
)
from proxy.services import lsr_assembly_service as la
from proxy.services import rim_lsr_trace_service as rim
from tests import test_rim_lsr_trace_service as gold
from tests.lsr_gold_pricebook import gold_pricebook  # noqa: F401  (фикстура ниже по имени)


CODE = gold.CODE
GOLD_TOTAL = gold.GOLD_TOTAL
GOLD_OZP, GOLD_EM, GOLD_MAT = gold.GOLD_OZP, gold.GOLD_EM, gold.GOLD_MAT
GOLD_HOLE = gold.GOLD_HOLE
K_TOTAL = 14569.55  # разбор — в докстринге above; сумма пересчитывается по строкам GOLD_*
NO_BASIS_TOTAL = 0.0


def _trace(**kw):
    return asyncio.run(lsr_rim_trace(RimTraceRequest(**kw), _user=object()))


@pytest.mark.parametrize("gold_pricebook", ["spb"], indirect=True)
def test_endpoint_matches_service_baseline(gold_pricebook):
    # страж герметичности: книгу, по которой считаются деньги ниже, разрешила фикстура,
    # а не установленный на машине дефолт — иначе эталон зависел бы от содержимого
    # data/price_base оператора.
    assert la._resolve_book(None) is gold_pricebook

    result = _trace(position={"code": CODE, "qty": 0.61})
    service = rim.build_position_trace({"code": CODE, "qty": 0.61}, pricebook=gold_pricebook)

    assert result["code"] == CODE
    assert result["summary"]["total"] == GOLD_TOTAL
    assert result["summary"] == service["summary"]
    assert isinstance(result["rows"], list) and result["rows"]
    # деньги позиции закрыты книгой, кроме одной строки → черновик с названной дырой
    assert result["summary"]["amount_status"] == "partial"
    assert result["summary"]["completeness_reasons"] == [GOLD_HOLE]
    assert result["summary"]["full_amount"] is None


@pytest.mark.parametrize("gold_pricebook", ["spb"], indirect=True)
def test_endpoint_applies_coefficients(gold_pricebook):
    base = _trace(position={"code": CODE, "qty": 0.61})
    coef = _trace(position={"code": CODE, "qty": 0.61}, k_ozp=1.15, k_em=1.15)

    assert base["summary"]["total"] == GOLD_TOTAL
    # коэффициент умножает количество ресурсов, поэтому ставка остаётся ставкой книги,
    # а сумма меняется предсказуемо — это и проверяется, а не «стало больше»
    assert coef["summary"]["ozp"] == round(GOLD_OZP * 1.15, 2) == 4607.33
    assert coef["summary"]["em"] == round(GOLD_EM * 1.15, 2) == 1300.18
    assert coef["summary"]["mat"] == GOLD_MAT
    assert coef["summary"]["total"] == K_TOTAL


@pytest.mark.parametrize("gold_pricebook", ["none"], indirect=True)
def test_endpoint_book_none_is_safe(gold_pricebook):
    """book не задан → pricebook=None → расчёт не изобретает деньги.

    Каноническая база не несёт цен (0 из 63 673 строк труда пишут ставку), поэтому
    позиция без выбранной книги обязана сойтись в нуль и назвать каждую дыру, а не
    упасть и не показать сумму «по карточке».
    """
    result = _trace(position={"code": CODE, "qty": 0.61}, book=None)

    assert result["summary"]["total"] == NO_BASIS_TOTAL
    assert result["summary"]["amount_status"] == "partial"
    assert result["summary"]["completeness_reasons"] == gold.NO_BASIS_REASONS
    assert result["summary"]["card_priced_resources"] == []
    assert len(result["rows"]) and result["summary"]["labor_qty"] == gold.GOLD_LABOR_QTY


@pytest.mark.parametrize("gold_pricebook", ["spb"], indirect=True)
def test_endpoint_lsr_trace_from_visible_rows_converts_quantity_and_blocks_unbound(
    gold_pricebook, monkeypatch, tmp_path
):
    """from-rows считает привязанную строку книгой эталона и остаётся черновиком.

    Ревизия пишется в ``tmp_path``: маршрут сохраняет неизменяемую ревизию, и без
    подмены корня тест оседал бы в рабочем ``storage/smeta_revisions``.
    """
    from proxy.smeta_core import revision_store

    monkeypatch.setattr(revision_store, "DEFAULT_ROOT", tmp_path)

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

    assert result["summary"]["total"] == GOLD_TOTAL  # считает только привязанная строка
    assert result["summary"]["result_status"] == "priced_partial"
    assert result["summary"]["bound_rows"] == 1
    assert result["summary"]["unbound_rows"] == 1
    accepted = result["coverage"][0]
    assert accepted["validation"]["physical_quantity"] == 61.0
    assert accepted["validation"]["norm_quantity"] == 0.61
    # строка без шифра нормы остаётся вопросом к оператору: код норму не выбирает
    blocked = result["coverage"][1]
    assert blocked["status"] == "norm_selection_required"
    assert blocked["message"] == "модель или пользователь ещё не выбрал норму"
    assert {"code": "norm_selection_required", "work_id": blocked["work_id"]} in result["blockers"]
    assert Path(result["revision"]["path"]).resolve().parent == tmp_path.resolve()
