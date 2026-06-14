"""Задачник Л.Е.С. — рабочая память задач (W16.2, LES3_PLAN).

ADR-11: создание/чтение задач из чата — детерминированные regex-команды и SQL,
LLM не участвует. Хранение — в метабазе рядом с chat_history.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import time
from typing import Any

from backend.rag_config import rag_meta_db_path

logger = logging.getLogger(__name__)

TASK_STATUSES = ("open", "in_progress", "done", "dropped")

# «поставь задачу …», «создай задачу …», «новая задача: …», «задача: …»
CREATE_TASK_RE = re.compile(
    r"^\s*(?:поставь|создай|добавь|новая)?\s*задач[ауи]\s*[:—-]?\s*(?P<title>.{3,300})$",
    re.IGNORECASE | re.DOTALL,
)
# «что по задачам», «мои задачи», «список задач», «покажи задачи»
LIST_TASKS_RE = re.compile(
    r"^\s*(?:что\s+(?:у\s+меня\s+)?по\s+задачам|мои\s+задачи|список\s+задач|покажи\s+задачи|задачи)\s*\??\s*$",
    re.IGNORECASE,
)
# «задача 5 готова/выполнена/закрой», «закрой задачу 5»
CLOSE_TASK_RE = re.compile(
    r"^\s*(?:закрой\s+)?задач[ау]\s*[№#]?\s*(?P<id>\d+)\s*(?:—|-|:)?\s*(?:готова?|выполнена?|сделана?|закрыть|закрой)?\s*$",
    re.IGNORECASE,
)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(rag_meta_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS les_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            details TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'open',
            dataset_filter TEXT NOT NULL DEFAULT '',
            link TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    try:  # Q3: партиционирование по объекту (project_id=0 — без объекта/глобально)
        conn.execute("ALTER TABLE les_tasks ADD COLUMN project_id INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    return conn


def create_task(title: str, details: str = "", dataset_filter: str = "", link: str = "", project_id: int = 0) -> dict[str, Any]:
    now = time.time()
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO les_tasks(title, details, status, dataset_filter, link, project_id, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (title.strip(), details.strip(), "open", dataset_filter, link, int(project_id), now, now),
        )
        conn.commit()
        task_id = cur.lastrowid
    logger.info("[TASKS] создана #%s: %s", task_id, title[:80])
    try:  # W17.2: детерминированные рёбра из задачи (НТД/[[вики]]/элемент), 0 LLM
        from proxy.services.edge_service import derive_edges_from_text
        derive_edges_from_text("task", str(task_id), f"{title}\n{details}", provenance=f"task#{task_id}")
    except Exception as edge_err:
        logger.warning("[EDGES] derive task#%s skipped: %s", task_id, edge_err)
    return get_task(task_id)


def get_task(task_id: int) -> dict[str, Any]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM les_tasks WHERE id=?", (task_id,)).fetchone()
    return dict(row) if row else {}


def list_tasks(status: str = "", limit: int = 50, project_id: int | None = None) -> list[dict[str, Any]]:
    clauses, params = [], []
    if status:
        clauses.append("status=?")
        params.append(status)
    if project_id is not None:  # Q3: фильтр по объекту (None → все)
        clauses.append("project_id=?")
        params.append(int(project_id))
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    order = ("ORDER BY id DESC" if status else
             "ORDER BY CASE status WHEN 'open' THEN 0 WHEN 'in_progress' THEN 1 ELSE 2 END, id DESC")
    with _connect() as conn:
        rows = conn.execute(f"SELECT * FROM les_tasks{where} {order} LIMIT ?", (*params, limit)).fetchall()
    return [dict(row) for row in rows]


def update_task(task_id: int, *, status: str | None = None, title: str | None = None, details: str | None = None) -> dict[str, Any]:
    fields, params = [], []
    if status is not None:
        if status not in TASK_STATUSES:
            raise ValueError(f"status must be one of {TASK_STATUSES}")
        fields.append("status=?")
        params.append(status)
    if title is not None:
        fields.append("title=?")
        params.append(title.strip())
    if details is not None:
        fields.append("details=?")
        params.append(details.strip())
    if not fields:
        return get_task(task_id)
    fields.append("updated_at=?")
    params.extend([time.time(), task_id])
    with _connect() as conn:
        conn.execute(f"UPDATE les_tasks SET {', '.join(fields)} WHERE id=?", params)
        conn.commit()
    return get_task(task_id)


def _format_task_line(task: dict[str, Any]) -> str:
    marker = {"open": "○", "in_progress": "◐", "done": "✓", "dropped": "✗"}.get(task["status"], "·")
    return f"{marker} #{task['id']} {task['title']}" + (f" [{task['dataset_filter']}]" if task["dataset_filter"] else "")


def maybe_handle_task_command(question: str, dataset_filter: str = "", project_id: int = 0) -> dict[str, Any] | None:
    """Детерминированный обработчик команд задачника из чата (ADR-11: без LLM).

    Возвращает готовый chat-ответ или None (не команда задачника).
    В режиме объекта (project_id>0) задачи создаются и перечисляются в рамках объекта.
    """
    text = question.strip()

    match = LIST_TASKS_RE.match(text)
    if match:
        tasks = list_tasks(limit=30, project_id=project_id or None)
        active = [t for t in tasks if t["status"] in ("open", "in_progress")]
        done_recent = [t for t in tasks if t["status"] == "done"][:5]
        if not tasks:
            answer = "Задач пока нет. Создать: «поставь задачу …»"
        else:
            lines = ["**Активные задачи:**" if active else "Активных задач нет."]
            lines += [_format_task_line(t) for t in active]
            if done_recent:
                lines.append("\n**Недавно закрытые:**")
                lines += [_format_task_line(t) for t in done_recent]
            answer = "\n".join(lines)
        return {"answer": answer, "operation": "tasks_list", "count": len(active)}

    match = CLOSE_TASK_RE.match(text)
    if match:
        task_id = int(match.group("id"))
        task = get_task(task_id)
        if not task:
            return {"answer": f"Задачи #{task_id} нет.", "operation": "task_close", "count": 0}
        updated = update_task(task_id, status="done")
        return {
            "answer": f"✓ Задача #{task_id} закрыта: {updated['title']}",
            "operation": "task_close",
            "count": 1,
        }

    match = CREATE_TASK_RE.match(text)
    if match:
        title = match.group("title").strip().rstrip(".")
        task = create_task(title, dataset_filter=dataset_filter or "", project_id=project_id)
        return {
            "answer": f"○ Задача #{task['id']} создана: {task['title']}\nЗакрыть: «задача {task['id']} готова»",
            "operation": "task_create",
            "count": 1,
            "task_id": task["id"],
        }

    return None
