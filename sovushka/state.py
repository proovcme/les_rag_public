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
        add_log(
            f"[METRICS] CPU:{d.get('system',{}).get('cpu',0):.1f}%"
            f" RAM:{d.get('system',{}).get('ram_used',0):.1f}GB"
        )


async def refresh_status():
    d = await api_get("/api/status")
    if d:
        state["status"] = d
        mode = d.get("mode", {})
        if mode.get("mode"):
            state["mode"] = mode["mode"]


async def refresh_mlx():
    from sovushka.config import MLX_URL
    d = await api_get("/api/health", base=MLX_URL)
    if d:
        state["mlx_health"] = d
        m = d.get('main_model', '?')
        if isinstance(m, dict):
            m_str = f"{m.get('path', '?')} [{'LIVE' if m.get('loaded') else 'IDLE'}]"
        else:
            m_str = str(m)
        add_log(f"[MLX] UP · main={m_str}")
    else:
        state["mlx_health"] = {}


async def refresh_samovar():
    src = await api_get("/api/rag/sources")
    ds  = await api_get("/api/rag/datasets")
    if src is not None:
        state["sources"] = src
    if ds is not None:
        state["datasets"] = ds
    j = await api_get("/api/jobs")
    if j:
        state["jobs"] = j
    add_log(f"[С.А.М.О.В.А.Р.] {len(state['sources'])} папок")


async def bg_loop():
    """Главный фоновый цикл опроса."""
    tick = 0
    while True:
        await asyncio.sleep(5)
        tick += 1
        await refresh_metrics()
        if tick % 2 == 0:
            await refresh_status()
        if tick % 3 == 0:
            await refresh_mlx()
        if tick % 6 == 0:
            await refresh_samovar()
