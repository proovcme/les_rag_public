"""Индекс «изделие → применённая норма»: что считать ресурсом под нормой.

Основание — разбор архива смет 11.09.2026. Строка ведомости именует изделие, норма
именует работу, и поиск по названиям работ их не связывает: на 56 нерешённых строках
прогона `sks-unit-20260911-0806` выдача пересеклась с реальной практикой в 11 случаях.
В готовых сметах связь записана прямо — ресурс стоит под своей нормой.
"""

from __future__ import annotations

import pytest

from tools.build_material_norm_index import (
    is_equipment,
    looks_like_material,
    material_title,
)


def row(number: str, code: str, title: str, unit: str, quantity: str = "1") -> list[str]:
    """Строка локальной сметы: номер, шифр, наименование, единица, количество."""
    return [number, code, title, unit, quantity]


@pytest.mark.parametrize(
    ("cells", "expected"),
    [
        # Оборудование по ссылке на том проекта — то, ради чего индекс и собирается.
        (row("2 О", "Том 11.3.3 стр.12 п.1", "Процессор управления 3-Series", "шт."), True),
        (row("", "Демонтируемый материал", "Кабель BC5E-4-LSHF", "м", "3200"), True),
        (row("", "ФССЦ-25.2.01.01", "Кабель UTP 4 пары категории 5e", "100 м"), True),
        # Строка самой нормы ресурсом не является: шифр расценки её выдаёт.
        (row("1", "ТЕРм11-04-008-01", "Съемные и выдвижные блоки", "1 шт.", "30"), False),
        # Итоги и накрутки стоят там же, где ресурсы, но изделием не являются.
        (row("", "", "Итого прямые затраты по разделу", "", "12345"), False),
        (row("", "", "Накладные расходы", "", "68%"), False),
        (row("", "", "Сметная прибыль", "", "44%"), False),
        (row("", "", "В том числе, справочно:", "", "")[:4] + ["1"], False),
        (row("", "НР", "Производство монтажных работ", "", "1")[:5], False),
        # Без единицы измерения строка ресурсом не считается: так выглядят заголовки.
        (row("", "", "Кабель витая пара", "", "1"), False),
        # Наименование из одних цифр и прочерков ничего не сообщает об изделии.
        (row("", "", "-- 12 --", "шт"), False),
    ],
)
def test_resource_row_is_told_apart_from_norm_and_totals(
    cells: list[str], expected: bool
) -> None:
    assert looks_like_material(cells) is expected


def test_short_row_is_not_a_resource() -> None:
    """Меньше четырёх граф — не строка позиции: обращение к `cells[3]` упало бы."""
    assert looks_like_material(["1", "ТЕРм11-04-008-01"]) is False


@pytest.mark.parametrize(
    ("mark", "expected"),
    [("О", True), ("о", True), (" 2 О ", False), ("", False), ("1", False)],
)
def test_equipment_flag_is_read_from_the_number_column(mark: str, expected: bool) -> None:
    """Флаг «О» отделяет оборудование от расходного материала."""
    assert is_equipment(mark) is expected


def test_service_tail_is_cut_from_the_material_title() -> None:
    """Хвост сметной программы дошёл бы до модели как подсказка несуществующего шифра."""
    assert material_title(
        "Кабель UTP 4 пары ИНДЕКС К ПОЗИЦИИ: ТЕРм10-06-010-01"
    ) == "Кабель UTP 4 пары"
