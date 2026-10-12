"""Построчная сверка ведомости, решений и итоговой книги.

Итог прогона говорил «12 норма в книге из 70» и не говорил, где остальные пятьдесят
восемь. «Учтено ресурсом работы» и «забыли» выглядят в книге одинаково — никак, — и
различить их можно только по решению (ревью Codex 11.09, шаг 6).
"""

from __future__ import annotations

from typing import Any

import pytest

from tools.smeta_book_audit import (
    DECIDED_NOT_IN_BOOK,
    INCOMPLETE,
    IN_BOOK_NO_PRICE,
    NEEDS_REVIEW,
    NO_DECISION,
    OWN_MATERIAL,
    PRICED,
    RESOURCE_OF_WORK,
    classify,
)


ROW = {"source_row": "995", "title": "Кабель витая пара", "unit": "м", "quantity": 366}

BOOK: dict[str, dict[str, Any]] = {
    "ГЭСНм08-02-398-01": {"norm_code": "ГЭСНм08-02-398-01", "total": 12345.67, "has_comment": False},
    "ГЭСНм08-02-395-01": {"norm_code": "ГЭСНм08-02-395-01", "total": None, "has_comment": True},
}


@pytest.fixture(autouse=True)
def book_positions():
    for entry in BOOK.values():
        entry['positions'] = [dict(title=ROW['title'], unit='100 м', quantity=3.66,
                                   total=entry['total'], has_comment=entry['has_comment'], taken=False)]


def decision(**fields: Any) -> dict[str, Any]:
    base = {"source_row": "995", "quantity": "3.66", "unit": "100 м"}
    base.update(fields)
    return base


def test_a_row_without_a_decision_is_named_as_such() -> None:
    """Молчание о строке — это состояние, а не отсутствие состояния."""
    assert classify(ROW, None, BOOK)["state"] == NO_DECISION


def test_a_priced_norm_is_the_only_finished_state() -> None:
    verdict = classify(ROW, decision(norm_code="ГЭСНм08-02-398-01"), BOOK)
    assert verdict["state"] == PRICED
    assert "12345.67" in verdict["detail"]


def test_a_norm_in_the_book_without_a_price_is_not_finished() -> None:
    """Строка дошла до книги, но не до денег — это разные вещи."""
    assert classify(ROW, decision(norm_code="ГЭСНм08-02-395-01"), BOOK)["state"] == IN_BOOK_NO_PRICE


def test_a_chosen_norm_missing_from_the_book_is_a_loss() -> None:
    assert classify(
        ROW, decision(norm_code="ГЭСНм99-99-999-99"), BOOK
    )["state"] == DECIDED_NOT_IN_BOOK


def test_a_complete_resource_decision_is_accounted_for() -> None:
    """Материал в составе работы — это учёт, а не пропажа, если работа названа."""
    verdict = classify(
        ROW,
        decision(
            decision_kind="ресурс",
            included_in="ГЭСНм08-02-395-01",
            analogue="крепёж учтён в норме на лоток",
        ),
        BOOK,
    )
    assert verdict["state"] == RESOURCE_OF_WORK
    assert "ГЭСНм08-02-395-01" in verdict["detail"]


def test_an_inclusion_without_the_work_is_not_accounted_for() -> None:
    """Ровно этим закрылись 8 строк прогона: проверить их было нечем."""
    verdict = classify(ROW, decision(coverage="Входит в стоимость монтажа"), BOOK)
    assert verdict["state"] == INCOMPLETE
    assert "не названа работа" in " ".join(verdict["gaps"])


def test_a_material_is_not_looked_for_in_the_book_as_a_norm() -> None:
    """Иначе законное отсутствие выдаётся за пропажу — так ошибалась первая сверка."""
    verdict = classify(
        ROW, decision(decision_kind="материал", analogue="поставка оборудования"), BOOK
    )
    assert verdict["state"] == OWN_MATERIAL


def test_an_unclear_row_keeps_its_reason() -> None:
    verdict = classify(
        ROW, decision(analogue="норма не найдена, нужен поиск по каталогу"), BOOK
    )
    assert verdict["state"] == NEEDS_REVIEW
    assert "норма не найдена" in verdict["detail"]


def test_an_empty_book_does_not_turn_decisions_into_losses() -> None:
    """Сверка без книги отвечает о решениях, а не приписывает им пропажу."""
    verdict = classify(
        ROW, decision(decision_kind="материал", analogue="поставка"), {}
    )
    assert verdict["state"] == OWN_MATERIAL


@pytest.mark.parametrize("quantity", ["", "0"])
def test_a_work_without_quantity_is_incomplete_even_if_priced(quantity: str) -> None:
    """Норма в книге не оправдывает решение без количества: считать было не из чего."""
    verdict = classify(
        ROW, decision(norm_code="ГЭСНм08-02-398-01", quantity=quantity), BOOK
    )
    assert verdict["state"] == INCOMPLETE
