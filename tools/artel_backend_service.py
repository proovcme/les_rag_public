"""АРТЕЛЬ Фабрика семейств — локальный бэкенд-сервис (спина пакета). 0 LLM в ядре.

Хаб, к которому ходят морда (Electron) и Revit-плагин. Несёт готовое детерминированное
ядро (`artel_datasheet_extractor`, `artel_family_action_plan`) и держит локальный store:
спецификации (draft→approved) и очередь заданий на генерацию. Плагин поллит `next_job`,
исполняет план в Revit, шлёт отчёт обратно. См. дизайн: products/artel/docs/family-factory-package.md

Автономно: SQLite в `ARTEL_DB_PATH`; ФОП из `ARTEL_SHARED_PARAMS_FILE` (опц.). Облако/ЛЕС —
поверх, здесь не требуются.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

try:  # pragma: no cover - import shim
    from tools import artel_datasheet_extractor as extractor
    from tools import artel_family_action_plan as planner
except ImportError:  # pragma: no cover
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from tools import artel_datasheet_extractor as extractor
    from tools import artel_family_action_plan as planner

JOB_PENDING = "pending"
JOB_RUNNING = "running"
JOB_DONE = "done"
JOB_FAILED = "failed"


def _db_path() -> str:
    explicit = os.getenv("ARTEL_DB_PATH")
    if explicit:
        return explicit
    root = os.getenv("APPDATA") or str(Path.home())
    d = Path(root) / "ARTEL"
    d.mkdir(parents=True, exist_ok=True)
    return str(d / "artel.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS artel_specs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft',
            spec_json TEXT NOT NULL DEFAULT '{}',
            geometry_json TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS artel_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            spec_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            plan_json TEXT NOT NULL DEFAULT '{}',
            report_json TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    return conn


def _fop_index() -> dict[str, dict[str, str]]:
    fop = os.getenv("ARTEL_SHARED_PARAMS_FILE")
    if fop and Path(fop).exists():
        return planner.build_fop_index(Path(fop).read_text(encoding="utf-8", errors="replace"))
    return {}


# ── Спецификации ────────────────────────────────────────────────────────────

def save_spec(spec: dict[str, Any], geometry: dict[str, Any] | None = None) -> dict[str, Any]:
    """Сохранить спецификацию (draft). Возвращает запись с id."""
    now = time.time()
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO artel_specs(name, category, status, spec_json, geometry_json, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?)""",
            (str(spec.get("familyName", "")), str(spec.get("revitCategory", "")),
             str(spec.get("status", "draft")), json.dumps(spec, ensure_ascii=False),
             json.dumps(geometry, ensure_ascii=False) if geometry else None, now, now),
        )
        conn.commit()
        return _spec_row(conn, int(cur.lastrowid))


def extract_spec_from_pdf(pdf_path: str, name: str, category: str) -> dict[str, Any] | None:
    """Техлист PDF → спец (0 модели) → сохранить как draft. None если таблица не распознана."""
    spec = extractor.datasheet_to_spec(pdf_path, family_name=name, category=category)
    return save_spec(spec) if spec else None


def extract_spec_from_table(matrix: list[list[Any]], name: str, category: str) -> dict[str, Any] | None:
    spec = extractor.table_to_spec(matrix, family_name=name, category=category)
    return save_spec(spec) if spec else None


def _spec_row(conn: sqlite3.Connection, spec_id: int) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM artel_specs WHERE id=?", (spec_id,)).fetchone()
    if not row:
        return {}
    item = dict(row)
    item["spec"] = json.loads(item.pop("spec_json") or "{}")
    item["geometry"] = json.loads(item["geometry_json"]) if item.get("geometry_json") else None
    item.pop("geometry_json", None)
    return item


def get_spec(spec_id: int) -> dict[str, Any]:
    with _connect() as conn:
        return _spec_row(conn, int(spec_id))


def list_specs() -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute("SELECT id, name, category, status, updated_at FROM artel_specs ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


def update_spec(spec_id: int, spec: dict[str, Any] | None = None, geometry: dict[str, Any] | None = None) -> dict[str, Any]:
    now = time.time()
    with _connect() as conn:
        if spec is not None:
            conn.execute(
                "UPDATE artel_specs SET name=?, category=?, spec_json=?, updated_at=? WHERE id=?",
                (str(spec.get("familyName", "")), str(spec.get("revitCategory", "")),
                 json.dumps(spec, ensure_ascii=False), now, int(spec_id)),
            )
        if geometry is not None:
            conn.execute("UPDATE artel_specs SET geometry_json=?, updated_at=? WHERE id=?",
                         (json.dumps(geometry, ensure_ascii=False), now, int(spec_id)))
        conn.commit()
        return _spec_row(conn, int(spec_id))


def approve_spec(spec_id: int) -> dict[str, Any]:
    with _connect() as conn:
        conn.execute("UPDATE artel_specs SET status='approved', updated_at=? WHERE id=?", (time.time(), int(spec_id)))
        conn.commit()
        return _spec_row(conn, int(spec_id))


# ── Компиляция и очередь заданий ────────────────────────────────────────────

def compile_plan(spec_id: int) -> dict[str, Any]:
    """Спец (+рецепт геометрии) → детерминированный план действий. 0 LLM."""
    rec = get_spec(spec_id)
    if not rec:
        raise ValueError(f"spec {spec_id} не найден")
    return planner.compile_action_plan(rec["spec"], _fop_index(), rec.get("geometry"))


def create_job(spec_id: int) -> dict[str, Any]:
    """Скомпилировать план и поставить задание на генерацию в очередь."""
    plan = compile_plan(spec_id)
    now = time.time()
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO artel_jobs(spec_id, status, plan_json, created_at, updated_at) VALUES (?,?,?,?,?)""",
            (int(spec_id), JOB_PENDING, json.dumps(plan, ensure_ascii=False), now, now),
        )
        conn.commit()
        return _job_row(conn, int(cur.lastrowid))


def next_job() -> dict[str, Any] | None:
    """Взять старейшее pending-задание (плагин на Idling). Помечает running."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM artel_jobs WHERE status=? ORDER BY id LIMIT 1", (JOB_PENDING,)
        ).fetchone()
        if not row:
            return None
        conn.execute("UPDATE artel_jobs SET status=?, updated_at=? WHERE id=?", (JOB_RUNNING, time.time(), row["id"]))
        conn.commit()
        return _job_row(conn, int(row["id"]))


def submit_report(job_id: int, report: dict[str, Any]) -> dict[str, Any]:
    """Плагин шлёт validation/generate report; задание done/failed по статусу отчёта."""
    status = JOB_FAILED if str(report.get("status", "")).lower() in ("fail", "failed", "error") else JOB_DONE
    with _connect() as conn:
        conn.execute(
            "UPDATE artel_jobs SET status=?, report_json=?, updated_at=? WHERE id=?",
            (status, json.dumps(report, ensure_ascii=False), time.time(), int(job_id)),
        )
        conn.commit()
        return _job_row(conn, int(job_id))


def _job_row(conn: sqlite3.Connection, job_id: int) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM artel_jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        return {}
    item = dict(row)
    item["plan"] = json.loads(item.pop("plan_json") or "{}")
    item["report"] = json.loads(item["report_json"]) if item.get("report_json") else None
    item.pop("report_json", None)
    return item


def get_job(job_id: int) -> dict[str, Any]:
    with _connect() as conn:
        return _job_row(conn, int(job_id))


def list_jobs() -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute("SELECT id, spec_id, status, updated_at FROM artel_jobs ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]
