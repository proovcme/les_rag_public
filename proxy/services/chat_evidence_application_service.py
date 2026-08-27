"""General evidence/RAG application execution extracted from the HTTP router.

The caller resolves request scope and deterministic tools first. This service owns the
unchanged retrieval -> context/evidence -> model -> sources/trace execution branch.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

import httpx
from fastapi import HTTPException

from backend.inference.routing import decide_provider, is_cloud_provider, memory_aware_provider
from backend.inference.validator import rules_pre_verdict
from proxy.services.answer_form_service import classify_answer_form
from proxy.services.answer_form_service import apply_response_length
from proxy.services.cad_bim_highlight import extract_highlight, set_highlight
from proxy.services.canonical_route_service import (
    CanonicalRouteMode,
    one_model_decision_from_calls,
    resolve_canonical_route,
)
from proxy.services.context_governor_service import (
    ContextCandidate,
    ContextGovernor,
    ContextKind,
    ContextObject,
    ContextPacket,
    ContextRequiredSectionOverflow,
)
from proxy.services.context_expander_service import expand_context_windows
from proxy.services.evidence_packet_service import (
    build_retrieval_evidence_packet,
    render_retrieval_evidence_for_model,
)
from proxy.services.lexical_index_service import retrieval_fingerprint
from proxy.services.notebook_service import dataset_memory_prompt_excerpt
from proxy.services.notebook_study_service import (
    build_notebook_study_pack,
    format_study_artifact,
    is_notebook_study_query,
    prompt_block as notebook_study_prompt_block,
)
from proxy.services.project_summary_service import (
    build_project_summary,
    format_project_inventory_context,
    format_project_inventory_prompt,
)
from proxy.services.prompt_registry_service import build_mode_system_prompt
from proxy.services.retrieval_service import required_reranker_policy, retrieve_chat_chunks
from proxy.services.runtime_admission import generation_semaphore
from proxy.services.saferag_service import (
    build_validation_context,
    concentrate_sources,
    rank_chunks_for_question,
    source_names,
)
from proxy.services.table_query_service import maybe_answer_table_query
from proxy.services.memory_port import get_memory_port
from proxy.services.llm_transport_profile_service import (
    assistant_delta_text,
    resolve_transport_execution_profile,
)
from proxy.services.model_execution_preset_service import ModelExecutionPreset
from proxy.services.typed_memory_projection_service import MemoryLimits, project_memory

logger = logging.getLogger(__name__)


def _context_objects(
    prefix: str,
    values: Sequence[Any],
) -> tuple[ContextObject, ...]:
    """Create stable, whole context objects; never slice an object to make it fit."""
    objects: list[ContextObject] = []
    for index, value in enumerate(values):
        if value in (None, "", [], {}, ()):
            continue
        objects.append(ContextObject(f"{prefix}:{index}", value))
    return tuple(objects)


def _text_context_objects(prefix: str, text: str) -> tuple[ContextObject, ...]:
    """Split only at producer-owned paragraph boundaries, preserving every paragraph."""
    return _context_objects(
        prefix,
        [part.strip() for part in str(text or "").split("\n\n") if part.strip()],
    )


def govern_inference_messages(
    *,
    preset: ModelExecutionPreset,
    profile_prefix: str,
    request_payload: Any,
    shortlist: Sequence[Any] = (),
    checkpoint: Sequence[ContextObject] = (),
    working_memory: Sequence[ContextObject] = (),
    evidence: Sequence[Any] = (),
    source_map: Sequence[Any] = (),
    tool_exchange: Sequence[Any] = (),
    dialogue: Sequence[Any] = (),
) -> tuple[list[dict[str, str]], ContextPacket]:
    """Build the sole bounded packet used for one provider inference request."""
    candidates = [
        ContextCandidate(
            ContextKind.PROFILE_PREFIX,
            (ContextObject("profile:bound", profile_prefix),),
            required=True,
        ),
        ContextCandidate(ContextKind.TOOL_SHORTLIST, _context_objects("tool", shortlist)),
        ContextCandidate(
            ContextKind.REQUEST,
            (ContextObject("request:current", request_payload),),
            required=True,
        ),
        ContextCandidate(ContextKind.CHECKPOINT, tuple(checkpoint)),
        ContextCandidate(ContextKind.WORKING_MEMORY, tuple(working_memory)),
        ContextCandidate(ContextKind.EVIDENCE, _context_objects("evidence", evidence)),
        ContextCandidate(ContextKind.SOURCE_MAP, _context_objects("source", source_map)),
        ContextCandidate(ContextKind.TOOL_EXCHANGE, _context_objects("exchange", tool_exchange)),
        ContextCandidate(ContextKind.DIALOGUE, _context_objects("dialogue", dialogue)),
    ]
    packet = ContextGovernor(preset).pack(candidates)
    return packet.as_messages(), packet


def context_packet_trace(packet: ContextPacket, *, purpose: str) -> dict[str, Any]:
    """Expose capacity and omission structure without prompt or evidence payloads."""
    return {
        "purpose": purpose,
        "preset_id": packet.preset_id,
        "input_budget_tokens": packet.input_budget_tokens,
        "generation_reserve_tokens": packet.generation_reserve_tokens,
        "safety_reserve_tokens": packet.safety_reserve_tokens,
        "included_tokens": packet.included_tokens,
        "sections": [
            {
                "kind": section.kind.value,
                "items": len(section.objects),
                "tokens": section.token_count,
            }
            for section in packet.sections
        ],
        "omissions": [
            {
                "kind": omission.kind.value,
                "total": omission.total,
                "omitted": omission.omitted,
                "cursor": omission.cursor,
                "reason": omission.reason,
            }
            for omission in packet.omissions
        ],
    }


async def execute_canonical_shadow_decision(
    *,
    proposed_calls: list[dict[str, Any]],
    allowed_tools: set[str],
    dataset_ids: list[str],
    tool_harness: Any,
) -> dict[str, Any]:
    """Execute at most one candidate call and return structural, redacted trace."""
    decision = one_model_decision_from_calls(proposed_calls, allowed=allowed_tools)
    trace: dict[str, Any] = {
        "schema": "les_canonical_shadow_v1",
        "user_visible": False,
        "persisted": False,
        "proposed_calls": decision.proposed_calls,
        "executed_calls": decision.executed_calls,
        "pending_calls": decision.pending_calls,
        "tool_name": str((decision.call or {}).get("tool") or ""),
    }
    if decision.call is None:
        trace.update(status="no_valid_call", execution_code="")
        return trace
    payload = await tool_harness.call_async(
        str(decision.call["tool"]),
        dict(decision.call["args"]),
        actor_id="canonical-shadow",
        actor_role="user",
        allowed_dataset_ids=tuple(str(item) for item in dataset_ids if str(item)),
        shadow=True,
    )
    execution = payload.get("execution") if isinstance(payload, dict) else {}
    trace.update(
        status=str((execution or {}).get("status") or payload.get("status") or "unknown"),
        execution_code=str((execution or {}).get("code") or ""),
        result_schema=str(payload.get("schema") or ""),
    )
    return trace


async def safe_execute_canonical_shadow_decision(**kwargs: Any) -> dict[str, Any]:
    """Keep every candidate failure outside the authoritative legacy path."""
    proposed = kwargs.get("proposed_calls") or []
    allowed = kwargs.get("allowed_tools") or set()
    structural = one_model_decision_from_calls(proposed, allowed=set(allowed))
    try:
        return await execute_canonical_shadow_decision(**kwargs)
    except Exception as error:  # noqa: BLE001 - shadow must never affect legacy
        logger.warning("[CANONICAL_SHADOW] candidate skipped: %s", type(error).__name__)
        return {
            "schema": "les_canonical_shadow_v1",
            "user_visible": False,
            "persisted": False,
            "status": "error",
            "error_type": type(error).__name__,
            "executed_calls": 0,
            "attempted_calls": structural.executed_calls,
            "pending_calls": structural.pending_calls,
        }


def profile_temperature(profile_snapshot: dict[str, Any] | None, *, fallback: float) -> float:
    """Return the bounded immutable profile temperature for generation."""

    policy = (profile_snapshot or {}).get("model_policy") or {}
    try:
        value = float(policy.get("temperature", fallback))
    except (TypeError, ValueError):
        value = fallback
    return max(0.0, min(2.0, value))


def profile_research_rounds(profile_snapshot: dict[str, Any] | None, *, configured: int) -> int:
    """Respect the profile's iterative-search switch without changing the global ceiling."""

    iterative = bool(((profile_snapshot or {}).get("rag_policy") or {}).get("iterative", True))
    return max(1, configured) if iterative else 1


def profile_system_prompt(profile_snapshot: dict[str, Any] | None, *, strict: bool) -> str:
    """Compile the exact per-chat prompt/skill snapshot for grounded generation."""

    snapshot = profile_snapshot if isinstance(profile_snapshot, dict) else {}
    prompt = str(snapshot.get("prompt_text") or "").strip()
    skill = str(snapshot.get("skill_text") or "").strip()
    if not prompt:
        prompt = build_mode_system_prompt("rag")
    parts = [prompt]
    if skill:
        parts.append("Активный skill профиля (правила работы, не evidence):\n" + skill)
    if strict:
        parts.append(
            "Повторная попытка: сохрани полезный ответ, но привяжи числа, требования и "
            "проектные факты к [Источник N]. Не найденное обозначь как ограничение."
        )
    else:
        parts.append(
            "Для проверяемых утверждений используй только реальные материалы текущего запроса. "
            "Ссылки оформляй номерами из заголовков [Источник N]; навигационные карты помогают "
            "выбрать файл, но сами по себе не подтверждают факт."
        )
    return "\n\n".join(parts)

@dataclass(frozen=True)
class EvidenceRequestContext:
    req: Any
    dataset_ids: list[str]
    effective_dataset_filter: str
    resolved_dataset_names: list[str]
    dataset_name_by_id: dict[str, str]
    query_route_payload: dict[str, Any]
    target_doc_filter: list[str]
    target_file_ref: dict[str, Any] | None
    topic_doc_filter: list[str]
    topic_retrieval_plan: dict[str, Any] | None
    inventory_requested: bool
    study_requested: bool
    memory_block: str
    session_block: str
    class_suggestions: list[dict[str, Any]]
    use_semantic_cache: bool
    use_validation: bool
    validation_skip_reason: str
    route: Any
    table_result: Any
    request_started_at: float
    profile_snapshot: dict[str, Any] = field(default_factory=dict)
    scope_resolution: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvidenceRuntimeDeps:
    state: Any
    rag_backend: Any
    cache: Any
    cache_embedding: Any
    cache_marker: str
    cache_scope: str
    assistant_text: Callable
    augment_model_tool_args: Callable
    chat_model_final_answer: Callable
    cloud_body_for_model: Callable
    compact_tool_result_for_prompt: Callable
    dataset_ids_from_chunks: Callable
    dataset_sensitivities: Callable
    env_bool: Callable
    env_float: Callable
    env_int: Callable
    expand_context_windows: Callable
    format_tool_results_for_model: Callable
    generation_token_budget: Callable
    llm_runtime: Callable
    local_context_budget: Callable
    mlx_runtime: Callable
    names_for_dataset_ids: Callable
    notebook_study_validation_status: Callable
    ollama_native_complete: Callable
    parse_model_tool_calls: Callable
    prepare_notebook_reader_memory: Callable
    record_cloud_cost: Callable
    retrieve_chat_chunks: Callable
    source_excerpts: Callable
    table_query_response: Callable
    cloud_fallback_models: Callable
    cloud_model_timeout: Callable


@dataclass(frozen=True)
class ResponseBoundary:
    save_chat_history: Callable
    token_sink: Callable | None
    version_stamp: Callable


async def run_chat_evidence_application(
    request: EvidenceRequestContext,
    runtime: EvidenceRuntimeDeps,
    response: ResponseBoundary,
):
    return await _execute_chat_evidence_application(
        _dataset_ids=request.dataset_ids,
        scope_resolution=request.scope_resolution,
        class_suggestions=request.class_suggestions,
        dataset_name_by_id=request.dataset_name_by_id,
        effective_dataset_filter=request.effective_dataset_filter,
        inventory_requested=request.inventory_requested,
        memory_block=request.memory_block,
        query_route_payload=request.query_route_payload,
        req=request.req,
        resolved_dataset_names=request.resolved_dataset_names,
        route=request.route,
        session_block=request.session_block,
        study_requested=request.study_requested,
        t_request_start=request.request_started_at,
        table_result=request.table_result,
        target_doc_filter=request.target_doc_filter,
        target_file_ref=request.target_file_ref,
        topic_doc_filter=request.topic_doc_filter,
        topic_retrieval_plan=request.topic_retrieval_plan,
        use_semantic_cache=request.use_semantic_cache,
        use_validation=request.use_validation,
        validation_skip_reason=request.validation_skip_reason,
        profile_snapshot=request.profile_snapshot,
        state=runtime.state,
        rag_backend=runtime.rag_backend,
        cache=runtime.cache,
        cache_embedding=runtime.cache_embedding,
        cache_marker=runtime.cache_marker,
        cache_scope=runtime.cache_scope,
        _assistant_text=runtime.assistant_text,
        _augment_model_tool_args=runtime.augment_model_tool_args,
        _chat_model_final_answer=runtime.chat_model_final_answer,
        _cloud_body_for_model=runtime.cloud_body_for_model,
        _compact_tool_result_for_prompt=runtime.compact_tool_result_for_prompt,
        _dataset_ids_from_chunks=runtime.dataset_ids_from_chunks,
        _dataset_sensitivities=runtime.dataset_sensitivities,
        _env_bool=runtime.env_bool,
        _env_float=runtime.env_float,
        _env_int=runtime.env_int,
        expand_context_windows=runtime.expand_context_windows,
        _format_tool_results_for_model=runtime.format_tool_results_for_model,
        _generation_token_budget=runtime.generation_token_budget,
        _llm_runtime=runtime.llm_runtime,
        _local_context_budget=runtime.local_context_budget,
        _mlx_runtime=runtime.mlx_runtime,
        _names_for_dataset_ids=runtime.names_for_dataset_ids,
        _notebook_study_validation_status=runtime.notebook_study_validation_status,
        _ollama_native_complete=runtime.ollama_native_complete,
        _parse_model_tool_calls=runtime.parse_model_tool_calls,
        _prepare_notebook_reader_memory=runtime.prepare_notebook_reader_memory,
        _record_cloud_cost=runtime.record_cloud_cost,
        retrieve_chat_chunks=runtime.retrieve_chat_chunks,
        source_excerpts=runtime.source_excerpts,
        _table_query_response=runtime.table_query_response,
        cloud_fallback_models=runtime.cloud_fallback_models,
        cloud_model_timeout=runtime.cloud_model_timeout,
        save_chat_history=response.save_chat_history,
        token_sink=response.token_sink,
        _version_stamp=response.version_stamp,
        HTTPException=HTTPException,
        Path=Path,
        asyncio=asyncio,
        build_mode_system_prompt=build_mode_system_prompt,
        build_notebook_study_pack=build_notebook_study_pack,
        build_project_summary=build_project_summary,
        build_retrieval_evidence_packet=build_retrieval_evidence_packet,
        build_validation_context=build_validation_context,
        classify_answer_form=classify_answer_form,
        concentrate_sources=concentrate_sources,
        dataset_memory_prompt_excerpt=dataset_memory_prompt_excerpt,
        decide_provider=decide_provider,
        extract_highlight=extract_highlight,
        format_project_inventory_context=format_project_inventory_context,
        format_project_inventory_prompt=format_project_inventory_prompt,
        format_study_artifact=format_study_artifact,
        generation_semaphore=generation_semaphore,
        httpx=httpx,
        is_cloud_provider=is_cloud_provider,
        is_notebook_study_query=is_notebook_study_query,
        json=json,
        logger=logger,
        maybe_answer_table_query=maybe_answer_table_query,
        memory_aware_provider=memory_aware_provider,
        notebook_study_prompt_block=notebook_study_prompt_block,
        os=os,
        rank_chunks_for_question=rank_chunks_for_question,
        render_retrieval_evidence_for_model=render_retrieval_evidence_for_model,
        retrieval_fingerprint=retrieval_fingerprint,
        rules_pre_verdict=rules_pre_verdict,
        set_highlight=set_highlight,
        source_names=source_names,
        time=time,
    )


async def _execute_chat_evidence_application(
    HTTPException,
    Path,
    _assistant_text,
    _augment_model_tool_args,
    _chat_model_final_answer,
    _cloud_body_for_model,
    _compact_tool_result_for_prompt,
    _dataset_ids,
    _dataset_ids_from_chunks,
    _dataset_sensitivities,
    _env_bool,
    _env_float,
    _env_int,
    _format_tool_results_for_model,
    _generation_token_budget,
    _llm_runtime,
    _local_context_budget,
    _mlx_runtime,
    _names_for_dataset_ids,
    _notebook_study_validation_status,
    _ollama_native_complete,
    _parse_model_tool_calls,
    _prepare_notebook_reader_memory,
    _record_cloud_cost,
    _table_query_response,
    _version_stamp,
    asyncio,
    build_mode_system_prompt,
    build_notebook_study_pack,
    build_project_summary,
    build_retrieval_evidence_packet,
    build_validation_context,
    cache,
    cache_embedding,
    cache_marker,
    cache_scope,
    class_suggestions,
    classify_answer_form,
    cloud_fallback_models,
    cloud_model_timeout,
    concentrate_sources,
    dataset_memory_prompt_excerpt,
    dataset_name_by_id,
    decide_provider,
    effective_dataset_filter,
    expand_context_windows,
    extract_highlight,
    format_project_inventory_context,
    format_project_inventory_prompt,
    format_study_artifact,
    generation_semaphore,
    httpx,
    inventory_requested,
    is_cloud_provider,
    is_notebook_study_query,
    json,
    logger,
    maybe_answer_table_query,
    memory_aware_provider,
    memory_block,
    notebook_study_prompt_block,
    os,
    query_route_payload,
    profile_snapshot,
    rag_backend,
    rank_chunks_for_question,
    render_retrieval_evidence_for_model,
    req,
    resolved_dataset_names,
    retrieval_fingerprint,
    retrieve_chat_chunks,
    route,
    rules_pre_verdict,
    save_chat_history,
    session_block,
    set_highlight,
    source_excerpts,
    source_names,
    state,
    study_requested,
    t_request_start,
    target_doc_filter,
    target_file_ref,
    time,
    token_sink,
    topic_doc_filter,
    topic_retrieval_plan,
    use_semantic_cache,
    use_validation,
    validation_skip_reason,
    answer=None,
    history_id=None,
    key=None,
    payload=None,
    retrieval=None,
    source_dataset_ids=None,
    source_dataset_names=None,
    scope_resolution=None,
    sources_list=None,
    status=None,
    table_result=None
):
    memory_project_id = 0
    project_memory_advisory = ""
    try:
        memory_project_id = int(getattr(req, "project_id", 0) or 0)
        if memory_project_id > 0:
            project_memory_advisory = get_memory_port().recall_project_advisory(
                memory_project_id, str(req.question or "")
            )
    except Exception as memory_error:  # Memory is advisory and fail-open.
        logger.warning("[MEMORY] advisory recall skipped: %s", memory_error)
        memory_project_id = 0
        project_memory_advisory = ""

    # Карты тем/разделов остаются навигацией для модели. Production chat-path
    # физически не делает topic/file prefetch до первого модельного хода.
    requested_topic_doc_filter = list(topic_doc_filter or [])
    topic_doc_filter = []

    t_search_start = time.time()
    try:
        _reranker_on, retrieval_trace_policy = required_reranker_policy(
            getattr(req, "reranker_enabled", None)
        )
        topic_chunks: list[Any] = []
        retrieval = await retrieve_chat_chunks(
            question=req.question,
            dataset_ids=_dataset_ids,
            rag_backend=rag_backend,
            reranker_enabled=_reranker_on,
            reranker_available=state.reranker_available,
            reranker_cls=state.reranker_cls,
            mlx_url=os.getenv("MLX_URL", "http://127.0.0.1:8080"),
            logger=logger,
            llm_semaphore=state.llm_semaphore,
            return_trace=True,
            doc_filter=target_doc_filter or None,
            scope_source=str((scope_resolution or {}).get("scope_source") or "unspecified"),
            scope_error_code=str((scope_resolution or {}).get("error_code") or ""),
        )
        chunks = [*topic_chunks, *retrieval.chunks] if topic_chunks else retrieval.chunks
    except Exception as e:
        import traceback

        tb = traceback.format_exc()
        logger.error("[CHAT] RETRIEVAL ERROR: %s\n%s", e, tb)
        raise HTTPException(500, f"Поиск по датасету не удался: {type(e).__name__}: {e}")
    t_search = time.time() - t_search_start
    retrieval_trace = retrieval.payload()
    retrieval_trace["scope_resolution"] = dict(scope_resolution or {})
    retrieval_trace["reranker_policy"] = retrieval_trace_policy
    retrieval_trace_object = getattr(retrieval, "trace", None)
    retrieval_status = str(
        getattr(retrieval_trace_object, "status", "") or retrieval_trace.get("status") or "ok"
    )
    if retrieval_status == "blocked":
        error_code = str(
            getattr(retrieval_trace_object, "error_code", "")
            or retrieval_trace.get("error_code")
            or "retrieval_blocked"
        )
        if error_code in {"dataset_scope_not_found", "no_datasets", "corpus_empty"}:
            blocked_answer = (
                "Нужный набор данных не найден или пока пуст. "
                "Выберите доступный проект/датасет либо добавьте источники — "
                "поиск по другим документам автоматически не выполнялся."
            )
            action = "Выбрать доступный датасет или загрузить источники."
        elif error_code in {"reranker_disabled", "reranker_unavailable", "reranker_failed"}:
            blocked_answer = (
                "Поиск остановлен: обязательный реранкер недоступен. "
                "Я не формирую ответ по непроверенному порядку фрагментов."
            )
            action = "Восстановить реранкер и повторить запрос."
        else:
            blocked_answer = (
                "Поиск остановлен: обязательный native RRF-контур недоступен. "
                "Старый или широкий поиск вместо него не запускался."
            )
            action = "Проверить индекс-контракт и native RRF, затем повторить запрос."
        retrieval_trace["blocker"] = {
            "schema": "retrieval_blocker_v1",
            "code": error_code,
            "action": action,
        }
        state.crag_stats["no_data"] += 1
        state.chat_metrics["retrieval_weak"] = state.chat_metrics.get("retrieval_weak", 0) + 1
        state.chat_metrics["latency_search"].append(t_search)
        state.chat_metrics["latency_gen"].append(0.0)
        state.chat_metrics["tokens"].append(0)
        state.chat_metrics["crag_fail"] += 1
        for key_name in ("latency_search", "latency_gen", "tokens"):
            state.chat_metrics[key_name] = state.chat_metrics[key_name][-100:]
        history_id = None
        try:
            history_id = save_chat_history(
                question=req.question,
                answer=blocked_answer,
                sources=[],
                crag_status="BLOCKED",
                latency_sec=t_search,
                tokens=0,
                session_id=req.session_id,
                requested_dataset_filter=req.dataset_filter,
                effective_dataset_filter=effective_dataset_filter,
                resolved_dataset_ids=_dataset_ids,
                resolved_dataset_names=resolved_dataset_names,
                query_route=query_route_payload,
                retrieval_trace=retrieval_trace,
                cache_type=cache_marker,
                validation_enabled=False,
                success=0,
            )
        except Exception as db_err:
            logger.warning("[CHAT] History save error: %s", db_err)
        return {
            "answer": blocked_answer,
            "crag_status": "BLOCKED",
            "sources": [],
            "effective_dataset_filter": effective_dataset_filter,
            "query_route": query_route_payload,
            "retrieval_trace": retrieval_trace,
            "blocker": retrieval_trace["blocker"],
            "cache": cache_marker,
            "validation": {"enabled": False, "reason": error_code},
            "history_id": history_id,
        }
    if topic_retrieval_plan:
        found_topic_docs = {str(getattr(chunk, "doc_name", "") or "") for chunk in topic_chunks}
        retrieval_trace["topic_guided_retrieval"] = {
            "schema": topic_retrieval_plan.get("schema") or "dataset_topic_selection_v1",
            "context_role": "navigation",
            "is_evidence": False,
            "selected_topics": topic_retrieval_plan.get("selected_topics") or [],
            "selected_files": topic_retrieval_plan.get("selected_files") or [],
            "selected_sections": topic_retrieval_plan.get("selected_sections") or [],
            "requested_doc_filter": requested_topic_doc_filter,
            "targeted_doc_filter": topic_doc_filter,
            "prefetch_enabled": False,
            "targeted_trace": {},
            "targeted_chunk_count": len(topic_chunks),
            "wide_fallback_trace": retrieval.payload(),
            "wide_fallback_chunk_count": len(retrieval.chunks),
            "fallback": topic_retrieval_plan.get("fallback") or "wide_retrieval",
            "not_found_files": [name for name in topic_doc_filter if name not in found_topic_docs],
        }
    if validation_skip_reason:
        retrieval_trace["validation_policy"] = {
            "enabled": False,
            "reason": validation_skip_reason,
            "evidence": "source_map+project_inventory_artifact",
        }
    if target_file_ref:
        retrieval_trace["target_file"] = target_file_ref
    if retrieval.quality.status == "good":
        state.chat_metrics["retrieval_good"] = state.chat_metrics.get("retrieval_good", 0) + 1
    else:
        state.chat_metrics["retrieval_weak"] = state.chat_metrics.get("retrieval_weak", 0) + 1

    notebook_study_pack = None
    notebook_study_prompt = ""
    notebook_study_artifact = ""
    notebook_study_latency = 0.0
    notebook_study_started = time.time()
    dataset_memory_prompt = ""
    project_inventory_prompt = ""
    project_inventory_artifact_text = ""
    project_inventory_payload: dict[str, Any] | None = None
    if _dataset_ids and study_requested:
        try:
            retrieval_trace["dataset_reader_prepare"] = await _prepare_notebook_reader_memory(
                [str(d) for d in _dataset_ids],
            )
        except Exception as reader_err:  # noqa: BLE001
            logger.warning("[DATASET_READER] study prepare failed: %s", reader_err)
            retrieval_trace["dataset_reader_prepare"] = {
                "schema": "dataset_reader_prepare_v1",
                "status": "skipped",
                "error": f"{type(reader_err).__name__}: {reader_err}",
            }
    if _dataset_ids:
        try:
            dataset_memory_prompt = await asyncio.to_thread(
                dataset_memory_prompt_excerpt,
                [str(d) for d in _dataset_ids],
                question=req.question,
            )
            if dataset_memory_prompt:
                retrieval_trace["dataset_memory"] = {
                    "schema": "dataset_brief_for_model_v1",
                    "context_role": "navigation",
                    "is_evidence": False,
                    "dataset_count": len(_dataset_ids),
                    "prompt_chars": len(dataset_memory_prompt),
                }
        except Exception as memory_err:  # noqa: BLE001
            logger.warning("[DATASET_MEMORY] skipped: %s", memory_err)
            retrieval_trace["dataset_memory"] = {
                "schema": "dataset_memory_context_v1",
                "status": "skipped",
                "error": f"{type(memory_err).__name__}: {memory_err}",
            }
    if _dataset_ids and (inventory_requested or study_requested):
        try:
            project_inventory_payload = await asyncio.to_thread(
                build_project_summary,
                [str(d) for d in _dataset_ids],
                storage_root=Path("./storage/datasets"),
            )
            if inventory_requested:
                project_inventory_prompt = format_project_inventory_prompt(
                    project_inventory_payload,
                    label=", ".join(resolved_dataset_names or [str(d) for d in _dataset_ids]),
                )
                project_inventory_artifact_text = format_project_inventory_context(
                    project_inventory_payload,
                    label=", ".join(resolved_dataset_names or [str(d) for d in _dataset_ids]),
                )
            retrieval_trace["project_inventory"] = {
                "schema": "project_inventory_context_v1",
                "context_role": "deterministic_evidence",
                "source": "metadb.documents",
                "file_count": project_inventory_payload.get("file_count", 0),
                "by_ext": (project_inventory_payload.get("inventory") or {}).get("by_ext") or [],
                "prompt_chars": len(project_inventory_prompt),
                "artifact_chars": len(project_inventory_artifact_text),
                "used_for_notebook_study": bool(study_requested),
            }
        except Exception as inv_err:  # noqa: BLE001
            logger.warning("[PROJECT_INVENTORY] skipped: %s", inv_err)
            retrieval_trace["project_inventory"] = {
                "schema": "project_inventory_context_v1",
                "status": "skipped",
                "error": f"{type(inv_err).__name__}: {inv_err}",
            }
    if _dataset_ids and is_notebook_study_query(req.question):
        retrieval_trace["notebook_study"] = {
            "schema": "notebook_study_v1",
            "status": "map_only",
            "query_prefetch_enabled": False,
            "reason": "model_first_single_rrf",
            "note": "dataset map and inventory are navigation; no automatic section/file retrieval",
        }
    notebook_study_latency = time.time() - notebook_study_started
    retrieval_trace["notebook_study_latency_sec"] = round(notebook_study_latency, 3)

    # «Заставь отвечать»: не хард-режем разнородность, если есть сильный сигнал —
    # пользователь задал датасет (уже сузил) ИЛИ топ-совпадение хорошее (есть, что
    # отвечать). Гейт остаётся только для реально широких безскоповых слабых запросов.
    inventory_has_files = bool(project_inventory_payload and int(project_inventory_payload.get("file_count") or 0) > 0)
    strong_signal = bool(effective_dataset_filter) or inventory_has_files or (retrieval.quality.top_score >= 0.5)
    if retrieval.quality.status == "needs_clarification" and not strong_signal:
        retrieval_trace["wide_scope"] = {"model_final_allowed": True, "reason": "low_concentration"}

    is_structured = any(word in req.question.casefold() for word in ("перечен", "состав", "список", "разделы", "все разделы", "перечисли"))
    is_technical_or_legal = bool(effective_dataset_filter and effective_dataset_filter != "MAIL")

    # Размер контекста зависит от того, КУДА пойдёт генерация. Облако ест большой контекст
    # быстро; локальная 4B (P0-данные форсят MLX по ADR-9) захлёбывается на префилле 32K
    # символов — генерация ~1 tok/s. Поэтому большой контекст — только для облака.
    _cfg_provider = ""
    try:
        _cfg_provider = _llm_runtime().provider
        _route_preview = decide_provider(
            _cfg_provider,
            _dataset_sensitivities([str(d) for d in (_dataset_ids or [])]),
            consent=_env_bool("LES_CLOUD_CONSENT", False),
        )
        will_be_cloud = is_cloud_provider(_cfg_provider) and not _route_preview.downgraded
    except Exception:
        will_be_cloud = False
    big_context = (is_structured or is_technical_or_legal) and will_be_cloud
    local_big = (is_structured or is_technical_or_legal) and not will_be_cloud

    context_budget = _local_context_budget(
        local_big=local_big,
        big_context=big_context,
        provider=_cfg_provider,
    )
    focus_max_chunks = context_budget["focus_max_chunks"] or None
    context_max_chunks = context_budget["context_max_chunks"] or None
    context_chars_limit = context_budget["context_chars_limit"]
    context_window_chars = context_budget["context_window_chars"]
    context_radius = 0 if is_structured else None

    chunks = rank_chunks_for_question(req.question, chunks)
    protected_doc_names: list[str] = list(target_doc_filter or [])
    protected_doc_names.extend(topic_doc_filter)
    if notebook_study_pack is not None:
        protected_doc_names.extend([
            str(item.get("file_name") or "")
            for item in getattr(notebook_study_pack, "targeted_files", [])
            if item.get("file_name")
        ])
    protected_doc_names = list(dict.fromkeys(name for name in protected_doc_names if name))
    focus_max_docs = max(1, len({str(getattr(chunk, "doc_name", "") or "") for chunk in chunks}))
    chunks = concentrate_sources(
        chunks,
        max_docs=focus_max_docs,
        min_score=float("-inf"),
        max_chunks=focus_max_chunks,
        protected_doc_names=protected_doc_names,
    )
    if topic_doc_filter and retrieval.chunks:
        topic_names = {str(name or "") for name in topic_doc_filter}
        topic_basenames = {Path(name).name for name in topic_names}
        focused_names = {str(getattr(chunk, "doc_name", "") or "") for chunk in chunks}
        fallback_floor = _env_float("RAG_CHAT_FOCUS_MIN_SCORE", 0.35)
        promoted_fallback = None
        for candidate in rank_chunks_for_question(req.question, list(retrieval.chunks)):
            candidate_name = str(getattr(candidate, "doc_name", "") or "")
            if (
                not candidate_name
                or candidate_name in topic_names
                or candidate_name in focused_names
                or Path(candidate_name).name in topic_basenames
            ):
                continue
            candidate_score = float(getattr(candidate, "_rank_score", getattr(candidate, "score", 0.0)) or 0.0)
            if candidate_score < fallback_floor:
                continue
            insert_at = min(len(chunks), 5)
            if focus_max_chunks is not None and len(chunks) >= focus_max_chunks:
                chunks = [*chunks[:insert_at], candidate, *chunks[insert_at: max(focus_max_chunks - 1, insert_at)]]
            else:
                chunks = [*chunks[:insert_at], candidate, *chunks[insert_at:]]
            promoted_fallback = {
                "doc_name": candidate_name,
                "rank_score": round(candidate_score, 4),
            }
            break
        if promoted_fallback:
            retrieval_trace.setdefault("topic_guided_retrieval", {})["wide_fallback_promoted"] = promoted_fallback
    if protected_doc_names:
        retrieval_trace.setdefault("notebook_study", {})["protected_doc_names"] = protected_doc_names
    logger.info(
        "[FOCUS] После концентрации: %s чанков из %s источников",
        len(chunks),
        len(set(c.doc_name for c in chunks)),
    )
    focused_fingerprint = retrieval_fingerprint(chunks)

    if use_semantic_cache and cache_scope and not use_validation:
        session_hit = cache.lookup_session_unvalidated(
            req.question,
            cache_scope,
            focused_fingerprint,
            req.session_id,
        )
        if session_hit:
            state.chat_metrics["cache_hit"] = state.chat_metrics.get("cache_hit", 0) + 1
            history_id = None
            try:
                history_id = save_chat_history(
                    question=req.question,
                    answer=session_hit.answer,
                    sources=session_hit.sources,
                    crag_status="UNVALIDATED",
                    latency_sec=t_search,
                    tokens=0,
                    session_id=req.session_id,
                    requested_dataset_filter=req.dataset_filter,
                    effective_dataset_filter=effective_dataset_filter,
                    resolved_dataset_ids=_dataset_ids,
                    resolved_dataset_names=resolved_dataset_names,
                    source_dataset_ids=_dataset_ids,
                    source_dataset_names=resolved_dataset_names,
                    query_route=query_route_payload,
                    retrieval_trace=retrieval_trace,
                    cache_type=session_hit.cache_type,
                    validation_enabled=use_validation,
                    success=1,
                )
            except Exception as db_err:
                logger.warning("[CHAT] History save error: %s", db_err)
            return {
                "answer": session_hit.answer,
                "crag_status": "UNVALIDATED",
                "sources": session_hit.sources,
                "effective_dataset_filter": effective_dataset_filter,
                "query_route": query_route_payload,
                "retrieval_trace": retrieval_trace,
                "cache": session_hit.cache_type,
                "validation": {"enabled": use_validation},
                "history_id": history_id,
            }
    state.chat_metrics["cache_miss"] = state.chat_metrics.get("cache_miss", 0) + 1

    table_result = maybe_answer_table_query(
        req.question,
        chunks,
        storage_root=Path("./storage/datasets"),
    )
    if table_result:
        return _table_query_response(
            state=state,
            question=req.question,
            table_result=table_result,
            chunks=chunks,
            t_search=t_search,
            session_id=req.session_id,
            requested_dataset_filter=req.dataset_filter,
            effective_dataset_filter=effective_dataset_filter,
            resolved_dataset_ids=_dataset_ids,
            resolved_dataset_names=resolved_dataset_names,
            dataset_name_by_id=dataset_name_by_id,
            query_route_payload=query_route_payload,
            retrieval_trace=retrieval_trace,
            cache_marker=cache_marker,
            use_validation=use_validation,
        )

    if not chunks and target_file_ref and target_file_ref.get("match_status") in {"matched", "ambiguous"}:
        state.crag_stats["no_data"] += 1
        state.chat_metrics["latency_search"].append(t_search)
        state.chat_metrics["latency_gen"].append(0.0)
        state.chat_metrics["crag_fail"] += 1
        for key in ("latency_search", "latency_gen", "tokens"):
            state.chat_metrics[key] = state.chat_metrics[key][-100:]
        no_data_answer = "Нет данных в выбранных источниках."
        if target_file_ref and target_file_ref.get("match_status") == "matched":
            file_name = str(target_file_ref.get("file_name") or target_file_ref.get("basename") or "файл")
            status = str(target_file_ref.get("status") or "UNKNOWN")
            chunk_count = int(target_file_ref.get("chunk_count") or 0)
            no_data_answer = (
                f"В реестре вижу файл `{file_name}`, статус индекса: `{status}`, чанков: {chunk_count}. "
                "Содержимое этого файла сейчас не найдено в индексе, поэтому честно не пересказываю его состав. "
                "Нужно дождаться индексации/переиндексировать файл или открыть его как вложение."
            )
        elif target_file_ref and target_file_ref.get("match_status") == "ambiguous":
            options = [
                str(item.get("file_name") or item.get("basename") or "")
                for item in (target_file_ref.get("matches") or [])[:8]
                if item
            ]
            no_data_answer = (
                "Нашёл несколько файлов, похожих на указанное имя. Уточни один из них:\n"
                + "\n".join(f"- `{name}`" for name in options)
            )
        history_id = None
        try:
            history_id = save_chat_history(
                question=req.question,
                answer=no_data_answer,
                sources=[],
                crag_status="NO_DATA",
                latency_sec=t_search,
                tokens=0,
                session_id=req.session_id,
                requested_dataset_filter=req.dataset_filter,
                effective_dataset_filter=effective_dataset_filter,
                resolved_dataset_ids=_dataset_ids,
                resolved_dataset_names=resolved_dataset_names,
                query_route=query_route_payload,
                retrieval_trace=retrieval_trace,
                cache_type=cache_marker,
                validation_enabled=use_validation,
                success=0,
            )
        except Exception as db_err:
            logger.warning("[CHAT] History save error: %s", db_err)
        return {
            "answer": no_data_answer,
            "crag_status": "NO_DATA",
            "sources": [],
            "effective_dataset_filter": effective_dataset_filter,
            "query_route": query_route_payload,
            "retrieval_trace": retrieval_trace,
            "cache": cache_marker,
            "history_id": history_id,
        }
    if not chunks and effective_dataset_filter:
        state.crag_stats["no_data"] += 1
        state.chat_metrics["latency_search"].append(t_search)
        state.chat_metrics["latency_gen"].append(0.0)
        state.chat_metrics["crag_fail"] += 1
        for key in ("latency_search", "latency_gen", "tokens"):
            state.chat_metrics[key] = state.chat_metrics[key][-100:]
        retrieval_trace["empty_retrieval"] = {
            "schema": "empty_scoped_retrieval_no_data_v1",
            "model_final_allowed": False,
            "note": "Explicit scoped retrieval returned no chunks and no navigation/memory context.",
        }
        no_data_answer = "В выбранных источниках ничего не найдено по этому вопросу."
        history_id = None
        try:
            history_id = save_chat_history(
                question=req.question,
                answer=no_data_answer,
                sources=[],
                crag_status="NO_DATA",
                latency_sec=t_search,
                tokens=0,
                session_id=req.session_id,
                requested_dataset_filter=req.dataset_filter,
                effective_dataset_filter=effective_dataset_filter,
                resolved_dataset_ids=_dataset_ids,
                resolved_dataset_names=resolved_dataset_names,
                query_route=query_route_payload,
                retrieval_trace=retrieval_trace,
                cache_type=cache_marker,
                validation_enabled=use_validation,
                success=0,
            )
        except Exception as db_err:
            logger.warning("[CHAT] History save error: %s", db_err)
        return {
            "answer": no_data_answer,
            "crag_status": "NO_DATA",
            "sources": [],
            "effective_dataset_filter": effective_dataset_filter,
            "query_route": query_route_payload,
            "retrieval_trace": retrieval_trace,
            "cache": cache_marker,
            "history_id": history_id,
        }
    if not chunks:
        retrieval_trace["empty_retrieval"] = {
            "schema": "empty_retrieval_model_first_v1",
            "model_final_allowed": True,
            "note": "No retrieved chunks; continue to model with memory/navigation instead of code NO_DATA final.",
        }

    t_ctx_start = time.time()
    context_windows = expand_context_windows(
        chunks,
        collection=getattr(rag_backend, "collection_name", ""),
        logger=logger,
        max_chunks=context_max_chunks,
        max_chars_per_chunk=context_window_chars,
        radius=context_radius,
    )
    llm_chunks = context_windows.chunks
    retrieval_trace["context_window"] = context_windows.payload()
    retrieval_trace["context_budget"] = {
        **context_budget,
        "big_context": big_context,
        "local_big": local_big,
        "will_be_cloud": will_be_cloud,
        "context_radius": context_radius,
    }
    expanded_table_chunks = [*chunks, *context_windows.chunks]
    table_result = maybe_answer_table_query(
        req.question,
        expanded_table_chunks,
        storage_root=Path("./storage/datasets"),
    )
    if table_result:
        return _table_query_response(
            state=state,
            question=req.question,
            table_result=table_result,
            chunks=expanded_table_chunks,
            t_search=t_search,
            session_id=req.session_id,
            requested_dataset_filter=req.dataset_filter,
            effective_dataset_filter=effective_dataset_filter,
            resolved_dataset_ids=_dataset_ids,
            resolved_dataset_names=resolved_dataset_names,
            dataset_name_by_id=dataset_name_by_id,
            query_route_payload=query_route_payload,
            retrieval_trace=retrieval_trace,
            cache_marker=cache_marker,
            use_validation=use_validation,
        )
    # ПЕРФ: валидатор теперь аддитивный/быстрый (rules+coreml fail-open) — ему НЕ нужен второй
    # дорогой проход expand_context_windows (это удваивало context-фазу, 2.7-5.7с на сложных).
    # Переиспользуем контекст ответа: те же чанки, валидатор проверяет ответ по ним.
    # Отдельный проход вернуть: RAG_VALIDATION_SEPARATE_CONTEXT=true.
    if _env_bool("RAG_VALIDATION_SEPARATE_CONTEXT", False):
        validation_context_windows = expand_context_windows(
            chunks,
            collection=getattr(rag_backend, "collection_name", ""),
            logger=logger,
            max_chunks=_env_int("RAG_VALIDATION_CONTEXT_MAX_CHUNKS", 10),
            max_chars_per_chunk=_env_int("RAG_VALIDATION_CONTEXT_WINDOW_CHARS", 2600),
            radius=_env_int("RAG_VALIDATION_CONTEXT_RADIUS", 1),
        )
    else:
        validation_context_windows = context_windows
    retrieval_trace["validation_context_window"] = validation_context_windows.payload()
    t_ctx = time.time() - t_ctx_start
    validation_context = ""

    configured_runtime = _llm_runtime()
    # W3.3 (ADR-9): гейт чувствительности. P0-данные физически не уходят в облако;
    # P2 — только при явном LES_CLOUD_CONSENT; иначе принудительный fallback на MLX.
    _source_ds = set(_dataset_ids_from_chunks(chunks)) | {str(d) for d in (_dataset_ids or [])}
    _route = decide_provider(
        configured_runtime.provider,
        _dataset_sensitivities(_source_ds),
        consent=_env_bool("LES_CLOUD_CONSENT", False),
    )
    if _route.downgraded:
        logger.warning("[ROUTE] %s (датасеты: %s)", _route.reason, sorted(_source_ds))
        llm_runtime = _mlx_runtime()
    else:
        # W3.3 memory-aware: локальный конкурент MLX за RAM (ollama/lemonade) на тесной
        # памяти сводится к MLX (защита от swap — полевой вывод 2026-06-11).
        _avail_gb = (state.metrics_cache or {}).get("ram_free_gb") if state.metrics_cache else None
        _mem_provider, _mem_reason = memory_aware_provider(
            configured_runtime.provider,
            available_gb=_avail_gb,
            threshold_gb=_env_float("LES_LOCAL_PROVIDER_MIN_FREE_GB", 6.0),
        )
        llm_runtime = _mlx_runtime() if _mem_reason else configured_runtime
        if _mem_reason:
            logger.warning("[ROUTE] %s", _mem_reason)
    cache_state: dict[str, Any] = {}
    if llm_runtime.provider == "freetoken":
        from proxy.services.freetoken_cache_profile_service import reconcile_freetoken_cache

        desired_kv = _env_int("FREETOKEN_CONTEXT_TOKENS", 8253)
        cache_state = await asyncio.to_thread(
            reconcile_freetoken_cache,
            llm_runtime.base_url,
            desired_kv,
        )
        retrieval_trace["freetoken_cache"] = cache_state
        if cache_state.get("status") not in {"aligned", "synchronized"}:
            raise HTTPException(
                503,
                "FreeToken KV не синхронизирован: "
                + str(cache_state.get("reason") or cache_state.get("status")),
            )
    observed_context_tokens = None
    observed_context = False
    observed_source = "unavailable"
    if cache_state.get("status") in {"aligned", "synchronized"}:
        try:
            observed_context_tokens = int(cache_state.get("effective_kv_tokens") or 0) or None
        except (TypeError, ValueError):
            observed_context_tokens = None
        observed_context = observed_context_tokens is not None
        observed_source = "freetoken_cache_probe" if observed_context else "unavailable"
    model_policy = (profile_snapshot or {}).get("model_policy") or {}
    execution_preset = resolve_transport_execution_profile(
        provider=llm_runtime.provider,
        model_id=llm_runtime.model,
        observed_context_tokens=observed_context_tokens,
        observed=observed_context,
        observed_source=observed_source,
        operator=model_policy,
    )
    preset_diagnostics = execution_preset.diagnostics(
        requested_input_tokens=cache_state.get("desired_kv_tokens")
    )
    preset_diagnostics["model_preset"]["requested"] = llm_runtime.model
    retrieval_trace["model_execution_profile"] = preset_diagnostics
    retrieval_trace["context_governor"] = {
        "schema": "les.context-governor.v1",
        "preset_id": execution_preset.preset_id,
        "calls": [],
    }
    try:
        typed_memory = await asyncio.to_thread(
            project_memory,
            session_id=str(req.session_id or ""),
            project_id=memory_project_id or None,
            dataset_ids=tuple(str(item) for item in _dataset_ids if str(item)),
            limits=MemoryLimits(),
        )
        memory_candidates = typed_memory.as_context_candidates()
        retrieval_trace["typed_memory"] = {
            "schema": "les.typed-memory-projection.v1",
            "context_role": typed_memory.context_role,
            "is_evidence": False,
            "items": len(typed_memory.items),
            "omitted": typed_memory.omitted,
            "cursor": typed_memory.cursor,
        }
    except Exception as memory_error:  # noqa: BLE001 - memory is advisory, never an answer blocker
        logger.warning("[TYPED_MEMORY] projection skipped: %s", type(memory_error).__name__)
        memory_candidates = ()
        retrieval_trace["typed_memory"] = {
            "schema": "les.typed-memory-projection.v1",
            "status": "skipped",
            "error_type": type(memory_error).__name__,
            "context_role": "advisory_state",
            "is_evidence": False,
        }
    retrieval_trace["routing"] = {
        "configured_provider": configured_runtime.provider,
        "configured_model": configured_runtime.model,
        "effective_provider": llm_runtime.provider,
        "effective_model": llm_runtime.model,
        "sensitivity": _route.sensitivity,
        "downgraded": llm_runtime.provider != configured_runtime.provider,
        "is_cloud": is_cloud_provider(llm_runtime.provider),
    }
    llm_model = llm_runtime.model
    val_url = llm_runtime.base_url.rstrip("/")
    # Локальный MLX-хост всегда держит /api/validate (coreml NLI, ~0.1с). Облачные ответы
    # валидируем им же, а не повторным промптом в облако (это давало 3-11с на P1-ответ).
    local_val_url = _mlx_runtime().base_url.rstrip("/")
    if not llm_model:
        raise HTTPException(503, f"LLM model is not configured for provider {llm_runtime.provider}")
    # W3.4-частично (вопрос оператора 2026-06-14 «почему не валидируем облаком?»):
    # у не-MLX провайдеров нет /api/validate — валидируем ТОЙ ЖЕ моделью
    # компактным промптом-вердиктом (VERIFIED/HALLUCINATION/NO_DATA).
    validate_via_llm = bool(use_validation and not llm_runtime.supports_validation)
    if validate_via_llm:
        logger.info("[TOSKA] validation via provider=%s (no LES /api/validate)", llm_runtime.provider)

    # The central RAG role pack already owns engineering style, source boundaries,
    # navigation-vs-evidence and human-facing wording.  Repeating those rules here
    # used to add thousands of prompt characters and, worse, made the application
    # service a second hidden prompt registry.  Keep only the source-label contract
    # that is specific to the evidence packet rendered below.
    sys_normal = profile_system_prompt(profile_snapshot, strict=False)
    sys_strict = profile_system_prompt(profile_snapshot, strict=True)

    # ADR-12 слой 2: форму ответа диктует интент вопроса (детерминированно, до генерации).
    answer_form = apply_response_length(classify_answer_form(req.question), req.response_length)
    retrieval_trace["answer_form"] = {"intent": answer_form.intent, "max_tokens": answer_form.max_tokens}
    if class_suggestions:
        retrieval_trace["class_suggestions"] = [s["class"] for s in class_suggestions]

    # Облако не держит локальный Metal-слот: отдельный пул (LES_CLOUD_LLM_CONCURRENCY).
    gen_semaphore = generation_semaphore(state.llm_semaphore)
    if gen_semaphore._value == 0:
        raise HTTPException(429, "Сервер занят — идёт генерация, попробуй через несколько секунд")

    t_gen_start = time.time()
    t_llm = 0.0  # W0.1: чистое время LLM-вызовов (включая загрузку модели на стороне MLX)
    t_val = 0.0  # W0.1: чистое время /api/validate
    answer_source_map: list[dict[str, object]] = []
    final_evidence_packet: dict[str, Any] = {}
    evidence_navigation: list[dict[str, Any]] = []
    if topic_retrieval_plan:
        evidence_navigation.append({
            "kind": "topic_selection",
            "available": True,
            "selected_files": len(topic_doc_filter),
            "context_role": "navigation",
            "is_evidence": False,
        })
    if dataset_memory_prompt:
        evidence_navigation.append({
            "kind": "dataset_memory",
            "available": True,
            "context_role": "navigation",
            "is_evidence": False,
        })
    if notebook_study_prompt:
        evidence_navigation.append({
            "kind": "notebook_study",
            "available": True,
            "context_role": "navigation",
            "is_evidence": False,
        })
    if target_file_ref:
        evidence_navigation.append({
            "kind": "target_file",
            "available": target_file_ref.get("match_status") == "matched",
            "match_status": str(target_file_ref.get("match_status") or ""),
            "context_role": "navigation",
            "is_evidence": False,
        })
    deterministic_evidence: list[dict[str, Any]] = []
    if project_inventory_payload:
        deterministic_evidence.append({
            "kind": "project_inventory",
            "source": "metadb.documents",
            "file_count": int(project_inventory_payload.get("file_count") or 0),
        })
    async with gen_semaphore:
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                answer = ""
                crag_status = "UNKNOWN"
                tokens = 0

                async def _post_llm(runtime, model, hdrs, body, *, allow_stream: bool = True):
                    """Один вызов LLM. token_sink задан → стрим (токены клиенту по
                    мере генерации), иначе — обычный POST (поведение неизменно).
                    Возвращает (answer_text, usage_dict)."""
                    if runtime.provider == "ollama":
                        # #1b: нативный /api/chat think:false → чистый ответ без CoT-дампа
                        # (OpenAI-compat ollama игнорирует reasoning-контроль). Облачного
                        # fallback у ollama нет — model == runtime.model.
                        return await _ollama_native_complete(
                            client, runtime, body["messages"],
                            max_tokens=int(body.get("max_tokens", 1400)),
                            temperature=float(body.get("temperature", 0.7)),
                            headers=hdrs, token_sink=token_sink if allow_stream else None)
                    _body = _cloud_body_for_model(body, model, runtime.provider)
                    if token_sink is not None and allow_stream:
                        sbody = {**_body, "model": model, "stream": True}
                        # include_usage нужен только облаку (учёт $); MLX/локальные —
                        # не шлём, чтобы не рисковать 400 на незнакомом поле.
                        if is_cloud_provider(runtime.provider):
                            sbody["stream_options"] = {"include_usage": True}
                        acc: list[str] = []
                        usage_d: dict = {}
                        async with client.stream("POST", runtime.chat_url, headers=hdrs, json=sbody) as sresp:
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
                                _delta = choices[0].get("delta", {}) if choices else {}
                                piece = assistant_delta_text(_delta)
                                if piece:
                                    acc.append(piece)
                                    await token_sink({"event": "token", "data": piece})
                                if chunk.get("usage"):
                                    usage_d = chunk["usage"]
                        return "".join(acc), usage_d
                    r = await client.post(runtime.chat_url, headers=hdrs, json={**_body, "model": model})
                    r.raise_for_status()
                    rj = r.json()
                    return (
                        _assistant_text(rj.get("choices", [{}])[0].get("message", {})),
                        rj.get("usage", {}) or {},
                    )

                async def _post_cloud_fallback(runtime, hdrs, body):
                    """Облако: перебор цепочки моделей с конечным таймаутом на модель.
                    Зависла/ошиблась/пустой ответ → следующая. Возвращает
                    (answer, usage, used_model); все упали → последняя ошибка."""
                    models = cloud_fallback_models(runtime)
                    per_model = cloud_model_timeout()
                    last_err: Exception = ValueError("облако: цепочка моделей пуста")
                    for i, m in enumerate(models):
                        # частичный вывод прошлой модели в стриме — отбросить
                        if token_sink is not None and i > 0:
                            await token_sink({"event": "reset", "data": ""})
                        try:
                            ans, usage_m = await asyncio.wait_for(
                                _post_llm(runtime, m, hdrs, body), timeout=per_model
                            )
                            if ans:
                                if i > 0:
                                    logger.warning("[ROUTE] облако: модель %s сработала после %s", m, models[:i])
                                return ans, usage_m, m
                            last_err = ValueError(f"пустой ответ от {m}")
                            logger.warning("[ROUTE] облако: %s дала пустой ответ — следующая модель", m)
                        except (asyncio.TimeoutError, httpx.TransportError, httpx.TimeoutException, httpx.HTTPStatusError) as e:
                            last_err = e
                            logger.warning("[ROUTE] облако: %s не ответила (%s) — следующая модель", m, type(e).__name__)
                    raise last_err

                tool_results_for_model: list[dict[str, Any]] = []
                tool_context = ""
                visual_tool_requested = any(
                    marker in str(req.question or "").casefold().replace("ё", "е")
                    for marker in ("посмотри глазами", "посмотри чертеж", "посмотри схему", "что видно на лист", "что изображено на лист")
                )
                profile_tools = [
                    str(name) for name in (profile_snapshot or {}).get("tools", []) if str(name).strip()
                ]
                canonical_route = resolve_canonical_route(receipt=None)
                retrieval_trace["canonical_route"] = canonical_route.public_payload()
                retrieval_trace["route_comparison"] = {
                    "schema": "les.canonical-route-comparison.v1",
                    "requested": canonical_route.requested.value,
                    "effective": canonical_route.effective.value,
                    "legacy_output_authoritative": (
                        canonical_route.effective is not CanonicalRouteMode.ACTIVE
                    ),
                    "same_request": True,
                    "profile_revision": str(
                        (profile_snapshot or {}).get("revision_id") or ""
                    ),
                    "canonical_provider_calls_added": 0,
                    "persisted_effects": 0,
                }
                canonical_shadow_recorded = False
                tool_loop_enabled = bool(profile_tools)
                if tool_loop_enabled:
                    try:
                        from proxy.services.tool_harness_service import harness

                        tool_harness = harness()
                        shortlist_limit = min(
                            execution_preset.max_tools,
                            max(1, _env_int("LES_CHAT_TOOL_SHORTLIST_LIMIT", 64)),
                        )
                        max_calls = min(
                            execution_preset.max_batch_items,
                            max(1, _env_int("LES_CHAT_TOOL_MAX_CALLS", 48)),
                        )
                        shortlist = await asyncio.to_thread(
                            tool_harness.shortlist,
                            req.question,
                            mode=str(req.mode or route.intent or ""),
                            allowed_tools=profile_tools,
                            limit=shortlist_limit,
                            dataset_ids=tuple(str(item) for item in _dataset_ids if str(item)),
                            workflow_phase="research",
                            model_preset=execution_preset.preset_id,
                            runtime_available=frozenset(profile_tools),
                            calls_remaining=max_calls,
                            result_chars_remaining=35_000,
                        )
                        allowed_tools = {
                            str(tool.get("name") or "")
                            for tool in shortlist.get("tools", [])
                            if isinstance(tool, dict) and tool.get("name")
                        }
                        selector_headers = {}
                        if llm_runtime.api_key:
                            selector_headers["Authorization"] = f"Bearer {llm_runtime.api_key}"
                        max_rounds = profile_research_rounds(
                            profile_snapshot,
                            configured=min(
                                execution_preset.max_batch_items,
                                max(1, min(24, _env_int("LES_CHAT_RESEARCH_MAX_ROUNDS", 12))),
                            ),
                        )
                        selected_calls: list[dict[str, Any]] = []
                        selector_usage: list[dict[str, Any]] = []
                        research_rounds: list[dict[str, Any]] = []
                        seen_call_signatures: set[str] = set()
                        stop_reason = "round_limit"
                        for research_round in range(1, max_rounds + 1):
                            prior_results = [
                                _compact_tool_result_for_prompt(item, max_chars=2400)
                                for item in tool_results_for_model[-max_calls:]
                            ]
                            selector_profile = (
                                profile_system_prompt(profile_snapshot, strict=False)
                                + "\n\nТы управляешь коротким исследовательским чтением LES. "
                                "Выбирай только read-only инструменты, чтобы закрыть конкретный пробел evidence. "
                                "Если оператор явно просит посмотреть глазами страницу или лист PDF, "
                                "обязательно выбери look_at_pdf_page с указанными файлом и номером страницы; "
                                "текстовый read_pdf_source не заменяет просмотр пикселей. "
                                "Инструменты не отвечают за тебя и не заменяют источники. "
                                "Верни только JSON {\"calls\":[{\"tool\":\"...\",\"args\":{...}}]}. "
                                "Если evidence достаточно или новый вызов повторит прошлый, верни {\"calls\":[]}. "
                                "Не выбирай инструмент вне списка и не выходи за выбранные dataset/file scope."
                            )
                            selector_checkpoint = tuple(
                                item
                                for candidate in memory_candidates
                                if candidate.kind == ContextKind.CHECKPOINT
                                for item in candidate.objects
                            )
                            selector_working_memory = tuple(
                                item
                                for candidate in memory_candidates
                                if candidate.kind == ContextKind.WORKING_MEMORY
                                for item in candidate.objects
                            )
                            selector_messages, selector_packet = govern_inference_messages(
                                preset=execution_preset,
                                profile_prefix=selector_profile,
                                request_payload={
                                    "question": req.question,
                                    "mode": req.mode or route.intent or "",
                                    "dataset_ids": _dataset_ids,
                                    "target_file": target_file_ref if target_file_ref else {},
                                    "round": research_round,
                                },
                                shortlist=shortlist.get("tools") or [],
                                checkpoint=selector_checkpoint,
                                working_memory=selector_working_memory,
                                tool_exchange=prior_results,
                            )
                            retrieval_trace["context_governor"]["calls"].append(
                                context_packet_trace(selector_packet, purpose="tool_decision")
                            )
                            selector_body = {
                                "messages": selector_messages,
                                "stream": False,
                                "temperature": 0,
                                "max_tokens": max(128, _env_int("LES_CHAT_TOOL_SELECTOR_MAX_TOKENS", 700)),
                            }
                            t_tool_selector = time.time()
                            selector_text, round_usage = await _post_llm(
                                llm_runtime,
                                llm_model,
                                selector_headers,
                                selector_body,
                                allow_stream=False,
                            )
                            t_llm += time.time() - t_tool_selector
                            selector_usage.append(round_usage)
                            proposed_calls = [
                                _augment_model_tool_args(
                                    call,
                                    question=req.question,
                                    dataset_ids=[str(d) for d in _dataset_ids],
                                    target_file_ref=target_file_ref,
                                )
                                for call in _parse_model_tool_calls(
                                    selector_text,
                                    allowed_tools=allowed_tools,
                                    max_calls=max_calls,
                                )
                            ]
                            if (
                                not canonical_shadow_recorded
                                and canonical_route.effective is CanonicalRouteMode.SHADOW
                            ):
                                shadow_trace = await safe_execute_canonical_shadow_decision(
                                        proposed_calls=proposed_calls,
                                        allowed_tools=allowed_tools,
                                        dataset_ids=[str(item) for item in _dataset_ids],
                                        tool_harness=tool_harness,
                                    )
                                shadow_trace.update(
                                    profile_revision=str(
                                        (profile_snapshot or {}).get("revision_id") or ""
                                    ),
                                    persisted_effects=0,
                                )
                                retrieval_trace["canonical_shadow"] = shadow_trace
                                canonical_shadow_recorded = True
                            calls: list[dict[str, Any]] = []
                            for call in proposed_calls:
                                signature = json.dumps(call, ensure_ascii=False, sort_keys=True, default=str)
                                if signature in seen_call_signatures:
                                    continue
                                seen_call_signatures.add(signature)
                                calls.append(call)
                                if len(selected_calls) + len(calls) >= max_calls:
                                    break
                            research_rounds.append(
                                {"round": research_round, "proposed": len(proposed_calls), "executed": len(calls)}
                            )
                            if not calls:
                                stop_reason = "model_stop" if not proposed_calls else "repeated_call"
                                break
                            for call in calls:
                                payload = await asyncio.to_thread(
                                    tool_harness.call, call["tool"], call.get("args") or {}
                                )
                                selected_calls.append(call)
                                tool_results_for_model.append(payload)
                            if len(selected_calls) >= max_calls:
                                stop_reason = "call_budget"
                                break
                        tool_context = _format_tool_results_for_model(tool_results_for_model)
                        retrieval_trace["tool_loop"] = {
                            "schema": "les_model_research_loop_v1",
                            "enabled": True,
                            "model_owns_selection": True,
                            "selector_model": llm_model,
                            "selector_provider": llm_runtime.provider,
                            "shortlist": shortlist,
                            "selected_calls": selected_calls,
                            "selector_usage": selector_usage,
                            "results": tool_results_for_model,
                            "rounds": research_rounds,
                            "stop_reason": stop_reason,
                            "max_rounds": max_rounds,
                            "max_calls": max_calls,
                        }
                    except ContextRequiredSectionOverflow as context_error:
                        retrieval_trace["context_governor"]["error"] = {
                            "code": context_error.code,
                            "purpose": "tool_decision",
                            "budget": context_error.budget,
                            "required_tokens": context_error.required_tokens,
                            "required_objects": len(context_error.object_ids),
                        }
                        raise HTTPException(
                            422,
                            detail={
                                "code": context_error.code,
                                "message": "Обязательная часть выбора инструмента не помещается в безопасный контекст модели.",
                            },
                        ) from context_error
                    except Exception as tool_err:  # noqa: BLE001 - tool loop must degrade into trace, not block chat
                        logger.warning("[TOOLS] model tool loop skipped: %s", tool_err)
                        retrieval_trace["tool_loop"] = {
                            "schema": "les_model_tool_loop_v1",
                            "enabled": True,
                            "status": "error",
                            "error": f"{type(tool_err).__name__}: {tool_err}",
                        }
                else:
                    retrieval_trace["tool_loop"] = {
                        "schema": "les_model_research_loop_v1",
                        "enabled": False,
                        "reason": "disabled_by_operator",
                        "model_owns_final_answer": True,
                    }
                if (
                    canonical_route.effective is CanonicalRouteMode.SHADOW
                    and not canonical_shadow_recorded
                ):
                    retrieval_trace["canonical_shadow"] = {
                        "schema": "les_canonical_shadow_v1",
                        "user_visible": False,
                        "persisted": False,
                        "status": "no_model_decision",
                        "executed_calls": 0,
                        "pending_calls": 0,
                        "profile_revision": str(
                            (profile_snapshot or {}).get("revision_id") or ""
                        ),
                        "persisted_effects": 0,
                    }
                max_attempts = 2
                for attempt in range(1, max_attempts + 1):
                    if attempt == 2:
                        # Ретрай не выбрасывает найденные источники: повторная генерация получает
                        # весь уже собранный evidence packet, а не новый кодовый shortlist.
                        strict_chunks = list(chunks)
                        strict_windows = expand_context_windows(
                            strict_chunks if strict_chunks else chunks[:2],
                            collection=getattr(rag_backend, "collection_name", ""),
                            logger=logger,
                            max_chunks=None,
                        )
                        ctx_chunks = strict_windows.chunks
                        evidence_packet = build_retrieval_evidence_packet(
                            question=req.question,
                            chunks=ctx_chunks,
                            retrieval_trace=retrieval_trace,
                            navigation=evidence_navigation,
                            deterministic_evidence=deterministic_evidence,
                        )
                        context = render_retrieval_evidence_for_model(
                            evidence_packet,
                            max_chars=context_chars_limit,
                            include_metadata=True,
                        )
                        answer_source_map = evidence_packet.source_map(max_chars=context_chars_limit, include_metadata=True)
                        final_evidence_packet = evidence_packet.to_dict(max_chars=context_chars_limit, include_metadata=True)
                        retrieval_trace["evidence_packet"] = evidence_packet.trace_summary(
                            max_chars=context_chars_limit,
                            include_metadata=True,
                        )
                        sys_msg = sys_strict
                        logger.warning("[SAFERAG] Retry #2 — строгий промпт, %s чанков", len(ctx_chunks))
                    else:
                        ctx_chunks = llm_chunks
                        evidence_packet = build_retrieval_evidence_packet(
                            question=req.question,
                            chunks=ctx_chunks,
                            retrieval_trace=retrieval_trace,
                            navigation=evidence_navigation,
                            deterministic_evidence=deterministic_evidence,
                        )
                        context = render_retrieval_evidence_for_model(
                            evidence_packet,
                            max_chars=context_chars_limit,
                            include_metadata=True,
                        )
                        answer_source_map = evidence_packet.source_map(
                            max_chars=context_chars_limit,
                            include_metadata=True,
                        )
                        final_evidence_packet = evidence_packet.to_dict(
                            max_chars=context_chars_limit,
                            include_metadata=True,
                        )
                        retrieval_trace["evidence_packet"] = evidence_packet.trace_summary(
                            max_chars=context_chars_limit,
                            include_metadata=True,
                        )
                        if token_sink is not None and attempt == 1:
                            await token_sink({
                                "event": "sources",
                                "data": {
                                    "sources": source_names(ctx_chunks),
                                    "source_excerpts": source_excerpts(ctx_chunks, max_n=len(ctx_chunks), max_chars=280),
                                    "source_map": answer_source_map,
                                },
                            })
                        # ADR-12 §2: каркас формы под интент добавляем к нормальному промпту.
                        sys_msg = sys_normal + (f" {answer_form.instruction}" if answer_form.instruction else "")
                        # Формат/стиль из GUI (глубина/язык) — ТОЛЬКО в системный промпт генерации,
                        # чтобы роутинг/авто-заметки/ретрив видели чистый вопрос (не мусор-директиву).
                        if req.output_directive and req.output_directive.strip():
                            sys_msg += " " + req.output_directive.strip()
                        if target_doc_filter:
                            sys_msg += (
                                " Оператор явно выбрал документы. Отвечай только по их содержимому, "
                                "явно называй использованные файлы и не расширяй область на остальной датасет."
                            )
                    question_tail = (
                        f"Вопрос: {req.question}\n\n"
                        "/no_think\n"
                        "Дай итоговый инженерный ответ. Не выдумывай факты и используй только существующие "
                        "номера [Источник N]. Если материалов недостаточно, отдели это от подтверждённых выводов."
                    )
                    answer_checkpoint = tuple(
                        item
                        for candidate in memory_candidates
                        if candidate.kind == ContextKind.CHECKPOINT
                        for item in candidate.objects
                    )
                    answer_working_memory = tuple(
                        item
                        for candidate in memory_candidates
                        if candidate.kind == ContextKind.WORKING_MEMORY
                        for item in candidate.objects
                    ) + _text_context_objects("working:legacy", memory_block) + _text_context_objects(
                        "working:project-advisory", project_memory_advisory
                    )
                    answer_working_memory += _context_objects(
                        "navigation:status", evidence_navigation
                    )
                    for navigation_name, navigation_text in (
                        ("dataset", dataset_memory_prompt),
                        ("inventory", project_inventory_prompt),
                        ("notebook", notebook_study_prompt),
                        (
                            "selected-documents",
                            "Выбранные документы: " + "; ".join(target_doc_filter) + "."
                            if target_doc_filter else "",
                        ),
                    ):
                        answer_working_memory += _text_context_objects(
                            f"navigation:{navigation_name}", navigation_text
                        )
                    answer_tool_exchange = [
                        _compact_tool_result_for_prompt(item, max_chars=2400)
                        for item in tool_results_for_model
                    ]
                    try:
                        messages, answer_packet = govern_inference_messages(
                            preset=execution_preset,
                            profile_prefix=sys_msg,
                            request_payload=question_tail,
                            checkpoint=answer_checkpoint,
                            working_memory=answer_working_memory,
                            evidence=[
                                "Материалы из найденных документов:",
                                *[
                                    item.payload
                                    for item in _text_context_objects("answer-evidence", context)
                                ],
                            ],
                            source_map=answer_source_map,
                            tool_exchange=answer_tool_exchange,
                            dialogue=[session_block] if session_block else [],
                        )
                    except ContextRequiredSectionOverflow as context_error:
                        retrieval_trace["context_governor"]["error"] = {
                            "code": context_error.code,
                            "budget": context_error.budget,
                            "required_tokens": context_error.required_tokens,
                            "required_objects": len(context_error.object_ids),
                        }
                        raise HTTPException(
                            422,
                            detail={
                                "code": context_error.code,
                                "message": "Обязательная часть запроса не помещается в безопасный контекст модели.",
                            },
                        ) from context_error
                    retrieval_trace["context_governor"]["calls"].append(
                        context_packet_trace(answer_packet, purpose="answer")
                    )
                    user_prompt = next(
                        (message["content"] for message in messages if message["role"] == "user"),
                        "",
                    )

                    prompt_layers = {
                        "system": len(sys_msg),
                        "evidence": len(context),
                        "tools": len(tool_context),
                        "dataset_navigation": len(dataset_memory_prompt),
                        "inventory_navigation": len(project_inventory_prompt),
                        "notebook_navigation": len(notebook_study_prompt),
                        "session_memory": len(session_block),
                        "working_memory": len(memory_block),
                        "project_memory_advisory": len(project_memory_advisory),
                        "question": len(req.question),
                        "user_total": len(user_prompt),
                        "messages_total": sum(len(str(message.get("content") or "")) for message in messages),
                    }
                    retrieval_trace["prompt_layers"] = prompt_layers
                    logger.info(
                        "[PROMPT] provider=%s model=%s attempt=%s chars=%s layers=%s",
                        llm_runtime.provider,
                        llm_model,
                        attempt,
                        prompt_layers["messages_total"],
                        prompt_layers,
                    )

                    headers = {}
                    if llm_runtime.api_key:
                        headers["Authorization"] = f"Bearer {llm_runtime.api_key}"
                    generation_budget = _generation_token_budget(
                        max_tokens=answer_form.max_tokens,
                        local_big=local_big,
                        attempt=attempt,
                        intent=answer_form.intent,
                    )
                    if notebook_study_prompt:
                        generation_budget = min(
                            generation_budget,
                            _env_int("LES_NOTEBOOK_STUDY_MAX_TOKENS", 2048),
                        )
                    if project_inventory_prompt:
                        generation_budget = min(
                            generation_budget,
                            _env_int("LES_PROJECT_INVENTORY_MAX_TOKENS", 3072),
                        )
                    generation_budget = min(
                        generation_budget,
                        execution_preset.generation_reserve_tokens,
                    )

                    chat_body = {
                        "messages": messages,
                        "stream": False,
                        "temperature": profile_temperature(
                            profile_snapshot,
                            fallback=_env_float("CHAT_TEMPERATURE", 0.2),
                        ),
                        "max_tokens": generation_budget,
                    }
                    # При стриминге ретрай (строгий промпт) шлёт уже новый текст —
                    # просим клиент очистить накопленное от прошлой попытки.
                    if token_sink is not None and attempt > 1:
                        await token_sink({"event": "reset", "data": ""})
                    t_llm_call = time.time()
                    try:
                        if is_cloud_provider(llm_runtime.provider):
                            # Облако: цепочка моделей с таймаутом на модель (зависла → следующая).
                            answer, usage, llm_model = await _post_cloud_fallback(llm_runtime, headers, chat_body)
                        else:
                            answer, usage = await _post_llm(llm_runtime, llm_model, headers, chat_body)
                    except (httpx.TransportError, httpx.TimeoutException, asyncio.TimeoutError, httpx.HTTPStatusError) as net_err:
                        # W3.3/ADR-9: все облачные модели не ответили → деградация на
                        # локальный MLX. Для не-облака (MLX) ошибку прокидываем как раньше.
                        if not is_cloud_provider(llm_runtime.provider):
                            raise
                        logger.warning(
                            "[ROUTE] облако %s исчерпало модели (%s) — fallback на локальный MLX",
                            llm_runtime.provider, type(net_err).__name__,
                        )
                        llm_runtime = _mlx_runtime()
                        llm_model = llm_runtime.model
                        val_url = llm_runtime.base_url.rstrip("/")
                        validate_via_llm = bool(use_validation and not llm_runtime.supports_validation)
                        fallback_preset = resolve_transport_execution_profile(
                            provider=llm_runtime.provider,
                            model_id=llm_runtime.model,
                            observed_context_tokens=None,
                            observed=False,
                            observed_source="cloud_fallback_unprobed",
                            operator=model_policy,
                        )
                        try:
                            fallback_messages, fallback_packet = govern_inference_messages(
                                preset=fallback_preset,
                                profile_prefix=sys_msg,
                                request_payload=question_tail,
                                checkpoint=answer_checkpoint,
                                working_memory=answer_working_memory,
                                evidence=[
                                    "Материалы из найденных документов:",
                                    *[
                                        item.payload
                                        for item in _text_context_objects(
                                            "answer-evidence-fallback", context
                                        )
                                    ],
                                ],
                                source_map=answer_source_map,
                                tool_exchange=answer_tool_exchange,
                                dialogue=[session_block] if session_block else [],
                            )
                        except ContextRequiredSectionOverflow as context_error:
                            retrieval_trace["context_governor"]["error"] = {
                                "code": context_error.code,
                                "purpose": "answer_fallback",
                                "budget": context_error.budget,
                                "required_tokens": context_error.required_tokens,
                                "required_objects": len(context_error.object_ids),
                            }
                            raise HTTPException(
                                422,
                                detail={
                                    "code": context_error.code,
                                    "message": "Обязательная часть ответа не помещается в локальный fallback-контекст.",
                                },
                            ) from context_error
                        retrieval_trace["context_governor"]["calls"].append(
                            context_packet_trace(fallback_packet, purpose="answer_fallback")
                        )
                        retrieval_trace["context_governor"]["fallback_preset_id"] = (
                            fallback_preset.preset_id
                        )
                        execution_preset = fallback_preset
                        headers = {}
                        retrieval_trace.setdefault("routing", {}).update(
                            {"cloud_fallback": type(net_err).__name__, "effective_provider": "mlx", "is_cloud": False}
                        )
                        # Возможный частичный вывод облака до обрыва — отбросить.
                        if token_sink is not None:
                            await token_sink({"event": "reset", "data": ""})
                        fallback_body = {
                            **chat_body,
                            "messages": fallback_messages,
                            "max_tokens": min(
                                int(chat_body.get("max_tokens") or 0),
                                fallback_preset.generation_reserve_tokens,
                            ),
                        }
                        answer, usage = await _post_llm(
                            llm_runtime,
                            llm_model,
                            headers,
                            fallback_body,
                        )
                    t_llm += time.time() - t_llm_call
                    if not answer:
                        if attempt < max_attempts:
                            logger.warning("[CHAT] empty LLM answer on attempt=%s — retrying strict", attempt)
                            continue
                        raise ValueError(f"Пустой ответ LLM (stream={token_sink is not None})")
                    tokens = usage.get("completion_tokens", 0)
                    # W3.3: учёт расходов облака (токены → $). Локальные вызовы не считаем.
                    if is_cloud_provider(llm_runtime.provider):
                        _record_cloud_cost(state, llm_model, usage)
                    logger.info(
                        "[CHAT] attempt=%s provider=%s model=%s tokens=%s",
                        attempt,
                        llm_runtime.provider,
                        llm_model,
                        tokens,
                    )

                    if use_validation:
                        try:
                            validation_context = build_validation_context(
                                validation_context_windows.chunks,
                                max_chars=_env_int("RAG_VALIDATION_CONTEXT_CHARS", 12000),
                                include_metadata=True,
                            )
                            # Рабочая память видна и валидатору — иначе ответ по заметке
                            # оператора ловил бы ложный HALLUCINATION.
                            if memory_block:
                                validation_context = f"{validation_context}\n\n{memory_block}"
                            if project_inventory_prompt:
                                validation_context = f"{validation_context}\n\n{project_inventory_prompt}"
                            if tool_context:
                                validation_context = f"{validation_context}\n\n{tool_context}"
                            t_val_call = time.time()
                            verdict_source = "coreml"
                            if validate_via_llm:
                                # W3.4: каскад rules→coreml. Дешёвый детерминированный отсев
                                # (числовой guard, пустой контекст) ДО валидатора.
                                pre = rules_pre_verdict(req.question, answer, validation_context)
                                if pre is not None:
                                    crag_status = pre
                                    verdict_source = "rules"
                                    logger.info("[TOSKA] rules short-circuit → %s (provider=%s)", pre, llm_runtime.provider)
                                else:
                                    # Облачный ответ валидируем ЛОКАЛЬНЫМ coreml (~0.1с),
                                    # а не повторным промптом в облако (было 3-11с).
                                    val_resp = await client.post(
                                        f"{local_val_url}/api/validate",
                                        json={"question": req.question, "answer": answer, "context": validation_context},
                                        timeout=90.0,
                                    )
                                    crag_status = (
                                        val_resp.json().get("status", "UNKNOWN")
                                        if val_resp.status_code == 200
                                        else "UNKNOWN"
                                    )
                            else:
                                val_resp = await client.post(
                                    f"{val_url}/api/validate",
                                    json={"question": req.question, "answer": answer, "context": validation_context},
                                    timeout=90.0,
                                )
                                crag_status = (
                                    val_resp.json().get("status", "UNKNOWN")
                                    if val_resp.status_code == 200
                                    else "UNKNOWN"
                                )
                            t_val += time.time() - t_val_call
                            # Fail-open: coreml-валидатор быстрый, но неточный (golden ~25%,
                            # вживую ложно блокировал реальные ответы). Он НЕ должен прятать
                            # ответ за заглушкой — его HALLUCINATION понижаем до UNVALIDATED
                            # (ответ виден, но помечен «не подтверждён»). Жёсткий блок
                            # остаётся только за детерминированными rules. Отключается
                            # TOSKA_FAIL_OPEN=false.
                            # АДДИТИВНЫЙ гейт (best-practice, не-хрупкий): валидатор МЕТИТ, не блокирует.
                            # ЛЮБОЙ HALLUCINATION (rules-числовой-guard ИЛИ coreml) → UNVALIDATED:
                            # ответ показан с меткой «не подтверждён», БЕЗ дорогого ретрая (он же
                            # таймаутил облако → падал на медленный локальный MLX, 34с). Числовой
                            # guard ложно рубил заземлённые ответы (контекст-валидации ≠ чанки ответа).
                            # Жёсткий блок вернуть: TOSKA_FAIL_OPEN=false.
                            if crag_status == "HALLUCINATION" and _env_bool("TOSKA_FAIL_OPEN", True):
                                logger.info("[TOSKA] fail-open: %s HALLUCINATION → UNVALIDATED (показан, без ретрая)", verdict_source)
                                crag_status = "UNVALIDATED"
                            # coreml NO_DATA на НЕПУСТОМ контексте недостоверен (golden ~25%): данные
                            # ЕСТЬ и ответ обоснован — не врать «нет данных». Понижаем до UNVALIDATED
                            # (ответ виден, помечен «не подтверждён»). Истинный NO_DATA = ПУСТОЙ контекст,
                            # его ставят детерминированные rules (verdict_source="rules"), их не трогаем.
                            if (crag_status == "NO_DATA" and verdict_source == "coreml"
                                    and validation_context.strip() and _env_bool("TOSKA_FAIL_OPEN", True)):
                                logger.info("[TOSKA] fail-open: coreml NO_DATA на непустом контексте → UNVALIDATED")
                                crag_status = "UNVALIDATED"
                            logger.info("[TOSKA] attempt=%s → %s%s", attempt, crag_status, " (via provider)" if validate_via_llm else "")
                        except Exception as ve:
                            logger.warning("[TOSKA] Validate skip: %s", ve)
                            crag_status = "UNKNOWN"
                    else:
                        crag_status = "UNVALIDATED"
                        logger.info("[TOSKA] validation disabled for this request")

                    if crag_status in ("VERIFIED", "NO_DATA", "UNVALIDATED"):
                        break

                    if answer and _env_bool("TOSKA_FAIL_OPEN", True):
                        retrieval_trace["validation_fail_open"] = {
                            "schema": "chat_validation_fail_open_v1",
                            "original_status": crag_status,
                            "final_status": "UNVALIDATED",
                            "reason": "model_answer_exists",
                        }
                        crag_status = "UNVALIDATED"
                        break

                    if attempt < max_attempts:
                        logger.warning("[SAFERAG] attempt=%s HALLUCINATION — retry...", attempt)

                if notebook_study_pack is not None:
                    crag_status = _notebook_study_validation_status(
                        crag_status,
                        has_context=bool(validation_context.strip() or context.strip()),
                    )
                answer, crag_status, final_policy = _chat_model_final_answer(answer, crag_status)
                if final_policy:
                    retrieval_trace["final_answer_policy"] = final_policy
                try:
                    from proxy.services.evidence_packet_service import verify_answer_source_labels

                    citation_check = verify_answer_source_labels(answer, answer_source_map)
                    retrieval_trace["citation_check"] = citation_check
                    if citation_check["status"] in {"missing_labels", "invalid_labels"}:
                        if crag_status == "VERIFIED":
                            crag_status = "UNVALIDATED"
                        if final_evidence_packet:
                            final_evidence_packet["evidence_status"] = "partial"
                            final_evidence_packet.setdefault("missing", []).append(
                                "Финальный ответ не содержит корректных ссылок на видимые источники"
                            )
                except Exception as citation_error:  # noqa: BLE001
                    retrieval_trace["citation_check"] = {
                        "schema": "les.answer-citation-check.v1",
                        "status": "error",
                        "error": type(citation_error).__name__,
                    }

                t_gen = time.time() - t_gen_start

                if crag_status == "HALLUCINATION":
                    state.crag_stats["hallucination"] += 1
                    state.chat_metrics["crag_fail"] += 1
                elif crag_status == "VERIFIED":
                    state.crag_stats["verified"] += 1
                    state.chat_metrics["crag_pass"] += 1
                elif crag_status == "UNVALIDATED":
                    state.crag_stats["unvalidated"] = state.crag_stats.get("unvalidated", 0) + 1
                    state.chat_metrics["crag_fail"] += 1
                else:
                    state.crag_stats["no_data"] += 1
                    state.chat_metrics["crag_fail"] += 1

                state.chat_metrics["latency_search"].append(t_search)
                state.chat_metrics["latency_gen"].append(t_gen)
                state.chat_metrics["tokens"].append(tokens)
                # W0.1: пофазная латентность; overhead = очередь семафора + сборка промпта внутри t_gen
                wall_total = time.time() - t_request_start
                phases = {
                    "pre_retrieval": round(max(0.0, t_search_start - t_request_start), 3),
                    "retrieval": round(t_search, 3),
                    "notebook_study": round(notebook_study_latency, 3),
                    "context": round(t_ctx, 3),
                    "generation": round(t_llm, 3),
                    "validation": round(t_val, 3),
                    "overhead": round(max(0.0, t_gen - t_llm - t_val), 3),
                    "total": round(t_search + notebook_study_latency + t_ctx + t_gen, 3),
                    "wall_total": round(wall_total, 3),
                }
                retrieval_trace["latency_phases"] = phases
                retrieval_trace["source_map_count"] = len(answer_source_map)
                state.chat_metrics.setdefault("latency_phases", []).append(phases)
                logger.info("[METRICS] phases=%s", phases)
                for key in ("latency_search", "latency_gen", "tokens", "latency_phases"):
                    state.chat_metrics[key] = state.chat_metrics[key][-100:]

                sources_list = source_names(chunks)
                if project_inventory_prompt:
                    sources_list = [*sources_list, "Опись файлов датасета (MetaDB documents)"]
                source_dataset_ids = _dataset_ids_from_chunks(chunks)
                source_dataset_names = _names_for_dataset_ids(source_dataset_ids, dataset_name_by_id)
                history_id = None

                try:
                    history_id = save_chat_history(
                        question=req.question,
                        answer=answer,
                        sources=sources_list,
                        crag_status=crag_status,
                        latency_sec=wall_total,
                        tokens=tokens,
                        session_id=req.session_id,
                        requested_dataset_filter=req.dataset_filter,
                        effective_dataset_filter=effective_dataset_filter,
                        resolved_dataset_ids=_dataset_ids,
                        resolved_dataset_names=resolved_dataset_names,
                        source_dataset_ids=source_dataset_ids,
                        source_dataset_names=source_dataset_names,
                        query_route=query_route_payload,
                        retrieval_trace=retrieval_trace,
                        cache_type=cache_marker,
                        validation_enabled=use_validation,
                    )
                except Exception as db_err:
                    logger.warning("[CHAT] History save error: %s", db_err)

                if use_semantic_cache and cache_embedding and cache_scope and crag_status == "VERIFIED":
                    try:
                        cache.store(
                            req.question,
                            cache_scope,
                            cache_embedding,
                            answer,
                            sources_list,
                            crag_status,
                        )
                    except Exception as cache_err:
                        logger.warning("[SEM_CACHE] store skipped: %s", cache_err)
                elif use_semantic_cache and cache_scope and crag_status == "UNVALIDATED":
                    try:
                        cache.store_session_unvalidated(
                            req.question,
                            cache_scope,
                            focused_fingerprint,
                            answer,
                            sources_list,
                            crag_status,
                            req.session_id,
                        )
                    except Exception as cache_err:
                        logger.warning("[SESSION_CACHE] store skipped: %s", cache_err)

                # Numeric provenance гард (Codex §8, пет, flag-only): числа в ответе, которых нет
                # в контексте — возможно не заземлённые. Метим, не блокируем. Сбой → пропуск.
                try:
                    from proxy.services.saferag_service import numeric_provenance_check
                    _num_unverified = numeric_provenance_check(answer, context)
                except Exception:  # noqa: BLE001
                    _num_unverified = []

                response: dict[str, Any] = {
                    "answer": answer,
                    "crag_status": crag_status,
                    "sources": sources_list,
                    "effective_dataset_filter": effective_dataset_filter,
                    "query_route": query_route_payload,
                    "retrieval_trace": retrieval_trace,
                    "cache": cache_marker,
                    "validation": {"enabled": use_validation},
                    "history_id": history_id,
                    "source_excerpts": source_excerpts(chunks),
                    "source_map": answer_source_map,
                    "evidence_packet": final_evidence_packet,
                    "latency_phases": phases,
                    "class_suggestions": class_suggestions,
                    "versions": _version_stamp(),
                    "numeric_unverified": _num_unverified,
                }
                if notebook_study_pack is not None:
                    response["notebook_context"] = notebook_study_pack.payload()
                    if notebook_study_artifact:
                        response["artifact"] = {
                            "title": "Инженерный блокнот",
                            "mode": "markdown",
                            "content": notebook_study_artifact,
                        }
                if dataset_memory_prompt:
                    response["dataset_memory"] = {
                        "schema": "dataset_memory_context_v1",
                        "context_role": "navigation",
                        "is_evidence": False,
                    }
                if project_inventory_prompt:
                    response["project_inventory"] = project_inventory_payload or {}
                    if notebook_study_pack is not None and notebook_study_artifact:
                        response["notebook_artifact"] = {
                            "title": "Инженерный блокнот",
                            "mode": "markdown",
                            "content": notebook_study_artifact,
                        }
                if project_inventory_prompt:
                    response["artifact"] = {
                        "title": "Реестр файлов",
                        "mode": "markdown",
                        "content": "```text\n" + (project_inventory_artifact_text or project_inventory_prompt).replace("```", "'''") + "\n```",
                        "project_inventory": project_inventory_payload or {},
                    }

                # W6.7: source_id CAD/BIM-элементов из текста чанков → ответ + снимок
                # подсветки. Вьювер АТЛАС поллит /api/cad-bim/highlight и перекрашивает.
                # The only ordinary-RAG write hook. It runs after a successful
                # response is complete and performs at most a durable queue INSERT.
                try:
                    evidence_sources = list(
                        ((final_evidence_packet.get("evidence") or {}).get("sources") or [])
                    )
                    memory_refs = [
                        {
                            "ref_id": str(item.get("id") or ""),
                            "doc_id": str(item.get("doc_id") or item.get("doc_name") or ""),
                            "locator": json.dumps(
                                item.get("locator") or {}, ensure_ascii=False, sort_keys=True
                            ),
                            "source_revision": str(item.get("source_version") or ""),
                            "is_evidence": bool(item.get("is_evidence")),
                            "snippet_sha256": "",
                        }
                        for item in evidence_sources
                        if isinstance(item, dict) and item.get("is_evidence")
                    ]
                    get_memory_port().enqueue_rag_turn(
                        memory_project_id,
                        {
                            "question": str(req.question or ""),
                            "answer": answer,
                            "crag_status": crag_status,
                            "query_route": query_route_payload,
                            "evidence_refs": memory_refs,
                            "retrieval_fingerprint": focused_fingerprint,
                            "cache_hit": False,
                        },
                    )
                except Exception as memory_error:  # queue pressure cannot fail chat
                    logger.warning("[MEMORY] grounded turn enqueue skipped: %s", memory_error)

                cad_bim_ids, cad_bim_import_id = extract_highlight(
                    getattr(chunk, "content", "") or "" for chunk in chunks
                )
                if cad_bim_ids:
                    response["source_ids"] = cad_bim_ids
                    response["cad_bim"] = {
                        "import_id": cad_bim_import_id,
                        "source_ids": cad_bim_ids,
                    }
                    try:
                        set_highlight(cad_bim_ids, import_id=cad_bim_import_id, question=req.question)
                    except Exception as hl_err:  # подсветка не должна ронять ответ
                        logger.warning("[CHAT] highlight store skipped: %s", hl_err)

                return response

        except HTTPException:
            raise
        except httpx.TimeoutException as e:
            logger.error("[CHAT] LLM TIMEOUT: %s", e)
            raise HTTPException(504, "LLM timeout (>120s) — модель перегружена или не отвечает. Попробуй позже.")
        except httpx.HTTPStatusError as e:
            detail = f"LLM HTTP {e.response.status_code}: {e.response.text[:200]}"
            logger.error("[CHAT] LLM HTTP ERROR: %s", detail)
            raise HTTPException(502, detail)
        except httpx.ConnectError as e:
            logger.error("[CHAT] LLM CONNECT ERROR: %s", e)
            raise HTTPException(503, f"LLM недоступен ({llm_runtime.base_url}) — проверь MLX Host.")
        except Exception as e:
            import traceback

            logger.error("[CHAT] UNEXPECTED ERROR: %s\n%s", e, traceback.format_exc())
            raise HTTPException(500, f"{type(e).__name__}: {e}")
