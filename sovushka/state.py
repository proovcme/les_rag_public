"""
С.О.В.У.Ш.К.А. v5.0 — Глобальное состояние и HTTP-клиент
"""
from __future__ import annotations

import asyncio
import httpx
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from nicegui import app
from typing import Optional, Union

# ─────────────────────────────────────────
# СОСТОЯНИЕ ПРИЛОЖЕНИЯ
# ─────────────────────────────────────────
def _new_session_id() -> str:
    return str(uuid.uuid4())


state = {
    "mode": "rag",
    "mode_model": "mlx-community/Qwen3-14B-4bit",
    "metrics": {},
    "status": {},
    "mlx_health": {},
    "datasets": [],
    "rag_health": {},
    "rag_documents": {},
    "indexing_mode": {},
    "proxy_logs": [],
    "sources": [],
    "jobs": {},
    "chat_history": [],        # list of {role, text, srcs, crag}
    "session_id": _new_session_id(),  # UUID текущей сессии чата
    "chat_pending": None,      # {question, started_at} для восстановления UI после реконнекта
    "load_session_id": None,   # если задан — чат отобразит эту сессию
    "logs": [],
    "mermaid_last": "",
    "output_template": None,
    "diag_results": [],
    "diag_running": False,
    "last_api_error": None,
}

# ─────────────────────────────────────────
# HTTP КЛИЕНТ (используется локально в функциях)
# ─────────────────────────────────────────

# ─────────────────────────────────────────
# ЛОГ-ЭЛЕМЕНТ (заполняется в build_log_terminal)
# ─────────────────────────────────────────
log_element = None


# ─────────────────────────────────────────
# API ХЕЛПЕРЫ
# ─────────────────────────────────────────

def _auth_headers() -> dict:
    try:
        key = app.storage.user.get("key", "")
    except Exception:
        key = ""
    return {"X-API-Key": key} if key else {}


def _api_error(method: str, path: str, exc: Exception) -> None:
    detail = str(exc)
    status_code = None
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        try:
            body = exc.response.json()
            detail = body.get("detail", detail) if isinstance(body, dict) else str(body)
        except Exception:
            detail = exc.response.text or detail
    state["last_api_error"] = {
        "method": method,
        "path": path,
        "status_code": status_code,
        "detail": detail,
    }
    prefix = f"{status_code} " if status_code else ""
    add_log(f"[ERR] {method} {path}: {prefix}{detail}")

async def api_get(path: str, base: Optional[str] = None) -> Optional[Union[dict, list]]:
    from sovushka.config import PROXY_URL
    if base is None:
        base = PROXY_URL
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            r = await client.get(f"{base}{path}", headers=_auth_headers())
            r.raise_for_status()
            state["last_api_error"] = None
            return r.json()
    except Exception as e:
        _api_error("GET", path, e)
        return None


async def api_post(path: str, data: Optional[dict] = None, base: Optional[str] = None) -> Optional[dict]:
    from sovushka.config import PROXY_URL
    if base is None:
        base = PROXY_URL
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            r = await client.post(f"{base}{path}", json=data or {}, headers=_auth_headers())
            r.raise_for_status()
            state["last_api_error"] = None
            return r.json()
    except Exception as e:
        _api_error("POST", path, e)
        return None


async def api_delete(path: str, base: Optional[str] = None) -> Optional[dict]:
    from sovushka.config import PROXY_URL
    if base is None:
        base = PROXY_URL
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            r = await client.delete(f"{base}{path}", headers=_auth_headers())
            r.raise_for_status()
            state["last_api_error"] = None
            return r.json()
    except Exception as e:
        _api_error("DELETE", path, e)
        return None


def last_api_error_text(default: str = "Ошибка API") -> str:
    err = state.get("last_api_error") or {}
    status = err.get("status_code")
    detail = err.get("detail") or default
    return f"{status}: {detail}" if status else detail


# ─────────────────────────────────────────
# ЛОГИ
# ─────────────────────────────────────────

def add_log(msg: str):
    t = datetime.now().strftime("%H:%M:%S")
    line = f"> [{t}] {msg}"
    state["logs"].append(line)
    if len(state["logs"]) > 200:
        state["logs"] = state["logs"][-200:]
    if log_element is not None:
        log_element.push(line)


# ─────────────────────────────────────────
# ФОНОВЫЕ ОБНОВЛЕНИЯ
# ─────────────────────────────────────────

async def refresh_metrics():
    d = await api_get("/api/metrics")
    if d:
        state["metrics"] = d
        # Не логируем каждый тик — только молча обновляем state


async def refresh_status():
    d = await api_get("/api/status")
    if d:
        state["status"] = d
        mode = d.get("mode", {})
        if mode.get("mode"):
            state["mode"] = mode["mode"]


async def refresh_indexing_mode():
    d = await api_get("/api/indexing-mode")
    if isinstance(d, dict):
        state["indexing_mode"] = d
        mode = d.get("mode", {})
        if isinstance(mode, dict) and mode.get("mode"):
            state["mode"] = mode["mode"]
    return state.get("indexing_mode", {})


async def refresh_proxy_logs(limit: int = 120):
    from sovushka.config import PROXY_URL

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{PROXY_URL}/api/logs/recent?limit={limit}", headers=_auth_headers())
            r.raise_for_status()
            d = r.json()
        if isinstance(d, dict):
            state["proxy_logs"] = d.get("lines", [])
            return state.get("proxy_logs", [])
    except Exception:
        pass

    logs_path = Path("logs/proxy.log")
    if logs_path.exists():
        try:
            lines = await asyncio.to_thread(lambda: logs_path.read_text(errors="replace").splitlines()[-limit:])
            state["proxy_logs"] = lines
        except Exception as error:
            add_log(f"[LOGS] local proxy.log read error: {error}")
    return state.get("proxy_logs", [])


async def refresh_mlx():
    from sovushka.config import MLX_URL
    prev_loaded = state["mlx_health"].get("main_model", {}).get("loaded") if isinstance(state["mlx_health"].get("main_model"), dict) else None
    d = await api_get("/api/health", base=MLX_URL)
    if d:
        state["mlx_health"] = d
        m = d.get('main_model', '?')
        if isinstance(m, dict):
            now_loaded = m.get("loaded")
            # Логируем только если статус модели изменился
            if now_loaded != prev_loaded:
                m_str = f"{m.get('path', '?')} [{'LIVE' if now_loaded else 'IDLE'}]"
                add_log(f"[MLX] Статус изменился: {m_str}")
    else:
        if state["mlx_health"]:  # логируем только при потере связи
            add_log("[MLX] Host недоступен")
        state["mlx_health"] = {}


def _local_rag_documents(limit: int = 120) -> dict:
    db_path = Path(os.getenv("RAG_META_DB_PATH", "data/les_meta.db"))
    if not db_path.exists():
        return {}
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            summary_rows = conn.execute(
                """
                SELECT status, COUNT(*) AS files, COALESCE(SUM(chunk_count),0) AS chunks
                FROM documents
                GROUP BY status
                """
            ).fetchall()
            rows = conn.execute(
                """
                SELECT
                    doc.id,
                    doc.dataset_id,
                    COALESCE(ds.name, '') AS dataset_name,
                    doc.file_name,
                    doc.status,
                    COALESCE(doc.file_size, 0) AS file_size,
                    COALESCE(doc.chunk_count, 0) AS chunk_count,
                    COALESCE(doc.domain, '') AS domain,
                    COALESCE(doc.doc_type, '') AS doc_type,
                    COALESCE(doc.content_type, '') AS content_type,
                    COALESCE(doc.complexity, '') AS complexity,
                    COALESCE(doc.pipeline, '') AS pipeline,
                    COALESCE(doc.last_error, '') AS last_error
                FROM documents doc
                LEFT JOIN datasets ds ON ds.id = doc.dataset_id
                ORDER BY
                    CASE doc.status
                        WHEN 'ERROR' THEN 0
                        WHEN 'INDEXED' THEN 1
                        WHEN 'PENDING' THEN 2
                        ELSE 3
                    END,
                    doc.chunk_count DESC,
                    doc.file_name
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return {
            "total": len(rows),
            "limit": limit,
            "offset": 0,
            "source": "sqlite",
            "summary": {
                row["status"]: {"files": row["files"], "chunks": row["chunks"]}
                for row in summary_rows
            },
            "documents": [dict(row) for row in rows],
        }
    except Exception as error:
        add_log(f"[С.А.М.О.В.А.Р.] SQLite documents fallback error: {error}")
        return {}


async def refresh_samovar():
    prev_count = len(state["sources"])
    src = await api_get("/api/rag/sources")
    ds  = await api_get("/api/rag/datasets")
    health = await api_get("/api/health")
    await refresh_indexing_mode()
    if src is not None:
        state["sources"] = src
    if ds is not None:
        state["datasets"] = ds
    if isinstance(health, dict):
        state["rag_health"] = health.get("rag", {})
    # The proxy owns the active RAG profile (collection/meta DB). Use the API
    # first so Qwen/BGE profile switches do not show stale legacy SQLite rows.
    docs = await api_get("/api/rag/documents?limit=120")
    if not isinstance(docs, dict):
        docs = await asyncio.to_thread(_local_rag_documents, 120)
    elif "source" not in docs:
        docs["source"] = "api_active_profile"
    if isinstance(docs, dict):
        state["rag_documents"] = docs
    j = await api_get("/api/jobs")
    if j:
        state["jobs"] = j
    await refresh_proxy_logs(120)
    # Логируем только при изменении количества источников
    now_count = len(state["sources"])
    if now_count != prev_count:
        add_log(f"[С.А.М.О.В.А.Р.] Источников: {prev_count} → {now_count}")


async def bg_loop():
    """Главный фоновый цикл опроса.

    Расписание (интервал тика = 10с):
      - metrics:  каждые 10с
      - status:   каждые 20с  (tick % 2)
      - mlx:      каждые 30с  (tick % 3)
      - samovar:  каждые 60с  (tick % 6)
    """
    tick = 0
    while True:
        await asyncio.sleep(10)
        tick += 1
        try:
            await refresh_metrics()
            if tick % 2 == 0:
                await refresh_status()
                await refresh_indexing_mode()
            if tick % 3 == 0:
                await refresh_mlx()
            if tick % 6 == 0:
                await refresh_samovar()
        except Exception as e:
            add_log(f"[bg_loop] Ошибка тика {tick}: {e}")
