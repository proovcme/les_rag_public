"""Application flows for model-first smeta chat requests.

The model owns every estimating decision inside ``run_vor_pdf_workflow``.  This
module only coordinates the server-owned attachment, model transport, progress
events, deterministic calculation/export and the response envelope consumed by
the generic chat router.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx

from proxy.services.chat_attachment_service import (
    consume_read_attachment,
    resolve_read_attachment,
)
from proxy.services.smeta_user_message_service import format_document_lsr_message
from proxy.services.smeta_artifact_service import (
    build_checked_rim_form_from_visible_rows,
    build_smeta_artifact,
    build_smeta_artifact_from_rim_form,
    compact_smeta_answer,
    persist_smeta_artifact_exports,
)
from proxy.smeta_core.document_workflow import run_vor_document_workflow


logger = logging.getLogger(__name__)

SMETA_ARTIFACT_DIR = Path("storage/smeta_artifacts")
SMETA_DOCUMENT_HEARTBEAT_SEC = 15.0

ModelExchange = Callable[[list[dict], list[dict]], dict[str, Any]]
MappingModelExchange = Callable[[list[dict], dict[str, Any]], dict[str, Any]]
TokenSink = Callable[[dict[str, Any]], Awaitable[None]]


def _source_fingerprint(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    stat = path.stat()
    return {
        "sha256": digest.hexdigest(),
        "size": stat.st_size,
    }


def _checkpoint_path(root: Path, attachment_id: str) -> Path:
    safe_id = "".join(
        char for char in str(attachment_id)
        if char.isalnum() or char in {"-", "_"}
    )
    if not safe_id:
        raise ValueError("attachment_id has no safe checkpoint characters")
    return root / ".checkpoints" / f"{safe_id}.json"


def _load_document_checkpoint(
    path: Path,
    *,
    source_fingerprint: dict[str, Any],
) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if envelope.get("schema") != "les.smeta-document-checkpoint.v1":
        return None
    if envelope.get("source_fingerprint") != source_fingerprint:
        return None
    agent_result = envelope.get("agent_result")
    return dict(agent_result) if isinstance(agent_result, dict) else None


def _write_document_checkpoint(
    path: Path,
    *,
    source_fingerprint: dict[str, Any],
    agent_result: dict[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    envelope = {
        "schema": "les.smeta-document-checkpoint.v1",
        "source_fingerprint": source_fingerprint,
        "agent_result": agent_result,
    }
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(envelope, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    temp.replace(path)


@dataclass(frozen=True)
class SmetaDocumentApplicationResult:
    """Mode reply fields returned to the generic chat response builder."""

    answer: str
    operation: str
    channel: str
    crag: str
    extra: dict[str, Any]


SmetaApplicationResult = SmetaDocumentApplicationResult


@dataclass(frozen=True)
class SmetaDirectDependencies:
    """Existing model-owned smeta operations injected without changing them."""

    rag_context: Callable[..., Awaitable[dict[str, Any]]]
    norm_lookup: Callable[[str], dict[str, Any]]
    norm_choice: Callable[[str, dict[str, Any], Callable[[dict[str, Any]], None] | None], dict[str, Any]]
    model_answer: Callable[[str, str], str]
    active_state: Callable[[str, str], dict[str, Any]]
    model_runtime: Callable[[], Any]


def default_smeta_direct_dependencies(
    *, active_state: Callable[[str, str], dict[str, Any]] | None = None
) -> SmetaDirectDependencies:
    """Ready smeta adapters; the HTTP router does not own prompts or transport."""

    from proxy.services import smeta_chat_adapter_service as adapters

    return SmetaDirectDependencies(
        rag_context=adapters._smeta_direct_rag_context,
        norm_lookup=adapters._smeta_direct_norm_lookup_context,
        norm_choice=adapters._smeta_direct_structured_norm_choice,
        model_answer=adapters._smeta_direct_model_answer,
        active_state=active_state or (lambda _question, _answer: {}),
        model_runtime=lambda: adapters._smeta_model_runtime("LES_SMETA_DIRECT_MODEL_PROVIDER"),
    )


def retry_smeta_transport(
    call: Callable[[], Any],
    *,
    on_attempt: Callable[[], None],
    attempts: int = 3,
) -> Any:
    """Retry provider transport only; never invent or alter model decisions."""

    result: Any = None
    last_error: Exception | None = None
    for _ in range(max(1, attempts)):
        on_attempt()
        try:
            result = call()
        except (TimeoutError, httpx.TimeoutException):
            # Один уже истёкший длинный model-call нельзя незаметно повторять ещё
            # два раза: пользователь должен получить явный результат и retry сам.
            raise
        except Exception as error:  # short provider failure is retried, then reported
            last_error = error
            continue
        if result:
            return result
    if last_error is not None:
        raise last_error
    return result


async def run_smeta_direct_application(
    *,
    request: Any,
    harness_question: str,
    rag_backend: Any,
    router_state: Any,
    dataset_ids: list[str] | None,
    dataset_filter: str | None,
    pricing_requested: bool,
    auto_estimate_work: bool,
    dependencies: SmetaDirectDependencies,
    rag_context_enabled: bool = True,
    token_sink: TokenSink | None = None,
    artifact_dir: str | Path = SMETA_ARTIFACT_DIR,
) -> SmetaApplicationResult:
    """Run the ordinary model-first smeta flow outside the HTTP router.

    This is a one-for-one application extraction: the injected model/RAG
    operations retain their existing prompts, limits and decision ownership.
    """

    async def emit_step(phase: str, status: str, label: str, **payload: Any) -> None:
        data = {"phase": phase, "status": status, "label": label, **payload}
        logger.info(
            "[SMETA_STEP] %s %s label=%s extra=%s",
            phase,
            status,
            label,
            {k: v for k, v in payload.items() if k not in {"prompt", "context"}},
        )
        if token_sink is not None:
            try:
                await token_sink({"event": "smeta_step", "data": data})
            except Exception as error:  # telemetry must not abort the estimate
                logger.warning("[SMETA_STEP] stream sink failed: %s", error)

    smeta_dataset_ids = dataset_ids
    if request.project_id and not request.dataset_ids:
        try:
            from proxy.services.project_service import project_dataset_ids

            project_scope = await asyncio.to_thread(project_dataset_ids, request.project_id)
            if project_scope:
                smeta_dataset_ids = project_scope
        except Exception as error:
            logger.warning("[PROJECT] smeta scope resolve failed: %s", error)
    try:
        from proxy.services.system_dataset_service import module_dataset_ids

        system_scope = await asyncio.to_thread(module_dataset_ids, "smeta")
        if system_scope:
            smeta_dataset_ids = list(dict.fromkeys([*(smeta_dataset_ids or []), *system_scope]))
    except Exception as error:
        logger.warning("[SMETA] system dataset scope resolve failed: %s", error)

    direct_rag_packet: dict[str, Any] = {}
    has_scope = bool(smeta_dataset_ids or dataset_filter or request.project_id)
    if has_scope and rag_context_enabled:
        await emit_step(
            "rag_context",
            "started",
            "Смета: собираю RAG-контекст области",
            has_dataset_filter=bool(dataset_filter),
            dataset_ids=len(smeta_dataset_ids or []),
        )
        original_dataset_filter = request.dataset_filter
        try:
            request.dataset_filter = dataset_filter
            direct_rag_packet = await dependencies.rag_context(
                request,
                rag_backend=rag_backend,
                dataset_ids=smeta_dataset_ids,
                state=router_state,
            )
        finally:
            request.dataset_filter = original_dataset_filter
        rag_text = str(direct_rag_packet.get("text") or "").strip()
        if rag_text:
            harness_question = (
                f"{harness_question}\n\n"
                "RAG-контекст сметной области для сметного планирования "
                "(используй как источник/навигацию, не как готовую смету):\n"
                f"{rag_text}"
            )
        await emit_step(
            "rag_context",
            "done",
            "Смета: RAG-контекст области готов",
            sources=len(direct_rag_packet.get("sources") or []),
            text_chars=len(str(direct_rag_packet.get("text") or "")),
        )

    execution_mode = "priced_lsr" if pricing_requested else "answer"
    await emit_step("norm_lookup", "started", "Смета: модель формирует поисковые запросы к нормам")
    norm_lookup_packet = await asyncio.to_thread(dependencies.norm_lookup, harness_question)
    lookup_trace = norm_lookup_packet.get("trace") if isinstance(norm_lookup_packet, dict) else {}
    await emit_step(
        "norm_lookup",
        "done",
        "Смета: нормативный поиск завершён",
        lookup_status=lookup_trace.get("status") if isinstance(lookup_trace, dict) else "",
        calls=len(lookup_trace.get("results") or []) if isinstance(lookup_trace, dict) else 0,
    )

    norm_choice_packet: dict[str, Any] = {
        "rows": [],
        "trace": {"enabled": False, "status": "not_requested"},
    }
    structured_rim_form = None
    if pricing_requested:
        progress_sink: Callable[[dict[str, Any]], None] | None = None
        if token_sink is not None:
            loop = asyncio.get_running_loop()

            def progress_sink(event: dict[str, Any]) -> None:
                try:
                    future = asyncio.run_coroutine_threadsafe(token_sink(event), loop)
                    future.result(timeout=1.0)
                except Exception as error:
                    logger.warning("[SMETA] stream bridge failed: %s", error)

        await emit_step(
            "norm_choice",
            "started",
            "Смета: модель работает с найденными нормами",
            calls=len((norm_lookup_packet.get("trace") or {}).get("results") or []),
        )
        norm_choice_packet = await asyncio.to_thread(
            dependencies.norm_choice,
            harness_question,
            norm_lookup_packet.get("trace") or {},
            progress_sink,
        )
        norm_choice_trace = (
            norm_choice_packet.get("trace")
            if isinstance(norm_choice_packet.get("trace"), dict)
            else {}
        )
        await emit_step(
            "norm_choice",
            "done",
            "Смета: работа с нормами завершена",
            norm_choice_status=norm_choice_trace.get("status"),
            rows=len(norm_choice_packet.get("rows") or []),
        )
        structured_rim_form = build_checked_rim_form_from_visible_rows(
            list(norm_choice_packet.get("rows") or []),
            question=harness_question,
        )

    if pricing_requested and not structured_rim_form:
        lookup_trace = norm_lookup_packet.get("trace") or {}
        choice_trace = norm_choice_packet.get("trace") or {}
        source_rows = int(lookup_trace.get("source_rows_expected") or 0)
        lookup_calls = len(lookup_trace.get("results") or [])
        trace = {
            "mode": "smeta",
            "model_first": True,
            "direct_model_answer_present": False,
            "smeta_failure": "verified_calculation_missing",
            "smeta_rag_context": direct_rag_packet.get("trace") or {},
            "smeta_norm_lookup": lookup_trace,
            "smeta_norm_choice": choice_trace,
            "smeta_execution_mode": execution_mode,
            "smeta_dataset_filter": dataset_filter or "",
            "smeta_artifact_present": False,
        }
        return SmetaApplicationResult(
            answer=(
                "ЛСР не сформирована: сметный контур не получил проверяемых расчётных строк "
                f"(исходных строк распознано: {source_rows}, запросов к нормам выполнено: {lookup_calls}). "
                "Неподтверждённые цены, шифры и трудозатраты в результат не выпущены. "
                "Повтори расчёт; если приложен файл, он сохранён для повторной обработки."
            ),
            operation="smeta_verified_calculation_missing",
            channel="smeta_mode",
            crag="ERROR",
            extra={
                "retrieval_trace": trace,
                "sources": direct_rag_packet.get("sources") or [],
                "source_map": direct_rag_packet.get("source_map") or [],
            },
        )

    structured_rim_context = ""
    if structured_rim_form:
        structured_rim_context = "CHECKED RIM CALCULATION FROM MODEL-SELECTED NORM CODES:\n" + json.dumps(
            {
                "schema": structured_rim_form.get("schema"),
                "amount_total": structured_rim_form.get("amount_total"),
                "finality": structured_rim_form.get("finality"),
                "pricebook": structured_rim_form.get("pricebook"),
                "rows": structured_rim_form.get("rows"),
                "trace_summary": (structured_rim_form.get("trace") or {}).get("summary"),
            },
            ensure_ascii=False,
            default=str,
        )
    model_context = "\n\n".join(
        item
        for item in (
            str(direct_rag_packet.get("text") or "").strip(),
            str(norm_lookup_packet.get("text") or "").strip(),
            structured_rim_context,
        )
        if item
    )
    await emit_step(
        "final_answer",
        "started",
        "Смета: модель готовит видимый ответ",
        execution_mode=execution_mode,
    )
    answer = await asyncio.to_thread(dependencies.model_answer, harness_question, model_context)
    await emit_step(
        "final_answer",
        "done" if answer else "error",
        "Смета: видимый ответ готов" if answer else "Смета: модель не вернула видимый ответ",
        answer_chars=len(str(answer or "")),
    )

    if not answer:
        runtime = dependencies.model_runtime()
        configured_provider = (
            os.getenv("LES_SMETA_DIRECT_MODEL_PROVIDER", "").strip().lower()
            or os.getenv("LES_SMETA_PROVIDER", "").strip().lower()
            or os.getenv("LES_LLM_PROVIDER", "mlx").strip().lower()
            or "mlx"
        )
        cloud_warning = ""
        if configured_provider in {
            "openai", "openai-compatible", "openai_compatible", "openrouter"
        } and runtime.provider == "mlx":
            cloud_warning = "cloud_provider_without_api_key_fell_back_to_mlx"
        trace = {
            "mode": "smeta",
            "model_first": True,
            "direct_model_answer_present": False,
            "smeta_failure": "llm_returned_empty_or_failed",
            "configured_provider": configured_provider,
            "effective_provider": runtime.provider,
            "effective_model": runtime.model,
            "cloud_config_warning": cloud_warning,
            "smeta_rag_context": direct_rag_packet.get("trace") or {},
            "smeta_norm_lookup": norm_lookup_packet.get("trace") or {},
            "smeta_norm_choice": norm_choice_packet.get("trace") or {},
            "smeta_dataset_filter": dataset_filter or "",
            "smeta_execution_mode": execution_mode,
            "code_fallback_disabled": True,
        }
        return SmetaApplicationResult(
            answer=(
                "Сметный ответ не сгенерирован: модель не вернула текст или вызов модели упал. "
                "Кодовый fallback для ЛСР/ВОР отключён, чтобы не подменять модель hardcoded-ответом. "
                "Проверь провайдера/ключ и повтори запрос."
            ),
            operation="smeta_model_failed",
            channel="smeta_mode",
            crag="ERROR",
            extra={
                "retrieval_trace": trace,
                "sources": direct_rag_packet.get("sources") or [],
                "source_map": direct_rag_packet.get("source_map") or [],
            },
        )

    model_artifact = build_smeta_artifact(answer, question=request.question)
    structured_artifact = (
        build_smeta_artifact_from_rim_form(structured_rim_form, question=request.question)
        if structured_rim_form
        else None
    )
    smeta_artifact = persist_smeta_artifact_exports(
        structured_artifact or model_artifact,
        output_dir=Path(artifact_dir),
    )
    visible_answer = compact_smeta_answer(answer, smeta_artifact)
    trace = {
        "mode": "smeta",
        "model_first": True,
        "direct_model_answer_present": bool(answer),
        "active_smeta_state": dependencies.active_state(harness_question, answer),
        "smeta_rag_context": direct_rag_packet.get("trace") or {},
        "smeta_norm_lookup": norm_lookup_packet.get("trace") or {},
        "smeta_norm_choice": norm_choice_packet.get("trace") or {},
        "smeta_structured_rim_trace": (structured_rim_form or {}).get("trace") or {},
        "smeta_execution_mode": execution_mode,
        "smeta_dataset_filter": dataset_filter or "",
        "smeta_artifact_present": bool(smeta_artifact),
    }
    return SmetaApplicationResult(
        answer=visible_answer,
        operation="smeta_auto_work" if auto_estimate_work else "smeta",
        channel="smeta_mode",
        crag="DETERMINISTIC",
        extra={
            "retrieval_trace": trace,
            **({"artifact": smeta_artifact} if smeta_artifact else {}),
            "sources": direct_rag_packet.get("sources") or [],
            "source_map": direct_rag_packet.get("source_map") or [],
        },
    )


async def run_smeta_document_application(
    *,
    attachment_id: str,
    user_request: str,
    model_exchange: ModelExchange | None = None,
    model_mapping_exchange: MappingModelExchange | None = None,
    model_provider: str | None = None,
    model_name: str | None = None,
    cloud_provider: bool | None = None,
    token_sink: TokenSink | None = None,
    artifact_dir: str | Path = SMETA_ARTIFACT_DIR,
) -> SmetaDocumentApplicationResult | None:
    """Build one zero-state PDF/XLSX LSR or return ``None`` for another attachment.

    A failed run deliberately leaves the attachment in place for a retry.  It is
    consumed only after the XLSX and trace were produced successfully.
    """

    from proxy.services.smeta_agent_runner_service import (
        build_smeta_agent_runner,
        normalize_smeta_agent_engine,
    )

    agent_engine = normalize_smeta_agent_engine(os.getenv("LES_SMETA_AGENT_ENGINE", "native"))
    use_default_exchange = model_exchange is None
    if agent_engine == "native" and (
        model_exchange is None or model_provider is None or model_name is None or cloud_provider is None
    ):
        from backend.inference.routing import is_cloud_provider
        from proxy.services import smeta_chat_adapter_service as adapters

        runtime = adapters._smeta_model_runtime("LES_SMETA_DOCUMENT_PROVIDER")
        model_exchange = model_exchange or adapters._smeta_document_exchange
        model_provider = model_provider or runtime.provider
        model_name = model_name or runtime.model
        if cloud_provider is None:
            cloud_provider = is_cloud_provider(runtime.provider)
        if use_default_exchange and model_mapping_exchange is None:
            model_mapping_exchange = adapters._smeta_document_mapping_exchange
    elif agent_engine == "qwen_agent":
        model_provider = "ollama"
        model_name = os.getenv("LES_SMETA_QWEN_MODEL", "qwen3.5:9b").strip() or "qwen3.5:9b"
        cloud_provider = False
    elif agent_engine == "google_adk":
        model_provider = "google"
        model_name = os.getenv("LES_SMETA_GOOGLE_MODEL", "gemini-3.5-flash").strip() or "gemini-3.5-flash"
        cloud_provider = True

    try:
        source_path, attachment_meta = await asyncio.to_thread(
            resolve_read_attachment, attachment_id
        )
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as error:
        return SmetaDocumentApplicationResult(
            answer=f"Не могу открыть исходное вложение для ЛСР: {error}. Прикрепи файл заново.",
            operation="smeta_document_attachment_missing",
            channel="smeta_mode",
            crag="ERROR",
            extra={"retrieval_trace": {"mode": "smeta_document", "error": str(error)}},
        )

    if source_path.suffix.lower() not in {".pdf", ".xlsx", ".xlsm"}:
        return None

    out_dir = Path(artifact_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    source_fingerprint = await asyncio.to_thread(_source_fingerprint, source_path)
    checkpoint_path = _checkpoint_path(out_dir, attachment_id)
    resume_agent_result = await asyncio.to_thread(
        _load_document_checkpoint,
        checkpoint_path,
        source_fingerprint=source_fingerprint,
    )
    stamp = f"{attachment_id}_{int(time.time() * 1000)}"
    xlsx_path = out_dir / f"LSR_{stamp}.xlsx"
    report_path = out_dir / f"LSR_{stamp}.json"

    if token_sink is not None:
        await token_sink({
            "event": "smeta_step",
            "data": {
                "phase": "document_workflow",
                "status": "started",
                "label": "Смета: читаю исходный документ с нуля и собираю ЛСР",
            },
        })

    loop = asyncio.get_running_loop()
    model_calls = 0
    started = time.monotonic()
    cancel_requested = threading.Event()

    def admit_model_call() -> None:
        nonlocal model_calls
        model_calls += 1

    def exchange(messages: list[dict], tools: list[dict]) -> dict[str, Any]:
        if model_exchange is None:
            raise RuntimeError(f"native exchange is unavailable for agent engine {agent_engine}")
        if cancel_requested.is_set():
            raise RuntimeError("smeta document workflow cancelled by user")
        result = retry_smeta_transport(
            lambda: model_exchange(messages, tools),
            on_attempt=admit_model_call,
        )
        if cancel_requested.is_set():
            raise RuntimeError("smeta document workflow cancelled by user")
        if not result:
            raise RuntimeError("smeta model returned no native tool response after transport retry")
        return result

    def mapping_exchange(
        messages: list[dict], schema: dict[str, Any],
    ) -> dict[str, Any]:
        if model_mapping_exchange is None:
            raise RuntimeError("structured smeta mapping transport is unavailable")
        if cancel_requested.is_set():
            raise RuntimeError("smeta document workflow cancelled by user")
        admit_model_call()
        result = model_mapping_exchange(messages, schema)
        if cancel_requested.is_set():
            raise RuntimeError("smeta document workflow cancelled by user")
        if not result:
            raise RuntimeError("smeta model returned no structured mapping response")
        return result

    def progress(event: dict[str, Any]) -> None:
        if token_sink is None:
            return
        payload = {
            "phase": str(event.get("phase") or "document_workflow"),
            "status": "running",
            "label": "Смета: модель обрабатывает строки ВОР",
            **event,
        }
        stream_event = "smeta_row" if payload["phase"] == "row_ready" else "smeta_step"
        try:
            asyncio.run_coroutine_threadsafe(
                token_sink({"event": stream_event, "data": payload}), loop
            ).result(timeout=1.0)
        except Exception as error:  # progress telemetry must not abort the estimate
            logger.warning("[SMETA_DOCUMENT] progress bridge failed: %s", error)

    def checkpoint(agent_result: dict[str, Any]) -> None:
        _write_document_checkpoint(
            checkpoint_path,
            source_fingerprint=source_fingerprint,
            agent_result=agent_result,
        )

    try:
        agent_runner = build_smeta_agent_runner(
            agent_engine,
            cancel_check=cancel_requested.is_set,
        )
        configured_batch_size = os.getenv("LES_SMETA_DOCUMENT_BATCH_SIZE")
        if configured_batch_size is not None:
            document_batch_size = int(configured_batch_size)
        elif agent_engine == "qwen_agent":
            document_batch_size = 1
        elif (
            not cloud_provider
            and str(model_provider or "").lower() == "ollama"
            and "qwen" in str(model_name or "").lower()
        ):
            # Local Qwen + Ollama: 5-row packages leave too little room for
            # read_norms_batch before forced mapping, then truncate multi-row JSON
            # (done_reason=length). One row per package keeps evidence+serialize small.
            document_batch_size = 1
        else:
            document_batch_size = 0 if cloud_provider else 5
        document_max_turns = int(os.getenv(
            "LES_SMETA_DOCUMENT_MAX_TOOL_TURNS",
            "64" if cloud_provider else (
                # Local Qwen often burns 10 turns on catalog browse; 6 + evidence
                # preflight is enough once search/open repair exists.
                "6"
                if (
                    str(model_provider or "").lower() == "ollama"
                    and "qwen" in str(model_name or "").lower()
                )
                else "10"
            ),
        ))
        # Second full-document pass roughly doubles wall time on local 9B.
        # Keep it for cloud; local default off unless explicitly enabled.
        global_review_env = os.getenv("LES_SMETA_DOCUMENT_GLOBAL_REVIEW", "").strip().lower()
        if global_review_env in {"1", "true", "yes", "on"}:
            require_global_review = True
        elif global_review_env in {"0", "false", "no", "off"}:
            require_global_review = False
        else:
            require_global_review = bool(cloud_provider)
        soft_accept_env = os.getenv("LES_SMETA_DOCUMENT_SOFT_ACCEPT", "").strip().lower()
        if soft_accept_env in {"1", "true", "yes", "on"}:
            soft_accept = True
        elif soft_accept_env in {"0", "false", "no", "off"}:
            soft_accept = False
        else:
            # Local Ollama/Qwen: restore 0.24.48 soft blockers so LSR reaches XLSX.
            soft_accept = (
                not cloud_provider
                and str(model_provider or "").lower() == "ollama"
                and "qwen" in str(model_name or "").lower()
            )
        workflow_task = asyncio.create_task(asyncio.to_thread(
            run_vor_document_workflow, source_path,
            exchange=exchange,
            mapping_exchange=mapping_exchange if model_mapping_exchange is not None else None,
            candidate_limit=12 if cloud_provider else 8,
            out_xlsx=xlsx_path, out_report=report_path, progress=progress,
            source_name=str(attachment_meta.get("original_name") or source_path.name),
            user_request=user_request,
            batch_size=document_batch_size,  # local transport packages stay small; zero keeps one cloud conversation
            max_agent_turns=document_max_turns,
            agent_batch_runner=agent_runner.run_batch if agent_runner is not None else None,
            accumulate_task_state=(agent_engine == "qwen_agent" and document_batch_size == 1),
            require_global_review=require_global_review,
            soft_accept=soft_accept,
        ))
        while True:
            try:
                workflow = await asyncio.wait_for(
                    asyncio.shield(workflow_task), timeout=SMETA_DOCUMENT_HEARTBEAT_SEC
                )
                break
            except TimeoutError:
                if token_sink is not None:
                    elapsed = int(time.monotonic() - started)
                    await token_sink({
                        "event": "smeta_step",
                        "data": {
                            "phase": "document_workflow",
                            "status": "running",
                            "label": f"Смета: модель работает, прошло {elapsed}с",
                            "elapsed_sec": elapsed,
                        },
                    })
        agent_trace = workflow.setdefault("agent_trace", {})
        if agent_runner is not None:
            model_calls = int(agent_trace.get("model_turns") or model_calls)
        agent_trace["document_model_calls"] = model_calls
        workflow["agent_trace"].setdefault("engine", agent_engine)
        workflow["agent_trace"].setdefault("provider", model_provider)
        workflow["agent_trace"].setdefault("model", model_name)
        if not cloud_provider:
            workflow["agent_trace"].setdefault(
                "seed", int(os.getenv("LES_SMETA_DOCUMENT_SEED", "0"))
            )
        workflow["agent_trace"]["document_elapsed_ms"] = round(
            (time.monotonic() - started) * 1000, 2
        )
        # `_finalize_document_workflow` writes before application-level timing
        # is known. Persist the enriched engine/provider/model/call trace in the
        # same report atomically; no professional row is changed here.
        def persist_enriched_report() -> None:
            report_temp = report_path.with_suffix(report_path.suffix + ".tmp")
            report_temp.write_text(
                json.dumps(workflow, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            report_temp.replace(report_path)

        await asyncio.to_thread(persist_enriched_report)
    except asyncio.CancelledError:
        cancel_requested.set()
        if "workflow_task" in locals():
            workflow_task.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
        logger.info("[SMETA_DOCUMENT] workflow cancellation requested by user")
        raise
    except Exception as error:  # preserve the source for a retry
        logger.exception("[SMETA_DOCUMENT] workflow failed")
        return SmetaDocumentApplicationResult(
            answer=(
                f"ЛСР не собрана: {type(error).__name__}: {error}. "
                "Вложение сохранено для повторной попытки."
            ),
            operation="smeta_document_failed",
            channel="smeta_mode",
            crag="ERROR",
            extra={"retrieval_trace": {"mode": "smeta_document", "error": str(error)}},
        )

    await asyncio.to_thread(consume_read_attachment, attachment_id)
    await asyncio.to_thread(checkpoint_path.unlink, missing_ok=True)
    summary = (workflow.get("lsr") or {}).get("summary") or {}
    status = str(summary.get("result_status") or "unknown")
    source_name = str(attachment_meta.get("original_name") or source_path.name)
    answer = format_document_lsr_message(source_name, summary)
    model_steps = [
        str((item.get("assistant") or {}).get("model") or "").strip()
        for item in (workflow.get("model_trace") or [])
        if str((item.get("assistant") or {}).get("model") or "").strip()
    ]
    effective_models = list(dict.fromkeys(model_steps))
    fallback_steps = [
        {
            "from": str((item.get("assistant") or {}).get("fallback_from") or "").strip(),
            "to": str((item.get("assistant") or {}).get("model") or "").strip(),
            "source_batch": item.get("source_batch"),
            "turn": item.get("turn"),
        }
        for item in (workflow.get("model_trace") or [])
        if (item.get("assistant") or {}).get("fallback_from")
    ]
    if fallback_steps:
        switches = ", ".join(
            f"{item['from']} → {item['to']}" for item in fallback_steps
        )
        answer += f"\n\nСметная модель переключилась на резерв: {switches}. Это записано в журнале ЛСР."
    artifact = {
        "mode": "xlsx",
        "stage": "priced_draft" if status == "priced_draft" else "priced_lsr",
        "title": f"ЛСР — {source_name}",
        "downloads": {
            "xlsx": f"/api/smeta-artifacts/download?path={xlsx_path.name}",
        },
        "files": {"xlsx_path": str(xlsx_path), "trace_path": str(report_path)},
        "rim_trace": json.loads(
            json.dumps(workflow.get("lsr") or {}, ensure_ascii=False, default=str)
        ),
        "approval": {
            "status": summary.get("approval_status") or "auto_draft",
            "mapping_revision_id": (workflow.get("mapping_run") or {}).get(
                "current_mapping_revision_id"
            ),
            "professional_conflicts": list(workflow.get("professional_conflicts") or []),
            "lock_url": (
                f"/api/smeta-mappings/{(workflow.get('mapping_run') or {}).get('current_mapping_revision_id')}/lock"
                if (workflow.get("mapping_run") or {}).get("current_mapping_revision_id")
                else ""
            ),
        },
    }
    return SmetaDocumentApplicationResult(
        answer=answer,
        operation="smeta_document_lsr",
        channel="smeta_mode",
        crag="SUPPORTED" if status == "priced_final" else "PARTIAL",
        extra={
            "artifact": artifact,
            "retrieval_trace": {
                "mode": "smeta_document",
                "schema": workflow.get("schema"),
                "zero_state": True,
                "previous_revision_read": False,
                "source_sha256": attachment_meta.get("sha256"),
                "result_status": status,
                "summary": summary,
                "model_provider": model_provider,
                "agent_engine": agent_engine,
                "model_requested": model_name,
                "model": effective_models[-1] if effective_models else model_name,
                "models_used": effective_models or [model_name],
                "model_fallbacks": fallback_steps,
                "model_calls": len(workflow.get("model_trace") or []),
            },
        },
    )
