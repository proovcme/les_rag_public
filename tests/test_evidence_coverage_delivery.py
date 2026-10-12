"""Предупреждение об охвате должно быть в сообщениях, которые получает модель.

Два ревью Codex подряд поймали одно и то же место с разных сторон. Сперва охват
считался только при первой сборке пакета и терялся при пересборке. Затем — уже после
пересчёта — предупреждение дописывалось в `context`, тогда как финальный вызов модели
собирает свидетельства из списка групп (`answer_evidence`), а `context` в этой ветке
не используется вовсе. Воспроизведение Codex: 6 запросов из 51, предупреждение в
`context` есть, в отправленном evidence его нет.

Поэтому проверяется именно то, что уходит модели.
"""

from __future__ import annotations

from proxy.services.chat_evidence_application_service import (
    answer_evidence_blocks,
    model_rag_evidence_coverage,
)


def test_partial_coverage_warning_is_inside_the_sent_evidence():
    blocks = answer_evidence_blocks(
        fixed_blocks=["Ранее закреплённое свидетельство"],
        group_blocks=["[Поисковый запрос Q1] строка 1", "[Поисковый запрос Q2] строка 2"],
        coverage={"queries_total": 51, "queries_covered": 6, "complete": False},
    )
    joined = "\n".join(blocks)
    assert "[ОХВАТ]" in joined, "модель обязана узнать, что ведомость прошла не целиком"
    assert "6" in joined and "51" in joined
    # Предупреждение идёт последним: оно относится ко всему пакету, а не к одной группе.
    assert "[ОХВАТ]" in blocks[-1]
    assert blocks[0] == "Ранее закреплённое свидетельство"


def test_complete_coverage_sends_no_warning():
    blocks = answer_evidence_blocks(
        fixed_blocks=[],
        group_blocks=["[Поисковый запрос Q1] строка 1"],
        coverage={"queries_total": 3, "queries_covered": 3, "complete": True},
    )
    assert blocks == ["[Поисковый запрос Q1] строка 1"]


def test_missing_coverage_data_changes_nothing():
    """Без данных об охвате пакет не меняется: выдуманное предупреждение хуже никакого."""
    blocks = answer_evidence_blocks(
        fixed_blocks=["A"], group_blocks=["B"], coverage=None,
    )
    assert blocks == ["A", "B"]


def test_coverage_counts_what_actually_reached_the_model():
    """Охват считается по собранным группам, а не по исходному числу запросов."""
    query_hits = [(f"строка {index}", []) for index in range(1, 52)]
    coverage = model_rag_evidence_coverage(query_hits, ["[Поисковый запрос Q1] строка 1"])
    assert coverage["queries_total"] == 51
    assert coverage["queries_covered"] == 1
    assert coverage["complete"] is False


def _preset():
    from proxy.services.model_execution_preset_service import ModelExecutionPreset

    return ModelExecutionPreset(
        preset_id="coverage-fixture",
        model_family="fixture",
        input_token_limit=6000,
        generation_reserve_tokens=20,
        safety_reserve_tokens=20,
        normal_tool_count=3,
        max_tools=5,
        max_batch_items=5,
        parallel_read_limit=1,
        reasoning_enabled=False,
        source_chain=("test",),
    )


def test_warning_survives_all_the_way_into_the_model_messages():
    """Сквозная проверка: предупреждение доходит до сообщений, отправляемых модели.

    Промежуточные переменные уже дважды вводили в заблуждение: предупреждение лежало
    сперва в `context`, потом в неподключённой функции, и оба раза зелёный тест ничего
    не доказывал. Здесь проверяется выход `govern_inference_messages` — то, что уходит
    в транспорт.
    """
    from proxy.services.chat_evidence_application_service import govern_inference_messages

    evidence = answer_evidence_blocks(
        fixed_blocks=[],
        group_blocks=["[Поисковый запрос Q1] строка ведомости 1"],
        coverage={"queries_total": 51, "queries_covered": 6, "complete": False},
    )
    messages, _packet = govern_inference_messages(
        preset=_preset(),
        profile_prefix="профиль сметчика",
        request_payload={"question": "Составь смету на основании ВОР"},
        evidence=evidence,
    )
    sent = "\n".join(str(message.get("content") or "") for message in messages)
    assert "[ОХВАТ]" in sent, "модель не узнает, что ведомость прошла не целиком"
    assert "6" in sent and "51" in sent


def test_the_note_speaks_about_queries_not_rows():
    """Счётчик считает поисковые запросы модели, а не строки ведомости.

    Ревью Codex 10.09: соответствия 1:1 между ними нет — на ведомость в 80 строк
    модель формулировала 51, 55 и 59 запросов в разных прогонах. Сообщение «вошли
    36 запросов из 55, по этим 36 строкам подбери нормы» смешивало два разных счёта
    и внушало модели, будто закрыто 36 строк ведомости.
    """
    from proxy.services.chat_evidence_application_service import _evidence_coverage_note

    note = _evidence_coverage_note({"queries_covered": 36, "queries_total": 55})
    assert "запрос" in note.casefold()
    assert "36 строкам" not in note
    assert "по 36 из 55" in note


def test_trace_records_whether_the_warning_was_actually_sent():
    """Факт доставки предупреждения должен быть виден в трассе.

    Живой прогон 16:02 нельзя было проверить: ответ модели не содержит отправленный
    промпт, а трасса показывала лишь число элементов в секции свидетельств. Утверждать
    доставку было нечем. Теперь сборка пакета сама отмечает, что именно она положила.
    """
    from proxy.services.chat_evidence_application_service import answer_evidence_blocks

    trace: dict = {}
    answer_evidence_blocks(
        fixed_blocks=[],
        group_blocks=["[Поисковый запрос Q1] строка 1"],
        coverage={"queries_total": 51, "queries_covered": 18, "complete": False},
        trace=trace,
    )
    assert trace["coverage_notice_sent"] is True
    assert trace["evidence_blocks_sent"] == 2

    full: dict = {}
    answer_evidence_blocks(
        fixed_blocks=[],
        group_blocks=["[Поисковый запрос Q1] строка 1"],
        coverage={"queries_total": 1, "queries_covered": 1, "complete": True},
        trace=full,
    )
    assert full["coverage_notice_sent"] is False
    assert full["evidence_blocks_sent"] == 1


def _long_hits(queries: int, per_query: int = 5):
    """Свидетельства такого объёма, что группы упираются в бюджет — как в живом прогоне."""

    class _Hit:
        def __init__(self, name: str, score: float, content: str) -> None:
            self.doc_name = name
            self.score = score
            self.content = content

    return [
        (
            f"прокладка кабеля вариант {index}",
            [
                _Hit(
                    f"ГЭСНм10-01-{index:03d}",
                    0.9 - order * 0.01,
                    # Distinct variants are necessary: exact duplicate cards are
                    # now aliases and no longer exhaust this boundary fixture.
                    f"Шифр ГЭСНм10-01-{index:03d}-{order:02d}. Наименование работы. " * 12,
                )
                for order in range(per_query)
            ],
        )
        for index in range(1, queries + 1)
    ]


def test_warning_survives_when_groups_fill_the_whole_budget():
    """Граница бюджета: предупреждение обязано пережить упаковку, а не быть отброшенным.

    Ревью Codex 10.09 (R1): свидетельства — необязательная секция governor'а, лишнее он
    режет с хвоста, а предупреждение добавляется последним. Воспроизведение на боевом
    бюджете 22 528 токенов: `coverage_notice_sent=True`, а в конечных messages текста
    нет — omission `evidence:25`. Прежний тест этой границы не достигал: одна короткая
    группа при бюджете 6000.

    Формула бюджета групп берётся из production-функции: повторить её здесь означало бы
    молчать при её изменении.
    """
    from proxy.services.chat_evidence_application_service import (
        build_model_rag_evidence_groups,
        govern_inference_messages,
        model_rag_group_char_budget,
    )
    from proxy.services.model_execution_preset_service import ModelExecutionPreset

    preset = ModelExecutionPreset(
        preset_id="budget-boundary",
        model_family="fixture",
        input_token_limit=22528,
        generation_reserve_tokens=0,
        safety_reserve_tokens=0,
        normal_tool_count=3,
        max_tools=5,
        max_batch_items=5,
        parallel_read_limit=1,
        reasoning_enabled=False,
        source_chain=("test",),
    )
    profile = "Ты сметчик. " * 200
    request = "Дай итоговый ответ по всем строкам ВОР. " * 50
    fixed = ["Ведомость: " + "строка ведомости; " * 300]

    _, fixed_packet = govern_inference_messages(
        preset=preset,
        profile_prefix=profile,
        request_payload=request,
        evidence=fixed,
    )
    query_hits = _long_hits(51)
    groups, _chunks = build_model_rag_evidence_groups(
        query_hits,
        max_chars=model_rag_group_char_budget(
            input_budget_tokens=fixed_packet.input_budget_tokens,
            included_tokens=fixed_packet.included_tokens,
            query_count=len(query_hits),
            context_chars_limit=55000,
        ),
        hits_per_query=5,
    )
    coverage = model_rag_evidence_coverage(query_hits, groups)
    assert not coverage["complete"], "фикстура обязана упереться в бюджет"

    evidence = answer_evidence_blocks(
        fixed_blocks=fixed, group_blocks=groups, coverage=coverage
    )
    messages, packet = govern_inference_messages(
        preset=preset,
        profile_prefix=profile,
        request_payload=request,
        evidence=evidence,
    )
    sent = "\n".join(str(message.get("content") or "") for message in messages)
    assert "[ОХВАТ]" in sent, "предупреждение отброшено governor'ом — модель о потере не узнает"


def test_delivery_is_read_from_the_assembled_packet():
    """Доставка проверяется по пакету, а не по нашему намерению его положить."""
    from proxy.services.chat_evidence_application_service import (
        coverage_notice_in_packet,
        govern_inference_messages,
    )

    evidence = answer_evidence_blocks(
        fixed_blocks=[],
        group_blocks=["[Поисковый запрос Q1] строка 1"],
        coverage={"queries_total": 51, "queries_covered": 6, "complete": False},
    )
    _messages, packet = govern_inference_messages(
        preset=_preset(),
        profile_prefix="профиль сметчика",
        request_payload={"question": "Составь смету"},
        evidence=evidence,
    )
    assert coverage_notice_in_packet(packet) is True

    _messages, empty = govern_inference_messages(
        preset=_preset(),
        profile_prefix="профиль сметчика",
        request_payload={"question": "Составь смету"},
        evidence=["[Поисковый запрос Q1] строка 1"],
    )
    assert coverage_notice_in_packet(empty) is False
