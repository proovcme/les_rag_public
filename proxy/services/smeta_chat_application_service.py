"""Application flows for model-first smeta chat requests.

The model owns every estimating decision inside ``run_vor_pdf_workflow``.  This
module only coordinates the server-owned attachment, model transport, progress
events, deterministic calculation/export and the response envelope consumed by
the generic chat router.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

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

ModelExchange = Callable[[list[dict], list[dict]], dict[str, Any]]
TokenSink = Callable[[dict[str, Any]], Awaitable[None]]


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
        except Exception as error:  # provider failure is retried, then reported
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

    if model_exchange is None or model_provider is None or model_name is None or cloud_provider is None:
        from backend.inference.routing import is_cloud_provider
        from proxy.services import smeta_chat_adapter_service as adapters

        runtime = adapters._smeta_model_runtime("LES_SMETA_DOCUMENT_PROVIDER")
        model_exchange = model_exchange or adapters._smeta_document_exchange
        model_provider = model_provider or runtime.provider
        model_name = model_name or runtime.model
        if cloud_provider is None:
            cloud_provider = is_cloud_provider(runtime.provider)

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

    def admit_model_call() -> None:
        nonlocal model_calls
        model_calls += 1

    def exchange(messages: list[dict], tools: list[dict]) -> dict[str, Any]:
        result = retry_smeta_transport(
            lambda: model_exchange(messages, tools),
            on_attempt=admit_model_call,
        )
        if not result:
            raise RuntimeError("smeta model returned no native tool response after transport retry")
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
        try:
            asyncio.run_coroutine_threadsafe(
                token_sink({"event": "smeta_step", "data": payload}), loop
            ).result(timeout=1.0)
        except Exception as error:  # progress telemetry must not abort the estimate
            logger.warning("[SMETA_DOCUMENT] progress bridge failed: %s", error)

    try:
        workflow = await asyncio.to_thread(
            run_vor_document_workflow,
            source_path,
            exchange=exchange,
            candidate_limit=12 if cloud_provider else 8,
            out_xlsx=xlsx_path,
            out_report=report_path,
            progress=progress,
            source_name=str(attachment_meta.get("original_name") or source_path.name),
            user_request=user_request,
        )
        workflow.setdefault("agent_trace", {})["document_model_calls"] = model_calls
        workflow["agent_trace"]["document_elapsed_ms"] = round(
            (time.monotonic() - started) * 1000, 2
        )
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
        "stage": "priced_lsr",
        "title": f"ЛСР — {source_name}",
        "downloads": {
            "xlsx": f"/api/smeta-artifacts/download?path={xlsx_path.name}",
        },
        "files": {"xlsx_path": str(xlsx_path), "trace_path": str(report_path)},
        "rim_trace": json.loads(
            json.dumps(workflow.get("lsr") or {}, ensure_ascii=False, default=str)
        ),
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
                "model_requested": model_name,
                "model": effective_models[-1] if effective_models else model_name,
                "models_used": effective_models or [model_name],
                "model_fallbacks": fallback_steps,
                "model_calls": len(workflow.get("model_trace") or []),
            },
        },
    )
