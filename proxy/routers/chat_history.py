"""Chat history routes for LES Proxy."""

from __future__ import annotations

import logging
import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends

from backend.rag_config import rag_meta_db_path
from proxy.security import require_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.get("/history")
async def get_chat_history(limit: int = 40, session_id: Optional[str] = None, _user=Depends(require_user)):
    """Return recent chat messages, optionally scoped to a session."""
    try:
        with sqlite3.connect(rag_meta_db_path()) as conn:
            if session_id:
                rows = conn.execute(
                    "SELECT question, answer, sources, crag_status FROM chat_history "
                    "WHERE session_id=? ORDER BY id ASC",
                    (session_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT question, answer, sources, crag_status FROM chat_history "
                    "ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
                rows = list(reversed(rows))
        messages = []
        for question, answer, sources_text, crag_status in rows:
            sources = [source for source in (sources_text or "").split(",") if source]
            messages.append({"role": "user", "text": question})
            messages.append(
                {"role": "ai", "text": answer, "srcs": sources, "crag": crag_status or ""}
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
