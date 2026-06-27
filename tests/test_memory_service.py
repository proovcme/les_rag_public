"""W16.1/W16.3: рабочая память — заметки и лексический recall, без LLM."""

import json
import sqlite3
import time

import pytest

import proxy.services.memory_service as ms


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(ms, "rag_meta_db_path", lambda: str(tmp_path / "meta.db"))


def _add_history(question, answer, crag="VERIFIED", feedback="", success=1):
    with ms._connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT, answer TEXT, crag_status TEXT,
                success INTEGER DEFAULT 0, feedback_status TEXT DEFAULT ''
            )
            """
        )
        conn.execute(
            "INSERT INTO chat_history(question, answer, crag_status, success, feedback_status) VALUES (?,?,?,?,?)",
            (question, answer, crag, success, feedback),
        )
        conn.commit()


def _add_session(session_id, question, answer):
    with ms._connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS chat_history ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, question TEXT, answer TEXT)"
        )
        conn.execute(
            "INSERT INTO chat_history(session_id, question, answer) VALUES (?,?,?)",
            (session_id, question, answer),
        )
        conn.commit()


def _add_session_trace(session_id, question, trace):
    with ms._connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS chat_history ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, question TEXT, answer TEXT, "
            "retrieval_trace_json TEXT DEFAULT '{}')"
        )
        conn.execute(
            "INSERT INTO chat_history(session_id, question, answer, retrieval_trace_json) VALUES (?,?,?,?)",
            (session_id, question, "ответ", json.dumps(trace, ensure_ascii=False)),
        )
        conn.commit()


# ── память диалога (запоминать всё) ──

def test_session_memory_returns_dialogue():
    _add_session("s1", "Как зовут объект?", "Объект — БЦ Банкрот.")
    _add_session("s1", "А кто прораб?", "Прораб — Иван.")
    _add_session("other", "Левый вопрос", "Левый ответ")
    block = ms.session_memory("s1")
    assert "БЦ Банкрот" in block and "Иван" in block
    assert "Левый" not in block  # чужая сессия не подмешивается
    assert block.index("Банкрот") < block.index("Иван")  # хронологический порядок


def test_session_memory_empty_without_session():
    assert ms.session_memory("") == ""
    assert ms.session_memory("nope") == ""


def test_session_user_questions_returns_chronological_questions():
    _add_session("s1", "Первый вопрос", "Первый ответ")
    _add_session("s1", "Второй вопрос", "Второй ответ")
    _add_session("other", "Чужой вопрос", "Чужой ответ")
    assert ms.session_user_questions("s1") == ["Первый вопрос", "Второй вопрос"]
    assert ms.session_user_questions("other") == ["Чужой вопрос"]
    assert ms.session_user_questions("") == []


def test_session_recent_retrieval_traces_returns_chronological_dicts():
    _add_session_trace("s1", "Первый", {"mode": "one", "mass_t": 1})
    _add_session_trace("s1", "Второй", {"mode": "two", "mass_t": 2})
    _add_session_trace("other", "Чужой", {"mode": "other"})
    traces = ms.session_recent_retrieval_traces("s1")
    assert [t["mode"] for t in traces] == ["one", "two"]
    assert ms.session_recent_retrieval_traces("missing") == []
    assert ms.session_recent_retrieval_traces("") == []


# ── авто-заметки (факт без «запомни:») ──

def test_autonote_saves_fact_statements():
    for fact in [
        "Прораб на объекте — Иван Петров",
        "Объект называется БЦ Банкрот",
        "Срок сдачи 30 июня",
        "Контактный телефон 8-900-000",
    ]:
        assert ms.looks_like_fact(fact), fact


def test_autonote_ignores_questions_and_commands():
    for q in [
        "Какие требования к серверным по СП 485?",   # вопрос
        "требования к серверным сп 485",             # запрос без «?» — НЕ факт (нет маркера)
        "Сделай ВОР из спецификации",                # команда
        "Сверь ведомости и акты",                    # команда
        "Сколько кабеля в смете",                    # запрос
        "Покажи заметки",                            # команда
    ]:
        assert not ms.looks_like_fact(q), q


def test_maybe_autonote_creates_auto_note():
    reply = ms.maybe_autonote("Главный инженер проекта — Сидоров")
    assert reply["operation"] == "note_autocreate"
    notes = ms.list_notes()
    assert notes and notes[0]["auto"] == 1 and "Сидоров" in notes[0]["text"]


def test_maybe_autonote_disabled_by_env(monkeypatch):
    monkeypatch.setenv("LES_AUTONOTE_ENABLED", "false")
    assert ms.maybe_autonote("Объект называется Банкрот") is None


def test_maybe_autonote_returns_none_for_query():
    assert ms.maybe_autonote("Сколько стоит кабель") is None


def test_strip_output_directive_drops_glued_suffix():
    directive = "Ответь развёрнуто — 3-5 абзацев. Пиши профессиональным техническим языком"
    # клиент приклеил директиву к вопросу без разделителя
    glued = "Главный инженер проекта — Сидоров" + directive
    assert ms.strip_output_directive(glued, directive) == "Главный инженер проекта — Сидоров"
    # без директивы или когда её нет в тексте — текст не меняется (кроме обрезки пробелов)
    assert ms.strip_output_directive("Главный инженер — Сидоров", None) == "Главный инженер — Сидоров"
    assert ms.strip_output_directive("Главный инженер — Сидоров", "что-то другое") == "Главный инженер — Сидоров"


def test_autonote_does_not_store_output_directive():
    """output_directive не должна попадать в текст авто-заметки (баг: склейка вопроса с директивой)."""
    directive = "Ответь развёрнуто — 3-5 абзацев. Пиши профессиональным техническим языком"
    glued = "Главный инженер проекта — Сидоров" + directive
    reply = ms.maybe_autonote(glued, output_directive=directive)
    assert reply is not None and reply["operation"] == "note_autocreate"
    notes = ms.list_notes()
    assert notes and notes[0]["text"] == "Главный инженер проекта — Сидоров"
    assert "Ответь развёрнуто" not in notes[0]["text"]
    assert "техническим языком" not in notes[0]["text"]


def test_remember_command_strips_output_directive():
    directive = "Ответь кратко — 1-2 абзаца."
    glued = "запомни: по корпусу Б дымоудаление считаем по СП 7" + directive
    reply = ms.maybe_handle_memory_command(glued, output_directive=directive)
    assert reply["operation"] == "note_create"
    notes = ms.list_notes()
    assert notes[0]["text"] == "по корпусу Б дымоудаление считаем по СП 7"
    assert "Ответь кратко" not in notes[0]["text"]


# ── чат-команды ──

def test_remember_and_list():
    reply = ms.maybe_handle_memory_command("запомни: по корпусу Б дымоудаление считаем по СП 7")
    assert reply["operation"] == "note_create"
    listing = ms.maybe_handle_memory_command("заметки")
    assert listing["count"] == 1 and "СП 7" in listing["answer"]


def test_forget():
    ms.create_note("временная заметка")
    reply = ms.maybe_handle_memory_command("забудь заметку 1")
    assert reply["count"] == 1
    assert ms.maybe_handle_memory_command("забудь заметку 1")["count"] == 0


def test_regular_questions_pass_through():
    for q in (
        "Какие требования к путям эвакуации?",
        "Запомни ли ты прошлый разговор?",  # вопрос, не команда
        "что ты помнишь про СП 60",  # не точная команда списка
    ):
        assert ms.maybe_handle_memory_command(q) is None, q


# ── recall ──

def test_recall_finds_relevant_note():
    ms.create_note("по корпусу Б дымоудаление считаем по СП 7 с коэффициентом 1.2")
    ms.create_note("заказчик просит ведомости в формате xlsx")
    block = ms.recall_context("какое дымоудаление принято для корпуса Б?")
    assert "дымоудаление" in block and "#1" in block
    assert "xlsx" not in block  # нерелевантная заметка не подмешана


def test_recall_empty_when_no_match():
    ms.create_note("заказчик просит ведомости в формате xlsx")
    assert ms.recall_context("ширина путей эвакуации по СП 1") == ""


def test_recall_uses_good_history_only():
    _add_history(
        "какая ширина эвакуационного выхода в детских садах?",
        "Не менее 1,2 м по СП 1.13130.",
    )
    _add_history(
        "какая ширина эвакуационного выхода в школах?",
        "Бредовый ответ.",
        feedback="bad_answer",
    )
    block = ms.recall_context("какая ширина эвакуационного выхода в детских садах нужна?")
    assert "1,2 м" in block
    assert "Бредовый" not in block


def test_recall_survives_missing_history_table():
    assert ms.recall_context("любой вопрос про дымоудаление") == ""
