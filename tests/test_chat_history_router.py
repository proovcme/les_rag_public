import sqlite3

import pytest

from proxy.routers.chat import save_chat_history
from proxy.routers.chat_history import get_chat_history, get_chat_sessions


def _init_chat_history(path):
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            question TEXT,
            answer TEXT,
            sources TEXT,
            crag_status TEXT,
            latency_sec REAL,
            tokens INTEGER,
            session_id TEXT DEFAULT NULL
        )
        """
    )
    conn.executemany(
        "INSERT INTO chat_history (question, answer, sources, crag_status, session_id) VALUES (?, ?, ?, ?, ?)",
        [
            ("q1", "a1", "doc-a,doc-b", "VERIFIED", "s1"),
            ("q2", "a2", "", "NO_DATA", "s1"),
            ("q3", "a3", "doc-c", "VERIFIED", "s2"),
        ],
    )
    conn.commit()
    conn.close()


@pytest.mark.asyncio
async def test_get_chat_history_returns_recent_messages_in_chronological_order(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    db_path = tmp_path / "data" / "les_meta_qwen.db"
    monkeypatch.setenv("RAG_META_DB_PATH", str(db_path))
    _init_chat_history(db_path)

    messages = await get_chat_history(limit=2, _user=object())

    assert messages == [
        {"role": "user", "text": "q2"},
        {"role": "ai", "text": "a2", "srcs": [], "crag": "NO_DATA"},
        {"role": "user", "text": "q3"},
        {"role": "ai", "text": "a3", "srcs": ["doc-c"], "crag": "VERIFIED"},
    ]


@pytest.mark.asyncio
async def test_get_chat_history_filters_by_session(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    db_path = tmp_path / "data" / "les_meta_qwen.db"
    monkeypatch.setenv("RAG_META_DB_PATH", str(db_path))
    _init_chat_history(db_path)

    messages = await get_chat_history(session_id="s1", _user=object())

    assert [m["text"] for m in messages] == ["q1", "a1", "q2", "a2"]


@pytest.mark.asyncio
async def test_get_chat_sessions_summarizes_sessions(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    db_path = tmp_path / "data" / "les_meta_qwen.db"
    monkeypatch.setenv("RAG_META_DB_PATH", str(db_path))
    _init_chat_history(db_path)

    sessions = await get_chat_sessions(_user=object())

    assert {session["session_id"]: session["msg_count"] for session in sessions} == {
        "s1": 2,
        "s2": 1,
    }


def test_save_chat_history_uses_active_meta_db_path(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    db_path = tmp_path / "data" / "les_meta_qwen.db"
    monkeypatch.setenv("RAG_META_DB_PATH", str(db_path))
    _init_chat_history(db_path)

    save_chat_history(
        question="q4",
        answer="a4",
        sources=["doc-a", "doc-b"],
        crag_status="VERIFIED",
        latency_sec=1.25,
        tokens=42,
        session_id="s3",
    )

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT question, answer, sources, crag_status, latency_sec, tokens, session_id "
            "FROM chat_history WHERE session_id='s3'"
        ).fetchone()

    assert row == ("q4", "a4", "doc-a,doc-b", "VERIFIED", 1.25, 42, "s3")
