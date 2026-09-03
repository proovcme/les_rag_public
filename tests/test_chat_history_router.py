import json
import sqlite3
from types import SimpleNamespace

import pytest

from proxy.routers.chat import begin_chat_history, save_chat_history
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

    assert [m["role"] for m in messages] == ["user", "ai", "user", "ai"]
    assert [m["text"] for m in messages] == ["q2", "a2", "q3", "a3"]
    assert messages[0]["requested_at"]
    assert messages[1]["meta"]["history_id"] == 2
    assert messages[1]["meta"]["requested_at"] == messages[0]["requested_at"]
    assert messages[1]["crag"] == "NO_DATA"
    assert messages[3]["srcs"] == ["doc-c"]
    assert messages[3]["meta"]["history_id"] == 3
    assert "latency_phases" in messages[1]["meta"]


@pytest.mark.asyncio
async def test_get_chat_history_filters_by_session(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    db_path = tmp_path / "data" / "les_meta_qwen.db"
    monkeypatch.setenv("RAG_META_DB_PATH", str(db_path))
    _init_chat_history(db_path)

    messages = await get_chat_history(session_id="s1", _user=object())

    assert [m["text"] for m in messages] == ["q1", "a1", "q2", "a2"]


@pytest.mark.asyncio
async def test_get_chat_history_restores_exact_source_map_and_counts(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    db_path = tmp_path / "data" / "les_meta_qwen.db"
    monkeypatch.setenv("RAG_META_DB_PATH", str(db_path))
    _init_chat_history(db_path)
    source_map = [{
        "index": 1,
        "doc_name": "project.pdf",
        "source_ref": "Project/project.pdf#page=7",
        "snippet": "Exact evidence excerpt",
        "locator": {"kind": "file_excerpt", "relative_path": "Project/project.pdf", "page": 7},
    }]
    save_chat_history(
        question="q4",
        answer="a4 [Источник 1]",
        sources=["project.pdf"],
        crag_status="VERIFIED",
        latency_sec=1,
        tokens=1,
        session_id="source-session",
        retrieval_trace={
            "source_map": source_map,
            "source_counts": {"found": 9, "model_visible": 1, "cited": 1},
        },
    )

    messages = await get_chat_history(session_id="source-session", _user=object())

    assert messages[-1]["meta"]["source_map"] == source_map
    assert messages[-1]["meta"]["source_counts"] == {
        "found": 9,
        "model_visible": 1,
        "cited": 1,
    }


@pytest.mark.asyncio
async def test_get_chat_history_recovers_pre_fix_source_map_from_evidence_manifest(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    db_path = tmp_path / "data" / "les_meta_qwen.db"
    monkeypatch.setenv("RAG_META_DB_PATH", str(db_path))
    _init_chat_history(db_path)
    save_chat_history(
        question="q4",
        answer="a4 [Источник 1]",
        sources=["project.pdf"],
        crag_status="VERIFIED",
        latency_sec=1,
        tokens=1,
        session_id="manifest-session",
        retrieval_trace={
            "evidence_manifest": {
                "model_visible": [{
                    "id": "S1",
                    "doc_name": "project.pdf",
                    "doc_id": "doc-1",
                    "dataset_id": "project",
                    "locator": {
                        "kind": "file_excerpt",
                        "relative_path": "Project/project.pdf",
                        "source_ref": "Project/project.pdf#page=7",
                        "page": 7,
                        "excerpt": "Exact evidence excerpt",
                    },
                }],
            },
        },
    )

    messages = await get_chat_history(session_id="manifest-session", _user=object())

    restored = messages[-1]["meta"]["source_map"][0]
    assert restored["evidence_ref"] == "S1"
    assert restored["source_ref"] == "Project/project.pdf#page=7"
    assert restored["snippet"] == "Exact evidence excerpt"


@pytest.mark.asyncio
async def test_get_chat_history_recovers_pre_fix_web_sources_from_tool_trace(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    db_path = tmp_path / "data" / "les_meta_qwen.db"
    monkeypatch.setenv("RAG_META_DB_PATH", str(db_path))
    _init_chat_history(db_path)
    save_chat_history(
        question="q4",
        answer="a4 [Источник 1–2]",
        sources=["web-one", "web-two"],
        crag_status="UNVALIDATED",
        latency_sec=1,
        tokens=1,
        session_id="web-trace-session",
        retrieval_trace={
            "tool_loop": {
                "results": [{
                    "tool": "web_search",
                    "result": {
                        "provider": "duckduckgo",
                        "results": [
                            {"url": "https://one.example", "title": "One", "snippet": "Excerpt one"},
                            {"url": "https://two.example", "title": "Two", "snippet": "Excerpt two"},
                        ],
                    },
                    "sources": [
                        {"url": "https://one.example", "title": "One"},
                        {"url": "https://two.example", "title": "Two"},
                    ],
                }],
            },
        },
    )

    messages = await get_chat_history(session_id="web-trace-session", _user=object())

    restored = messages[-1]["meta"]["source_map"]
    assert [item["source_ref"] for item in restored] == [
        "https://one.example",
        "https://two.example",
    ]
    assert [item["snippet"] for item in restored] == ["Excerpt one", "Excerpt two"]


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
    assert all(session["in_progress"] is False for session in sessions)


@pytest.mark.asyncio
async def test_get_chat_sessions_uses_first_question_not_alphabetical(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    db_path = tmp_path / "data" / "les_meta_qwen.db"
    monkeypatch.setenv("RAG_META_DB_PATH", str(db_path))
    _init_chat_history(db_path)
    save_chat_history(
        question="Яблоко",
        answer="a",
        sources=[],
        crag_status="VERIFIED",
        latency_sec=0.1,
        tokens=1,
        session_id="alpha-order",
    )
    save_chat_history(
        question="Абрикос",
        answer="b",
        sources=[],
        crag_status="VERIFIED",
        latency_sec=0.1,
        tokens=1,
        session_id="alpha-order",
    )

    sessions = await get_chat_sessions(_user=object())
    by_id = {session["session_id"]: session for session in sessions}

    assert by_id["alpha-order"]["first_question"] == "Яблоко"
    assert by_id["alpha-order"]["msg_count"] == 2


@pytest.mark.asyncio
async def test_pending_history_stub_appears_in_sessions_and_completes_same_row(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    db_path = tmp_path / "data" / "les_meta_qwen.db"
    monkeypatch.setenv("RAG_META_DB_PATH", str(db_path))
    _init_chat_history(db_path)
    history_id = begin_chat_history(question="Собери ВОР", session_id="vor-live")

    sessions = await get_chat_sessions(_user=object())
    live = next(session for session in sessions if session["session_id"] == "vor-live")
    messages = await get_chat_history(session_id="vor-live", _user=object())

    assert live["in_progress"] is True
    assert live["first_question"] == "Собери ВОР"
    assert messages[-1]["crag"] == "PENDING"
    assert messages[-1]["text"] == ""

    completed_id = save_chat_history(
        question="Собери ВОР",
        answer="Ведомость готова.",
        sources=[],
        crag_status="UNVALIDATED",
        latency_sec=12.0,
        tokens=8,
        session_id="vor-live",
        history_id=history_id,
    )
    sessions = await get_chat_sessions(_user=object())
    live = next(session for session in sessions if session["session_id"] == "vor-live")
    messages = await get_chat_history(session_id="vor-live", _user=object())

    assert completed_id == history_id
    assert live["in_progress"] is False
    assert live["msg_count"] == 1
    assert messages[-1]["text"] == "Ведомость готова."
    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM chat_history WHERE session_id='vor-live'").fetchone()[0]
    assert count == 1


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
async def test_smeta_artifact_survives_chat_history_round_trip(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    db_path = tmp_path / "data" / "les_meta_qwen.db"
    monkeypatch.setenv("RAG_META_DB_PATH", str(db_path))
    _init_chat_history(db_path)
    artifact = {
        "mode": "xlsx",
        "title": "ЛСР — тестовая ВОР",
        "downloads": {"xlsx": "/api/smeta-artifacts/download?path=LSR_test.xlsx"},
        "files": {"xlsx_path": "storage/smeta_artifacts/LSR_test.xlsx"},
    }
    save_chat_history(
        question="Сделай ЛСР",
        answer="Смета готова.",
        sources=[],
        crag_status="PARTIAL",
        latency_sec=120,
        tokens=0,
        session_id="smeta-session",
        artifact=artifact,
    )

    messages = await get_chat_history(session_id="smeta-session", _user=object())

    assert messages[-1]["meta"]["artifact"] == artifact


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
