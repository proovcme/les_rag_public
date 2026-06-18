"""W16.1/W16.3: рабочая память — заметки и лексический recall, без LLM."""

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
