"""Runtime, status, mode, warmup and metrics routes for LES Proxy."""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.metrics_collector import DB_PATH, heartbeats
from backend.rag_config import rag_meta_db_path, rag_runtime_config
from proxy.config import docker_control_enabled, mlx_url
from proxy.security import require_admin
from proxy.services.resource_governor import (
    active_parse_priority_order,
    enter_chat_mode,
    enter_indexing_mode,
    is_indexing_mode,
)
from proxy.services.runtime_admission import count_active_jobs, evaluate_chat_admission

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["runtime"])


class ModeRequest(BaseModel):
    mode: str
    model: str


class IndexingModeRequest(BaseModel):
    enabled: bool = True
    reason: str = "manual"
    unload_models: bool = True
    dataset_priority_order: list[str] | None = None


@dataclass
class RuntimeRouterState:
    rag_backend: Any
    current_mode: dict
    metrics_cache: dict
    chat_metrics: dict
    crag_stats: dict
    error_counts: dict
    llm_semaphore: asyncio.Semaphore
    llm_concurrency: int
    proxy_start: float
    job_service: Any = None
    job_tracker: dict[str, Any] | None = None

    @property
    def backend(self):
        return self.rag_backend() if callable(self.rag_backend) else self.rag_backend


_state: RuntimeRouterState | None = None


def set_runtime_state(state: RuntimeRouterState) -> None:
    global _state
    _state = state


def get_runtime_state() -> RuntimeRouterState:
    if _state is None:
        raise RuntimeError("runtime router state is not configured")
    return _state


def chat_admission_for_state(state: RuntimeRouterState):
    return evaluate_chat_admission(
        current_mode=state.current_mode,
        metrics_cache=state.metrics_cache,
        active_jobs=count_active_jobs(state.job_service, state.job_tracker),
        llm_available=getattr(state.llm_semaphore, "_value", 1) > 0,
    )


@router.get("/health")
async def health():
    backend = get_runtime_state().backend
    if not backend:
        return {"status": "starting", "backend": "none"}
    ok = await backend.health()
    response = {"status": "ok" if ok else "error", "backend": "qdrant_llama"}
    if hasattr(backend, "health_snapshot"):
        try:
            snapshot = await backend.health_snapshot()
            response["rag"] = snapshot
            rag_status = snapshot.get("status")
            if ok and rag_status in {"empty", "not_indexed", "degraded"}:
                response["status"] = "degraded"
        except Exception as error:
            logger.warning("[HEALTH] RAG snapshot failed: %s", error)
            response["rag"] = {"status": "unknown", "error": str(error)}
    response["embedding"] = rag_runtime_config()
    return response


@router.post("/warmup")
async def warmup_models(_admin=Depends(require_admin)):
    mlx_url = os.getenv("MLX_URL", "http://127.0.0.1:8080").rstrip("/")
    results = {}
    async with httpx.AsyncClient(timeout=120.0) as client:
        for name, model in [
            ("main", os.getenv("LLM_MODEL", "mlx-community/Qwen3-14B-4bit")),
            ("val", os.getenv("MLX_VAL_MODEL", "mlx-community/Qwen3-4B-4bit")),
        ]:
            try:
                started = time.time()
                response = await client.post(
                    f"{mlx_url}/v1/chat/completions",
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": "/no_think\n1"}],
                        "max_tokens": 1,
                        "temperature": 0.0,
                    },
                )
                response.raise_for_status()
                results[name] = {"status": "ok", "elapsed": round(time.time() - started, 1)}
            except Exception as e:
                results[name] = {"status": "error", "msg": str(e)}
    logger.info("[WARMUP] %s", results)
    return {"status": "done", "models": results}


@router.get("/mode")
async def get_mode():
    return get_runtime_state().current_mode


@router.post("/mode")
async def set_mode(req: ModeRequest, _admin=Depends(require_admin)):
    state = get_runtime_state()
    state.current_mode["mode"] = req.mode
    state.current_mode["model"] = req.model
    logger.info("[MODE] Switched to %s / %s", req.mode, req.model)
    return state.current_mode


async def _unload_mlx_models() -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(f"{mlx_url()}/api/unload_all", json={})
        result: Any
        try:
            result = response.json()
        except ValueError:
            result = response.text[:500]
        return {"ok": response.status_code == 200, "status_code": response.status_code, "result": result}
    except Exception as error:
        return {"ok": False, "error": str(error)}


async def _host_memory() -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{mlx_url()}/api/host_memory")
        response.raise_for_status()
        return response.json()
    except Exception as error:
        return {"error": str(error)}


@router.get("/indexing-mode")
async def get_indexing_mode():
    state = get_runtime_state()
    admission = chat_admission_for_state(state)
    return {
        "active": is_indexing_mode(state.current_mode),
        "mode": state.current_mode,
        "chat_generation_allowed": admission.allowed,
        "chat_generation_reason": admission.reason,
        "chat_admission": admission.payload(),
        "dataset_priority_order": active_parse_priority_order(state.current_mode),
    }


@router.post("/indexing-mode")
async def set_indexing_mode(req: IndexingModeRequest, _admin=Depends(require_admin)):
    state = get_runtime_state()
    unload = None
    if req.enabled:
        enter_indexing_mode(
            state.current_mode,
            reason=req.reason,
            priority_order=req.dataset_priority_order,
        )
        if req.unload_models:
            unload = await _unload_mlx_models()
    else:
        enter_chat_mode(state.current_mode, reason=req.reason)

    memory = await _host_memory()
    logger.info("[RESOURCE] indexing_mode=%s reason=%s", req.enabled, req.reason)
    return {
        "active": is_indexing_mode(state.current_mode),
        "mode": state.current_mode,
        "unload": unload,
        "memory": memory,
        "dataset_priority_order": active_parse_priority_order(state.current_mode),
    }


@router.get("/status")
async def get_status():
    state = get_runtime_state()
    mlx_url = os.getenv("MLX_URL", "http://127.0.0.1:8080")

    loaded_models = []
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"{mlx_url}/api/ps")
            if response.status_code == 200:
                for model in response.json().get("models", []):
                    loaded_models.append(
                        {
                            "name": model.get("name", "?"),
                            "size_gb": round(model.get("size", 0) / (1024**3), 1),
                            "vram_gb": round(model.get("size_vram", 0) / (1024**3), 1),
                            "expires_at": model.get("expires_at", ""),
                        }
                    )
    except Exception as e:
        logger.warning("MLX /api/ps error: %s", e)

    containers = []
    if docker_control_enabled():
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}\t{{.Image}}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in result.stdout.strip().splitlines():
                parts = line.split("\t")
                if len(parts) >= 3:
                    containers.append(
                        {
                            "name": parts[0],
                            "status": parts[1],
                            "image": parts[2],
                            "ok": "Up" in parts[1],
                        }
                    )
        except Exception as e:
            logger.warning("Docker ps error: %s", e)

    admission = chat_admission_for_state(state)
    return {
        "mode": state.current_mode,
        "mlx": {"models": loaded_models, "count": len(loaded_models)},
        "containers": containers,
        "proxy": {
            "uptime_sec": int(time.time() - state.proxy_start),
            "version": "2.1",
            "port": 8050,
            "llm_url": os.getenv("MLX_URL", "http://127.0.0.1:8080"),
            "llm_model": os.getenv("LLM_MODEL", "qwen3:14b"),
        },
        "chat_admission": admission.payload(),
        "embedding": rag_runtime_config(),
    }


@router.get("/metrics")
async def get_metrics():
    state = get_runtime_state()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM metrics ORDER BY id DESC LIMIT 60").fetchall()

    rag_stats = {"datasets": 0, "files": 0, "chunks": 0, "status": "unknown"}
    try:
        with sqlite3.connect(rag_meta_db_path()) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM datasets")
            rag_stats["datasets"] = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM documents")
            rag_stats["files"] = cur.fetchone()[0] or 0
        backend = state.backend
        if backend:
            collection = await backend.aclient.get_collection(backend.collection_name)
            rag_stats["chunks"] = collection.points_count or 0
            rag_stats["status"] = "ready" if rag_stats["chunks"] > 0 else "indexing"
    except Exception as e:
        logger.warning("RAG stats error: %s", e)
        rag_stats["status"] = "error"

    crag_total = max(1, sum(state.crag_stats.values()))
    crag_verified = state.crag_stats.get("verified", 0)
    crag_no_data = state.crag_stats.get("no_data", 0)
    crag_hallucination = state.crag_stats.get("hallucination", 0)
    crag_unvalidated = state.crag_stats.get("unvalidated", 0)
    cache_total = max(1, state.chat_metrics.get("cache_hit", 0) + state.chat_metrics.get("cache_miss", 0))
    retrieval_total = max(1, state.chat_metrics.get("retrieval_good", 0) + state.chat_metrics.get("retrieval_weak", 0))
    ram_used = rows[0]["ram_used"] if rows else 0
    ram_total = state.metrics_cache.get("ram_total", rows[0]["ram_total"] if rows else 0)
    ram_free = state.metrics_cache.get("ram_free_gb")
    if ram_free is None:
        ram_free = max(0, ram_total - ram_used)
    latest = rows[0] if rows else {}
    latest_keys = set(latest.keys()) if hasattr(latest, "keys") else set()
    llm_ram = latest["llm_ram"] if "llm_ram" in latest_keys else 0
    return {
        "system": {
            "cpu": latest["cpu"] if rows else 0,
            "ram_used": ram_used,
            "ram_free_gb": ram_free,
            "ram_total": ram_total,
            "swap_used": state.metrics_cache.get("swap_used_gb", latest["swap_used"] if rows else 0),
            "swap_total": state.metrics_cache.get("swap_total_gb", 0),
            "swap_pct": state.metrics_cache.get("swap_pct", 0),
            "disk_used": latest["disk_used"] if rows else 0,
            "disk_total": latest["disk_total"] if rows else 0,
            "llm_ram": llm_ram,
            "network_ok": latest["network_ok"] if rows else 0,
        },
        "pipeline": {
            "latency_search": state.chat_metrics["latency_search"][-10:],
            "latency_gen": state.chat_metrics["latency_gen"][-10:],
            "tokens": state.chat_metrics["tokens"][-10:],
            "crag_pass_rate": crag_verified / crag_total,
            "crag_verified_rate": crag_verified / crag_total,
            "crag_nodata_rate": crag_no_data / crag_total,
            "crag_halluc_rate": crag_hallucination / crag_total,
            "crag_unvalidated_rate": crag_unvalidated / crag_total,
            "cache_hit_rate": state.chat_metrics.get("cache_hit", 0) / cache_total,
            "retrieval_good_rate": state.chat_metrics.get("retrieval_good", 0) / retrieval_total,
            "total_requests": sum(state.crag_stats.values()),
        },
        "queue": {"llm_waiting": max(0, state.llm_concurrency - state.llm_semaphore._value)},
        "errors": dict(state.error_counts),
        "heartbeats": heartbeats,
        "rag": rag_stats,
        "embedding": rag_runtime_config(),
    }
