"""Стабильные якоря строк ведомости — основание для работы в несколько проходов.

Измерение 10.09 показало физику: в окно модели помещаются свидетельства примерно по
18 запросам из 51, и настройкой бюджета этого не изменить — 32 768 токенов контекста,
22 528 на вход этапа ответа, минус профиль и текст ведомости остаётся 14 031 токен.
Значит длинная ведомость закрывается за несколько проходов.

Продолжать проход по номеру поискового запроса нельзя: соответствия один к одному со
строками ведомости у него нет — на 80 строк модель формулировала 51, 55 и 59 запросов.
Якорем должна быть сама строка исходного файла.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from proxy.smeta_core.vor_rows import (
    row_anchors,
    rows_from_attachment_text,
    slice_rows,
)

FIXTURE = Path("C:/Users/almax/Downloads/Telegram Desktop/СКС (2).xlsx")

pytestmark = pytest.mark.skipif(not FIXTURE.is_file(), reason="боевая ведомость недоступна")


def test_anchor_keeps_the_number_the_estimator_sees():
    rows = row_anchors(FIXTURE)
    assert rows, "ведомость должна разбираться"
    first = rows[0]
    # Номер из первой колонки — тот, по которому строку ищет человек и на который
    # ссылается модель в поле source_row.
    assert first["source_row"] == "984"
    assert "Шкаф напольный" in first["title"]
    assert first["sheet_row"] > 0
    assert first["unit"] == "шт."
    assert first["quantity"] == 2


def test_anchors_are_unique_and_ordered():
    rows = row_anchors(FIXTURE)
    numbers = [row["source_row"] for row in rows]
    assert len(numbers) == len(set(numbers)), "повторяющийся якорь сделает продолжение неоднозначным"
    assert numbers == sorted(numbers, key=int)


def test_slice_takes_a_portion_and_reports_the_rest():
    rows = row_anchors(FIXTURE)
    portion, rest = slice_rows(rows, limit=18)
    assert len(portion) == 18
    assert len(rest) == len(rows) - 18
    # Продолжение начинается ровно там, где закончилась порция.
    assert rest[0]["source_row"] == rows[18]["source_row"]


def test_slice_after_a_given_anchor():
    """Второй проход берёт строки после последней закрытой — по её якорю.

    Якорь — «лист!позиция», а не голый номер: позиция №1 есть на каждом листе книги,
    и продолжение по номеру останавливалось на первом совпадении (ревью Codex, R3).
    """
    from proxy.smeta_core.vor_rows import row_anchor

    rows = row_anchors(FIXTURE)
    portion, rest = slice_rows(rows, limit=5, after=row_anchor(rows[9]))
    assert portion[0]["source_row"] == rows[10]["source_row"]
    assert len(portion) == 5
    assert rest[0]["source_row"] == rows[15]["source_row"]


def test_unknown_anchor_starts_from_the_beginning():
    """Неизвестный якорь не должен молча терять всю ведомость."""
    rows = row_anchors(FIXTURE)
    portion, _rest = slice_rows(rows, limit=3, after="нет такой строки")
    assert portion[0]["source_row"] == rows[0]["source_row"]


ATTACHMENT_TEXT = """Файл: СКС (2).xlsx
Тип данных: таблица/спецификация. Строки ниже сохранены с номерами листов/строк.

## Лист: СКС
СКС!R1: № П.П | НАИМЕНОВАНИЕ РАБОТ И ЗАТРАТ | Артикул | Производитель | ЕД. ИЗМ | ОБЪЕМ
СКС!R3: 982 | Раздел 6.21. "МОНТАЖ СКС" | 0 | 0 | 0
СКС!R5: 983 | Оборудование | 0 | 0 | 0
СКС!R6: 984 | Hyperline TTR-4281 Шкаф напольный 42U | TTR-4281 | Hyperline | шт. | 2
СКС!R7: 985 | Hyperline CM-1U-ML Кабельный организатор | CM-1U-ML | Hyperline | шт. | 8
"""


def test_rows_are_read_from_the_attachment_text():
    """Вложение доходит текстом, а не файлом: разбирать надо то, что есть.

    Чат передаёт содержимое скрепки строкой вида «СКС!R6: 984 | наименование | …»,
    и лезть за файлом в хранилище ради номеров строк незачем.
    """
    from proxy.smeta_core.vor_rows import rows_from_attachment_text

    rows = rows_from_attachment_text(ATTACHMENT_TEXT)
    numbers = [row["source_row"] for row in rows]
    assert numbers == ["984", "985"], "заголовок, раздел и группа не позиции"
    assert rows[0]["title"].startswith("Hyperline TTR-4281")
    assert rows[0]["unit"] == "шт."
    assert rows[0]["quantity"] == 2
    assert rows[0]["sheet_row"] == 6


def test_text_without_a_table_gives_nothing():
    from proxy.smeta_core.vor_rows import rows_from_attachment_text

    assert rows_from_attachment_text("Файл: письмо.docx\n\nДобрый день!") == []
    assert rows_from_attachment_text("") == []


def test_attachment_rows_keep_the_original_cells():
    """Строка сохраняется целиком: артикул и производитель различают похожие позиции.

    Ревью Codex 10.09 (R2): порция отдавала лишь номер, наименование, единицу и
    количество, а выбор нормы делается по всей строке.
    """
    rows = rows_from_attachment_text(ATTACHMENT_TEXT)
    first = rows[0]
    assert first["raw"].startswith(first["source_row"])
    assert first["cells"][0] == first["source_row"]
    assert any("Hyperline" in str(cell) for cell in first["cells"])
    assert first["header"], "шапка таблицы объясняет ячейки"


def test_quantity_keeps_its_exact_value():
    """Формат :g держал шесть значащих цифр и портил количество до модели."""
    text = (
        "Файл: большие числа.xlsx\n"
        "ВОР!R1: № П.П | НАИМЕНОВАНИЕ РАБОТ И ЗАТРАТ | ЕД. ИЗМ | ОБЪЕМ\n"
        "ВОР!R2: 1 | Кабель силовой | м | 1234567.89\n"
    )
    row = rows_from_attachment_text(text)[0]
    assert row["quantity_text"] == "1234567.89"
    assert "1.23457e+06" not in row["raw"]


def test_the_same_position_number_on_two_sheets_gets_two_anchors():
    """Позиция №1 есть на каждом листе — якорь обязан их различать (ревью Codex, R3)."""
    text = (
        "Файл: Книга.xlsx\n"
        "СКС!R1: № П.П | НАИМЕНОВАНИЕ РАБОТ И ЗАТРАТ | ЕД. ИЗМ | ОБЪЕМ\n"
        "СКС!R2: 1 | Розетка RJ45 | шт. | 40\n"
        "ЭОМ!R1: № П.П | НАИМЕНОВАНИЕ РАБОТ И ЗАТРАТ | ЕД. ИЗМ | ОБЪЕМ\n"
        "ЭОМ!R2: 1 | Щит распределительный | шт. | 3\n"
    )
    rows = rows_from_attachment_text(text)
    anchors = [row["anchor"] for row in rows]
    assert anchors == ["СКС!1", "ЭОМ!1"]
    assert len(set(anchors)) == 2

    portion, rest = slice_rows(rows, limit=1, after="СКС!1")
    assert portion[0]["title"] == "Щит распределительный"
    assert rest == []


def test_section_headings_explain_the_rows_under_them():
    text = (
        "Файл: разделы.xlsx\n"
        "ВОР!R1: № П.П | НАИМЕНОВАНИЕ РАБОТ И ЗАТРАТ | ЕД. ИЗМ | ОБЪЕМ\n"
        "ВОР!R2: Раздел 1. Слаботочные системы\n"
        "ВОР!R3: 1 | Розетка RJ45 | шт. | 40\n"
    )
    assert rows_from_attachment_text(text)[0]["section"] == "Раздел 1. Слаботочные системы"


def test_the_vor_fingerprint_survives_a_parser_fix():
    """Отпечаток ведомости считается по исходным ячейкам, а не по разобранным полям.

    Ревью Codex 11.09: починка `quantity_text` превратила «2,50» в «2.5», отпечаток
    сменился, и сохранённые решения перестали находиться — продолжение оборвалось на
    ровном месте. Разобранные поля выводятся из ячеек, и включать их в отпечаток
    значит ронять продолжение при каждой правке разбора.
    """
    from proxy.smeta_core.vor_rows import source_revision

    text = (
        "Файл: x.xlsx\n"
        "СКС!R1: № П.П | НАИМЕНОВАНИЕ РАБОТ И ЗАТРАТ | ЕД. ИЗМ | ОБЪЕМ\n"
        "СКС!R2: 1 | Кабель | м | 2,50\n"
    )
    rows = rows_from_attachment_text(text)
    baseline = source_revision(rows)

    reparsed = [{**rows[0], "quantity_text": "2,50", "unit": "м.п.", "quantity": 2.5}]
    assert source_revision(reparsed) == baseline, "починка разбора не трогает отпечаток"

    other = rows_from_attachment_text(text.replace("2,50", "3,50"))
    assert source_revision(other) != baseline, "другая ячейка — другая ведомость"
