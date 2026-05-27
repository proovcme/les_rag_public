import json
import sqlite3
from types import SimpleNamespace

import pytest

from proxy.routers.chat import save_chat_history
from proxy.routers.chat_history import (
    ChatFeedbackRequest,
    get_chat_history,
    get_chat_sessions,
    get_learning_history,
    save_chat_feedback,
)


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
        {
            "role": "ai",
            "text": "a2",
            "srcs": [],
            "crag": "NO_DATA",
            "meta": {
                "history_id": 2,
                "query_route": {},
                "retrieval_trace": {},
                "cache": "miss",
                "validation": {"enabled": True},
            },
        },
        {"role": "user", "text": "q3"},
        {
            "role": "ai",
            "text": "a3",
            "srcs": ["doc-c"],
            "crag": "VERIFIED",
            "meta": {
                "history_id": 3,
                "query_route": {},
                "retrieval_trace": {},
                "cache": "miss",
                "validation": {"enabled": True},
            },
        },
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

    history_id = save_chat_history(
        question="q4",
        answer="a4",
        sources=["doc-a", "doc-b"],
        crag_status="VERIFIED",
        latency_sec=1.25,
        tokens=42,
        session_id="s3",
        requested_dataset_filter="NTD",
        effective_dataset_filter="NTD_FIRE",
        resolved_dataset_ids=["target-ds"],
        resolved_dataset_names=["NTD_FIRE_Index"],
        source_dataset_ids=["target-ds"],
        source_dataset_names=["NTD_FIRE_Index"],
        query_route={"channel": "normative", "reason": "fire_safety_keyword"},
        retrieval_trace={"quality": {"status": "good"}},
        cache_type="miss",
        validation_enabled=True,
    )

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT id, question, answer, sources, crag_status, latency_sec, tokens, session_id, "
            "requested_dataset_filter, effective_dataset_filter, resolved_dataset_names, "
            "source_dataset_names, source_dataset_mismatch, retrieval_quality, success "
            "FROM chat_history WHERE session_id='s3'"
        ).fetchone()

    assert row[:8] == (history_id, "q4", "a4", "doc-a,doc-b", "VERIFIED", 1.25, 42, "s3")
    assert row[8:10] == ("NTD", "NTD_FIRE")
    assert json.loads(row[10]) == ["NTD_FIRE_Index"]
    assert json.loads(row[11]) == ["NTD_FIRE_Index"]
    assert row[12:] == (0, "good", 1)


@pytest.mark.asyncio
async def test_save_chat_feedback_updates_history_row(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "logs").mkdir()
    db_path = tmp_path / "data" / "les_meta_qwen.db"
    feedback_log = tmp_path / "logs" / "chat_feedback.jsonl"
    monkeypatch.setenv("RAG_META_DB_PATH", str(db_path))
    monkeypatch.setenv("CHAT_FEEDBACK_LOG_PATH", str(feedback_log))
    _init_chat_history(db_path)
    history_id = save_chat_history(
        question="q",
        answer="a",
        sources=["doc"],
        crag_status="VERIFIED",
        latency_sec=0.1,
        tokens=1,
        session_id="feedback-session",
    )

    result = await save_chat_feedback(
        history_id,
        ChatFeedbackRequest(
            feedback="wrong_dataset",
            comment="answer came from mail, not NTD",
            correct_dataset_filter="MAIL",
        ),
        _user=SimpleNamespace(holder="tester", source="api_key"),
    )

    assert result["status"] == "saved"
    assert result["history_id"] == history_id
    assert result["feedback"] == "wrong_dataset"
    assert result["correct_dataset_filter"] == "MAIL"
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT feedback_status, feedback_comment, feedback_correct_dataset_filter, feedback_user "
            "FROM chat_history WHERE id=?",
            (history_id,),
        ).fetchone()
    assert row == ("wrong_dataset", "answer came from mail, not NTD", "MAIL", "tester")
    event = json.loads(feedback_log.read_text(encoding="utf-8").strip())
    assert event["event"] == "chat_feedback"
    assert event["feedback"] == "wrong_dataset"
    assert event["history_id"] == history_id
    assert event["question"] == "q"


@pytest.mark.asyncio
async def test_bad_answer_feedback_is_allowed_and_logged(tmp_path, monkeypatch, caplog):
    (tmp_path / "data").mkdir()
    db_path = tmp_path / "data" / "les_meta_qwen.db"
    feedback_log = tmp_path / "logs" / "chat_feedback.jsonl"
    monkeypatch.setenv("RAG_META_DB_PATH", str(db_path))
    monkeypatch.setenv("CHAT_FEEDBACK_LOG_PATH", str(feedback_log))
    _init_chat_history(db_path)
    history_id = save_chat_history(
        question="bad q",
        answer="bad a",
        sources=["doc"],
        crag_status="VERIFIED",
        latency_sec=0.1,
        tokens=1,
        session_id="feedback-session",
    )

    with caplog.at_level("WARNING"):
        result = await save_chat_feedback(
            history_id,
            ChatFeedbackRequest(feedback="bad_answer", comment="missed clause"),
            _user=SimpleNamespace(holder="tester", source="api_key"),
        )

    assert result["feedback"] == "bad_answer"
    assert "CHAT_FEEDBACK" in caplog.text
    event = json.loads(feedback_log.read_text(encoding="utf-8").strip())
    assert event["feedback"] == "bad_answer"
    assert event["answer_preview"] == "bad a"


@pytest.mark.asyncio
async def test_get_learning_history_returns_success_and_confirmed_dataset_trace(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "logs").mkdir()
    db_path = tmp_path / "data" / "les_meta_qwen.db"
    feedback_log = tmp_path / "logs" / "chat_feedback.jsonl"
    monkeypatch.setenv("RAG_META_DB_PATH", str(db_path))
    monkeypatch.setenv("CHAT_FEEDBACK_LOG_PATH", str(feedback_log))
    _init_chat_history(db_path)
    save_chat_history(
        question="verified question",
        answer="verified answer",
        sources=["doc-target"],
        crag_status="VERIFIED",
        latency_sec=0.2,
        tokens=3,
        session_id="learn-ok",
        effective_dataset_filter="NTD_FIRE",
        resolved_dataset_ids=["target"],
        resolved_dataset_names=["NTD_FIRE_Index"],
        source_dataset_ids=["target"],
        source_dataset_names=["NTD_FIRE_Index"],
        query_route={"channel": "normative", "reason": "fire_safety_keyword"},
        retrieval_trace={"quality": {"status": "good"}},
    )
    mismatch_id = save_chat_history(
        question="routed wrong",
        answer="answer from other dataset",
        sources=["doc-other"],
        crag_status="VERIFIED",
        latency_sec=0.3,
        tokens=4,
        session_id="learn-wrong",
        effective_dataset_filter="NTD_FIRE",
        resolved_dataset_ids=["target"],
        resolved_dataset_names=["NTD_FIRE_Index"],
        source_dataset_ids=["other"],
        source_dataset_names=["MAIL_Index"],
        query_route={"channel": "normative", "reason": "fire_safety_keyword"},
        retrieval_trace={"quality": {"status": "good"}},
    )
    await save_chat_feedback(
        mismatch_id,
        ChatFeedbackRequest(feedback="wrong_dataset", correct_dataset_filter="MAIL"),
        _user=SimpleNamespace(holder="tester"),
    )

    learning = await get_learning_history(limit=10, _user=object())
    by_question = {row["question"]: row for row in learning}

    assert by_question["verified question"]["source_dataset_mismatch"] is False
    assert by_question["verified question"]["resolved_dataset_names"] == ["NTD_FIRE_Index"]
    assert by_question["routed wrong"]["source_dataset_mismatch"] is True
    assert by_question["routed wrong"]["source_dataset_names"] == ["MAIL_Index"]
    assert by_question["routed wrong"]["feedback_status"] == "wrong_dataset"
    assert by_question["routed wrong"]["feedback_correct_dataset_filter"] == "MAIL"
