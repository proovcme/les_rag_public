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
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.metrics_collector import DB_PATH, heartbeats
from backend.rag_config import rag_meta_db_path, rag_runtime_config
from proxy.config import docker_control_enabled, mlx_url
from proxy.security import require_admin
from proxy.services.resource_governor import (
    active_parse_priority_order,
    current_runtime_profile,
    enter_chat_mode,
    enter_indexing_mode,
    is_indexing_mode,
    normalize_runtime_profile,
)
from proxy.services.runtime_admission import (
    count_active_jobs,
    evaluate_chat_admission,
    evaluate_memory_pressure,
    generation_semaphore,
)
from proxy.services.runtime_dispatcher import DEFAULT_DATASETS, DispatcherError, RuntimeDispatcher

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["runtime"])


def summarize_phases(phases: list[dict]) -> dict[str, float]:
    """W0.1: среднее по каждой фазе латентности за накопленные запросы."""
    if not phases:
        return {}
    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for entry in phases:
        for key, value in entry.items():
            if isinstance(value, (int, float)):
                totals[key] = totals.get(key, 0.0) + float(value)
                counts[key] = counts.get(key, 0) + 1
    return {key: round(totals[key] / counts[key], 3) for key in totals}


class ModeRequest(BaseModel):
    mode: str
    model: str
    runtime_profile: str | None = None


class IndexingModeRequest(BaseModel):
    enabled: bool = True
    reason: str = "manual"
    unload_models: bool = True
    dataset_priority_order: list[str] | None = None


class DispatcherReindexRequest(BaseModel):
    datasets: list[str] = Field(default_factory=lambda: list(DEFAULT_DATASETS), min_length=1, max_length=20)
    parse_method: str = Field(default="scheduler", pattern="^(scheduler|batch)$")
    min_free_gb: float = Field(default=4.0, ge=0.5, le=64.0)
    max_swap_pct: float = Field(default=85.0, ge=0.0, le=100.0)
    post_min_free_gb: float = Field(default=3.0, ge=0.5, le=64.0)
    post_max_swap_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    memory_wait_sec: float = Field(default=86400.0, ge=0.0, le=604800.0)
    memory_poll_sec: float = Field(default=30.0, ge=1.0, le=3600.0)
    cooldown_sec: float = Field(default=90.0, ge=0.0, le=3600.0)
    parse_timeout: float = Field(default=3600.0, ge=60.0, le=86400.0)
    unload_between_docs: bool = True
    auth_smoke_after: bool = True
    reset_state: bool = False


class DispatcherPauseRequest(BaseModel):
    reason: str = Field(default="operator", max_length=200)


class DispatcherRouteChangeRequest(BaseModel):
    source_root: str = "RAG_Content"
    dry_run: bool = True
    max_docs: int = Field(default=0, ge=0, le=500)
    min_free_gb: float = Field(default=4.0, ge=0.5, le=64.0)
    max_swap_pct: float = Field(default=85.0, ge=0.0, le=100.0)
    post_min_free_gb: float = Field(default=3.0, ge=0.5, le=64.0)
    post_max_swap_pct: float = Field(default=85.0, ge=0.0, le=100.0)
    memory_wait_sec: float = Field(default=86400.0, ge=0.0, le=604800.0)
    memory_poll_sec: float = Field(default=30.0, ge=1.0, le=3600.0)
    cooldown_sec: float = Field(default=90.0, ge=0.0, le=3600.0)
    parse_timeout: float = Field(default=3600.0, ge=60.0, le=86400.0)


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
    active_reindex_jobs = 0
    try:
        active_reindex_jobs = 1 if dispatcher_for_state(state).reindex_status_payload().get("running") else 0
    except Exception:
        active_reindex_jobs = 0
    return evaluate_chat_admission(
        current_mode=state.current_mode,
        metrics_cache=state.metrics_cache,
        active_jobs=count_active_jobs(state.job_service, state.job_tracker) + active_reindex_jobs,
        llm_available=getattr(generation_semaphore(state.llm_semaphore), "_value", 1) > 0,
    )


def _provider_status() -> dict[str, str]:
    provider = os.getenv("LES_LLM_PROVIDER", "mlx").strip().lower() or "mlx"
    if provider == "openrouter":
        return {
            "provider": provider,
            "base_url": os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            "model": os.getenv("OPENROUTER_MODEL", ""),
        }
    if provider in {"openai", "openai-compatible", "openai_compatible"}:
        return {
            "provider": provider,
            "base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            "model": os.getenv("OPENAI_MODEL", ""),
        }
    if provider == "ollama":
        return {
            "provider": provider,
            "base_url": os.getenv("OLLAMA_BASE_URL", os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")),
            "model": os.getenv("OLLAMA_MODEL", ""),
        }
    if provider == "lemonade":
        return {
            "provider": provider,
            "base_url": os.getenv("LEMONADE_BASE_URL", "http://127.0.0.1:13305/api/v1"),
            "model": os.getenv("LEMONADE_MODEL", ""),
        }
    return {
        "provider": "mlx",
        "base_url": os.getenv("MLX_URL", "http://127.0.0.1:8080"),
        "model": os.getenv("LLM_MODEL", "qwen3:14b"),
    }


def dispatcher_for_state(state: RuntimeRouterState) -> RuntimeDispatcher:
    return RuntimeDispatcher(current_mode=state.current_mode, metrics_cache=state.metrics_cache)


def _dispatcher_error(error: DispatcherError) -> HTTPException:
    detail: Any = {"message": error.detail}
    if error.payload:
        detail["dispatcher"] = error.payload
    return HTTPException(status_code=error.status_code, detail=detail)


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
    state = get_runtime_state()
    admission = chat_admission_for_state(state)
    if not admission.allowed:
        raise HTTPException(status_code=admission.status_code, detail=admission.reason)
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
    if req.runtime_profile:
        state.current_mode["runtime_profile"] = normalize_runtime_profile(req.runtime_profile)
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
    memory_pressure = evaluate_memory_pressure(state.metrics_cache)
    return {
        "active": is_indexing_mode(state.current_mode),
        "mode": state.current_mode,
        "runtime_profile": current_runtime_profile(state.current_mode),
        "memory_state": memory_pressure.payload(),
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
    memory_state = evaluate_memory_pressure(memory).payload()
    logger.info("[RESOURCE] indexing_mode=%s reason=%s", req.enabled, req.reason)
    return {
        "active": is_indexing_mode(state.current_mode),
        "mode": state.current_mode,
        "runtime_profile": current_runtime_profile(state.current_mode),
        "memory_state": memory_state,
        "unload": unload,
        "memory": memory,
        "dataset_priority_order": active_parse_priority_order(state.current_mode),
    }


@router.get("/runtime/dispatcher/status")
async def runtime_dispatcher_status(_admin=Depends(require_admin)):
    state = get_runtime_state()
    dispatcher = dispatcher_for_state(state)
    return await asyncio.to_thread(dispatcher.status_payload)


@router.post("/runtime/dispatcher/reindex/start")
async def runtime_dispatcher_reindex_start(req: DispatcherReindexRequest, _admin=Depends(require_admin)):
    state = get_runtime_state()
    dispatcher = dispatcher_for_state(state)
    try:
        return await asyncio.to_thread(
            dispatcher.start_reindex,
            datasets=req.datasets,
            parse_method=req.parse_method,
            min_free_gb=req.min_free_gb,
            max_swap_pct=req.max_swap_pct,
            post_min_free_gb=req.post_min_free_gb,
            post_max_swap_pct=req.post_max_swap_pct,
            memory_wait_sec=req.memory_wait_sec,
            memory_poll_sec=req.memory_poll_sec,
            cooldown_sec=req.cooldown_sec,
            parse_timeout=req.parse_timeout,
            unload_between_docs=req.unload_between_docs,
            auth_smoke_after=req.auth_smoke_after,
            reset_state=req.reset_state,
        )
    except DispatcherError as error:
        raise _dispatcher_error(error) from error


@router.post("/runtime/dispatcher/reindex/pause")
async def runtime_dispatcher_reindex_pause(req: DispatcherPauseRequest, _admin=Depends(require_admin)):
    state = get_runtime_state()
    dispatcher = dispatcher_for_state(state)
    try:
        return await asyncio.to_thread(dispatcher.pause_reindex, reason=req.reason)
    except DispatcherError as error:
        raise _dispatcher_error(error) from error


@router.post("/runtime/dispatcher/reindex/resume")
async def runtime_dispatcher_reindex_resume(req: DispatcherReindexRequest, _admin=Depends(require_admin)):
    state = get_runtime_state()
    dispatcher = dispatcher_for_state(state)
    try:
        return await asyncio.to_thread(
            dispatcher.resume_reindex,
            datasets=req.datasets,
            parse_method=req.parse_method,
            min_free_gb=req.min_free_gb,
            max_swap_pct=req.max_swap_pct,
            post_min_free_gb=req.post_min_free_gb,
            post_max_swap_pct=req.post_max_swap_pct,
            memory_wait_sec=req.memory_wait_sec,
            memory_poll_sec=req.memory_poll_sec,
            cooldown_sec=req.cooldown_sec,
            parse_timeout=req.parse_timeout,
            unload_between_docs=req.unload_between_docs,
            auth_smoke_after=req.auth_smoke_after,
            reset_state=req.reset_state,
        )
    except DispatcherError as error:
        raise _dispatcher_error(error) from error


@router.get("/runtime/dispatcher/route-changes/status")
async def runtime_dispatcher_route_changes_status(_admin=Depends(require_admin)):
    state = get_runtime_state()
    dispatcher = dispatcher_for_state(state)
    return await asyncio.to_thread(dispatcher.route_change_status_payload)


@router.post("/runtime/dispatcher/route-changes/start")
async def runtime_dispatcher_route_changes_start(req: DispatcherRouteChangeRequest, _admin=Depends(require_admin)):
    state = get_runtime_state()
    dispatcher = dispatcher_for_state(state)
    try:
        return await asyncio.to_thread(
            dispatcher.start_route_change_reindex,
            source_root=req.source_root,
            dry_run=req.dry_run,
            max_docs=req.max_docs,
            min_free_gb=req.min_free_gb,
            max_swap_pct=req.max_swap_pct,
            post_min_free_gb=req.post_min_free_gb,
            post_max_swap_pct=req.post_max_swap_pct,
            memory_wait_sec=req.memory_wait_sec,
            memory_poll_sec=req.memory_poll_sec,
            cooldown_sec=req.cooldown_sec,
            parse_timeout=req.parse_timeout,
        )
    except DispatcherError as error:
        raise _dispatcher_error(error) from error


@router.post("/runtime/dispatcher/route-changes/pause")
async def runtime_dispatcher_route_changes_pause(req: DispatcherPauseRequest, _admin=Depends(require_admin)):
    state = get_runtime_state()
    dispatcher = dispatcher_for_state(state)
    try:
        return await asyncio.to_thread(dispatcher.pause_route_change_reindex, reason=req.reason)
    except DispatcherError as error:
        raise _dispatcher_error(error) from error


@router.post("/runtime/dispatcher/mlx/unload")
async def runtime_dispatcher_mlx_unload(_admin=Depends(require_admin)):
    unload = await _unload_mlx_models()
    state = get_runtime_state()
    dispatcher = dispatcher_for_state(state)
    status = await asyncio.to_thread(dispatcher.status_payload)
    return {"status": "ok" if unload.get("ok") else "error", "unload": unload, "dispatcher": status}


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
    memory_pressure = evaluate_memory_pressure(state.metrics_cache)
    return {
        "mode": state.current_mode,
        "runtime_profile": current_runtime_profile(state.current_mode),
        "memory_state": memory_pressure.payload(),
        "mlx": {"models": loaded_models, "count": len(loaded_models)},
        "containers": containers,
        "proxy": {
            "uptime_sec": int(time.time() - state.proxy_start),
            "version": "2.1",
            "port": 8050,
            "llm_url": os.getenv("MLX_URL", "http://127.0.0.1:8080"),
            "llm_model": os.getenv("LLM_MODEL", "qwen3:14b"),
            "llm_provider": _provider_status(),
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
            "latency_phases": state.chat_metrics.get("latency_phases", [])[-10:],
            "latency_phases_avg": summarize_phases(state.chat_metrics.get("latency_phases", [])),
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
        # W3.3: расходы облака накопительно за аптайм proxy (токены/$).
        "cost": {
            "cloud_requests": state.chat_metrics.get("cloud_requests", 0),
            "cloud_prompt_tokens": state.chat_metrics.get("cloud_prompt_tokens", 0),
            "cloud_completion_tokens": state.chat_metrics.get("cloud_completion_tokens", 0),
            "cloud_cost_usd": round(state.chat_metrics.get("cloud_cost_usd", 0.0), 4),
            "cloud_cost_by_model": dict(state.chat_metrics.get("cloud_cost_by_model", {})),
        },
    }


@router.get("/backup/status")
async def get_backup_status(_admin=Depends(require_admin)):
    """
    Returns lists of existing SQLite backups and Qdrant snapshots.
    """
    from datetime import datetime
    from pathlib import Path
    from backend.rag_config import embed_profile_name, rag_collection_name
    from qdrant_client import QdrantClient
    
    # 1. SQLite backups
    profile = embed_profile_name()
    backup_dir = Path("storage/backups")
    sqlite_backups = []
    if backup_dir.exists():
        pattern = f"les_meta_{profile}_*.db"
        for p in sorted(backup_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True):
            sqlite_backups.append({
                "name": p.name,
                "path": str(p),
                "size_bytes": p.stat().st_size,
                "created_at": datetime.fromtimestamp(p.stat().st_mtime).isoformat(),
            })

    # 2. Qdrant snapshots
    qdrant_snapshots = []
    collection_name = rag_collection_name()
    try:
        qdrant_url = os.getenv("QDRANT_URL", "http://127.0.0.1:6333")
        client = QdrantClient(url=qdrant_url, timeout=5.0)
        if client.collection_exists(collection_name):
            snaps = client.list_snapshots(collection_name)
            # Sort newest first
            snaps_sorted = sorted(snaps, key=lambda s: s.creation_time or "", reverse=True)
            for s in snaps_sorted:
                qdrant_snapshots.append({
                    "name": s.name,
                    "size_bytes": s.size,
                    "created_at": s.creation_time,
                })
    except Exception as e:
        logger.warning("Failed to list Qdrant snapshots for status: %s", e)

    return {
        "sqlite_backups": sqlite_backups,
        "qdrant_snapshots": qdrant_snapshots,
        "collection_name": collection_name,
        "profile": profile,
    }


class BackupDeleteRequest(BaseModel):
    type: str  # "sqlite" or "qdrant"
    name: str


@router.post("/backup/create")
async def create_backup(_admin=Depends(require_admin)):
    """
    Triggers both SQLite and Qdrant backups.
    """
    from tools.backup_suharik import run_sqlite_backup, run_qdrant_backup
    
    def _run():
        sqlite_ok, sqlite_res = run_sqlite_backup()
        qdrant_ok, qdrant_res = run_qdrant_backup()
        return sqlite_ok, sqlite_res, qdrant_ok, qdrant_res

    sqlite_ok, sqlite_res, qdrant_ok, qdrant_res = await asyncio.to_thread(_run)
    return {
        "sqlite": {"ok": sqlite_ok, "result": sqlite_res},
        "qdrant": {"ok": qdrant_ok, "result": qdrant_res},
    }


@router.post("/backup/delete")
async def delete_backup(req: BackupDeleteRequest, _admin=Depends(require_admin)):
    """
    Deletes a specific SQLite backup file or Qdrant snapshot.
    """
    from pathlib import Path
    if req.type == "sqlite":
        backup_dir = Path("storage/backups")
        target_path = (backup_dir / req.name).resolve()
        # Security check: must be inside backup_dir
        if not str(target_path).startswith(str(backup_dir.resolve())):
            raise HTTPException(status_code=400, detail="Invalid backup file path")
        if target_path.exists():
            target_path.unlink()
            return {"status": "ok", "message": f"SQLite backup {req.name} deleted"}
        raise HTTPException(status_code=404, detail="SQLite backup not found")
    elif req.type == "qdrant":
        from backend.rag_config import rag_collection_name
        from qdrant_client import QdrantClient
        collection_name = rag_collection_name()
        qdrant_url = os.getenv("QDRANT_URL", "http://127.0.0.1:6333")
        client = QdrantClient(url=qdrant_url, timeout=10.0)
        try:
            client.delete_snapshot(collection_name, req.name)
            return {"status": "ok", "message": f"Qdrant snapshot {req.name} deleted"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete Qdrant snapshot: {e}")
    else:
        raise HTTPException(status_code=400, detail="Invalid backup type")
