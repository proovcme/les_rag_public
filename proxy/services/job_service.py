"""Durable job service backed by SQLite."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from proxy.config import META_DB_PATH


class JobService:
    def __init__(self, db_path=META_DB_PATH):
        self.db_path = db_path
        self.init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _with_retry(self, fn):
        last_error = None
        for attempt in range(3):
            try:
                return fn()
            except sqlite3.OperationalError as error:
                last_error = error
                if "disk I/O error" not in str(error) and "locked" not in str(error):
                    raise
                time.sleep(0.2 * (attempt + 1))
        raise last_error

    def init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    source TEXT DEFAULT '',
                    dataset_id TEXT DEFAULT '',
                    dataset_name TEXT DEFAULT '',
                    total INTEGER DEFAULT 0,
                    processed INTEGER DEFAULT 0,
                    errors INTEGER DEFAULT 0,
                    message TEXT DEFAULT '',
                    result TEXT DEFAULT '{}',
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    finished_at TEXT DEFAULT NULL
                )
                """
            )

    def create(
        self,
        job_type: str,
        source: str = "",
        dataset_id: str = "",
        dataset_name: str = "",
        total: int = 0,
        status: str = "queued",
        message: str = "",
    ) -> Dict[str, Any]:
        job_id = str(uuid.uuid4())[:12]
        now = datetime.now().isoformat()
        def _insert():
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO jobs "
                    "(id, type, status, source, dataset_id, dataset_name, total, processed, errors, message, result, started_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?, '{}', ?, ?)",
                    (job_id, job_type, status, source, dataset_id, dataset_name, total, message, now, now),
                )
        self._with_retry(_insert)
        return self.get(job_id) or {}

    def update(self, job_id: str, **updates) -> Dict[str, Any]:
        if not updates:
            return self.get(job_id) or {}
        updates["updated_at"] = datetime.now().isoformat()
        if updates.get("status") in {"completed", "failed", "cancelled"} and "finished_at" not in updates:
            updates["finished_at"] = updates["updated_at"]
        if "result" in updates and not isinstance(updates["result"], str):
            updates["result"] = json.dumps(updates["result"], ensure_ascii=False)
        keys = list(updates.keys())
        set_clause = ", ".join(f"{k}=?" for k in keys)
        def _update():
            with self._connect() as conn:
                conn.execute(
                    f"UPDATE jobs SET {set_clause} WHERE id=?",
                    [updates[k] for k in keys] + [job_id],
                )
        self._with_retry(_update)
        return self.get(job_id) or {}

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        def _get():
            with self._connect() as conn:
                conn.row_factory = sqlite3.Row
                return conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        row = self._with_retry(_get)
        return self._row_to_job(row) if row else None

    def list(self, limit: int = 200) -> Dict[str, Dict[str, Any]]:
        def _list():
            with self._connect() as conn:
                conn.row_factory = sqlite3.Row
                return conn.execute(
                    "SELECT * FROM jobs ORDER BY started_at DESC LIMIT ?", (limit,)
                ).fetchall()
        rows = self._with_retry(_list)
        return {row["id"]: self._row_to_job(row) for row in rows}

    def mark_interrupted_active_jobs(self, reason: str) -> int:
        """Mark durable active jobs as interrupted after process restart."""
        now = datetime.now().isoformat()
        message = f"Interrupted by {reason}"

        def _update():
            with self._connect() as conn:
                cursor = conn.execute(
                    """
                    UPDATE jobs
                    SET status='cancelled',
                        message=CASE
                            WHEN COALESCE(message, '') = '' THEN ?
                            ELSE message || ' | ' || ?
                        END,
                        updated_at=?,
                        finished_at=?
                    WHERE finished_at IS NULL
                      AND lower(status) IN ('queued', 'running')
                    """,
                    (message, message, now, now),
                )
                return cursor.rowcount

        return int(self._with_retry(_update) or 0)

    def _row_to_job(self, row: sqlite3.Row) -> Dict[str, Any]:
        item = dict(row)
        try:
            item["result"] = json.loads(item.get("result") or "{}")
        except json.JSONDecodeError:
            item["result"] = {}
        return item
