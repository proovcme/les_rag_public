"""
С.О.В.У.Ш.К.А. v5.0 — Глобальное состояние и HTTP-клиент
"""
from __future__ import annotations

import asyncio
import httpx
from datetime import datetime
from typing import Optional, Union

# ─────────────────────────────────────────
# СОСТОЯНИЕ ПРИЛОЖЕНИЯ
# ─────────────────────────────────────────
state = {
    "mode": "rag",
    "mode_model": "mlx-community/Qwen3-14B-4bit",
    "metrics": {},
    "status": {},
    "mlx_health": {},
    "datasets": [],
    "sources": [],
    "jobs": {},
    "chat_history": [],   # list of {role, text, srcs, crag}
    "logs": [],
    "mermaid_last": "",
    "output_template": None,  # образец таблицы выдачи
    "diag_results": [],       # последний прогон диагностики
    "diag_running": False,
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

async def api_get(path: str, base: Optional[str] = None) -> Optional[Union[dict, list]]:
    from sovushka.config import PROXY_URL
    if base is None:
        base = PROXY_URL
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            r = await client.get(f"{base}{path}")
            r.raise_for_status()
            return r.json()
    except Exception as e:
        add_log(f"[ERR] GET {path}: {e}")
        return None


async def api_post(path: str, data: Optional[dict] = None, base: Optional[str] = None) -> Optional[dict]:
    from sovushka.config import PROXY_URL
    if base is None:
        base = PROXY_URL
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            r = await client.post(f"{base}{path}", json=data or {})
            r.raise_for_status()
            return r.json()
    except Exception as e:
        add_log(f"[ERR] POST {path}: {e}")
        return None


async def api_delete(path: str, base: Optional[str] = None) -> Optional[dict]:
    from sovushka.config import PROXY_URL
    if base is None:
        base = PROXY_URL
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            r = await client.delete(f"{base}{path}")
            r.raise_for_status()
            return r.json()
    except Exception as e:
        add_log(f"[ERR] DELETE {path}: {e}")
        return None


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


async def refresh_samovar():
    prev_count = len(state["sources"])
    src = await api_get("/api/rag/sources")
    ds  = await api_get("/api/rag/datasets")
    if src is not None:
        state["sources"] = src
    if ds is not None:
        state["datasets"] = ds
    j = await api_get("/api/jobs")
    if j:
        state["jobs"] = j
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
        await asyncio.sleep(10)  # был 5с — уменьшает нагрузку на логи
        tick += 1
        await refresh_metrics()
        if tick % 2 == 0:
            await refresh_status()
        if tick % 3 == 0:
            await refresh_mlx()
        if tick % 6 == 0:
            await refresh_samovar()
