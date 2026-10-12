"""Модели передаётся порция ведомости, а не весь файл.

Измерение 10.09: из 22 528 токенов входа профиль и текст ведомости занимают 8 444, и
на карточки норм остаётся 14 031 токен — свидетельства по 18 запросам из 51. Ведомость
целиком не только не помещается сама, но и вытесняет то, ради чего запрос делается.

Порция режется по якорям строк (`proxy.smeta_core.vor_rows`), а не по символам: разрыв
посередине строки превратил бы позицию в мусор, а модель ссылается на неё по номеру.
"""

from __future__ import annotations

from proxy.services.chat_evidence_application_service import attachment_portion_text


ROWS = [
    {"source_row": "984", "title": "Шкаф напольный 42U", "unit": "шт.", "quantity": 2},
    {"source_row": "985", "title": "Кабельный организатор 1U", "unit": "шт.", "quantity": 8},
    {"source_row": "986", "title": "Шина заземления 19 дюймов", "unit": "шт.", "quantity": 2},
    {"source_row": "987", "title": "Блок розеток горизонтальный", "unit": "шт.", "quantity": 4},
]


def test_portion_carries_only_its_rows():
    text = attachment_portion_text(ROWS, limit=2, name="СКС (2).xlsx")
    assert "984" in text and "985" in text
    # Номер 986 упоминается как начало следующего прохода, но самой позиции быть не должно.
    assert "986 | Шина заземления" not in text, "строки следующего прохода не должны занимать окно"
    assert "Шкаф напольный 42U" in text
    assert "шт." in text and "2" in text


def test_portion_says_where_it_stopped():
    """Модель должна знать границы порции — иначе примет её за всю ведомость."""
    text = attachment_portion_text(ROWS, limit=2, name="СКС (2).xlsx")
    assert "984" in text and "985" in text
    assert "4" in text, "общее число позиций названо"
    assert "следующ" in text.casefold()


def test_continuation_starts_after_the_anchor():
    text = attachment_portion_text(ROWS, limit=2, name="СКС (2).xlsx", after="985")
    assert "986 | Шина заземления" in text
    assert "987 | Блок розеток" in text
    assert "984 | Шкаф" not in text


def test_last_portion_reports_completion():
    text = attachment_portion_text(ROWS, limit=10, name="СКС (2).xlsx")
    assert all(row["source_row"] in text for row in ROWS)
    assert "следующ" not in text.casefold(), "продолжать нечего — не зови зря"


def test_empty_rows_give_empty_text():
    assert attachment_portion_text([], limit=5, name="пусто.xlsx") == ""
