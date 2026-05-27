"""Read-only diagnostics route for LES Proxy."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime

import httpx
import psutil
from fastapi import APIRouter, Depends

from backend.rag_config import rag_collection_name, rag_meta_db_path, rag_runtime_config
from proxy.security import require_internal_or_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["diagnostics"])


@dataclass
class DiagnosticsRouterState:
    crag_stats: dict
    proxy_start: float


_state: DiagnosticsRouterState | None = None


def set_diagnostics_state(state: DiagnosticsRouterState) -> None:
    global _state
    _state = state


def get_diagnostics_state() -> DiagnosticsRouterState:
    if _state is None:
        raise RuntimeError("diagnostics router state is not configured")
    return _state


@router.get("/diag")
async def run_diagnostics(_internal=Depends(require_internal_or_admin)):
    """Read-only diagnostics for Sovushka."""
    state = get_diagnostics_state()
    results = []
    started_total = time.time()

    async def _check(name: str, coro):
        started = time.time()
        try:
            status, value, expected, message = await coro
        except Exception as e:
            status, value, expected, message = "err", "exception", "-", str(e)[:120]
        results.append(
            {
                "name": name,
                "status": status,
                "value": str(value),
                "expected": str(expected),
                "message": message,
                "latency_ms": round((time.time() - started) * 1000, 1),
            }
        )

    async def _chk_proxy():
        uptime = int(time.time() - state.proxy_start)
        return "ok", f"UP {uptime}s", "UP", f"port 8050 | {os.getenv('LLM_MODEL', '?')}"

    await _check("les-proxy :8050", _chk_proxy())

    async def _chk_qdrant():
        qdrant_url = os.getenv("QDRANT_URL", "http://127.0.0.1:6333")
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{qdrant_url}/collections")
            response.raise_for_status()
            collections = response.json().get("result", {}).get("collections", [])
        total_points = 0
        async with httpx.AsyncClient(timeout=5.0) as client:
            for collection in collections:
                try:
                    response = await client.get(f"{qdrant_url}/collections/{collection['name']}")
                    total_points += response.json().get("result", {}).get("points_count", 0) or 0
                except Exception:
                    pass
        status = "ok" if total_points > 0 else "warn"
        active_collection = rag_collection_name()
        return status, f"{total_points} pts / {len(collections)} cols; active={active_collection}", ">0", ""

    await _check("Qdrant :6333", _chk_qdrant())

    async def _chk_llm():
        llm_url = os.getenv("MLX_URL", "http://127.0.0.1:8080")
        llm_model = os.getenv("LLM_MODEL", "?")
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{llm_url}/api/health")
                data = response.json()
            main_model = data.get("main_model", {})
            model_path = main_model.get("path", llm_model) if isinstance(main_model, dict) else str(main_model)
            loaded = main_model.get("loaded", False) if isinstance(main_model, dict) else True
            embed_model = data.get("embed_model", {})
            embed_ok = embed_model.get("loaded", False) if isinstance(embed_model, dict) else False
            status = "ok" if loaded else "warn"
            return status, model_path.split("/")[-1], "loaded", f"embed={'OK' if embed_ok else 'lazy'}"
        except Exception as e:
            return "err", "?", "loaded", str(e)

    await _check("MLX Backend", _chk_llm())

    async def _chk_ram():
        vm = psutil.virtual_memory()
        pct = vm.percent
        used = vm.used / 1024**3
        total = vm.total / 1024**3
        status = "ok" if pct < 85 else ("warn" if pct < 95 else "err")
        return status, f"{used:.1f}/{total:.1f} GB ({pct:.0f}%)", "<85%", ""

    await _check("RAM", _chk_ram())

    async def _chk_cpu():
        cpu = await asyncio.to_thread(psutil.cpu_percent, interval=0.5)
        status = "ok" if cpu < 80 else ("warn" if cpu < 95 else "err")
        return status, f"{cpu:.1f}%", "<80%", ""

    await _check("CPU", _chk_cpu())

    async def _chk_disk():
        usage = psutil.disk_usage("/")
        status = "ok" if usage.percent < 85 else ("warn" if usage.percent < 95 else "err")
        return status, f"{usage.percent:.0f}% занято, {usage.free / 1024**3:.0f} GB свободно", "<85%", ""

    await _check("Диск", _chk_disk())

    async def _chk_no_docker():
        return "ok", "removed", "no Docker", "Qdrant/proxy/UI/MLX run on host LaunchAgents"

    await _check("Docker runtime", _chk_no_docker())

    async def _chk_sqlite():
        def _query():
            with sqlite3.connect(rag_meta_db_path()) as conn:
                datasets = conn.execute("SELECT COUNT(*) FROM datasets").fetchone()[0]
                docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            return datasets, docs

        datasets, docs = await asyncio.to_thread(_query)
        status = "ok" if datasets > 0 else "warn"
        return status, f"{datasets} датасетов / {docs} документов", ">=1 ds", ""

    await _check("SQLite метабаза", _chk_sqlite())

    async def _chk_chat():
        started = time.time()
        llm_url = os.getenv("MLX_URL", "http://127.0.0.1:8080")
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"{llm_url}/api/health")
        ms = (time.time() - started) * 1000
        ok = response.status_code == 200
        status = "ok" if ms < 5000 else ("warn" if ms < 15000 else "err")
        return status, f"{ms:.0f} ms", "<5000 ms", "MLX health OK" if ok else f"HTTP {response.status_code}"

    await _check("MLX latency", _chk_chat())

    async def _chk_net():
        def _ping():
            try:
                conn = socket.create_connection(("8.8.8.8", 53), timeout=3)
                conn.close()
                return True
            except Exception:
                return False

        ok = await asyncio.to_thread(_ping)
        return ("ok" if ok else "warn"), ("доступен" if ok else "недоступен"), "connected", ""

    await _check("Интернет", _chk_net())

    async def _chk_crag():
        total = max(1, sum(state.crag_stats.values()))
        verified = state.crag_stats.get("verified", 0)
        no_data = state.crag_stats.get("no_data", 0)
        hallucination = state.crag_stats.get("hallucination", 0)
        unvalidated = state.crag_stats.get("unvalidated", 0)
        pct = verified / total * 100
        status = "ok" if pct >= 70 else ("warn" if pct >= 40 else "err")
        return status, f"V:{verified} N:{no_data} H:{hallucination} U:{unvalidated} ({pct:.0f}% verified)", ">=70%", ""

    await _check("Т.О.С.К.А. статистика", _chk_crag())

    total_ms = round((time.time() - started_total) * 1000, 1)
    ok_count = sum(1 for result in results if result["status"] == "ok")
    warn_count = sum(1 for result in results if result["status"] == "warn")
    err_count = sum(1 for result in results if result["status"] == "err")
    overall = "ok" if err_count == 0 and warn_count <= 1 else ("warn" if err_count == 0 else "err")

    logger.info("[DIAG] %s ok, %s warn, %s err за %.0fмс", ok_count, warn_count, err_count, total_ms)
    return {
        "overall": overall,
        "ok_count": ok_count,
        "warn_count": warn_count,
        "err_count": err_count,
        "total_ms": total_ms,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "embedding": rag_runtime_config(),
        "checks": results,
    }
