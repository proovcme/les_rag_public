"""
С.О.В.У.Ш.К.А. v5.0 — Глобальное состояние и HTTP-клиент
"""
from __future__ import annotations

import asyncio
import httpx
import json
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
    "proxy_health": {},
    "mlx_health": {},
    "datasets": [],
    "rag_health": {},
    "rag_documents": {},
    "indexing_mode": {},
    "reindex": {},          # W5.2: прогресс реиндекса из push-канала /api/live
    "proxy_logs": [],
    "sources": [],
    "jobs": {},
    "jobs_summary": {},
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
    # W5.3: индикатор «proxy недоступен» — поднимается при connect/timeout-сбоях.
    "proxy_online": True,
    "proxy_offline_reason": "",
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


def _api_success() -> None:
    """Успешный ответ proxy → сброс ошибки и индикатора недоступности (W5.3)."""
    state["last_api_error"] = None
    state["proxy_online"] = True
    state["proxy_offline_reason"] = ""


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
    # W5.3: честное сообщение и индикатор «proxy недоступен» — отличаем сетевую
    # недоступность/таймаут (proxy не отвечает) от прикладной HTTP-ошибки.
    elif isinstance(exc, httpx.TimeoutException):
        detail = "превышено время ожидания ответа (proxy перегружен или не отвечает)"
        state["proxy_online"] = False
        state["proxy_offline_reason"] = "timeout"
    elif isinstance(exc, httpx.TransportError):
        detail = "proxy недоступен (нет соединения) — проверь, запущен ли сервис :8050"
        state["proxy_online"] = False
        state["proxy_offline_reason"] = "offline"
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
            _api_success()
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
            _api_success()
            return r.json()
    except Exception as e:
        _api_error("POST", path, e)
        return None


async def api_post_stream(path: str, data: Optional[dict], on_event, base: Optional[str] = None) -> bool:
    """W5.1: POST с чтением Server-Sent Events. Для каждого события вызывает
    `on_event(event: str, payload)` — payload уже распарсен из JSON (для `token`
    это строка-кусок ответа, для `final`/`error` — dict, для `reset` — "").
    Возвращает True, если получено событие `final` (ответ дошёл целиком)."""
    from sovushka.config import PROXY_URL
    if base is None:
        base = PROXY_URL
    got_final = False
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream(
                "POST", f"{base}{path}", json=data or {}, headers=_auth_headers()
            ) as r:
                if r.status_code != 200:
                    body = (await r.aread()).decode("utf-8", "replace")
                    raise httpx.HTTPStatusError(body[:300], request=r.request, response=r)
                _api_success()
                event: Optional[str] = None
                data_buf: list[str] = []
                async for line in r.aiter_lines():
                    if line == "":  # конец события — диспатчим накопленное
                        if event is not None and data_buf:
                            raw = "\n".join(data_buf)
                            try:
                                payload = json.loads(raw)
                            except json.JSONDecodeError:
                                payload = raw
                            on_event(event, payload)
                            if event == "final":
                                got_final = True
                        event, data_buf = None, []
                        continue
                    if line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:"):
                        data_buf.append(line[5:].lstrip())
        return got_final
    except Exception as e:
        _api_error("POST", path, e)
        return False


async def api_get_bytes(path: str, base: Optional[str] = None) -> Optional[tuple[bytes, str]]:
    """GET бинарного файла (xlsx-отчёты и т.п.) → (содержимое, имя файла) или None."""
    from sovushka.config import PROXY_URL
    if base is None:
        base = PROXY_URL
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            r = await client.get(f"{base}{path}", headers=_auth_headers())
            r.raise_for_status()
            disp = r.headers.get("content-disposition", "")
            fname = ""
            if "filename=" in disp:
                fname = disp.split("filename=", 1)[1].strip('"; ')
            _api_success()
            return r.content, (fname or path.rsplit("/", 1)[-1])
    except Exception as e:
        _api_error("GET", path, e)
        return None


async def api_patch(path: str, data: Optional[dict] = None, base: Optional[str] = None) -> Optional[dict]:
    from sovushka.config import PROXY_URL
    if base is None:
        base = PROXY_URL
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            r = await client.patch(f"{base}{path}", json=data or {}, headers=_auth_headers())
            r.raise_for_status()
            _api_success()
            return r.json()
    except Exception as e:
        _api_error("PATCH", path, e)
        return None


async def api_delete(path: str, base: Optional[str] = None) -> Optional[dict]:
    from sovushka.config import PROXY_URL
    if base is None:
        base = PROXY_URL
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            r = await client.delete(f"{base}{path}", headers=_auth_headers())
            r.raise_for_status()
            _api_success()
            return r.json()
    except Exception as e:
        _api_error("DELETE", path, e)
        return None


def last_api_error_text(default: str = "Ошибка API") -> str:
    err = state.get("last_api_error") or {}
    status = err.get("status_code")
    detail = err.get("detail") or default
    return f"{status}: {detail}" if status else detail


def proxy_online() -> bool:
    """W5.3: доступен ли proxy по последним запросам (для индикатора в шапке)."""
    return bool(state.get("proxy_online", True))


# W5.3: TTL-кэш GET-ответов — гасит дубль-запросы одинаковых путей с разных
# таймеров/вкладок в окне ttl. Кэш per-процесс; None (ошибка) не кэшируется.
_GET_CACHE: dict[str, tuple[float, Union[dict, list]]] = {}


async def api_get_cached(path: str, ttl: float = 2.0, base: Optional[str] = None) -> Optional[Union[dict, list]]:
    import time as _time

    key = f"{base or ''}{path}"
    hit = _GET_CACHE.get(key)
    now = _time.monotonic()
    if hit and now - hit[0] < ttl:
        return hit[1]
    data = await api_get(path, base=base)
    if data is not None:
        _GET_CACHE[key] = (now, data)
    return data


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
    # W5.3: TTL-кэш гасит дубль-опрос /api/metrics с разных вкладок/таймеров в окне 2с.
    d = await api_get_cached("/api/metrics", ttl=2.0)
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

    logs_path = Path("logs/proxy.log")
    if logs_path.exists():
        try:
            lines = await asyncio.to_thread(lambda: logs_path.read_text(errors="replace").splitlines()[-limit:])
            state["proxy_logs"] = lines
            return state.get("proxy_logs", [])
        except Exception as error:
            add_log(f"[LOGS] local proxy.log read error: {error}")

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
                    COALESCE(doc.route_dataset, '') AS route_dataset,
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
        state["proxy_health"] = health
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
    j = await api_get("/api/jobs/summary?limit=120")
    if isinstance(j, dict):
        state["jobs_summary"] = j
        state["jobs"] = {
            str(item.get("id") or ""): item
            for item in (j.get("jobs") or [])
            if isinstance(item, dict) and item.get("id")
        }
    await refresh_proxy_logs(120)
    # Логируем только при изменении количества источников
    now_count = len(state["sources"])
    if now_count != prev_count:
        add_log(f"[С.А.М.О.В.А.Р.] Источников: {prev_count} → {now_count}")


def _apply_live_snapshot(snap: dict) -> None:
    """W5.2: применяет push-снимок /api/live в state — зеркалит логику
    refresh_metrics/status/indexing_mode/samovar(jobs), но без HTTP."""
    m = snap.get("metrics")
    if isinstance(m, dict) and "error" not in m:
        state["metrics"] = m
    s = snap.get("status")
    if isinstance(s, dict) and "error" not in s:
        state["status"] = s
        mode = s.get("mode", {})
        if isinstance(mode, dict) and mode.get("mode"):
            state["mode"] = mode["mode"]
    im = snap.get("indexing_mode")
    if isinstance(im, dict) and "error" not in im:
        state["indexing_mode"] = im
    rx = snap.get("reindex")
    if isinstance(rx, dict) and "error" not in rx:
        state["reindex"] = rx
    j = snap.get("jobs_summary")
    if isinstance(j, dict) and "error" not in j:
        state["jobs_summary"] = j
        state["jobs"] = {
            str(item.get("id") or ""): item
            for item in (j.get("jobs") or [])
            if isinstance(item, dict) and item.get("id")
        }


async def live_subscribe() -> bool:
    """W5.2: подписка на /api/live (SSE) — единый push вместо частого поллинга.
    Обновляет state на каждый снимок. Возвращает при штатном завершении/обрыве —
    bg_loop переподключает. True, если соединение открывалось успешно."""
    from sovushka.config import PROXY_URL

    opened = False
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=None)) as client:
            async with client.stream("GET", f"{PROXY_URL}/api/live", headers=_auth_headers()) as r:
                if r.status_code != 200:
                    return False
                opened = True
                _api_success()
                event: Optional[str] = None
                data_buf: list[str] = []
                async for line in r.aiter_lines():
                    if line == "":
                        if event == "snapshot" and data_buf:
                            try:
                                snap = json.loads("\n".join(data_buf))
                            except json.JSONDecodeError:
                                snap = None
                            if isinstance(snap, dict):
                                _apply_live_snapshot(snap)
                        event, data_buf = None, []
                        continue
                    if line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:"):
                        data_buf.append(line[5:].lstrip())
        return opened
    except (httpx.TimeoutException, httpx.TransportError):
        state["proxy_online"] = False
        state["proxy_offline_reason"] = "offline"
        return opened
    except Exception:
        return opened


async def bg_loop():
    """Главный фоновый цикл (W5.2: push-first).

    Высокочастотное (metrics/status/indexing/jobs) приходит push-каналом
    `live_subscribe()` одним долгоживущим SSE-соединением. Здесь остаётся только
    редкое и тяжёлое (mlx-health 30с, samovar 60с) + переподключение push при
    обрыве. Если push недоступен — деградация на прежний поллинг, чтобы UI не
    «застывал»."""
    live_task: Optional[asyncio.Task] = None
    tick = 0
    while True:
        # Поднять/переподнять push-канал, если он не жив.
        if live_task is None or live_task.done():
            live_task = asyncio.create_task(live_subscribe())
            await asyncio.sleep(1.0)  # дать снимку прийти до первого фолбэка

        await asyncio.sleep(10)
        tick += 1
        push_alive = live_task is not None and not live_task.done()
        try:
            if not push_alive:
                # Фолбэк-поллинг, пока push лежит.
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
