"""Durable job service backed by SQLite."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from proxy.config import META_DB_PATH


class JobService:
    def __init__(self, db_path=META_DB_PATH):
        self.db_path = db_path
        self.init_db()

    def init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
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
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO jobs "
                "(id, type, status, source, dataset_id, dataset_name, total, processed, errors, message, result, started_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?, '{}', ?, ?)",
                (job_id, job_type, status, source, dataset_id, dataset_name, total, message, now, now),
            )
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
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"UPDATE jobs SET {set_clause} WHERE id=?",
                [updates[k] for k in keys] + [job_id],
            )
        return self.get(job_id) or {}

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return self._row_to_job(row) if row else None

    def list(self, limit: int = 200) -> Dict[str, Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return {row["id"]: self._row_to_job(row) for row in rows}

    def _row_to_job(self, row: sqlite3.Row) -> Dict[str, Any]:
        item = dict(row)
        try:
            item["result"] = json.loads(item.get("result") or "{}")
        except json.JSONDecodeError:
            item["result"] = {}
        return item
