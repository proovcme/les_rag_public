"""Вид решения по строке и его полнота.

Основание — прогон `sks-unit-20260911-0806`: из 70 строк 8 закрылись фразой «входит в
стоимость монтажа» без работы, количества и основания, и проверить их было нечем. В
книге такая строка не появляется, и «учтено ресурсом» неотличимо от «забыли».
"""

from __future__ import annotations

import pytest

from proxy.smeta_core.row_decision import (
    MATERIAL,
    RESOURCE,
    UNCLEAR,
    WORK,
    claims_inclusion,
    decision_gaps,
    decision_kind,
    describe_decision,
    included_reference,
)


def row(**fields: object) -> dict[str, object]:
    base = {
        "source_row": "995",
        "title": "Кабель витая пара U/UTP категория 5e",
        "unit": "м",
        "quantity": "366",
        "norm_code": "",
        "analogue": "",
        "coverage": "",
    }
    base.update(fields)
    return base


def test_a_norm_code_makes_it_a_work() -> None:
    assert decision_kind(row(norm_code="ГЭСНм08-02-398-01")) == WORK


@pytest.mark.parametrize(
    "code", ["", "-", "—", "нет", "не найдена", "норма не найдена", "отсутствует"]
)
def test_an_absence_marker_is_not_a_norm(code: str) -> None:
    """Этим модель сообщает, что нормы нет, а не называет её."""
    assert decision_kind(row(norm_code=code)) != WORK


def test_inclusion_without_a_norm_is_a_resource() -> None:
    assert decision_kind(row(coverage="Входит в стоимость монтажа кабеля")) == RESOURCE


@pytest.mark.parametrize(
    "text",
    [
        "Входит в стоимость монтажа",
        "входят в состав работ",
        "учтено в норме на прокладку",
        "учтён ресурсом работы",
        "включено в расценку",
    ],
)
def test_inclusion_is_recognised_in_its_usual_wordings(text: str) -> None:
    assert claims_inclusion(row(coverage=text)) is True


@pytest.mark.parametrize(
    "text",
    [
        "Не входит в стоимость монтажа",
        "не учтено в норме",
        "не включено в расценку",
    ],
)
def test_a_denial_is_not_a_claim_of_inclusion(text: str) -> None:
    """Отрицание переворачивает смысл: иначе «не входит» читалось бы как «входит»."""
    assert claims_inclusion(row(coverage=text)) is False


def test_an_explicit_kind_wins_over_the_text() -> None:
    """Названный вид — утверждение сметчика, текст рядом с ним лишь пересказ."""
    assert decision_kind(
        row(decision_kind="материал", coverage="входит в стоимость монтажа")
    ) == MATERIAL


def test_nothing_said_at_all_is_unclear() -> None:
    assert decision_kind(row()) == UNCLEAR


def test_a_resource_needs_the_work_it_belongs_to() -> None:
    """Без ссылки «входит в монтаж» непроверяемо: неизвестно, к чему отнесён материал."""
    gaps = decision_gaps(row(coverage="Входит в стоимость монтажа"))
    assert "не названа работа, в которую входит материал" in gaps


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Входит в монтаж по ГЭСНм08-02-398-01", "ГЭСНм08-02-398-01"),
        ("Учтено в работе строка 995", "строка 995"),
        ("Входит в стоимость монтажа СКС!R995", "СКС!R995"),
    ],
)
def test_the_work_is_read_from_the_text_when_no_field_is_given(
    text: str, expected: str
) -> None:
    assert included_reference(row(coverage=text)) == expected


def test_an_explicit_field_beats_the_text() -> None:
    assert included_reference(
        row(included_in="СКС!R990", coverage="входит в монтаж по ГЭСНм08-02-398-01")
    ) == "СКС!R990"


def test_a_complete_resource_decision_has_no_gaps() -> None:
    decision = describe_decision(
        row(
            decision_kind="ресурс",
            included_in="ГЭСНм08-02-395-01",
            quantity="120",
            analogue="крепёж учтён в норме на лоток",
        )
    )
    assert decision["kind"] == RESOURCE
    assert decision["complete"] is True
    assert decision["included_in"] == "ГЭСНм08-02-395-01"


def test_a_work_without_quantity_is_incomplete() -> None:
    assert "нет количества" in decision_gaps(
        row(norm_code="ГЭСНм08-02-398-01", quantity="")
    )


@pytest.mark.parametrize("quantity", ["", "0", "0,0", "—"])
def test_an_empty_quantity_does_not_count(quantity: str) -> None:
    """Ноль и прочерк в книге дают пустую строку — это не посчитанная позиция."""
    assert "нет количества" in decision_gaps(
        row(norm_code="ГЭСНм08-02-398-01", quantity=quantity)
    )


def test_an_incomplete_decision_keeps_its_kind() -> None:
    """Подмена вида скрыла бы разницу между «не смог решить» и «решил, но не обосновал»."""
    decision = describe_decision(row(coverage="Входит в стоимость монтажа"))
    assert decision["kind"] == RESOURCE
    assert decision["complete"] is False


def test_unclear_without_a_reason_is_itself_a_gap() -> None:
    assert "не названа причина" in decision_gaps(row())


def test_a_stated_inclusion_beats_the_code_in_the_norm_field() -> None:
    """Шифр при заявленном включении называет работу-хозяина, а не норму этой строки.

    Живой прогон 11.09: восемь строк крепежа закрылись как «входит в работу
    ГЭСНм08-02-395-01» с этим же шифром в поле нормы. По шифру они прошли бы
    самостоятельными работами по норме на лоток — каждая со своим количеством, то есть
    лоток был бы посчитан девять раз.
    """
    fastener = row(
        title="Гайка М8 с насечкой",
        norm_code="ГЭСНм08-02-395-01",
        quantity="500",
        analogue="входит в работу ГЭСНм08-02-395-01",
    )
    assert decision_kind(fastener) == RESOURCE
    assert included_reference(fastener) == "ГЭСНм08-02-395-01"
    assert decision_gaps(fastener) == ()


def test_a_norm_without_any_inclusion_claim_is_still_a_work() -> None:
    """Обратное не должно сломаться: шифр без заявления — обычная работа по норме."""
    assert decision_kind(
        row(norm_code="ГЭСНм08-02-395-01", analogue="лоток по установленным конструкциям")
    ) == WORK
