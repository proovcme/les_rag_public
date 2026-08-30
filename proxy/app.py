"""FastAPI application factory for LES Proxy v3."""

from __future__ import annotations

import asyncio
import collections
import logging
import os
import sqlite3
import sys
import time
from collections import defaultdict

import httpx
import psutil
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from backend.http_client_policy import trust_env_for_url
from backend.metrics_collector import init_db, metrics_loop
from backend.qdrant_adapter import QdrantLlamaIndexAdapter
from backend.rag_config import embedding_api_model, rag_meta_db_path
from proxy.config import CORS_ALLOWED_ORIGIN_REGEX, CORS_ALLOWED_ORIGINS
from proxy.local_model_registry import DEFAULT_LOCAL_MLX_MODEL
from proxy.routers.auth import router as auth_router, seed_admin_key
from proxy.routers.artifacts import router as artifacts_router
from proxy.routers.bor import router as bor_router
from proxy.routers.diff import router as diff_router
from proxy.routers.filemap import router as filemap_router
from proxy.routers.tasks import notes_router, router as tasks_router
from proxy.routers.projects import router as projects_router
from proxy.routers.edges import router as edges_router
from proxy.routers.ontology import router as ontology_router
from proxy.routers.decisions import router as decisions_router
from proxy.routers.estimates import router as estimates_router
from proxy.routers.prices import router as prices_router
from proxy.routers.kac import router as kac_router
from proxy.routers.lsr import router as lsr_router
from proxy.routers.rim import router as rim_router
from proxy.routers.external_radar import router as external_radar_router
from proxy.routers.verify import router as verify_router
from proxy.routers.forms import router as forms_router
from proxy.routers.files import router as files_router
from proxy.routers.field import router as field_router
from proxy.routers.les_md import router as les_md_router
from proxy.routers.normcontrol import router as normcontrol_router
from proxy.routers.notebooks import router as notebooks_router
from proxy.routers.profiles import router as profiles_router
from proxy.routers.model_connections import router as model_connections_router
from proxy.routers.doc_review import router as doc_review_router
from proxy.routers.checklist_review import router as checklist_review_router
from proxy.routers.documents import router as documents_router
from proxy.routers.tools import router as tools_router
from proxy.routers.chat import ChatRouterState, ensure_chat_history_schema, router as chat_router, set_chat_state
from proxy.routers.chat_history import router as chat_history_router
from proxy.routers.datasets import DatasetRouterState, router as datasets_router, search_router, set_dataset_state
from proxy.routers.diagnostics import DiagnosticsRouterState, router as diagnostics_router, set_diagnostics_state
from proxy.routers.jobs import JobsRouterState, router as jobs_router, set_jobs_state
from proxy.routers.logs import LogsRouterState, router as logs_router, set_logs_state
from proxy.routers.mail import recover_outlook_spool, router as mail_router
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
from proxy.routers.rag_advanced import router as rag_advanced_router
from proxy.routers.updates import router as updates_router
from proxy.routers.service_sources import router as service_sources_router
from proxy.routers.speckle import cad_bim_router
from proxy.routers.status_page import StatusPageState, router as status_page_router, set_status_page_state
from proxy.routers.memory import router as memory_router
from proxy.services.job_service import JobService
from proxy.services.resource_governor import CHAT_MODE, PROFILE_CHAT
from proxy.services.memory_runtime_service import initialize_memory_runtime, shutdown_memory_runtime

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
    "model": os.getenv("LLM_MODEL", DEFAULT_LOCAL_MLX_MODEL),
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


mail_autosync = {"last_sync": 0.0, "last_count": 0, "runs": 0, "last_error": "", "enabled": False}


async def mail_imap_autosync_loop():
    """Poll every enabled IMAP account into that mailbox's private dataset.

    The env-driven single MAIL_Index importer remains a compatibility fallback
    only when the account registry is empty.
    """
    from backend.mail_ingest import fetch_imap_eml_files, imap_settings_from_env

    await asyncio.sleep(25)  # дать backend подняться
    while True:
        try:
            interval = int(os.getenv("MAIL_IMAP_POLL_SEC", "180") or "180")
        except ValueError:
            interval = 0
        mail_autosync["enabled"] = interval > 0
        if interval <= 0:
            await asyncio.sleep(300)  # выключен — перечитываем флаг раз в 5 мин
            continue
        try:
            from proxy.routers.datasets import get_dataset_state
            from proxy.services.mail_registry_service import get_mail_registry
            from proxy.services.mail_sync_service import settings_for_account, sync_imap_account

            state = get_dataset_state()
            registry = get_mail_registry()
            accounts = [
                account for account in registry.list_accounts()
                if account.get("enabled") and account.get("kind") == "imap"
            ]
            total = 0
            for account in accounts:
                settings = settings_for_account(account, registry.account_secret(account["id"]))
                fetched = await asyncio.to_thread(
                    sync_imap_account,
                    settings,
                    registry,
                    account_id=account["id"],
                    mode="incremental",
                    max_messages=200,
                )
                for item in fetched:
                    doc_id = await state.backend.upload_file(
                        account["dataset_id"], item.file.path, relative_path=item.file.relative_path
                    )
                    registry.mark_indexed(item.message_id, rag_doc_id=doc_id, status="registered")
                if fetched:
                    try:
                        result = None
                        for _batch in range(40):
                            result = await state.backend.parse_dataset(account["dataset_id"], limit=25)
                            if int(result.get("remaining_pending") or 0) <= 0 or int(result.get("errors") or 0) > 0:
                                break
                        if int(result.get("remaining_pending") or 0) == 0:
                            for item in fetched:
                                registry.mark_indexed(item.message_id, status="indexed")
                    except Exception as parse_err:  # noqa: BLE001
                        logger.warning("[ЕЖИК] autosync parse account=%s: %s", account["id"], parse_err)
                total += len(fetched)

            if not accounts:
                settings = imap_settings_from_env()
                if getattr(settings, "configured", False):
                    from proxy.routers.mail import _upload_fetched_mail

                    fetched = await asyncio.to_thread(fetch_imap_eml_files, settings, max_messages=200)
                    if fetched:
                        dataset_id, _created, _uploaded = await _upload_fetched_mail(state, fetched)
                        await state.backend.parse_dataset(dataset_id, limit=25)
                    total = len(fetched)
            mail_autosync.update(
                last_sync=time.time(), last_count=total,
                runs=mail_autosync["runs"] + 1, last_error="",
            )
            if total:
                logger.info("[ЕЖИК] IMAP autosync: +%s писем across %s accounts", total, len(accounts))
        except Exception as error:  # noqa: BLE001 — поллер не падает
            mail_autosync["last_error"] = str(error)[:200]
            logger.warning("[ЕЖИК] IMAP autosync failed: %s", error)
        await asyncio.sleep(max(60, interval))


async def metrics_collector_loop():
    while True:
        try:
            cpu = await asyncio.to_thread(psutil.cpu_percent, interval=None)
            vm = await asyncio.to_thread(psutil.virtual_memory)
            files = await asyncio.to_thread(_get_db_files)

            host_mem = {}
            try:
                provider = os.getenv("LES_LLM_PROVIDER", "mlx").strip().lower() or "mlx"
                if provider == "mlx":
                    mlx_url = os.getenv("MLX_URL", "http://127.0.0.1:8080")
                    async with httpx.AsyncClient(
                        trust_env=trust_env_for_url(mlx_url),
                        timeout=2.0,
                    ) as client:
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
    await initialize_memory_runtime(llm_semaphore)
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
        import torch
        max_threads = max(1, (os.cpu_count() or 4) // 2)
        torch.set_num_threads(max_threads)
        logger.info("[INIT] PyTorch threads capped at %s to prevent CPU fan noise", max_threads)
    except Exception:
        pass

    try:
        default_mlx_url = "http://127.0.0.1:11434" if sys.platform == "win32" or os.getenv("EMBED_BACKEND") == "ollama" else "http://127.0.0.1:8080"
        rag_backend = QdrantLlamaIndexAdapter(
            qdrant_url=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"),
            mlx_url=os.getenv("MLX_URL", default_mlx_url),
            embed_model_name=embedding_api_model(),
        )
        await rag_backend.health()
        logger.info("[INIT] Backend initialized successfully")
        asyncio.create_task(metrics_collector_loop())
        asyncio.create_task(metrics_loop())
        asyncio.create_task(mail_imap_autosync_loop())  # Е.Ж.И.К.: внутренний IMAP-сервис (MAIL_IMAP_POLL_SEC)
        recovered_outlook = recover_outlook_spool()
        if recovered_outlook:
            logger.info("[INIT] Resumed %s durable Outlook spool item(s)", recovered_outlook)
        asyncio.create_task(_warmup_models())  # №2: убрать холодный старт первого запроса
        asyncio.create_task(_catalog_self_heal())
        asyncio.create_task(_parse_resume_supervisor())
        asyncio.create_task(_raptor_resume_supervisor())
    except Exception as e:
        logger.error("[INIT] Backend initialization failed: %s", e)
        raise


async def _catalog_self_heal():
    """One bounded additive recovery pass after Qdrant startup."""
    await asyncio.sleep(2)
    from proxy.services.rag_catalog_guard_service import run_catalog_guard

    result = await run_catalog_guard(
        qdrant_url=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"),
        collection=rag_backend.collection_name,
        meta_db_path=rag_meta_db_path(),
        apply=os.getenv("LES_RAG_CATALOG_SELF_HEAL", "true").lower() in {"1", "true", "yes", "on"},
    )
    navigation_counts = None
    if result.get("status") != "blocked":
        navigation_counts = await asyncio.to_thread(
            rag_backend.reconcile_legacy_navigation_counts,
            apply=True,
        )
        result["navigation_count_reconcile"] = navigation_counts
    if result.get("status") == "blocked":
        logger.error(
            "[CATALOG_GUARD] code=%s phase=%s type=%s message=%s",
            result.get("error_code"),
            result.get("phase"),
            result.get("exception_type"),
            result.get("message"),
        )
    else:
        logger.info("[CATALOG_GUARD] %s", result)


async def _parse_resume_supervisor():
    """Durable SQLite-backed resume for interrupted and bounded-retry work."""
    await asyncio.sleep(6)
    while True:
        try:
            recovered = await asyncio.to_thread(rag_backend.db.recover_interrupted_parsing)
            if recovered:
                logger.info("[PARSE_RESUME] requeued=%s", recovered)
            from proxy.routers.datasets import active_parse_scheduler_job, get_dataset_state

            state = get_dataset_state()
            if active_parse_scheduler_job(state) is None:
                with sqlite3.connect(rag_meta_db_path()) as conn:
                    pending = int(
                        conn.execute(
                            "SELECT COUNT(*) FROM documents WHERE upper(status)='PENDING'"
                        ).fetchone()[0]
                        or 0
                    )
                if pending:
                    await _auto_resume_pending_parse()
        except Exception as exc:
            logger.error(
                "[PARSE_RESUME] code=PARSE_RESUME_SUPERVISOR_FAILED type=%s message=%s",
                type(exc).__name__,
                str(exc) or type(exc).__name__,
            )
        await asyncio.sleep(max(10.0, float(os.getenv("RAG_PARSE_RESUME_POLL_SEC", "30"))))


async def _raptor_resume_supervisor():
    """Resume interrupted RAPTOR work and refresh a previously ready tree."""
    await asyncio.sleep(15)
    while True:
        try:
            from proxy.services.raptor_publication_service import (
                raptor_auto_action_needed,
                run_raptor_publication,
            )

            needed = await asyncio.to_thread(raptor_auto_action_needed, rag_backend)
            if needed:
                await asyncio.to_thread(run_raptor_publication, rag_backend)
            from proxy.services.colbert_generation_service import (
                colbert_auto_resume_needed,
                run_colbert_generation,
            )

            if colbert_auto_resume_needed():
                await asyncio.to_thread(run_colbert_generation, rag_backend)
        except RuntimeError as error:
            if "RAPTOR_BUILD_ALREADY_RUNNING" not in str(error):
                logger.error(
                    "[RAPTOR_RESUME] code=RAPTOR_RESUME_FAILED type=%s message=%s",
                    type(error).__name__,
                    str(error) or type(error).__name__,
                )
        except Exception as error:
            logger.error(
                "[RAPTOR_RESUME] code=RAPTOR_RESUME_FAILED type=%s message=%s",
                type(error).__name__,
                str(error) or type(error).__name__,
            )
        await asyncio.sleep(60)


async def _auto_resume_pending_parse():
    """Автоматическое возобновление индексации ожидающих документов при запуске серверов."""
    await asyncio.sleep(6)  # Дать бэкенду и Qdrant завершить стартовые задачи
    try:
        db_path = rag_meta_db_path()
        conn = sqlite3.connect(db_path)
        pending_count = int(conn.execute("SELECT COUNT(*) FROM documents WHERE upper(status) = 'PENDING'").fetchone()[0] or 0)
        conn.close()
        if pending_count > 0:
            logger.info("[INIT] Авто-возобновление индексации для %s ожидающих файлов...", pending_count)
            from proxy.routers.datasets import ParseSchedulerRequest, get_dataset_state, run_parse_scheduler
            state = get_dataset_state()
            req = ParseSchedulerRequest(
                batch_limit=1,
                max_batches=10000,
                cooldown_sec=2.0,
                background=True,
                min_free_gb=2.5,
                unload_before_start=False,
                unload_between_batches=False,
                warm_embedder=True,
                unload_after_finish=False,
            )
            job = state.job_service.create(
                "rag_parse_scheduler",
                source="auto_resume",
                status="running",
                message=f"Auto-resumed indexing for {pending_count} pending files",
                total=pending_count,
            )
            job_id = job["id"]
            state.job_tracker[job_id] = {
                "type": "rag_parse_scheduler",
                "status": "QUEUED",
                "total": req.max_batches,
                "processed": 0,
                "started_at": job["started_at"],
                "message": f"Auto-resumed indexing for {pending_count} pending files",
            }

            async def _run():
                try:
                    await run_parse_scheduler(state, req, job_id=job_id)
                    # Остаток подхватит постоянный supervisor. Отдельную рекурсивную
                    # задачу не создаём: это исключает два параллельных scheduler job.
                    conn_check = sqlite3.connect(db_path)
                    rem = int(conn_check.execute("SELECT COUNT(*) FROM documents WHERE upper(status) = 'PENDING'").fetchone()[0] or 0)
                    conn_check.close()
                    if rem > 0:
                        logger.info("[AUTO_RESUME_PARSE] remaining=%s; supervisor will continue", rem)
                except Exception as err:
                    logger.error("[AUTO_RESUME_PARSE %s] Error: %s", job_id, err, exc_info=True)

            asyncio.create_task(_run())
    except Exception as exc:
        logger.warning("[INIT] Auto-resume parse check failed: %s", exc)

async def _warmup_reranker() -> bool:
    from proxy.services.retrieval_service import required_reranker_policy

    enabled, _trace = required_reranker_policy()
    if not enabled:
        logger.info("[WARMUP] production reranker disabled by runtime policy")
        return False
    reranker_cls = _select_reranker_cls()
    mlx = os.getenv("MLX_URL", "http://127.0.0.1:8080")
    reranker = reranker_cls(mlx_url=mlx, mode="batch")
    ranked = await reranker.rerank(
        "прогрев",
        [
            {"text": "прогрев первый документ", "score": 1.0, "metadata": {}},
            {"text": "прогрев второй документ", "score": 0.5, "metadata": {}},
        ],
        top_k=1,
    )
    if not ranked:
        raise RuntimeError("reranker warmup returned no ranked fragments")
    logger.info("[WARMUP] production reranker %s прогрет", reranker_cls.__name__)
    return True


async def _warmup_models():
    """№2 латентность: прогрев эмбеддера и фактического production-реранкера.

    Первый запрос лениво грузил обе модели → 25-30с. Фоном, не блокирует старт."""

    await asyncio.sleep(3)  # дать бэкенду/MLX-хосту подняться
    try:
        from proxy.services.retrieval_service import hybrid_backend

        retrieve = (
            rag_backend.retrieve_native_hybrid
            if hybrid_backend() == "qdrant_native"
            and hasattr(rag_backend, "retrieve_native_hybrid")
            else rag_backend.retrieve
        )
        await retrieve("прогрев системы при запуске", dataset_ids=None, top_k=2)
        logger.info("[WARMUP] dense+sparse RRF прогрет")
    except Exception as exc:
        logger.warning("[WARMUP] embed: %s", exc)
    try:
        await _warmup_reranker()
    except Exception as exc:
        logger.warning("[WARMUP] rerank: %s", exc)
    try:
        # Прогрев основной LLM: грузит main-движок на старте, иначе первый реальный
        # запрос после рестарта платил холодную загрузку модели (~100-120с).
        import httpx

        mlx = os.getenv("MLX_URL", "http://127.0.0.1:8080")
        model = os.getenv("LLM_MODEL", DEFAULT_LOCAL_MLX_MODEL)
        async with httpx.AsyncClient(
            trust_env=trust_env_for_url(mlx),
            timeout=180,
        ) as client:
            await client.post(
                f"{mlx}/v1/chat/completions",
                json={"model": model, "messages": [{"role": "user", "content": "прогрев"}], "max_tokens": 1},
            )
        logger.info("[WARMUP] LLM прогрета")
    except Exception as exc:
        logger.warning("[WARMUP] llm: %s", exc)


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
    fastapi_app.include_router(artifacts_router)
    fastapi_app.include_router(bor_router)
    fastapi_app.include_router(diff_router)
    fastapi_app.include_router(filemap_router)
    fastapi_app.include_router(tasks_router)
    fastapi_app.include_router(projects_router)
    fastapi_app.include_router(edges_router)
    fastapi_app.include_router(ontology_router)
    fastapi_app.include_router(decisions_router)
    fastapi_app.include_router(estimates_router)
    fastapi_app.include_router(prices_router)
    fastapi_app.include_router(kac_router)
    fastapi_app.include_router(lsr_router)
    fastapi_app.include_router(rim_router)
    fastapi_app.include_router(external_radar_router)
    fastapi_app.include_router(verify_router)
    fastapi_app.include_router(forms_router)
    fastapi_app.include_router(files_router)
    fastapi_app.include_router(notes_router)
    fastapi_app.include_router(field_router)
    fastapi_app.include_router(les_md_router)
    fastapi_app.include_router(normcontrol_router)
    fastapi_app.include_router(notebooks_router)
    fastapi_app.include_router(profiles_router)
    fastapi_app.include_router(model_connections_router)
    fastapi_app.include_router(doc_review_router)
    fastapi_app.include_router(checklist_review_router)
    fastapi_app.include_router(documents_router)
    fastapi_app.include_router(tools_router)
    fastapi_app.include_router(service_sources_router)
    fastapi_app.include_router(settings_router)
    fastapi_app.include_router(rag_advanced_router)
    fastapi_app.include_router(updates_router)
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
    fastapi_app.include_router(memory_router)
    fastapi_app.on_event("startup")(startup)
    fastapi_app.on_event("shutdown")(shutdown_memory_runtime)
    fastapi_app.middleware("http")(track_errors)
    _app = fastapi_app
    return _app


app = create_app()
