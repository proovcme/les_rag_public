import os
import time
import sqlite3
import json
from pathlib import Path
from typing import Dict, Any, List

class MetricsCollector:
    def __init__(self, db_path: str = "./data/les_metrics.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    cpu REAL,
                    ram_used REAL,
                    ram_total REAL,
                    datasets INTEGER,
                    chunks INTEGER,
                    chat_latency REAL,
                    crag_verified INTEGER,
                    crag_no_data INTEGER
                )
            """)

    def record(self, cpu: float, ram_used: float, ram_total: float, datasets: int, chunks: int, latency: float, crag_v: int, crag_n: int):
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO metrics (ts, cpu, ram_used, ram_total, datasets, chunks, chat_latency, crag_verified, crag_no_data) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (time.time(), cpu, ram_used, ram_total, datasets, chunks, latency, crag_v, crag_n)
            )
            conn.execute("DELETE FROM metrics WHERE ts < ?", (time.time() - 86400,))

    def get_latest(self) -> Dict[str, Any]:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM metrics ORDER BY ts DESC LIMIT 1").fetchone()
            return dict(row) if row else {"status": "no_data"}

    def get_history(self, limit: int = 60) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM metrics ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in reversed(rows)]
