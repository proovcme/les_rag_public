"""Chat history routes for LES Proxy."""

from __future__ import annotations

import logging
import json
import os
import sqlite3
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from backend.rag_config import rag_meta_db_path
from proxy.security import require_user
from proxy.routers.chat import ensure_chat_history_schema
from proxy.services.context_memory_service import get_chat_profile

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

NEGATIVE_FEEDBACK = {"bad_answer", "incorrect", "wrong_dataset", "bad_source"}


class ChatFeedbackRequest(BaseModel):
    feedback: str
    comment: Optional[str] = None
    correct_answer: Optional[str] = None
    correct_dataset_filter: Optional[str] = None

    @field_validator("feedback")
    @classmethod
    def feedback_allowed(cls, value: str) -> str:
        normalized = value.strip().lower()
        allowed = {"correct", "bad_answer", "incorrect", "partial", "wrong_dataset", "bad_source"}
        if normalized not in allowed:
            raise ValueError(f"feedback must be one of: {', '.join(sorted(allowed))}")
        return normalized


def _json_list(raw: str | None) -> list:
    try:
        value = json.loads(raw or "[]")
        return value if isinstance(value, list) else []
    except Exception:
        return []


def _json_object(raw: str | None) -> dict:
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _feedback_log_path() -> Path:
    return Path(os.getenv("CHAT_FEEDBACK_LOG_PATH", "logs/chat_feedback.jsonl"))


def _preview(text: str | None, limit: int = 500) -> str:
    value = " ".join(str(text or "").split())
    return value[:limit]


def _append_feedback_event(event: dict) -> None:
    path = _feedback_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


@router.get("/history")
async def get_chat_history(limit: int = 40, session_id: Optional[str] = None, _user=Depends(require_user)):
    """Return recent chat messages, optionally scoped to a session."""
    try:
        with sqlite3.connect(rag_meta_db_path()) as conn:
            ensure_chat_history_schema(conn)
            if session_id:
                rows = conn.execute(
                    "SELECT id, question, answer, sources, crag_status, query_route_json, "
                    "retrieval_trace_json, cache_type, validation_enabled, feedback_status FROM chat_history "
                    "WHERE session_id=? ORDER BY id ASC",
                    (session_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, question, answer, sources, crag_status, query_route_json, "
                    "retrieval_trace_json, cache_type, validation_enabled, feedback_status FROM chat_history "
                    "ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
                rows = list(reversed(rows))
        messages = []
        for (
            history_id,
            question,
            answer,
            sources_text,
            crag_status,
            route,
            trace,
            cache_type,
            validation_enabled,
            feedback_status,
        ) in rows:
            sources = [source for source in (sources_text or "").split(",") if source]
            messages.append({"role": "user", "text": question})
            meta = {
                "history_id": history_id,
                "query_route": _json_object(route),
                "retrieval_trace": _json_object(trace),
                "cache": cache_type or "miss",
                "validation": {"enabled": bool(validation_enabled)},
            }
            if feedback_status:
                meta["feedback"] = feedback_status
            messages.append(
                {
                    "role": "ai",
                    "text": answer,
                    "srcs": sources,
                    "crag": crag_status or "",
                    "meta": meta,
                }
            )
        return messages
    except Exception as e:
        logger.warning("[HISTORY] %s", e)
        return []


@router.get("/sessions")
async def get_chat_sessions(limit: int = 50, _user=Depends(require_user)):
    """Return chat sessions ordered by last activity."""
    try:
        with sqlite3.connect(rag_meta_db_path()) as conn:
            rows = conn.execute(
                """
                SELECT
                    session_id,
                    MIN(timestamp)   AS started_at,
                    MAX(timestamp)   AS last_at,
                    COUNT(*)         AS msg_count,
                    MIN(question)    AS first_question
                FROM chat_history
                WHERE session_id IS NOT NULL
                GROUP BY session_id
                ORDER BY last_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "session_id": row[0],
                "started_at": row[1],
                "last_at": row[2],
                "msg_count": row[3],
                "first_question": (row[4] or "")[:120],
            }
            for row in rows
        ]
    except Exception as e:
        logger.warning("[SESSIONS] %s", e)
        return []


@router.get("/memory/{session_id}")
async def get_chat_memory(session_id: str, _user=Depends(require_user)):
    """Return deterministic context profile for a chat session."""
    profile = get_chat_profile(session_id)
    if not profile:
        raise HTTPException(status_code=404, detail="chat memory profile not found")
    return profile


@router.post("/history/{history_id}/feedback")
async def save_chat_feedback(history_id: int, req: ChatFeedbackRequest, _user=Depends(require_user)):
    """Store user confirmation/correction for a chat answer."""
    try:
        feedback_user = getattr(_user, "holder", "") or getattr(_user, "source", "")
        with sqlite3.connect(rag_meta_db_path()) as conn:
            ensure_chat_history_schema(conn)
            cur = conn.execute(
                """
                UPDATE chat_history
                SET feedback_status=?,
                    feedback_comment=?,
                    feedback_correct_answer=?,
                    feedback_correct_dataset_filter=?,
                    feedback_at=CURRENT_TIMESTAMP,
                    feedback_user=?
                WHERE id=?
                """,
                (
                    req.feedback,
                    req.comment or "",
                    req.correct_answer or "",
                    req.correct_dataset_filter or "",
                    feedback_user,
                    history_id,
                ),
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="chat history row not found")
            row = conn.execute(
                """
                SELECT
                    id, feedback_status, feedback_comment, feedback_correct_dataset_filter, feedback_at,
                    question, answer, sources, crag_status, requested_dataset_filter,
                    effective_dataset_filter, source_dataset_names, source_dataset_mismatch,
                    route_channel, route_reason, retrieval_quality, cache_type, validation_enabled
                FROM chat_history WHERE id=?
                """,
                (history_id,),
            ).fetchone()
        event = {
            "event": "chat_feedback",
            "history_id": row[0],
            "feedback": row[1],
            "comment": row[2] or "",
            "correct_dataset_filter": row[3] or "",
            "feedback_at": row[4],
            "user": feedback_user,
            "question": _preview(row[5], 500),
            "answer_preview": _preview(row[6], 700),
            "sources": [source for source in (row[7] or "").split(",") if source],
            "crag_status": row[8] or "",
            "requested_dataset_filter": row[9] or "",
            "effective_dataset_filter": row[10] or "",
            "source_dataset_names": _json_list(row[11]),
            "source_dataset_mismatch": bool(row[12]),
            "route_channel": row[13] or "",
            "route_reason": row[14] or "",
            "retrieval_quality": row[15] or "",
            "cache_type": row[16] or "",
            "validation_enabled": bool(row[17]),
        }
        _append_feedback_event(event)
        log_message = (
            "[CHAT_FEEDBACK] feedback=%s history_id=%s user=%s crag=%s route=%s/%s "
            "effective_filter=%s sources=%s question=%r"
        )
        log_args = (
            event["feedback"],
            event["history_id"],
            event["user"],
            event["crag_status"],
            event["route_channel"],
            event["route_reason"],
            event["effective_dataset_filter"],
            ",".join(event["sources"]),
            event["question"],
        )
        if event["feedback"] in NEGATIVE_FEEDBACK:
            logger.warning(log_message, *log_args)
        else:
            logger.info(log_message, *log_args)
        return {
            "status": "saved",
            "history_id": row[0],
            "feedback": row[1],
            "comment": row[2],
            "correct_dataset_filter": row[3],
            "feedback_at": row[4],
            "log": str(_feedback_log_path()),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("[FEEDBACK] %s", e)
        raise HTTPException(status_code=500, detail="failed to save feedback")


@router.get("/learning")
async def get_learning_history(
    limit: int = 100,
    confirmed_only: bool = False,
    _user=Depends(require_user),
):
    """Return successful/confirmed answers for routing and dataset heuristics."""
    try:
        with sqlite3.connect(rag_meta_db_path()) as conn:
            ensure_chat_history_schema(conn)
            conn.row_factory = sqlite3.Row
            if confirmed_only:
                where = "feedback_status='correct'"
            else:
                where = "success=1 OR feedback_status IN ('correct', 'partial', 'bad_answer', 'incorrect', 'wrong_dataset', 'bad_source')"
            rows = conn.execute(
                f"""
                SELECT
                    id, timestamp, question, answer, crag_status, sources,
                    requested_dataset_filter, effective_dataset_filter,
                    resolved_dataset_names, source_dataset_names, source_dataset_mismatch,
                    route_channel, route_reason, retrieval_quality,
                    feedback_status, feedback_comment, feedback_correct_dataset_filter
                FROM chat_history
                WHERE {where}
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "timestamp": row["timestamp"],
                "question": row["question"],
                "answer": row["answer"],
                "crag_status": row["crag_status"],
                "sources": [source for source in (row["sources"] or "").split(",") if source],
                "requested_dataset_filter": row["requested_dataset_filter"] or "",
                "effective_dataset_filter": row["effective_dataset_filter"] or "",
                "resolved_dataset_names": _json_list(row["resolved_dataset_names"]),
                "source_dataset_names": _json_list(row["source_dataset_names"]),
                "source_dataset_mismatch": bool(row["source_dataset_mismatch"]),
                "route_channel": row["route_channel"] or "",
                "route_reason": row["route_reason"] or "",
                "retrieval_quality": row["retrieval_quality"] or "",
                "feedback_status": row["feedback_status"] or "",
                "feedback_comment": row["feedback_comment"] or "",
                "feedback_correct_dataset_filter": row["feedback_correct_dataset_filter"] or "",
            }
            for row in rows
        ]
    except Exception as e:
        logger.warning("[LEARNING] %s", e)
        return []
