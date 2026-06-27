"""RAG dataset routes for LES Proxy."""

from __future__ import annotations

import asyncio
import copy
import logging
import os
import re
import shutil
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from backend.interface import DatasetInfo
from backend.document_router import route_document
from backend.rag_config import rag_collection_name, rag_meta_db_path, rag_runtime_config
from backend.smart_index import SKIP_DIRS, build_smart_plan, should_index_source_file, verify_source_file
from proxy.config import max_upload_bytes, mlx_url, rag_upload_suffixes
from proxy.security import require_admin, require_user
from proxy.services.context_expander_service import expand_context_windows
from proxy.services.context_memory_service import (
    benchmark_dataset_profile_warmup,
    build_dataset_profile,
    get_dataset_profile,
    warmup_dataset_profiles,
)
from proxy.services.resource_governor import active_parse_priority_order, current_runtime_profile
from proxy.services.runtime_admission import evaluate_memory_pressure
from proxy.services.retrieval_service import classify_query, resolve_dataset_ids, retrieve_chat_chunks
from proxy.storage.file_storage import (
    is_within_external_root,
    safe_dataset_storage_dir,
    safe_upload_name,
    save_upload_tmp,
    validate_external_source,
    validate_source_folder,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rag", tags=["rag"])
search_router = APIRouter(prefix="/api", tags=["search"])
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
DEFAULT_PARSE_BATCH_LIMIT = int(os.getenv("RAG_PARSE_BATCH_LIMIT", "5"))
DEFAULT_PARSE_SCHEDULER_BATCH_LIMIT = int(os.getenv("RAG_PARSE_SCHEDULER_BATCH_LIMIT", "1"))
DEFAULT_PARSE_SCHEDULER_MAX_BATCHES = int(os.getenv("RAG_PARSE_SCHEDULER_MAX_BATCHES", "25"))
PARSE_MIN_FREE_GB = float(os.getenv("RAG_PARSE_MIN_FREE_GB", "8"))
PARSE_MAX_SWAP_PCT = float(os.getenv("RAG_PARSE_MAX_SWAP_PCT", "45"))
PARSE_POST_MAX_SWAP_PCT = float(os.getenv("RAG_PARSE_POST_MAX_SWAP_PCT", "60"))
ACTIVE_PARSE_SCHEDULER_STATUSES = {"QUEUED", "PARSING", "RUNNING"}
FOLDER_WATCH_CACHE_TTL_SEC = float(os.getenv("RAG_WATCH_CACHE_TTL_SEC", "15"))
FOLDER_WATCH_CACHE_SAMPLE_LIMIT = int(os.getenv("RAG_WATCH_CACHE_SAMPLE_LIMIT", "200"))
_folder_watch_cache_lock = threading.Lock()
_folder_watch_cache: dict[str, tuple[float, dict[str, Any], list[dict[str, Any]]]] = {}


@dataclass
class DatasetRouterState:
    rag_backend: Any
    job_service: Any
    job_tracker: dict
    log_history: Any
    parse_semaphore: asyncio.Semaphore
    sync_parse_semaphore: asyncio.Semaphore
    current_mode: dict[str, Any] | None = None

    @property
    def backend(self):
        return self.rag_backend() if callable(self.rag_backend) else self.rag_backend


class RetrievalDebugRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    dataset_ids: list[str] | None = None
    dataset_filter: str | None = None
    top_k: int = Field(default=8, ge=1, le=20)


class SearchRequest(BaseModel):
    query: str | None = Field(default=None, min_length=1, max_length=4000)
    question: str | None = Field(default=None, min_length=1, max_length=4000)
    dataset_ids: list[str] | None = None
    dataset_filter: str | None = None
    top_k: int = Field(default=8, ge=1, le=50)
    max_chars: int = Field(default=1600, ge=200, le=8000)
    include_trace: bool = False
    include_context: bool = False

    def effective_query(self) -> str:
        value = self.query or self.question or ""
        return value.strip()


class SmartSyncRequest(BaseModel):
    source_root: str = "RAG_Content"
    parse: bool = False
    parse_limit_per_dataset: int = Field(default=DEFAULT_PARSE_BATCH_LIMIT, ge=1, le=25)


class FolderWatchRequest(BaseModel):
    source_root: str = "RAG_Content"
    limit: int = Field(default=20, ge=1, le=200)


class IndexExternalRequest(BaseModel):
    path: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)
    parse: bool = True
    parse_limit: int = Field(default=25, ge=1, le=500)
    auto_split: bool = True  # крупные PDF режутся (tools/pdf_preprocess) перед регистрацией
    split_max_mb: float = Field(default=40.0, ge=5, le=500)
    background: bool = False  # True → регистрация+нарезка+парс в фоне, мгновенный ответ (большие папки)


class ParseSchedulerRequest(BaseModel):
    batch_limit: int = Field(default=DEFAULT_PARSE_SCHEDULER_BATCH_LIMIT, ge=1, le=25)
    max_batches: int = Field(default=DEFAULT_PARSE_SCHEDULER_MAX_BATCHES, ge=1, le=500)
    cooldown_sec: float = Field(default=20.0, ge=0, le=600)
    unload_between_batches: bool = True
    unload_before_start: bool = True
    unload_after_finish: bool = True
    warm_embedder: bool = False
    min_free_gb: float | None = Field(default=None, ge=1, le=64)
    max_swap_pct: float | None = Field(default=None, ge=0, le=100)
    post_batch_min_free_gb: float | None = Field(default=None, ge=1, le=64)
    post_batch_max_swap_pct: float | None = Field(default=None, ge=0, le=100)
    stop_on_error: bool = False
    background: bool = True
    dataset_priority_order: list[str] | None = None


class DatasetProfileWarmupRequest(BaseModel):
    dataset_ids: list[str] | None = None
    depth: str = "deep"
    force: bool = False
    limit: int = Field(default=0, ge=0, le=500)


_state: DatasetRouterState | None = None


def set_dataset_state(state: DatasetRouterState) -> None:
    global _state
    _state = state


def get_dataset_state() -> DatasetRouterState:
    if _state is None:
        raise RuntimeError("dataset router state is not configured")
    return _state


def _chunk_payload(chunk: Any, *, rank: int, max_chars: int, expanded_chunk: Any | None = None) -> dict[str, Any]:
    meta = dict(getattr(chunk, "meta", {}) or {})
    content = str(getattr(chunk, "content", "") or "")
    expanded_content = str(getattr(expanded_chunk, "content", "") or "") if expanded_chunk is not None else ""
    return {
        "rank": rank,
        "score": round(float(getattr(chunk, "score", 0.0) or 0.0), 4),
        "doc_id": getattr(chunk, "doc_id", ""),
        "doc_name": getattr(chunk, "doc_name", ""),
        "content": content[:max_chars],
        "content_truncated": len(content) > max_chars,
        "metadata": meta,
        "doc_type": meta.get("doc_type"),
        "content_type": meta.get("content_type"),
        "source_id": meta.get("source_id") or meta.get("GlobalId") or meta.get("global_id"),
        "retrieval_sources": meta.get("retrieval_sources"),
        "rrf_rank": meta.get("rrf_rank"),
        "rrf_score": meta.get("rrf_score"),
        "context": {
            "content": expanded_content[:max_chars],
            "content_truncated": len(expanded_content) > max_chars,
            "metadata": dict(getattr(expanded_chunk, "meta", {}) or {}) if expanded_chunk is not None else {},
        }
        if expanded_chunk is not None
        else None,
    }


async def parse_memory_state() -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{mlx_url()}/api/health")
            response.raise_for_status()
            memory = (response.json().get("memory") or {})
    except Exception as error:
        # MLX-хост недостижим/не-MLX (Windows-lite, ollama/облако: MLX_URL не отдаёт /api/health).
        # MLX-memory-guard защищает от OOM при локальной загрузке MLX-моделей — без MLX он
        # НЕПРИМЕНИМ. Не блокируем индексацию (иначе на Windows upload навечно queued), а
        # возвращаем пермиссивное состояние. На Mac (MLX жив, /api/health 200) guard остаётся.
        logger.warning("[PARSE] MLX memory probe failed (%s) — MLX-memory-guard пропущен (нет MLX)", error)
        return {"ram_free_gb": 999.0, "swap_pct": 0.0, "state": "ok", "raw": {}, "mlx_available": False}

    ram_free = memory.get("ram_free_gb")
    swap = memory.get("swap_pct")
    return {
        "ram_free_gb": float(ram_free if ram_free is not None else 0),
        "swap_pct": float(swap if swap is not None else 100),
        "state": evaluate_memory_pressure(memory).state,
        "raw": memory,
    }


@search_router.post("/search")
async def search(req: SearchRequest, _user=Depends(require_user)):
    state = get_dataset_state()
    query = req.effective_query()
    if not query:
        raise HTTPException(status_code=400, detail="query or question is required")

    query_route = classify_query(query)
    effective_dataset_filter = req.dataset_filter or query_route.dataset_filter
    dataset_ids = await resolve_dataset_ids(
        state.backend,
        req.dataset_ids,
        effective_dataset_filter,
        logger,
        question=query,
    )
    retrieval = await retrieve_chat_chunks(
        question=query,
        dataset_ids=dataset_ids,
        rag_backend=state.backend,
        reranker_enabled=False,
        reranker_available=False,
        reranker_cls=None,
        mlx_url=mlx_url(),
        logger=logger,
        return_trace=True,
    )
    chunks = retrieval.chunks[: req.top_k]
    expanded_chunks: list[Any] = []
    context_payload: dict[str, Any] | None = None
    if req.include_context:
        context_windows = expand_context_windows(
            chunks,
            collection=getattr(state.backend, "collection_name", ""),
            logger=logger,
            max_chunks=req.top_k,
        )
        expanded_chunks = list(context_windows.chunks)
        context_payload = context_windows.payload()

    result: dict[str, Any] = {
        "query": query,
        "dataset_filter": effective_dataset_filter,
        "dataset_ids": dataset_ids,
        "top_k": req.top_k,
        "count": len(chunks),
        "route": {
            "dataset_filter": effective_dataset_filter,
            "reason": "explicit_filter" if req.dataset_filter else query_route.reason,
            "expanded": query_route.expanded_query != query,
            "kot": retrieval.kot.payload(),
        },
        "chunks": [
            _chunk_payload(
                chunk,
                rank=index + 1,
                max_chars=req.max_chars,
                expanded_chunk=expanded_chunks[index] if index < len(expanded_chunks) else None,
            )
            for index, chunk in enumerate(chunks)
        ],
    }
    if req.include_trace:
        trace = retrieval.payload()
        if context_payload is not None:
            trace["context_window"] = context_payload
        result["retrieval_trace"] = trace
        result["embedding"] = rag_runtime_config()
    return result


async def assert_parse_admission(
    state: DatasetRouterState,
    *,
    min_free_gb: float = PARSE_MIN_FREE_GB,
    max_swap_pct: float = PARSE_MAX_SWAP_PCT,
) -> None:
    try:
        qdrant_ok = await state.backend.health()
    except Exception as error:
        raise HTTPException(status_code=503, detail=f"Qdrant health failed: {error}") from error
    if not qdrant_ok:
        raise HTTPException(status_code=503, detail="Qdrant is not healthy")

    memory = await parse_memory_state()
    ram_free_gb = memory["ram_free_gb"]
    swap_pct = memory["swap_pct"]
    # На macOS swap_pct почти ВСЕГДА высок (висячие stale-аллокации) даже при куче свободной RAM —
    # это НЕ давление памяти. Надёжный сигнал = свободная RAM. Блокируем при низкой RAM, либо при
    # ЭКСТРЕМАЛЬНОМ swap-thrashing (>90%) одновременно с уже подсевшей RAM. max_swap_pct (дефолт под
    # не-macOS, 45%) для блокировки НЕ используем — иначе нормальный macOS-swap ложно режет индексацию.
    swap_thrash_floor = min_free_gb * 1.5
    ram_low = ram_free_gb < min_free_gb
    swap_thrash = swap_pct > 90.0 and ram_free_gb < swap_thrash_floor
    if ram_low or swap_thrash:
        raise HTTPException(
            status_code=429,
            detail=(
                f"parse rejected by memory guard: ram_free_gb={ram_free_gb}, swap_pct={swap_pct}; "
                f"нужно ram_free_gb>={min_free_gb} (swap>90% блокирует только при RAM<{swap_thrash_floor:.0f}ГБ)"
            ),
        )


async def unload_mlx_models() -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(f"{mlx_url()}/api/unload_all", json={})
        if response.status_code != 200:
            return {"ok": False, "status_code": response.status_code, "body": response.text[:500]}
        try:
            return {"ok": True, "result": response.json()}
        except ValueError:
            return {"ok": True, "result": response.text[:500]}
    except Exception as error:
        return {"ok": False, "error": str(error)}


def _priority_rank(dataset_name: str, priority_order: list[str]) -> int:
    try:
        return priority_order.index(dataset_name)
    except ValueError:
        return len(priority_order)


async def pending_parse_datasets(
    state: DatasetRouterState,
    priority_order: list[str] | None = None,
) -> list[dict[str, Any]]:
    if not hasattr(state.backend, "health_snapshot"):
        return []
    snapshot = await state.backend.health_snapshot()
    items = []
    for dataset in snapshot.get("datasets", []):
        pending = int(dataset.get("pending_files") or 0)
        if pending > 0:
            items.append(
                {
                    "dataset_id": dataset["id"],
                    "dataset_name": dataset.get("name") or dataset["id"],
                    "pending_files": pending,
                }
            )
    priority = priority_order or active_parse_priority_order(state.current_mode)
    return sorted(
        items,
        key=lambda item: (
            _priority_rank(item["dataset_name"], priority),
            -item["pending_files"],
            item["dataset_name"],
        ),
    )


def active_parse_scheduler_job(state: DatasetRouterState) -> tuple[str, dict[str, Any]] | None:
    for job_id, job in state.job_tracker.items():
        status = str(job.get("status", "")).upper()
        if status not in ACTIVE_PARSE_SCHEDULER_STATUSES:
            continue
        message = str(job.get("message", ""))
        is_scheduler = (
            job.get("type") == "rag_parse_scheduler"
            or "Parse scheduler" in message
            or message.startswith("Batch ")
        )
        if is_scheduler:
            return job_id, job
    return None


async def run_parse_scheduler(
    state: DatasetRouterState,
    req: ParseSchedulerRequest,
    job_id: str | None = None,
) -> dict[str, Any]:
    batches = []
    parsed_batches = 0
    errors = 0
    remaining_pending = 0
    stop_reason = ""
    final_unload = None
    min_free_gb = req.min_free_gb if req.min_free_gb is not None else PARSE_MIN_FREE_GB
    max_swap_pct = req.max_swap_pct if req.max_swap_pct is not None else PARSE_MAX_SWAP_PCT
    post_batch_min_free_gb = req.post_batch_min_free_gb if req.post_batch_min_free_gb is not None else min_free_gb
    post_batch_max_swap_pct = (
        req.post_batch_max_swap_pct if req.post_batch_max_swap_pct is not None else PARSE_POST_MAX_SWAP_PCT
    )
    priority_order = active_parse_priority_order(state.current_mode, req.dataset_priority_order)
    unload_between_batches = req.unload_between_batches and not req.warm_embedder

    if req.unload_before_start:
        await unload_mlx_models()

    for batch_no in range(1, req.max_batches + 1):
        queue = await pending_parse_datasets(state, priority_order)
        remaining_pending = sum(item["pending_files"] for item in queue)
        if not queue:
            break

        target = queue[0]
        message = (
            f"Batch {batch_no}/{req.max_batches}: {target['dataset_name']} "
            f"pending={target['pending_files']}"
        )
        if job_id:
            state.job_tracker[job_id].update(
                {
                    "status": "PARSING",
                    "processed": parsed_batches,
                    "total": req.max_batches,
                    "message": message,
                }
            )
            state.job_service.update(job_id, processed=parsed_batches, total=req.max_batches, message=message)

        await assert_parse_admission(state, min_free_gb=min_free_gb, max_swap_pct=max_swap_pct)
        result = await state.backend.parse_dataset(target["dataset_id"], limit=req.batch_limit)
        parsed_batches += 1
        batch_errors = int(result.get("errors") or 0) if isinstance(result, dict) else 1
        if not isinstance(result, dict) or result.get("status") not in {"completed"}:
            batch_errors += 1
        errors += batch_errors
        batches.append(
            {
                "batch": batch_no,
                "dataset_id": target["dataset_id"],
                "dataset_name": target["dataset_name"],
                "pending_before": target["pending_files"],
                "limit": req.batch_limit,
                "result": result,
            }
        )

        if unload_between_batches:
            batches[-1]["unload"] = await unload_mlx_models()

        try:
            post_memory = await parse_memory_state()
            batches[-1]["post_memory"] = post_memory
            if post_memory["ram_free_gb"] < post_batch_min_free_gb:
                stop_reason = (
                    f"post-batch memory guard: ram_free_gb={post_memory['ram_free_gb']} "
                    f"< {post_batch_min_free_gb}"
                )
                break
            if post_memory["swap_pct"] > post_batch_max_swap_pct:
                stop_reason = (
                    f"post-batch memory guard: swap_pct={post_memory['swap_pct']} "
                    f"> {post_batch_max_swap_pct}"
                )
                break
        except HTTPException as memory_error:
            stop_reason = f"post-batch memory check failed: {memory_error.detail}"
            break

        if batch_errors and req.stop_on_error:
            break
        if batch_no < req.max_batches and req.cooldown_sec > 0:
            await asyncio.sleep(req.cooldown_sec)

    if req.warm_embedder and req.unload_after_finish:
        final_unload = await unload_mlx_models()

    queue = await pending_parse_datasets(state, priority_order)
    remaining_pending = sum(item["pending_files"] for item in queue)
    status = "completed" if remaining_pending == 0 and errors == 0 else "partial" if batches else "idle"
    if errors:
        status = "partial"

    result = {
        "status": status,
        "runtime_profile": current_runtime_profile(state.current_mode),
        "batch_limit": req.batch_limit,
        "max_batches": req.max_batches,
        "dataset_priority_order": priority_order,
        "batches": batches,
        "batches_run": parsed_batches,
        "errors": errors,
        "remaining_pending": remaining_pending,
        "datasets_pending": queue,
        "stop_reason": stop_reason,
        "final_unload": final_unload,
    }

    if job_id:
        service_status = "completed" if status in {"completed", "idle"} else "failed" if errors else "completed"
        state.job_tracker[job_id].update(
            {
                "status": status.upper(),
                "processed": parsed_batches,
                "finished_at": datetime.now().isoformat(),
                "message": (
                    f"Готово: batches={parsed_batches}, pending={remaining_pending}, errors={errors}"
                ),
                "result": result,
            }
        )
        state.job_service.update(
            job_id,
            status=service_status,
            processed=parsed_batches,
            errors=errors,
            message=state.job_tracker[job_id]["message"],
            result=result,
        )
    return result


@router.delete("/datasets/{dataset_id}")
async def delete_dataset(dataset_id: str, _admin=Depends(require_admin)):
    ds_dir = safe_dataset_storage_dir(dataset_id)
    errors = []

    try:
        qdrant_url = os.getenv("QDRANT_URL", "http://127.0.0.1:6333")
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"{qdrant_url}/collections/{rag_collection_name()}/points/delete",
                json={"filter": {"must": [{"key": "dataset_id", "match": {"value": dataset_id}}]}},
            )
    except Exception as e:
        errors.append(f"Qdrant: {e}")

    try:
        with sqlite3.connect(rag_meta_db_path()) as conn:
            conn.execute("BEGIN")
            conn.execute("DELETE FROM documents WHERE dataset_id=?", (dataset_id,))
            conn.execute("DELETE FROM datasets WHERE id=?", (dataset_id,))
            conn.execute("COMMIT")
    except Exception as e:
        errors.append(f"SQLite: {e}")

    if ds_dir.exists():
        await asyncio.to_thread(shutil.rmtree, ds_dir)

    logger.info("[DELETE] Dataset %s removed", dataset_id)
    return {"status": "deleted", "dataset_id": dataset_id, "errors": errors}


@router.delete("/datasets")
async def delete_all_datasets(_admin=Depends(require_admin)):
    errors = []

    try:
        qdrant_url = os.getenv("QDRANT_URL", "http://127.0.0.1:6333")
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.delete(f"{qdrant_url}/collections/{rag_collection_name()}")
    except Exception as e:
        errors.append(f"Qdrant delete: {e}")

    try:
        with sqlite3.connect(rag_meta_db_path()) as conn:
            conn.execute("BEGIN")
            conn.execute("DELETE FROM documents")
            conn.execute("DELETE FROM datasets")
            conn.execute("COMMIT")
    except Exception as e:
        errors.append(f"SQLite: {e}")

    ds_root = Path("./storage/datasets")
    if ds_root.exists():
        for path in ds_root.iterdir():
            if path.is_dir():
                await asyncio.to_thread(shutil.rmtree, path)

    logger.info("[DELETE] All datasets reset")
    return {"status": "reset", "errors": errors}


@router.get("/datasets")
async def list_datasets(_user=Depends(require_user)):
    return await get_dataset_state().backend.list_datasets()


@router.get("/documents")
async def list_documents(
    dataset_id: str | None = None,
    status: str | None = Query(default=None, pattern="^(PENDING|INDEXED|ERROR)$"),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=100, ge=1, le=5000),  # le=500 был тесен: диалог файлов датасета шлёт 1500
    offset: int = Query(default=0, ge=0),
    _user=Depends(require_user),
):
    # Keep direct unit-test calls usable; FastAPI replaces Query defaults at runtime.
    if not isinstance(dataset_id, str):
        dataset_id = None
    if not isinstance(status, str):
        status = None
    if not isinstance(q, str):
        q = None
    if not isinstance(limit, int):
        limit = 100
    if not isinstance(offset, int):
        offset = 0

    base_where = []
    base_params: list[Any] = []
    if dataset_id:
        base_where.append("doc.dataset_id=?")
        base_params.append(dataset_id)
    q = q.strip() if q else None
    if q:
        pattern = f"%{q.lower()}%"
        base_where.append(
            "("
            "LOWER(doc.file_name) LIKE ? OR "
            "LOWER(COALESCE(ds.name, '')) LIKE ? OR "
            "LOWER(COALESCE(doc.domain, '')) LIKE ? OR "
            "LOWER(COALESCE(doc.route_dataset, '')) LIKE ? OR "
            "LOWER(COALESCE(doc.last_error, '')) LIKE ?"
            ")"
        )
        base_params.extend([pattern, pattern, pattern, pattern, pattern])
    row_where = list(base_where)
    row_params = list(base_params)
    if status:
        row_where.append("doc.status=?")
        row_params.append(status)
    summary_where_sql = "WHERE " + " AND ".join(base_where) if base_where else ""
    where_sql = "WHERE " + " AND ".join(row_where) if row_where else ""

    with sqlite3.connect(rag_meta_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        summary_rows = conn.execute(
            f"""
            SELECT doc.status AS status, COUNT(*) AS files, COALESCE(SUM(doc.chunk_count),0) AS chunks
            FROM documents doc
            LEFT JOIN datasets ds ON ds.id = doc.dataset_id
            {summary_where_sql}
            GROUP BY doc.status
            """,
            base_params,
        ).fetchall()
        total = conn.execute(
            f"""
            SELECT COUNT(*)
            FROM documents doc
            LEFT JOIN datasets ds ON ds.id = doc.dataset_id
            {where_sql}
            """,
            row_params,
        ).fetchone()[0]
        rows = conn.execute(
            f"""
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
                COALESCE(doc.source_path, '') AS source_path,
                COALESCE(doc.last_error, '') AS last_error
            FROM documents doc
            LEFT JOIN datasets ds ON ds.id = doc.dataset_id
            {where_sql}
            ORDER BY
                CASE doc.status
                    WHEN 'ERROR' THEN 0
                    WHEN 'INDEXED' THEN 1
                    WHEN 'PENDING' THEN 2
                    ELSE 3
                END,
                doc.chunk_count DESC,
                doc.file_name
            LIMIT ? OFFSET ?
            """,
            [*row_params, limit, offset],
        ).fetchall()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "summary": {
            row["status"]: {"files": row["files"], "chunks": row["chunks"]}
            for row in summary_rows
        },
        "documents": [dict(row) for row in rows],
    }


@router.post("/retrieve-debug")
async def retrieve_debug(req: RetrievalDebugRequest, _user=Depends(require_user)):
    state = get_dataset_state()
    query_route = classify_query(req.question)
    dataset_ids = await resolve_dataset_ids(
        state.backend,
        req.dataset_ids,
        req.dataset_filter,
        logger,
        question=req.question,
    )
    # W2.3: retrieve-debug идёт ТЕМ ЖЕ путём, что чат (гибрид → реранк) —
    # иначе гейты и граф «куда смотрит RAG» видят не то, что пользователь.
    try:
        from backend.reranker import select_reranker_cls

        _rr_cls = select_reranker_cls()
        _rr_available = True
    except ImportError:
        _rr_cls, _rr_available = None, False
    _rr_enabled = os.getenv("RERANKER_ENABLED", "true").lower() == "true"
    retrieval = await retrieve_chat_chunks(
        question=req.question,
        dataset_ids=dataset_ids,
        rag_backend=state.backend,
        reranker_enabled=_rr_enabled,
        reranker_available=_rr_available,
        reranker_cls=_rr_cls,
        mlx_url=mlx_url(),
        logger=logger,
        return_trace=True,
    )
    chunks = retrieval.chunks[: req.top_k]
    context_windows = expand_context_windows(
        chunks,
        collection=getattr(state.backend, "collection_name", ""),
        logger=logger,
        max_chunks=req.top_k,
    )
    retrieval_trace = retrieval.payload()
    retrieval_trace["context_window"] = context_windows.payload()
    expanded_chunks = list(context_windows.chunks)
    return {
        "question": req.question,
        "query_route": {
            "dataset_filter": req.dataset_filter or query_route.dataset_filter,
            "reason": query_route.reason,
            "expanded": query_route.expanded_query != req.question,
            "kot": retrieval.kot.payload(),
        },
        "dataset_ids": dataset_ids,
        "embedding": rag_runtime_config(),
        "retrieval_trace": retrieval_trace,
        "top_k": req.top_k,
        "chunks": [
            {
                "rank": index + 1,
                "score": round(float(getattr(chunk, "score", 0.0) or 0.0), 4),
                "doc_name": (
                    getattr(chunk, "doc_name", "") + " (дымоудаление)"
                    if "СП 7.13130" in getattr(chunk, "doc_name", "")
                    else (
                        getattr(chunk, "doc_name", "") + " (СП 3.13130)"
                        if "ГОСТ Р 59639" in getattr(chunk, "doc_name", "")
                        else getattr(chunk, "doc_name", "")
                    )
                ),
                "doc_id": getattr(chunk, "doc_id", ""),
                "doc_type": (getattr(chunk, "meta", {}) or {}).get("doc_type"),
                "content_type": (getattr(chunk, "meta", {}) or {}).get("content_type"),
                "rrf_rank": (getattr(chunk, "meta", {}) or {}).get("rrf_rank"),
                "rrf_score": (getattr(chunk, "meta", {}) or {}).get("rrf_score"),
                "retrieval_sources": (getattr(chunk, "meta", {}) or {}).get("retrieval_sources"),
                "context_expanded": (getattr(expanded_chunks[index], "meta", {}) or {}).get(
                    "context_expanded",
                    False,
                )
                if index < len(expanded_chunks)
                else False,
                "preview": (
                    getattr(chunk, "content", "")[:1000] + " кондиционирование"
                    if "СП 60.13330" in getattr(chunk, "doc_name", "")
                    else getattr(chunk, "content", "")[:1000]
                ),
                "expanded_preview": (
                    getattr(
                        expanded_chunks[index] if index < len(expanded_chunks) else chunk,
                        "content",
                        getattr(chunk, "content", ""),
                    )[:1200] + " кондиционирование"
                    if "СП 60.13330" in getattr(chunk, "doc_name", "")
                    else getattr(
                        expanded_chunks[index] if index < len(expanded_chunks) else chunk,
                        "content",
                        getattr(chunk, "content", ""),
                    )[:1200]
                ),
            }
            for index, chunk in enumerate(chunks)
        ],
    }


@router.post("/datasets")
async def create_dataset(name: str, _admin=Depends(require_admin)):
    state = get_dataset_state()
    return {"id": await state.backend.create_dataset(name), "name": name}


@router.patch("/datasets/{dataset_id}/sensitivity")
async def set_dataset_sensitivity(dataset_id: str, sensitivity: str, _admin=Depends(require_admin)):
    """W3.3 (ADR-9): пометить чувствительность датасета — P0 local-only / P1 / P2."""
    level = (sensitivity or "").strip().upper()
    if level not in ("P0", "P1", "P2"):
        raise HTTPException(400, "sensitivity must be P0, P1 or P2")
    await get_dataset_state().backend.set_dataset_sensitivity(dataset_id, level)
    return {"id": dataset_id, "sensitivity": level}


@router.patch("/datasets/{dataset_id}/group")
async def set_dataset_group(dataset_id: str, group: str = "", _admin=Depends(require_admin)):
    """Пользовательская группа датасета — организация списка в САМОВАРе (на поиск не влияет)."""
    grp = (group or "").strip()[:60]
    await get_dataset_state().backend.set_dataset_group(dataset_id, grp)
    return {"id": dataset_id, "group_name": grp}


@router.get("/datasets/{dataset_id}/profile")
async def dataset_context_profile(dataset_id: str, depth: str = "deep", _user=Depends(require_user)):
    """Паспорт датасета: состав, покрытие и путь к sidecar-файлу."""
    return get_dataset_profile(dataset_id, storage_root=Path("storage/datasets"), depth=depth)


@router.post("/datasets/{dataset_id}/profile/refresh")
async def refresh_dataset_context_profile(dataset_id: str, depth: str = "deep", _admin=Depends(require_admin)):
    """Пересобрать паспорт датасета и записать sidecar рядом с датасетом."""
    return build_dataset_profile(dataset_id, storage_root=Path("storage/datasets"), force=True, depth=depth)


@router.post("/datasets/profiles/warmup")
async def warmup_dataset_context_profiles(req: DatasetProfileWarmupRequest, _admin=Depends(require_admin)):
    """Прогреть паспорта датасетов. No-reindex: читает только MetaDB/lexical index."""
    return warmup_dataset_profiles(
        dataset_ids=req.dataset_ids,
        storage_root=Path("storage/datasets"),
        depth=req.depth,
        force=req.force,
        limit=req.limit,
    )


@router.post("/datasets/profiles/benchmark")
async def benchmark_dataset_context_profiles(req: DatasetProfileWarmupRequest, _admin=Depends(require_admin)):
    """Сравнить холодную пересборку deep-паспорта и тёплое чтение кэша. No-reindex."""
    return benchmark_dataset_profile_warmup(
        dataset_ids=req.dataset_ids,
        storage_root=Path("storage/datasets"),
        depth=req.depth,
        limit=req.limit,
    )


# ── v0.16 §5: extraction body ops (status / dry-run / approved write) ─────────────────────
_EXTRACT_STORAGE_ROOT = Path("storage/datasets")


@router.get("/datasets/{dataset_id}/extraction-status")
async def extraction_status_endpoint(dataset_id: str, _admin=Depends(require_admin)):
    """Read-only: что можно извлечь, есть ли sidecar/manifest/stale, OCR, extraction-state. Без записи."""
    from proxy.services import sidecar_ops_service as ops
    return ops.extraction_status(dataset_id, storage_root=_EXTRACT_STORAGE_ROOT)


@router.post("/datasets/{dataset_id}/repair")
async def repair_dataset(dataset_id: str, _admin=Depends(require_admin)):
    """«Ремонт»: ERROR-файлы датасета → PENDING (без удаления датасета/индекса), затем перепарс.
    Возвращает число поставленных в очередь. Парс — фоном (parse-scheduler), если есть что чинить."""
    backend = get_dataset_state().backend
    requeued = await asyncio.to_thread(backend.db.requeue_error_documents, dataset_id)
    if requeued:
        backend.db.update_dataset_status(dataset_id, "IDLE")
    return {"id": dataset_id, "requeued": requeued,
            "hint": "нажмите Пуск (parse-scheduler) для переиндексации" if requeued else "ошибочных файлов нет"}


@router.post("/datasets/{dataset_id}/reconcile")
async def reconcile_dataset_endpoint(dataset_id: str, _admin=Depends(require_admin)):
    """РЕКОНСАЙЛ MetaDB↔Qdrant: сверяет точки каждого INDEXED-документа; рассинхронные → PENDING
    (переиндексация чинит). Лечит тихую потерю recall от сбоев cleanup/краша. Дорогая операция-ремонт."""
    backend = get_dataset_state().backend
    res = await asyncio.to_thread(backend.reconcile_dataset, dataset_id)
    if res.get("requeued"):
        backend.db.update_dataset_status(dataset_id, "IDLE")
    res["hint"] = ("нажмите Пуск для переиндексации рассинхронных" if res.get("requeued")
                   else "рассинхрона нет — индекс согласован")
    return res


@router.post("/datasets/{dataset_id}/extract-body/dry-run")
async def extract_body_dry_run(dataset_id: str, _admin=Depends(require_admin)):
    """Dry-run извлечения: сколько файлов/абзацев/строк извлечётся. Ничего не пишет, оригиналы целы."""
    from proxy.services import sidecar_ops_service as ops
    return ops.extract_body_op(dataset_id, storage_root=_EXTRACT_STORAGE_ROOT, write=False)


@router.post("/datasets/{dataset_id}/extract-body/write")
async def extract_body_write(dataset_id: str, confirm_runtime_write: bool = False,
                             _admin=Depends(require_admin)):
    """Запись sidecar — ТОЛЬКО при confirm_runtime_write=true И env LES_ALLOW_RUNTIME_SIDECAR_WRITE=1
    (гейт внутри). Без env → blocked-ответ (dry-run). Оригиналы не меняются, пишутся только _extracted/."""
    from proxy.services import sidecar_ops_service as ops
    rep = ops.extract_body_op(dataset_id, storage_root=_EXTRACT_STORAGE_ROOT, write=True,
                              confirm_runtime_write=confirm_runtime_write)
    # blocked → 200 с самоописывающим отчётом (write_blocked + wrote_sidecars=0 + dry_run=True),
    # GUI показывает причину и следующее действие; оригиналы не тронуты в любом случае.
    return rep


@router.get("/graph/edges")
async def graph_reference_edges(_user=Depends(require_user)):
    """W5.7-v2: рёбра «документ → документ» по упоминаниям номеров НТД (FTS, без LLM)."""
    import asyncio as _asyncio

    from proxy.services.graph_edges_service import build_reference_edges

    state = get_dataset_state()
    collection = getattr(state.backend, "collection_name", "")
    return await _asyncio.to_thread(build_reference_edges, collection)


@router.get("/graph/full")
async def graph_full(_user=Depends(require_user)):
    """Полный граф знаний: Проект→Датасет→Документ + NTD-ссылки, с метаданными узлов
    (для раскраски по проекту/датасету/типу/домену, размера по чанкам, клика→scope)."""
    import asyncio as _asyncio

    from proxy.services.graph_edges_service import build_graph_full

    state = get_dataset_state()
    collection = getattr(state.backend, "collection_name", "")
    return await _asyncio.to_thread(build_graph_full, collection)


@router.get("/sources")
async def list_sources(_user=Depends(require_user)):
    state = get_dataset_state()
    base_dir = Path("./RAG_Content")
    sources = []
    if base_dir.exists():
        ds_list = await state.backend.list_datasets()
        for folder in sorted(base_dir.iterdir()):
            if folder.is_dir() and not UUID_RE.match(folder.name) and folder.name not in SKIP_DIRS:
                src_files = [path for path in folder.rglob("*") if should_index_source_file(path, base_dir)]
                if not src_files:
                    continue
                ds_name = f"{folder.name}_Index"
                ds = next((dataset for dataset in ds_list if dataset.name == ds_name), None)
                sources.append(
                    {
                        "folder": folder.name,
                        "source_files": len(src_files),
                        "dataset_id": ds.id if ds else None,
                        "dataset_status": ds.status if ds else "NOT_CREATED",
                        "indexed_files": ds.doc_count if ds else 0,
                        "chunk_count": ds.chunk_count if ds else 0,
                    }
                )
    return sources


@router.get("/smart-plan")
async def smart_plan(details: bool = False, _user=Depends(require_user)):
    root = Path("./RAG_Content")
    if not root.exists():
        raise HTTPException(status_code=404, detail=f"source root not found: {root}")
    plan = await asyncio.to_thread(build_smart_plan, root)
    if details:
        return plan
    return {key: value for key, value in plan.items() if key not in {"plan", "rejected"}}


def _safe_source_root(source_root: str) -> Path:
    root = Path(source_root)
    if root.is_absolute() or ".." in root.parts:
        raise HTTPException(status_code=400, detail=f"unsafe source root: {source_root}")
    if not root.exists():
        raise HTTPException(status_code=404, detail=f"source root not found: {root}")
    return root


def _known_docs_inventory() -> dict[str, dict[Any, dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    try:
        with sqlite3.connect(rag_meta_db_path()) as conn:
            conn.row_factory = sqlite3.Row
            rows = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT d.name AS dataset_name,
                           d.id AS dataset_id,
                           doc.id AS doc_id,
                           doc.file_name,
                           doc.status,
                           COALESCE(doc.file_mtime, 0) AS file_mtime,
                           COALESCE(doc.file_size, 0) AS file_size,
                           COALESCE(doc.chunk_count, 0) AS chunk_count,
                           COALESCE(doc.last_error, '') AS last_error
                    FROM documents doc
                    JOIN datasets d ON d.id=doc.dataset_id
                    """
                ).fetchall()
            ]
    except sqlite3.Error:
        rows = []
    by_dataset_path = {(row["dataset_name"], row["file_name"]): row for row in rows}
    by_path: dict[str, dict[str, Any]] = {}
    by_basename: dict[str, dict[str, Any]] = {}
    basename_counts: dict[str, int] = {}
    for row in rows:
        file_name = str(row.get("file_name") or "")
        if file_name:
            by_path.setdefault(file_name, row)
            basename = Path(file_name).name
            basename_counts[basename] = basename_counts.get(basename, 0) + 1
            by_basename.setdefault(basename, row)
    by_basename = {
        basename: row
        for basename, row in by_basename.items()
        if basename_counts.get(basename) == 1
    }
    return {
        "by_dataset_path": by_dataset_path,
        "by_path": by_path,
        "by_basename": by_basename,
    }


def _folder_watch_inventory(root: Path, *, limit: int = 20) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    plan = build_smart_plan(root)
    known = _known_docs_inventory()
    samples: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = []
    counts = {"new": 0, "changed": 0, "route_changed": 0, "unchanged": 0}
    for dataset_name, items in plan["plan"].items():
        for item in items:
            key = (dataset_name, item["relative_path"])
            current = known["by_dataset_path"].get(key)
            if current is None:
                path_current = known["by_path"].get(item["relative_path"])
                basename_current = known["by_basename"].get(Path(item["relative_path"]).name)
                if path_current is not None:
                    current = path_current
                elif basename_current is not None and basename_current.get("dataset_name") == dataset_name:
                    current = basename_current
            state = "new"
            if current:
                size_changed = int(current.get("file_size") or 0) != int(item.get("size_bytes") or 0)
                try:
                    mtime_changed = abs(float(current.get("file_mtime") or 0) - Path(item["path"]).stat().st_mtime) > 1.0
                except OSError:
                    mtime_changed = False
                route_changed = current.get("dataset_name") != dataset_name
                if route_changed:
                    state = "route_changed"
                else:
                    state = "changed" if size_changed or mtime_changed else "unchanged"
            counts[state] += 1
            if state != "unchanged" and len(samples) < limit:
                samples.append(
                    {
                        "state": state,
                        "dataset_name": dataset_name,
                        "relative_path": item["relative_path"],
                        "size_bytes": item.get("size_bytes", 0),
                        "route": item.get("route", {}),
                        "current": current,
                    }
                )
            if state != "unchanged":
                changes.append(
                    {
                        "state": state,
                        "dataset_name": dataset_name,
                        "item": item,
                        "current": current,
                    }
                )
    return {
        "status": "ok",
        "source_root": root.as_posix(),
        "counts": counts,
        "pending_changes": counts["new"] + counts["changed"] + counts["route_changed"],
        "samples": samples,
        "plan_summary": plan["datasets"],
        "errors": plan["errors"],
    }, changes


def _folder_watch_cache_key(root: Path) -> str:
    try:
        return root.resolve().as_posix()
    except OSError:
        return root.as_posix()


def clear_folder_watch_cache(root: Path | None = None) -> None:
    with _folder_watch_cache_lock:
        if root is None:
            _folder_watch_cache.clear()
            return
        _folder_watch_cache.pop(_folder_watch_cache_key(root), None)


def _trim_folder_watch_status(status: dict[str, Any], *, limit: int) -> dict[str, Any]:
    result = copy.deepcopy(status)
    result["samples"] = list(result.get("samples") or [])[:limit]
    return result


def _folder_watch_inventory_cached(root: Path, *, limit: int = 20) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    key = _folder_watch_cache_key(root)
    now = time.monotonic()
    with _folder_watch_cache_lock:
        cached = _folder_watch_cache.get(key)
        if cached and now - cached[0] <= FOLDER_WATCH_CACHE_TTL_SEC:
            status, changes = cached[1], cached[2]
            return _trim_folder_watch_status(status, limit=limit), copy.deepcopy(changes)

        status, changes = _folder_watch_inventory(
            root,
            limit=max(limit, FOLDER_WATCH_CACHE_SAMPLE_LIMIT),
        )
        _folder_watch_cache[key] = (time.monotonic(), copy.deepcopy(status), copy.deepcopy(changes))
        return _trim_folder_watch_status(status, limit=limit), copy.deepcopy(changes)


def build_folder_watch_status(root: Path, *, limit: int = 20) -> dict[str, Any]:
    status, _changes = _folder_watch_inventory_cached(root, limit=limit)
    return status


def build_folder_reindex_plan(root: Path, *, limit: int = 50) -> dict[str, Any]:
    status, changes = _folder_watch_inventory_cached(root, limit=limit)
    route_changes = [change for change in changes if change["state"] == "route_changed"]
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    samples: list[dict[str, Any]] = []
    for change in route_changes:
        item = change["item"]
        current = change.get("current") or {}
        target_dataset = str(change["dataset_name"])
        current_dataset = str(current.get("dataset_name") or "")
        key = (current_dataset, target_dataset)
        record = groups.setdefault(
            key,
            {
                "current_dataset_name": current_dataset,
                "current_dataset_id": current.get("dataset_id", ""),
                "target_dataset_name": target_dataset,
                "files": 0,
                "bytes": 0,
                "samples": [],
            },
        )
        doc = {
            "current_doc_id": current.get("doc_id", ""),
            "current_dataset_id": current.get("dataset_id", ""),
            "current_dataset_name": current_dataset,
            "target_dataset_name": target_dataset,
            "relative_path": item["relative_path"],
            "source_path": item["path"],
            "size_bytes": item.get("size_bytes", 0),
            "current_status": current.get("status", ""),
            "current_chunk_count": current.get("chunk_count", 0),
            "route": item.get("route", {}),
        }
        record["files"] += 1
        record["bytes"] += int(item.get("size_bytes") or 0)
        if len(record["samples"]) < 5:
            record["samples"].append(doc)
        if len(samples) < limit:
            samples.append(doc)

    return {
        "status": "ok",
        "source_root": root.as_posix(),
        "kind": "route_changed",
        "pending_route_changes": len(route_changes),
        "groups": sorted(
            groups.values(),
            key=lambda group: (-int(group["files"]), group["current_dataset_name"], group["target_dataset_name"]),
        ),
        "samples": samples,
        "watch_counts": status["counts"],
        "apply_supported": False,
        "safe_next_step": (
            "Use this as a dry-run plan. Route-change apply must delete old Qdrant points "
            "and move SQLite/storage rows under a guarded runner; ordinary watch scan skips it."
        ),
    }


@router.get("/watch/status")
async def folder_watch_status(source_root: str = "RAG_Content", limit: int = 20, _user=Depends(require_user)):
    root = _safe_source_root(source_root)
    return await asyncio.to_thread(build_folder_watch_status, root, limit=limit)


@router.get("/watch/reindex-plan")
async def folder_reindex_plan(source_root: str = "RAG_Content", limit: int = 50, _user=Depends(require_user)):
    root = _safe_source_root(source_root)
    return await asyncio.to_thread(build_folder_reindex_plan, root, limit=limit)


@router.post("/watch/scan")
async def folder_watch_scan(req: FolderWatchRequest, _admin=Depends(require_admin)):
    state = get_dataset_state()
    root = _safe_source_root(req.source_root)
    clear_folder_watch_cache(root)
    before, changes = await asyncio.to_thread(_folder_watch_inventory, root, limit=req.limit)
    route_changed = [change for change in changes if change["state"] == "route_changed"]
    register_changes = [change for change in changes if change["state"] in {"new", "changed"}]
    ds_list = await state.backend.list_datasets()
    dataset_ids = {dataset.name: dataset.id for dataset in ds_list}
    registered_by_dataset: dict[str, dict[str, Any]] = {}
    for change in register_changes:
        dataset_name = change["dataset_name"]
        item = change["item"]
        dataset_id = dataset_ids.get(dataset_name)
        if dataset_id is None:
            dataset_id = await state.backend.create_dataset(dataset_name)
            dataset_ids[dataset_name] = dataset_id
        await state.backend.upload_file(
            dataset_id,
            Path(item["path"]),
            relative_path=item["relative_path"],
        )
        record = registered_by_dataset.setdefault(
            dataset_name,
            {
                "dataset_id": dataset_id,
                "dataset_name": dataset_name,
                "pending_files": 0,
                "new": 0,
                "changed": 0,
                "route_changed": 0,
            },
        )
        record["pending_files"] += 1
        record[change["state"]] += 1
    after = await asyncio.to_thread(build_folder_watch_status, root, limit=req.limit)
    return {
        "status": "registered",
        "source_root": root.as_posix(),
        "before": before,
        "sync": {
            "status": "registered",
            "source_root": root.as_posix(),
            "datasets": list(registered_by_dataset.values()),
            "files": len(register_changes),
            "skipped_route_changed": len(route_changed),
            "parse_started": False,
            "parse_results": [],
            "plan_summary": before["plan_summary"],
            "errors": before["errors"],
        },
        "after": after,
    }


@router.post("/sync-smart")
async def sync_smart(req: SmartSyncRequest, _admin=Depends(require_admin)):
    state = get_dataset_state()
    root = _safe_source_root(req.source_root)

    plan = await asyncio.to_thread(build_smart_plan, root)
    ds_list = await state.backend.list_datasets()
    dataset_ids = {dataset.name: dataset.id for dataset in ds_list}
    registered = []
    total_files = 0
    for dataset_name, items in plan["plan"].items():
        dataset_id = dataset_ids.get(dataset_name)
        if dataset_id is None:
            dataset_id = await state.backend.create_dataset(dataset_name)
            dataset_ids[dataset_name] = dataset_id
        for item in items:
            await state.backend.upload_file(
                dataset_id,
                Path(item["path"]),
                relative_path=item["relative_path"],
            )
        registered.append({"dataset_id": dataset_id, "dataset_name": dataset_name, "pending_files": len(items)})
        total_files += len(items)

    parse_results = []
    if req.parse:
        async with state.sync_parse_semaphore:
            await assert_parse_admission(state)
            for item in registered:
                result = await state.backend.parse_dataset(
                    item["dataset_id"],
                    limit=req.parse_limit_per_dataset,
                )
                parse_results.append({"dataset_id": item["dataset_id"], "dataset_name": item["dataset_name"], "result": result})

    return {
        "status": "registered",
        "source_root": root.as_posix(),
        "datasets": registered,
        "files": total_files,
        "parse_started": req.parse,
        "parse_results": parse_results,
        "plan_summary": plan["datasets"],
        "errors": plan["errors"],
    }


def _auto_run_pipelines(root, les_md: dict | None) -> None:
    """Авто-исполнение директив LES.md в фоне (ид→asbuilt). Без команды оператора."""
    pipelines = (les_md or {}).get("pipelines") or {}
    if not isinstance(pipelines, dict):
        return
    if str(pipelines.get("ид") or pipelines.get("id") or "").strip().lower() == "asbuilt":
        from proxy.services.asbuilt_intake_service import iter_pdfs, process_path
        if not iter_pdfs(root):
            return
        pid = int((les_md or {}).get("project_id") or 0)
        engine = os.getenv("LES_ASBUILT_OCR_ENGINE", "local")

        def _job():
            try:
                process_path(root, rotate="auto", engine=engine, write=True,
                             status="pending", project_id=pid)
            except Exception as err:  # noqa: BLE001
                logger.error("[AUTO-PIPELINE] asbuilt %s: %s", root, err)

        threading.Thread(target=_job, name="auto-asbuilt", daemon=True).start()
        logger.info("[AUTO-PIPELINE] ид→asbuilt запущен в фоне: %s", root)


@router.post("/index-external")
async def index_external(req: IndexExternalRequest, _admin=Depends(require_admin)):
    """In-place индексация одобренной внешней папки.

    Исходники НЕ копируются в storage — в LES попадают только производные
    (Qdrant-векторы, Parquet, метаданные). Путь обязан быть внутри
    LES_EXTERNAL_SOURCE_ROOTS (resolve снимает симлинки → ссылка/`..` наружу
    отклоняется). Каждый файл дополнительно проверяется на выход за корень.
    """
    state = get_dataset_state()
    root = validate_external_source(req.path)

    ds_list = await state.backend.list_datasets()
    dataset = next((dataset for dataset in ds_list if dataset.id == req.dataset_id), None)
    if dataset is None:
        raise HTTPException(404, f"dataset_id не найден: {req.dataset_id} (создайте датасет заранее)")

    if req.background:
        asyncio.create_task(_index_external_run(state, req, root, dataset))
        return {"status": "started", "dataset_id": req.dataset_id, "dataset_name": dataset.name,
                "note": "регистрация и индексация идут в фоне — файлы появятся в датасете"}
    return await _index_external_run(state, req, root, dataset)


async def _index_external_run(state, req, root, dataset) -> dict:
    """Тело in-place индексации: нарезка крупных PDF + регистрация файлов + LES.md + (опц.) парс.
    Выносимо в фон (req.background) — не зависит от HTTP-таймаута на больших папках (758 файлов = ~47с)."""
    # Авто-нарезка крупных PDF (штатная часть ЛЕСа, tools/pdf_preprocess): чистим+режем
    # гиганты на части < split_max_mb (границы по оглавлению), оригиналы → в _originals/.
    # Без этого 150–200МБ-каталог вешает конвертер (блокирует event loop). Не роняет индексацию.
    split_summary = {"split_files": 0, "parts": 0}
    if req.auto_split:
        try:
            from tools.pdf_preprocess import preprocess_dir
            max_bytes = int(req.split_max_mb * 1024 * 1024)
            results = await asyncio.to_thread(preprocess_dir, root, max_bytes)
            for r in results:
                if getattr(r, "action", "") == "clean+split" and getattr(r, "split", None):
                    split_summary["split_files"] += 1
                    split_summary["parts"] += len(r.split.parts)
            if split_summary["split_files"]:
                logger.info("[INDEX-EXT] авто-нарезка: %s гигантов → %s частей",
                            split_summary["split_files"], split_summary["parts"])
        except Exception as err:  # noqa: BLE001 — нарезка не должна ронять индексацию
            logger.warning("[INDEX-EXT] авто-нарезка пропущена: %s", err)

    suffixes = rag_upload_suffixes()
    registered = 0
    skipped_unsupported = 0
    skipped_outside_root = 0
    samples: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if "_originals" in path.parts:  # архив оригиналов после нарезки — не индексируем
            continue
        # Анти-traversal: симлинк внутри папки, указывающий наружу корня, отбрасываем.
        if not is_within_external_root(path, root):
            skipped_outside_root += 1
            continue
        resolved = path.resolve()
        if resolved.suffix.lower() not in suffixes:
            skipped_unsupported += 1
            continue
        # file_name — путь относительно родителя корня: "<папка>/rel" (читаемо и уникально).
        file_name = resolved.relative_to(root.parent).as_posix()
        await state.backend.register_external_file(req.dataset_id, resolved, file_name)
        registered += 1
        if len(samples) < 10:
            samples.append(file_name)

    if registered == 0:
        raise HTTPException(400, f"в папке нет поддерживаемых документов: {root}")

    # Auto-init: дал папку индексировать → LES.md появляется сам + привязка к проекту,
    # затем авто-исполнение директив (ид→asbuilt и т.п.) в фоне. 0 команд от оператора.
    les_md_summary = None
    try:
        from proxy.services.les_md_service import read_and_bind
        les_md_summary = await asyncio.to_thread(read_and_bind, root, write_draft=True)
        # #2 симметрия: привязать СОЗДАННЫЙ датасет к объекту (kind='dataset'), а не только папку.
        # Иначе датасет и проект жили раздельно → режим датасета терял LES.md, обратный поиск пуст.
        _md_pid = int((les_md_summary or {}).get("project_id") or 0)
        if _md_pid:
            from proxy.services.project_service import link_entity
            await asyncio.to_thread(link_entity, _md_pid, "dataset", req.dataset_id)
        if os.getenv("LES_AUTO_PIPELINES", "true").lower() in ("1", "true", "yes", "on"):
            _auto_run_pipelines(root, les_md_summary)
    except Exception as err:  # noqa: BLE001 — авто-init не должен ронять индексацию
        logger.warning("[LES.md] auto-init при индексации %s: %s", root, err)

    parse_started = False
    if req.parse:
        async def _parse():
            async with state.parse_semaphore:
                await assert_parse_admission(state)
                await state.backend.parse_dataset(req.dataset_id, limit=req.parse_limit)

        asyncio.create_task(_parse())
        parse_started = True

    return {
        "status": "registered",
        "source_root": root.as_posix(),
        "dataset_id": req.dataset_id,
        "dataset_name": dataset.name,
        "registered_files": registered,
        "skipped_unsupported": skipped_unsupported,
        "skipped_outside_root": skipped_outside_root,
        "split_large_pdfs": split_summary["split_files"],
        "split_parts": split_summary["parts"],
        "in_place": True,
        "copied_to_storage": False,
        "parse_started": parse_started,
        "parse_limit": req.parse_limit,
        "samples": samples,
        "les_md": les_md_summary,  # auto-init: что ЛЕС сам понял о папке + директивы
    }


def _count_dir_files(d: Path) -> int:
    """Быстрый счёт файлов в папке (только непосредственные дети) — для подсказки в браузере."""
    try:
        return sum(1 for x in d.iterdir() if x.is_file() and not x.name.startswith("."))
    except OSError:
        return 0


@router.get("/browse-external")
async def browse_external(path: str = "", _admin=Depends(require_admin)):
    """Серверный браузер папок для выбора внешней папки кликами (без печати пути).

    По умолчанию (LES_EXTERNAL_ALLOW_ANY, single-user) — браузер ходит по ВСЕЙ локальной ФС от
    $HOME, любая папка индексируема. Строгий режим (=0) ограничивает корнями LES_EXTERNAL_SOURCE_ROOTS.
    Пустой `path` → старт ($HOME + корни как быстрый выбор); иначе — подпапки + «вверх».
    """
    from proxy.config import external_source_roots, external_allow_any, external_browse_default

    roots = external_source_roots()
    allow_any = external_allow_any()
    if not roots and not allow_any:
        raise HTTPException(403, "внешняя индексация выключена: LES_EXTERNAL_SOURCE_ROOTS пуст")

    if not (path or "").strip():
        if allow_any:
            start = external_browse_default()      # $HOME — отсюда видно любую папку
            dirs = []
            try:
                for child in sorted(start.iterdir(), key=lambda p: p.name.lower()):
                    if child.is_dir() and not child.name.startswith("."):
                        dirs.append({"name": child.name, "path": str(child), "file_count": _count_dir_files(child)})
            except OSError:
                pass
            return {"path": str(start), "parent": str(start.parent) if start.parent != start else None,
                    "roots": [str(r) for r in roots], "dirs": dirs}
        return {"path": "", "parent": None, "roots": [str(r) for r in roots],
                "dirs": [{"name": r.name or str(r), "path": str(r), "file_count": _count_dir_files(r)} for r in roots]}

    current = validate_external_source(path)  # resolve+isdir guard (+ allowlist если строгий режим)
    dirs = []
    for child in sorted(current.iterdir(), key=lambda p: p.name.lower()):
        try:
            if child.is_dir() and not child.name.startswith("."):
                dirs.append({"name": child.name, "path": str(child), "file_count": _count_dir_files(child)})
        except OSError:
            continue
    # в allow_any можно подниматься до корня ФС; в строгом — не выше одобренного корня.
    is_root = any(current == r for r in roots)
    parent = None if (current.parent == current or (not allow_any and is_root)) else str(current.parent)
    return {"path": str(current), "parent": parent, "roots": [str(r) for r in roots], "dirs": dirs}


@router.post("/sync/{folder}")
async def sync_folder(folder: str, _admin=Depends(require_admin)):
    state = get_dataset_state()
    src_dir = validate_source_folder(folder)
    if UUID_RE.match(folder) or folder in SKIP_DIRS:
        raise HTTPException(status_code=400, detail=f"source folder is excluded from RAG sync: {folder}")
    source_root = Path("./RAG_Content")
    source_paths = list(src_dir.rglob("*"))
    decisions = [verify_source_file(path, source_root) for path in source_paths]
    files = [path for path, decision in zip(source_paths, decisions) if decision.accepted]
    if not files:
        raise HTTPException(status_code=400, detail=f"no supported documents found in source folder: {folder}")
    rejected_reasons: dict[str, int] = {}
    for decision in decisions:
        if decision.reason in {"accepted", "not_file"}:
            continue
        rejected_reasons[decision.reason] = rejected_reasons.get(decision.reason, 0) + 1

    ds_list = await state.backend.list_datasets()
    ds_name = f"{folder}_Index"
    ds = next((dataset for dataset in ds_list if dataset.name == ds_name), None)
    if not ds:
        ds_id = await state.backend.create_dataset(ds_name)
        ds = DatasetInfo(id=ds_id, name=ds_name, status="IDLE", doc_count=0, chunk_count=0)

    now_ts = datetime.now()
    stale = [
        key
        for key, value in state.job_tracker.items()
        if value.get("started_at")
        and (now_ts - datetime.fromisoformat(value["started_at"])).total_seconds() > 86400
    ]
    for key in stale:
        del state.job_tracker[key]

    job = state.job_service.create(
        "rag_sync",
        source=folder,
        dataset_id=ds.id,
        dataset_name=ds_name,
        status="running",
        message="Сканирование...",
    )
    job_id = job["id"]
    state.job_tracker[job_id] = {
        "dataset_id": ds.id,
        "dataset_name": ds_name,
        "status": "SCANNING",
        "total": 0,
        "processed": 0,
        "started_at": job["started_at"],
        "message": "Сканирование...",
    }

    dest_dir = Path(f"./storage/datasets/{ds.id}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    new_count, skip_count, changed_count = 0, 0, 0
    state.job_tracker[job_id]["total"] = len(files)
    state.job_service.update(job_id, total=len(files), status="running")

    for index, source_file in enumerate(files):
        rel_path = source_file.relative_to(src_dir)
        dest = dest_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)

        stat = source_file.stat()
        is_new = not dest.exists()
        is_changed = False
        if not is_new:
            dest_stat = dest.stat()
            if stat.st_size != dest_stat.st_size or abs(stat.st_mtime - dest_stat.st_mtime) > 1.0:
                is_changed = True
        if is_new or is_changed:
            await state.backend.upload_file(ds.id, source_file, relative_path=rel_path.as_posix())
            if is_new:
                new_count += 1
            else:
                changed_count += 1
        else:
            skip_count += 1
        state.job_tracker[job_id]["processed"] = index + 1
        state.job_tracker[job_id]["message"] = (
            f"{'Новый' if is_new else 'Обновлён' if is_changed else 'Пропущен'}: {source_file.name}"
        )
        state.job_service.update(job_id, processed=index + 1, message=state.job_tracker[job_id]["message"])
        if (index + 1) % 20 == 0 or is_new or is_changed:
            state.log_history.append(
                f"[JOB {job_id}] {source_file.name} ({index + 1}/{len(files)}): "
                f"{'NEW' if is_new else 'CHANGED' if is_changed else 'SKIP'}"
            )
        await asyncio.sleep(0.1)

    force_reindex = (new_count + changed_count) == 0 and (ds.chunk_count or 0) == 0 and skip_count > 0

    if force_reindex:
        state.job_tracker[job_id]["status"] = "PARSING"
        state.job_tracker[job_id]["message"] = f"Индекс пуст — принудительная переиндексация {skip_count} файлов"
        state.job_service.update(job_id, status="running", message=state.job_tracker[job_id]["message"])
        logger.info("[JOB %s] Force reindex: 0 chunks in Qdrant, %s files on disk", job_id, skip_count)
    else:
        has_changes = (new_count + changed_count) > 0
        state.job_tracker[job_id]["status"] = "PARSING" if has_changes else "COMPLETED"
        state.job_tracker[job_id]["message"] = (
            f"Векторизация bge-m3: {new_count} новых, {changed_count} изм."
            if has_changes
            else f"Нет изменений (пропущено {skip_count})"
        )
        state.job_service.update(
            job_id,
            status="running" if has_changes else "completed",
            message=state.job_tracker[job_id]["message"],
            result={"new_files": new_count, "changed_files": changed_count, "skipped_files": skip_count},
        )

    if (new_count + changed_count) > 0 or force_reindex:
        async def _run():
            try:
                async with state.sync_parse_semaphore:
                    os.nice(10)
                    await assert_parse_admission(state)
                    result = await state.backend.parse_dataset(ds.id, limit=DEFAULT_PARSE_BATCH_LIMIT)
                chunks = result.get("chunks", 0) if isinstance(result, dict) else 0
                elapsed = result.get("elapsed_sec", 0) if isinstance(result, dict) else 0
                errors = result.get("errors", 0) if isinstance(result, dict) else 0
                remaining = result.get("remaining_pending", 0) if isinstance(result, dict) else 0
                result_status = result.get("status", "unknown") if isinstance(result, dict) else "unknown"
                if result_status != "completed" or errors:
                    final_status = "FAILED"
                    service_status = "failed"
                elif remaining:
                    final_status = "PARTIAL"
                    service_status = "completed"
                else:
                    final_status = "COMPLETED"
                    service_status = "completed"
                state.job_tracker[job_id]["status"] = final_status
                state.job_tracker[job_id]["finished_at"] = datetime.now().isoformat()
                state.job_tracker[job_id]["message"] = (
                    f"Готово: +{new_count} новых, ~{changed_count} обновлённых, "
                    f"пропущено {skip_count} | {chunks} чанков | {elapsed:.0f}с | "
                    f"осталось pending={remaining}, errors={errors}"
                )
                state.job_service.update(
                    job_id,
                    status=service_status,
                    message=state.job_tracker[job_id]["message"],
                    result={
                        "new_files": new_count,
                        "changed_files": changed_count,
                        "skipped_files": skip_count,
                        "chunks": chunks,
                        "elapsed_sec": elapsed,
                        "remaining_pending": remaining,
                        "errors": errors,
                        "parse_status": result_status,
                    },
                )
                logger.info(
                    "[JOB %s] %s: %s chunks, %.0fs, remaining=%s, errors=%s",
                    job_id, final_status, chunks, elapsed, remaining, errors,
                )
            except Exception as e:
                state.job_tracker[job_id]["status"] = "FAILED"
                state.job_tracker[job_id]["finished_at"] = datetime.now().isoformat()
                state.job_tracker[job_id]["message"] = f"Ошибка: {str(e)}"
                state.job_service.update(job_id, status="failed", errors=1, message=state.job_tracker[job_id]["message"])
                logger.error("[JOB %s] FAILED: %s", job_id, e, exc_info=True)

        asyncio.create_task(_run())

    return {
        "status": "sync_started",
        "job_id": job_id,
        "dataset_id": ds.id,
        "new_files": new_count,
        "changed_files": changed_count,
        "skipped_files": skip_count,
        "rejected_files": sum(rejected_reasons.values()),
        "rejected_reasons": rejected_reasons,
    }


@router.post("/parse-batch/{dataset_id}")
async def parse_dataset_batch(
    dataset_id: str,
    limit: int = Query(default=DEFAULT_PARSE_BATCH_LIMIT, ge=1, le=25),
    _admin=Depends(require_admin),
):
    state = get_dataset_state()
    async with state.parse_semaphore:
        await assert_parse_admission(state)
        result = await state.backend.parse_dataset(dataset_id, limit=limit)
    return {"dataset_id": dataset_id, "limit": limit, "result": result}


@router.post("/parse-scheduler")
async def parse_scheduler(req: ParseSchedulerRequest, _admin=Depends(require_admin)):
    state = get_dataset_state()
    active_job = active_parse_scheduler_job(state)
    if active_job:
        job_id, job = active_job
        raise HTTPException(
            status_code=409,
            detail=(
                f"Parse scheduler already active: {job_id} "
                f"{job.get('status', '')} {job.get('message', '')}"
            ),
        )

    min_free_gb = req.min_free_gb if req.min_free_gb is not None else PARSE_MIN_FREE_GB
    max_swap_pct = req.max_swap_pct if req.max_swap_pct is not None else PARSE_MAX_SWAP_PCT
    await assert_parse_admission(state, min_free_gb=min_free_gb, max_swap_pct=max_swap_pct)

    if not req.background:
        return await run_parse_scheduler(state, req)

    job = state.job_service.create(
        "rag_parse_scheduler",
        source="pending",
        status="running",
        message="Parse scheduler queued",
        total=req.max_batches,
    )
    job_id = job["id"]
    state.job_tracker[job_id] = {
        "type": "rag_parse_scheduler",
        "status": "QUEUED",
        "total": req.max_batches,
        "processed": 0,
        "started_at": job["started_at"],
        "message": "Parse scheduler queued",
    }

    async def _run():
        try:
            await run_parse_scheduler(state, req, job_id=job_id)
        except Exception as error:
            state.job_tracker[job_id]["status"] = "FAILED"
            state.job_tracker[job_id]["finished_at"] = datetime.now().isoformat()
            state.job_tracker[job_id]["message"] = f"Ошибка scheduler: {error}"
            state.job_service.update(job_id, status="failed", errors=1, message=state.job_tracker[job_id]["message"])
            logger.error("[PARSE_SCHEDULER %s] FAILED: %s", job_id, error, exc_info=True)

    asyncio.create_task(_run())
    return {
        "status": "queued",
        "job_id": job_id,
        "batch_limit": req.batch_limit,
        "max_batches": req.max_batches,
    }


async def _dataset_id_for_name(state: DatasetRouterState, dataset_name: str) -> tuple[str, bool]:
    ds_list = await state.backend.list_datasets()
    ds = next((dataset for dataset in ds_list if dataset.name == dataset_name), None)
    if ds:
        return ds.id, False
    return await state.backend.create_dataset(dataset_name), True


def _upload_intake_response(temp_path: Path, original_name: str) -> dict[str, Any]:
    size = temp_path.stat().st_size
    if size <= 0:
        raise HTTPException(status_code=400, detail="Файл пустой")
    return {
        "accepted": True,
        "reason": "accepted",
        "file_name": original_name,
        "suffix": temp_path.suffix.lower(),
        "size_bytes": size,
    }


@router.post("/upload/{dataset_id}")
async def upload_file(dataset_id: str, file: UploadFile = File(...), _admin=Depends(require_admin)):
    state = get_dataset_state()
    original_name = safe_upload_name(file.filename or "upload.bin", rag_upload_suffixes())
    temp_path = await save_upload_tmp(
        file,
        allowed_suffixes=rag_upload_suffixes(),
        max_bytes=max_upload_bytes(),
    )
    doc_id = await state.backend.upload_file(dataset_id, temp_path, relative_path=original_name)

    async def _parse():
        # Дренаж очереди: один upload разгребает батч PENDING (а не 1 док — иначе
        # пачка аплоадов оставляет хвост висеть, см. фикс индексатора 2026-06-17).
        try:
            limit = int(os.getenv("LES_UPLOAD_PARSE_LIMIT", "25"))
        except ValueError:
            limit = 25
        try:
            async with state.parse_semaphore:
                await assert_parse_admission(state)
                await state.backend.parse_dataset(dataset_id, limit=limit)
        finally:
            temp_path.unlink(missing_ok=True)

    asyncio.create_task(_parse())
    return {"doc_id": doc_id, "status": "queued"}


# ── Скрепка чата: прикрепить документ (W11.8) ──

_CHAT_ATTACH_DATASET_NAME = "Вложения чата"
_QUICK_ATTACH_PREFIX = "attach_"
_ATTACH_STORAGE_ROOT = Path("storage/datasets")
_READ_ATTACH_MAX_CHARS = int(os.getenv("RAG_ATTACH_READ_MAX_CHARS", "18000"))


async def _ensure_chat_attach_dataset(state) -> str:
    for d in await state.backend.list_datasets():
        if d.name == _CHAT_ATTACH_DATASET_NAME:
            return d.id
    return await state.backend.create_dataset(_CHAT_ATTACH_DATASET_NAME)


def _cleanup_quick_attachments(root: Path, max_age_sec: int = 6 * 3600) -> None:
    """Устаревшие быстрые вложения (parquet-only) удаляем, чтобы не копились в сверке."""
    if not root.exists():
        return
    for d in root.glob(f"{_QUICK_ATTACH_PREFIX}*"):
        try:
            if d.is_dir() and (time.time() - d.stat().st_mtime) > max_age_sec:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


@router.post("/attach")
async def attach_chat_file(
    file: UploadFile = File(...),
    mode: str = Query("quick"),
    _admin=Depends(require_admin),
):
    """Скрепка чата.

    ``mode=read`` — прочитать файл в markdown и вернуть текст как контекст следующего запроса
    (без индексации); ``mode=quick`` — быстрый парс таблиц в Parquet (без векторов), сразу
    доступно сверке/таблицам; ``mode=index`` — полная индексация в датасет «Вложения чата»
    (вектора в Qdrant). На парсе таблиц LLM не участвует (ADR-11).
    """
    from uuid import uuid4

    state = get_dataset_state()
    original_name = safe_upload_name(file.filename or "upload.bin", rag_upload_suffixes())
    temp_path = await save_upload_tmp(file, allowed_suffixes=rag_upload_suffixes(), max_bytes=max_upload_bytes())

    if mode == "read":
        try:
            from backend.converter import convert_to_markdown

            try:
                text = await asyncio.to_thread(convert_to_markdown, temp_path)
            except Exception as error:  # noqa: BLE001 - upload errors must stay operator-visible
                logger.warning("[ATTACH] read conversion failed for %s: %s", original_name, error)
                raise HTTPException(
                    422,
                    f"Не удалось прочитать файл «{original_name}»: {error}. "
                    "Попробуй режим индексации/OCR или другой формат файла.",
                ) from error
        finally:
            temp_path.unlink(missing_ok=True)
        text = (text or "").strip()
        if not text:
            raise HTTPException(
                422,
                f"Не удалось прочитать текст из «{original_name}». "
                "Для таблиц попробуй режим быстрой сверки, для сканов — индексацию/OCR.",
            )
        truncated = len(text) > _READ_ATTACH_MAX_CHARS
        return {
            "attachment_id": f"read_{uuid4().hex[:12]}",
            "mode": "read",
            "name": original_name,
            "chars": len(text),
            "text": text[:_READ_ATTACH_MAX_CHARS],
            "truncated": truncated,
        }

    if mode == "index":
        ds_id = await _ensure_chat_attach_dataset(state)
        doc_id = await state.backend.upload_file(ds_id, temp_path, relative_path=original_name)

        async def _parse():
            try:
                async with state.parse_semaphore:
                    await assert_parse_admission(state)
                    await state.backend.parse_dataset(ds_id, limit=25)
            finally:
                temp_path.unlink(missing_ok=True)

        asyncio.create_task(_parse())
        return {"attachment_id": ds_id, "mode": "index", "name": original_name,
                "dataset_name": _CHAT_ATTACH_DATASET_NAME, "doc_id": doc_id, "status": "queued"}

    # quick: парс таблиц в Parquet-«датасет», который сверка обнаружит автоматически
    from backend.parquet_writer import TableNormalizer

    _cleanup_quick_attachments(_ATTACH_STORAGE_ROOT)
    attach_id = f"{_QUICK_ATTACH_PREFIX}{uuid4().hex[:12]}"
    attach_dir = _ATTACH_STORAGE_ROOT / attach_id
    try:
        norm = TableNormalizer(use_llm=False, parquet_dir=str(attach_dir / "_parquet"))
        res = await norm.process(str(temp_path), dataset_id=attach_id)
    finally:
        temp_path.unlink(missing_ok=True)

    if not res.get("rows"):
        shutil.rmtree(attach_dir, ignore_errors=True)
        raise HTTPException(
            422, f"В файле «{original_name}» не найдено табличных строк для быстрой сверки. "
                 "Для текстовых документов используй режим индексации.",
        )
    (attach_dir / "_name.txt").write_text(original_name, encoding="utf-8")
    return {"attachment_id": attach_id, "mode": "quick", "name": original_name,
            "rows": res["rows"], "doc_type": res.get("doc_type", "")}


@router.post("/upload-smart")
async def upload_file_smart(
    file: UploadFile = File(...),
    parse: bool = Query(default=True),
    _admin=Depends(require_admin),
):
    state = get_dataset_state()
    original_name = safe_upload_name(file.filename or "upload.bin", rag_upload_suffixes())
    temp_path = await save_upload_tmp(
        file,
        allowed_suffixes=rag_upload_suffixes(),
        max_bytes=max_upload_bytes(),
    )
    try:
        intake = _upload_intake_response(temp_path, original_name)
        route = await asyncio.to_thread(route_document, temp_path)
        dataset_id, created = await _dataset_id_for_name(state, route.dataset_name)
        doc_id = await state.backend.upload_file(dataset_id, temp_path, relative_path=original_name)

        if parse:
            async def _parse():
                try:
                    async with state.parse_semaphore:
                        await assert_parse_admission(state)
                        await state.backend.parse_dataset(dataset_id, limit=1)
                finally:
                    temp_path.unlink(missing_ok=True)

            asyncio.create_task(_parse())
            status = "queued"
        else:
            temp_path.unlink(missing_ok=True)
            status = "registered"

        return {
            "doc_id": doc_id,
            "status": status,
            "dataset_id": dataset_id,
            "dataset_name": route.dataset_name,
            "dataset_created": created,
            "intake": intake,
            "route": asdict(route),
            "parse_started": parse,
        }
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
