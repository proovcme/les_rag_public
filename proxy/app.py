"""FastAPI application factory for LES Proxy v3."""

from __future__ import annotations

import asyncio
import collections
import logging
import os
import sqlite3
import time
from collections import defaultdict

import httpx
import psutil
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from backend.metrics_collector import init_db, metrics_loop
from backend.qdrant_adapter import QdrantLlamaIndexAdapter
from backend.rag_config import embedding_api_model, rag_meta_db_path
from proxy.config import CORS_ALLOWED_ORIGIN_REGEX, CORS_ALLOWED_ORIGINS
from proxy.routers.auth import router as auth_router, seed_admin_key
from proxy.routers.bor import router as bor_router
from proxy.routers.diff import router as diff_router
from proxy.routers.filemap import router as filemap_router
from proxy.routers.tasks import notes_router, router as tasks_router
from proxy.routers.projects import router as projects_router
from proxy.routers.edges import router as edges_router
from proxy.routers.ontology import router as ontology_router
from proxy.routers.decisions import router as decisions_router
from proxy.routers.worklog import router as worklog_router
from proxy.routers.incoming_control import router as incoming_control_router
from proxy.routers.estimates import router as estimates_router
from proxy.routers.forms import router as forms_router
from proxy.routers.files import router as files_router
from proxy.routers.field import router as field_router
from proxy.routers.normcontrol import router as normcontrol_router
from proxy.routers.chat import ChatRouterState, ensure_chat_history_schema, router as chat_router, set_chat_state
from proxy.routers.chat_history import router as chat_history_router
from proxy.routers.datasets import DatasetRouterState, router as datasets_router, search_router, set_dataset_state
from proxy.routers.diagnostics import DiagnosticsRouterState, router as diagnostics_router, set_diagnostics_state
from proxy.routers.jobs import JobsRouterState, router as jobs_router, set_jobs_state
from proxy.routers.logs import LogsRouterState, router as logs_router, set_logs_state
from proxy.routers.mail import router as mail_router
from proxy.routers.rerank import (
    RERANKER_AVAILABLE,
    Reranker,
    RerankRouterState,
    router as rerank_router,
    set_rerank_state,
)


def _select_reranker_cls():
    """W2.2 (ADR-3): cross-encoder по умолчанию, RERANKER_BACKEND=llm — старый путь."""
    try:
        from backend.reranker import select_reranker_cls

        return select_reranker_cls()
    except ImportError:
        return Reranker


from proxy.routers.runtime import RuntimeRouterState, router as runtime_router, set_runtime_state
from proxy.routers.settings import router as settings_router
from proxy.routers.speckle import cad_bim_router
from proxy.routers.status_page import StatusPageState, router as status_page_router, set_status_page_state
from proxy.services.job_service import JobService
from proxy.services.resource_governor import CHAT_MODE, PROFILE_CHAT

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

log_history = collections.deque(maxlen=2000)


class LogCapture(logging.Handler):
    def emit(self, record):
        log_history.append(self.format(record))


logging.getLogger().addHandler(LogCapture())

PARSE_CONCURRENCY = int(os.getenv("RAG_PARSE_CONCURRENCY", "1"))
SYNC_PARSE_CONCURRENCY = int(os.getenv("RAG_SYNC_PARSE_CONCURRENCY", "1"))
LLM_CONCURRENCY = int(os.getenv("LLM_CONCURRENCY", "1"))
parse_semaphore = asyncio.Semaphore(PARSE_CONCURRENCY)
sync_parse_semaphore = asyncio.Semaphore(SYNC_PARSE_CONCURRENCY)
llm_semaphore = asyncio.Semaphore(LLM_CONCURRENCY)
crag_stats = {"verified": 0, "no_data": 0, "hallucination": 0, "unvalidated": 0}
proxy_start = time.time()
rag_backend = None
job_tracker = {}
job_service = JobService()
current_mode = {
    "mode": CHAT_MODE,
    "runtime_profile": PROFILE_CHAT,
    "model": os.getenv("LLM_MODEL", "mlx-community/Qwen3-14B-4bit"),
    "chat_generation": "allowed",
}

error_counts = defaultdict(int)
chat_metrics = {
    "latency_search": [],
    "latency_gen": [],
    "latency_phases": [],  # W0.1: per-request dict {retrieval, context, generation, validation, overhead}
    "tokens": [],
    "crag_pass": 0,
    "crag_fail": 0,
    "cache_hit": 0,
    "cache_miss": 0,
    "retrieval_good": 0,
    "retrieval_weak": 0,
    # W3.3: учёт расходов облака (накопительно за аптайм proxy)
    "cloud_requests": 0,
    "cloud_prompt_tokens": 0,
    "cloud_completion_tokens": 0,
    "cloud_cost_usd": 0.0,
    "cloud_cost_by_model": {},
}

metrics_cache = {
    "cpu": 0.0,
    "ram_used": 0.0,
    "ram_free_gb": 0.0,
    "ram_total": 1.0,
    "datasets": 0,
    "files_processed": 0,
    "chunks_indexed": 0,
    "queue": 0,
    "active": 0,
    "avg_speed_fps": 0.0,
    "crag_verified": 0,
    "crag_no_data": 0,
}


class ParseStats:
    def __init__(self):
        self.queued = 0
        self.active = 0
        self.total_files = 0
        self.total_chunks = 0
        self.durations = []

    def avg_speed(self):
        if not self.durations:
            return 0.0
        avg = sum(self.durations) / len(self.durations)
        return round(1.0 / avg, 2) if avg > 0 else 0.0


parse_stats = ParseStats()


def _get_db_files():
    try:
        conn = sqlite3.connect(rag_meta_db_path())
        count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        conn.close()
        return count
    except Exception:
        return 0


async def metrics_collector_loop():
    while True:
        try:
            cpu = await asyncio.to_thread(psutil.cpu_percent, interval=None)
            vm = await asyncio.to_thread(psutil.virtual_memory)
            files = await asyncio.to_thread(_get_db_files)

            host_mem = {}
            try:
                mlx_url = os.getenv("MLX_URL", "http://127.0.0.1:8080")
                async with httpx.AsyncClient(timeout=2.0) as client:
                    response = await client.get(f"{mlx_url}/api/host_memory")
                    if response.status_code == 200:
                        host_mem = response.json()
            except Exception:
                pass

            ram_total_gb = float(host_mem.get("ram_total_gb", vm.total / 1e9))
            ram_free_gb = float(host_mem.get("ram_free_gb", vm.available / 1e9))
            ram_used_gb = max(0.0, ram_total_gb - ram_free_gb) if host_mem else vm.used / 1e9

            chunks = 0
            ds_count = 0
            if rag_backend:
                try:
                    ds_list = await rag_backend.list_datasets()
                    ds_count = len(ds_list)
                    if rag_backend._collection_ready:
                        info = await rag_backend.aclient.get_collection(rag_backend.collection_name)
                        chunks = getattr(info, "points_count", 0) or 0
                except Exception:
                    pass

            metrics_cache.update(
                {
                    "cpu": cpu,
                    "ram_used": ram_used_gb,
                    "ram_free_gb": ram_free_gb,
                    "ram_total": ram_total_gb,
                    "swap_used_gb": host_mem.get("swap_used_gb", 0),
                    "swap_total_gb": host_mem.get("swap_total_gb", 0),
                    "swap_pct": host_mem.get("swap_pct", 0),
                    "datasets": ds_count,
                    "files_processed": files,
                    "chunks_indexed": chunks,
                    "queue": parse_stats.queued,
                    "active": parse_stats.active,
                    "avg_speed_fps": parse_stats.avg_speed(),
                    "crag_verified": crag_stats["verified"],
                    "crag_no_data": crag_stats["no_data"],
                    "crag_unvalidated": crag_stats["unvalidated"],
                }
            )
        except Exception:
            pass
        await asyncio.sleep(3)


async def startup():
    global rag_backend
    init_db()
    seed_admin_key()
    interrupted_jobs = job_service.mark_interrupted_active_jobs("proxy startup")
    if interrupted_jobs:
        logger.info("[INIT] Marked %s stale active job(s) as interrupted", interrupted_jobs)
    try:
        conn = sqlite3.connect(rag_meta_db_path(), check_same_thread=False)
        ensure_chat_history_schema(conn)
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error("[INIT] Failed to init chat_history table: %s", e)

    try:
        rag_backend = QdrantLlamaIndexAdapter(
            qdrant_url=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"),
            mlx_url=os.getenv("MLX_URL", "http://127.0.0.1:8080"),
            embed_model_name=embedding_api_model(),
        )
        await rag_backend.health()
        logger.info("[INIT] Backend initialized successfully")
        asyncio.create_task(metrics_collector_loop())
        asyncio.create_task(metrics_loop())
    except Exception as e:
        logger.error("[INIT] Backend initialization failed: %s", e)
        raise


async def track_errors(request: Request, call_next):
    response = await call_next(request)
    if response.status_code >= 400:
        error_counts[response.status_code] += 1
    return response


def configure_router_state() -> None:
    set_dataset_state(
        DatasetRouterState(
            rag_backend=lambda: rag_backend,
            job_service=job_service,
            job_tracker=job_tracker,
            log_history=log_history,
            parse_semaphore=parse_semaphore,
            sync_parse_semaphore=sync_parse_semaphore,
            current_mode=current_mode,
        )
    )
    set_runtime_state(
        RuntimeRouterState(
            rag_backend=lambda: rag_backend,
            current_mode=current_mode,
            metrics_cache=metrics_cache,
            chat_metrics=chat_metrics,
            crag_stats=crag_stats,
            error_counts=error_counts,
            llm_semaphore=llm_semaphore,
            llm_concurrency=LLM_CONCURRENCY,
            proxy_start=proxy_start,
            job_service=job_service,
            job_tracker=job_tracker,
        )
    )
    set_diagnostics_state(DiagnosticsRouterState(crag_stats=crag_stats, proxy_start=proxy_start))
    set_jobs_state(JobsRouterState(job_service=job_service, job_tracker=job_tracker))
    set_logs_state(LogsRouterState(log_history=log_history))
    set_status_page_state(StatusPageState(crag_stats=crag_stats, proxy_start=proxy_start))
    set_chat_state(
        ChatRouterState(
            rag_backend=lambda: rag_backend,
            llm_semaphore=llm_semaphore,
            crag_stats=crag_stats,
            chat_metrics=chat_metrics,
            reranker_available=RERANKER_AVAILABLE,
            reranker_cls=_select_reranker_cls(),
            current_mode=current_mode,
            metrics_cache=metrics_cache,
            job_service=job_service,
            job_tracker=job_tracker,
        )
    )
    set_rerank_state(RerankRouterState(llm_semaphore=llm_semaphore, current_mode=current_mode))


_app: FastAPI | None = None


def create_app():
    global _app
    if _app is not None:
        return _app

    configure_router_state()

    fastapi_app = FastAPI(title="LES Proxy v2.0", version="2.0.0")
    fastapi_app.add_middleware(
        CORSMiddleware,
        allow_origins=list(CORS_ALLOWED_ORIGINS),
        allow_origin_regex=CORS_ALLOWED_ORIGIN_REGEX,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    fastapi_app.include_router(auth_router)
    fastapi_app.include_router(bor_router)
    fastapi_app.include_router(diff_router)
    fastapi_app.include_router(filemap_router)
    fastapi_app.include_router(tasks_router)
    fastapi_app.include_router(projects_router)
    fastapi_app.include_router(edges_router)
    fastapi_app.include_router(ontology_router)
    fastapi_app.include_router(decisions_router)
    fastapi_app.include_router(worklog_router)
    fastapi_app.include_router(incoming_control_router)
    fastapi_app.include_router(estimates_router)
    fastapi_app.include_router(forms_router)
    fastapi_app.include_router(files_router)
    fastapi_app.include_router(notes_router)
    fastapi_app.include_router(field_router)
    fastapi_app.include_router(normcontrol_router)
    fastapi_app.include_router(settings_router)
    fastapi_app.include_router(cad_bim_router)
    fastapi_app.include_router(chat_history_router)
    fastapi_app.include_router(datasets_router)
    fastapi_app.include_router(search_router)
    fastapi_app.include_router(runtime_router)
    fastapi_app.include_router(diagnostics_router)
    fastapi_app.include_router(jobs_router)
    fastapi_app.include_router(logs_router)
    fastapi_app.include_router(mail_router)
    fastapi_app.include_router(rerank_router)
    fastapi_app.include_router(status_page_router)
    fastapi_app.include_router(chat_router)
    fastapi_app.on_event("startup")(startup)
    fastapi_app.middleware("http")(track_errors)
    _app = fastapi_app
    return _app


app = create_app()
