"""W11.5 — формирование ответа по интенту (ADR-12 §2). Pure-классификатор, без LLM."""

from __future__ import annotations

from proxy.services.answer_form_service import classify_answer_form


def test_value_intent_one_liner():
    for q in [
        "Какова минимальная ширина эвакуационного выхода?",
        "Сколько эвакуационных выходов нужно?",
        "Можно ли прокладывать кабель в одном лотке?",
        "Чему равно расстояние между извещателями?",
    ]:
        f = classify_answer_form(q)
        assert f.intent == "value", q
        assert f.max_tokens <= 256


def test_enum_intent_bare_list():
    for q in ["Перечисли разделы РД", "Какие разделы входят в проект?", "Состав проектной документации"]:
        assert classify_answer_form(q).intent == "enum", q


def test_full_intent_verbose():
    for q in ["Собери всё про серверные", "Опиши максимально подробно требования", "Дай исчерпывающий обзор"]:
        assert classify_answer_form(q).intent == "full", q


def test_brief_intent_compact():
    for q in ["Расскажи про требования к серверным", "Основные требования к эвакуации", "Кратко о ПУЭ"]:
        assert classify_answer_form(q).intent == "brief", q


def test_default_when_unknown():
    f = classify_answer_form("Серверные помещения СП 485")
    assert f.intent == "default"
    assert f.instruction == ""
    assert f.max_tokens == 8192   # снят блок длины по умолчанию (было 2048) — форму не навязываем


def test_empty_question_is_default():
    assert classify_answer_form("").intent == "default"
    assert classify_answer_form("   ").intent == "default"


def test_priority_value_over_brief():
    # вопрос содержит и «требования», и «какое значение» → побеждает узкий value
    f = classify_answer_form("Какое значение сопротивления требуется по нормам?")
    assert f.intent == "value"


def test_yo_normalization():
    # «объём» с ё не должен мешать; «развёрнуто» матчится с ё и без
    assert classify_answer_form("Опиши развёрнуто весь раздел").intent == "full"
    assert classify_answer_form("Опиши развернуто весь раздел").intent == "full"


def test_instruction_present_for_non_default():
    for q in ["Перечисли разделы", "Расскажи кратко", "Собери всё", "Какова ширина"]:
        assert classify_answer_form(q).instruction, q
