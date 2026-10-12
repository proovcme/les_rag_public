"""Длинная ведомость не должна ронять сборку сметы."""
from __future__ import annotations

import pytest

from proxy.services.chat_evidence_application_service import build_model_rag_evidence_groups


class _Hit:
    def __init__(self, name: str, body: str) -> None:
        self.doc_name = name
        self.content = body
        self.score = 0.5
        self.meta = {}
        self.doc_id = name


def _hits(count: int):
    return [_Hit("smeta_norm_cards.v1", "тело нормы " * 20) for _ in range(count)]


def test_many_queries_shrink_instead_of_failing():
    """Ведомость на 80 строк даёт полсотни запросов; они обязаны ужаться, а не упасть.

    10.09: сборка ЛСР по СКС падала на пятнадцатой минуте с
    MODEL_RAG_EVIDENCE_BUDGET_TOO_SMALL_FOR_ALL_QUERY_HEADERS — заголовки 51 запроса
    (~24 000 символов) не влезали в бюджет 16 000. Потерять часть свидетельств можно,
    потерять весь ответ — нет.
    """
    query_hits = [(f"строка ведомости {index}", _hits(6)) for index in range(1, 52)]

    blocks, chunks = build_model_rag_evidence_groups(
        query_hits, max_chars=16000, hits_per_query=6,
    )

    assert blocks, "ответ не должен исчезать целиком"
    rendered = "\n".join(blocks)
    assert len(rendered) <= 16000
    # Первые запросы обязаны сохраниться: по ним модель уже приняла решения.
    assert "[Поисковый запрос Q1]" in rendered
    assert chunks

    # Урезать надо число запросов, а не источники у каждого. 10.09 проверено на живой
    # сборке: срезав хиты до одного-двух, выдача стала вдвое многочисленнее и вчетверо
    # хуже по профильности — 18 % норм связи против 49 %, — и модель, не найдя
    # подходящих, сочинила несуществующий шифр.
    kept = [block for block in blocks if "[Поисковый запрос" in block]
    assert blocks[0].count("[Q1.H") >= 5, "выбор важнее охвата: при трёх карточках модель ставит одну норму на всё"
    # Сужение до пола помогает, но не любой ценой: с пятью карточками в бюджет входят
    # 11 строк против 12 без сужения — зато у каждой есть из чего выбирать.
    assert len(kept) >= 10, f"строки не должны теряться пачками: {len(kept)}"


def test_small_input_is_unchanged():
    """Обычный запрос ведёт себя как раньше — усечение не должно включаться зря."""
    blocks, chunks = build_model_rag_evidence_groups(
        [("прокладка кабеля", _hits(3))], max_chars=16000, hits_per_query=3,
    )
    assert len(blocks) == 1
    assert len(chunks) == 3


def test_dropped_queries_are_reported_not_hidden():
    """Если часть строк не влезла, это должно быть видно, а не пропасть молча.

    Пошаговая сборка сметы опирается ровно на это число: сколько строк прошло за
    проход и сколько осталось на следующий.
    """
    from proxy.services.chat_evidence_application_service import model_rag_evidence_coverage

    query_hits = [(f"строка ведомости {index}", _hits(6)) for index in range(1, 52)]
    blocks, _chunks = build_model_rag_evidence_groups(
        query_hits, max_chars=16000, hits_per_query=6,
    )
    coverage = model_rag_evidence_coverage(query_hits, blocks)

    assert coverage["queries_total"] == 51
    assert 0 < coverage["queries_covered"] < 51
    assert coverage["queries_dropped"] == 51 - coverage["queries_covered"]
    assert coverage["complete"] is False


def test_full_coverage_is_reported_as_complete():
    from proxy.services.chat_evidence_application_service import model_rag_evidence_coverage

    query_hits = [("прокладка кабеля", _hits(3))]
    blocks, _chunks = build_model_rag_evidence_groups(
        query_hits, max_chars=16000, hits_per_query=3,
    )
    coverage = model_rag_evidence_coverage(query_hits, blocks)
    assert coverage == {
        "queries_total": 1, "queries_covered": 1, "queries_dropped": 0, "complete": True,
    }


def test_bodies_stay_readable_at_any_budget():
    """Карточка обязана дойти с текстом, а не одним заголовком.

    Резерв под тела учитывался только тогда, когда не влезали сами заголовки. При
    бюджете пошире заголовки помещались, ужатие не включалось — и каждому источнику
    доставалось по несколько десятков символов: шифр без наименования и практики.
    """
    body = (
        "Шифр: ГЭСНм10-01-055-02\n"
        "Наименование: Прокладка кабеля в готовых каналах, масса 1 м: до 1 кг\n"
        "Измеритель: 100 м кабеля\n"
        "Практика раздела: в архиве применяется регулярно: 153 раз из 125 смет раздела"
    )
    query_hits = [
        (f"строка ведомости {index}", [_Hit("smeta_norm_cards.v1", body) for _ in range(6)])
        for index in range(1, 52)
    ]

    blocks, _chunks = build_model_rag_evidence_groups(
        query_hits, max_chars=30000, hits_per_query=6,
    )
    rendered = "\n".join(blocks)
    assert len(rendered) <= 30000
    # У первого источника должно остаться и наименование, а не только шифр.
    assert "Наименование: Прокладка кабеля" in rendered


def test_narrow_the_shortlist_before_dropping_rows():
    """Каждая строка ведомости важнее ширины выбора по одной из них.

    10.09: при шести источниках на строку в бюджет влезали 17 строк из 55, остальные
    38 модель закрывала вслепую. Три источника на все 55 полезнее шести на семнадцать:
    строка без единой карточки — это заведомо выдуманная норма.
    """
    body = (
        "Шифр: ГЭСНм10-01-055-02\n"
        "Наименование: Прокладка кабеля в готовых каналах, масса 1 м: до 1 кг\n"
        "Измеритель: 100 м кабеля\n"
        "Практика раздела: в архиве применяется регулярно: 153 раз из 125 смет"
    )
    query_hits = [
        (f"строка ведомости {index}", [_Hit("smeta_norm_cards.v1", body) for _ in range(6)])
        for index in range(1, 56)
    ]

    blocks, _chunks = build_model_rag_evidence_groups(
        query_hits, max_chars=45000, hits_per_query=6,
    )
    rendered = "\n".join(blocks)
    assert len(rendered) <= 45000

    covered = len([b for b in blocks if "[Поисковый запрос" in b])
    assert covered >= 30, f"строк должно доходить много больше семнадцати: {covered}"
    # Ширина ужимается только до пола: ниже него модель ставит одну норму на все строки.
    assert blocks[0].count("[Q1.H") >= 5
    assert "Наименование: Прокладка кабеля" in rendered


def test_coverage_note_demands_work_on_the_rows_that_did_fit():
    """Примечание об охвате должно требовать работы, а не воздержания.

    Прогон 14:11: прежний текст «отвечай только по вошедшим, остальные не выдумывай»
    вместе с прочими предупреждениями прочитался как «лучше не подбирать вовсе» —
    модель вернула все 70 строк с пустым norm_code.
    """
    from proxy.services.chat_evidence_application_service import _evidence_coverage_note

    note = _evidence_coverage_note({"queries_covered": 36, "queries_total": 55})
    assert "36" in note and "55" in note
    # Указание работать, а не воздерживаться; счёт идёт по запросам, не по строкам.
    assert "подбирай нормы" in note.casefold()
    assert "не выдумывай" not in note
    assert "поисковых запросов" in note
