"""SafeRAG chat route."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import sqlite3
import time
import json
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Callable, Iterable, List, Optional
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, field_validator

from backend.rag_config import rag_meta_db_path
from proxy.config import ENV_PATH
from proxy.security import require_user
from proxy.services.answer_form_service import classify_answer_form
from proxy.services.chat_evidence_application_service import (
    EvidenceRequestContext,
    EvidenceRuntimeDeps,
    ResponseBoundary,
    run_chat_evidence_application,
)
from proxy.services.answer_contract_service import decorate_payload, scenario_for_request
from proxy.services.class_router_service import build_class_suggestions
from proxy.services.chat_provider_session_service import ChatProviderConfig
from proxy.services.canonical_route_service import (
    BoundModelChatRunner,
    CanonicalRouteMode,
    resolve_canonical_route,
)
from proxy.services.model_connection_registry_service import ModelConnectionRegistry
from proxy.services.model_connection_resolver_service import ModelConnectionResolver
from proxy.services.model_secret_service import EnvironmentSecretStore
from proxy.services.openai_compatible_transport_service import (
    InferenceRequest,
    InferenceResponse,
    OpenAICompatibleTransport,
)
from backend.inference.validator import rules_pre_verdict
from backend.inference.routing import (
    decide_provider,
    estimate_cost_usd,
    is_cloud_provider,
    load_price_table_from_env,
    memory_aware_provider,
)
from proxy.services.cad_bim_highlight import extract_highlight, set_highlight
from proxy.services.clause_lookup_service import maybe_answer_clause_lookup
from proxy.services.context_expander_service import expand_context_windows
from proxy.services.context_memory_service import build_context_memory_block, update_chat_profile
from proxy.services.evidence_packet_service import (
    build_retrieval_evidence_packet,
    render_retrieval_evidence_for_model,
)
from proxy.services.memory_service import (
    session_memory, session_recent_retrieval_traces, session_user_questions)
from proxy.services.kot_service import analyze_question
from proxy.services.lexical_index_service import retrieval_fingerprint
from proxy.local_model_registry import DEFAULT_LOCAL_MLX_MODEL
from proxy.services.notebook_study_service import (
    build_notebook_study_pack,
    format_study_artifact,
    is_notebook_study_query,
    prompt_block as notebook_study_prompt_block,
)
from proxy.services.dataset_memory_service import (
    get_typed_dataset_memory,
    run_dataset_reader_pass,
    schedule_dataset_reader_pass,
    select_topic_retrieval_plan,
)
from proxy.services.estimate_math_service import parse_ru_number, quantity_sum_audit
from proxy.services.notebook_service import dataset_memory_prompt_excerpt
from proxy.services.project_summary_service import (
    build_project_summary,
    format_project_inventory_context,
    format_project_inventory_prompt,
    is_project_inventory_query,
    resolve_inventory_file_reference,
)
from proxy.services.prompt_registry_service import build_mode_system_prompt
from proxy.services.llm_transport_profile_service import (
    apply_transport_options,
    assistant_delta_text,
    provider_prompt_max_chars,
    provider_is_local,
)
from proxy.services.query_router import route_query
from proxy.services.retrieval_service import resolve_dataset_ids, retrieve_chat_chunks
from proxy.services.runtime_admission import count_active_jobs, evaluate_chat_admission, generation_semaphore
from proxy.services.runtime_dispatcher import RuntimeDispatcher
from proxy.services.smeta_artifact_service import (
    build_norm_candidate_artifact_from_lookup,
)
from proxy.services.smeta_chat_application_service import (
    SMETA_ARTIFACT_DIR as _SMETA_ARTIFACT_DIR,
    retry_smeta_transport as _retry_smeta_transport,
)
from proxy.smeta_core.document_workflow import finalize_locked_mapping_revision
from proxy.smeta_core.professional_review import create_user_lock_revision
from proxy.smeta_core.revision_store import DEFAULT_ROOT as SMETA_REVISION_ROOT
from proxy.services.smeta_chat_adapter_service import (
    _smeta_model_runtime,
    _smeta_request_needs_lsr_output,
)
from proxy.services.saferag_service import (
    SAFE_FALLBACK,
    build_context,
    build_validation_context,
    concentrate_sources,
    rank_chunks_for_question,
    source_map_for_context,
    source_names,
)
from proxy.services.semantic_cache import (
    SemanticCache,
    dataset_scope_key,
    embed_question,
    semantic_cache_enabled,
    semantic_cache_threshold,
)
from proxy.services.table_query_service import maybe_answer_table_query, parquet_ref_chunks_for_datasets

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])
DEFAULT_OPENAI_MODEL = "gpt-5.4"
_REQUEST_LLM_RUNTIME: ContextVar[Any | None] = ContextVar("request_llm_runtime", default=None)
_REQUEST_CLOUD_CONSENT: ContextVar[bool | None] = ContextVar("request_cloud_consent", default=None)
_XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/commands")
async def list_chat_commands(_user=Depends(require_user)):
    """Палитра /-команд для GUI (команда + ярлык + описание). W11.17."""
    from proxy.services.command_service import list_commands
    return {"commands": list_commands()}


@router.get("/smeta-artifacts/download")
async def smeta_artifact_download(path: str = Query(...), _user=Depends(require_user)):
    out_dir = _SMETA_ARTIFACT_DIR.resolve()
    target = (out_dir / Path(path).name).resolve()
    if out_dir not in target.parents or not target.is_file():
        raise HTTPException(404, "Файл не найден")
    media = _XLSX_MEDIA if target.suffix.lower() == ".xlsx" else "text/csv; charset=utf-8"
    return FileResponse(target, media_type=media, filename=target.name)


class SmetaMappingLockRequest(BaseModel):
    review_note: str
    accepted_conflict_ids: List[str] = []

    @field_validator("review_note")
    @classmethod
    def review_note_required(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("Нужно указать результат пользовательской проверки")
        if len(cleaned) > 1000:
            raise ValueError("Комментарий проверки слишком длинный")
        return cleaned


@router.post("/smeta-mappings/{revision_id}/lock")
async def lock_smeta_mapping(
    revision_id: str,
    req: SmetaMappingLockRequest,
    user=Depends(require_user),
):
    """Lock a reviewed mapping and calculate a separate user-owned revision."""

    try:
        locked = create_user_lock_revision(
            revision_id,
            root=SMETA_REVISION_ROOT,
            reviewed_by=str(user.holder or user.role),
            review_note=req.review_note,
            accepted_conflict_ids=tuple(req.accepted_conflict_ids),
        )
        token = uuid4().hex
        _SMETA_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        xlsx_path = _SMETA_ARTIFACT_DIR / f"lsr_locked_{token}.xlsx"
        report_path = _SMETA_ARTIFACT_DIR / f"lsr_locked_{token}.json"
        workflow = await asyncio.to_thread(
            finalize_locked_mapping_revision,
            locked,
            out_xlsx=xlsx_path,
            out_report=report_path,
            revision_root=SMETA_REVISION_ROOT,
        )
        # Explicit user lock is the external feedback signal for episodic
        # Memory.  It promotes an already captured project trace; Memory off or
        # a missing trace remains a fail-open no-op.
        try:
            from proxy.services.memory_port import get_memory_port

            get_memory_port().confirm_smeta_revision(
                revision_id,
                locked.revision_id,
                req.review_note,
            )
        except Exception as memory_error:
            logger.warning("[MEMORY] smeta lock feedback skipped: %s", memory_error)
    except FileNotFoundError as error:
        raise HTTPException(404, "Mapping-ревизия не найдена") from error
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    summary = (workflow.get("lsr") or {}).get("summary") or {}
    return {
        "status": "mapping_locked",
        "mapping_revision_id": locked.revision_id,
        "calculation_status": summary.get("result_status"),
        "summary": summary,
        "artifact": {
            "title": "Проверенная ЛСР",
            "downloads": {
                "xlsx": f"/api/smeta-artifacts/download?path={xlsx_path.name}",
            },
        },
    }


class ChatRequest(BaseModel):
    question: str
    dataset_ids: Optional[List[str]] = None
    dataset_filter: Optional[str] = None
    # Legacy-compatible input only. Production RAG always follows the mandatory
    # runtime reranker policy and ignores client attempts to disable it.
    reranker_enabled: Optional[bool] = None
    semantic_cache_enabled: Optional[bool] = None
    validation_enabled: Optional[bool] = None
    session_id: Optional[str] = None
    project_id: Optional[int] = None  # W17.1: режим проекта — ретрив сужается к датасетам объекта
    scope: Optional[dict] = None  # v0.21: нормализованная область поиска {scope_type, project_ids, dataset_ids}
    output_directive: Optional[str] = None  # формат/стиль ответа — ТОЛЬКО в генерацию (не в роутинг/заметки/ретрив)
    response_length: Optional[str] = None  # short|standard|detailed|maximum; только бюджет/форма генерации
    mode: Optional[str] = None  # явный РЕЖИМ из UI («smeta» → форс сметного пути минуя роутер/RAG)
    profile_revision_id: Optional[str] = None
    apply_profile_revision: bool = False
    attachment_context: Optional[str] = None  # текст файла из скрепки (read-mode), без индексации
    attachment_id: Optional[str] = None  # server-owned read_<id>; клиентский путь не принимается
    target_file: Optional[str] = None  # точный file_name из MetaDB documents (для клика по реестру/узкого RAG)
    target_files: Optional[List[str]] = None  # явный выбор нескольких документов оператором
    provider_config: Optional[ChatProviderConfig] = None  # per-session BYOK, без изменения общего .env

    @field_validator("question")
    @classmethod
    def question_limits(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("Пустой вопрос")
        # Сметные исходники часто приходят как pasted ВОР/спецификация, а не как
        # отдельный attachment_context. 4k ломал живой сценарий "спецификация -> ВОР".
        if len(v) > 20000:
            raise ValueError(f"Вопрос слишком длинный ({len(v)} симв., макс. 20000)")
        return v

    @field_validator("attachment_context")
    @classmethod
    def attachment_context_limits(cls, v):
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        if len(v) > 20000:
            raise ValueError(f"Контекст вложения слишком длинный ({len(v)} симв., макс. 20000)")
        return v

    @field_validator("attachment_id")
    @classmethod
    def attachment_id_limits(cls, v):
        if v is None:
            return None
        value = v.strip().lower()
        if not re.fullmatch(r"read_[0-9a-f]{12}", value):
            raise ValueError("Некорректный идентификатор вложения")
        return value

    @field_validator("target_file")
    @classmethod
    def target_file_limits(cls, v):
        if v is None:
            return None
        v = v.strip().replace("\\", "/")
        if not v:
            return None
        if len(v) > 1000:
            raise ValueError(f"Имя целевого файла слишком длинное ({len(v)} симв., макс. 1000)")
        return v

    @field_validator("response_length")
    @classmethod
    def response_length_values(cls, v):
        if v is None:
            return None
        value = v.strip().casefold()
        if value not in {"short", "standard", "detailed", "maximum"}:
            raise ValueError("Некорректная длина ответа")
        return value

    @field_validator("target_files")
    @classmethod
    def target_files_limits(cls, values):
        if values is None:
            return None
        result: list[str] = []
        for raw in values:
            value = str(raw or "").strip().replace("\\", "/")
            if not value or value in result:
                continue
            if len(value) > 1000:
                raise ValueError("Имя выбранного документа слишком длинное")
            result.append(value)
        return result or None


@dataclass
class ChatRouterState:
    rag_backend: Any
    llm_semaphore: Any
    crag_stats: dict
    chat_metrics: dict
    reranker_available: bool
    reranker_cls: Any
    current_mode: dict[str, Any] | None = None
    metrics_cache: dict[str, Any] | None = None
    job_service: Any = None
    job_tracker: dict[str, Any] | None = None

    @property
    def backend(self):
        return self.rag_backend() if callable(self.rag_backend) else self.rag_backend


_state: ChatRouterState | None = None


def set_chat_state(state: ChatRouterState) -> None:
    global _state
    _state = state


def get_chat_state() -> ChatRouterState:
    if _state is None:
        raise RuntimeError("chat router state is not configured")
    return _state


def _active_dispatcher_reindex_jobs(state: ChatRouterState) -> int:
    try:
        status = RuntimeDispatcher(
            current_mode=state.current_mode or {},
            metrics_cache=state.metrics_cache or {},
        ).reindex_status_payload()
    except Exception:
        return 0
    return 1 if status.get("running") else 0


def chat_validation_enabled() -> bool:
    return os.getenv("CHAT_VALIDATION_ENABLED", "true").lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    if name == "LES_CLOUD_CONSENT":
        request_consent = _REQUEST_CLOUD_CONSENT.get()
        if request_consent is not None:
            return request_consent
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


_SMETA_ROW_UNITS_RE = re.compile(
    r"^(?:"
    r"м|м2|м²|м3|м³|мм|см|км|шт\.?|компл\.?|комплект|ед\.?|"
    r"т|кг|100\s*м|100\s*м2|100\s*м²|100\s*шт|100\s*отверстий"
    r")$",
    re.IGNORECASE,
)








@dataclass(frozen=True)
class LlmRuntime:
    provider: str
    base_url: str
    chat_url: str
    model: str
    api_key: str
    supports_validation: bool
    requires_cache_alignment: bool = False
    uses_native_chat: bool = False


def _join_openai_path(base_url: str, path: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1") or base.endswith("/api/v1"):
        return f"{base}{path}"
    return f"{base}/v1{path}"


def _is_local_llm_url(base_url: str) -> bool:
    low = (base_url or "").strip().lower()
    return (
        low.startswith("http://127.")
        or low.startswith("http://localhost")
        or low.startswith("http://[::1]")
        or low.startswith("http://0.0.0.0")
    )


def _model_needs_completion_tokens(model: str) -> bool:
    """GPT-5.x и reasoning o-серия (o1/o3/o4) требуют `max_completion_tokens`
    вместо `max_tokens` — иначе OpenAI/proxyapi отвечает 400."""
    m = (model or "").strip().lower().rsplit("/", 1)[-1]
    return m.startswith("gpt-5") or (len(m) >= 2 and m[0] == "o" and m[1].isdigit())


def _cloud_body_for_model(body: dict, model: str, provider: str) -> dict:
    """Облако: для GPT-5/o-моделей переименовать max_tokens→max_completion_tokens
    (один точечный фикс совместимости; для остальных тело без изменений)."""
    normalized = body
    if (is_cloud_provider(provider) and "max_tokens" in body
            and _model_needs_completion_tokens(model)):
        normalized = dict(body)
        normalized["max_completion_tokens"] = normalized.pop("max_tokens")
    return apply_transport_options(normalized, provider)


def _llm_runtime() -> LlmRuntime:
    request_runtime = _REQUEST_LLM_RUNTIME.get()
    if request_runtime is not None:
        return request_runtime
    provider = os.getenv("LES_LLM_PROVIDER", "mlx").strip().lower() or "mlx"
    if provider == "freetoken":
        base_url = os.getenv("FREETOKEN_BASE_URL", "http://127.0.0.1:1919/v1").strip()
        model = os.getenv("FREETOKEN_MODEL", "").strip() or os.getenv("LLM_MODEL", "")
        api_key = os.getenv("FREETOKEN_API_KEY", "").strip()
        return LlmRuntime(
            provider,
            base_url,
            _join_openai_path(base_url, "/chat/completions"),
            model,
            api_key,
            False,
            requires_cache_alignment=True,
        )
    if provider == "openrouter":
        base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").strip()
        model = os.getenv("OPENROUTER_MODEL", "").strip() or os.getenv("LLM_MODEL", "")
        api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if not api_key and not _is_local_llm_url(base_url):
            return _mlx_runtime()
        return LlmRuntime(provider, base_url, _join_openai_path(base_url, "/chat/completions"), model, api_key, False)
    if provider in {"openai", "openai-compatible", "openai_compatible"}:
        base_url = os.getenv("OPENAI_BASE_URL", "").strip() or "https://api.openai.com/v1"
        model = os.getenv("OPENAI_MODEL", "").strip() or os.getenv("LES_DEFAULT_OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key and not _is_local_llm_url(base_url):
            return _mlx_runtime()
        return LlmRuntime(provider, base_url, _join_openai_path(base_url, "/chat/completions"), model, api_key, False)
    if provider == "ollama":
        base_url = os.getenv("OLLAMA_BASE_URL", os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")).strip()
        model = os.getenv("OLLAMA_MODEL", "").strip() or os.getenv("LLM_MODEL", "")
        api_key = os.getenv("OLLAMA_API_KEY", "").strip()
        return LlmRuntime(
            provider,
            base_url,
            _join_openai_path(base_url, "/chat/completions"),
            model,
            api_key,
            False,
            uses_native_chat=True,
        )
    if provider == "lemonade":
        base_url = os.getenv("LEMONADE_BASE_URL", "http://127.0.0.1:13305/api/v1").strip()
        model = os.getenv("LEMONADE_MODEL", "").strip() or os.getenv("LLM_MODEL", "")
        api_key = os.getenv("LEMONADE_API_KEY", "lemonade").strip()
        return LlmRuntime(provider, base_url, _join_openai_path(base_url, "/chat/completions"), model, api_key, False)

    return _mlx_runtime()


def _mlx_runtime() -> LlmRuntime:
    """Локальный MLX-провайдер — он же fallback политики маршрутизации (W3.3)."""
    base_url = os.getenv("MLX_URL", "http://127.0.0.1:8080").strip()
    model = (
        os.getenv("LLM_MODEL", "").strip()
        or os.getenv("MLX_MODEL", "").strip()
        or DEFAULT_LOCAL_MLX_MODEL
    )
    return LlmRuntime("mlx", base_url, _join_openai_path(base_url, "/chat/completions"), model, "", True)


def _runtime_from_provider_config(config: ChatProviderConfig) -> LlmRuntime:
    if config.provider == "mlx":
        return _mlx_runtime()
    if config.provider == "openrouter":
        base_url = "https://openrouter.ai/api/v1"
    else:
        base_url = "https://api.openai.com/v1"
    return LlmRuntime(
        config.provider,
        base_url,
        _join_openai_path(base_url, "/chat/completions"),
        config.model,
        config.api_key,
        False,
    )


async def _run_chat_with_provider(req: ChatRequest, token_sink=None):
    """Bind a provider to this asyncio context only, then reliably remove it."""
    if req.provider_config is None:
        if token_sink is None:
            return await _run_chat(req)
        return await _run_chat(req, token_sink=token_sink)
    if os.getenv("LES_DEMO_PROVIDER_OVERRIDE_ENABLED", "false").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        raise HTTPException(409, "SESSION_PROVIDER_OVERRIDE_DISABLED")
    runtime = _runtime_from_provider_config(req.provider_config)
    runtime_token = _REQUEST_LLM_RUNTIME.set(runtime)
    consent_token = _REQUEST_CLOUD_CONSENT.set(is_cloud_provider(runtime.provider))
    try:
        if token_sink is None:
            return await _run_chat(req)
        return await _run_chat(req, token_sink=token_sink)
    finally:
        _REQUEST_CLOUD_CONSENT.reset(consent_token)
        _REQUEST_LLM_RUNTIME.reset(runtime_token)


def _idempotency_payload(req: ChatRequest) -> dict[str, Any]:
    """Fingerprint provider selection without retaining the plaintext API key."""
    payload = req.model_dump(mode="json")
    provider_config = payload.get("provider_config")
    if isinstance(provider_config, dict):
        secret = str(provider_config.pop("api_key", ""))
        provider_config["api_key_sha256"] = hashlib.sha256(secret.encode("utf-8")).hexdigest() if secret else ""
    return payload




def cloud_fallback_models(runtime: LlmRuntime) -> list[str]:
    """Цепочка моделей облачного фолбэка: primary (`*_MODEL`) первым, затем
    `OPENROUTER_MODELS`/`OPENAI_MODELS` (через запятую). Зависшая/ошибившаяся
    модель → следующая (см. cloud_model_timeout). Не-облако → одна модель."""
    if _REQUEST_LLM_RUNTIME.get() is not None:
        return [runtime.model]
    if runtime.provider == "openrouter":
        env = os.getenv("OPENROUTER_MODELS", "")
    elif runtime.provider in ("openai", "openai-compatible"):
        env = os.getenv("OPENAI_MODELS", "")
    else:
        return [runtime.model]
    chain: list[str] = [runtime.model] if runtime.model else []
    for m in env.split(","):
        m = m.strip()
        if m and m not in chain:
            chain.append(m)
    return chain or [runtime.model]


def cloud_model_timeout() -> float:
    """Конечный таймаут на одну облачную модель — зависший провайдер не держит
    запрос 300с, а быстро уступает следующей модели / локальному MLX."""
    return _env_float("LES_CLOUD_MODEL_TIMEOUT_SEC", 45.0)


def _effective_model_connection_mode() -> CanonicalRouteMode:
    return resolve_canonical_route(receipt=None).effective


def _bound_model_chat_runner(client: httpx.AsyncClient) -> BoundModelChatRunner:
    resolver, secret_store = _model_connection_resolver()
    return BoundModelChatRunner(
        resolver=resolver,
        transport=OpenAICompatibleTransport(
            client=client,
            secret_store=secret_store,
        ),
    )


def _model_connection_resolver() -> tuple[ModelConnectionResolver, EnvironmentSecretStore]:
    secret_store = EnvironmentSecretStore(ENV_PATH)
    return ModelConnectionResolver(
        registry=ModelConnectionRegistry(),
        secret_store=secret_store,
    ), secret_store


_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]+")


def clean_visible_text(text: str) -> str:
    """Remove CJK garbage from visible Russian/Latin operator output."""
    cleaned = _CJK_RE.sub("", str(text or ""))
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def source_excerpts(chunks, *, max_n: int = 6, max_chars: int = 700) -> list[dict[str, Any]]:
    """Конкретные фрагменты источников (текст, а не только имя файла) — чтобы
    показать «вот это место в норме» под ответом. Дедуп по (документ, начало)."""
    out: list[dict[str, Any]] = []
    seen: set = set()
    for ch in chunks or []:
        content = clean_visible_text((getattr(ch, "content", "") or "").strip())
        if not content:
            continue
        doc = getattr(ch, "doc_name", "") or ""
        key = (doc, content[:80])
        if key in seen:
            continue
        seen.add(key)
        if len(content) > max_chars:
            content = content[:max_chars].rsplit(" ", 1)[0].rstrip() + " …"
        meta = getattr(ch, "meta", {}) or {}
        out.append({
            "doc": doc,
            "text": content,
            "score": round(float(getattr(ch, "score", 0.0) or 0.0), 3),
            "dataset_id": meta.get("dataset_id", "") if isinstance(meta, dict) else "",
        })
        if len(out) >= max_n:
            break
    return out


def _extract_json_object(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, flags=re.DOTALL | re.IGNORECASE)
    if fence:
        raw = fence.group(1).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(raw[start:end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _parse_model_tool_calls(text: str, *, allowed_tools: set[str], max_calls: int = 3) -> list[dict[str, Any]]:
    parsed = _extract_json_object(text)
    if not parsed:
        return []
    calls_raw = parsed.get("calls")
    if isinstance(calls_raw, dict):
        calls_raw = [calls_raw]
    if not isinstance(calls_raw, list):
        return []
    calls: list[dict[str, Any]] = []
    for item in calls_raw:
        if not isinstance(item, dict):
            continue
        tool = str(item.get("tool") or item.get("name") or "").strip()
        if tool not in allowed_tools:
            continue
        args = item.get("args") if isinstance(item.get("args"), dict) else {}
        parsed_call = {"tool": tool, "args": dict(args)}
        call_id = str(item.get("call_id") or item.get("id") or "")
        if call_id:
            parsed_call["call_id"] = call_id
        calls.append(parsed_call)
        if len(calls) >= max(1, max_calls):
            break
    return calls


def _augment_model_tool_args(
    call: dict[str, Any],
    *,
    question: str,
    dataset_ids: list[str],
    target_file_ref: dict[str, Any] | None,
) -> dict[str, Any]:
    tool = str(call.get("tool") or "")
    args = dict(call.get("args") or {})
    if tool == "dataset_map" and dataset_ids and not args.get("dataset_id"):
        args["dataset_id"] = dataset_ids[0]
    if tool in {"search_sources", "read_source", "read_pdf_source", "read_excel_source", "look_at_pdf_page"}:
        if question and not (args.get("q") or args.get("question")):
            args["question" if tool == "look_at_pdf_page" else "q"] = question
        if dataset_ids:
            if tool == "search_sources" and not args.get("dataset_ids") and not args.get("dataset_id"):
                args["dataset_ids"] = dataset_ids
            elif tool != "search_sources" and not args.get("dataset_id") and not args.get("doc_id"):
                args["dataset_id"] = dataset_ids[0]
        if target_file_ref and target_file_ref.get("match_status") == "matched":
            if not args.get("doc_id") and not args.get("doc_name"):
                args["doc_name"] = target_file_ref.get("file_name") or ""
            if not args.get("doc_id") and target_file_ref.get("dataset_id"):
                args["dataset_id"] = target_file_ref.get("dataset_id")
    augmented = {"tool": tool, "args": args}
    if call.get("call_id"):
        augmented["call_id"] = str(call["call_id"])
    return augmented


async def _execute_chat_workbook_tool(
    call: dict[str, Any],
    request_context: dict[str, Any],
    progress_sink: Callable[[dict[str, Any]], Any],
) -> dict[str, Any]:
    """Execute one workbook draft through the canonical registry/trust boundary."""
    from proxy.services.artifact_revision_service import ArtifactRevisionStore
    from proxy.services.tool_registry_service import ToolRegistration, ToolRegistry
    from proxy.services.trusted_executor_service import ExecutionRequest, TrustedExecutor
    from proxy.services.workflow_checkpoint_service import WorkflowCheckpointService
    from proxy.services.workbook_tool_service import (
        BUILD_LSR_WORKBOOK,
        BUILD_VOR_WORKBOOK,
        WorkbookExecutionContext,
        build_lsr_workbook,
        build_vor_workbook,
    )

    tool_name = str(call.get("tool") or "")
    contracts = {
        "build_lsr_workbook": (BUILD_LSR_WORKBOOK, build_lsr_workbook),
        "build_vor_workbook": (BUILD_VOR_WORKBOOK, build_vor_workbook),
    }
    if tool_name not in contracts:
        raise ValueError("unsupported workbook tool")
    args = dict(call.get("args") or {})
    bound_attachment_id = str(request_context.get("attachment_id") or "").strip()
    if not bound_attachment_id:
        return {
            "schema": "les.workbook_tool_result.v1",
            "tool": tool_name,
            "status": "rejected",
            "code": "TOOL_ATTACHMENT_SCOPE_REQUIRED",
            "missing": ["attachment_id"],
            "blockers": [],
        }
    requested_attachment_id = str(args.get("attachment_id") or "").strip()
    if requested_attachment_id and requested_attachment_id != bound_attachment_id:
        return {
            "schema": "les.workbook_tool_result.v1",
            "tool": tool_name,
            "status": "rejected",
            "code": "TOOL_SCOPE_VIOLATION",
            "missing": [],
            "blockers": [],
        }
    args["attachment_id"] = bound_attachment_id
    if request_context.get("question") and not args.get("question"):
        args["question"] = request_context["question"]
    bound_project_id = request_context.get("project_id")
    if args.get("project_id") is not None and args.get("project_id") != bound_project_id:
        return {
            "schema": "les.workbook_tool_result.v1",
            "tool": tool_name,
            "status": "rejected",
            "code": "TOOL_SCOPE_VIOLATION",
            "missing": [],
            "blockers": [],
        }
    args["project_id"] = bound_project_id
    if request_context.get("dataset_ids") and not args.get("dataset_ids"):
        args["dataset_ids"] = list(request_context["dataset_ids"])

    identity_payload = {
        "session_id": str(request_context.get("session_id") or ""),
        "tool": tool_name,
        "args": args,
        "profile_revision_id": str(request_context.get("profile_revision_id") or ""),
    }
    identity = hashlib.sha256(
        json.dumps(identity_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    call_id = str(call.get("call_id") or f"workbook-{identity[:16]}")
    pending_progress: list[asyncio.Task] = []

    def emit_progress(event: dict[str, Any]) -> None:
        phase = str(event.get("phase") or "rows")
        label = (
            "Собираю строки ВОР"
            if tool_name == "build_vor_workbook"
            else "Собираю строки ЛСР"
        )
        pending_progress.append(asyncio.create_task(progress_sink({
            "call_id": call_id,
            "checkpoint_id": str(event.get("checkpoint_id") or ""),
            "phase": phase,
            "completed": int(event.get("completed") or 0),
            "total": event.get("total"),
            "label": label,
        })))

    context = WorkbookExecutionContext(
        session_id=str(request_context.get("session_id") or "anonymous"),
        idempotency_key=f"workbook:{identity}",
        model_decision_revision=call_id,
        profile_revision_id=str(request_context.get("profile_revision_id") or "unknown"),
        model_identity=str(request_context.get("model_identity") or "unknown"),
        model_preset=str(request_context.get("model_preset") or "unknown"),
        attachment_root=Path(os.getenv("LES_CHAT_ATTACHMENT_ROOT", "storage/chat_attachments")),
        work_dir=Path("storage/workbook_work"),
        checkpoints=WorkflowCheckpointService(Path("storage/workbook_checkpoints.db")),
        artifacts=ArtifactRevisionStore(
            Path("storage/artifacts/meta.db"), Path("storage/artifacts/files")
        ),
        progress_sink=emit_progress,
    )
    contract, builder = contracts[tool_name]

    async def handler(handler_args: dict[str, Any]) -> dict[str, Any]:
        return await builder(handler_args, context)

    registry = ToolRegistry([ToolRegistration(contract=contract, handler=handler)])
    executor = TrustedExecutor(registry)
    envelope = await executor.execute(ExecutionRequest(
        call_id=call_id,
        tool_name=tool_name,
        arguments=args,
        allowed_dataset_ids=tuple(
            str(item) for item in (request_context.get("dataset_ids") or ())
        ),
        actor_id=str(request_context.get("session_id") or "ordinary-chat"),
        actor_role="user",
        approval_receipt_id=None,
        idempotency_key=f"workbook:{identity}",
        deadline_monotonic=time.monotonic() + 900,
        shadow=False,
        allowed_attachment_ids=(bound_attachment_id,),
    ))
    if pending_progress:
        await asyncio.gather(*pending_progress, return_exceptions=True)
    result = envelope.to_dict()["result"]
    if isinstance(result, dict):
        result["execution"] = envelope.metadata()
    return result


def _compact_tool_result_for_prompt(payload: dict[str, Any], *, max_chars: int = 7000) -> dict[str, Any]:
    keep = {
        "tool": payload.get("tool"),
        "status": payload.get("status"),
        "result": payload.get("result") or {},
        "sources": payload.get("sources") or [],
        "missing": payload.get("missing") or [],
        "warnings": payload.get("warnings") or [],
        "trace": payload.get("trace") or "",
    }
    text = json.dumps(keep, ensure_ascii=False, default=str)
    if len(text) <= max_chars:
        return keep
    trimmed = dict(keep)
    trimmed["result"] = {
        "summary": "tool result trimmed for prompt only; full result is in retrieval_trace.tool_loop",
        "text": text[:max_chars].rsplit(" ", 1)[0].rstrip(),
        "prompt_truncated": True,
    }
    return trimmed


def _format_tool_results_for_model(results: list[dict[str, Any]]) -> str:
    if not results:
        return ""
    compacted = [
        _compact_tool_result_for_prompt(
            result,
            max_chars=max(1000, _env_int("LES_CHAT_TOOL_RESULT_PROMPT_CHARS", 7000)),
        )
        for result in results
    ]
    return (
        "РЕЗУЛЬТАТЫ ИНСТРУМЕНТОВ LES (read-only; это материалы для модели, не готовый ответ):\n"
        + json.dumps(compacted, ensure_ascii=False, indent=2, default=str)
    )


def _local_context_budget(
    *,
    local_big: bool,
    big_context: bool,
    provider: str = "",
) -> dict[str, int]:
    """Context budget for chat generation.

    Cloud can digest a large prompt quickly. Local MLX pays heavily for prefill,
    so technical/legal RAG gets a smaller default budget with env overrides.
    """
    if provider_is_local(provider):
        prompt_chars = provider_prompt_max_chars(provider)
        return {
            "focus_max_chunks": _env_int("FREETOKEN_FOCUS_MAX_CHUNKS", 0),
            "context_max_chunks": _env_int("FREETOKEN_CONTEXT_MAX_CHUNKS", 0),
            "context_chars_limit": _env_int("FREETOKEN_EVIDENCE_MAX_CHARS", prompt_chars),
            "context_window_chars": _env_int("FREETOKEN_CONTEXT_WINDOW_CHARS", 1800),
        }
    return {
        "focus_max_chunks": 0,
        "context_max_chunks": 0,
        "context_chars_limit": _env_int("RAG_MODEL_CONTEXT_CHARS", 120000),
        "context_window_chars": _env_int("RAG_CONTEXT_WINDOW_CHARS", 4000),
    }


def _generation_token_budget(*, max_tokens: int, local_big: bool, attempt: int, intent: str) -> int:
    if attempt != 1:
        return _env_int("RAG_CHAT_RETRY_MAX_TOKENS", 2048)
    if not local_big:
        return max_tokens
    if intent in {"default", "full"}:
        return max_tokens
    cap = _env_int("RAG_LOCAL_CHAT_MAX_TOKENS", 1100)
    return min(max_tokens, cap)


def _dataset_sensitivities(dataset_ids: Iterable[str]) -> list[str]:
    """Уровни чувствительности (P0/P1/P2) задействованных датасетов из метабазы.

    Fail-closed: БД/колонка недоступны или хоть один датасет не найден → P0
    (приватно), чтобы политика W3.3 никогда не открыла облако по ошибке чтения.
    """
    ids = [str(d).strip() for d in dataset_ids if str(d).strip()]
    if not ids:
        return []
    try:
        with sqlite3.connect(rag_meta_db_path()) as conn:
            placeholders = ",".join("?" for _ in ids)
            rows = conn.execute(
                f"SELECT sensitivity FROM datasets WHERE id IN ({placeholders})",
                ids,
            ).fetchall()
        levels = [r[0] for r in rows]
        if len(levels) < len(ids):  # неизвестный датасет → считаем приватным
            levels.append("P0")
        return levels or ["P0"]
    except Exception as exc:  # noqa: BLE001 — любая ошибка чтения → приватно
        logger.warning("[ROUTE] sensitivity read failed (%s) — fail-closed P0", exc)
        return ["P0"]


def _record_cloud_cost(state: "ChatRouterState", model: str, usage: dict[str, Any]) -> None:
    """Учёт расходов облака (токены → $) в метриках. Локальные вызовы сюда не идут."""
    prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
    completion_tokens = int(usage.get("completion_tokens", 0) or 0)
    cost = estimate_cost_usd(model, prompt_tokens, completion_tokens, load_price_table_from_env())
    metrics = state.chat_metrics
    metrics["cloud_requests"] = metrics.get("cloud_requests", 0) + 1
    metrics["cloud_prompt_tokens"] = metrics.get("cloud_prompt_tokens", 0) + prompt_tokens
    metrics["cloud_completion_tokens"] = metrics.get("cloud_completion_tokens", 0) + completion_tokens
    metrics["cloud_cost_usd"] = round(metrics.get("cloud_cost_usd", 0.0) + cost, 6)
    by_model = metrics.setdefault("cloud_cost_by_model", {})
    by_model[model] = round(by_model.get(model, 0.0) + cost, 6)


async def _validate_via_provider(client, llm_runtime, headers, *, question: str, answer: str, context: str) -> str:
    """W3.4-частично: вердикт Т.О.С.К.А. той же (в т.ч. облачной) моделью.

    Компактный промпт со строгим однословным ответом; парсинг — поиск одного
    из трёх статусов в начале ответа. Любой сбой → UNKNOWN (как у MLX-пути).
    """
    system = (
        "Ты — строгий проверяющий фактов (валидатор RAG). Сравни ОТВЕТ с КОНТЕКСТОМ. "
        "Верни РОВНО ОДНО СЛОВО без пояснений: "
        "VERIFIED — все ключевые факты ответа подтверждаются контекстом; "
        "HALLUCINATION — в ответе есть утверждения, противоречащие контексту или отсутствующие в нём; "
        "NO_DATA — контекст не содержит информации для ответа на вопрос."
    )
    user = f"КОНТЕКСТ:\n{context[:9000]}\n\nВОПРОС: {question}\n\nОТВЕТ:\n{answer[:4000]}\n\nВердикт (одно слово):"
    _vbody = {
        "model": llm_runtime.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "temperature": 0,
        # Reasoning-модели тратят токены на скрытое рассуждение — даём запас,
        # иначе видимый контент пуст и вердикт теряется (кейс tencent/hy3).
        "max_tokens": 400,
    }
    # GPT-5.x/o-серия: max_tokens→max_completion_tokens (иначе 400).
    _vbody = _cloud_body_for_model(_vbody, llm_runtime.model, llm_runtime.provider)
    resp = await client.post(
        llm_runtime.chat_url,
        headers=headers,
        json=_vbody,
        timeout=90.0,
    )
    resp.raise_for_status()
    message = resp.json().get("choices", [{}])[0].get("message", {})
    text = f"{message.get('content') or ''}\n{message.get('reasoning') or ''}".upper()
    # HALLUCINATION проверяем первым: «NOT VERIFIED»/рассуждения могут содержать
    # слово VERIFIED в отрицательном контексте — порядок важен.
    for status in ("HALLUCINATION", "NO_DATA", "VERIFIED"):
        if status in text:
            return status
    return "UNKNOWN"


CHAT_HISTORY_EXTRA_COLUMNS = {
    "route_channel": "TEXT DEFAULT ''",
    "route_reason": "TEXT DEFAULT ''",
    "requested_dataset_filter": "TEXT DEFAULT ''",
    "effective_dataset_filter": "TEXT DEFAULT ''",
    "resolved_dataset_ids": "TEXT DEFAULT '[]'",
    "resolved_dataset_names": "TEXT DEFAULT '[]'",
    "source_dataset_ids": "TEXT DEFAULT '[]'",
    "source_dataset_names": "TEXT DEFAULT '[]'",
    "source_dataset_mismatch": "INTEGER DEFAULT 0",
    "query_route_json": "TEXT DEFAULT '{}'",
    "retrieval_trace_json": "TEXT DEFAULT '{}'",
    "artifact_json": "TEXT DEFAULT '{}'",
    "retrieval_quality": "TEXT DEFAULT ''",
    "cache_type": "TEXT DEFAULT ''",
    "validation_enabled": "INTEGER DEFAULT 1",
    "success": "INTEGER DEFAULT 0",
    "feedback_status": "TEXT DEFAULT ''",
    "feedback_comment": "TEXT DEFAULT ''",
    "feedback_correct_answer": "TEXT DEFAULT ''",
    "feedback_correct_dataset_filter": "TEXT DEFAULT ''",
    "feedback_at": "TEXT DEFAULT NULL",
    "feedback_user": "TEXT DEFAULT ''",
}


def ensure_chat_history_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            question TEXT,
            answer TEXT,
            sources TEXT,
            crag_status TEXT,
            latency_sec REAL,
            tokens INTEGER,
            session_id TEXT DEFAULT NULL
        )
        """
    )
    cols = [r[1] for r in conn.execute("PRAGMA table_info(chat_history)").fetchall()]
    if "session_id" not in cols:
        conn.execute("ALTER TABLE chat_history ADD COLUMN session_id TEXT DEFAULT NULL")
        cols.append("session_id")
    for name, ddl in CHAT_HISTORY_EXTRA_COLUMNS.items():
        if name not in cols:
            conn.execute(f"ALTER TABLE chat_history ADD COLUMN {name} {ddl}")
    conn.execute(
        """
        UPDATE chat_history
        SET success=1
        WHERE COALESCE(success, 0)=0
          AND crag_status IN ('VERIFIED', 'UNVALIDATED')
          AND COALESCE(answer, '') <> ''
          AND answer <> ?
        """,
        (SAFE_FALLBACK,),
    )


def _json_text(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except Exception:
        return json.dumps(str(value), ensure_ascii=False)


def _dataset_ids_from_chunks(chunks: list[Any]) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        meta = getattr(chunk, "meta", {}) or {}
        dataset_id = str(meta.get("dataset_id") or "").strip()
        if dataset_id and dataset_id not in seen:
            ids.append(dataset_id)
            seen.add(dataset_id)
    return ids


async def _dataset_name_map(rag_backend) -> dict[str, str]:
    try:
        datasets = await rag_backend.list_datasets()
    except Exception:
        return {}
    return {str(dataset.id): str(dataset.name) for dataset in datasets}


def _names_for_dataset_ids(dataset_ids: list[str] | None, name_by_id: dict[str, str]) -> list[str]:
    return [name_by_id.get(str(dataset_id), str(dataset_id)) for dataset_id in (dataset_ids or [])]


def _history_success(crag_status: str, answer: str) -> int:
    if not answer or answer == SAFE_FALLBACK:
        return 0
    return 1 if crag_status in {"VERIFIED", "UNVALIDATED"} else 0


def _query_route_payload(query_intent: Any, effective_dataset_filter: str | None, kot_decision: Any) -> dict[str, Any]:
    return {
        "channel": query_intent.channel,
        "reason": query_intent.reason,
        "dataset_filter": effective_dataset_filter,
        "kot": kot_decision.payload(),
    }


SOURCE_LOOKUP_MARKERS = (
    "где смотреть",
    "где посмотреть",
    "какие нормы",
    "какая норма",
    "какой норматив",
    "каким норматив",
    "какие норматив",
    "нормы регулиру",
    "нормы примен",
    "требования примен",
)


def _is_source_lookup_question(question: str) -> bool:
    q = question.casefold().replace("ё", "е")
    return any(marker in q for marker in SOURCE_LOOKUP_MARKERS)


def _preview_text(text: str, limit: int = 220) -> str:
    return " ".join(str(text or "").split())[:limit].strip()


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _strip_think(text: str) -> str:
    """Срезать <think>…</think> — reasoning-модели инлайнят размышления в content."""
    return _THINK_RE.sub("", text or "").strip()


def _assistant_text(message: dict) -> str:
    """Текст ответа из chat-completion `message` с поддержкой reasoning-моделей.

    Reasoning-модели (Qwen3.5, o-серия и др.) держат ФИНАЛЬНЫЙ ответ в ``content``, а
    размышления — в ``reasoning``/``reasoning_content`` и/или в ``<think>…</think>`` внутри
    content. Берём content без think-блоков; если он пуст (модель «думала» и упёрлась в лимит
    токенов — ровно случай ollama qwen3.5 на Windows) — fallback на reasoning, чтобы не отдать
    пустой ответ. Не-reasoning модели не затронуты (content присутствует → возвращается как был)."""
    if not isinstance(message, dict):
        return ""
    content = _strip_think(str(message.get("content") or ""))
    if content:
        return content
    for call in message.get("tool_calls") or []:
        if not isinstance(call, dict):
            continue
        function = call.get("function") or {}
        arguments = function.get("arguments") if isinstance(function, dict) else ""
        if isinstance(arguments, dict):
            return json.dumps(arguments, ensure_ascii=False)
        if str(arguments or "").strip():
            return str(arguments).strip()
    legacy_call = message.get("function_call") or {}
    if isinstance(legacy_call, dict) and str(legacy_call.get("arguments") or "").strip():
        return str(legacy_call["arguments"]).strip()
    reasoning = message.get("reasoning") or message.get("reasoning_content") or ""
    return _strip_think(str(reasoning))


def _mlx_prefill_no_think_messages(messages: list[dict[str, Any]], provider: str) -> list[dict[str, Any]]:
    """Local Qwen reasoning models need a final-answer prefill to avoid empty visible content."""
    if str(provider or "").lower() != "mlx":
        return messages
    return [*messages, {"role": "assistant", "content": "<think>\n\n</think>\n\n"}]


# ── Нативный ollama /api/chat с think:false (#1b) ──────────────────────────────────────────
# OpenAI-совместимый эндпоинт ollama ИГНОРИРУЕТ управление «думаньем» (think, /no_think,
# chat_template_kwargs — проверено на qwen3.5:9b), и reasoning-модель тратит весь лимит токенов
# на размышления → пустой/CoT-ответ. Нативный /api/chat с think:false даёт ЧИСТЫЙ content.
# Совпадает с интентом кода (в основном промпте уже есть /no_think «без скрытых рассуждений»).

def _ollama_native_url(base_url: str) -> str:
    """Корень ollama (для /api/chat) из base_url, который мог быть задан с /v1."""
    b = (base_url or "http://127.0.0.1:11434").rstrip("/")
    if b.endswith("/v1"):
        b = b[: -len("/v1")].rstrip("/")
    return f"{b}/api/chat"


def _ollama_native_body(model: str, messages: list, *, max_tokens: int, temperature: float,
                        stream: bool, think: bool = False) -> dict:
    """OpenAI-style messages → нативный ollama /api/chat body. think=False → чистый ответ."""
    return {
        "model": model, "messages": messages, "think": think, "stream": stream,
        "options": {"num_predict": int(max_tokens), "temperature": float(temperature)},
    }


async def _ollama_native_complete(client, runtime, messages, *, max_tokens: int, temperature: float,
                                  headers=None, token_sink=None):
    """Нативный ollama-вызов (think:false). Стрим = NDJSON-строки `{"message":{"content":…},"done":…}`.
    Возвращает (text, usage). usage пуст — ollama локальна, $ не считаем."""
    url = _ollama_native_url(runtime.base_url)
    headers = headers or {}
    if token_sink is not None:
        body = _ollama_native_body(runtime.model, messages, max_tokens=max_tokens,
                                   temperature=temperature, stream=True)
        acc: list[str] = []
        async with client.stream("POST", url, headers=headers, json=body) as sresp:
            sresp.raise_for_status()
            async for line in sresp.aiter_lines():
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                piece = (chunk.get("message") or {}).get("content") or ""
                if piece:
                    acc.append(piece)
                    await token_sink({"event": "token", "data": piece})
                if chunk.get("done"):
                    break
        return "".join(acc), {}
    body = _ollama_native_body(runtime.model, messages, max_tokens=max_tokens,
                               temperature=temperature, stream=False)
    r = await client.post(url, headers=headers, json=body)
    r.raise_for_status()
    return _assistant_text(r.json().get("message", {})), {}


def _source_lookup_answer(question: str, chunks: list[Any], *, max_sources: int | None = None) -> str | None:
    if not _is_source_lookup_question(question) or not chunks:
        return None

    lines = ["Смотреть прежде всего в этих источниках из базы:"]
    seen: set[str] = set()
    source_count = 0
    for chunk in chunks:
        doc_name = str(getattr(chunk, "doc_name", "") or "").strip()
        if not doc_name or doc_name in seen:
            continue
        seen.add(doc_name)
        source_count += 1
        title = Path(doc_name).name
        preview = _preview_text(getattr(chunk, "content", ""), 260)
        if preview:
            lines.append(f"{source_count}. {title} — {preview}")
        else:
            lines.append(f"{source_count}. {title}")
        if max_sources is not None and source_count >= max_sources:
            break

    if source_count == 0:
        return None
    return "\n".join(lines)


def save_chat_history(
    *,
    question: str,
    answer: str,
    sources: list[str],
    crag_status: str,
    latency_sec: float,
    tokens: int,
    session_id: str | None,
    requested_dataset_filter: str | None = None,
    effective_dataset_filter: str | None = None,
    resolved_dataset_ids: list[str] | None = None,
    resolved_dataset_names: list[str] | None = None,
    source_dataset_ids: list[str] | None = None,
    source_dataset_names: list[str] | None = None,
    query_route: dict[str, Any] | None = None,
    retrieval_trace: dict[str, Any] | None = None,
    artifact: dict[str, Any] | None = None,
    cache_type: str = "",
    validation_enabled: bool = True,
    success: int | None = None,
) -> int:
    resolved_set = set(resolved_dataset_ids or [])
    source_set = set(source_dataset_ids or [])
    source_dataset_mismatch = int(bool(resolved_set and source_set and not source_set.issubset(resolved_set)))
    route = query_route or {}
    trace = retrieval_trace or {}
    quality = ""
    if isinstance(trace.get("quality"), dict):
        quality = str(trace["quality"].get("status") or "")
    quality = quality or str(trace.get("quality_status") or "")
    success_value = _history_success(crag_status, answer) if success is None else int(bool(success))
    with sqlite3.connect(rag_meta_db_path()) as conn:
        ensure_chat_history_schema(conn)
        cur = conn.execute(
            "INSERT INTO chat_history "
            "("
            "question, answer, sources, crag_status, latency_sec, tokens, session_id, "
            "route_channel, route_reason, requested_dataset_filter, effective_dataset_filter, "
            "resolved_dataset_ids, resolved_dataset_names, source_dataset_ids, source_dataset_names, "
            "source_dataset_mismatch, query_route_json, retrieval_trace_json, artifact_json, retrieval_quality, "
            "cache_type, validation_enabled, success"
            ") "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                question,
                answer,
                ",".join(sources),
                crag_status,
                latency_sec,
                tokens,
                session_id,
                str(route.get("channel") or ""),
                str(route.get("reason") or ""),
                requested_dataset_filter or "",
                effective_dataset_filter or "",
                _json_text(resolved_dataset_ids or []),
                _json_text(resolved_dataset_names or []),
                _json_text(source_dataset_ids or []),
                _json_text(source_dataset_names or []),
                source_dataset_mismatch,
                _json_text(route),
                _json_text(trace),
                _json_text(artifact or {}),
                quality,
                cache_type,
                int(bool(validation_enabled)),
                success_value,
            ),
        )
        history_id = int(cur.lastrowid)
    try:
        update_chat_profile(
            session_id=session_id,
            question=question,
            answer=answer,
            crag_status=crag_status,
            route=route,
            requested_dataset_filter=requested_dataset_filter,
            effective_dataset_filter=effective_dataset_filter,
            resolved_dataset_ids=resolved_dataset_ids or [],
            resolved_dataset_names=resolved_dataset_names or [],
            source_dataset_ids=source_dataset_ids or [],
            source_dataset_names=source_dataset_names or [],
            success=success_value,
        )
    except Exception as err:  # профиль не должен ломать ответ/историю
        logger.warning("[CONTEXT_MEMORY] chat profile update skipped: %s", err)
    return history_id


def _table_query_response(
    *,
    state: ChatRouterState,
    question: str,
    table_result: Any,
    chunks: list[Any],
    t_search: float,
    session_id: str | None,
    requested_dataset_filter: str | None,
    effective_dataset_filter: str | None,
    resolved_dataset_ids: list[str],
    resolved_dataset_names: list[str],
    dataset_name_by_id: dict[str, str],
    query_route_payload: dict[str, Any],
    retrieval_trace: dict[str, Any],
    cache_marker: str,
    use_validation: bool,
) -> dict[str, Any]:
    state.crag_stats["verified"] += 1
    state.chat_metrics["latency_search"].append(t_search)
    state.chat_metrics["latency_gen"].append(0.0)
    state.chat_metrics["tokens"].append(0)
    state.chat_metrics["crag_pass"] += 1
    for key in ("latency_search", "latency_gen", "tokens"):
        state.chat_metrics[key] = state.chat_metrics[key][-100:]
    history_id = None
    source_dataset_ids = _dataset_ids_from_chunks(chunks)
    source_dataset_names = _names_for_dataset_ids(source_dataset_ids, dataset_name_by_id)
    try:
        history_id = save_chat_history(
            question=question,
            answer=table_result.answer,
            sources=table_result.sources,
            crag_status="VERIFIED",
            latency_sec=t_search,
            tokens=0,
            session_id=session_id,
            requested_dataset_filter=requested_dataset_filter,
            effective_dataset_filter=effective_dataset_filter,
            resolved_dataset_ids=resolved_dataset_ids,
            resolved_dataset_names=resolved_dataset_names,
            source_dataset_ids=source_dataset_ids,
            source_dataset_names=source_dataset_names,
            query_route=query_route_payload,
            retrieval_trace=retrieval_trace,
            cache_type=cache_marker,
            validation_enabled=use_validation,
            success=1,
        )
    except Exception as db_err:
        logger.warning("[CHAT] History save error: %s", db_err)
    return {
        "answer": table_result.answer,
        "crag_status": "VERIFIED",
        "sources": table_result.sources,
        "effective_dataset_filter": effective_dataset_filter,
        "query_route": query_route_payload,
        "retrieval_trace": retrieval_trace,
        "cache": cache_marker,
        "table_query": table_result.payload(),
        "history_id": history_id,
    }


def _clause_lookup_response(
    *,
    state: ChatRouterState,
    question: str,
    clause_result: Any,
    t_search: float,
    session_id: str | None,
    requested_dataset_filter: str | None,
    effective_dataset_filter: str | None,
    resolved_dataset_ids: list[str],
    resolved_dataset_names: list[str],
    dataset_name_by_id: dict[str, str],
    query_route_payload: dict[str, Any],
) -> dict[str, Any]:
    trace = {
        "mode": "deterministic_clause",
        "vector_count": 0,
        "lexical_count": 1,
        "merged_count": 1,
        "retry_count": 0,
        "quality_status": "deterministic_clause",
        "clause_lookup": clause_result.payload(),
    }
    state.crag_stats["verified"] += 1
    state.chat_metrics["latency_search"].append(t_search)
    state.chat_metrics["latency_gen"].append(0.0)
    state.chat_metrics["tokens"].append(0)
    state.chat_metrics["crag_pass"] += 1
    for key in ("latency_search", "latency_gen", "tokens"):
        state.chat_metrics[key] = state.chat_metrics[key][-100:]
    source_dataset_ids = [clause_result.dataset_id] if clause_result.dataset_id else []
    source_dataset_names = _names_for_dataset_ids(source_dataset_ids, dataset_name_by_id)
    history_id = None
    try:
        history_id = save_chat_history(
            question=question,
            answer=clause_result.answer,
            sources=clause_result.sources,
            crag_status="VERIFIED",
            latency_sec=t_search,
            tokens=0,
            session_id=session_id,
            requested_dataset_filter=requested_dataset_filter,
            effective_dataset_filter=effective_dataset_filter,
            resolved_dataset_ids=resolved_dataset_ids,
            resolved_dataset_names=resolved_dataset_names,
            source_dataset_ids=source_dataset_ids,
            source_dataset_names=source_dataset_names,
            query_route=query_route_payload,
            retrieval_trace=trace,
            cache_type="deterministic_clause",
            validation_enabled=False,
            success=1,
        )
    except Exception as db_err:
        logger.warning("[CHAT] History save error: %s", db_err)
    return {
        "answer": clause_result.answer,
        "crag_status": "VERIFIED",
        "sources": clause_result.sources,
        "effective_dataset_filter": effective_dataset_filter,
        "query_route": query_route_payload,
        "retrieval_trace": trace,
        "cache": "deterministic_clause",
        "validation": {"enabled": False, "reason": "deterministic_clause"},
        "clause_lookup": clause_result.payload(),
        "history_id": history_id,
    }


def _sse_event(event: str, data: Any) -> str:
    """Кадр SSE: `event:` + одно `data:` с JSON-телом. Юникод не эскейпим —
    клиент читает UTF-8."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _synthetic_stream_pieces(text: str, *, max_piece_chars: int = 42) -> list[str]:
    """Fallback typing for model/tool branches that returned final text without SSE tokens."""
    words = str(text or "").split(" ")
    pieces: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if len(candidate) > max_piece_chars and current:
            pieces.append(current + " ")
            current = word
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces


def _should_synthesize_stream(result: dict[str, Any]) -> bool:
    """True when the client asked for stream but the selected path produced only final text."""
    answer = str((result or {}).get("answer") or (result or {}).get("response") or "").strip()
    if not answer:
        return False
    artifact = (result or {}).get("artifact")
    if isinstance(artifact, dict) and str(artifact.get("content") or "").strip():
        # Keep chat summary live, but do not type huge artifact payloads.
        return True
    return True


def _notebook_study_validation_status(status: str, *, has_context: bool) -> str:
    """Notebook-study is a reading workflow: incomplete validation must warn, not erase."""
    normalized = (status or "UNKNOWN").upper()
    if has_context and normalized in {"HALLUCINATION", "UNKNOWN"}:
        return "UNVALIDATED"
    return normalized


def _chat_model_final_answer(answer: str, status: str) -> tuple[str, str, dict[str, Any]]:
    """Chat route policy: validation may label, but must not replace a model answer."""
    cleaned = clean_visible_text(answer)
    normalized = (status or "UNKNOWN").upper()
    if not cleaned:
        return cleaned, normalized, {}
    if normalized in {"VERIFIED", "NO_DATA", "UNVALIDATED"}:
        return cleaned, normalized, {}
    return cleaned, "UNVALIDATED", {
        "schema": "chat_model_final_preservation_v1",
        "original_status": normalized,
        "final_status": "UNVALIDATED",
        "reason": "validator_warns_without_replacing_model_answer",
    }


async def _prepare_notebook_reader_memory(dataset_ids: list[str]) -> dict[str, Any]:
    """Best-effort model reader-pass before broad dataset study.

    Reader output is navigation only. It helps the final model choose files and
    sections, but the answer still needs retrieved chunks/tables as evidence.
    """
    # The reader pass is an additional LLM job, not retrieval.  Running it by
    # default made a broad chat silently start a second local model generation
    # and, after timeout, schedule it again in background.  Typed notebook
    # memory + RRF remain available; explicit warmup can opt this job back in.
    if not dataset_ids or not _env_bool("LES_NOTEBOOK_READER_ON_STUDY", False):
        return {"schema": "dataset_reader_prepare_v1", "status": "disabled", "datasets": []}
    limit = _env_int("LES_NOTEBOOK_READER_ON_STUDY_LIMIT", 2)
    timeout_s = _env_float("LES_NOTEBOOK_READER_ON_STUDY_TIMEOUT", 35.0)
    prepared: list[dict[str, Any]] = []
    for dataset_id in [str(d) for d in dataset_ids if str(d).strip()][:limit]:
        try:
            memory = await asyncio.to_thread(get_typed_dataset_memory, dataset_id)
            if memory.get("reader_status") == "model":
                prepared.append({"dataset_id": dataset_id, "status": "ready"})
                continue
            try:
                updated = await asyncio.wait_for(
                    run_dataset_reader_pass(dataset_id, force=False),
                    timeout=timeout_s,
                )
                prepared.append({
                    "dataset_id": dataset_id,
                    "status": str(updated.get("reader_status") or "unknown"),
                })
            except TimeoutError:
                scheduled = schedule_dataset_reader_pass(
                    dataset_id,
                    reason="notebook_study_timeout",
                    force=False,
                    require_enabled=False,
                )
                prepared.append({
                    "dataset_id": dataset_id,
                    "status": "scheduled_after_timeout",
                    "scheduled": scheduled,
                })
        except Exception as err:  # noqa: BLE001
            logger.warning("[DATASET_READER] prepare skipped dataset=%s: %s", dataset_id, err)
            prepared.append({
                "dataset_id": dataset_id,
                "status": "skipped",
                "error": f"{type(err).__name__}: {err}",
            })
    return {"schema": "dataset_reader_prepare_v1", "status": "ok", "datasets": prepared}


def _recoverable_stream_payload(req: ChatRequest, stream_state: dict[str, Any], err: BaseException) -> dict[str, Any] | None:
    """Return a final payload from an already useful SSE answer if the tail failed.

    Broad notebook/project answers can stream a good response for minutes and then hit
    provider timeout/retry plumbing before the final frame. In that case the visible
    streamed answer is the best operator artifact we have, so finish it as
    UNVALIDATED instead of sending a late reset/error that erases it in the UI.
    """
    text = clean_visible_text(str(stream_state.get("text") or stream_state.get("preserved_text") or ""))
    min_chars = _env_int("LES_STREAM_RECOVERY_MIN_CHARS", 700)
    if len(text) < min_chars:
        return None
    sources_payload = stream_state.get("sources_payload")
    if not isinstance(sources_payload, dict):
        sources_payload = {}
    return {
        "answer": text,
        "crag_status": "UNVALIDATED",
        "sources": sources_payload.get("sources") or [],
        "source_excerpts": sources_payload.get("source_excerpts") or [],
        "source_map": sources_payload.get("source_map") or [],
        "effective_dataset_filter": req.dataset_filter,
        "retrieval_trace": {
            "stream_recovery": {
                "reason": type(err).__name__,
                "detail": str(err)[:300],
                "tokens": stream_state.get("tokens", 0),
                "chars": len(text),
                "reset_suppressed": bool(stream_state.get("reset_suppressed")),
            }
        },
        "cache": "stream_recovered",
        "validation": {"enabled": False, "reason": "stream_recovered_after_partial_answer"},
    }


def _persist_recovered_stream_history(
    req: ChatRequest,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Persist an already useful recovered SSE answer for session reopen."""
    if payload.get("history_id"):
        return payload
    try:
        sources = [
            str(source.get("source_ref") or source.get("ref") or source.get("path") or source)
            if isinstance(source, dict)
            else str(source)
            for source in (payload.get("sources") or [])
        ]
        history_id = save_chat_history(
            question=req.question,
            answer=str(payload.get("answer") or ""),
            sources=sources,
            crag_status=str(payload.get("crag_status") or "UNVALIDATED"),
            latency_sec=0.0,
            tokens=int(
                ((payload.get("retrieval_trace") or {}).get("stream_recovery") or {}).get(
                    "tokens"
                )
                or 0
            ),
            session_id=req.session_id,
            query_route={
                "channel": "stream_recovery",
                "operation": "recovered_partial_answer",
            },
            retrieval_trace=(
                payload.get("retrieval_trace")
                if isinstance(payload.get("retrieval_trace"), dict)
                else {}
            ),
            artifact=(
                payload.get("artifact")
                if isinstance(payload.get("artifact"), dict)
                else None
            ),
            cache_type=str(payload.get("cache") or "stream_recovered"),
            validation_enabled=False,
        )
        if history_id:
            payload = {**payload, "history_id": history_id}
    except Exception as error:  # persistence must not hide the recovered answer
        logger.warning("[CHAT/STREAM] recovered history save failed: %s", error)
    return payload


@router.post("/chat")
async def chat(
    req: ChatRequest,
    _user=Depends(require_user),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    """W5.1: нестриминговый эндпоинт — поведение неизменно (M5, смоуки, АРТЕЛЬ,
    chat_format_smoke). token_sink=None → путь stream:False, как раньше.

    Внешний клиент может передать ``Idempotency-Key``. Повтор с тем же телом
    получит исходный ответ без нового вызова модели; тот же ключ с другим телом
    отклоняется.
    """
    if not idempotency_key:
        return decorate_payload(await _run_chat_with_provider(req))

    from proxy.services.request_idempotency_service import (
        IdempotencyConflict,
        begin,
        caller_scope,
        complete,
        release,
        request_fingerprint,
    )

    caller = caller_scope(_user)
    fingerprint = request_fingerprint(_idempotency_payload(req))
    try:
        idem_state, cached = await asyncio.to_thread(
            begin,
            operation="chat",
            caller=caller,
            idempotency_key=idempotency_key,
            request_hash=fingerprint,
        )
    except (ValueError, IdempotencyConflict) as error:
        raise HTTPException(409, str(error)) from error
    if idem_state == "completed" and cached is not None:
        return cached
    if idem_state == "in_progress":
        raise HTTPException(
            409,
            "Запрос с этим Idempotency-Key уже выполняется",
            headers={"Retry-After": "2"},
        )

    try:
        result = decorate_payload(await _run_chat_with_provider(req))
    except Exception:
        await asyncio.to_thread(
            release,
            operation="chat",
            caller=caller,
            idempotency_key=idempotency_key,
            request_hash=fingerprint,
        )
        raise
    try:
        await asyncio.to_thread(
            complete,
            operation="chat",
            caller=caller,
            idempotency_key=idempotency_key,
            request_hash=fingerprint,
            response=result,
        )
    except Exception as error:  # noqa: BLE001 - first caller still receives paid result
        logger.error("[IDEMPOTENCY] chat response persistence failed: %s", error)
    return result


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest, _user=Depends(require_user)):
    """W5.1: SSE-стриминг. События:
      • `token` — кусок ответа по мере генерации (только generic-LLM путь);
      • `progress` — видимый шаг workflow для tool/детерминированных веток;
      • `smeta_step` — крупный этап сметного маршрута до/после model calls;
      • `smeta_batch` — прогресс батчей выбора норм для режима «Смета»;
      • `smeta_row` — завершённое модельное решение по одной строке ВОР;
      • `reset` — очистить накопленный текст (ретрай/деградация на MLX);
      • `final` — полный payload (sources + вердикт валидации в `crag_status`);
      • `error` — {status, detail}.
    Детерминированные/tool ветки не подделывают токены модели: они шлют progress,
    а затем авторитетный final payload."""
    if not req.question.strip():
        raise HTTPException(400, "Empty question")
    queue: asyncio.Queue = asyncio.Queue()
    stream_state: dict[str, Any] = {
        "tokens": 0,
        "text": "",
        "preserved_text": "",
        "sources_payload": {},
        "reset_suppressed": False,
        "suppress_tokens": False,
    }

    async def sink(ev: dict) -> None:
        event = ev.get("event")
        if event == "token" and ev.get("data"):
            if stream_state.get("suppress_tokens"):
                return
            stream_state["tokens"] += 1
            stream_state["text"] = str(stream_state.get("text") or "") + str(ev.get("data") or "")
        elif event == "reset":
            preserve_chars = _env_int("LES_STREAM_RESET_PRESERVE_CHARS", _env_int("LES_STREAM_RECOVERY_MIN_CHARS", 700))
            current_text = str(stream_state.get("text") or "").strip()
            if len(current_text) >= preserve_chars:
                stream_state["preserved_text"] = current_text
                stream_state["reset_suppressed"] = True
                stream_state["suppress_tokens"] = True
                logger.warning("[CHAT/STREAM] late reset suppressed after %s chars", len(current_text))
                return
            stream_state["tokens"] = 0
            stream_state["text"] = ""
        elif event == "sources" and isinstance(ev.get("data"), dict):
            stream_state["sources_payload"] = ev.get("data") or {}
        await queue.put(ev)

    async def runner() -> None:
        try:
            scenario = scenario_for_request(
                mode=req.mode,
                question=req.question,
                has_attachment=bool(req.attachment_context),
            )
            steps = scenario.get("progress") or []
            total = len(steps)
            for idx, label in enumerate(steps, 1):
                await queue.put({
                    "event": "progress",
                    "data": {
                        "step": idx,
                        "total": total,
                        "label": label,
                        "scenario": {"id": scenario.get("id"), "label": scenario.get("label")},
                    },
                })
            result = decorate_payload(await _run_chat_with_provider(req, token_sink=sink))
            if stream_state["tokens"] == 0 and _should_synthesize_stream(result):
                answer_text = str(result.get("answer") or result.get("response") or "")
                for piece in _synthetic_stream_pieces(answer_text):
                    await sink({"event": "token", "data": piece})
                    await asyncio.sleep(0.012)
            await queue.put({"event": "final", "data": result})
        except HTTPException as he:
            recovered = _recoverable_stream_payload(req, stream_state, he)
            if recovered is not None:
                recovered = _persist_recovered_stream_history(req, recovered)
                await queue.put({"event": "final", "data": decorate_payload(recovered)})
            else:
                await queue.put({"event": "error", "data": {"status": he.status_code, "detail": he.detail}})
        except Exception as e:  # noqa: BLE001 — любую ошибку доносим клиенту как событие
            logger.error("[CHAT/STREAM] %s", e)
            recovered = _recoverable_stream_payload(req, stream_state, e)
            if recovered is not None:
                recovered = _persist_recovered_stream_history(req, recovered)
                await queue.put({"event": "final", "data": decorate_payload(recovered)})
            else:
                await queue.put({"event": "error", "data": {"status": 500, "detail": f"{type(e).__name__}: {e}"}})
        finally:
            await queue.put(None)

    async def event_source():
        task = asyncio.create_task(runner())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield _sse_event(item["event"], item.get("data", ""))
        finally:
            if not task.done():
                # Closing the tab must not discard a completed estimate/history
                # record. Explicit user cancellation remains a separate UI action.
                logger.info("[CHAT/STREAM] client disconnected; waiting for runner to finish")
                await asyncio.gather(task, return_exceptions=True)

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


async def _run_free_mode(req: "ChatRequest", token_sink=None) -> str:
    """Режим «Свободный»: прямой вызов LLM БЕЗ ретрива (ответ из знаний модели) + мягкая
    плашка. Изолирован — RAG-конвейер не задействуется. Стримит токены, если token_sink задан."""
    runtime = _llm_runtime()
    disclaimer = ("⚠️ Вольный режим — ответ модели без обращения к базе документов; "
                  "возможны неточности, проверяй факты.\n\n")
    sys_prompt = build_mode_system_prompt("free")
    attachment = (
        f"Контекст прикреплённого файла:\n{req.attachment_context}\n\n"
        if req.attachment_context else ""
    )
    try:
        session_block = session_memory(req.session_id, max_turns=6, max_chars=2000)
    except Exception as err:
        logger.warning("[MEMORY] free session recall failed: %s", err)
        session_block = ""
    messages = [
        {"role": "system", "content": sys_prompt},
        {
            "role": "user",
            "content": (f"{session_block}\n\n" if session_block else "")
            + attachment
            + req.question,
        },
    ]
    request = InferenceRequest(
        messages=tuple(messages),
        temperature=0.85,
        max_output_tokens=1400,
    )
    acc: list[str] = []
    try:
        if token_sink is not None:
            await token_sink({"event": "token", "data": disclaimer})
        async with httpx.AsyncClient(timeout=300.0) as client:
            connection_mode = _effective_model_connection_mode()
            async def legacy_complete(_request: InferenceRequest) -> InferenceResponse:
                body = {
                    "model": runtime.model,
                    "messages": messages,
                    "temperature": 0.85,
                    "max_tokens": 1400,
                }
                body = _cloud_body_for_model(body, runtime.model, runtime.provider)
                headers = {"Authorization": f"Bearer {runtime.api_key}"} if runtime.api_key else {}
                if runtime.provider == "ollama":
                    text, usage = await _ollama_native_complete(
                        client,
                        runtime,
                        messages,
                        max_tokens=1400,
                        temperature=0.85,
                        headers=headers,
                        token_sink=token_sink,
                    )
                    return InferenceResponse(text=text, tool_calls=(), finish_reason="stop", usage=usage)
                if token_sink is not None:
                    sbody = {**body, "stream": True}
                    if is_cloud_provider(runtime.provider):
                        sbody["stream_options"] = {"include_usage": True}
                    pieces: list[str] = []
                    usage: dict[str, int] = {}
                    async with client.stream(
                        "POST", runtime.chat_url, headers=headers, json=sbody
                    ) as sresp:
                        sresp.raise_for_status()
                        async for line in sresp.aiter_lines():
                            if not line or not line.startswith("data:"):
                                continue
                            payload = line[5:].strip()
                            if payload == "[DONE]":
                                break
                            try:
                                chunk = json.loads(payload)
                            except json.JSONDecodeError:
                                continue
                            choices = chunk.get("choices") or []
                            delta = choices[0].get("delta", {}) if choices else {}
                            piece = assistant_delta_text(delta)
                            if piece:
                                pieces.append(piece)
                                await token_sink({"event": "token", "data": piece})
                            if chunk.get("usage"):
                                usage = chunk["usage"]
                    return InferenceResponse(
                        text="".join(pieces),
                        tool_calls=(),
                        finish_reason="stop",
                        usage=usage,
                    )
                response = await client.post(runtime.chat_url, headers=headers, json=body)
                response.raise_for_status()
                payload = response.json()
                choice = (payload.get("choices") or [{}])[0]
                return InferenceResponse(
                    text=_assistant_text(choice.get("message", {})),
                    tool_calls=tuple((choice.get("message") or {}).get("tool_calls") or ()),
                    finish_reason=str(choice.get("finish_reason") or ""),
                    usage=payload.get("usage", {}) or {},
                )

            result = await _bound_model_chat_runner(client).complete(
                mode=connection_mode,
                request=request,
                legacy_complete=legacy_complete,
            )
            acc.append(result.response.text)
            if (
                token_sink is not None
                and connection_mode is CanonicalRouteMode.ACTIVE
                and result.response.text
            ):
                await token_sink({"event": "token", "data": result.response.text})
    except Exception as e:  # noqa: BLE001
        logger.warning("[FREE] generation failed: %s", e)
        return disclaimer + f"Не удалось получить вольный ответ: {type(e).__name__}: {e}"
    return disclaimer + "".join(acc).strip()


def _attachment_source_label(ctx: str | None) -> str:
    if not ctx:
        return "attachment"
    first = ctx.strip().splitlines()[0].strip()
    if first.lower().startswith("файл:"):
        name = first.split(":", 1)[1].strip()
        if name:
            return f"attachment:{name}"
    return "attachment"


def _question_with_attachment(req: "ChatRequest") -> str:
    """User task plus read-attachment text for explicit tool modes.

    Auto/free/RAG have their own context paths; explicit tools must still see the file instead of
    silently using only the typed question.
    """
    if not req.attachment_context:
        return req.question
    return f"{req.question}\n\nКонтекст прикреплённого файла:\n{req.attachment_context}"


async def _run_attachment_mode(req: "ChatRequest", token_sink=None) -> str:
    """Direct LLM over the attached file text only. No global RAG sources."""
    runtime = _smeta_model_runtime("LES_SMETA_WORKFLOW_DECISION_PROVIDER")
    try:
        session_block = session_memory(req.session_id, max_turns=4, max_chars=1600)
    except Exception as err:
        logger.warning("[MEMORY] attachment session recall failed: %s", err)
        session_block = ""
    sys_prompt = build_mode_system_prompt(
        "review",
        extra=(
            "Пользователь прикрепил файл к сообщению. Отвечай по тексту файла как по главному "
            "источнику; не привлекай внешние документы и не выдумывай отсутствующие данные. "
            "Если в тексте файла нет нужной информации, прямо скажи, чего не хватает. Кратко."
        ),
    )
    user_prompt = (
        (f"{session_block}\n\n" if session_block else "")
        + (
        "Контекст прикреплённого файла:\n"
        f"{req.attachment_context}\n\n"
        f"Задание пользователя: {req.question}"
        )
    )
    body = {
        "model": runtime.model,
        "messages": [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}],
        "temperature": 0.2,
        "max_tokens": 1400,
    }
    body = _cloud_body_for_model(body, runtime.model, runtime.provider)
    headers = {"Authorization": f"Bearer {runtime.api_key}"} if runtime.api_key else {}
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            if runtime.provider == "ollama":
                text, _ = await _ollama_native_complete(
                    client, runtime, body["messages"], max_tokens=1400, temperature=0.2,
                    headers=headers, token_sink=None)
            else:
                r = await client.post(runtime.chat_url, headers=headers, json=body)
                r.raise_for_status()
                text = _assistant_text(r.json().get("choices", [{}])[0].get("message", {}))
    except Exception as e:  # noqa: BLE001
        logger.warning("[ATTACHMENT] generation failed: %s", e)
        text = f"Не удалось обработать прикреплённый файл: {type(e).__name__}: {e}"
    text = text.strip()
    if token_sink is not None and text:
        await token_sink({"event": "token", "data": text})
    return text


def _harness_complete(messages: list[dict]) -> str:
    """Sync LLM-вызов для петли сметного харнесса (исполняется в to_thread). Облако/MLX по
    конфигу — декомпозиция объекта = где большая модель уместна. Низкая temperature для tool-call."""
    runtime = _llm_runtime()
    timeout_s = float(os.getenv("LES_ESTIMATE_HARNESS_TIMEOUT_SEC", "35"))
    body = {
        "model": runtime.model,
        "messages": _mlx_prefill_no_think_messages(messages, runtime.provider),
        "temperature": 0.0,
        "max_tokens": _estimate_harness_plan_tokens(messages),
    }
    body = _cloud_body_for_model(body, runtime.model, runtime.provider)
    headers = {"Authorization": f"Bearer {runtime.api_key}"} if runtime.api_key else {}
    try:
        with httpx.Client(timeout=timeout_s) as c:
            r = c.post(runtime.chat_url, headers=headers, json=body)
            r.raise_for_status()
            return _assistant_text(r.json().get("choices", [{}])[0].get("message", {}))
    except Exception as e:  # noqa: BLE001 — петля переживёт пустой ответ (учтёт как «нет JSON»)
        logger.warning("[HARNESS] llm call failed: %s", e)
        return ""






def _estimate_harness_plan_tokens(messages: list[dict]) -> int:
    """Completion budget for the model-owned smeta work plan.

    Full TZ/BOR attachments can need many work items. If this budget is too small, the
    model returns a partial plan and the user sees a false "missing source" problem.
    """
    total_chars = sum(len(str(m.get("content") or "")) for m in messages if isinstance(m, dict))
    if total_chars >= 8000:
        default = 2400
    elif total_chars >= 3500:
        default = 1800
    else:
        default = 1100
    configured = _env_int("LES_ESTIMATE_HARNESS_MAX_TOKENS", default)
    return max(700, min(configured, 3200))


def _compact_question_excerpt(question: str, *, max_chars: int = 1600) -> dict[str, Any]:
    text = str(question or "")
    if len(text) <= max_chars:
        return {"text": text, "chars": len(text), "truncated": False}
    half = max(300, max_chars // 2)
    return {
        "text": text[:half].rstrip() + "\n...\n" + text[-half:].lstrip(),
        "chars": len(text),
        "truncated": True,
    }


def _voice_claims_source_truncated(text: str) -> bool:
    t = str(text or "").casefold().replace("ё", "е")
    return bool(re.search(
        r"(?:исходн\w*|файл|тз|ведомост\w*|перечен\w*)\s+"
        r"(?:оборвал|обрыва|усеч|неполн|не полн|заканчива|прерыва)|"
        r"(?:пришл(?:ите|и)|дошл(?:ите|и))\s+(?:продолжени|остаток)",
        t,
    ))


def _harness_model_comment(result: dict, question: str) -> str:
    """LLM smetnik layer: visible professional reasoning around tool results."""
    runtime = _llm_runtime()
    comp = result.get("computed") or []
    pending = [*(result.get("rejected") or []), *(result.get("needs_input") or [])]
    allowed_codes = {
        str(p.get("code") or "").strip()
        for p in [*comp, *pending]
        if isinstance(p, dict) and str(p.get("code") or "").strip()
    }
    final_total = result.get("final_total") if isinstance(result.get("final_total"), dict) else {}
    partial_total = result.get("partial_total") if isinstance(result.get("partial_total"), dict) else {}
    has_partial_protocol = bool(partial_total and comp)
    allowed_money = {
        _rub(total.get(key))
        for total in (final_total,)
        if isinstance(total, dict)
        for key in ("smr", "grand_total")
        if total.get(key)
    }
    payload = {
        "question_excerpt": _compact_question_excerpt(question),
        "status": result.get("total_status"),
        "object": result.get("schema") if isinstance(result.get("schema"), dict) else {},
        "assumption_mode": bool(result.get("assumption_mode")),
        "scenario_assumptions": [str(x)[:160] for x in (result.get("scenario_assumptions") or [])[:5]],
        "computed_count": len(comp),
        "pending_count": len(pending),
        "has_partial_protocol": has_partial_protocol,
        "visible_total_policy": (
            "final_total_only" if result.get("total_status") == "complete"
            else "partial_protocol_no_money" if has_partial_protocol
            else "no_money_visible"
        ),
        "computed": [
            {
                "work": str(p.get("work") or "")[:100],
                "code": str(p.get("code") or "")[:40],
                "unit": str(p.get("physical_unit") or "")[:20],
                "assumptions": [_smeta_humanize_text(a)[:120] for a in (p.get("assumptions") or [])[:3]],
                "norm_questions": [str(x)[:100] for x in (p.get("norm_questions") or [])[:6]],
            }
            for p in comp[:6] if isinstance(p, dict)
        ],
        "pending": [
            {
                "work": str(p.get("work") or "")[:100],
                "reason": _smeta_humanize_text(p.get("reason") or p.get("detail") or "")[:180],
                "missing_slots": [_smeta_human_slot(s)[:80] for s in (p.get("missing_slots") or [])[:5]],
                "norm_questions": [str(x)[:100] for x in (p.get("norm_questions") or [])[:6]],
            }
            for p in pending[:8] if isinstance(p, dict)
        ],
        "allowed_exact_facts": {
            "codes": sorted(allowed_codes)[:8],
            "money_rub": sorted(allowed_money)[:4],
        },
    }
    messages = [
        {"role": "system", "content": (
            "Ты опытный сметчик ЛЕС. Верни видимый сметный ход перед таблицей: 3-7 коротких строк, "
            "живо, слегка иронично, профессионально. Не раскрывай скрытую цепочку размышлений; дай "
            "пользователю понятное рабочее рассуждение: что понял из запроса, чем готов пользоваться "
            "из инструментов, что нельзя считать без исходных, какой следующий вопрос самый полезный. "
            "Поле question_excerpt может быть сокращённым фрагментом большого ТЗ/ВОР; запрещено делать "
            "по нему вывод, что файл, ведомость или исходные данные оборвались, неполные или требуют "
            "продолжения. О неполноте говори только если это прямо есть в расчётном payload как "
            "недостающие параметры/условия нормы. "
            "Если в payload есть norm_questions, спрашивай именно их как условия выбранной нормы. "
            "Если итог не complete, "
            "не перечисляй рубли и не обещай, что уже раскладываешь ресурсы, коэффициенты, НР/СП "
            "или региональные цены: только смысл, принятые расчётным слоем строки, недостающие "
            "исходные и следующий шаг. "
            "Если visible_total_policy=partial_protocol_no_money, не говори "
            "«деньги посчитаны», «есть рассчитанная сумма», «рассчитанная часть в рублях» или похожее: "
            "скажи, что финальный итог не сформирован, а ниже будет протокол принятых строк и незакрытых условий. "
            "Коды и суммы можно "
            "упоминать только дословно из allowed_exact_facts; не округляй и не добавляй новые. "
            "Не переформулируй условия нормы как новые границы: если в норме «до 2 м», а в исходнике "
            "глубина 1,5 м, говори «глубина 1,5 м попадает в условие до 2 м», а не «норма до 1,5 м». "
            "Проценты, новые параметры и обещания не добавляй. Не переписывай таблицу и не делай "
            "финальный вывод вместо расчётного слоя. Не используй англицизмы и внутренние имена полей "
            "в видимом тексте: не пиши element_type, slots, missing_inputs, wall_length_m и т.п.; "
            "говори по-русски: тип работ, параметры, недостающие исходные, длина стен. Без markdown."
        )},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    body = {"model": runtime.model, "messages": messages, "temperature": 0.65, "max_tokens": 360}
    body = _cloud_body_for_model(body, runtime.model, runtime.provider)
    headers = {"Authorization": f"Bearer {runtime.api_key}"} if runtime.api_key else {}
    timeout_s = _env_float("LES_ESTIMATE_MODEL_COMMENT_TIMEOUT_SEC", 35.0)
    try:
        with httpx.Client(timeout=timeout_s) as c:
            r = c.post(runtime.chat_url, headers=headers, json=body)
            r.raise_for_status()
            text = _assistant_text(r.json().get("choices", [{}])[0].get("message", {})).strip()
    except Exception as e:  # noqa: BLE001
        logger.warning("[HARNESS] model comment failed: %s", e)
        return ""
    text = re.sub(r"\n{3,}", "\n\n", text).strip(" \n\t\"'")
    text = re.split(
        r"(?im)^\s*(?:таблица|расч[её]тный слой|таблица расч[её]тного слоя|позиции\s*:)",
        text,
        maxsplit=1,
    )[0].strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) > 7:
        text = "\n".join(lines[:7])
    if not text or len(text) > 2000:
        return ""
    if _voice_claims_source_truncated(text):
        logger.warning("[HARNESS] suppressed unsupported source-truncation voice claim")
        return ""
    def _norm_literal(value: str) -> str:
        return re.sub(r"\s+", " ", str(value or "").replace("₽", "").strip()).casefold()

    allowed_money_norm = {_norm_literal(v) for v in allowed_money}
    for found in re.finditer(r"\d[\d\s.,]*\s*₽", text):
        if _norm_literal(found.group(0)) not in allowed_money_norm:
            return ""

    allowed_code_norm = {_norm_literal(v) for v in allowed_codes}
    for found in re.finditer(r"ГЭСНм?:\s*[\d-]+", text, flags=re.IGNORECASE):
        if _norm_literal(found.group(0)) not in allowed_code_norm:
            return ""

    if re.search(r"\d[\d\s.,]*\s*%", text):
        return ""
    if has_partial_protocol and result.get("total_status") != "complete":
        contradiction_patterns = (
            r"деньг\w*\s+(?:сейчас\s+)?не\s+счита",
            r"стоимост\w*\s+(?:сейчас\s+)?не\s+счита",
            r"рубл\w*\s+(?:сейчас\s+)?не\s+счита",
            r"расч[её]т\s+невозможен",
            r"ничего\s+не\s+счита",
            r"рассчитанн\w*\s+(?:част\w*|сумм\w*)",
            r"част\w*\s+(?:сумм\w*|денег)\s+(?:есть|посчитан)",
        )
        if any(re.search(pat, text, flags=re.IGNORECASE) for pat in contradiction_patterns):
            return ""
    return text


_harness_voice_comment = _harness_model_comment


def _should_use_model_first_smeta(result: dict) -> bool:
    if not isinstance(result, dict):
        return False
    if not _env_bool("LES_SMETA_MODEL_FIRST_VISIBLE_ENABLED", True):
        return False
    status = str(result.get("total_status") or "")
    if status not in {"complete", "partial", "blocked"}:
        return False
    if status == "partial" and result.get("computed"):
        return False
    return (
        bool(result.get("computed") or [])
        or bool((result.get("rejected") or []) or (result.get("needs_input") or []))
        or bool(result.get("price_requirements") or [])
    )


def _smeta_blocked_advisory(result: dict) -> dict[str, Any]:
    computed = result.get("computed") or []
    final_total = result.get("final_total") if isinstance(result.get("final_total"), dict) else {}
    pending = [*(result.get("rejected") or []), *(result.get("needs_input") or [])]
    trace = result.get("trace") if isinstance(result.get("trace"), list) else []
    return {
        "schema": "smeta_calculator_advisory_v1",
        "status": result.get("total_status"),
        "planner_status": result.get("planner_status"),
        "visible_money_policy": (
            "final_total_allowed_from_this_payload"
            if result.get("total_status") == "complete" and final_total
            else "no_rubles_for_partial_or_blocked"
        ),
        "final_total": (
            {
                "direct": final_total.get("direct"),
                "nr": final_total.get("nr"),
                "sp": final_total.get("sp"),
                "smr": final_total.get("smr"),
                "vat": final_total.get("vat"),
                "grand_total": final_total.get("grand_total"),
            }
            if result.get("total_status") == "complete" and final_total
            else None
        ),
        "computed_count": len(computed),
        "pending_count": len(pending),
        "computed": [
            {
                "work": str(p.get("work") or "")[:140],
                "code": str(p.get("code") or "")[:50],
                "qty": p.get("qty"),
                "norm_unit": str(p.get("norm_unit") or "")[:30],
                "phys_qty": p.get("phys_qty"),
                "physical_unit": str(p.get("physical_unit") or "")[:20],
                "norm_questions": [str(x)[:120] for x in (p.get("norm_questions") or [])[:6]],
            }
            for p in computed[:24] if isinstance(p, dict)
        ],
        "pending": [
            {
                "work": str(p.get("work") or "")[:140],
                "code": str(p.get("code") or "")[:50],
                "unit": str(p.get("physical_unit") or "")[:20],
                "reason": _smeta_humanize_text(p.get("reason") or p.get("status") or "")[:220],
            }
            for p in pending[:24] if isinstance(p, dict)
        ],
        "tools": [
            {
                "tool": str(t.get("tool") or ""),
                "status": str(t.get("status") or ""),
                "work": str(t.get("work") or "")[:120],
                "candidates": [str(c)[:50] for c in (t.get("candidates") or [])[:4]],
            }
            for t in trace[:32] if isinstance(t, dict)
        ],
    }


def _smeta_model_first_answer(harness_question: str, result: dict) -> str:
    """Visible model-first estimate answer; calculator output is only a protocol."""
    runtime = _llm_runtime()
    sys_prompt = build_mode_system_prompt(
        "smeta_direct",
        extra=(
            "Ты основной видимый сметчик. Ниже будет расчётный протокол принятых строк, "
            "проверок и незакрытых условий; не пересказывай его как готовую смету. Если статус "
            "complete, можно назвать итог только из calculator_advisory.final_total. Если статус "
            "partial или blocked, не называй рубли и не делай вид, что итог посчитан. "
            "Не показывай пользователю внутренние слова complete, partial, blocked, shortlist, "
            "calculator_advisory, status и «калькулятор». Пиши по-русски: итог сформирован, "
            "итог не сформирован, расчётный протокол, найденные варианты норм, нужно выбрать норму. "
            "Сохрани структуру ТЗ/ВОР, отдели работы от поставки, посчитай простые количества "
            "из текста, если они прямо следуют из исходных, и покажи, что нужно добрать до рублей. "
            "Не проси продолжение файла и не говори, что исходные оборвались, если в тексте нет "
            "явной отметки усечения."
        ),
    )
    payload = {
        "task": "model_first_smeta_answer",
        "user_context": str(harness_question or "")[:18000],
        "calculator_advisory": _smeta_blocked_advisory(result),
        "blocked_harness_advisory": _smeta_blocked_advisory(result),
        "required_visible_shape": [
            "коротко что понял",
            "ведомость работ/количеств: на 1 изделие и итог по количеству изделий, если множитель явно есть",
            "что является работой, что поставкой/материалом",
            "что принято в расчётный протокол и что ещё не принято",
            "если статус complete: краткий итог только из final_total; если нет: что требует КАЦ/ФГИС/КП/региона/выбора нормы",
            "следующий практический шаг",
        ],
    }
    body = {
        "model": runtime.model,
        "messages": _mlx_prefill_no_think_messages(
            [{"role": "system", "content": sys_prompt}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            runtime.provider,
        ),
        "temperature": 0.25,
        "max_tokens": _env_int("LES_SMETA_MODEL_FIRST_MAX_TOKENS", 2200),
    }
    body = _cloud_body_for_model(body, runtime.model, runtime.provider)
    headers = {"Authorization": f"Bearer {runtime.api_key}"} if runtime.api_key else {}
    timeout_s = _env_float("LES_SMETA_MODEL_FIRST_TIMEOUT_SEC", 90.0)
    try:
        with httpx.Client(timeout=timeout_s) as c:
            r = c.post(runtime.chat_url, headers=headers, json=body)
            r.raise_for_status()
            text = _assistant_text(r.json().get("choices", [{}])[0].get("message", {})).strip()
    except Exception as e:  # noqa: BLE001
        logger.warning("[HARNESS] model-first smeta answer failed: %s", e)
        return ""
    text = re.sub(r"\n{3,}", "\n\n", text).strip(" \n\t\"'")
    if not text or _voice_claims_source_truncated(text):
        return ""
    return text[:10000]







































def _smeta_service_context_prompt() -> str:
    """Navigation context for direct smeta answers: GESN map + available pricebooks.

    This is prompt/RAG context for the model, not a calculator and not a case template.
    """
    blocks: list[str] = []
    try:
        from proxy.services.notebook_service import smeta_norm_rag_prompt_excerpt

        blocks.append(
            "Сметный RAG-блокнот ГЭСН/РИМ (навигация, не готовый ответ):\n"
            f"{smeta_norm_rag_prompt_excerpt()}"
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[SMETA] service GESN prompt skipped: %s", exc)
    try:
        from proxy.services.service_source_registry import service_sources

        sources = [
            src for src in service_sources().get("sources", [])
            if src.get("domain") == "smeta"
        ]
        if sources:
            lines = ["Сметные источники, доступные в ЛЕС:"]
            for src in sources:
                facts = src.get("facts") if isinstance(src.get("facts"), dict) else {}
                fact_text = ", ".join(f"{k}: {v}" for k, v in facts.items()) or "факты не указаны"
                file_paths = [
                    str(f.get("path") or "")
                    for f in src.get("files") or []
                    if f.get("exists") and f.get("path")
                ][:4]
                file_text = f"; файлы: {', '.join(file_paths)}" if file_paths else ""
                lines.append(f"- {src.get('label')}: {src.get('status')} ({fact_text}{file_text})")
            lines.append(
                "Правило для ответа: использовать эти источники как карту норм и цен. "
                "Если источник со статусом ok, не говорить, что пользователь его не дал; говорить, "
                "что источник в ЛЕС доступен, но для итоговых рублей нужно выбрать норму, раскрыть "
                "ресурсы и привязать конкретную ценовую строку. Если нужной цены/нормы нет в RAG "
                "или файле, показать ВОР и ценовой добор (КАЦ/КП/ФГИС/прайс), а не блокировать весь ответ."
            )
            blocks.append("\n".join(lines))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[SMETA] service source prompt skipped: %s", exc)
    return "\n\n".join(blocks)


def _smeta_available_pricebook_context() -> str:
    try:
        from proxy.services import fgis_price_service as fps

        books = fps.available_pricebooks()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[SMETA] pricebook context skipped: %s", exc)
        return ""
    if not books:
        return ""
    stems = sorted(Path(p).stem for p in books)
    shown = stems[:80]
    default_book = _smeta_default_pricebook_name(stems)
    return (
        "Доступные локальные ценовые книги ФГИС ЦС / сплит-формы: "
        f"{', '.join(shown)}. Всего книг: {len(stems)}. "
        f"Системная книга по умолчанию при неуказанном регионе: {default_book or 'нет'}. "
        "Рабочее правило: сначала смотри в эти книги и RAG, потом спрашивай пользователя. "
        "Не пиши, что пользователь не приложил сплит-форму или что ценовой базы нет, если "
        "подходящая книга уже есть в ЛЕС. Если нужного региона/периода нет среди доступных "
        "книг, спроси именно регион/период или попроси загрузить недостающую книгу. Если книга "
        "есть, но итог не закрыт, причина не в отсутствии сплит-формы, а в незакрытой связке "
        "«норма -> ресурсы -> коды ресурсов -> цены»."
    )


def _smeta_default_pricebook_name(stems: list[str]) -> str:
    configured = os.getenv("LES_DEFAULT_PRICEBOOK", "").strip()
    preferred: list[str] = []
    if configured:
        preferred.append(Path(configured).stem)
    preferred.extend(["spb_2kv2026", "sankt-peterburg_2kv2026", "spb_2kv2025", "sankt-peterburg_2kv2025"])
    preferred.extend([stem for stem in stems if "2026" in stem])
    preferred.extend(stems)
    seen: set[str] = set()
    for stem in preferred:
        if stem in seen:
            continue
        seen.add(stem)
        if stem in stems:
            return stem
    return ""


def _smeta_system_source_readiness_context() -> str:
    try:
        from proxy.services.service_source_registry import service_sources

        sources = service_sources().get("sources", [])
    except Exception as exc:  # noqa: BLE001
        logger.warning("[SMETA] service source readiness skipped: %s", exc)
        return ""
    smeta_ids = {"gesn_base", "fgis_price_base", "smeta_coefficients", "smeta_service_dataset"}
    ready: list[str] = []
    missing: list[str] = []
    for src in sources:
        if not isinstance(src, dict) or str(src.get("id") or "") not in smeta_ids:
            continue
        label = str(src.get("label") or src.get("id") or "")
        status = str(src.get("status") or "")
        facts = src.get("facts") if isinstance(src.get("facts"), dict) else {}
        fact_bits: list[str] = []
        for key in ("parquet_rows", "base_norms", "pricebooks", "price_rows"):
            if facts.get(key) not in (None, ""):
                fact_bits.append(f"{key}={facts.get(key)}")
        line = f"{label}: {status}" + (f" ({', '.join(fact_bits)})" if fact_bits else "")
        if status == "ok":
            ready.append(line)
        else:
            missing.append(line)
    if not ready and not missing:
        return ""
    text = [
        "Системные сметные источники ЛЕС физически подключены:",
        *[f"- {line}" for line in ready[:8]],
    ]
    if missing:
        text.append("Чего не хватает в системном слое:")
        text.extend(f"- {line}" for line in missing[:8])
    else:
        text.append("Чего не хватает в системном сметном слое: нет blocking-missing по ГЭСН/ФГИС/НРСП.")
    return "\n".join(text)


def _smeta_service_rag_map_context() -> str:
    """Compact, generic smeta RAG map for the direct estimator prompt.

    This is navigation for the model. It does not choose works, norms or
    contractual quantities; it only tells the model which LES sources exist
    before it asks the user for missing files.
    """
    notebook_text = ""
    try:
        from proxy.services.notebook_service import smeta_norm_rag_prompt_excerpt

        notebook_text = smeta_norm_rag_prompt_excerpt()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[SMETA] smeta norm RAG notebook skipped: %s", exc)
    overview = Path("RAG_Content/TABLE_SMETA/SMETA_SERVICE/00_smeta_service_overview.md")
    if not overview.exists():
        return notebook_text
    try:
        text = overview.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[SMETA] service RAG map skipped: %s", exc)
        return ""
    lines: list[str] = []
    in_collections = False
    collection_count = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("# "):
            lines.append(line.lstrip("# ").strip())
            continue
        if line.startswith("- Норм в локальной базе") or line.startswith("- Коллекций/сборников") or line.startswith("- Ценовых книг"):
            lines.append(line)
            continue
        if line.startswith("## Карточки сборников"):
            in_collections = True
            lines.append("Основные карточки сборников:")
            continue
        if line.startswith("## Карточки ценовых книг"):
            in_collections = False
            continue
        if in_collections and line.startswith("- [") and collection_count < 80:
            lines.append(line)
            collection_count += 1
    if not lines:
        return notebook_text
    lines.extend([
        "Правило: это карта доступных сметных источников ЛЕС, а не готовая смета.",
        "Сначала используй эту карту и RAG для выбора нормативного маршрута; у пользователя спрашивай только то, чего в карте/источниках нет.",
    ])
    overview_text = "Карта сметного RAG ЛЕС:\n" + "\n".join(lines[:90])
    return "\n\n".join(x for x in (notebook_text, overview_text) if x)


def _norm_code_label(code: Any) -> str:
    text = str(code or "").strip()
    return text if text else "—"


_SMETA_HUMAN_SLOTS = {
    "area_total_m2": "площадь/габариты объекта",
    "excavation_depth_m": "глубина котлована (м)",
    "slab_thickness_m": "толщина плиты (мм/м)",
    "slab_area_m2": "площадь плиты (м2)",
    "floor_area_m2": "площадь перекрытия (м2)",
    "wall_thickness_m": "толщина стен (мм/м)",
    "wall_height_m": "высота стен (м)",
    "wall_length_m": "длина/периметр стен (м)",
    "pile_count": "количество свай",
    "volume_m3": "объём (м3)",
    "area_m2": "площадь (м2)",
    "mass_t": "масса (т)",
    "piece_count": "количество (шт)",
    "object_type": "тип объекта",
    "floors": "этажность",
    "levels_below_ground": "подземные этажи",
    "structural_system": "конструктивная схема",
}

_SMETA_HUMAN_ELEMENTS = {
    "excavation": "земляные работы",
    "concrete_preparation": "бетонная подготовка",
    "foundation_slab": "фундаментная плита",
    "monolithic_wall": "монолитные стены",
    "monolithic_slab": "монолитное перекрытие",
    "column": "колонны",
    "waterproofing": "гидроизоляция",
    "roofing": "кровля",
    "wood_wall": "деревянный каркас/стены",
    "metal_assembly": "монтаж металлоконструкций",
    "pile": "сваи",
    "foundation": "фундамент",
    "floors": "полы/перекрытия",
    "finishes": "отделка",
    "engineering_networks": "инженерные сети",
}


def _smeta_human_slot(value: Any) -> str:
    return _SMETA_HUMAN_SLOTS.get(str(value or "").strip(), str(value or "").strip())


def _smeta_humanize_text(text: Any) -> str:
    out = str(text or "").strip()
    if not out:
        return ""
    for key, label in {**_SMETA_HUMAN_ELEMENTS, **_SMETA_HUMAN_SLOTS}.items():
        out = re.sub(rf"\b{re.escape(key)}\b", label, out)
    out = re.sub(
        r"нет расч[её]тной формулы для\s+element_type=([^;.,]+)",
        r"нет расчётной формулы для типа работ: \1",
        out,
    )
    out = out.replace("missing_inputs", "недостающие исходные")
    out = out.replace("missing_slots", "недостающие параметры")
    out = out.replace("slots", "параметры")
    out = re.sub(r"\bshortlist\b", "кандидаты норм", out, flags=re.IGNORECASE)
    out = re.sub(r"\bharness\b", "расчётный слой", out, flags=re.IGNORECASE)
    out = re.sub(r"\brole-pack\b", "сметный контракт", out, flags=re.IGNORECASE)
    out = re.sub(r"\btool-loop\b", "расчётный цикл", out, flags=re.IGNORECASE)
    out = re.sub(r"\braw JSON\b", "служебный JSON", out, flags=re.IGNORECASE)
    out = out.replace("work items", "позиции работ")
    out = out.replace("work item", "позиция работ")
    return out


def _candidate_table_row(position: dict[str, Any]) -> str:
    work = str(position.get("work") or "Работа").strip()
    candidates = [c for c in (position.get("candidates") or []) if isinstance(c, dict)]
    top = candidates[0] if candidates else {}
    code = _norm_code_label(top.get("norm_code") or position.get("code"))
    unit = str(top.get("measure_unit") or top.get("base_unit") or position.get("physical_unit") or "—")
    rest = ", ".join(_norm_code_label(c.get("norm_code")) for c in candidates[1:4]) or "—"
    selection = position.get("selection") if isinstance(position.get("selection"), dict) else {}
    reason = str(selection.get("reason") or position.get("reason") or "нужна проверка применимости").strip()
    reason_low = reason.lower()
    if (
        "кандидат" in reason_low
        or "применим" in reason_low
        or "лидер" in reason_low
        or "отрыв" in reason_low
        or "shortlist" in reason_low
    ):
        reason = "нужно выбрать применимую норму, измеритель или исходный объём"
    reason = _smeta_humanize_text(reason)
    return f"| {work} | {code} | {unit} | {rest} | {reason} |"


def _rub(value: Any) -> str:
    try:
        return f"{float(value):,.2f}".replace(",", " ")
    except (TypeError, ValueError):
        return str(value or "0")


def _qty(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value or "")
    return f"{number:,.6f}".rstrip("0").rstrip(".").replace(",", " ")


def _resource_kind_label(kind: str) -> str:
    return {
        "labor": "Труд",
        "machinist": "Машинисты",
        "machine": "Машины",
        "material": "Материалы",
    }.get(kind, kind or "Ресурс")


def _estimate_positions(r: dict) -> list[dict[str, Any]]:
    estimate = r.get("estimate") if isinstance(r.get("estimate"), dict) else {}
    positions = estimate.get("positions") if isinstance(estimate.get("positions"), list) else []
    return [p for p in positions if isinstance(p, dict)]


def _format_harness_artifact(r: dict) -> str:
    """Полная сметная расшифровка для панели артефактов."""
    if r.get("total_status") != "complete":
        computed = [p for p in (r.get("computed") or []) if isinstance(p, dict)]
        if not computed:
            return ""
        positions = _estimate_positions(r)
        price_requirements = [
            req for req in (
                ((r.get("estimate") or {}).get("summary") or {}).get("price_requirements")
                or r.get("price_requirements")
                or []
            )
            if isinstance(req, dict)
        ]
        lines = [
            "# Частичный расчётный протокол",
            "",
            "Это не финальная смета: состав работ, нормы или цены ещё не закрыты. "
            "Рубли ниже показывают только рассчитанную часть; незакрытые ресурсы не превращены в нулевую цену.",
            "",
        ]
        if positions:
            lines += [
                "## Рассчитанная часть",
                "",
                "| Работа | Код | Кол-во | Ед. | Учтено в частичном расчёте, ₽ |",
                "|---|---:|---:|---:|---:|",
            ]
            for pos in positions:
                lines.append(
                    f"| {pos.get('name') or 'Работа'} | {pos.get('code') or '—'} "
                    f"| {_qty(pos.get('qty'))} | {pos.get('unit') or '—'} | {_rub(pos.get('total'))} |"
                )
        else:
            lines += [
                "## Принятые расчётные строки",
                "",
                "| Работа | Код | Кол-во | Ед. |",
                "|---|---:|---:|---:|",
            ]
            for pos in computed:
                lines.append(
                    f"| {pos.get('work') or 'Работа'} | {pos.get('code') or '—'} "
                    f"| {_qty(pos.get('qty'))} | {pos.get('norm_unit') or pos.get('physical_unit') or '—'} |"
                )
        if price_requirements:
            lines += ["", "## Ценовой добор", ""]
            seen = set()
            for req in price_requirements:
                key = (req.get("action"), req.get("resource_code"), req.get("resource_name"))
                if key in seen:
                    continue
                seen.add(key)
                lines.append(f"- {req.get('message') or 'нужна цена ресурса'}")
        pending = [*(r.get("needs_input") or []), *(r.get("rejected") or [])]
        if pending:
            lines += ["", "## Что нужно добрать", "",
                      "| Работа | Недостающие данные или проверка |",
                      "|---|---|"]
            for item in pending[:12]:
                if not isinstance(item, dict):
                    continue
                work = str(item.get("work") or item.get("work_description") or "Работа")
                reason = _smeta_humanize_text(item.get("reason") or item.get("detail") or item.get("status") or "")
                lines.append(f"| {work} | {reason or 'нужно уточнить норму, параметр или цену'} |")
        return "\n".join(lines)
    positions = _estimate_positions(r)
    if not positions:
        return ""
    lines = ["# Сметная расшифровка", ""]
    lines += ["## Позиции", "",
              "| Работа | Код | Кол-во | Ед. | Сумма, ₽ |",
              "|---|---:|---:|---:|---:|"]
    for pos in positions:
        lines.append(
            f"| {pos.get('name') or 'Работа'} | {pos.get('code') or '—'} "
            f"| {_qty(pos.get('qty'))} | {pos.get('unit') or '—'} | {_rub(pos.get('total'))} |"
        )

    totals = [
        ("ОЗП", "ozp"),
        ("ЭМ", "em"),
        ("в том числе ЗПМ", "zpm"),
        ("Материалы", "mat"),
        ("Прямые затраты", "direct"),
        ("ФОТ", "fot"),
        ("НР", "nr"),
        ("СП", "sp"),
        ("Всего по СМР", "total"),
    ]
    lines += ["", "## Структура стоимости", "",
              "| Статья | Сумма, ₽ |",
              "|---|---:|"]
    for label, key in totals:
        value = 0.0
        for pos in positions:
            bucket = pos.get("adjusted") or pos.get("base") or {}
            if isinstance(bucket, dict):
                value += float(bucket.get(key) or 0)
        lines.append(f"| {label} | {_rub(value)} |")

    estimate = r.get("estimate") if isinstance(r.get("estimate"), dict) else {}
    condition = str(estimate.get("condition") or "").strip()
    k_ozp = float(estimate.get("k_ozp") or 1)
    k_em = float(estimate.get("k_em") or 1)
    lines += ["", "## Коэффициенты и условия", "",
              "| Условие | Применено |",
              "|---|---|"]
    if condition or k_ozp != 1 or k_em != 1:
        lines.append(f"| Стеснённость/условия работ | {condition or 'коэффициент'}: ОЗП ×{k_ozp:g}, ЭМ ×{k_em:g} |")
    else:
        lines.append("| Стеснённость/высотные работы | Коэффициент не применён: нужен явный коэффициент, ПОС или нормативное основание |")

    resources: list[dict[str, Any]] = []
    for pos in positions:
        for res in pos.get("resources") or []:
            if isinstance(res, dict):
                resources.append(res)
    if resources:
        lines += ["", "## Ресурсы", "",
                  "| Вид | Код | Наименование | Кол-во | Цена, ₽ | Источник/добор | Сумма, ₽ |",
                  "|---|---:|---|---:|---:|---|---:|"]
        for res in resources:
            name = str(res.get("name") or "").replace("|", "/")
            source = str(res.get("price_source") or res.get("price_action") or "").strip()
            if res.get("price_action") == "needs_kac":
                source = "нужен КАЦ"
            elif res.get("price_action") == "needs_labor_rate":
                source = "нужна ставка ОЗП"
            elif res.get("price_action") == "needs_machinist_rate":
                source = "нужна ставка ЗПМ"
            elif res.get("price_action") == "needs_fgis_price":
                source = "нужна цена машины"
            lines.append(
                f"| {_resource_kind_label(str(res.get('kind') or ''))} "
                f"| {res.get('code') or '—'} "
                f"| {name} "
                f"| {_qty(res.get('qty'))} {res.get('unit') or ''} "
                f"| {_rub(res.get('price_used'))} "
                f"| {source or '—'} "
                f"| {_rub(res.get('cost'))} |"
            )
    price_requirements = []
    estimate = r.get("estimate") if isinstance(r.get("estimate"), dict) else {}
    summary = estimate.get("summary") if isinstance(estimate.get("summary"), dict) else {}
    for req in summary.get("price_requirements") or r.get("price_requirements") or []:
        if isinstance(req, dict):
            price_requirements.append(req)
    if price_requirements:
        lines += ["", "## Что нужно добрать для полного расчёта", ""]
        seen = set()
        for req in price_requirements:
            msg = str(req.get("message") or "").strip()
            if not msg:
                action = str(req.get("action") or "needs_price")
                msg = {
                    "needs_kac": "нужен КАЦ",
                    "needs_labor_rate": "нужна ставка ОЗП",
                    "needs_machinist_rate": "нужна ставка ЗПМ",
                    "needs_fgis_price": "нужна цена ресурса ФГИС/машины",
                }.get(action, "нужна цена ресурса")
            key = (req.get("action"), req.get("resource_code"), req.get("resource_name"))
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"- {msg}")
    flags = []
    for pos in positions:
        flags.extend(pos.get("flags") or [])
    if flags:
        lines += ["", "## Проверить", ""]
        lines.extend(f"- {flag}" for flag in flags)
    return "\n".join(lines)


def _format_harness(r: dict) -> str:
    """Результат model-first estimate → operator-facing markdown.

    First layer must be human-readable: no tool names, planner trace or internal English enums.
    The machine trace stays in payload technical details.
    """
    sch = r.get("schema", {}) or {}
    obj_type = str(sch.get("object_type") or "объект")
    obj_type = {"house": "дом", "residential_house": "жилой дом"}.get(obj_type, obj_type)
    area = sch.get("area_total_m2")
    hide_planner_area = bool(r.get("direct_quantity_estimate"))
    area_text = f" · {area} м²" if area not in (None, "", 0) and not hide_planner_area else ""
    comp = r.get("computed", [])
    status = r.get("total_status")
    if status == "complete" and comp:
        title = "Предварительная сметная стоимость"
    elif comp:
        title = "Расчётный протокол"
    else:
        title = "Смета пока не собрана"
    lines = [f"**{title}** — {obj_type}{area_text}", ""]
    scenario_assumptions = [str(x) for x in (r.get("scenario_assumptions") or []) if str(x).strip()]
    if r.get("assumption_mode"):
        hint = "; ".join(scenario_assumptions[:3]) or "исходные приняты моделью как типовой сценарий"
        lines += [
            "**Сценарий по допущениям.** Это ориентировочная прикидка, не проектная смета; "
            f"{hint}.",
            "",
        ]
    if comp:
        lines += ["**Принятые расчётные строки**", "",
                  "| Работа | Код ГЭСН | Кол-во в измерителе нормы | Физический объём |",
                  "|---|---:|---:|---:|"]
        for p in comp:
            lines.append(f"| {p.get('work', '')} | {p.get('code')} | {p.get('qty')} {p.get('norm_unit','')} "
                         f"| {p.get('phys_qty','')} {p.get('physical_unit','')} |")
        has_artifact_rows = bool(_estimate_positions(r) or r.get("computed"))
        if _estimate_positions(r) and r.get("total_status") == "complete":
            lines += ["", "Полная ресурсная расшифровка, НР/СП, машины, труд и материалы — в артефакте."]
        elif has_artifact_rows:
            lines += ["", "Расчётный протокол и незакрытые позиции — в артефакте."]
        norm_checks = [p for p in comp if isinstance(p, dict) and p.get("norm_questions")]
        if norm_checks:
            lines += ["", "**Проверить по выбранным нормам**"]
            for p in norm_checks[:6]:
                qs = ", ".join(str(x) for x in (p.get("norm_questions") or [])[:6])
                if qs:
                    lines.append(f"- {p.get('work') or p.get('code')}: {qs}.")

    pt, ft = r.get("partial_total"), r.get("final_total")
    if status == "complete" and ft:
        lines += ["", f"**Итого: СМР {_rub(ft.get('smr'))} ₽ · всего с НДС {_rub(ft.get('grand_total'))} ₽** "
                  f"({ft.get('positions')} поз.)"]
    elif status == "partial" and pt:
        lines += ["", f"**Частично оценено: ~{_rub(pt.get('grand_total'))} ₽** "
                  f"по {pt.get('positions')} поз. Это не финальная смета: "
                  "часть состава работ ещё без подтверждённой нормы, параметров или ценового источника."]

    rej = r.get("rejected", [])
    ni = r.get("needs_input", [])
    pending = [p for p in [*rej, *ni] if isinstance(p, dict)]
    if pending:
        lines += ["", "**Нужно выбрать норму или уточнить параметры**", "",
                  "| Работа | Норма | Ед. | Другие варианты | Что нужно добрать |",
                  "|---|---:|---:|---|---|"]
        for p in pending:
            lines.append(_candidate_table_row(p))
    elif not comp:
        lines += ["", "В протоколе пока нет расчётных строк: нужно выбрать норму из поиска или добрать исходные."]

    if ni:
        slots_needed: list[str] = []
        for p in ni:
            slots_needed += [s for s in (p.get("missing_slots") or []) if s not in slots_needed]
        if slots_needed:
            ask = ", ".join(_smeta_human_slot(s) for s in slots_needed)
            lines += ["", f"**Чтобы дорассчитать:** {ask}."]
    if not ft and not pt:
        lines += ["", "Число не показываю, пока нормы и параметры не подтверждены."]
    elif not ft and pt:
        lines += ["", "Финальную сумму не показываю: рубли показаны только по закрытой части протокола. До финальной сметы нужно закрыть нормы, параметры и ценовые источники."]
    return "\n".join(lines)


def _smeta_dialog_state(result: dict) -> dict[str, Any]:
    """Compact tool-result memory for the next model turn in the same smeta dialog."""
    computed = result.get("computed") or []
    pending = [*(result.get("needs_input") or []), *(result.get("rejected") or [])]
    return {
        "schema": "smeta_dialog_state_v1",
        "total_status": result.get("total_status"),
        "object": result.get("schema") if isinstance(result.get("schema"), dict) else {},
        "assumption_mode": bool(result.get("assumption_mode")),
        "scenario_assumptions": [str(x)[:160] for x in (result.get("scenario_assumptions") or [])[:5]],
        "computed": [
            {
                "work": str(p.get("work") or "")[:120],
                "code": str(p.get("code") or "")[:50],
                "physical_unit": str(p.get("physical_unit") or "")[:20],
                "phys_qty": p.get("phys_qty"),
                "norm_unit": str(p.get("norm_unit") or "")[:40],
                "qty": p.get("qty"),
                "norm_questions": [str(x)[:100] for x in (p.get("norm_questions") or [])[:6]],
            }
            for p in computed[:8] if isinstance(p, dict)
        ],
        "pending": [
            {
                "work": str(p.get("work") or "")[:120],
                "status": _smeta_humanize_text(p.get("status") or p.get("reason") or "")[:80],
                "reason": _smeta_humanize_text(p.get("reason") or p.get("detail") or "")[:220],
                "missing_slots": [_smeta_human_slot(s)[:80] for s in (p.get("missing_slots") or [])[:8]],
                "norm_questions": [str(x)[:100] for x in (p.get("norm_questions") or [])[:6]],
                "candidate": str(p.get("code") or p.get("candidate") or "")[:50],
            }
            for p in pending[:10] if isinstance(p, dict)
        ],
    }


def _format_smeta_dialog_state(state: dict[str, Any]) -> str:
    if not isinstance(state, dict) or state.get("schema") != "smeta_dialog_state_v1":
        return ""
    lines = [f"Предыдущий результат smeta-инструментов: статус {state.get('total_status') or '—'}."]
    obj = state.get("object") if isinstance(state.get("object"), dict) else {}
    if obj:
        obj_text = ", ".join(f"{k}={v}" for k, v in obj.items() if v not in (None, "", []))
        if obj_text:
            lines.append(f"Объект: {obj_text}.")
    if state.get("assumption_mode"):
        assumptions = "; ".join(str(x) for x in (state.get("scenario_assumptions") or [])[:3])
        lines.append("Предыдущий расчёт был сценарием по допущениям" + (f": {assumptions}." if assumptions else "."))
    comp = state.get("computed") if isinstance(state.get("computed"), list) else []
    if comp:
        lines.append("Уже считалось:")
        for p in comp[:6]:
            if isinstance(p, dict):
                questions = ", ".join(p.get("norm_questions") or [])
                lines.append(
                    f"- {p.get('work') or 'работа'}; {p.get('code') or 'код не задан'}; "
                    f"{p.get('phys_qty') or '—'} {p.get('physical_unit') or ''}".strip()
                    + (f"; проверить по норме: {questions}" if questions else "")
                )
    pending = state.get("pending") if isinstance(state.get("pending"), list) else []
    if pending:
        lines.append("Осталось уточнить:")
        for p in pending[:8]:
            if not isinstance(p, dict):
                continue
            slots = ", ".join(p.get("missing_slots") or [])
            questions = ", ".join(p.get("norm_questions") or [])
            detail = questions or slots or _smeta_humanize_text(p.get("reason") or p.get("status")) or "нужны исходные данные"
            lines.append(f"- {p.get('work') or 'работа'}: {detail}.")
    return "\n".join(lines)


def _split_markdown_table_row(line: str) -> list[str]:
    cells = [c.strip() for c in str(line or "").strip().strip("|").split("|")]
    return [re.sub(r"\s+", " ", c).strip() for c in cells]


def _smeta_active_state_from_answer(question: str, answer: str) -> dict[str, Any]:
    """Build compact active estimate state from the visible direct answer.

    This is working memory for follow-up edits, not a pricing/norm authority.
    """
    text = str(answer or "")
    text_low = text.lower()
    methodology = ""
    has_rim = bool(re.search(r"\bрим\b|гэсн|фгис", text_low))
    has_market = bool(re.search(r"рынок|рыноч", text_low))
    if has_rim and has_market:
        methodology = "РИМ/ГЭСН + рынок"
    elif has_rim:
        methodology = "РИМ/ГЭСН"
    elif has_market:
        methodology = "рынок"

    if re.search(r"(код|номер|шифр)[^.\n]{0,80}гэсн|гэсн[^.\n]{0,80}(код|номер|шифр)|кандидат[^.\n]{0,80}гэсн", text_low):
        last_action = "подбор кандидатов ГЭСН"
    elif re.search(r"стоим|оцен|сумм|руб|рим-сценар|рыноч", text_low):
        last_action = "предварительная оценка стоимости"
    elif re.search(r"\bвор\b|ведомост[^.\n]{0,40}работ|структур[^.\n]{0,40}работ", text_low):
        last_action = "формирование/уточнение ВОР"
    elif re.search(r"развил|конфликт|расхожд", text_low):
        last_action = "контроль исходных объёмов"
    else:
        last_action = ""

    last_table = ""
    works: list[dict[str, Any]] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip().startswith("|"):
            i += 1
            continue
        header = _split_markdown_table_row(line)
        low = [h.lower() for h in header]
        if any("гэсн" in h or "норм" in h for h in low):
            last_table = "таблица кандидатов норм/ГЭСН"
        elif any("рим" in h for h in low) and any("рын" in h for h in low):
            last_table = "сравнительная таблица РИМ/рынок"
        elif any("вариант" in h for h in low) and any("объ" in h for h in low):
            last_table = "форма развилки исходных объёмов"
        elif any(("работ" in h or "наименование" in h) for h in low):
            last_table = "таблица ВОР"
        if not any(("работ" in h or "наименование" in h) for h in low):
            i += 1
            continue
        title_idx = next((idx for idx, h in enumerate(low) if "работ" in h or "наименование" in h), 0)
        unit_idx = next((idx for idx, h in enumerate(low) if "ед" in h or "измер" in h), None)
        qty_idx = next((idx for idx, h in enumerate(low) if "кол" in h or "объ" in h), None)
        basis_idx = next((idx for idx, h in enumerate(low) if "норм" in h or "гэсн" in h or "обосн" in h or "источник" in h), None)
        price_idx = next((idx for idx, h in enumerate(low) if "ставк" in h or "цена" in h), None)
        amount_idx = next((idx for idx, h in enumerate(low) if "сумм" in h or "стоим" in h or "всего" in h), None)
        status_idx = next((idx for idx, h in enumerate(low) if "статус" in h or "коммент" in h), None)
        j = i + 1
        if j < len(lines) and re.fullmatch(r"\s*\|?[\s:\-\|]+\|?\s*", lines[j] or ""):
            j += 1
        while j < len(lines) and lines[j].strip().startswith("|"):
            cells = _split_markdown_table_row(lines[j])
            if len(cells) < len(header):
                j += 1
                continue
            title = cells[title_idx] if title_idx < len(cells) else ""
            if not title or title.lower() in ("итого", "итого вариант а", "итого вариант б"):
                j += 1
                continue
            if len(title) > 180:
                j += 1
                continue
            unit = cells[unit_idx] if unit_idx is not None and unit_idx < len(cells) else ""
            qty_raw = cells[qty_idx] if qty_idx is not None and qty_idx < len(cells) else ""
            qty = parse_ru_number(qty_raw) if qty_raw else None
            works.append({
                "title": title[:160],
                "unit": unit[:30],
                "quantity": qty,
                "quantity_text": qty_raw[:50],
                "basis": (cells[basis_idx] if basis_idx is not None and basis_idx < len(cells) else "")[:120],
                "unit_price": (cells[price_idx] if price_idx is not None and price_idx < len(cells) else "")[:80],
                "amount": (cells[amount_idx] if amount_idx is not None and amount_idx < len(cells) else "")[:80],
                "status": (cells[status_idx] if status_idx is not None and status_idx < len(cells) else "")[:120],
            })
            max_active_works = max(1, _env_int("LES_SMETA_ACTIVE_STATE_MAX_WORKS", 500))
            if len(works) >= max_active_works:
                break
            j += 1
        i = j
        if len(works) >= max(1, _env_int("LES_SMETA_ACTIVE_STATE_MAX_WORKS", 500)):
            break

    excluded: list[str] = []
    for line in lines:
        clean = re.sub(r"^[\s\-•]+", "", line).strip()
        if not clean:
            continue
        low = clean.lower()
        if ("0 руб" in low or "исключ" in low or "не включ" in low) and len(clean) <= 220:
            excluded.append(clean)
        if len(excluded) >= 8:
            break

    assumptions: list[str] = []
    open_conflicts: list[str] = []
    for line in lines:
        clean = re.sub(r"^[\s\-•]+", "", line).strip()
        if not clean:
            continue
        low = clean.lower()
        if (
            re.search(r"допущ|принято|принимаю|ориентир|сценарн[^.\n]{0,80}став|ставк[^.\n]{0,80}сценарн|assumption", low)
            and len(clean) <= 240
        ):
            assumptions.append(clean)
        if (
            re.search(r"развил|конфликт|расхожд|вариант", low)
            and (re.search(r"\d", clean) or "конфликт" in low or "развил" in low)
            and len(clean) <= 260
        ):
            open_conflicts.append(clean)
        if len(assumptions) >= 6 and len(open_conflicts) >= 6:
            break

    accepted_variant = ""
    m = re.search(r"(вариант\s+[А-ЯA-Z][^.\n]{0,140}(?:\d{2,4}[,\s]\d{2,6}\s*т)?)", text, flags=re.IGNORECASE)
    if m:
        accepted_variant = re.sub(r"\s+", " ", m.group(1)).strip()[:180]

    status = "scenario_estimate" if re.search(r"сценарн|не финальн|не финальная", text, re.IGNORECASE) else "draft"
    total_match = re.search(r"(?:итого|всего)[^.\n|]{0,80}?([\d\s]+(?:[,.]\d+)?)\s*(?:руб|₽)", text, flags=re.IGNORECASE)
    last_total = re.sub(r"\s+", " ", total_match.group(1)).strip() + " руб." if total_match else ""
    if not works and not excluded and not accepted_variant and not methodology and not assumptions and not open_conflicts:
        return {}
    return {
        "schema": "active_smeta_state_v1",
        "task": re.sub(r"\s+", " ", str(question or "")).strip()[:260],
        "methodology": methodology,
        "last_action": last_action,
        "last_table": last_table,
        "accepted_variant": accepted_variant,
        "open_conflicts": open_conflicts[:6],
        "assumptions": assumptions[:6],
        "excluded": excluded,
        "works": works,
        "last_total": last_total,
        "status": status,
    }


def _format_active_smeta_state(state: dict[str, Any]) -> str:
    if not isinstance(state, dict) or state.get("schema") != "active_smeta_state_v1":
        return ""
    lines = [
        "Активная смета для продолжения. Используй как рабочее состояние текущего расчёта; "
        "нормы, цены и числа всё равно проверяй по RAG/trace. "
        "Если текущий запрос просит только оформить, вывести в ЛСР, добавить шифры/колонки "
        "или изменить формат, сохраняй уже принятые строки, ставки и итоги; не пересчитывай "
        "и не сокращай состав без нового источника или прямой команды:"
    ]
    if state.get("task"):
        lines.append(f"Задача: {state.get('task')}.")
    if state.get("methodology"):
        lines.append(f"Методика: {state.get('methodology')}.")
    table_action = "; ".join(
        str(x) for x in (state.get("last_table"), state.get("last_action")) if str(x or "").strip()
    )
    if table_action:
        lines.append(f"Последняя таблица/действие: {table_action}.")
    if state.get("accepted_variant"):
        lines.append(f"Принятый/рабочий вариант: {state.get('accepted_variant')}.")
    open_conflicts = state.get("open_conflicts") if isinstance(state.get("open_conflicts"), list) else []
    if open_conflicts:
        lines.append("Открытые развилки: " + "; ".join(str(x) for x in open_conflicts[:4]) + ".")
    if state.get("status"):
        lines.append(f"Статус: {state.get('status')}.")
    if state.get("last_total"):
        lines.append(f"Последний итог: {state.get('last_total')}. Для форматных правок сохраняй его без пересчёта.")
    excluded = state.get("excluded") if isinstance(state.get("excluded"), list) else []
    if excluded:
        lines.append("Исключения/нулевые позиции: " + "; ".join(str(x) for x in excluded[:5]) + ".")
    assumptions = state.get("assumptions") if isinstance(state.get("assumptions"), list) else []
    if assumptions:
        lines.append("Принятые допущения: " + "; ".join(str(x) for x in assumptions[:5]) + ".")
    works = state.get("works") if isinstance(state.get("works"), list) else []
    if works:
        lines.append("Текущая ВОР:")
        prompt_works_limit = max(1, _env_int("LES_SMETA_ACTIVE_STATE_PROMPT_WORKS", 200))
        for idx, w in enumerate(works[:prompt_works_limit], 1):
            if not isinstance(w, dict):
                continue
            qty = w.get("quantity_text") or w.get("quantity")
            unit = str(w.get("unit") or "").strip()
            qty_text = f" — {qty} {unit}".rstrip() if qty not in (None, "") or unit else ""
            details = []
            if w.get("basis"):
                details.append(f"обоснование: {w.get('basis')}")
            if w.get("unit_price"):
                details.append(f"цена/ставка: {w.get('unit_price')}")
            if w.get("amount"):
                details.append(f"сумма: {w.get('amount')}")
            if w.get("status"):
                details.append(f"статус: {w.get('status')}")
            suffix = f" ({'; '.join(str(x) for x in details)})" if details else ""
            lines.append(f"{idx}. {w.get('title') or 'работа'}{qty_text}{suffix}")
        if len(works) > prompt_works_limit:
            lines.append(f"... ещё {len(works) - prompt_works_limit} строк ВОР в предыдущем ответе/артефакте.")
    return "\n".join(lines)


def _smeta_recent_dialog_context(
    session_id: str | None,
    *,
    max_turns: int = 4,
    max_answer_chars: int = 2200,
    max_total_chars: int = 9000,
) -> str:
    """Recent smeta Q/A context for follow-up edits like "add GESN numbers"."""
    sid = str(session_id or "").strip()
    if not sid:
        return ""
    try:
        with sqlite3.connect(rag_meta_db_path()) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT question, answer FROM chat_history WHERE session_id=? "
                "ORDER BY id DESC LIMIT ?",
                (sid, max_turns),
            ).fetchall()
    except sqlite3.OperationalError:
        return ""
    rows = list(reversed(rows))
    if not rows:
        return ""
    parts: list[str] = [
        "Предыдущий сметный диалог. Используй как рабочий контекст для продолжения, "
        "но не как самостоятельный источник норм/цен без проверки:"
    ]
    for row in rows:
        q = str(row["question"] or "").strip()
        a = str(row["answer"] or "").strip()
        if q:
            parts.append("Пользователь:\n" + q[:900])
        if a:
            parts.append("Ответ ЛЕС:\n" + a[:max_answer_chars])
    return "\n\n".join(parts)[:max_total_chars]


def _smeta_harness_question(req: "ChatRequest") -> str:
    """Передать модели контекст диалога и прошлые tool results, не подсовывая готовый состав работ."""
    current = _question_with_attachment(req)
    try:
        history = session_user_questions(req.session_id, max_turns=6)
    except Exception as err:  # noqa: BLE001
        logger.warning("[HARNESS] session history failed: %s", err)
        history = []
    history = [str(q).strip() for q in history if str(q or "").strip()]
    state_block = ""
    try:
        traces = session_recent_retrieval_traces(req.session_id, max_turns=4)
        for trace in reversed(traces):
            if not isinstance(trace, dict):
                continue
            active_state = trace.get("active_smeta_state")
            state_block = _format_active_smeta_state(active_state)
            if not state_block:
                state = trace.get("smeta_dialog_state")
                state_block = _format_smeta_dialog_state(state)
            if state_block:
                break
    except Exception as err:  # noqa: BLE001
        logger.warning("[HARNESS] session smeta state failed: %s", err)
        state_block = ""
    blocks = []
    recent_dialog = _smeta_recent_dialog_context(req.session_id)
    if recent_dialog:
        blocks.append(recent_dialog)
    if history:
        turns = "\n".join(f"- {q}" for q in history)
        blocks.append(f"Контекст текущего диалога:\n{turns}")
    if state_block:
        blocks.append(state_block)
    blocks.append(f"Текущий запрос:\n{current}")
    return "\n\n".join(blocks)


def _version_stamp() -> dict:
    """Version-stamp для воспроизводимости (Codex §15, пет-размер): через месяц объяснить,
    почему тот же запрос дал другой ответ. v0.19: + version_info (app/harness/commit/флаги) из
    единого version_service — баг-репорт идентифицирует точный build."""
    try:
        runtime = _llm_runtime()
        llm_provider, llm_model = runtime.provider, runtime.model
    except Exception:  # noqa: BLE001
        llm_provider, llm_model = "unknown", "unknown"
    stamp = {
        "llm_provider": llm_provider,
        "llm_model": llm_model,
        "embed_model": os.getenv("EMBED_MODEL", "?"),
        "collection": os.getenv("RAG_COLLECTION", "") or "default",
        "norm_base": "ГЭСН-2022",
        "prompt": "sys_normal_v1",
        "profiles": "v1",
    }
    try:
        from proxy.services.version_service import version_info_trace
        stamp["version_info"] = version_info_trace()
    except Exception:  # noqa: BLE001
        pass
    return stamp


async def _run_chat(req: ChatRequest, token_sink=None):
    """Ядро чата. token_sink=None — обычный ответ (dict). Если задан — корутина
    `await token_sink({"event":..., "data":...})` получает события стриминга по
    мере генерации; итог всё равно возвращается dict'ом (его шлёт `chat_stream`
    финальным событием)."""
    state = get_chat_state()
    if not req.question.strip():
        raise HTTPException(400, "Empty question")
    t_request_start = time.time()

    pid = req.project_id or 0

    # v0.21: нормализованная ОБЛАСТЬ ПОИСКА (snapshot для trace/истории; явный ui-scope управляет ретривом).
    from proxy.services.scope_service import resolve_scope
    _scope_snap = resolve_scope(scope=req.scope, project_id=req.project_id,
                                dataset_ids=req.dataset_ids, dataset_filter=req.dataset_filter)
    if isinstance(req.scope, dict) and req.scope.get("scope_type"):
        # явный scope из ScopeSelector приоритетнее legacy: проставляем resolved в поля, которые
        # понимает существующий конвейер (без молчаливого fallback на «весь RAG»).
        if _scope_snap["resolved_dataset_ids"]:
            req.dataset_ids = _scope_snap["resolved_dataset_ids"]
        if _scope_snap["scope_type"] == "project" and _scope_snap["project_ids"]:
            req.project_id = _scope_snap["project_ids"][0]
            pid = req.project_id

    # Resolve one persistent profile snapshot before any professional route.
    from proxy.services.chat_profile_service import resolve_chat_profile

    try:
        _profile_snapshot = resolve_chat_profile(
            session_id=req.session_id,
            requested_mode=req.mode,
            requested_revision_id=req.profile_revision_id,
            apply_revision=bool(req.apply_profile_revision),
        )
    except ValueError as error:
        raise HTTPException(409, f"Профиль чата не применён: {error}") from error
    req.mode = str(_profile_snapshot.get("mode") or "agent")

    # ── МАРШРУТИЗАЦИЯ ЧЕРЕЗ ProfileResolver (Codex §10.1A: единый контракт) ──
    # Все источники выбора пути сводятся к ОДНОЙ ProfileResolution. Явный режим → профиль,
    # а фактически выбранный канал уточняет резолюцию через refine. Так «какой канал дёрнут» — один записанный контракт
    # (query_route.profile), а не неявный control-flow. Резолвер сам не отвечает (§10.3 №4).
    from proxy.services.profile_resolver import (
        resolve as _resolve_profile, route_source_for_channel)
    _resolution = _resolve_profile(mode=req.mode, question=req.question)
    _PROFILE = _resolution.profile_id
    # Model-final-only invariant: свободный запрос не может завершиться ответом
    # regex/SQL/Python обработчика. Код читает, ищет, считает и проверяет внутри
    # evidence/tool loop; видимый ответ формулирует модель.
    def _profile_route(channel: str, operation: str | None, *,
                       base: dict | None = None, source: str | None = None) -> dict:
        """query_route c честным profile-трейсом: refine резолюции выбранным каналом + as_trace.
        Профиль не меняется — фиксируем КАК принят маршрут и КАКОЙ канал."""
        _resolution.refine(route_source=(source or route_source_for_channel(channel)),
                            channel=channel, operation=operation)
        route = dict(base or {})
        route["channel"] = channel
        if operation is not None:
            route["operation"] = operation
        route["profile"] = _resolution.as_trace()
        route["profile_snapshot"] = {
            key: _profile_snapshot.get(key)
            for key in (
                "revision_id", "mode", "name", "revision_no", "prompt_revision_id",
                "prompt_sha256", "skill_revision_id", "skill_sha256", "tools",
            )
        }
        return route

    # W11.17: /-команды (палитра). rewrite → переформулировать и пройти конвейером; иначе — детерм. ответ.
    from proxy.services.command_service import handle_command, is_command
    if is_command(req.question):
        cmd_res = handle_command(req.question, project_id=pid)
        if cmd_res and cmd_res.get("rewrite"):
            req.question = cmd_res["rewrite"]
        elif cmd_res is not None:
            cmd_payload = dict(cmd_res.get("command") or {})
            if cmd_payload.get("action") == "generate_filled_form":
                from proxy.services.ks_forms_chat_service import answer_ks_forms_query

                ks_res = await asyncio.to_thread(
                    answer_ks_forms_query,
                    f"собери {cmd_payload.get('form_id')}",
                    project_id=int(pid) if pid else None,
                    session_id=str(req.session_id or ""),
                    fmt=str(cmd_payload.get("fmt") or "xlsx"),
                )
                return {
                    "answer": ks_res.get("answer") or cmd_res["answer"],
                    "crag_status": "DETERMINISTIC",
                    "sources": [],
                    "query_route": _profile_route(
                        "ks_forms", "filled" if ks_res.get("ok") else "clarify"
                    ),
                    "validation": {"enabled": False, "reason": "deterministic_ks_forms"},
                    "command": ks_res.get("command") or cmd_payload,
                }
            return {
                "answer": cmd_res["answer"],
                "crag_status": "DETERMINISTIC",
                "sources": [],
                "query_route": _profile_route("command", (cmd_res.get("command") or {}).get("action")),
                "validation": {"enabled": False, "reason": "deterministic_command"},
                "command": cmd_payload,
            }

    from proxy.services.ks_forms_chat_service import (
        answer_ks_forms_query,
        is_ks_forms_query,
    )
    if is_ks_forms_query(req.question):
        ks_res = await asyncio.to_thread(
            answer_ks_forms_query,
            req.question,
            project_id=int(pid) if pid else None,
            session_id=str(req.session_id or ""),
        )
        return {
            "answer": ks_res.get("answer") or "",
            "crag_status": "DETERMINISTIC",
            "sources": [],
            "query_route": _profile_route(
                "ks_forms", "filled" if ks_res.get("ok") else "clarify"
            ),
            "validation": {"enabled": False, "reason": "deterministic_ks_forms"},
            "command": ks_res.get("command"),
        }

    # Операторские заметки не создаются, не читаются и не подмешиваются в чат.
    # Контекст ниже содержит только явное вложение, LES.md, typed dataset passport
    # и историю текущей сессии, которую читает модель.
    memory_block = ""
    if req.attachment_context:
        attachment_block = (
            "Контекст прикреплённого файла (read-mode, не индекс):\n"
            f"{req.attachment_context}"
        )
        memory_block = attachment_block + ("\n\n" + memory_block if memory_block else "")
    # LES.md: контекст папки/проекта — ВСЕГДА (как CLAUDE.md для harness). Симметрия датасет↔проект
    # (#2): если выбран ДАТАСЕТ без проекта (pid=0), резолвим его объект и подмешиваем тот же LES.md,
    # что и в режиме проекта — иначе режим датасета терял контекст (системы/стадия/состав папки).
    _les_pid = pid
    if not _les_pid and req.dataset_ids:
        try:
            from proxy.services.project_service import project_for_dataset
            _les_pid = project_for_dataset(req.dataset_ids[0]) or 0
        except Exception:  # noqa: BLE001
            _les_pid = 0
    if _les_pid:
        try:
            from proxy.services.les_md_service import context_for_chat
            les_md_block = context_for_chat(_les_pid)
            if les_md_block:
                memory_block = les_md_block + ("\n\n" + memory_block if memory_block else "")
                logger.info("[LES.md] подмешан контекст объекта #%s (%s симв.; scope=%s)",
                            _les_pid, len(les_md_block), "project" if pid else "dataset")
        except Exception as err:  # noqa: BLE001
            logger.warning("[LES.md] context inject failed: %s", err)
    if memory_block:
        logger.info("[MEMORY] подмешано %s символов рабочей памяти", len(memory_block))
    # «Запоминать всё»: история диалога текущей сессии в промпт (чат потурно безсостоятельный).
    # Только в промпт LLM, НЕ дописываем к детерминированным ответам (это были бы простыни).
    try:
        session_block = session_memory(req.session_id)
    except Exception as err:
        logger.warning("[MEMORY] session recall failed: %s", err)
        session_block = ""

    rag_backend = state.backend

    # W17.1: двойной режим. Если задан project_id и пользователь не выбрал датасеты
    # явно — сужаем ретрив к датасетам объекта (режим проекта). Нет project_id или
    # нет привязанных датасетов → обычный RAG (поведение неизменно). Явный выбор
    # пользователя приоритетнее проекта.
    effective_dataset_ids = req.dataset_ids
    if req.project_id and not req.dataset_ids:
        try:
            from proxy.services.project_service import project_dataset_ids
            scope = await asyncio.to_thread(project_dataset_ids, req.project_id)
            if scope:
                effective_dataset_ids = scope
                logger.info("[PROJECT] режим объекта %s → датасеты %s", req.project_id, scope)
        except Exception as proj_err:
            logger.warning("[PROJECT] scope resolve failed: %s", proj_err)

    query_intent = route_query(
        req.question,
        dataset_filter=req.dataset_filter,
        dataset_ids=effective_dataset_ids,
    )
    kot_decision = analyze_question(req.question)
    effective_dataset_filter = req.dataset_filter or query_intent.dataset_filter or kot_decision.dataset_filter
    logger.info(
        "[QUERY_ROUTER] channel=%s reason=%s filter=%s",
        query_intent.channel,
        query_intent.reason,
        effective_dataset_filter,
    )
    # ADR-12: мультикласс через диалог — чипы-варианты для прочих распознанных классов.
    # (retrieval_trace тут ещё не инициализирован — пишем класс-метки в трейс ниже, после retrieve.)
    class_suggestions = build_class_suggestions(req.question, primary_filter=effective_dataset_filter)

    if req.dataset_ids:
        scope_source = "explicit_dataset_ids"
    elif req.dataset_filter:
        scope_source = "explicit_dataset_filter"
    elif req.project_id:
        scope_source = "explicit_project"
    elif effective_dataset_filter:
        scope_source = "inferred_filter"
    else:
        scope_source = "all_corpus"
    scope_resolution: dict[str, Any] = {}
    _dataset_ids = await resolve_dataset_ids(
        rag_backend,
        effective_dataset_ids,
        effective_dataset_filter,
        logger,
        question=req.question,
        resolution_trace=scope_resolution,
        scope_source=scope_source,
    )
    dataset_name_by_id = await _dataset_name_map(rag_backend)
    resolved_dataset_names = _names_for_dataset_ids(_dataset_ids, dataset_name_by_id)
    target_file_ref: dict[str, Any] | None = None
    target_file_refs: list[dict[str, Any]] = []
    target_doc_filter: list[str] = []
    if _dataset_ids:
        explicit_targets = list(req.target_files or [])
        if req.target_file:
            explicit_targets.insert(0, req.target_file)
        target_queries = list(dict.fromkeys(explicit_targets)) or [req.question]
        for target_query in target_queries:
            resolved_ref = await asyncio.to_thread(
                resolve_inventory_file_reference,
                target_query,
                [str(d) for d in _dataset_ids],
            )
            if not resolved_ref:
                continue
            target_file_refs.append(resolved_ref)
            if resolved_ref.get("match_status") == "matched" and resolved_ref.get("file_name"):
                target_doc_filter.append(str(resolved_ref["file_name"]))
            elif resolved_ref.get("match_status") == "ambiguous":
                logger.info("[FILE_TARGET] ambiguous file reference: %s", resolved_ref.get("match_count"))
        target_doc_filter = list(dict.fromkeys(target_doc_filter))
        if len(target_file_refs) == 1:
            target_file_ref = target_file_refs[0]
        if target_doc_filter:
            logger.info("[FILE_TARGET] question scoped to %s explicit files", len(target_doc_filter))
    try:
        context_memory_block = build_context_memory_block(
            session_id=req.session_id,
            dataset_ids=_dataset_ids,
            dataset_names=resolved_dataset_names,
            storage_root=Path("./storage/datasets"),
            # Typed dataset memory is added once by the evidence application.
            # Rebuilding the deep dataset profile here duplicated navigation and
            # cost 30-40 seconds on BAI before retrieval even started.  Keep only
            # the cheap chat-session passport in this layer.
            max_datasets=0,
        )
        if context_memory_block:
            memory_block = memory_block + ("\n\n" if memory_block else "") + context_memory_block
            logger.info("[CONTEXT_MEMORY] подмешан паспорт чата/датасетов (%s симв.)", len(context_memory_block))
    except Exception as err:  # навигационная память не должна блокировать RAG
        logger.warning("[CONTEXT_MEMORY] prompt block skipped: %s", err)

    # W11.15 used to auto-hijack broad chat questions ("расскажи про проект") into a
    # deterministic project register. That made LES look like a file inventory instead of a
    # notebook/RAG synthesis. Project summary stays available as an explicit command/MCP tool,
    # but normal chat questions now continue into retrieval + model.

    query_route_payload = _query_route_payload(query_intent, effective_dataset_filter, kot_decision)
    query_route_payload["scope"] = _scope_snap   # v0.21: где реально искали (snapshot для trace/истории)
    if target_file_ref:
        query_route_payload["target_file"] = target_file_ref
    if target_file_refs:
        query_route_payload["target_files"] = target_file_refs
    study_requested = bool(req.dataset_ids or effective_dataset_filter) and is_notebook_study_query(req.question)
    inventory_requested = bool(req.dataset_ids or effective_dataset_filter) and is_project_inventory_query(req.question)
    if study_requested:
        query_route_payload["breadth"] = "wide"
        query_route_payload["notebook_study_requested"] = True
    if inventory_requested:
        query_route_payload["inventory_requested"] = True
    topic_retrieval_plan: dict[str, Any] = {}
    topic_doc_filter: list[str] = []
    if _dataset_ids and not target_doc_filter:
        try:
            topic_memories = await asyncio.to_thread(
                lambda: [get_typed_dataset_memory(str(dataset_id)) for dataset_id in _dataset_ids]
            )
            topic_retrieval_plan = await asyncio.to_thread(
                select_topic_retrieval_plan,
                topic_memories,
                req.question,
            )
            topic_doc_filter = [
                str(item.get("file_name") or "")
                for item in (topic_retrieval_plan.get("selected_files") or [])
                if str(item.get("file_name") or "").strip()
            ]
            topic_doc_filter = list(dict.fromkeys(topic_doc_filter))
            if topic_doc_filter:
                query_route_payload["topic_selection"] = {
                    "schema": topic_retrieval_plan.get("schema"),
                    "selected_topics": topic_retrieval_plan.get("selected_topics") or [],
                    "selected_files": topic_retrieval_plan.get("selected_files") or [],
                    "selected_sections": topic_retrieval_plan.get("selected_sections") or [],
                    "fallback": topic_retrieval_plan.get("fallback"),
                }
        except Exception as topic_err:  # noqa: BLE001
            logger.warning("[TOPIC_RETRIEVAL] topic selection skipped: %s", topic_err)
            topic_retrieval_plan = {
                "schema": "dataset_topic_selection_v1",
                "status": "skipped",
                "error": f"{type(topic_err).__name__}: {topic_err}",
            }
    # #2: финальный resolved-канал = семантический RAG. default_rag (ни команда/regex/каскад
    # не поймали) → честный fallback; иначе keyword (route_query поймал по словарю). profile-
    # трейс кладём в payload — как у детерминированных каналов выше: один контракт в каждом route.
    if _resolution.route_source == "explicit_mode":
        _resolution.channel = query_intent.channel
        _resolution.operation = query_intent.reason
    else:
        _resolution.refine(
            route_source=("fallback" if query_intent.reason == "default_rag" else "keyword"),
            channel=query_intent.channel,
            operation=query_intent.reason,
        )
    query_route_payload["profile"] = _resolution.as_trace()
    query_route_payload["profile_snapshot"] = {
        key: _profile_snapshot.get(key)
        for key in (
            "revision_id", "mode", "name", "revision_no", "prompt_revision_id",
            "prompt_sha256", "skill_revision_id", "skill_sha256", "tools",
        )
    }
    cache = SemanticCache()
    cache_embedding = None
    cache_scope = ""
    cache_marker = "miss"

    use_semantic_cache = (
        req.semantic_cache_enabled
        if req.semantic_cache_enabled is not None
        else semantic_cache_enabled()
    )
    if study_requested or inventory_requested or target_doc_filter or topic_doc_filter:
        # Broad project/object questions must re-read the selected area. A cached short RAG table
        # turns "расскажи про объект" into a stale narrow answer and hides the broad reading layer.
        # File-register questions need fresh MetaDB inventory, not an old aggregate RAG answer.
        # File-target questions must stay scoped to the named document.
        # Topic-guided retrieval must not be bypassed by a previous flat semantic-cache answer.
        use_semantic_cache = False
    use_validation = (
        req.validation_enabled
        if req.validation_enabled is not None
        else chat_validation_enabled()
    )
    validation_skip_reason = ""
    if req.validation_enabled is None and (study_requested or inventory_requested):
        # Broad project/inventory answers are grounded by source-map plus deterministic
        # MetaDB inventory/artifact. Running TOSKA over the full synthesized report added
        # 30-40s on BAI while not improving the operator-facing evidence boundary.
        use_validation = False
        validation_skip_reason = "broad_project_inventory_fast_path"
        query_route_payload["validation_policy"] = {
            "enabled": False,
            "reason": validation_skip_reason,
            "evidence": "source_map+project_inventory_artifact",
        }

    table_result = None

    _gen_semaphore = generation_semaphore(state.llm_semaphore)
    admission = evaluate_chat_admission(
        current_mode=state.current_mode,
        metrics_cache=state.metrics_cache,
        active_jobs=count_active_jobs(state.job_service, state.job_tracker) + _active_dispatcher_reindex_jobs(state),
        llm_available=getattr(_gen_semaphore, "_value", 1) > 0,
    )
    if not admission.allowed:
        raise HTTPException(status_code=admission.status_code, detail=admission.reason)

    if use_semantic_cache:
        try:
            datasets = await rag_backend.list_datasets()
            cache_scope = dataset_scope_key(datasets, _dataset_ids)
            cache_embedding = await embed_question(rag_backend, req.question)
            if cache_embedding:
                cache_hit = cache.lookup(
                    req.question,
                    cache_scope,
                    cache_embedding,
                    semantic_cache_threshold(),
                )
                if cache_hit:
                    cache_trace = {
                        "mode": "cache",
                        "vector_count": 0,
                        "lexical_count": 0,
                        "merged_count": 0,
                        "retry_count": 0,
                        "quality_status": "cache_hit",
                    }
                    history_id = None
                    state.crag_stats["verified"] += 1
                    state.chat_metrics["latency_search"].append(0.0)
                    state.chat_metrics["latency_gen"].append(0.0)
                    state.chat_metrics["tokens"].append(0)
                    state.chat_metrics["crag_pass"] += 1
                    for key in ("latency_search", "latency_gen", "tokens"):
                        state.chat_metrics[key] = state.chat_metrics[key][-100:]
                    try:
                        history_id = save_chat_history(
                            question=req.question,
                            answer=cache_hit.answer,
                            sources=cache_hit.sources,
                            crag_status="VERIFIED",
                            latency_sec=0.0,
                            tokens=0,
                            session_id=req.session_id,
                            requested_dataset_filter=req.dataset_filter,
                            effective_dataset_filter=effective_dataset_filter,
                            resolved_dataset_ids=_dataset_ids,
                            resolved_dataset_names=resolved_dataset_names,
                            source_dataset_ids=_dataset_ids,
                            source_dataset_names=resolved_dataset_names,
                            query_route=query_route_payload,
                            retrieval_trace=cache_trace,
                            cache_type=cache_hit.cache_type,
                            validation_enabled=use_validation,
                            success=1,
                        )
                    except Exception as db_err:
                        logger.warning("[CHAT] History save error: %s", db_err)
                    logger.info("[SEM_CACHE] hit similarity=%.3f", cache_hit.similarity)
                    state.chat_metrics["cache_hit"] = state.chat_metrics.get("cache_hit", 0) + 1
                    return {
                        "answer": cache_hit.answer,
                        "crag_status": "VERIFIED",
                        "sources": cache_hit.sources,
                        "effective_dataset_filter": effective_dataset_filter,
                        "query_route": query_route_payload,
                        "retrieval_trace": cache_trace,
                        "cache": cache_hit.cache_type,
                        "similarity": round(cache_hit.similarity, 3),
                        "history_id": history_id,
                    }
        except Exception as cache_err:
            logger.warning("[SEM_CACHE] lookup skipped: %s", cache_err)

    evidence_request = EvidenceRequestContext(
        req=req,
        dataset_ids=_dataset_ids,
        scope_resolution=scope_resolution,
        effective_dataset_filter=effective_dataset_filter,
        resolved_dataset_names=resolved_dataset_names,
        dataset_name_by_id=dataset_name_by_id,
        query_route_payload=query_route_payload,
        target_doc_filter=target_doc_filter,
        target_file_ref=target_file_ref,
        topic_doc_filter=topic_doc_filter,
        topic_retrieval_plan=topic_retrieval_plan,
        inventory_requested=inventory_requested,
        study_requested=study_requested,
        memory_block=memory_block,
        session_block=session_block,
        class_suggestions=class_suggestions,
        use_semantic_cache=use_semantic_cache,
        use_validation=use_validation,
        validation_skip_reason=validation_skip_reason,
        route=query_intent,
        table_result=table_result,
        request_started_at=t_request_start,
        profile_snapshot=_profile_snapshot,
    )
    evidence_runtime = EvidenceRuntimeDeps(
        state=state,
        rag_backend=rag_backend,
        cache=cache,
        cache_embedding=cache_embedding,
        cache_marker=cache_marker,
        cache_scope=cache_scope,
        assistant_text=_assistant_text,
        augment_model_tool_args=_augment_model_tool_args,
        chat_model_final_answer=_chat_model_final_answer,
        cloud_body_for_model=_cloud_body_for_model,
        compact_tool_result_for_prompt=_compact_tool_result_for_prompt,
        dataset_ids_from_chunks=_dataset_ids_from_chunks,
        dataset_sensitivities=_dataset_sensitivities,
        env_bool=_env_bool,
        env_float=_env_float,
        env_int=_env_int,
        expand_context_windows=expand_context_windows,
        format_tool_results_for_model=_format_tool_results_for_model,
        generation_token_budget=_generation_token_budget,
        llm_runtime=_llm_runtime,
        local_context_budget=_local_context_budget,
        mlx_runtime=_mlx_runtime,
        names_for_dataset_ids=_names_for_dataset_ids,
        notebook_study_validation_status=_notebook_study_validation_status,
        ollama_native_complete=_ollama_native_complete,
        parse_model_tool_calls=_parse_model_tool_calls,
        prepare_notebook_reader_memory=_prepare_notebook_reader_memory,
        record_cloud_cost=_record_cloud_cost,
        retrieve_chat_chunks=retrieve_chat_chunks,
        source_excerpts=source_excerpts,
        table_query_response=_table_query_response,
        cloud_fallback_models=cloud_fallback_models,
        cloud_model_timeout=cloud_model_timeout,
        model_connection_resolver=_model_connection_resolver,
        model_connection_transport=lambda client, secret_store: OpenAICompatibleTransport(
            client=client,
            secret_store=secret_store,
        ),
        workbook_tool_executor=_execute_chat_workbook_tool,
    )
    response_boundary = ResponseBoundary(
        save_chat_history=save_chat_history,
        token_sink=token_sink,
        version_stamp=_version_stamp,
    )
    return await run_chat_evidence_application(
        evidence_request,
        evidence_runtime,
        response_boundary,
    )
