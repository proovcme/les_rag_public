"""В контекст модели уходит порция ведомости, а не весь файл.

Измерено 10.09: профиль и текст ведомости занимают 8 444 токена из 22 528, оставляя на
карточки норм 14 031 — свидетельства по 18 запросам из 51. Ведомость целиком вытесняет
то, ради чего запрос делается.

Проверяется точка, где вложение превращается в закреплённое свидетельство: подмена
должна происходить там, иначе полный текст всё равно уйдёт модели.
"""

from __future__ import annotations

from proxy.services.chat_evidence_application_service import portioned_attachment_context


VOR_TEXT = """Файл: СКС (2).xlsx

## Лист: СКС
СКС!R1: № П.П | НАИМЕНОВАНИЕ РАБОТ И ЗАТРАТ | Артикул | ЕД. ИЗМ | ОБЪЕМ
СКС!R6: 984 | Шкаф напольный 42U | TTR-4281 | шт. | 2
СКС!R7: 985 | Кабельный организатор 1U | CM-1U-ML | шт. | 8
СКС!R8: 986 | Шина заземления 19 | TGRD-19 | шт. | 2
"""


def test_portion_replaces_the_whole_attachment():
    rows = [
        {"source_row": "984", "title": "Шкаф напольный 42U", "unit": "шт.", "quantity": 2},
        {"source_row": "985", "title": "Кабельный организатор 1U", "unit": "шт.", "quantity": 8},
        {"source_row": "986", "title": "Шина заземления 19", "unit": "шт.", "quantity": 2},
    ]
    text = portioned_attachment_context(
        VOR_TEXT, rows=rows, limit=2, name="СКС (2).xlsx", after="",
    )
    assert "984" in text and "985" in text
    assert "986 | Шина заземления" not in text
    # Исходная простыня с адресами ячеек в контекст не идёт.
    assert "СКС!R1" not in text


def test_without_rows_the_original_text_survives():
    """Если ведомость не разобралась, лучше отдать что есть, чем ничего."""
    text = portioned_attachment_context(VOR_TEXT, rows=[], limit=2, name="x.xlsx", after="")
    assert text == VOR_TEXT


def test_continuation_uses_the_anchor():
    rows = [
        {"source_row": "984", "title": "Шкаф", "unit": "шт.", "quantity": 2},
        {"source_row": "985", "title": "Организатор", "unit": "шт.", "quantity": 8},
        {"source_row": "986", "title": "Шина", "unit": "шт.", "quantity": 2},
    ]
    text = portioned_attachment_context(
        VOR_TEXT, rows=rows, limit=2, name="СКС (2).xlsx", after="984",
    )
    assert "985 | Организатор" in text
    assert "986 | Шина" in text
    assert "984 | Шкаф" not in text


def test_prior_works_block_stays_bounded_as_the_vor_is_processed():
    """Список работ прошлых проходов не растёт вместе с ведомостью.

    Блок нужен, чтобы материал сослался на свою работу через included_in. Если в него
    складывать все работы всей ведомости, он вытесняет из окна сами строки: живой
    прогон 14.09 — 91 работа, 14 602 символа, 7 301 токен, и порция схлопнулась с 7
    строк до 2 при неизменном лимите.
    """
    from proxy.services.chat_evidence_application_service import (
        MAX_PRIOR_WORKS, conservative_token_estimate, prior_works_context,
    )

    decisions = {
        f"{sheet}!{n}": {
            "source_row": f"{sheet}!{n}",
            "work_id": f"{sheet}!{n}",
            "decision_kind": "работа",
            "norm_code": f"ГЭСН{n:02d}-01-001-01",
            # Наименования в настоящей ВОР длинные: замер 14.09 — 14 602 символа на
            # 91 работу, около 160 символов на строку. Короткая заглушка не нагружает
            # бюджет и такой тест ничего не проверяет.
            "title": f"Работа {sheet} {n}. " + "Комплектная система КНАУФ С112 с обшивкой ГКЛВ "
                     "по одинарному металлическому каркасу, высота помещения до 3 м, "
                     "с устройством проёмов и заделкой стыков",
            "quantity": n,
            "unit": "шт",
        }
        for sheet in ("АР", "ЭОМ")
        for n in range(1, 61)
    }
    portion = [{"source_row": "ЭОМ!60", "sheet": "ЭОМ", "anchor": "ЭОМ!60"}]

    text = prior_works_context(decisions, portion=portion)

    assert "АР!" not in text, "работы чужого листа материалу текущей порции не нужны"
    assert "ЭОМ!60" in text, "ближайшие работы своего листа остаются доступны для included_in"
    assert len(text.splitlines()) <= MAX_PRIOR_WORKS, (
        f"блок обязан быть ограничен, получено {len(text.splitlines())}")
    # Замер прохода 39 на большой ВОР: бюджет источника 8 663 токена, и блок ссылок
    # обязан оставить место самой порции и чеку проверяемой строки (3 242 токена).
    assert conservative_token_estimate(text) <= 1500, (
        f"блок ссылок не должен съедать бюджет источника: {conservative_token_estimate(text)} токенов")
