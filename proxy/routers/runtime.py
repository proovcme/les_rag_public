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
from backend.rag_config import embed_profile_name, embedding_model_id, rag_meta_db_path
from proxy.config import docker_control_enabled, mlx_url
from proxy.security import require_admin
from proxy.services.resource_governor import (
    active_parse_priority_order,
    chat_generation_allowed,
    enter_chat_mode,
    enter_indexing_mode,
    is_indexing_mode,
)

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
    allowed, reason = chat_generation_allowed(state.current_mode)
    return {
        "active": is_indexing_mode(state.current_mode),
        "mode": state.current_mode,
        "chat_generation_allowed": allowed,
        "chat_generation_reason": reason,
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

    models = []
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"{mlx_url}/api/ps")
            if response.status_code == 200:
                for model in response.json().get("models", []):
                    models.append(
                        {
                            "name": model.get("name", "?"),
                            "size_gb": round(model.get("size", 0) / (1024**3), 1),
                            "vram_gb": round(model.get("size_vram", 0) / (1024**3), 1),
                            "expires_at": model.get("expires_at", ""),
                        }
                    )
    except Exception as e:
        logger.warning("Ollama /api/ps error: %s", e)

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

    return {
        "mode": state.current_mode,
        "ollama": {"models": models, "count": len(models)},
        "containers": containers,
        "proxy": {
            "uptime_sec": int(time.time() - state.proxy_start),
            "version": "2.1",
            "port": 8050,
            "llm_url": os.getenv("MLX_URL", "http://127.0.0.1:8080"),
            "llm_model": os.getenv("LLM_MODEL", "qwen3:14b"),
        },
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
    return {
        "system": {
            "cpu": rows[0]["cpu"] if rows else 0,
            "ram_used": rows[0]["ram_used"] if rows else 0,
            "ram_total": state.metrics_cache.get("ram_total", rows[0]["ram_total"] if rows else 0),
            "swap_used": state.metrics_cache.get("swap_used_gb", rows[0]["swap_used"] if rows else 0),
            "swap_total": state.metrics_cache.get("swap_total_gb", 0),
            "swap_pct": state.metrics_cache.get("swap_pct", 0),
            "disk_used": rows[0]["disk_used"] if rows else 0,
            "disk_total": rows[0]["disk_total"] if rows else 0,
            "ollama_ram": rows[0]["ollama_ram"] if rows else 0,
            "network_ok": rows[0]["network_ok"] if rows else 0,
        },
        "pipeline": {
            "latency_search": state.chat_metrics["latency_search"][-10:],
            "latency_gen": state.chat_metrics["latency_gen"][-10:],
            "tokens": state.chat_metrics["tokens"][-10:],
            "crag_pass_rate": state.crag_stats["verified"] / crag_total,
            "crag_verified_rate": state.crag_stats["verified"] / crag_total,
            "crag_nodata_rate": state.crag_stats["no_data"] / crag_total,
            "crag_halluc_rate": state.crag_stats["hallucination"] / crag_total,
            "total_requests": sum(state.crag_stats.values()),
        },
        "queue": {"llm_waiting": max(0, state.llm_concurrency - state.llm_semaphore._value)},
        "errors": dict(state.error_counts),
        "heartbeats": heartbeats,
        "rag": rag_stats,
        "embedding": {
            "profile": embed_profile_name(),
            "model": embedding_model_id(),
            "meta_db": rag_meta_db_path(),
            "collection": getattr(state.backend, "collection_name", ""),
            "vector_size": getattr(state.backend, "vector_size", 0),
        },
    }
