"""Голос Совушки в детерминированных каналах: рамка поверх фактов + обход к модели."""

from __future__ import annotations

from proxy.services.glossary_chat_service import glossary_tool_result, maybe_handle_glossary_query
from proxy.services.smeta_chat_service import maybe_handle_smeta_query
from proxy.services import sovushka_tone as tone


def test_flavor_wraps_but_keeps_facts():
    out = tone.flavor("КАЦ — конъюнктурный анализ цен", "glossary", seed="кац")
    assert "КАЦ — конъюнктурный анализ цен" in out      # факт цел
    assert out != "КАЦ — конъюнктурный анализ цен"        # есть рамка
    assert "\n" in out
    # неизвестный тип → без рамки
    assert tone.flavor("X", "нет-такого") == "X"


def test_flavor_is_stable():
    a = tone.flavor("Y", "price", seed="91.05.01-017")
    b = tone.flavor("Y", "price", seed="91.05.01-017")
    assert a == b                                          # детерминировано (тестируемо)


def test_wants_model_bypass():
    assert tone.wants_model("что такое КАЦ своими словами") is True
    assert tone.wants_model("поговорим про смету") is True
    assert tone.wants_model("что такое КАЦ") is False


REASSURING = "можешь не перепроверять"


def _assemble_seeds() -> list[str]:
    """Настоящие формулировки сметного канала (слова ветки `_ASSEMBLE_WORDS`), а не случайный текст."""
    words = ("собери", "собрать", "сосчитай", "посчитай смет", "посчитай позиц", "смета по",
             "рассчитай смет")
    codes = ("ГЭСН12-01-034-02", "ГЭСНм12-01-034-02", "ФЕР12-01-034-02", "ТЕР12-01-034-02")
    volumes = ("объём 61 м2", "объём 0,61", "объём 100", "61 м2")
    return [f"{w} {c} {v}" for w in words for c in codes for v in volumes]


def test_reassuring_frame_never_wraps_an_unfinished_calculation():
    """Тон не имеет права называть незакрытый расчёт тем, что не надо перепроверять.

    До сборки 830 `flavor()` не знал статуса и на 20 из 28 достижимых формулировок печатал
    «Готово, цифры выверены — можешь не перепроверять:» над позицией со статусом `partial`,
    где строкой ниже лежит названный пробел цены.  Рамка обязана следовать за статусом, а
    числа — оставаться дословными.
    """
    seeds = _assemble_seeds()
    assert len(seeds) == 112
    for seed in seeds:
        for status in ("partial", "unsafe_source", "not_calculated"):
            out = tone.flavor("Известная стоимость позиции: 12 679.40 руб.", "assemble",
                              seed=seed, status=status)
            assert REASSURING not in out, (seed, status)
            assert "12 679.40" in out  # рамка не трогает число
    # Реплика жива и положена там, где расчёт закрыт: иначе проверка выше была бы трюком
    # с удалением строки, а не следованием статусу.
    assert any(REASSURING in tone.flavor("X", "assemble", seed=s) for s in seeds)
    assert any(REASSURING in tone.flavor("X", "assemble", seed=s, status="complete") for s in seeds)


def test_calculation_that_never_ran_gets_no_frame_at_all():
    """Над «расчёт не запускался» не может стоять рамка «Собрала. Считал код…»."""
    answer = "Норма ФЕР12-01-034-02 не найдена в локальной trusted machine base."
    for seed in _assemble_seeds():
        assert tone.flavor(answer, "assemble", seed=seed, status="not_calculated") == answer


def test_bypass_lets_channels_yield_to_model():
    # явное «к модели» → каналы возвращают None (вопрос уходит в RAG/LLM, не в справочник)
    assert maybe_handle_glossary_query("что такое КАЦ своими словами") is None
    assert maybe_handle_smeta_query("цена 91.05.01-017, но ответь своими словами") is None
    # Обычный lookup тоже не создаёт visible answer: typed evidence идёт модели.
    assert maybe_handle_glossary_query("что такое КАЦ") is None
    g = glossary_tool_result("что такое КАЦ")
    assert g is not None and "конъюнктурный" in g["evidence"]["term"].lower()
    assert "answer" not in g
