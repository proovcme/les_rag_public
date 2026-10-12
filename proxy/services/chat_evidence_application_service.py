"""General evidence/RAG application execution extracted from the HTTP router.

The caller resolves request scope and deterministic tools first. This service owns the
unchanged retrieval -> context/evidence -> model -> sources/trace execution branch.
"""
from __future__ import annotations

from functools import partial

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from backend.runtime_paths import mutable_path
from proxy.smeta_core.material_accounting import RESOURCE_FIELDS
from typing import Any, Callable, Mapping, Sequence

import httpx
from fastapi import HTTPException

from backend.inference.routing import (
    cloud_allowed,
    decide_provider,
    is_cloud_provider,
)
from backend.inference.validator import rules_pre_verdict
from proxy.services.answer_form_service import classify_answer_form
from proxy.services.answer_form_service import (
    answer_echoes_prompt,
    answer_is_degenerate_repetition,
    apply_response_length,
    finalize_truncated_answer,
    is_transient_retrieval_block,
    strip_unsupported_links,
)
from proxy.services.cad_bim_highlight import extract_highlight, set_highlight
from proxy.services.canonical_route_service import (
    BoundModelChatRunner,
    CanonicalRouteMode,
    canonical_route_trace_payload,
    one_model_decision_from_calls,
    resolve_canonical_route,
)
from proxy.services.canonical_promotion_service import resolve_promoted_route
from proxy.services.candidate_acceptance_service import execution_mode_for_candidate_acceptance
from proxy.services.model_connection_contracts import ConnectionLocality, ConnectionRole
from proxy.services.openai_compatible_transport_service import (
    InferenceRequest,
    InferenceResponse,
    ModelTransportError,
)
from proxy.services.context_governor_service import (
    ContextCandidate,
    ContextGovernor,
    ContextKind,
    ContextObject,
    ContextPacket,
    ContextRequiredSectionOverflow,
    conservative_token_estimate,
)
from proxy.services.context_expander_service import expand_context_windows
from proxy.services.evidence_packet_service import (
    build_retrieval_evidence_packet,
    render_retrieval_evidence_for_model,
)
from proxy.services.lexical_index_service import retrieval_fingerprint
from proxy.services.smeta_evidence_delivery_service import smeta_evidence_delivery_trace
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
from proxy.services.chat_profile_service import effective_retrieval_policy
from proxy.services.retrieval_service import required_reranker_policy, retrieve_chat_chunks
from proxy.services.runtime_admission import acquire_generation_slot, generation_semaphore
from proxy.services.saferag_service import (
    build_validation_context,
    concentrate_sources,
    rank_chunks_for_question,
    source_names,
)
from proxy.services.table_query_service import maybe_answer_table_query
from proxy.services.memory_port import get_memory_port
from proxy.services.llm_transport_profile_service import (
    is_control_channel_text,
    assistant_delta_text,
    resolve_transport_execution_profile,
)


_WORKBOOK_TOOL_NAMES = frozenset({"build_lsr_workbook", "build_vor_workbook"})


def prioritize_workbook_tools(
    profile_tools: Sequence[str],
    *,
    workbook_phase: bool,
) -> list[str]:
    """Keep attachment-bound workbook choices inside a small-model shortlist.

    Ordering only controls what the model can see. It never selects or executes
    a tool on the model's behalf.
    """
    tools = [str(name) for name in profile_tools if str(name).strip()]
    if not workbook_phase:
        return tools
    workbook = [name for name in tools if name in _WORKBOOK_TOOL_NAMES]
    other = [name for name in tools if name not in _WORKBOOK_TOOL_NAMES]
    return workbook + other


def tool_selector_request_payload(
    *,
    question: str,
    mode: str,
    dataset_ids: Sequence[str],
    target_file_ref: dict[str, Any] | None,
    round_no: int,
    attachment_id: str | None,
) -> dict[str, Any]:
    """Describe the exact operator-bound inputs required for model tool choice."""
    payload: dict[str, Any] = {
        "question": question,
        "mode": mode,
        "dataset_ids": list(dataset_ids),
        "target_file": target_file_ref if target_file_ref else {},
        "round": round_no,
    }
    bound_attachment = str(attachment_id or "").strip()
    if bound_attachment:
        payload["attachment"] = {
            "bound": True,
            "attachment_id": bound_attachment,
        }
    return payload
from proxy.services.model_execution_preset_service import ModelExecutionPreset
from proxy.services.model_research_tool_service import (
    FailedToolCallGuard,
    ModelResearchToolService,
    evidence_limit,
    model_rag_empty_queries,
    model_rag_failure_detail,
    retrieve_smeta_norm_cards,
)
from proxy.services.source_locator_service import evidence_counts, source_map_item
from proxy.services.chat_evidence_manifest_service import build_evidence_manifest
from proxy.services.chat_capability_scope_service import filter_profile_tools
from proxy.services.typed_memory_projection_service import MemoryLimits, project_memory
from proxy.services.web_research_config_service import (
    WebResearchConfig,
    capture_web_research_config,
    public_web_research_config,
)

logger = logging.getLogger(__name__)

_DOCUMENT_EVIDENCE_TOOLS = frozenset({
    "dataset_map",
    "search_sources",
    "read_source",
    "read_pdf_source",
    "look_at_pdf_page",
    "read_excel_source",
    "search_project_tables",
    "read_project_table",
    "assemble_project_volume",
})


@dataclass(frozen=True)
class _WebToolSourceChunk:
    content: str
    doc_name: str
    score: float
    meta: dict[str, Any]


def web_tools_for_request(
    tools: Sequence[str], config: WebResearchConfig
) -> list[str]:
    """Expose page reading only for the explicitly captured extended mode."""

    normalized = [str(name) for name in tools if str(name).strip()]
    if config.mode == "extended":
        return normalized
    return [name for name in normalized if name != "web_read"]


def web_source_map_from_tool_results(
    tool_results: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Project actual web evidence into locators without changing its content."""

    chunks_by_url: dict[str, _WebToolSourceChunk] = {}
    for payload in tool_results:
        tool = str(payload.get("tool") or "")
        if tool not in {"web_search", "web_read"}:
            continue
        result = payload.get("result")
        result_data = dict(result) if isinstance(result, Mapping) else {}
        search_rows = result_data.get("results")
        rows = search_rows if isinstance(search_rows, list) else []
        rows_by_url = {
            str(row.get("url") or ""): row
            for row in rows
            if isinstance(row, Mapping) and str(row.get("url") or "")
        }
        for raw_source in payload.get("sources") or []:
            if not isinstance(raw_source, Mapping):
                continue
            url = str(raw_source.get("url") or result_data.get("final_url") or "").strip()
            if not url:
                continue
            row = rows_by_url.get(url, {})
            title = str(
                raw_source.get("title")
                or result_data.get("title")
                or (row.get("title") if isinstance(row, Mapping) else "")
                or ""
            )
            content = str(
                result_data.get("text")
                or (row.get("snippet") if isinstance(row, Mapping) else "")
                or ""
            )
            chunks_by_url[url] = _WebToolSourceChunk(
                content=content,
                doc_name=title,
                score=0.0,
                meta={
                    "url": url,
                    "title": title,
                    "provider": str(result_data.get("provider") or ""),
                    "retrieved_at": str(result_data.get("retrieved_at") or ""),
                },
            )
    return [
        source_map_item(chunk, index=index)
        for index, chunk in enumerate(chunks_by_url.values(), 1)
    ]


def _merge_web_source_map(
    source_map: Sequence[dict[str, Any]],
    tool_results: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    web_sources = web_source_map_from_tool_results(tool_results)
    if not web_sources:
        return list(source_map)
    combined_sources = [
        dict(item)
        for item in source_map
        if str(((item.get("locator") or {}).get("kind") or "")) != "web_result"
    ]
    combined_sources.extend(web_sources)
    for source_index, item in enumerate(combined_sources, 1):
        item["index"] = source_index
        item["label"] = f"Источник {source_index}"
    return combined_sources


def tools_for_document_scope(tools: Sequence[str], *, enabled: bool) -> list[str]:
    """Remove indexed-document tools when the user selected no document scope."""
    normalized = [str(name) for name in tools if str(name).strip()]
    if enabled:
        return normalized
    return [name for name in normalized if name not in _DOCUMENT_EVIDENCE_TOOLS]


def native_model_tool_schemas(
    tool_contracts: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert registry contracts to provider-native function definitions."""

    schemas: list[dict[str, Any]] = []
    for contract in tool_contracts:
        name = str(contract.get("name") or "").strip()
        parameters = contract.get("input_schema")
        if not name or not isinstance(parameters, dict):
            continue
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": str(contract.get("summary") or name),
                    "parameters": parameters,
                },
            }
        )
    return schemas


@dataclass(frozen=True)
class _SkippedRetrievalQuality:
    status: str = "skipped"
    top_score: float = 0.0


@dataclass(frozen=True)
class _SkippedRetrievalTrace:
    status: str = "skipped"
    error_code: str = ""


@dataclass(frozen=True)
class _SkippedDocumentRetrieval:
    chunks: tuple[Any, ...] = ()
    trace: _SkippedRetrievalTrace = _SkippedRetrievalTrace()
    quality: _SkippedRetrievalQuality = _SkippedRetrievalQuality()

    def payload(self) -> dict[str, Any]:
        return {
            "schema": "retrieval_trace_v1",
            "status": "skipped",
            "reason": "scope_none",
            "quality": {"status": "skipped", "top_score": 0.0},
        }


def safe_selected_call_trace(call: dict[str, Any]) -> dict[str, str]:
    """Expose a call's shape without retaining model-supplied argument text."""
    arguments = call.get("args") if isinstance(call.get("args"), dict) else {}
    encoded_arguments = json.dumps(
        arguments,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    trace = {
        "tool": str(call.get("tool") or ""),
        "arguments_sha256": hashlib.sha256(encoded_arguments).hexdigest(),
    }
    if call.get("call_id"):
        trace["call_id"] = str(call["call_id"])
    return trace


def _safe_workbook_filename(value: Any) -> str:
    """Keep one operator-facing xlsx basename and never expose a local path."""

    raw = str(value or "").strip().replace("\\", "/")
    name = Path(raw).name
    if not name or name != raw or ".." in name:
        return ""
    if not name.lower().endswith(".xlsx") or name.lower() in {".xlsx", "artifact.xlsx"}:
        return ""
    return name


def _chat_workbook_filename(
    filename: Any,
    *,
    artifact_kind: str = "",
    tool: str = "",
) -> str:
    """Return a safe download name without changing workbook contents."""

    safe = _safe_workbook_filename(filename)
    if safe:
        return safe
    kind = str(artifact_kind or "").strip()
    if kind not in {"lsr_workbook", "vor_workbook"}:
        kind = "vor_workbook" if tool == "build_vor_workbook" else "lsr_workbook"
    from proxy.services.workbook_tool_service import workbook_download_filename

    return workbook_download_filename(artifact_kind=kind)


def safe_workbook_history_projection(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Retain only workbook identifiers that the chat UI can safely use."""
    result = payload if isinstance(payload, dict) else {}
    if result.get("schema") != "les.workbook_tool_result.v1":
        return {}

    def selected(value: Any, fields: tuple[str, ...]) -> dict[str, Any]:
        source = value if isinstance(value, dict) else {}
        return {field: source[field] for field in fields if field in source}

    # `bound_rows` — не идентификатор, а результат расчёта, и он обязан пережить
    # проекцию: без него измерение успеха подменялось арифметикой (ревью Codex 11.09).
    safe = selected(result, ("schema", "tool", "status", "code", "bound_rows"))
    if isinstance(result.get("row_calculation"), list):
        safe["row_calculation"] = [selected(item, ("source_row", "work_id", "status",
                                   "calculation_ref", "calculation", "pricebook", "resource_bindings",
                                   "covered_by_work_id", "parent_normative_source", "reason"))
                                   for item in result["row_calculation"] if isinstance(item, dict)]
    if safe.get("status") in {"complete", "partial"}:
        for field in ("missing", "blockers"):
            values = result.get(field)
            safe[field] = [str(value)[:500] for value in values[:100]] if isinstance(values, list) else []
            if isinstance(values, list) and len(values) > 100:
                safe[field].append(f'Ещё {len(values) - 100} замечаний сохранено в ревизии и книге.')
        if safe.get("status") == "complete" and (safe["missing"] or safe["blockers"]):
            safe["status"] = "partial"
    artifact = selected(
        result.get("artifact"),
        (
            "artifact_id", "revision_id", "revision_no", "parent_revision_id",
            "sha256", "byte_size", "download_url", "source_scope",
            "decision_checkpoint_id", "filename", "artifact_kind",
        ),
    )
    checkpoint = selected(
        result.get("checkpoint"),
        ("checkpoint_id", "phase", "status", "completed_items", "total_items", "resumed"),
    )
    source = selected(result.get("source"), ("attachment_id", "sha256", "rows"))
    if artifact:
        filename = _safe_workbook_filename(artifact.get("filename"))
        if filename:
            artifact["filename"] = filename
        else:
            artifact.pop("filename", None)
        kind = str(artifact.get("artifact_kind") or "").strip()
        if kind in {"lsr_workbook", "vor_workbook"}:
            artifact["artifact_kind"] = kind
        else:
            artifact.pop("artifact_kind", None)
        safe["artifact"] = artifact
    if checkpoint:
        safe["checkpoint"] = checkpoint
    if source:
        safe["source"] = source
    return safe


def harvest_workbook_tool_result(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Project one completed workbook tool result into chat/history metadata."""
    result = safe_workbook_history_projection(payload)
    if (
        result.get("schema") != "les.workbook_tool_result.v1"
        or result.get("status") not in {"complete", "partial"}
    ):
        return {}
    artifact = result.get("artifact") if isinstance(result.get("artifact"), dict) else {}
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    checkpoint = (
        result.get("checkpoint") if isinstance(result.get("checkpoint"), dict) else {}
    )
    attachment_id = str(source.get("attachment_id") or "").strip()
    checkpoint_id = str(checkpoint.get("checkpoint_id") or "").strip()
    source_scope = artifact.get("source_scope")
    if not isinstance(source_scope, (list, tuple, set)):
        return {}
    if (
        not artifact.get("revision_id")
        or not attachment_id
        or not checkpoint_id
        or str(checkpoint.get("status") or "") != "complete"
        or str(artifact.get("decision_checkpoint_id") or "") != checkpoint_id
        or f"attachment:{attachment_id}" not in source_scope
    ):
        return {}
    harvested = {
        "artifact": dict(artifact),
        "source": {
            key: source[key]
            for key in ("attachment_id", "sha256")
            if key in source
        },
        "attachment_retry": {
            "attachment_id": attachment_id,
            "id": attachment_id,
            "preserved": True,
            "checkpoint_id": str(checkpoint.get("checkpoint_id") or ""),
        },
        "checkpoint": dict(checkpoint),
    }
    # Причины, по которым строка не попала в расчёт, доходят до пользователя. Книга со
    # статусом `partial` внешне неотличима от полной, а расхождение измерителя —
    # «шт.» против «100 м» — сметчику важнее самой книги: в живом прогоне так потерялись
    # 18 привязок из 48, и в чате об этом не было ни слова (ревью Codex 11.09).
    reasons = [str(item) for item in (result.get("missing") or []) if str(item).strip()]
    blockers = [str(item) for item in (result.get("blockers") or []) if str(item).strip()]
    status = str(result.get("status") or "")
    # Число связанных строк нужно и при полном успехе: без него воронка не может
    # сказать, что расчёт вообще состоялся (ревью Codex 11.09).
    if reasons or blockers or status == "partial" or result.get("bound_rows") is not None:
        harvested["workbook_diagnostics"] = {
            "schema": "les.workbook_diagnostics.v2",
            "status": status,
            "unbound_rows": reasons,
            "blockers": blockers,
            # Фактический результат расчёта доходит до чата и до воронки: раньше он
            # терялся при сборке метаданных (ревью Codex 11.09).
            "bound_rows": result.get("bound_rows"),
            "row_calculation": result.get("row_calculation"),
        }
    return harvested


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
    required_evidence: Sequence[Any] = (),
    source_map: Sequence[Any] = (),
    tool_exchange: Sequence[Any] = (),
    required_tool_exchange: Sequence[Any] = (),
    dialogue: Sequence[Any] = (),
    native_tools: Sequence[Any] = (),
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
        ContextCandidate(ContextKind.EVIDENCE, _context_objects("required-evidence", required_evidence),
                         required=True),
        ContextCandidate(ContextKind.EVIDENCE, _context_objects("evidence", evidence)),
        ContextCandidate(ContextKind.SOURCE_MAP, _context_objects("source", source_map)),
        ContextCandidate(ContextKind.TOOL_EXCHANGE, _context_objects("exchange", tool_exchange)),
        ContextCandidate(ContextKind.TOOL_EXCHANGE, _context_objects("required-exchange", required_tool_exchange),
                         required=True),
        ContextCandidate(ContextKind.DIALOGUE, _context_objects("dialogue", dialogue)),
    ]
    # Native schemas travel outside messages. Reserve their serialized size with
    # the same estimator, without duplicating them in the user evidence.
    if native_tools:
        schema_tokens = ContextGovernor(preset).estimate_tokens(
            json.dumps(list(native_tools), ensure_ascii=False, separators=(",", ":"))
        )
        preset = replace(preset, safety_reserve_tokens=preset.safety_reserve_tokens + schema_tokens)
    packet = ContextGovernor(preset).pack(candidates)
    return packet.as_messages(), packet


def govern_model_rag_read_messages(
    *, preset: ModelExecutionPreset, profile_prefix: str, request_payload: Any,
    fixed_evidence: Sequence[Any], read_evidence: Sequence[Any],
    prior_evidence: Sequence[Any], exchange: Sequence[Any], native_tools: Sequence[Any],
) -> tuple[list[dict[str, str]], ContextPacket]:
    """Reserve the requested read intact; expose every displaced older object."""
    notice: list[Any] = []
    # Adding the notice itself can displace another optional object. Repack until
    # the notice describes the actual packet; required overflow remains explicit.
    for _ in range(len(prior_evidence) + 2):
        messages, packet = govern_inference_messages(
            preset=preset, profile_prefix=profile_prefix, request_payload=request_payload,
            required_evidence=[*fixed_evidence, *read_evidence], evidence=prior_evidence,
            required_tool_exchange=[*exchange, *notice], native_tools=native_tools,
        )
        updated = ([{"context_omissions": [
            {"object_ids": list(item.object_ids), "cursor": item.cursor, "reason": item.reason}
            for item in packet.omissions
        ], "meaning": "Материалы сохранены, но не доставлены в этом запросе; их отсутствие не закрывает строки."}]
                   if packet.omissions else [])
        if updated == notice:
            return messages, packet
        notice = updated
    raise RuntimeError("MODEL_RAG_READ_OMISSION_NOTICE_UNSTABLE")


def persist_model_rag_read_receipt(
    *, trace: Mapping[str, Any], question: str, attachment_context: Any,
    session_id: str | None, error: Any,
) -> dict[str, str]:
    """Keep completed reads and pending calls even when inference cannot finish."""
    from uuid import uuid4

    receipt_id = uuid4().hex
    directory = mutable_path("storage/model_read_receipts")
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{receipt_id}.json"
    temporary = directory / f"{receipt_id}.tmp"
    data = json.dumps({
        "schema": "les.model-rag-read-receipt.v1", "receipt_id": receipt_id,
        "session_id": session_id, "question": question, "attachment_context": attachment_context,
        "error": str(error) if error is not None else None, "trace": trace,
    }, ensure_ascii=False, default=str).encode("utf-8")
    with temporary.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(target)
    return {"receipt_id": receipt_id, "path": str(target), "sha256": hashlib.sha256(data).hexdigest()}


def context_packet_trace(packet: ContextPacket, *, purpose: str) -> dict[str, Any]:
    """Expose exact model-visible evidence while keeping private prompt/memory redacted."""
    visible_kinds = {ContextKind.EVIDENCE, ContextKind.SOURCE_MAP}

    def fingerprint(text: str) -> dict[str, Any]:
        return {'chars': len(text), 'sha256': hashlib.sha256(text.encode('utf-8')).hexdigest()}

    def section_trace(section) -> dict[str, Any]:
        item = {
            "kind": section.kind.value,
            "items": len(section.objects),
            "tokens": section.token_count,
            "object_fingerprints": [fingerprint(obj.render()) for obj in section.objects],
        }
        if section.kind in visible_kinds:
            item["objects"] = [
                {
                    "object_id": obj.object_id,
                    "payload": json.loads(json.dumps(obj.payload, ensure_ascii=False, default=str)),
                    "text": obj.render(),
                    "sha256": hashlib.sha256(obj.render().encode("utf-8")).hexdigest(),
                }
                for obj in section.objects
            ]
        return item

    return {
        "purpose": purpose,
        "preset_id": packet.preset_id,
        "input_budget_tokens": packet.input_budget_tokens,
        "generation_reserve_tokens": packet.generation_reserve_tokens,
        "safety_reserve_tokens": packet.safety_reserve_tokens,
        "included_tokens": packet.included_tokens,
        "message_fingerprints": [
            {'role': message['role'], **fingerprint(message['content'])}
            for message in packet.as_messages()
        ],
        "sections": [section_trace(section) for section in packet.sections],
        "omissions": [
            {
                "kind": omission.kind.value,
                "total": omission.total,
                "omitted": omission.omitted,
                "object_ids": list(omission.object_ids),
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


def profile_uses_model_driven_retrieval(
    profile_snapshot: dict[str, Any] | None,
) -> bool:
    """Keep model-authored retrieval as an estimator workflow invariant."""

    snapshot = profile_snapshot if isinstance(profile_snapshot, dict) else {}
    return bool(
        str(snapshot.get("mode") or "").strip().casefold() == "estimator"
        or (snapshot.get("rag_policy") or {}).get(
            "model_authored_initial_query", False
        )
    )


def model_rag_query_instruction(
    profile_snapshot: dict[str, Any] | None, *, rows_in_pass: int = 0,
) -> str:
    """Инструкция первого вызова модели: какие поисковые запросы вернуть."""
    budget = plan_model_rag_queries((), rows_in_pass=rows_in_pass)["budget"]
    smeta = profile_uses_smeta_norm_retrieval(profile_snapshot)
    search_scope = (
        "для работ и материалов исходного документа. Названия разделов сами по себе "
        "не являются целями поиска; используй их только как контекст позиций. "
        if smeta else "по всем фактическим строкам исходного материала. "
    )
    coverage_order = (
        "Сначала охвати содержательные позиции работ и материалов порции, "
        if smeta else "Сначала охвати все строки порции, "
    )
    text = (
        "Прочитай приложенный материал целиком. Сформулируй поисковые "
        "запросы к выбранным датасетам, необходимые для подбора evidence "
        f"{search_scope}Число запросов "
        "определяешь ты. За текущий проход исполнитель выполнит "
        f"до {budget} первых запросов по твоему порядку; остальные останутся невыполненными. "
        "Это бюджет одного прохода, а не предел дальнейшего исследования строки. "
        f"{coverage_order}затем добавляй альтернативные формулировки "
        "там, где они нужны. Не перебирай гипотетические материалы и способы выполнения, "
        "которых нет в исходных данных; неизвестные условия сохрани как неизвестные. "
        "В запросах сохраняй язык "
        "и профессиональную терминологию исходных строк; не переводи и не "
        "транслитерируй их. Сейчас не выбирай нормы "
        "и не отвечай по существу — верни только сами поисковые запросы, "
        "каждый с новой строки, без нумерации и вводных строк. "
        "Одинаковый запрос пиши один раз. Если приложена порция ведомости, "
        "подбирай evidence для её строк; дополнительные сведения из вопроса "
        "используй там, где они относятся к этим строкам."
    )
    if smeta:
        text += (
            " Заголовки разделов используй как контекст соседних позиций, а не как "
            "самостоятельные работы для поиска нормы. Роль каждой строки определяешь ты "
            "по её смыслу и соседним строкам. Пустое количество само по себе не означает заголовок: "
            "работа или изделие с неизвестным объёмом тоже требует поиска. "
            "Перед списком мысленно отдели операцию от изделия и названия раздела; "
            "сформулируй запросы для конкретных работ и нужных цен по всем содержательным "
            "позициям порции. Сохрани в запросе указанную в исходнике операцию и признаки "
            "конструкции или изделия, необходимые для её различения. Не заменяй операцию "
            "общим названием раздела и не дополняй неизвестную технологию догадкой."
        )
        # Карточки цен ищутся отдельным запросом: без него модель не видит кодов ФССЦ
        # и не может оценить самостоятельный материал (P5, 17.09).
        text += (
            " Для цены изделия или материала, который ставится отдельной операцией, добавь "
            "отдельный запрос, начинающийся с «цена:», и назови в нём изделие с ключевыми "
            "характеристиками из строки, например: цена: кабель витая пара UTP 4 пары категория 5e."
            # Живая проверка 17.09: модель писала «смета нормативная база Москва 3 квартал 2026 …»
            # и «…Atlas 05 темно серая»; в карточках норм и цен этих слов нет, и они вытесняли
            # из выдачи само изделие.
            " Изделие называй родовым наименованием, как в справочнике сметных цен; марку, "
            "артикул, производителя и цвет в запрос не пиши. В запросах норм называй вид работ "
            "и конструкцию; название базы, регион и квартал в запросы не добавляй — они выбраны "
            "для сметы заранее и в карточках не встречаются."
        )
    return text


def smeta_price_browse(query: str, limit: int) -> Any:
    """Карточки цен того справочника, по которому считается смета; None — справочник не выбран."""
    from proxy.services import fgis_price_service

    path = fgis_price_service.resolve_pricebook_path(None)
    if not path:
        return None
    return fgis_price_service.get_pricebook(path).browse(query, limit=limit)


def bind_document_price_browse(basis: Mapping[str, Any]):
    """Request-local price search over exactly the persisted document basis."""
    from proxy.services import fgis_price_service
    frozen = json.loads(json.dumps(dict(basis)))
    def browse(query: str, limit: int):
        book = fgis_price_service.pricebook_for_basis(frozen)
        return book.browse(query, limit=limit) if book is not None else None
    return browse


def document_price_source_revision(context: str, attachment_sha256: str = '') -> str:
    """Keep row-based continuation; unparsed files must not all share hash([])."""
    from proxy.smeta_core.vor_rows import rows_from_attachment_text, source_revision
    rows = rows_from_attachment_text(context)
    if rows:
        return source_revision(rows)
    if attachment_sha256:
        return 'attachment-sha256:' + attachment_sha256
    return 'unparsed-context-sha256:' + hashlib.sha256(context.encode('utf-8')).hexdigest()


def document_price_basis_or_error(store, *, session_id, source_revision, capture, http_exception):
    """Expose a technical capture conflict before any model inference."""
    from proxy.services import fgis_price_service
    try:
        return store.document_price_basis(session_id=session_id,source_revision=source_revision,capture=capture)
    except fgis_price_service.PriceBookRevisionConflict as error:
        raise http_exception(status_code=422,detail={'code':'pricebook_revision_conflict',
            'error_code':'pricebook_revision_conflict','expected':error.expected,
            'actual':error.actual,'reason':error.reason}) from error


def document_price_safe_cache_lookup(cache, question, scope, fingerprint, session_id, *, primary_document):
    """A generic cached answer cannot precede binding an estimate's document prices."""
    if primary_document:
        return None
    return cache.lookup_session_unvalidated(question, scope, fingerprint, session_id)


def profile_uses_smeta_norm_retrieval(
    profile_snapshot: dict[str, Any] | None,
) -> bool:
    """Route only the estimator workflow to the configured normative-card index."""

    snapshot = profile_snapshot if isinstance(profile_snapshot, dict) else {}
    return str(snapshot.get("mode") or "").strip().casefold() == "estimator"


def compact_estimator_draft_rows(rows: Sequence[Any]) -> list[dict[str, Any]]:
    """Project model rows for display without inventing identity or a decision."""

    compact: list[dict[str, Any]] = []
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        source_row = item.get("source_row")
        if source_row in (None, ""):
            continue
        row = {
            "work_id": str(item.get("work_id") or source_row),
            "source_row": source_row,
            "section": str(item.get("section") or "").strip(),
            "title": str(item.get("title") or "").strip(),
            "quantity": item.get("quantity"),
            "unit": str(item.get("unit") or "").strip(),
            "norm_code": str(item.get("norm_code") or "").strip(),
        }
        for field_name in ("operation", "not_covered", "analogue", "coverage", "coefficient",
                           "coefficient_basis", "coefficient_target", "evidence_refs",
                           "resource_review_ref", "resource_review_status", "nr_sp_rule_id"):
            if field_name in item:
                row[field_name] = item[field_name]
        compact.append(row)
    return compact


# Поиск по каждому запросу стоит секунды, а окно свидетельств вмещает единицы групп.
# Проходы 3 и 5 (17.09): модель выдала по 87 запросов об одной операции и упёрлась в потолок
# генерации (1600 токенов) — список оборван, выполнение заняло 20 минут, и строки порции
# остались без карточек. Код не придумывает запросы и не решает, какие из них по смыслу
# лучше: он выполняет столько, сколько отведено строкам порции, по порядку самой модели,
# а остальные показывает ей с номерами, чтобы она сама расставила приоритеты.
MODEL_RAG_QUERIES_PER_ROW = 4
MODEL_RAG_QUERIES_MIN = 8
# Запас токенов на один запрос списка. Замеры: 12–20 токенов на запрос (R13 19.09 —
# 12 запросов/178; .193 проход 2 — 3 запроса/61). Исполнитель всё равно выполнит только
# бюджет прохода, поэтому списку незачем расти до общего потолка: в контроле .199 модель
# 1600 токенов повторяла одни и те же 20 строк и не дошла до цены кабеля.
MODEL_RAG_QUERY_TOKENS_PER_QUERY = 48
MODEL_RAG_QUERY_MIN_TOKENS = 256


def model_rag_query_rows(portion_state: Mapping[str, Any] | None) -> int:
    """Сколько строк порции получают бюджет запросов.

    Заголовок раздела без единицы и количества остаётся в порции и виден модели, но
    нормы не требует. Если измеримых строк нет, действует прежний счёт по всем строкам.
    """
    state = portion_state or {}
    return int(state.get("query_rows_in_pass") or state.get("rows_in_pass") or 0)


def model_rag_query_max_tokens(*, query_budget: int, ceiling: int) -> int:
    """Предел генерации списка запросов: по бюджету прохода, не выше настроенного потолка."""
    wanted = MODEL_RAG_QUERY_TOKENS_PER_QUERY * max(int(query_budget or 0), 0)
    return max(MODEL_RAG_QUERY_MIN_TOKENS, min(int(ceiling), wanted))


def plan_model_rag_queries(
    queries: Sequence[str], *, rows_in_pass: int = 0, truncated: bool = False,
) -> dict[str, Any]:
    """Какие запросы выполнить сейчас и какие остались невыполненными."""
    items = [str(query or "").strip() for query in queries or () if str(query or "").strip()]
    budget = max(MODEL_RAG_QUERIES_MIN, MODEL_RAG_QUERIES_PER_ROW * max(int(rows_in_pass or 0), 0))
    return {
        "total": len(items),
        "budget": budget,
        "executed": items[:budget],
        "skipped": [{"index": index, "query": query}
                    for index, query in enumerate(items[budget:], budget + 1)],
        "truncated": bool(truncated),
    }


def model_rag_query_plan_note(plan: Mapping[str, Any]) -> str:
    """Сообщение модели о невыполненных запросах; пусто — выполнено всё."""
    skipped = list(plan.get("skipped") or ())
    if not skipped and not plan.get('truncated'):
        return ""
    shown = "; ".join(f"{item['index']}. {item['query']}" for item in skipped[:5])
    note = (f"\n\n[ЗАПРОСЫ] Выполнено {len(plan.get('executed') or ())} из {plan.get('total')} "
            f"твоих поисковых запросов по порядку."
            + (f" Не выполнены {len(skipped)}, начиная с: {shown}"
               + (" и другие." if len(skipped) > 5 else ".") if skipped else ""))
    if plan.get("truncated"):
        note += (" Твой список запросов был оборван по пределу генерации: он не закончен. ")
    note += (" Невыполненный запрос не означает отсутствия нормы или цены. В следующем проходе "
             "назови меньше запросов и охвати ими все строки порции, а не одну операцию.")
    return note


def parse_model_rag_queries(raw: str) -> list[str]:
    """Return the model-authored plain-text query lines without presentation wrappers."""

    plain_lines = [line.strip() for line in str(raw or "").splitlines()]
    fence_indexes = [
        index for index, line in enumerate(plain_lines) if line.startswith("```")
    ]
    if len(fence_indexes) >= 2:
        plain_lines = plain_lines[fence_indexes[0] + 1 : fence_indexes[-1]]
    visible_lines = [
        line for line in plain_lines if line and not line.startswith("```")
    ]
    if any(line.startswith(("{", "[")) or line.endswith(("}", "]")) for line in visible_lines):
        return []
    numbered = any(re.match(r"^\d+[.)]\s+", line) for line in visible_lines)
    visible_lines = [
        re.sub(r"^(?:\d+[.)]\s+|запрос\s+\d+\s*:\s+)", "", line, flags=re.IGNORECASE)
        for index, line in enumerate(visible_lines)
        if not (
            (numbered or (index == 0 and len(visible_lines) > 1))
            and re.fullmatch(
                r"(?:вот\s+)?(?:поисковые\s+)?запросы(?:\s+к\s+выбранным\s+датасетам)?"
                r"(?:\s+для\s+подбора\s+evidence)?"
                r"(?:\s+по\s+строкам\s+\d[\d\s,–—-]*)?\s*:",
                line, flags=re.IGNORECASE,
            )
        )
    ]
    explicitly_wrapped: list[str] = []
    for line in visible_lines:
        if len(line) >= 2 and line[0] == line[-1] and line[0] in {'"', "'"}:
            explicitly_wrapped.append(line[1:-1].strip())
            continue
        prefix = "search_sources"
        if not line.startswith(prefix):
            continue
        remainder = line[len(prefix) :].strip()
        if remainder.startswith("(") and remainder.endswith(")"):
            remainder = remainder[1:-1].strip()
        if (
            len(remainder) >= 2
            and remainder[0] == remainder[-1]
            and remainder[0] in {'"', "'"}
        ):
            explicitly_wrapped.append(remainder[1:-1].strip())
    raw_queries = explicitly_wrapped or visible_lines

    queries: list[str] = []
    for item in raw_queries:
        if not isinstance(item, str):
            continue
        query = item.strip()
        if query and query not in queries:
            queries.append(query)
    return queries


_RESOURCE_CODE_SHAPE = re.compile(
    r"(?:[0-9]+(?:\.[0-9]+)+|[0-9A-Za-zА-Яа-яЁё.]+(?:-[0-9A-Za-zА-Яа-яЁё.]+)+)"
)
_NR_SP_RULE_SHAPE = re.compile(r"nrsp-[0-9A-Za-z.\-]+", re.IGNORECASE)
_MATERIAL_REVIEW_STATUS_VALUES = frozenset({'confirmed', 'not_present', 'unresolved', 'rejected'})


def shifted_decision_fields(raw_row: Mapping[str, str], absence_marker: Callable[[str], bool]) -> list[str]:
    """Fields contradicting their column grammar; no missing-cell position inferred."""
    shifted: list[str] = []
    for name, value in raw_row.items():
        text = str(value or "").strip()
        if not text or absence_marker(text):
            continue
        if name in {"resource_code", "target_resource_code"} and not _RESOURCE_CODE_SHAPE.fullmatch(text):
            shifted.append(name)
        elif name == "nr_sp_rule_id" and not _NR_SP_RULE_SHAPE.fullmatch(text):
            shifted.append(name)
        elif name == 'material_review_status' and text not in _MATERIAL_REVIEW_STATUS_VALUES:
            shifted.append(name)
        elif name in {"resource_quantity", "conversion_factor"}:
            try:
                float(text.replace(",", ".").replace(" ", ""))
            except ValueError:
                shifted.append(name)
    return shifted


# Названия компонентов и число — непересекающиеся словари, поэтому «labor,machines» в
# coefficient читается однозначно: это область действия, а не коэффициент. Живой проход 4 на
# 0.30.142: строка уходила в coefficient_basis_required, хотя коэффициента модель не давала.
_COEFFICIENT_COMPONENTS = frozenset({
    "labor", "machines", "materials", "machinists",
    "труд", "машины", "материалы", "машинисты",
})


def coefficient_components_only(value: Any) -> str:
    """Область действия, ошибочно записанная в coefficient; пусто — это не она."""
    text = str(value or "").replace(";", ",").strip()
    parts = [part.strip().casefold() for part in text.split(",") if part.strip()]
    if parts and all(part in _COEFFICIENT_COMPONENTS for part in parts):
        return text
    return ""


def parse_model_rag_result(raw: str) -> tuple[str, list[dict[str, Any]]] | None:
    """Decode only an unambiguous table; preserve the authored answer and cell values."""

    required_fields = {"title", "unit", "norm_code"}
    header_fields = {
        "coefficient_basis": "coefficient_basis",
        "resource_review_ref": "resource_review_ref",
        "nr_sp_rule_id": "nr_sp_rule_id",
        "material_review_status": "material_review_status",
        "material_review_reason": "material_review_reason",
        "resource_review_status": "resource_review_status",
        "coefficient_target": "coefficient_target",
        "operation": "operation",
        "not_covered": "not_covered",
        "work_id": "work_id",
        "source_row": "source_row",
        "№": "source_row",
        "№ п/п": "source_row",
        "№ пп": "source_row",
        "section": "section",
        "раздел": "section",
        "title": "title",
        "title (наименование)": "title",
        "title (описание оборудования из комментариев)": "title",
        "наименование": "title",
        "наименование работ": "title",
        "наименование работ (из вор)": "title",
        "unit": "unit",
        "ед. изм.": "unit",
        "ед. изм": "unit",
        "quantity": "quantity",
        "кол-во": "quantity",
        "norm_code": "norm_code",
        "norm_code (выбранная норма)": "norm_code",
        "norm_code (возможная норма монтажа)": "norm_code",
        "norm_code (шифр)": "norm_code",
        "нормативная база (шифр нормы)": "norm_code",
        "вид решения": "decision_kind",
        "вид": "decision_kind",
        "decision_kind": "decision_kind",
        "входит в работу": "included_in",
        "входит в": "included_in",
        "included_in": "included_in",
        "нормативная база (norm code)": "norm_code",
        "нормативный код (гэсн/ер)": "norm_code",
        "analogue": "analogue",
        "analogue / coverage": "analogue",
        "analogue / coverage (обоснование/аналог)": "analogue",
        "analogue / coverage (обоснование)": "analogue",
        "аналог/обоснование": "analogue",
        "обоснование выбора и аналог": "analogue",
        "coverage": "coverage",
        "coverage (соответствие)": "coverage",
        "примечание инженера": "coverage",
        "примечание": "coverage_fallback",
        "примечания к составу работ": "coverage",
        "примечания к выбору": "coverage",
        "coefficient": "coefficient",
        "coefficient (кэф.)": "coefficient",
        "коэфф.": "coefficient",
        "evidence_refs": "evidence_refs",
        "evidence_refs (источник)": "evidence_refs",
    }

    def field_name(value: str) -> str:
        normalized = " ".join(value.replace("**", "").strip().split()).casefold()
        if normalized in RESOURCE_FIELDS:
            return normalized
        return header_fields.get(normalized, "")

    def cells(line: str) -> list[str]:
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            return []
        return [item.strip() for item in stripped[1:-1].split("|")]

    def number(value: str) -> int | float | None:
        normalized = value.replace("\u00a0", "").replace(" ", "").replace(",", ".")
        if not normalized:
            return None
        try:
            parsed = float(normalized)
        except ValueError:
            return None
        return int(parsed) if parsed.is_integer() else parsed

    def source_row_identity(value: str) -> int | str | None:
        authored = value.strip()
        if not authored:
            return None
        parsed = number(authored)
        return parsed if isinstance(parsed, int) else authored

    def absence_marker(value: str) -> bool:
        marker = value.strip().strip("*_` ").strip()
        if len(marker) >= 2 and (marker[0], marker[-1]) in {
            ("(", ")"),
            ("[", "]"),
        }:
            marker = marker[1:-1].strip()
        return marker.casefold() in {
            "—",
            "-",
            "–",
            "−",
            "нет",
            "н/д",
            "n/a",
            "na",
        }

    def divider_cell(value: str) -> bool:
        candidate = value.strip()
        if candidate.startswith(":"):
            candidate = candidate[1:]
        if candidate.endswith(":"):
            candidate = candidate[:-1]
        return len(candidate) >= 3 and set(candidate) == {"-"}

    def evidence_refs(value: str) -> list[str]:
        separated = value.replace("<br>", " ").replace("<br/>", " ")
        for marker in "[](),;":
            separated = separated.replace(marker, " ")
        found: list[str] = []
        for token in separated.split():
            candidate = token.strip(".*_`:").upper()
            if not candidate.startswith("Q") or ".H" not in candidate:
                continue
            left, right = candidate[1:].split(".H", 1)
            if left.isdigit() and right.isdigit():
                found.append(candidate)
        return list(dict.fromkeys(found))

    lines = str(raw or "").splitlines()
    table_rows: list[dict[str, Any]] = []
    current_section = ""
    header_index = 0
    while header_index < len(lines):
        stripped_line = lines[header_index].strip()
        if stripped_line.startswith("### ") and stripped_line[4:].casefold().startswith(
            "раздел "
        ):
            current_section = stripped_line[4:].strip()
            header_index += 1
            continue
        header = cells(lines[header_index])
        mapped_header = [field_name(item) for item in header]
        if "coverage_fallback" in mapped_header:
            fallback_name = "" if "coverage" in mapped_header else "coverage"
            mapped_header = [
                fallback_name if item == "coverage_fallback" else item
                for item in mapped_header
            ]
        mapped_set = set(mapped_header)
        # Таблица материалов не содержит norm_code, и её шапка не распознавалась: строки
        # исчезали молча (проход 18, 18.09). Узкие таблицы работ и материалов позволяют
        # модели не считать пустые ячейки широкой общей таблицы.
        material_header = {"title", "unit"}.issubset(mapped_set) and bool(
            mapped_set & {"decision_kind", "resource_code"}
        )
        if (
            not header
            or not (required_fields.issubset(mapped_set) or material_header)
            or len([item for item in mapped_header if item])
            != len(set(item for item in mapped_header if item))
        ):
            header_index += 1
            continue
        if header_index + 1 >= len(lines):
            break
        divider = cells(lines[header_index + 1])
        # Delimiter cells carry no authored data; their width need not prevent
        # reading an explicit header and aligned data cells.
        if not divider or not all(divider_cell(item) for item in divider):
            header_index += 1
            continue
        table_section = current_section
        row_index = header_index + 2
        while row_index < len(lines):
            values = cells(lines[row_index])
            if not values:
                break
            authored_values = list(values)
            while len(values) > len(header) and not values[-1].strip():
                values.pop()
            padded = len(values) < len(header)
            if padded:
                values = values + [""] * (len(header) - len(values))
            elif len(values) > len(header):
                # Only a leading source identity is safe after a column-count
                # mismatch. Keep the authored cells; never guess shifted fields.
                source = source_row_identity(values[0]) if mapped_header[0] == "source_row" else None
                if source is None:
                    return None
                table_rows.append({
                    "source_row": source, "parse_error": "column_count_mismatch",
                    "raw_cells": authored_values, "raw_header": list(header),
                })
                row_index += 1
                continue
            visible_values = [value.replace("**", "").strip() for value in values]
            if visible_values[0].casefold().startswith("раздел") and not any(
                visible_values[1:]
            ):
                table_section = visible_values[0]
                row_index += 1
                continue
            raw_row = {
                name: value
                for name, value in zip(mapped_header, visible_values, strict=True)
                if name
            }
            # Форма поля проверяется в любой строке: в проходе 17 длина строки была верной,
            # а в resource_code попал обрывок хэша чека (18.09).
            invalid_fields = shifted_decision_fields(raw_row, absence_marker)
            if invalid_fields:
                # Field grammar is contradicted. Width alone cannot establish a
                # middle omission, and neither the values nor their order are repaired.
                source = source_row_identity(values[0]) if mapped_header[0] == "source_row" else None
                if source is None:
                    return None
                table_rows.append({
                    "source_row": source,
                    "parse_error": ('invalid_decision_field' if 'material_review_status' in invalid_fields
                                    else 'column_count_mismatch'),
                    "raw_cells": authored_values, "raw_header": list(header),
                    "raw_cells_sha256": hashlib.sha256(json.dumps(authored_values, ensure_ascii=False,
                        separators=(',', ':')).encode('utf-8')).hexdigest(),
                    "raw_model_row": lines[row_index],
                    "raw_model_row_sha256": hashlib.sha256(lines[row_index].encode('utf-8')).hexdigest(),
                    "raw_table_header": lines[header_index],
                    "raw_header_sha256": hashlib.sha256(lines[header_index].encode('utf-8')).hexdigest(),
                    "row_format_diagnostic": {
                        "reason": "invalid_decision_field", "invalid_fields": invalid_fields,
                        "invalid_values": {name: raw_row[name] for name in invalid_fields},
                        "observed_width": len(authored_values), "expected_width": len(header),
                        "trailing_padding_count": max(0, len(header) - len(authored_values)),
                    },
                })
                row_index += 1
                continue
            row: dict[str, Any] = {}
            for name, value in raw_row.items():
                if not value:
                    continue
                if name == "source_row":
                    parsed_source_row = source_row_identity(value)
                    if parsed_source_row is None:
                        return None
                    row[name] = parsed_source_row
                elif name in {"quantity", "coefficient"}:
                    numeric_value = value.strip()
                    if absence_marker(numeric_value):
                        continue
                    parsed_number: int | float | None = None
                    if name == "coefficient" and "/" in numeric_value:
                        numerator_text, separator, denominator_text = numeric_value.partition("/")
                        numerator = number(numerator_text)
                        denominator = number(denominator_text)
                        if separator and numerator is not None and denominator not in {None, 0}:
                            parsed_number = numerator / denominator
                    else:
                        parsed_number = number(numeric_value)
                    if parsed_number is None:
                        if name == "coefficient":
                            row[name] = value
                            continue
                        return None
                    row[name] = parsed_number
                elif name == "evidence_refs":
                    refs = evidence_refs(value)
                    if not refs:
                        separated = value.replace(";", ",")
                        refs = [item.strip() for item in separated.split(",") if item.strip()]
                    if refs:
                        row[name] = refs
                elif name:
                    row[name] = value
            misplaced_target = coefficient_components_only(row.get("coefficient"))
            if misplaced_target:
                row.pop("coefficient", None)
                row.setdefault("coefficient_target", misplaced_target)
            embedded_refs = evidence_refs(" ".join(visible_values))
            if embedded_refs and not row.get("evidence_refs"):
                row["evidence_refs"] = embedded_refs
            if row:
                if table_section and not row.get("section"):
                    row["section"] = table_section
                table_rows.append(row)
            row_index += 1
        header_index = max(row_index, header_index + 1)
    if table_rows:
        return str(raw or ""), table_rows

    block_fields = {
        "coefficient_basis": "coefficient_basis",
        "resource_review_ref": "resource_review_ref",
        "nr_sp_rule_id": "nr_sp_rule_id",
        "resource_review_status": "resource_review_status",
        "coefficient_target": "coefficient_target",
        "operation": "operation",
        "not_covered": "not_covered",
        "work_id": "work_id",
        "source_row": "source_row",
        "section": "section",
        "title": "title",
        "unit": "unit",
        "quantity": "quantity",
        "norm_code": "norm_code",
        "analogue": "analogue",
        "coverage": "coverage",
        "coefficient": "coefficient",
        "evidence_refs": "evidence_refs",
    }
    block_rows: list[dict[str, Any]] = []
    current_block: dict[str, Any] | None = None
    invalid_block = False

    def flush_block() -> None:
        nonlocal current_block, invalid_block
        if current_block is None:
            return
        if not required_fields.issubset(current_block) or current_block.get(
            "source_row"
        ) in (None, ""):
            invalid_block = True
        else:
            block_rows.append(current_block)
        current_block = None

    for line in lines:
        stripped = line.strip()
        heading = stripped.strip("*_`# ")
        heading_parts = heading.split()
        explicit_heading_row: int | None = None
        heading_row_token = (
            heading_parts[1].rstrip(":") if len(heading_parts) >= 2 else ""
        )
        is_block_heading = (
            len(heading_parts) >= 2
            and heading_parts[0].casefold() == "строка"
            and heading_row_token.isdigit()
        )
        if is_block_heading and len(heading_parts) > 2:
            heading_suffix = " ".join(heading_parts[2:]).strip()
            if heading_parts[1].endswith(":"):
                pass
            elif heading_suffix.startswith("(") and heading_suffix.endswith(")"):
                identity_label, identity_delimiter, identity_value = heading_suffix[
                    1:-1
                ].partition("=")
                if (
                    identity_delimiter
                    and identity_label.strip().casefold() == "source_row"
                    and identity_value.strip().isdigit()
                ):
                    explicit_heading_row = int(identity_value.strip())
                else:
                    is_block_heading = False
            else:
                is_block_heading = False
        if is_block_heading:
            flush_block()
            current_block = (
                {"source_row": explicit_heading_row}
                if explicit_heading_row is not None
                else {}
            )
            continue
        if current_block is None:
            continue
        labelled = stripped.lstrip("*-+ ").strip()
        label, delimiter, value = labelled.partition(":")
        if not delimiter:
            continue
        key = field_name(label.strip().strip("*_` ")) or block_fields.get(label.strip().strip("*_` ").casefold())
        clean = value.strip().lstrip("*_` ").strip()
        if not key or not clean:
            continue
        if key == "source_row":
            parsed_source_row = source_row_identity(clean)
            if parsed_source_row is None:
                invalid_block = True
                continue
            current_block[key] = parsed_source_row
        elif key in {"quantity", "coefficient"}:
            if clean.casefold() in {
                "—", "-", "–", "−", "нет", "н/д", "n/a", "na",
            }:
                continue
            parsed_number = number(clean)
            if parsed_number is None and key == "coefficient":
                first_token = clean.split(maxsplit=1)[0].rstrip(".,;")
                parsed_number = number(first_token)
            if parsed_number is None:
                invalid_block = True
                continue
            current_block[key] = parsed_number
        elif key == "evidence_refs":
            refs = evidence_refs(clean)
            if refs:
                current_block[key] = refs
        else:
            current_block[key] = clean
    flush_block()
    if block_rows and not invalid_block:
        return str(raw or ""), block_rows

    labelled_fields = {
        "раздел": "section",
        "ед. изм.": "unit",
        "ед. изм": "unit",
        "единица": "unit",
        "unit": "unit",
        "количество": "quantity",
        "кол-во": "quantity",
        "quantity": "quantity",
        "norm_code": "norm_code",
        "шифр нормы": "norm_code",
        "вид решения": "decision_kind",
        "вид": "decision_kind",
        "decision_kind": "decision_kind",
        "входит в работу": "included_in",
        "входит в": "included_in",
        "included_in": "included_in",
        "аналог": "analogue",
        "обоснование": "coverage",
        "coverage": "coverage",
        "коэффициент": "coefficient",
        "coefficient": "coefficient",
        "evidence": "evidence_refs",
        "evidence_refs": "evidence_refs",
    }
    labelled_rows: list[dict[str, Any]] = []
    for line in lines:
        stripped = line.strip()
        separator = next(
            (candidate for candidate in (" — ", " – ", " - ") if candidate in stripped),
            "",
        )
        if not separator:
            continue
        identity, remainder = stripped.split(separator, 1)
        identity_parts = identity.split()
        if (
            len(identity_parts) != 2
            or identity_parts[0].casefold() != "строка"
            or not identity_parts[1].isdigit()
        ):
            continue
        segments = remainder.split(";")
        title = segments[0].strip()
        if not title:
            return None
        row: dict[str, Any] = {
            "source_row": int(identity_parts[1]),
            "title": title,
        }
        for segment in segments[1:]:
            label, delimiter, value = segment.partition(":")
            if not delimiter:
                continue
            key = field_name(label) or labelled_fields.get(" ".join(label.strip().split()).casefold())
            clean = value.strip()
            if not key or not clean:
                continue
            if key in {"quantity", "coefficient"}:
                parsed_number = number(clean)
                if parsed_number is None:
                    return None
                row[key] = parsed_number
            elif key == "evidence_refs":
                refs = evidence_refs(clean)
                if refs:
                    row[key] = refs
            else:
                row[key] = clean
        if not required_fields.issubset(row):
            return None
        labelled_rows.append(row)
    if labelled_rows:
        return str(raw or ""), labelled_rows
    return None


@dataclass(frozen=True)
class _ModelRagEvidenceChunk:
    """One model-visible RAG hit with its query/hit coordinate preserved."""

    content: str
    doc_id: str
    doc_name: str
    score: float
    meta: dict[str, Any]


# Общий ориентир для тел источников. Для нормативных карточек отдельный обязательный
# минимум сохраняет весь заголовок, включая фактический раздел источника.
MIN_EVIDENCE_BODY_CHARS = 240
EVIDENCE_TRUNCATION_SUFFIX = "… [карточка сокращена]"
ARCHIVE_CONTEXT_OMITTED_HEADER = " | архивный контекст не показан"


def _required_evidence_body_chars(hit: Any, body: str) -> int:
    """Reserve the normative header and a truthful truncation marker together."""
    if (getattr(hit, "meta", {}) or {}).get("smeta_full_read") is True:
        # A full exact read cannot retain its completeness claim after cutting
        # operations/resources. Existing coverage handling reports omitted groups.
        return len(body)
    required = (getattr(hit, "meta", {}) or {}).get("smeta_required_header_chars", 0)
    if type(required) is not int or required <= 0:
        return 0
    return min(len(body), required + len(EVIDENCE_TRUNCATION_SUFFIX))

# Пол ширины выбора. Три живых прогона 10.09 на одной ведомости показали, что выбор
# важнее охвата: при шести карточках модель подобрала 69 разных норм, при трёх — четыре
# на семьдесят строк, поставив «Стойку, полустойку, каркас шкафа» и организатору, и шине
# заземления, и патч-панели. Строки, не вошедшие в проход, помечаются честно
# (`_evidence_coverage_note`) и достаются следующему проходу — это лучше, чем ответ по
# всем строкам одной нормой.
MIN_EVIDENCE_HITS_PER_QUERY = 5

# Сколько карточек практики остаётся в самом тесном бюджете. Ниже опускаться незачем:
# группа перестаёт быть источником выбора, а место, которое она освободит, всё равно
# не спасёт поисковый запрос целиком.
PRACTICE_MIN_HITS = 2


def _evidence_aliases(prepared: Sequence[Any]) -> dict[tuple[int, int], tuple[int, int]]:
    """Only identical content AND provenance may share a visible body.

    Recomputed from the surviving groups on every budget pass, so a removed
    practice group cannot remain the target of an alias. Scores and query/hit
    coordinates stay in their own headers; they are not source identity.
    """
    first: dict[str, tuple[int, int]] = {}
    aliases: dict[tuple[int, int], tuple[int, int]] = {}
    for qi, _header, hits, _query in prepared:
        for hi, hit, _source_header, body in hits:
            try:
                identity = json.dumps({
                    "content": body,
                    "doc_id": getattr(hit, "doc_id", "") or "",
                    "doc_name": getattr(hit, "doc_name", "") or "",
                    "meta": getattr(hit, "meta", {}) or {},
                }, ensure_ascii=False, sort_keys=True, allow_nan=False)
            except (TypeError, ValueError):
                continue  # Unknown metadata cannot establish exact equality.
            ref = (qi, hi)
            if identity in first:
                aliases[ref] = first[identity]
            else:
                first[identity] = ref
    return aliases


def _evidence_alias_text(ref: tuple[int, int]) -> str:
    return f"См. Q{ref[0]}.H{ref[1]}: тот же текст и источник."


def _is_optional_practice_hit(hit: Any) -> bool:
    meta = getattr(hit, "meta", {}) or {}
    return bool(meta.get("practice_candidate") or meta.get("material_candidate"))


def _fit_evidence_into_budget(
    prepared: list[tuple[int, str, list[tuple[int, Any, str, str]], str]],
    *,
    max_chars: int,
) -> tuple[list[tuple[int, str, list[tuple[int, Any, str, str]], str]], int]:
    """Ужать набор свидетельств до бюджета, отбрасывая поздние запросы целиком.

    Источники у оставшихся запросов сохраняются. Обратный порядок — срезать хиты у всех
    запросов — проверен на живой сборке ЛСР 10.09 и оказался вреден: выдача стала вдвое
    многочисленнее и вчетверо хуже по профильности (18 % норм связи против 49 %), а
    модель, не найдя подходящих, сочинила несуществующий шифр. Лучше меньше строк за
    проход, но с полной выдачей по каждой.
    """

    def measure(
        groups: list[tuple[int, str, list[tuple[int, Any, str, str]], str]],
        *,
        with_bodies: bool,
        preserve_query_bodies: bool = False,
        oversized_by_floor: bool = False,
    ) -> int:
        """Заголовки, а по запросу — и место под тела: карточка без текста бесполезна."""
        segments = 0
        total = 0
        aliases = _evidence_aliases(groups)
        for group in groups:
            query_index, header, hits, _query = group
            total += len(header)
            segments += 1
            for hit_index, hit, source_header, body in hits:
                total += len(source_header) + 2
                alias = aliases.get((query_index, hit_index))
                if alias:
                    total += len(_evidence_alias_text(alias))
                elif with_bodies:
                    floor = max(min(len(body), MIN_EVIDENCE_BODY_CHARS),
                                _required_evidence_body_chars(hit, body))
                    # Карточка, которая одна больше доли бюджета на запрос, целой не дойдёт
                    # никогда. Она сокращается открыто и не вытесняет чужие запросы.
                    whole = (preserve_query_bodies and not _is_practice(group)
                             and not (oversized_by_floor and len(body) > whole_limit))
                    total += len(body) if whole else floor
                segments += 1
        return total + max(0, segments - 1) * 2

    groups = [(index, header, list(hits), query) for index, header, hits, query in prepared]
    whole_limit = max_chars // MIN_EVIDENCE_HITS_PER_QUERY

    def _is_practice(group: tuple[int, str, list[Any], str]) -> bool:
        """Группа-подсказка: практика раздела или нормы по наименованию изделия.

        Обе — дополнительный источник кандидатов, и место в окне обе отдают раньше
        поисковых запросов, которые модель сформулировала под конкретные строки. Пока
        проверялся только признак практики раздела, вторая группа вытесняла выдачу
        поиска вместо того, чтобы ужиматься самой (ревью Codex 11.09).
        """
        hits = group[2]
        return bool(hits) and all(_is_optional_practice_hit(hit[1]) for hit in hits)

    # Практика ужимается первой. Она — дополнительный источник кандидатов, и место в
    # окне не должна отбирать у запросов, которые модель сформулировала под конкретные
    # строки ведомости: при равном бюджете добавление её группы выбрасывало целиком
    # второй поисковый запрос (ревью Codex 11.09).
    # Optional exact cards must not consume the resource tails of query previews.
    # Reserve query bodies while fitting optional groups. Their floor is also
    # enforced by the renderer; long optional archive prose may still be omitted.
    # If queries alone are too large,
    # remove optional groups and retain the ordinary query-only budgeting below.
    while measure(groups, with_bodies=True, preserve_query_bodies=True) > max_chars and any(
        _is_practice(group) and len(group[2]) > PRACTICE_MIN_HITS for group in groups
    ):
        for group in groups:
            if _is_practice(group) and len(group[2]) > PRACTICE_MIN_HITS:
                group[2].pop()
                break
    # Если и ужатой практики много — она уходит целиком. Запрос, сформулированный под
    # конкретную строку ведомости, ценнее справки о разделе: при тесном бюджете две
    # оставленные карточки практики всё равно выталкивали поисковую группу
    # (ревью Codex 11.09, второй заход).
    if (
        measure(groups, with_bodies=True, preserve_query_bodies=True) > max_chars
        and any(_is_practice(group) for group in groups)
        and sum(1 for group in groups if not _is_practice(group)) >= 1
    ):
        groups = [group for group in groups if not _is_practice(group)]
    # Сначала сужаем выбор по каждой строке: три карточки на все строки полезнее шести
    # на треть из них. 10.09 при шести источниках в бюджет влезали 17 строк из 55, и
    # остальные 38 модель закрывала вслепую.
    #
    # Место запросу считается по целым телам его карточек. Пока мерили по полу в 240
    # символов, «помещались» почти все запросы, а тела потом резались поровну: в контроле
    # .199 (10.10) из 102 нормативных карточек целой не дошла ни одна — ни состава работ,
    # ни ресурсов. Запрос, которому не хватило места, уходит целиком и объявляется в
    # предупреждении об охвате: его строку закроет следующий проход.
    def overflows() -> bool:
        return measure(groups, with_bodies=True, preserve_query_bodies=True,
                       oversized_by_floor=True) > max_chars

    while overflows() and any(
        len(hits) > MIN_EVIDENCE_HITS_PER_QUERY for _index, _header, hits, _q in groups
    ):
        widest = max(len(hits) for _index, _header, hits, _q in groups)
        for _index, _header, hits, _q in groups:
            if len(hits) == widest:
                hits.pop()
    while len(groups) > 1 and overflows():
        groups.pop()
    # Единственный оставшийся запрос обязан влезть хотя бы одним источником. Если целой
    # не помещается и одна карточка, остаётся прежнее открытое сокращение с пометкой.
    while groups and measure(groups, with_bodies=True) > max_chars and len(groups[0][2]) > 1:
        groups[0][2].pop()
    if groups and measure(groups, with_bodies=False) > max_chars:
        groups = []
    if groups:
        aliases = _evidence_aliases(groups)
        mandatory = sum(_required_evidence_body_chars(hit, body)
                        for qi, _header, hits, _query in groups
                        for hi, hit, _sh, body in hits if (qi, hi) not in aliases)
        if measure(groups, with_bodies=False) + mandatory > max_chars:
            groups = []
    # Наружу отдаётся только место под заголовки: остаток бюджета делят тела.
    return groups, measure(groups, with_bodies=False)


# Признак предупреждения об охвате в готовом пакете: по нему проверяется, что модель
# его действительно увидела, а не что мы его добавили в список блоков.
COVERAGE_NOTICE_MARKER = "[ОХВАТ]"


def coverage_note_reserve_tokens() -> int:
    """Сколько токенов держать свободными под предупреждение об охвате.

    Свидетельства — необязательная секция governor'а, и лишний блок он отбрасывает с
    хвоста. Предупреждение добавляется последним, поэтому при полном бюджете отбрасывали
    именно его: флаг `coverage_notice_sent` стоял `True`, а в конечных messages текста
    не было. Место резервируется до набора групп; шестизначные числа — запас на любую
    длину ведомости.
    """
    sample = _evidence_coverage_note({"queries_covered": 999999, "queries_total": 999999})
    # Плюс разделитель между объектами секции: его governor тоже считает.
    return conservative_token_estimate(sample.strip()) + 1


def model_rag_group_char_budget(
    *,
    input_budget_tokens: int,
    included_tokens: int,
    query_count: int,
    context_chars_limit: int,
) -> int:
    """Сколько символов отдаётся группам свидетельств в финальном пакете.

    Общая с горячим путём формула: иначе тест повторял бы арифметику и молчал бы при
    её изменении. Вычитаются разделители между группами и место под предупреждение
    об охвате — без последнего governor отбрасывал именно предупреждение.
    """
    remaining = max(
        0,
        int(input_budget_tokens)
        - int(included_tokens)
        - int(query_count)
        - 2
        - coverage_note_reserve_tokens(),
    )
    return min(int(context_chars_limit), remaining * 2)


def coverage_notice_in_packet(packet: Any) -> bool:
    """Дошло ли предупреждение до модели — по объектам собранного пакета."""
    for section in getattr(packet, "sections", ()) or ():
        for item in getattr(section, "objects", ()) or ():
            try:
                text = item.render()
            except Exception:  # noqa: BLE001 — трасса не должна ронять ответ
                continue
            if COVERAGE_NOTICE_MARKER in str(text):
                return True
    return False


def _evidence_coverage_note(coverage: Mapping[str, Any]) -> str:
    """Сообщение модели о том, что ведомость обработана не целиком."""
    covered = coverage.get("queries_covered")
    total = coverage.get("queries_total")
    # Формулировка требует работы по вошедшим строкам, а не воздержания. Прогон 14:11:
    # прежний текст вместе с прочими предупреждениями прочитался как «лучше не
    # подбирать вовсе» — модель вернула все 70 строк с пустым norm_code.
    return (
        f"{chr(10)}{chr(10)}[ОХВАТ] В пакет вошли свидетельства по {covered} из {total} "
        "твоих поисковых запросов. Подбирай нормы только из показанных карточек. "
        "Если для строки ведомости подходящих карточек в пакете нет, оставь norm_code "
        "пустым — её закроет следующий проход."
    )


def model_rag_evidence_coverage(
    query_hits: Sequence[tuple[str, Sequence[Any]]],
    blocks: Sequence[str],
) -> dict[str, Any]:
    """Сколько запросов модели уместилось в бюджет свидетельств.

    Длинная ведомость за один проход не помещается, и молчать об этом нельзя: по
    непрошедшим строкам модель иначе примет решение вслепую. Пошаговая сборка сметы
    опирается ровно на это число.
    """
    total = len(list(query_hits))
    covered = sum(1 for block in blocks if str(block).startswith("[Поисковый запрос "))
    return {
        "queries_total": total,
        "queries_covered": covered,
        "queries_dropped": max(0, total - covered),
        "complete": covered >= total,
    }


def answer_evidence_blocks(
    *,
    fixed_blocks: Sequence[str],
    group_blocks: Sequence[str],
    coverage: Mapping[str, Any] | None,
    trace: dict[str, Any] | None = None,
) -> list[str]:
    """Свидетельства для финального вызова модели вместе с предупреждением об охвате.

    Предупреждение обязано лежать здесь, а не в отдельной переменной контекста: финальный
    вызов собирает пакет именно из этих блоков. Два ревью Codex подряд показали, что
    иначе модель получает неполный набор строк, не зная об этом, — 6 запросов из 51 и
    ни слова о потере.
    """
    blocks = [*(str(item) for item in fixed_blocks), *(str(item) for item in group_blocks)]
    data = coverage if isinstance(coverage, Mapping) else {}
    sent = bool(data) and not data.get("complete", True)
    if sent:
        blocks.append(_evidence_coverage_note(data).strip())
    if trace is not None:
        # Факт доставки виден в трассе: ответ модели не содержит отправленный промпт,
        # и после живого прогона 16:02 подтвердить доставку было нечем.
        trace["coverage_notice_sent"] = sent
        trace["evidence_blocks_sent"] = len(blocks)
    return blocks


def build_model_rag_evidence_groups(
    query_hits: Sequence[tuple[str, Sequence[Any]]],
    *,
    max_chars: int,
    hits_per_query: int,
    query_offset: int = 0,
) -> tuple[list[str], list[_ModelRagEvidenceChunk]]:
    """Render the profile-owned hit count without letting early queries crowd out later ones."""

    if not query_hits:
        return [], []
    prepared: list[tuple[int, str, list[tuple[int, Any, str, str]]]] = []
    source_index = 0
    fixed_chars = 0
    segment_count = 0
    for query_index, (raw_query, raw_hits) in enumerate(query_hits, 1 + query_offset):
        query = str(raw_query or "").strip()
        query_header = f"[Поисковый запрос Q{query_index}] {query}"
        if not list(raw_hits):
            # Голый заголовок неотличим от обрезанных карточек. Пустую выдачу называем
            # явно и без вывода за модель: один поиск не доказывает отсутствия нормы.
            query_header += (f"\n[Q{query_index}: поиск выполнен, совпадений нет. Это не доказывает "
                             "отсутствие нормы во всей базе — переформулируй запрос по операции и изделию.]")
        hits: list[tuple[int, Any, str, str]] = []
        fixed_chars += len(query_header)
        segment_count += 1
        # Живая проверка 17.09, проход 4: выдача цен резалась до лимита карточек норм,
        # и модель видела пять карточек цен вместо десяти.
        limit = max(1, evidence_limit(raw_hits, int(hits_per_query)))
        for hit_index, hit in enumerate(list(raw_hits)[:limit], 1):
            source_index += 1
            doc_name = str(getattr(hit, "doc_name", "") or "")
            score = float(getattr(hit, "score", 0.0) or 0.0)
            meta = getattr(hit, "meta", {}) or {}
            # PracticeChunk.score is an application count, not retrieval quality.
            # Its number belongs only in the complete archive context/provenance.
            score_label = "" if meta.get("practice_candidate") else f" | score={score:.4f}"
            archive_header = (
                ARCHIVE_CONTEXT_OMITTED_HEADER
                if 0 < int(meta.get("smeta_required_header_chars") or 0)
                < int(meta.get("smeta_archive_context_end") or 0) else ""
            )
            # Reserve the warning before fitting groups; remove it only when the
            # full archive context survives. Omitted context must be model-visible.
            source_header = f"[Q{query_index}.H{hit_index} | {doc_name}{score_label}{archive_header}]"
            body = str(getattr(hit, "content", "") or "").strip()
            hits.append((hit_index, hit, source_header, body))
            fixed_chars += len(source_header) + 2
            segment_count += 1
        prepared.append((query_index, query_header, hits, query))

    fixed_chars += max(0, segment_count - 1) * 2
    # Порог считается с запасом под тела: заголовки могут влезть, а карточке достанется
    # по несколько десятков символов — шифр без наименования и практики.
    prepared, fixed_chars = _fit_evidence_into_budget(prepared, max_chars=max_chars)
    if not prepared:
        raise ValueError("MODEL_RAG_EVIDENCE_BUDGET_TOO_SMALL_FOR_ALL_QUERY_HEADERS")

    aliases = _evidence_aliases(prepared)
    optional_groups = {qi for qi, _qh, hits, _qt in prepared
                       if hits and all(_is_optional_practice_hit(hit) for _hi, hit, _sh, _body in hits)}

    def body_floor(query_index: int, hit: Any, body: str) -> int:
        if optional_groups and query_index not in optional_groups:
            return len(body)
        return _required_evidence_body_chars(hit, body)

    bodies = [(body, body_floor(qi, hit, body))
              for qi, _qh, hits, _qt in prepared for hi, hit, _sh, body in hits
              if (qi, hi) not in aliases]
    body_budget = max_chars - fixed_chars
    low, high = 0, max((len(body) for body, _floor in bodies), default=0)
    while low < high:
        cap = (low + high + 1) // 2
        if sum(max(floor, min(len(body), cap)) for body, floor in bodies) <= body_budget:
            low = cap
        else:
            high = cap - 1
    body_cap = low

    groups: list[str] = []
    chunks: list[_ModelRagEvidenceChunk] = []
    source_index = 0
    for query_index, query_header, hits, query_text in prepared:
        group_parts = [query_header]
        for hit_index, hit, source_header, body in hits:
            source_index += 1
            visible_body = body
            meta = dict(getattr(hit, "meta", {}) or {})
            hit_cap = max(body_cap, body_floor(query_index, hit, body))
            header_end = int(meta.get("smeta_required_header_chars") or 0)
            archive_end = int(meta.get("smeta_archive_context_end") or 0)
            archive_omitted = False
            if 0 < header_end < archive_end <= len(body):
                available = hit_cap - len(EVIDENCE_TRUNCATION_SUFFIX) if len(body) > hit_cap else hit_cap
                archive_omitted = archive_end > available
                if archive_omitted:
                    # A frequency or example without its provenance/unknowns is
                    # misleading. Omit the entire optional block, keeping the
                    # canonical norm header and using space for normative content.
                    visible_body = body[:header_end] + body[archive_end:]
                meta["model_archive_evidence_delivered"] = not archive_omitted
            if len(visible_body) > hit_cap or archive_omitted:
                suffix = EVIDENCE_TRUNCATION_SUFFIX if hit_cap >= 22 else "…"
                visible_body = (
                    visible_body[: max(0, hit_cap - len(suffix))].rstrip() + suffix
                    if hit_cap
                    else ""
                )
            alias = aliases.get((query_index, hit_index))
            rendered_body = _evidence_alias_text(alias) if alias else visible_body
            if not archive_omitted:
                source_header = source_header.replace(ARCHIVE_CONTEXT_OMITTED_HEADER, "")
            group_parts.append(f"{source_header}:\n{rendered_body}")
            meta["model_evidence_truncated"] = visible_body != body
            if alias:
                meta["model_evidence_alias_of"] = f"Q{alias[0]}.H{alias[1]}"
            meta.update(
                {
                    "model_query_index": query_index,
                    "model_hit_index": hit_index,
                    "model_evidence_ref": f"Q{query_index}.H{hit_index}",
                    "model_source_index": source_index,
                    # Сам запрос, а не только его номер: «Q1.H1» живёт ровно один
                    # проход, и по сохранённому решению нельзя было бы восстановить,
                    # что именно модель видела (ревью Codex 11.09).
                    #
                    # Берётся из `prepared`, а не из переменной внешнего цикла: к этому
                    # месту она давно держит последний запрос прохода, и все карточки
                    # получали его один на всех — диагностика происхождения врала
                    # (ревью Codex 11.09, второй заход).
                    "model_query": query_text,
                }
            )
            chunks.append(
                _ModelRagEvidenceChunk(
                    content=visible_body,
                    doc_id=str(getattr(hit, "doc_id", "") or ""),
                    doc_name=str(getattr(hit, "doc_name", "") or ""),
                    score=float(getattr(hit, "score", 0.0) or 0.0),
                    meta=meta,
                )
            )
        groups.append("\n\n".join(group_parts))
    return groups, chunks


def _model_rag_source_map(chunks: Sequence[_ModelRagEvidenceChunk]) -> list[dict[str, Any]]:
    return [source_map_item(chunk, index=index) for index, chunk in enumerate(chunks, 1)]


def validate_model_rag_result_structure(
    rows: Sequence[dict[str, Any]],
    evidence_chunks: Sequence[Any],
    *,
    expected_source_rows: int,
) -> list[str]:
    """Validate references before packaging without changing model decisions."""

    errors: list[str] = []
    observed_keys: set[tuple[str, str]] = set()
    work_ids: set[str] = set()
    source_operations: dict[tuple[str, str], list[str]] = {}
    for row in rows:
        source_row = row.get("source_row")
        is_positive_int = (
            isinstance(source_row, int)
            and not isinstance(source_row, bool)
            and source_row > 0
        )
        is_authored_label = isinstance(source_row, str) and bool(source_row.strip())
        if not is_positive_int and not is_authored_label:
            errors.append("invalid_source_row")
            continue
        if row.get("parse_error"):
            # Неразобранная строка не считается и возвращается модели со своими ячейками;
            # её work_id неизвестен, и сравнивать с ним соседние операции той же позиции
            # нельзя: иначе неблокирующая ошибка формата отвергала порцию целиком
            # (живая проверка 17.09, проход 3).
            errors.append(f"model_row_format_error:{source_row}")
            continue
        source_key = (type(source_row).__name__, str(source_row))
        work_id = str(row.get("work_id") or "").strip()
        prior_ids = source_operations.setdefault(source_key, [])
        if source_key in observed_keys and (not work_id or any(not value for value in prior_ids)):
            errors.append(f"duplicate_source_row:{source_row}")
        if work_id and work_id in work_ids:
            errors.append(f"duplicate_work_id:{work_id}")
        if work_id:
            work_ids.add(work_id)
        prior_ids.append(work_id)
        observed_keys.add(source_key)

    evidence_by_ref: dict[str, dict[str, Any]] = {}
    for chunk in evidence_chunks:
        meta = dict(getattr(chunk, "meta", {}) or {})
        evidence_ref = str(meta.get("model_evidence_ref") or "").strip().upper()
        if evidence_ref:
            evidence_by_ref[evidence_ref] = meta

    def code_identity(value: Any) -> str:
        return "".join(
            character
            for character in str(value or "").strip().casefold()
            if not character.isspace() and character != ":"
        )

    from proxy.smeta_core.vor_rows import explicit_norm_absence

    for row in rows:
        source_row = row.get("source_row")
        refs = [
            str(item or "").strip().upper()
            for item in (row.get("evidence_refs") or [])
            if str(item or "").strip()
        ]
        selected_code = (
            ""
            if explicit_norm_absence(row.get("norm_code"))
            else code_identity(row.get("norm_code"))
        )
        if not refs:
            # Ссылка требуется только там, где норма выбрана. Пустой norm_code — прямо
            # предусмотренный ответ «подходящих карточек в пакете нет», и ссылаться в
            # нём не на что: живой прогон 22:31 забраковал весь проход из-за шести
            # таких строк, хотя по девятнадцати другим нормы были подобраны.
            if selected_code:
                errors.append(f"missing_evidence_ref:{source_row}")
            continue
        unknown_refs = [ref for ref in refs if ref not in evidence_by_ref]
        errors.extend(f"unknown_evidence_ref:{ref}" for ref in unknown_refs)
        if selected_code and not any(
            (
                (evidence_code := code_identity(evidence_by_ref[ref].get("norm_code")))
                and evidence_code in selected_code
            )
            for ref in refs
            if ref in evidence_by_ref
        ):
            errors.append(f"norm_code_not_in_referenced_evidence:{source_row}")
    return list(dict.fromkeys(errors))


def model_rows_must_belong_to_sheet(portion_state):
    """Строки ответа сверяются с ведомостью, пока она распознана как ведомость.

    Проход 32 (18.09): на пройденной ведомости проверка не применялась, и модель,
    которой нечего было решать, сочинила три позиции с выдуманными calculation_ref —
    они попали в книгу и в реестр источников.
    """
    return str((portion_state or {}).get("state") or "") in {"portion", "complete"}


def portion_structure_errors(rows: Sequence[Mapping[str, Any]], portion_state: Mapping[str, Any]) -> list[str]:
    """Строки ответа, которые не принадлежат порции или сливают операции позиции."""
    from proxy.smeta_core.vor_rows import decision_anchor

    errors: list[str] = []
    seen_operations: dict[str, list[tuple[str, str]]] = {}
    for row in rows:
        anchor = decision_anchor(row, portion_state.get("source_anchors") or [])
        label = str(row.get("source_row") or "").strip()
        work_id = str(row.get("work_id") or "").strip()
        if not anchor or anchor not in (portion_state.get("shown") or []):
            errors.append(f"invalid_portion_source_row:{row.get('source_row')}")
            continue
        if row.get("parse_error"):
            # Идентичность неразобранной строки неизвестна: она не сливается с соседями.
            continue
        previous = seen_operations.setdefault(anchor, [])
        if previous and (not work_id or any(not identity for _, identity in previous)):
            errors.append(f"invalid_portion_source_row:{row.get('source_row')}")
        elif any(prior_label != label for prior_label, _ in previous):
            # Downstream receipts/evidence retain the authored source label.
            # Do not merge aliases and silently lose an operation's history.
            errors.append(f"inconsistent_portion_source_label:{label}")
        previous.append((label, work_id))
    return errors


def blocking_model_rag_result_errors(errors: Sequence[str]) -> list[str]:
    """Keep evidence-code disagreement visible without withholding the model draft."""

    return [
        error
        for error in errors
        # Норма без ссылки на карточку не считается, но отказ адресуется её строке
        # (withhold_unreferenced_norms), а не всей порции (живая проверка 17.09, проход 5).
        if not str(error).startswith(("norm_code_not_in_referenced_evidence:", "model_row_format_error:",
                                      "missing_evidence_ref:", "unknown_evidence_ref:"))
    ]


def evidence_code_identity(value: Any) -> str:
    """Шифр нормы без пробелов и двоеточий: сравнение идентификаторов, а не текста."""
    return "".join(
        character
        for character in str(value or "").strip().casefold()
        if not character.isspace() and character != ":"
    )


_EVIDENCE_CARD_BODY = re.compile(r"\[(Q\d+\.H\d+) \|[^\]]*\]:?[ \t]*(.*?)(?=\n\[Q\d+\.H\d+ \||\n\[Поисковый запрос|\Z)",
                                 re.DOTALL)
_EVIDENCE_ALIAS_BODY = re.compile(r"^\s*См\. (Q\d+\.H\d+)")


def delivered_evidence_cards(packet_text: str, chunks: Sequence[Any]) -> dict[str, str]:
    """Ссылка -> шифр присутствующей карточки; это не проверка полноты её содержимого.

    Набор найденных карточек шире доставленного: упаковщик и governor отбрасывают хвост
    (аудит Codex 17.09). Повтор карточки упаковщик заменяет на «См. Q1.H1», и доставленная
    ссылка без своего оригинала ничего не подтверждает: её содержание модель не видела.
    """
    bodies: dict[str, str] = {}
    for match in _EVIDENCE_CARD_BODY.finditer(str(packet_text or "")):
        bodies.setdefault(match.group(1).upper(), match.group(2))
    complete = {ref for ref, body in bodies.items() if not _EVIDENCE_ALIAS_BODY.match(body)}
    for ref, body in bodies.items():
        alias = _EVIDENCE_ALIAS_BODY.match(body)
        if alias and alias.group(1).upper() in complete:
            complete.add(ref)
    out: dict[str, str] = {}
    for chunk in chunks or ():
        meta = getattr(chunk, "meta", {}) or {}
        ref = str(meta.get("model_evidence_ref") or "").strip().upper()
        if ref and ref in complete:
            out[ref] = str(meta.get("norm_code") or "")
    return out


def evidence_group_ids(groups: Sequence[str]) -> list[str]:
    """Идентификаторы групп так, как их видит модель в доставленном тексте.

    Нумерация по порядку списка лгала: в проходе 3 трасса писала Q1-Q14, а модель получила
    Q3-Q16, и по трассе нельзя было сказать, какая карточка доставлена (аудит Codex 17.09).
    """
    identifiers: list[str] = []
    for block in groups or ():
        match = re.match(r"\[Поисковый запрос (Q\d+)\]", str(block or ""))
        if match:
            identifiers.append(match.group(1))
    return identifiers


def delivered_group_ids(packet_text: str) -> list[str]:
    """Группы запросов, дошедшие до модели: заголовки в тексте доставленного пакета."""
    return list(dict.fromkeys(re.findall(r"\[Поисковый запрос (Q\d+)\]", str(packet_text or ""))))


def saved_norm_evidence(decisions):
    """Reuse delivered evidence for the same operation, never infer it from a receipt."""
    from proxy.smeta_core.row_decision import operation_rows
    from proxy.services.rim_lsr_trace_service import selected_norm_code

    proofs = []
    for decision in (decisions or {}).values():
        for row in operation_rows(decision):
            code = evidence_code_identity(selected_norm_code(row))
            cards = [dict(card) for card in row.get('evidence_snapshot') or []
                     if card.get('delivered') is True and card.get('sent_text')
                     and card.get('sent_sha256')
                     and evidence_code_identity(selected_norm_code({'norm_code': card.get('norm_code')})) == code]
            if code and cards:
                proofs.append(dict(source_row=str(row.get('source_row') or ''),
                                   work_id=str(row.get('work_id') or row.get('source_row') or ''),
                                   norm_code=code, cards=cards))
    return proofs


def withhold_unreferenced_norms(
    rows: Sequence[Mapping[str, Any]], *, delivered_cards: Mapping[str, str] | None = None,
    prior_evidence: Sequence[Mapping[str, Any]] = (),
    observed_refs: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """Копии строк, где норма не подкреплена доставленной карточкой, помечены к отказу.

    Шифр выбран, ссылок нет — missing_evidence_ref. Ссылки есть, но ни одна не указывает на
    карточку этого прохода — unknown_evidence_ref (проход 3 на IQ2_M: Q7.2.H1 вместо Q7.H2).
    Ссылка доставлена, а её карточка описывает другую норму — norm_code_not_in_referenced_evidence:
    подтверждает выбор совпадение шифра, а не наличие ссылки (аудит Codex 17.09). Помеченная
    строка не рассчитывается и возвращается модели со своей причиной; соседние операции остаются.

    При повторе операции принимается её сохранённое доказательство доставки карточки,
    только если новые локальные ссылки не переопределили источник этого прохода.
    Старый расчёт сам по себе не доказывает источник. Проверки формата действуют всегда.
    """
    from proxy.smeta_core.vor_rows import explicit_norm_absence

    out: list[dict[str, Any]] = []
    current_refs = set(delivered_cards or ()) | {
        str(ref).strip().upper() for ref in observed_refs if str(ref).strip()
    }
    for row in rows:
        item = dict(row)
        refs = [str(ref or "").strip().upper() for ref in (row.get("evidence_refs") or []) if str(ref or "").strip()]
        code = str(row.get("norm_code") or "").strip()
        if not row.get("parse_error") and code and not explicit_norm_absence(code):
            from proxy.services.rim_lsr_trace_service import norm_codes_in_value, selected_norm_code

            # Сравнивается ровно тот шифр, который возьмёт расчёт; несколько шифров в поле —
            # конфликт формата: подтверждать один, а считать другой нельзя (аудит Codex 17.09).
            selected = evidence_code_identity(selected_norm_code(row))
            if len(norm_codes_in_value(row.get("norm_code"))) > 1:
                item["evidence_error"] = "ambiguous_norm_code"
                out.append(item)
                continue
            proof = next((entry for entry in prior_evidence
                          if entry.get('source_row') == str(row.get('source_row') or '')
                          and entry.get('work_id') == str(row.get('work_id') or row.get('source_row') or '')
                          and entry.get('norm_code') == selected and entry.get('cards')), None)
            prior_refs = {str(card.get('ref') or '').strip().upper()
                          for card in (proof or {}).get('cards', [])}
            if (proof and not any(ref in current_refs for ref in refs)
                    and (not refs or set(refs).issubset(prior_refs))):
                item['evidence_snapshot'] = [dict(card) for card in proof['cards']]
                out.append(item)
                continue
            if not refs:
                item["evidence_error"] = "missing_evidence_ref"
            elif delivered_cards is not None:
                delivered = [delivered_cards[ref] for ref in refs if ref in delivered_cards]
                if not delivered:
                    item["evidence_error"] = "unknown_evidence_ref"
                elif not any(
                    selected and evidence_code_identity(selected_norm_code({"norm_code": value})) == selected
                    for value in delivered
                ):
                    item["evidence_error"] = "norm_code_not_in_referenced_evidence"
        out.append(item)
    return out


async def post_with_delivery_messages(post, runtime, model, headers, body, *, allow_stream):
    """Return the successful request's messages alongside its unchanged response."""
    answer, usage = await post(runtime, model, headers, body, allow_stream=allow_stream)
    return answer, usage, body['messages']


def bind_normative_identity(
    rows: Sequence[Mapping[str, Any]], *, chunks: Sequence[Any] = (),
    delivered_cards: Mapping[str, str] | None = None,
    prior_evidence: Sequence[Mapping[str, Any]] = (),
    packet_text: str | None = None,
) -> list[dict[str, Any]]:
    """Bind source revision mechanically; never trust provenance authored by a model.

    Current delivered refs take precedence over persisted operation-specific proof.
    An unavailable new ref must not silently inherit an old local Q coordinate.
    """
    from proxy.services.rim_lsr_trace_service import selected_norm_code
    from proxy.smeta_core.vor_rows import explicit_norm_absence

    delivered = dict(delivered_cards or {})
    by_ref = {str((getattr(c, 'meta', {}) or {}).get('model_evidence_ref') or '').upper(): c
              for c in chunks}
    fields = ('normative_identity', 'normative_identity_status', 'normative_identity_refs', 'normative_identity_conflicts',
              'evidence_snapshot', 'resource_delivery_proof', 'source_resource_id', 'source_resource_ids', 'source_resource_group_id',
              'delivered_resource_ids', 'delivered_resource_groups')
    from proxy.services.smeta_evidence_delivery_service import resource_delivery_proofs
    resource_proofs = resource_delivery_proofs(packet_text, chunks) if packet_text is not None else {}

    def identity(card):
        value = (card.get('source_meta') or {}).get('normative_identity')
        if not isinstance(value, Mapping) or value.get('schema') != 'les.norm-revision.v1':
            return None
        if not re.fullmatch(r'[0-9a-fA-F]{64}', str(value.get('base_sha256') or '')):
            return None
        keys = ('schema', 'base_sha256', 'norm_id', 'norm_key', 'edition', 'base_type')
        if any(not str(value.get(k) or '').strip() for k in keys):
            return None
        return {k: str(value[k]) for k in keys}

    out = []
    for authored in rows:
        item = {k: v for k, v in authored.items() if k not in fields}
        if isinstance(authored.get('operations'), list):
            item['operations'] = bind_normative_identity(authored['operations'], chunks=chunks,
                delivered_cards=delivered, prior_evidence=prior_evidence, packet_text=packet_text)
            out.append(item)
            continue
        selected = evidence_code_identity(selected_norm_code(item))
        if not selected or explicit_norm_absence(item.get('norm_code')):
            out.append(item)
            continue
        refs = list(dict.fromkeys(str(r).strip().upper() for r in item.get('evidence_refs') or [] if str(r).strip()))
        cards = []
        for ref in refs:
            c = by_ref.get(ref)
            if c is None or ref not in delivered:
                continue
            meta = dict(getattr(c, 'meta', {}) or {})
            if evidence_code_identity(selected_norm_code({'norm_code': delivered[ref]})) != selected:
                continue
            if evidence_code_identity(selected_norm_code({'norm_code': meta.get('norm_code')})) != selected:
                continue
            body = str(getattr(c, 'content', '') or '')
            cards.append(dict(ref=ref, norm_code=meta.get('norm_code'), delivered=True,
                sent_text=body, sent_sha256=hashlib.sha256(body.encode('utf-8')).hexdigest()[:16],
                source_meta=meta, query=str(meta.get('model_query') or ''),
                doc_name=str(getattr(c, 'doc_name', '') or ''), doc_id=str(getattr(c, 'doc_id', '') or '')))
            if ref in resource_proofs:
                cards[-1]['resource_delivery_proof'] = resource_proofs[ref]
        # A coordinate observed in this turn belongs to this turn even when
        # Governor omitted its body. Never reinterpret it using an old local Q ID.
        if not any(ref in by_ref or ref in delivered for ref in refs):
            for proof in prior_evidence:
                if (str(proof.get('source_row') or '') != str(item.get('source_row') or '')
                    or str(proof.get('work_id') or '') != str(item.get('work_id') or item.get('source_row') or '')
                    or proof.get('norm_code') != selected):
                    continue
                prior_cards = [dict(c) for c in proof.get('cards') or []
                    if c.get('delivered') is True and c.get('sent_text') and c.get('sent_sha256')
                    and evidence_code_identity(selected_norm_code({'norm_code': c.get('norm_code')})) == selected]
                if refs and not set(refs).issubset({str(c.get('ref') or '').upper() for c in prior_cards}):
                    continue
                cards = [c for c in prior_cards if not refs or str(c.get('ref') or '').upper() in refs]
                break
        values = [identity(c) for c in cards]
        unique = {json.dumps(v, sort_keys=True): v for v in values if v is not None}
        status = 'conflict' if len(unique) > 1 else 'pinned' if len(unique) == 1 and all(v is not None for v in values) else 'unpinned'
        item.update(normative_identity=next(iter(unique.values())) if status == 'pinned' else None,
                    normative_identity_status=status, normative_identity_refs=[str(c.get('ref')) for c in cards])
        if status == 'conflict':
            item['normative_identity_conflicts'] = list(unique.values())
        if cards:
            item['evidence_snapshot'] = cards
        if status == 'pinned':
            proofs = [c['resource_delivery_proof'] for c in cards
                      if isinstance(c.get('resource_delivery_proof'), Mapping)
                      and c['resource_delivery_proof'].get('normative_identity') == item['normative_identity']]
            if proofs:
                item['resource_delivery_proof'] = dict(normative_identity=item['normative_identity'],
                    rows=[r for p in proofs for r in p.get('rows') or []],
                    groups=[g for p in proofs for g in p.get('groups') or []])
        out.append(item)
    return out


def model_rag_search_tool_schema() -> list[dict[str, Any]]:
    """Expose the selected datasets as one native search tool."""

    return native_model_tool_schemas(
        [
            {
                "name": "search_sources",
                "summary": (
                    "Искать evidence в явно выбранных датасетах. Для полного чтения нормы "
                    "(операции и все ресурсы) передай её полный шифр в q. "
                    "Дополнительный поиск необязателен: если данных достаточно, дай обычный ответ."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {"q": {"type": "string"}},
                    "required": ["q"],
                    "additionalProperties": False,
                },
            }
        ]
    )


def _bounded_source_blocks(text: str, *, max_chars: int = 700) -> list[str]:
    """Keep source rows intact while making a large attachment packable."""

    blocks: list[str] = []
    current: list[str] = []
    current_chars = 0
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        added = len(line) + (1 if current else 0)
        if current and current_chars + added > max_chars:
            blocks.append("\n".join(current))
            current = []
            current_chars = 0
        if len(line) > max_chars:
            if current:
                blocks.append("\n".join(current))
                current = []
                current_chars = 0
            blocks.append(line)
            continue
        current.append(line)
        current_chars += len(line) + (1 if current_chars else 0)
    if current:
        blocks.append("\n".join(current))
    return blocks


def _portion_row_line(row: Mapping[str, Any]) -> str:
    """Строка порции в том виде, в каком она стоит в ведомости.

    Отдаётся исходная строка целиком: артикул и производитель различают похожие позиции
    («Шкаф TTR-4281 Hyperline» и «Шкаф ШТК-М Цмо» — разные нормы и разные аналоги), а
    проекция «номер, наименование, единица, количество» их теряла (ревью Codex, R2).
    Для строк без исходных ячеек собирается та же проекция, но с точным количеством.
    """
    raw = str(row.get("raw") or "").strip()
    if raw:
        return raw
    quantity = row.get("quantity_text")
    if quantity in (None, ""):
        value = row.get("quantity")
        quantity = "" if value is None else str(value)
    unit = str(row.get("unit") or "")
    return " | ".join(
        part for part in (str(row.get("source_row") or ""), str(row.get("title") or ""), unit, str(quantity))
        if part
    )


def attachment_portion_text(
    rows: Sequence[Mapping[str, Any]],
    *,
    limit: int,
    name: str,
    after: str = "",
    completed: Sequence[str] = (),
    rejected: Mapping[str, str] | None = None,
    selected: Sequence[Mapping[str, Any]] | None = None,
) -> str:
    """Порция ведомости для одного прохода — в том виде, в каком её увидит модель.

    Ведомость целиком не помещается в окно и вытесняет карточки норм: замер 10.09
    показал, что она вместе с профилем занимает 8 444 токена из 22 528, оставляя на
    свидетельства 14 031. Поэтому в контекст уходит порция строк, а не весь файл.

    Режется набор строк, а не сами строки: каждая уходит целиком, вместе с шапкой таблицы
    и разделом, к которому относится. Обеднённая строка меняет свидетельство ещё до
    модели и мешает выбрать между похожими нормами.

    Границы названы прямо: модель должна знать, что видит часть, иначе примет её за всю
    ведомость и закроет отсутствующие строки вслепую.
    """
    from proxy.smeta_core.vor_rows import row_anchor, slice_rows

    ordered = [dict(row) for row in rows]
    if not ordered:
        return ""
    if selected is not None:
        portion = [dict(row) for row in selected]
        done = set(completed) | {row_anchor(row) for row in portion}
        rest = [row for row in ordered if row_anchor(row) not in done]
    elif completed:
        done = set(completed)
        portion, rest = slice_rows([row for row in ordered if row_anchor(row) not in done], limit=limit)
    else:
        portion, rest = slice_rows(ordered, limit=limit, after=after)
    if not portion:
        return ""
    lines = [
        f"Ведомость «{name}», позиции {portion[0].get('source_row')}–"
        f"{portion[-1].get('source_row')} из {len(ordered)}:",
        # Без этого указания у строки остаётся один исход помимо нормы — «нет
        # подходящей нормы», и крепёж, который в готовых сметах идёт ресурсом работы,
        # закрывался именно так: в прогоне 11.09 семь строк подряд (анкеры, гайки,
        # шпильки, винты) получили этот ответ, хотя в архиве они стоят под нормой на
        # лоток. Разбор ответа понимает вид решения, а модель о нём не знала.
        "Вид решения описывает способ расчёта строки, а не тип изделия в ведомости. "
        "«Работа» (decision_kind=работа) — ты выбрал норму или аналог на операцию; "
        "укажи norm_code и evidence_refs этой карточки. Оборудование или материал "
        "в исходной ведомости может требовать такой работы по монтажу. "
        "Самостоятельная стоимость изделия и работа по его монтажу — разные решения.",
        "Если по твоему решению исходная строка является только заголовком раздела, "
        "сохрани её source_row и укажи decision_kind=раздел с объяснением в analogue или coverage. "
        "Это не рассчитанная работа: не добавляй ей норму, поставку или ресурсные действия. "
        "Пустое количество само по себе не доказывает заголовок; неоднозначность оставляй уточнением.",
        "Если своей нормы у позиции нет, скажи прямо, как она попадает в смету:",
        "  «входит в работу <work_id>» — материал учтён конкретным ресурсом этой операции; "
        "назови included_in — идентификатор операции, resource_action=included (или excluded, чтобы снять материал нормы, заменяемый изделием строки, с replaced_by=work_id поставки либо replaced_by=not_required и обоснованием в coverage), "
        "target_resource_code — код конкретного материала из состава нормы и количество. "
        "Один шифр работы без ресурса не подтверждает учёт;",
        "  «самостоятельный материал» — позиция идёт в смету отдельной строкой "
        "по прайсу, нормой не считается. resource_code — только известный код ресурса прайса; "
        "без цены материал остаётся в книге с явным запросом цены;",
        "Дополнительные поля ответа можно дать колонками: decision_kind, resource_code, "
        "resource_quantity, resource_unit, included_in, resource_action, target_resource_code, target_resource_id. "
        "Optional target_resource_id: row:<SQL id> for a displayed source row, or group:<displayed digest> "
        "for an explicitly displayed group; included_in remains the parent work_id. "
        "Не объявляй материал включённым по соседству в архивной смете: нужны конкретный "
        "ресурс и количество. Для самостоятельного материала не заполняй norm_code.",
        "При доказанном пересчёте фасовки или массы сохраняй исходные quantity/unit и укажи "
        "conversion_factor (физических единиц на исходную), conversion_unit, conversion_source. "
        "Код умножит исходное количество один раз и затем переведёт в измеритель нормы. "
        "coefficient для этого не используется. Без документированного множителя назови пробел.",
        "  «нет подходящей нормы» — только когда ни одно из двух не подходит, "
        "и скажи, чего не хватает для решения.",
    ]
    previous_header = None
    previous_sheet = None
    multisheet = len({str(row.get("sheet") or "") for row in ordered}) > 1
    if multisheet:
        # Пометка мало чего стоит, если не сказать, что с ней делать: номер позиции на
        # каждом листе свой, и голая «1» неоднозначна. Такой ответ блокирует упаковку,
        # а без указания модель повторяла бы его проход за проходом — строка бы никогда
        # не закрылась. Поэтому требование названо прямо.
        lines.append(
            "В книге несколько листов, и номера позиций на них повторяются. "
            "В поле source_row копируй идентификатор из пометки [Строка ВОР] целиком, "
            "вместе с именем листа."
        )
    section = ""
    for row in portion:
        sheet = str(row.get("sheet") or "")
        header = row.get("header")
        if sheet != previous_sheet:
            if sheet:
                lines.append(f"[Лист] {sheet}")
            section = ""
        if header != previous_header or sheet != previous_sheet:
            if isinstance(header, (list, tuple)) and any(str(cell).strip() for cell in header):
                # Не «Колонки», а прямое пояснение: короткая шапка со списком имён
                # читается моделью как образец таблицы, и она копирует его в ответ.
                lines.append(
                    "Ячейки строк ниже означают: "
                    + " | ".join(str(cell).strip() for cell in header)
                )
        previous_header, previous_sheet = header, sheet
        current = str(row.get("section") or "")
        if current and current != section:
            section = current
            lines.append(f"[Раздел] {section}")
        if multisheet:
            lines.append(f"[Строка ВОР: source_row={row_anchor(row)}]")
        lines.append(_portion_row_line(row))
        previous = (rejected or {}).get(row_anchor(row))
        if previous:
            # Прошлый выбор не прошёл расчёт — модель должна знать причину, иначе
            # предложит ту же норму снова. Самый частый случай — измеритель нормы не
            # сходится с единицей строки: «шт.» против «100 м» (ревью Codex 11.09).
            lines.append(f"    [Прошлый выбор отклонён] {previous}")
    if rest:
        lines.append(
            f"Это часть ведомости. Оставшиеся {len(rest)} позиций "
            f"(с {rest[0].get('source_row')}) закроет следующий проход — "
            "не придумывай для них нормы."
        )
    return chr(10).join(lines)


def smeta_portion_rows(attachment_context: str = "") -> int:
    """Offer source rows to the budget fitter; explicit zero/negative disables portions.

    A row count is not a context budget. By default the existing fitter admits
    complete rows and receipts while reserving room for retrieval. An explicit
    positive setting remains an upper bound, not a completion/attempt limit.
    """
    raw = os.getenv("LES_SMETA_PORTION_ROWS", "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass  # An invalid legacy setting uses the same automatic default.
    from proxy.smeta_core.vor_rows import rows_from_attachment_text

    return max(1, len(rows_from_attachment_text(attachment_context)))


def portion_cursor_store() -> Any:
    """Хранилище прогресса порций; None, если его не удалось открыть.

    Без хранилища каждый проход начинается сначала — это хуже продолжения, но лучше
    отказа отвечать: ведомость всё равно будет разобрана, пусть и по первой её части.
    """
    from proxy.services.portion_cursor_service import PortionCursorService

    try:
        return PortionCursorService(mutable_path("storage/smeta_portions.db"))
    except Exception:  # noqa: BLE001 — сборка сметы не должна падать из-за хранилища
        logging.getLogger(__name__).warning(
            "[SMETA_PORTION] хранилище прогресса недоступно, проход начнётся сначала",
            exc_info=True,
        )
        return None


def closed_row_anchors(
    rows: Sequence[Mapping[str, Any]], shown: Sequence[str]
) -> list[str]:
    """Якоря строк, которые модель действительно закрыла нормой.

    Закрытой считается строка с непустым шифром: пустой `norm_code` — прямо
    предусмотренный ответ «в этом пакете карточек для неё нет», и такая строка обязана
    вернуться в следующий проход, а не исчезнуть (ревью Codex 10.09, R4).

    Модель называет строку номером позиции, а якорь несёт ещё и лист. Сопоставление
    идёт по показанным строкам: номер, которого в порции не было, не засчитывается —
    иначе решение по чужой строке двигало бы курсор.
    """
    from proxy.smeta_core.vor_rows import decision_anchor, explicit_norm_absence

    closed: list[str] = []
    for row in rows:
        if explicit_norm_absence(row.get("norm_code")):
            continue
        anchor = decision_anchor(row, shown)
        if anchor:
            closed.append(anchor)
    return list(dict.fromkeys(closed))


def declined_row_anchors(
    rows: Sequence[Mapping[str, Any]], shown: Sequence[str]
) -> list[str]:
    """Якоря строк, по которым модель прямо сказала, что нормы нет.

    Это ответ, а не молчание: строка показана, карточки прочитаны, вывод сделан. Но
    первый отказ ещё может объясняться неполным пакетом свидетельств, поэтому строке
    даётся вторая попытка — предел живёт в хранилище прогресса.

    Без такого счёта живой прогон 23:15 зациклился бы: все 25 позиций порции вернулись
    с «Нет подходящей нормы» — это чистые материалы (заглушки, накладки, суппорты), у
    которых своей нормы монтажа не бывает, и следующий проход показал бы их снова.
    """
    from proxy.smeta_core.vor_rows import decision_anchor, explicit_norm_absence

    declined: list[str] = []
    for row in rows:
        if not explicit_norm_absence(row.get("norm_code")):
            continue
        anchor = decision_anchor(row, shown)
        if anchor:
            declined.append(anchor)
    return declined


def _workbook_revision_id(workbook_chat_meta: Any) -> str | None:
    """Ревизия собранной книги, если этот проход её собрал."""
    meta = workbook_chat_meta if isinstance(workbook_chat_meta, Mapping) else {}
    artifact = meta.get("artifact") if isinstance(meta.get("artifact"), Mapping) else {}
    return str(artifact.get("revision_id") or "").strip() or None


def _portion_decisions_revision(decisions: Any, *, document_price_basis=None) -> str:
    """Отпечаток решений одной нормализацией — и для книги, и для проверки свежести."""
    from proxy.services.portion_cursor_service import decisions_revision

    return decisions_revision(decisions, document_price_basis=document_price_basis)


class _PracticeChunk:
    """Карточка нормы из практики раздела в том же виде, что и поисковая."""

    def __init__(self, card: Mapping[str, Any]) -> None:
        from proxy.services.model_research_tool_service import smeta_card_header, smeta_card_text, smeta_card_context, smeta_card_delivery_metadata

        self.content = smeta_card_text(card)
        self.doc_id = str(card.get("norm_id") or "")
        self.doc_name = "smeta_practice_cards.v1"
        self.score = float(card.get("usage_evidence", {}).get("applications") or 0)
        self.meta = {
            **{key: str(card.get(key) or "") for key in ("norm_id", "edition", "base_type")},
            "norm_code": str(card.get("norm_code") or ""),
            "measure_unit": str(card.get("measure_unit") or ""),
            "source_ref": str(card.get("source_ref") or ""),
            "smeta_required_header_chars": len(smeta_card_header(card)),
            "smeta_archive_context_end": len(smeta_card_context(card)),
            **smeta_card_delivery_metadata(card, self.content),
            "practice_candidate": True,
            "archive_provenance": card.get("archive_provenance") or {},
        }


def material_application_note(item: Mapping[str, Any]) -> str:
    """Чем норма подтверждена: изделие из чужой сметы, число применений, вид работы.

    Без наименования изделия модель не отличит дословное совпадение от совпадения по
    слову «кабель». Демонтаж называется прямо — иначе «Кабель BC5E-4-LSHF» тянул бы за
    собой «Демонтаж кабеля» молча.
    """
    note = (
        f"в архиве после этой работы указано «{item.get('material')}»"
        f" — применений {item.get('applications')}, {item.get('confidence')}"
    )
    similar = int(item.get("similar_applications") or 0)
    if similar > int(item.get("applications") or 0):
        note += f"; с близкими по названию изделиями — {similar} применений"
    if item.get("demolition"):
        note += "; это демонтажная норма"
    return note


def material_candidate_card(item: Mapping[str, Any]) -> dict[str, Any] | None:
    """Карточка нормы из активной базы с пояснением о подтвердившем её изделии.

    Измеритель и состав работы берутся из базы, а не из строки архивной сметы: в смете
    рядом с нормой стоит её измеритель на момент того расчёта, и подставить его вместо
    базового значило бы считать по чужой единице. Ненайденная норма пропускается —
    модель сошлётся на карточку, которой нет, и расчёт её отвергнет.
    """
    from proxy.smeta_core.norm_browser import browse_norms

    code = str(item.get("norm_code") or "").strip()
    if not code:
        return None
    try:
        found = (browse_norms(code, limit=1) or {}).get("cards") or []
    except Exception:  # noqa: BLE001 — подсказка не должна ронять ответ
        return None
    card = next(
        (dict(row) for row in found if str(row.get("norm_code") or "").strip() == code),
        None,
    )
    if card is None:
        return None
    card["application_note"] = material_application_note(item)
    from proxy.smeta_core.estimate_usage import archive_provenance
    card["archive_provenance"] = archive_provenance(item, card)
    return card


class _MaterialChunk:
    """Карточка нормы, подобранной по наименованию изделия."""

    def __init__(self, card: Mapping[str, Any], item: Mapping[str, Any], render: Any) -> None:
        from proxy.services.model_research_tool_service import smeta_card_header, smeta_card_context, smeta_card_delivery_metadata
        code = str(card.get("norm_code") or "")
        self.content = render(card)
        self.doc_id = str(card.get("norm_id") or code)
        self.doc_name = "smeta_material_cards.v1"
        self.score = float(item.get("score") or 0.0)
        self.meta = {
            **{key: str(card.get(key) or "") for key in ("norm_id", "edition", "base_type")},
            "norm_code": code,
            "measure_unit": str(card.get("measure_unit") or ""),
            "source_ref": str(card.get("source_ref") or ""),
            "smeta_required_header_chars": len(smeta_card_header(card)),
            "smeta_archive_context_end": len(smeta_card_context(card)),
            **smeta_card_delivery_metadata(card, self.content),
            "application_note": str(card.get("application_note") or ""),
            "material_candidate": True,
            "archive_provenance": card.get("archive_provenance") or {},
            "demolition": bool(item.get("demolition")),
        }


from proxy.smeta_core.row_decision import ACCOUNTED_STATUSES as _CALCULATED_ROW_STATUSES
from proxy.smeta_core.row_decision import source_resolved


def smeta_selection_funnel(
    *,
    query_hits: Sequence[tuple[str, Sequence[Any]]],
    shown_chunks: Sequence[Any],
    rows: Sequence[Mapping[str, Any]],
    rejected: Mapping[str, str] | None = None,
    bound_rows: int | None = None,
    includes_prior_rows: bool = False,
    row_statuses: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Где именно теряется норма: найдена → показана → выбрана → рассчитана.

    Одно число «решено 9 из 70» не отвечает на вопрос, что чинить. Нужная норма может
    не найтись поиском, найтись и не влезть в окно, влезть и не быть выбранной, быть
    выбранной и не пройти расчёт — это четыре разные задачи (ревью Codex 11.09).

    Строки и нормы считаются раздельно: одна норма закрывает несколько строк, и
    вычитать «отвергнуто строк» из «выбрано шифров» бессмысленно — так получалось
    `calculated=-1`. Успех берётся из фактического результата расчётчика
    (`bound_rows`), а не выводится арифметикой; без него поле остаётся пустым, потому
    что отсутствие данных — не успех (ревью Codex 11.09, второй заход).
    """
    from proxy.smeta_core.vor_rows import explicit_norm_absence

    def code_of(chunk: Any) -> str:
        return str((getattr(chunk, "meta", {}) or {}).get("norm_code") or "").strip().upper()

    found = {code_of(hit) for _query, hits in query_hits for hit in hits} - {""}
    shown = {code_of(chunk) for chunk in shown_chunks} - {""}
    practice = {
        code_of(hit)
        for _query, hits in query_hits
        for hit in hits
        if (getattr(hit, "meta", {}) or {}).get("practice_candidate")
    } - {""}

    rows_with_norm: list[str] = []
    selected_codes: set[str] = set()
    for row in rows:
        code = str(row.get("norm_code") or "").strip().upper()
        if not code or explicit_norm_absence(row.get("norm_code")):
            continue
        rows_with_norm.append(str(row.get("source_row") or ""))
        selected_codes.add(code)
    current_rows = {str(row.get("source_row") or "").strip() for row in rows}
    diagnostics = {
        str(key): reason for key, reason in (rejected or {}).items()
        if str(key) in current_rows
    }
    # A missing coefficient basis is a warning: the calculator keeps the work
    # at its unadjusted quantity. It is not a rejected binding.
    refused = {
        key: reason for key, reason in diagnostics.items()
        if reason != "coefficient_needs_basis"
    }
    calculated = None if includes_prior_rows else bound_rows
    if row_statuses is not None:
        calculated = (
            sum(row_statuses[key] in _CALCULATED_ROW_STATUSES for key in current_rows)
            if current_rows <= row_statuses.keys() else None
        )
        refused = {key: value for key, value in row_statuses.items()
                   if key in current_rows and not source_resolved(value)}
    practice_rows = [
        str(row.get("source_row") or "")
        for row in rows
        if str(row.get("norm_code") or "").strip().upper() in practice
        and not explicit_norm_absence(row.get("norm_code"))
    ]
    return {
        "schema": "les.smeta.selection-funnel.v3",
        # Строки ведомости
        "rows": len(current_rows),
        "operations": len(rows),
        "rows_with_norm": len(set(rows_with_norm)),
        "rows_without_norm": len(current_rows - set(rows_with_norm)),
        "rows_rejected_by_calc": len(refused),
        # The tool count covers the merged workbook. Without per-row calculation
        # results we cannot assign that count to the current model portion.
        "rows_calculated": calculated,
        "workbook_rows_calculated": bound_rows,
        "rows_with_calc_diagnostics": len(diagnostics),
        "rows_from_practice": len(set(practice_rows)),
        # Нормы
        "norms_found": len(found),
        "norms_shown": len(shown),
        "norms_lost_to_budget": len(found - shown),
        "norms_selected": len(selected_codes),
        "norms_selected_outside_shown": sorted(selected_codes - shown)[:10],
        "practice_offered": len(practice),
        "practice_shown": len(practice & shown),
        "practice_selected": len(practice & selected_codes),
        "reject_reasons": sorted(set(refused.values())),
    }


def smeta_practice_group(
    *,
    attachment_context: str,
    question: str,
    already_shown: Sequence[tuple[str, Sequence[Any]]],
    trace: dict[str, Any] | None = None,
) -> tuple[str, tuple[Any, ...]] | None:
    """Группа карточек из практики раздела; None, если раздел неизвестен или пуст.

    Добавление к поиску, а не замена: порядок поисковой выдачи не трогается, редкая
    норма вне архива остаётся доступной. Уже показанные шифры не дублируются.
    """
    from proxy.services.practice_candidates_service import (
        practice_candidate_cards,
        practice_query_label,
    )
    from proxy.smeta_core.collection_scope import discipline_for_text

    head = " ".join(str(attachment_context or "").split())[:2000]
    discipline = discipline_for_text(head) or discipline_for_text(str(question or ""))
    if not discipline:
        return None
    shown = {
        str(getattr(hit, "meta", {}).get("norm_code") or "").strip().upper()
        for _query, hits in already_shown
        for hit in hits
    }
    try:
        cards = practice_candidate_cards(discipline, exclude=tuple(shown))
    except Exception:  # noqa: BLE001 — подсказка не должна ронять ответ
        logging.getLogger(__name__).warning(
            "[SMETA_PRACTICE] кандидаты раздела не собраны", exc_info=True
        )
        return None
    if not cards:
        return None
    if trace is not None:
        trace["smeta_practice_candidates"] = {
            "schema": "les.smeta.practice-candidates.v1",
            "discipline": discipline,
            "offered": [str(card.get("norm_code") or "") for card in cards],
        }
    logging.getLogger(__name__).warning(
        "[SMETA_PRACTICE] раздел %s: предложено %s норм из практики",
        discipline, len(cards),
    )
    return (
        practice_query_label(discipline, len(cards)),
        tuple(_PracticeChunk(card) for card in cards),
    )


# Bounded alternatives; first candidate for every row precedes second candidates.
MATERIAL_PER_ROW = 2

# Запас кандидатов на строку сверх нужного числа: норма может быть уже показана другой
# строкой или отсутствовать в активной базе.
MATERIAL_LOOKUP_SPARE = 4


def evidence_sources_revision(*, document_price_basis=None) -> str:
    """Отпечаток источников подсказок: индекс применений и корпус раздела.

    По нему решается, дать ли исчерпавшим попытки строкам ещё один шанс. Отказ модели
    относится к тому набору свидетельств, который ей показали: пока набор тот же,
    повтор ничего не добавит, а собранный индекс или пересобранный корпус — новые
    сведения (ревью Codex 11.09, шаг 5).
    """
    from proxy.smeta_core.estimate_usage import corpus_revision
    from proxy.smeta_core.material_practice import index_revision

    parts: list[str] = []
    if document_price_basis is not None:
        from proxy.services.portion_cursor_service import document_price_basis_identity
        parts.append('price:' + hashlib.sha256(json.dumps(document_price_basis_identity(document_price_basis),
                          sort_keys=True).encode('utf-8')).hexdigest())
    for name, reader in (("index", index_revision), ("corpus", corpus_revision)):
        try:
            parts.append(f"{name}:{reader()}")
        except Exception:  # noqa: BLE001 — неопознанный источник не должен ронять проход
            parts.append(f"{name}:unknown")
    # «Не опознано» и «отсутствует» не должны выглядеть как новая ревизия: иначе строки
    # возвращались бы в оборот на каждом проходе по недоступности файла.
    if all(part.endswith(("unknown", "absent")) for part in parts):
        return ""
    return "|".join(parts)


def smeta_material_group(
    *,
    titles: Sequence[str],
    already_shown: Sequence[tuple[str, Sequence[Any]]],
    limit_per_row: int = MATERIAL_PER_ROW,
    limit_total: int | None = None,
    trace: dict[str, Any] | None = None,
) -> tuple[str, tuple[Any, ...]] | None:
    """Нормы, которыми считали такие же изделия; None, если подсказок нет.

    Отличие от группы раздела: та берёт частые нормы раздела и одинакова для всей
    ведомости, а эта отвечает на каждую строку отдельно. Для розеток список раздела
    ещё годился, для шпилек и ответвителей лотка — нет.

    По умолчанию доступны два разных примера на строку; первые кандидаты всех
    строк предшествуют вторым. Место в окне она отдаёт первой — это делает упаковщик свидетельств,
    которому она помечена как подсказка.
    """
    from proxy.services.model_research_tool_service import smeta_card_text
    from proxy.smeta_core.material_practice import similar_applications

    rows = [" ".join(str(title or "").split()) for title in titles]
    rows = [text for text in rows if text]
    per_row_limit = max(1, int(limit_per_row))
    ceiling = len(rows) * per_row_limit if limit_total is None else max(1, int(limit_total))
    shown = {str(getattr(hit, "content", "")) for _query, hits in already_shown for hit in hits}
    picked: list[dict[str, Any]] = []
    cards_built: list[Any] = []
    per_row: list[dict[str, Any]] = []
    candidates: list[list[tuple[dict[str, Any], Any]]] = []
    for text in rows:
        try:
            found = similar_applications(
                text, limit=per_row_limit + MATERIAL_LOOKUP_SPARE
            )
        except Exception:  # noqa: BLE001 — optional archive lookup
            logging.getLogger(__name__).warning(
                "[SMETA_MATERIAL] подбор по наименованию не удался", exc_info=True
            )
            return None
        row_candidates = []
        for item in found:
            if not str(item.get("norm_code") or "").strip():
                continue
            card = material_candidate_card(item)
            if card is None:
                continue
            chunk = _MaterialChunk(card, item, smeta_card_text)
            row_candidates.append(({**item, "row_title": text}, chunk))
        candidates.append(row_candidates)
        per_row.append({"row": text[:80], "found": len(found), "offered": 0})
    # Fair allocation even under an explicit smaller total ceiling. Deduplication
    # compares complete rendered archive evidence, never just canonical norm code.
    for _round in range(per_row_limit):
        for index, row_candidates in enumerate(candidates):
            while row_candidates and len(picked) < ceiling:
                item, chunk = row_candidates.pop(0)
                if chunk.content in shown:
                    continue
                shown.add(chunk.content)
                picked.append(item)
                cards_built.append(chunk)
                per_row[index]["offered"] += 1
                break
    if not picked:
        return None

    cards = tuple(cards_built)
    if trace is not None:
        trace["smeta_material_candidates"] = {
            "schema": "les.smeta.material-norm-index.v1",
            "rows": per_row,
            "offered": [item["norm_code"] for item in picked],
        }
    logging.getLogger(__name__).warning(
        "[SMETA_MATERIAL] по %s строкам предложено %s норм из применений",
        len(per_row), len(picked),
    )
    return (
        f"нормы, которыми считали такие же изделия ({len(picked)})",
        cards,
    )


def evidence_snapshot(
    rows: Sequence[Mapping[str, Any]], chunks: Sequence[Any], *,
    delivered_cards: Mapping[str, str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Чем подкреплено каждое решение — в виде, переживающем проход.

    Ссылка `Q1.H1` локальна: на следующем проходе тот же номер указывает на другую
    карточку, и по сохранённому решению нельзя проверить, на что модель опиралась.
    Поэтому рядом с решением остаётся разрешённая ссылка: запрос, шифр карточки,
    её источник и отпечаток ровно того текста, который ушёл модели (ревью Codex 11.09).

    Текст и provenance сохраняются вместе с отпечатком. Alias разрешён до снимка:
    одной ссылки на другую группу недостаточно для проверки после завершения чата.
    """
    by_ref: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        meta = dict(getattr(chunk, "meta", {}) or {})
        ref = str(meta.get("model_evidence_ref") or "").strip().upper()
        if not ref:
            continue
        body = str(getattr(chunk, "content", "") or "")
        by_ref[ref] = {
            "ref": ref,
            "query": str(meta.get("model_query") or ""),
            "norm_code": str(meta.get("norm_code") or ""),
            "doc_name": str(getattr(chunk, "doc_name", "") or ""),
            "doc_id": str(getattr(chunk, "doc_id", "") or ""),
            "score": round(float(getattr(chunk, "score", 0.0) or 0.0), 4),
            "sent_chars": len(body),
            "sent_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest()[:16],
            "sent_text": body,
            "source_meta": dict(meta),
        }
        if delivered_cards is not None:
            by_ref[ref]['delivered'] = ref in delivered_cards
    snapshot: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        source_row = str(row.get("source_row") or "").strip()
        if not source_row:
            continue
        # Reused proof retains its original query/ref/source, even when current Q IDs changed.
        reused = [dict(card) for card in row.get('evidence_snapshot') or [] if card.get('delivered') is True]
        seen = reused or [
            by_ref[str(ref or "").strip().upper()]
            for ref in (row.get("evidence_refs") or [])
            if str(ref or "").strip().upper() in by_ref
        ]
        if seen:
            snapshot[source_row] = list({item['ref']: item for item in [*snapshot.get(source_row, []), *seen]}.values())
    return snapshot


# Отметки упаковщика, которые означают отсутствие выбора, а не его отклонение.
NOT_A_REJECTED_CHOICE = frozenset({"norm_selection_required"})


def workbook_bound_rows(workbook_meta: Any) -> int | None:
    """Сколько строк расчётчик действительно связал; None — если он не отчитался.

    Считать успехом всё, что не помечено отказом, нельзя: книга могла не собраться
    вовсе (ревью Codex 11.09).
    """
    meta = workbook_meta if isinstance(workbook_meta, Mapping) else {}
    diagnostics = meta.get("workbook_diagnostics")
    rows = (diagnostics or {}).get("bound_rows") if isinstance(diagnostics, Mapping) else None
    if rows is None:
        artifact = meta.get("artifact") if isinstance(meta.get("artifact"), Mapping) else {}
        rows = artifact.get("bound_rows")
    try:
        return int(rows) if rows is not None else None
    except (TypeError, ValueError):
        return None


def workbook_row_statuses(workbook_meta: Any) -> dict[str, str] | None:
    diagnostics = (workbook_meta or {}).get("workbook_diagnostics") if isinstance(workbook_meta, Mapping) else None
    items = diagnostics.get("row_calculation") if isinstance(diagnostics, Mapping) else None
    if not isinstance(items, list):
        return None
    from proxy.smeta_core.row_decision import aggregate_operation_statuses
    return aggregate_operation_statuses(items)


def rejected_row_reasons(workbook_meta: Any) -> dict[str, str]:
    """Строки, чью привязку упаковщик отверг, и причина по каждой.

    Формат упаковщика — «row:987:unit_conflict». Такая строка в расчёт не попала, и
    считать её решённой нельзя: в живом прогоне 11.09 так «решёнными» числились 18
    позиций из 48, которых в книге нет вовсе. Причина возвращается модели, чтобы она
    пересмотрела выбор, а не гадала (ревью Codex 11.09).
    """
    meta = workbook_meta if isinstance(workbook_meta, Mapping) else {}
    diagnostics = meta.get("workbook_diagnostics")
    rows = (diagnostics or {}).get("unbound_rows") if isinstance(diagnostics, Mapping) else None
    reasons: dict[str, str] = {}
    for item in rows or ():
        parts = str(item).split(":")
        if len(parts) < 3 or parts[0] != "row":
            continue
        reason = ":".join(parts[2:]).strip()
        if reason in NOT_A_REJECTED_CHOICE:
            # «Норма не выбрана» — не отвергнутый выбор, а его отсутствие. Такая строка
            # и так возвращается как незакрытая; называть это отказом расчёта значит
            # сказать модели «твой выбор отклонён» там, где она ничего не выбирала
            # (живой прогон 11.09, 08:06 — 21 строка из 25).
            continue
        reasons[parts[1].strip()] = reason
    return reasons


def portion_result_digest(
    portion_state: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]
) -> str:
    """Полный отпечаток результата прохода: что показали и что модель ответила.

    Служит не ключом идемпотентности, а проверкой: если тот же ключ хода приносит
    другой результат, это противоречие, а не повтор доставки. Раньше отпечаток брал
    лишь номер строки, шифр и ссылку — смена количества проходила незамеченной
    (ревью Codex 11.09).
    """
    from proxy.services.portion_cursor_service import canonical_decision

    digest = hashlib.sha256()
    digest.update(str(portion_state.get("source_revision") or "").encode("utf-8"))
    for anchor in portion_state.get("shown") or ():
        digest.update(b"|")
        digest.update(str(anchor).encode("utf-8"))
    for row in rows:
        digest.update(b"~")
        digest.update(
            json.dumps(
                {**canonical_decision(row), "evidence_refs": row.get("evidence_refs")},
                ensure_ascii=False, sort_keys=True, default=str,
            ).encode("utf-8")
        )
    return digest.hexdigest()[:32]


def record_portion_pass(
    cursors: Any,
    *,
    session_id: str,
    portion_state: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    closed: Sequence[str],
    artifact_revision_id: str | None,
    artifact_decisions_revision: str | None = None,
    rejected: Mapping[str, str] | None = None,
    row_statuses: Mapping[str, str] | None = None,
    evidence: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    calculation_receipts: Sequence[Mapping[str, Any]] = (),
    pass_id: str = "",
    trace: dict[str, Any] | None = None,
) -> int:
    """Записать проход: закрытые строки с их решениями и ревизию книги.

    Возвращает число закрытых строк. Сбой хранилища не должен ронять уже готовый
    ответ — следующий проход просто начнётся заново, что хуже продолжения, но лучше
    потерянного ответа.

    `pass_id` приходит от клиента вместе с ходом. Без него запись идёт всегда: два
    «Продолжай» подряд текстуально неотличимы, и вывести идентичность из содержимого
    нельзя — одинаковый пустой ответ трёх настоящих проходов засчитался бы за один
    (ревью Codex 11.09). Полный отпечаток результата идёт рядом и ловит противоречие:
    тот же ключ с другим ответом — не повтор.
    """
    from proxy.smeta_core.vor_rows import decision_anchor

    shown = portion_state.get("shown") or list(closed)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        anchor = decision_anchor(row, shown)
        if anchor:
            grouped.setdefault(anchor, []).append(dict(row))
    decisions = {anchor: values[0] if len(values) == 1 else {
        "source_row": values[0].get("source_row"), "operations": values,
    } for anchor, values in grouped.items()}
    # Привязку, отвергнутую упаковщиком, решением считать нельзя: этой строки в книге
    # нет. Она возвращается модели вместе с причиной, а попытка засчитывается.
    refused = dict(rejected or {})
    seen_evidence = dict(evidence or {})
    turned_down: list[str] = []
    for anchor, decision in decisions.items():
        source_row = str(decision.get("source_row") or "").strip()
        receipts = [dict(item) for item in calculation_receipts if item.get('source_row') == source_row]
        if receipts:
            decision['calculation_receipts'] = receipts
        if source_row in seen_evidence:
            # Снимок ложится в само решение: проход сменится, номера ссылок поедут,
            # а проверить, на что опирался выбор, будет по чему.
            decision["evidence_snapshot"] = [dict(item) for item in seen_evidence[source_row]]
            for op in decision.get("operations") or []:
                if op.get('evidence_snapshot'):
                    continue
                refs = {str(ref).upper() for ref in op.get("evidence_refs") or []}
                op["evidence_snapshot"] = [dict(item) for item in seen_evidence[source_row] if item.get("ref") in refs]
        reason = refused.get(source_row)
        if row_statuses is not None and source_row in row_statuses:
            status = row_statuses[source_row]
            reason = None if source_resolved(status) else status
        if reason:
            decision["rejected_reason"] = reason
            turned_down.append(anchor)
    kept = [anchor for anchor in closed if anchor not in turned_down]
    if row_statuses is not None:
        kept = [anchor for anchor, decision in decisions.items()
                if source_resolved(row_statuses.get(str(decision.get("source_row") or "").strip()))]
    completed = {anchor: decisions[anchor] for anchor in kept if anchor in decisions}
    try:
        progress = cursors.record_pass(
            session_id=str(session_id or ""),
            source_revision=str(portion_state.get("source_revision") or ""),
            completed=completed,
            decisions=decisions,
            declined=declined_row_anchors(rows, shown),
            rejected={
                anchor: str(decisions[anchor].get("rejected_reason") or "")
                for anchor in turned_down
            },
            artifact_revision_id=artifact_revision_id,
            artifact_decisions_revision=artifact_decisions_revision,
            pass_id=str(pass_id or ""),
            result_digest=portion_result_digest(portion_state, rows),
        )
        # A workbook contains all accumulated operations. Recalculation can invalidate
        # an old receipt even when that row was not part of this model turn.
        if artifact_revision_id and row_statuses is not None and callable(getattr(cursors, 'record_calculation', None)):
            all_decisions = {**(portion_state.get('prior_decisions') or {}), **decisions}
            cursors.record_calculation(
                session_id=str(session_id or ''), source_revision=str(portion_state.get('source_revision') or ''),
                statuses={anchor: row_statuses[str(decision.get('source_row') or '')]
                          for anchor, decision in all_decisions.items()
                          if str(decision.get('source_row') or '') in row_statuses},
                receipts=calculation_receipts,
            )
            progress = cursors.progress(session_id=str(session_id or ''),
                                        source_revision=str(portion_state.get('source_revision') or ''))
    except Exception:  # noqa: BLE001 — ответ уже готов, терять его из-за записи нельзя
        logging.getLogger(__name__).warning(
            "[SMETA_PORTION] прогресс не записан, следующий проход начнётся сначала",
            exc_info=True,
        )
        if trace is not None:
            trace["smeta_portion_recorded"] = False
        return 0
    if trace is not None:
        trace["smeta_portion_recorded"] = True
        trace["smeta_portion_rejected"] = len(turned_down)
        trace["smeta_portion_closed"] = len(completed)
        trace["smeta_portion_total_closed"] = len(progress.completed)
        # Счётчики после записи, а не до: ход, исчерпавший последнюю попытку, обязан
        # отчитаться о ней в своём же ответе (ревью Codex 11.09).
        trace["smeta_portion_decided"] = len(progress.completed)
        trace["smeta_portion_unresolved"] = len(progress.exhausted)
    return len(completed)


# Потолок на пересборку книги. Она — удобство: экономит модели проход по уже
# разобранным строкам. Держать ради неё ответ нельзя ни по какой причине — ни из-за
# холодного кеша книги цен, ни из-за уснувшей машины.
REBUILD_TIMEOUT_SECONDS = 90.0


async def rebuild_workbook_from_stored_decisions(
    *,
    executor: Any,
    portion_state: Mapping[str, Any],
    attachment_id: str,
    question: str,
    context: Mapping[str, Any],
    progress: Any,
    trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Пересобрать книгу из уже сохранённых решений, не обращаясь к модели.

    Решения приняты, записаны и неизменны — значит книгу можно построить заново
    детерминированно. Просить модель пройти те же строки второй раз и дорого, и
    неверно: её ответ мог бы отличаться, и книга перестала бы соответствовать
    записанному решению (ревью Codex 11.09).

    Возвращает результат упаковки или пустой словарь, если пересобирать нечего или
    не получилось. Исключение сюда не выходит: без книги ответ хуже, но он есть.
    """
    stored = portion_state.get("prior_decisions")
    if not isinstance(stored, Mapping) or not stored or not str(attachment_id or "").strip():
        return {}
    order = {anchor: index for index, anchor in enumerate(portion_state.get("source_anchors") or ())}
    decisions = [
        dict(stored[anchor])
        for anchor in sorted(stored, key=lambda item: order.get(item, len(order)))
        if isinstance(stored.get(anchor), Mapping) and stored[anchor]
    ]
    if not decisions:
        return {}
    from proxy.smeta_core.row_decision import operation_rows
    decisions = [op for row in decisions for op in operation_rows(row)]
    decisions = bind_normative_identity(decisions, prior_evidence=saved_norm_evidence(stored))
    try:
        payload = await asyncio.wait_for(_run_rebuild(executor, attachment_id, question, decisions, portion_state, context, progress), timeout=REBUILD_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        logging.getLogger(__name__).warning(
            "[SMETA_PORTION] пересборка книги не уложилась в %s с — идём обычным путём",
            REBUILD_TIMEOUT_SECONDS,
        )
        if trace is not None:
            trace["smeta_portion_rebuild"] = "timeout"
        return {}
    except Exception:  # noqa: BLE001 — без книги ответ хуже, но он есть
        logging.getLogger(__name__).warning(
            "[SMETA_PORTION] пересборка книги из сохранённых решений не удалась",
            exc_info=True,
        )
        if trace is not None:
            trace["smeta_portion_rebuild"] = "failed"
        return {}
    harvested = harvest_workbook_tool_result(safe_workbook_history_projection(payload))
    logging.getLogger(__name__).warning(
        "[SMETA_PORTION] пересборка завершена: %s",
        "книга собрана" if harvested else "книги нет",
    )
    if trace is not None:
        trace["smeta_portion_rebuild"] = "rebuilt" if harvested else "empty"
        trace["smeta_portion_rebuild_rows"] = len(decisions)
    return harvested


async def _run_rebuild(executor, attachment_id, question, decisions, portion_state, context, progress):
    """Один вызов упаковщика по сохранённым решениям."""
    return await executor(
            {
                "tool": "build_lsr_workbook",
                "args": {
                    "attachment_id": str(attachment_id),
                    "question": str(question or ""),
                    "decisions": decisions,
                    "review_calculation": True,
                    "parent_revision_id": (
                        str(portion_state.get("artifact_revision_id") or "") or None
                    ),
                },
            },
            dict(context),
            progress,
        )


def stored_decisions_need_a_workbook(portion_state: Mapping[str, Any], *, artifact_available=None) -> bool:
    """Устарела ли книга относительно сохранённых решений.

    Раньше здесь проверялось «книги нет вовсе», и это покрывало не тот случай. Штатный
    отказ упаковщика выглядит иначе: решения записаны, книга прошлой порции существует,
    а текущим решениям она уже не соответствует. Проверка «любая ревизия есть» принимала
    старую книгу за актуальную (ревью Codex 11.09).

    Сравниваются отпечатки: из чего книга собрана и что лежит в решениях сейчас.
    """
    from proxy.services.portion_cursor_service import decisions_revision

    stored = portion_state.get("prior_decisions")
    if not isinstance(stored, Mapping) or not stored:
        return False
    built_from = str(portion_state.get("artifact_decisions_revision") or "").strip()
    if built_from != decisions_revision(stored, document_price_basis=portion_state.get('document_price_basis')):
        return True
    revision_id = str(portion_state.get('artifact_revision_id') or '')
    return bool(artifact_available is not None and (not revision_id or not artifact_available(revision_id)))


def merged_pass_decisions(
    rows: Sequence[Mapping[str, Any]],
    *,
    closed: Sequence[str],
    portion_state: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Решения для книги: прошлые проходы плюс текущий, в порядке ведомости.

    Книга собирается из решений, а не из файла, поэтому последний проход, отдав только
    свои двадцать строк, потерял бы пятьдесят прежних. Решения накапливаются в
    хранилище прогресса и подмешиваются сюда (ревью Codex 10.09).

    Порядок сохраняется естественный: проходы идут вперёд по ведомости, значит прежние
    строки стоят выше текущих. Строка, решённая заново, вытесняет прежнее решение —
    свежее ближе к правде.
    """
    current = [dict(row) for row in rows]
    prior = portion_state.get("prior_decisions")
    if not isinstance(prior, Mapping) or not prior:
        return current
    from proxy.smeta_core.vor_rows import decision_anchor

    anchors = portion_state.get("source_anchors") or list(dict.fromkeys([
        *prior, *(portion_state.get("shown") or []), *closed,
    ]))
    shown = portion_state.get("shown") or anchors
    keyed_current = [(decision_anchor(row, shown), row) for row in current]
    replaced = {anchor for anchor, _ in keyed_current if anchor}
    entries = [(anchor, bind_normative_identity([row], prior_evidence=saved_norm_evidence(prior))[0]) for anchor, row in prior.items()
               if anchor not in replaced and isinstance(row, Mapping) and row]
    entries.extend(keyed_current)
    order = {anchor: index for index, anchor in enumerate(anchors)}
    # Keep unresolvable model rows visible; never guess their sheet or discard them.
    entries.sort(key=lambda entry: order.get(entry[0], len(order)))
    from proxy.smeta_core.row_decision import operation_rows
    return [op for _, row in entries for op in operation_rows(row)]


def _previous_rejections(decisions: Mapping[str, Any] | None) -> dict[str, str]:
    """Причины, по которым прошлый выбор модели не прошёл расчёт, — по якорям строк."""
    notes: dict[str, str] = {}
    for anchor, decision in (decisions or {}).items():
        if not isinstance(decision, Mapping):
            continue
        reason = str(decision.get("rejected_reason") or "").strip()
        # Отметку об отсутствии выбора отсеиваем и здесь: она могла попасть в базу
        # прежней версией, а показывать «твой выбор отклонён» там, где выбора не было,
        # нельзя (живой прогон 11.09, 08:06).
        if not reason or reason in NOT_A_REJECTED_CHOICE:
            continue
        code = str(decision.get("norm_code") or "").strip()
        notes[str(anchor)] = (
            f"{code}: {_rejection_wording(reason)}" if code else _rejection_wording(reason)
        )
        diagnostic = decision.get('row_format_diagnostic')
        if isinstance(diagnostic, Mapping) and diagnostic.get('reason') == 'invalid_decision_field':
            notes[str(anchor)] = (
                'Недопустимое значение управляющего поля: '
                + '; '.join(f'{name}={value}' for name, value in (diagnostic.get('invalid_values') or {}).items())
                + '. Поля не были угаданы или переставлены; верни исправленную исходную строку.'
            )
        if decision.get("parse_error") and isinstance(decision.get("raw_cells"), list):
            notes[str(anchor)] += (
                "\nИсходная разметка твоего ответа (данные для исправления, не источник норм):"
                "\nЗаголовок: " + json.dumps(decision.get("raw_header") or [], ensure_ascii=False)
                + "\nЯчейки: " + json.dumps(decision["raw_cells"], ensure_ascii=False)
            )
    return notes


def _rejection_wording(reason: str) -> str:
    """Причина отказа человеческими словами; незнакомый код — как есть."""
    return {
        "unit_conflict": (
            "измеритель нормы не сходится с единицей строки. Нужен подтверждённый "
            "пересчёт (фасовка, масса или другая характеристика). Не придумывай множитель "
            "и не меняй подходящую технологию только ради единицы; назови недостающие данные"
        ),
        "norm_not_found": "такого шифра нет в базе",
        "model_row_format_error": (
            "число ячеек твоей строки не совпало с заголовком таблицы; поля не были "
            "угаданы и строка не рассчитана. Верни строку с теми же колонками, что в "
            "заголовке; параметры conversion_* укажи в отдельных подписанных полях"
        ),
        "resource_quantity_mismatch": "связанное количество ресурса не равно исходной потребности строки",
        "norm_code_ambiguous": (
            "в norm_code несколько шифров, строка не рассчитана: подтверждается один шифр, а "
            "считается другой. Оставь в norm_code ровно один выбранный шифр, а сравнение с другой "
            "нормой напиши в analogue"
        ),
        "evidence_card_mismatch": (
            "показанная карточка относится к другой норме, строка не рассчитана. Сверь шифр с "
            "карточкой, на которую ссылаешься: выбор подтверждает совпадение шифра, а не наличие "
            "ссылки; если подходящей карточки нет, оставь norm_code пустым"
        ),
        "evidence_ref_unknown": (
            "ссылка строки не указывает ни на одну карточку этого прохода, строка не рассчитана. "
            "Ссылка пишется как Qx.Hy — номер поискового запроса и номер карточки в его выдаче, "
            "а не номер строки ведомости; укажи карточку, из которой взят шифр"
        ),
        "evidence_ref_required": (
            "норма выбрана без ссылки на карточку этого прохода, строка не рассчитана. Укажи в "
            "evidence_refs карточку, из которой взят шифр, и проверь шифр по ней; если подходящей "
            "карточки нет, оставь norm_code пустым"
        ),
        "coefficient_basis_required": "коэффициент не применён: нужны точный нормативный источник, пункт и область действия labor/machines/materials; исходный выбор сохранён",
    }.get(reason, reason)


def _portion_feedback_store(cursors: Any) -> Any:
    """Feedback uses separate tables, never the packagable decisions projection."""
    import sqlite3
    from proxy.services.portion_feedback_service import PortionFeedbackService

    path = getattr(cursors, "db_path", None)
    if path is None:
        return None
    try:
        return PortionFeedbackService(path)
    except (OSError, sqlite3.Error, TypeError, ValueError):
        logger.warning("[SMETA_FEEDBACK] хранилище недоступно", exc_info=True)
        return None


def _structural_feedback_text(feedback: Mapping[str, Any] | None) -> str:
    if not feedback or not feedback.get("errors"):
        return ""
    lines = [
        "Диагностика предыдущего ответа (не источник норм): книга не была собрана.",
        "Ошибки проверки: " + "; ".join(str(error) for error in feedback["errors"]),
    ]
    for row in feedback.get("rows") or []:
        lines.append(
            f"Предыдущая строка {row.get('source_row')}: norm_code={row.get('norm_code') or ''}; "
            f"evidence_refs={row.get('evidence_refs') or []}."
        )
    lines.append(
        "Подтверди или измени своё решение по карточкам текущего прохода. Для выбранной нормы "
        "укажи её актуальную ссылку Qx.Hy; старые номера ссылок не являются источниками. "
        "Отклонённый тобой вариант опиши в analogue, не записывай его как выбранный norm_code. "
        "Соблюдай одинаковые колонки заголовка и строк."
    )
    return "\n".join(lines)


def _record_structural_feedback(
    cursors: Any, *, session_id: str, revision: str, turn_id: str,
    answer: str, rows: list[dict[str, Any]], errors: list[str],
    evidence: Mapping[str, Any],
) -> bool:
    import sqlite3

    store = _portion_feedback_store(cursors)
    if store is None or not turn_id:
        return False
    try:
        inserted = store.record(
            session_id=session_id, source_revision=revision, turn_id=turn_id,
            raw_answer=answer, rows=rows, errors=errors, evidence=evidence,
        )
        latest = store.last(session_id=session_id, source_revision=revision)
        return bool(inserted or (latest and latest["turn_id"] == turn_id
                                and latest["raw_answer"] == answer and latest["errors"] == errors))
    except (OSError, sqlite3.Error, TypeError, ValueError):
        logger.warning("[SMETA_FEEDBACK] отказ не записан", exc_info=True)
        return False


def _model_result_notice(errors: Sequence[str], *, saved: bool) -> dict[str, Any]:
    labels = {
        "missing_evidence_ref": "нет ссылки на карточку выбранной нормы",
        "unknown_evidence_ref": "ссылка отсутствует в карточках этого прохода",
        "invalid_source_row": "не указан однозначный номер исходной позиции",
        "duplicate_source_row": "номер исходной позиции повторён",
        "duplicate_work_id": "идентификатор операции повторён",
        "invalid_portion_source_row": "строка не соответствует текущей порции",
        "inconsistent_portion_source_label": "операции одной позиции должны повторять одинаковый source_row",
        "source_row_count_mismatch": "число строк не соответствует ведомости",
        "unstructured_model_result": "ответ не удалось прочитать как таблицу",
    }
    reasons = []
    for error in errors:
        kind, _, detail = str(error).partition(":")
        reasons.append((f"{detail}: " if detail else "") + labels.get(kind, "нарушена структура ответа"))
    return {
        "status": "unstructured" if "unstructured_model_result" in errors else "structural_error",
        "message": "Книга не собрана. " + "; ".join(reasons) + ". "
        + ("Исходный ответ сохранён для исправления в следующем проходе." if saved else
           "Нужен исправленный ответ со ссылками на полученные карточки."),
        "errors": list(errors), "saved": saved,
    }


# Работ прошлых проходов в контексте: столько, сколько нужно материалу текущей порции
# сослаться на свою работу. Весь список ведомости сюда не помещается и не должен:
# живой прогон 14.09 — 91 работа, 14 602 символа, 7 301 токен, и порция схлопнулась
# с 7 строк до 2 при неизменном лимите, потому что бюджет источника съедал этот блок.
# Предел считан по замеру прохода 39: бюджет источника 8 663 токена, чек одной
# проверяемой строки — 3 242, и место обязано остаться самой порции. Одна работа
# стоит около 105 токенов, поэтому список ссылок держим примерно в 1 200.
MAX_PRIOR_WORKS = 12


def prior_works_context(
    decisions: Mapping[str, Any] | None, *, portion: Sequence[Mapping[str, Any]],
) -> str:
    """Работы прошлых проходов, на которые может сослаться материал текущей порции.

    Отбираются работы листов текущей порции: `included_in` адресует работу той же
    дисциплины, а чужой лист только занимает окно. Из них остаются ближайшие —
    материал следует за своей работой рядом, а не через всю ведомость.
    """
    from proxy.smeta_core.row_decision import WORK, decision_kind, operation_rows
    from proxy.smeta_core.vor_rows import row_anchor

    sheets = {row_anchor(row).split("!")[0] for row in portion or ()}
    sheets.discard("")
    lines: list[str] = []
    for anchor, stored in (decisions or {}).items():
        # Лист берём из якоря: work_id пишет модель, и он бывает голым номером позиции.
        # Неопределённый лист не повод выбрасывать работу — ссылка нужнее экономии окна.
        sheet = str(anchor or "").split("!")[0] if "!" in str(anchor or "") else ""
        if sheets and sheet and sheet not in sheets:
            continue
        for decision in operation_rows(stored):
            if decision_kind(decision) != WORK or not decision.get("norm_code"):
                continue
            work_id = decision.get("work_id") or decision.get("source_row")
            lines.append(
                f"included_in={work_id}: {decision.get('norm_code')}; "
                f"{decision.get('title')}; {decision.get('quantity')} {decision.get('unit')}"
            )
    return "\n".join(lines[-MAX_PRIOR_WORKS:])


def smeta_portion_context(
    attachment_context: str,
    *,
    session_id: str,
    limit: int,
    cursors: Any = None,
) -> tuple[str, dict[str, Any]]:
    """Контекст одного прохода по ведомости и описание того, что в него вошло.

    Ведомость целиком вытесняет из окна карточки норм: замер 10.09 — вместе с профилем
    она занимает 8 444 токена из 22 528, и на свидетельства остаётся 14 031. Поэтому
    модель видит порцию строк, а не весь файл.

    Не всякое вложение — ведомость: письмо или договор возвращаются как есть, с пустым
    планом. Разбор идёт из текста скрепки, потому что именно текст сюда и приходит.

    Три состояния различаются явно, и смешивать их нельзя (ревью Codex, R5):
    ведомость не распознана — отдаём текст как есть; есть строки для прохода — отдаём
    порцию; всё закрыто — отдаём короткое сообщение о завершении, а не ведомость
    заново.
    """
    from proxy.smeta_core.vor_rows import (
        row_anchor,
        rows_from_attachment_text,
        source_revision,
    )
    from proxy.services.portion_plan_service import portion_plan

    text = str(attachment_context or "")
    rows = rows_from_attachment_text(text)
    if not rows:
        return text, {
            "state": "not-a-vor", "total": 0, "rows_in_pass": 0, "remaining": 0,
            "pass_no": 1, "complete": False, "last_row": "", "after": "",
            "source_revision": "",
        }

    revision = source_revision(rows)
    plan = portion_plan(
        rows=rows,
        limit=limit,
        session_id=str(session_id or ""),
        source_revision=revision,
        cursors=cursors,
    )
    portion = plan["rows"]
    name = _attachment_name(text)
    described = {
        "total": plan["total"],
        "rows_in_pass": len(portion),
        # Строки с единицей или количеством: только им отводится бюджет запросов.
        "query_rows_in_pass": sum(
            1 for row in portion
            if str(row.get("unit") or "").strip() or str(row.get("quantity_text") or "").strip()
        ),
        "remaining": plan["remaining"],
        "completed": plan["completed"],
        "pending": max(0, plan["total"] - plan["completed"]),
        # Решения прошлых проходов: книга собирается из них вместе с новыми.
        "prior_decisions": plan["decisions"],
        "source_anchors": [row_anchor(row) for row in rows],
        "pass_no": plan["pass_no"],
        "complete": plan["complete"],
        "final_portion": plan["final_portion"],
        "after": plan["after"],
        # Якоря показанных строк. Закрытыми они становятся не здесь, а после решений
        # модели: показать — не значит закрыть.
        "shown": [row_anchor(row) for row in portion],
        # Наименования показанных строк: по ним подбираются нормы, которыми считали
        # такое же изделие. Якоря для этого не годятся — в них нет наименования.
        "shown_titles": [str(row.get("title") or "") for row in portion],
        "last_row": (row_anchor(portion[-1]) if portion else plan["after"]),
        "source_revision": revision,
        "artifact_revision_id": plan["artifact_revision_id"],
        "artifact_decisions_revision": plan["artifact_decisions_revision"],
        "exhausted": plan["exhausted"],
        "unresolved": plan["unresolved"],
    }
    if not portion:
        described["state"] = "complete"
        unresolved = int(plan["exhausted"] or 0)
        tail = (
            f" По {unresolved} позициям норма так и не найдена — они остались нерешёнными."
            if unresolved else ""
        )
        return (
            f"Ведомость «{name}»: решение принято по {plan['completed']} позициям из "
            f"{plan['total']}.{tail} Новых строк для разбора нет.",
            described,
        )
    described["state"] = "portion"
    portion_text = attachment_portion_text(
        rows, limit=limit, name=name, after=plan["after"], completed=plan["completed_anchors"],
        rejected=_previous_rejections(plan["decisions"]),
        selected=portion,
    )
    prior_works = prior_works_context(plan.get('decisions'), portion=portion)
    if prior_works:
        portion_text += ('\nРаботы из сохранённых решений предыдущих проходов '
                         '(для ссылки на конкретную работу, не повторяй их как новые строки):\n'
                         + prior_works)
    from proxy.smeta_core.calculation_receipt import receipt_context
    shown_sources = {value for row in portion for value in (str(row.get('source_row')), row_anchor(row))}
    receipts = [receipt for stored in (plan.get('decisions') or {}).values()
                if str(stored.get('source_row')) in shown_sources
                for receipt in stored.get('calculation_receipts') or []]
    if receipts:
        portion_text += '\n' + receipt_context(receipts)
    # Номер карточки живёт один проход; повтор использует сохранённую доставку
    # карточки той же операции, а не наличие расчётного чека.
    described['prior_evidence'] = saved_norm_evidence(plan.get('decisions'))
    feedback_store = _portion_feedback_store(cursors)
    if feedback_store is not None:
        import sqlite3

        try:
            feedback_text = _structural_feedback_text(feedback_store.for_anchors(
                session_id=str(session_id or ""), source_revision=revision,
                anchors=described['shown'],source_anchors=described['source_anchors'],
            ))
        except (OSError, sqlite3.Error):
            logger.warning("[SMETA_FEEDBACK] отказ не прочитан", exc_info=True)
            feedback_text = ""
        if feedback_text:
            portion_text = feedback_text + "\n\n" + portion_text
    return portion_text, described


def query_attachment_context(source: str, portion_state: Mapping[str, Any]) -> str:
    """Give query generation the selected source rows, before answer-format enrichment."""
    if portion_state.get('state') == 'complete':
        return 'Текущая порция ведомости пуста.'
    if portion_state.get('state') != 'portion':
        return source
    from proxy.smeta_core.vor_rows import row_anchor, rows_from_attachment_text

    shown = list(portion_state.get('shown') or [])
    by_anchor = {row_anchor(row): row for row in rows_from_attachment_text(source)}
    if not shown or any(anchor not in by_anchor for anchor in shown):
        raise ValueError('QUERY_PORTION_SOURCE_MISMATCH')
    rows = [by_anchor[anchor] for anchor in shown]
    lines = ['Текущая порция ведомости: ' + ', '.join(shown)]
    headers = set()
    for row in rows:
        header = tuple(row.get('header') or [])
        if header and header not in headers:
            lines.append('Колонки исходника: ' + ' | '.join(header))
            headers.add(header)
        lines.append(f"{row_anchor(row)}; раздел: {row.get('section') or ''}\n{row['raw']}")
    rejected = _previous_rejections({anchor: value for anchor, value in
        (portion_state.get('prior_decisions') or {}).items() if anchor in shown})
    if rejected:
        lines.append('Предыдущие результаты модели для этих строк: ' + json.dumps(rejected, ensure_ascii=False))
    return '\n'.join(lines)


def model_answer_prefix(normal: str, *, instruction: str, output_directive: str | None, target_doc_filter: Any) -> str:
    sys_msg = normal + (f" {instruction}" if instruction else "")
    # Формат/стиль из GUI (глубина/язык) — ТОЛЬКО в системный промпт генерации,
    # чтобы роутинг/авто-заметки/ретрив видели чистый вопрос (не мусор-директиву).
    if output_directive and output_directive.strip():
        sys_msg += " " + output_directive.strip()
    if target_doc_filter:
        sys_msg += (
            " Оператор явно выбрал документы. Отвечай только по их содержимому, "
            "явно называй использованные файлы и не расширяй область на остальной датасет."
        )
    return sys_msg


def model_answer_request(question: str, *, model_driven: bool,
                         active_estimator_answer: bool = False, native_tools_enabled: bool = True) -> str:
    source_refs = 'идентификаторы Qn.Hm показанных карточек' if active_estimator_answer else 'номера [Источник N]'
    question_tail = (
        f"Вопрос: {question}\n\n"
        "/no_think\n"
        "Дай итоговый инженерный ответ. Не выдумывай факты и используй только существующие "
        f"{source_refs}. Если материалов недостаточно, отдели это от подтверждённых выводов."
    )
    if model_driven:
        question_tail += (
            "\nТребования к Markdown, первой строке и запрет вывода JSON относятся только "
            "к итоговому пользовательскому ответу. "
            + ("До него при необходимости можешь использовать native search_sources, если этот инструмент доступен; "
               "решение о дополнительном чтении принимаешь ты."
               if not active_estimator_answer or native_tools_enabled else
               "В этом вызове native-инструменты не предоставлены; явно назови недостающие данные.")
            # Формат назван буквально, вместе с шапкой. «Обычным текстом» и
            # перечислением полей его не задать: живой прогон 21:24 вернул
            # строки в разметке порции — «984 | … | Q10.H2», без ведущей
            # черты и без шапки, — и разбор законно счёл ответ
            # неструктурированным. Модель повторяет тот вид, что видит.
            + "\nДай итоговый ответ таблицами в разметке Markdown по всем "
            "строкам исходного ВОР. Первой строкой — базовая шапка:\n"
            # work_id входит в базовую шапку: модель копирует шапку, и без этой колонки две
            # операции одной строки отвергались целиком (живая проверка 17.09).
            # Проход 19: на широкой шапке модель промахивается по ячейкам, а пустых колонок
            # в строке тем больше, чем шире шапка. Обязательных колонок семь; остальные —
            # по необходимости строки (18.09).
            "| source_row | work_id | title | unit | quantity | norm_code | evidence_refs |\n"
            "второй строкой — разделитель |---|---|---|---|---|---|---|, "
            "Для каждой операции добавь work_id и operation; у нескольких операций одной позиции "
            "source_row одинаковый, work_id разные и уникальны во всей смете. В каждой новой ревизии "
            "позиции верни полный набор её операций. Для каждой строки прими явное решение по самому "
            "изделию: если работа по норме его не содержит (монтажные нормы оборудования и кабеля "
            "обычно не содержат), поставь изделие отдельной операцией как самостоятельный материал "
            "в дополнение к работе по монтажу, а не вместо неё, "
            "с количеством и resource_code из показанной карточки цены ФССЦ, если она описывает "
            "это изделие; чужой товар ради цены не подставляй — без подходящей карточки оставь "
            "resource_code пустым, цена останется неизвестной; если изделие уже есть в составе нормы — укажи included_in и "
            "resource_action=included; если вместо изделия в составе нормы другой материал — сними "
            "его отдельной операцией (resource_action=excluded, target_resource_code, replaced_by=work_id "
            "поставки изделия); если изделие не требуется, например при демонтаже, объясни "
            "это в coverage и не добавляй изделие. Сначала сравни вид операции и условия, затем "
            "состав работ/ресурсов и физическое количество. coverage — что учтено; not_covered — "
            "что не учтено или неизвестно; analogue — краткое основание выбора. Архивный пример "
            "обосновывает кандидата, но не подтверждает учёт строки. included_in адресует work_id "
            "конкретной работы. evidence_refs — только идентификаторы показанных карточек вида Qn.Hm "
            "(номер поискового запроса и номер карточки в его выдаче, например Q3.H1); номер строки "
            "ведомости ссылкой не является. К базовой шапке добавь отдельные колонки для используемых дополнительных "
            # Частые колонки первыми, редкие — в конце: пустые ячейки уходят в хвост строки,
            # который разбор отбрасывает без потерь. Когда nr_sp_rule_id стоял после девяти
            # редких колонок, все проверенные модели сбивались со счёта (сравнение 17.09).
            # Колонки подтверждения — в перечне: без них «лишних не добавляй» читалось как
            # запрет, и модель не подтверждала чеки (проход 2 на IQ2_M, 17.09).
            "полей строго в этом порядке: decision_kind, nr_sp_rule_id, resource_review_status, "
            "resource_review_ref, resource_code, resource_quantity, resource_unit, included_in, "
            "resource_action, target_resource_code, target_resource_id, replaced_by, material_review_status, "
            "material_review_reason, conversion_factor, conversion_unit, conversion_source, "
            # Проход 25: по демонтажу модель написала «нормы на демонтаж нет, эта — про монтаж»,
            # хотя расчёт принимает коэффициент к норме. Контракт просил coefficient_basis, но
            # самих колонок в перечне не было, а вне перечня — запрещено (18.09).
            "coefficient, coefficient_basis, coefficient_target, section, operation, analogue, "
            "coverage, not_covered. Колонку, которая "
            "не нужна ни одной строке, не добавляй; пустые ячейки в конце строки можно не писать. "
            # Проход 18: на 27 колонках модель промахивается по ячейкам. Узкие таблицы
            # снимают счёт пустых ячеек, а разбор читает их обе.
            "Работы и материалы можно дать отдельными таблицами: в каждой повтори базовую шапку "
            "и добавь только нужные её строкам колонки. "
            # Живая проверка 17.09: у монтажных норм НР/СП неоднозначны по сборнику, а выбрать
            # норматив модели было нечем — работа оставалась без полной суммы.
            "Если в расчёте nr_sp.status не resolved, выбери для работы норматив НР/СП из "
            "nr_sp.candidates по виду работ и укажи его rule_id в колонке nr_sp_rule_id. "
            "Если получен расчётный receipt, проверь его состав/влияние и добавь "
            "resource_review_status=keep_all_confirmed, а в resource_review_ref — значение calculation_ref "
            "этой операции из полученного расчёта, скопированное целиком (длинная строка), а не само слово; "
            "только для подтверждённого тобой результата, иначе измени собственное решение. Это делается для "
            "каждой операции со своим чеком, включая самостоятельный материал: у каждой свой calculation_ref. "
            "Для coefficient не 1 укажи coefficient_basis — точный нормативный источник и пункт, "
            "и coefficient_target: labor, machines (включая машинистов), materials или явный список "
            "этих компонентов через запятую. Проверь, что источник подтверждает значение и область "
            "действия; без этого коэффициент останется неприменённым. Физический пересчёт — только conversion_*. "
            "В разделителе и каждой строке должно быть столько же ячеек, сколько колонок в шапке. "
            "Не помещай дополнительные поля внутрь coefficient или coverage. Символ вертикальной "
            "черты внутри значения замени точкой с запятой. "
            "Каждая строка начинается и заканчивается вертикальной чертой. Для каждой "
            "строки явно укажи source_row, section, title, unit, quantity, выбранный тобой "
            "norm_code, analogue, coverage, coefficient и evidence_refs Qx.Hy. Не добавляй "
            "status и не ограничивай количество строк. Если выбираешь карточку как норму "
            "или инженерный аналог, укажи её точный шифр в norm_code; оставляй его пустым "
            "только если не выбрана ни одна карточка. Для строки с выбранной карточкой укажи "
            "точную evidence_refs Qx.Hy; не сокращай её до Qx. "
            "Если карточка не выбрана, оставь evidence_refs пустым и объясни пробел. Не выводи "
            "JSON. Код не подтверждает и не меняет твой выбор. Ответ должен вместить все "
            "операции: без вводного обзора и итоговых рекомендаций, кратко по одной операции в строке таблицы."
        )
    return question_tail


def fit_smeta_portion_context(attachment_context: str, *, session_id: str, limit: int,
                             cursors: Any, preset: ModelExecutionPreset,
                             profile_prefix: str, request_payload: Any):
    """Plan whole rows/receipts against the actual inference budget, without writes.

    Half the remaining input window is reserved for retrieval. This is a context
    allocation, never a decision/attempt limit; all deferred rows remain pending.
    """
    from dataclasses import replace

    answer_preset = replace(preset, generation_reserve_tokens=max(
        preset.generation_reserve_tokens, 8192 if preset.input_token_limit >= 32768 else 0))
    _, base = govern_inference_messages(preset=answer_preset, profile_prefix=profile_prefix,
                                       request_payload=request_payload)
    source_budget = max(1, (base.input_budget_tokens - base.included_tokens) // 2)
    candidate_limit = max(1, limit)
    while True:
        context, state = smeta_portion_context(attachment_context, session_id=session_id,
                                               limit=candidate_limit, cursors=cursors)
        if state.get('state') != 'portion':
            return context, state
        source_tokens = conservative_token_estimate('\n'.join(selector_evidence_payload(
            attachment_context=context, rendered_context='')))
        if source_tokens <= source_budget or state['rows_in_pass'] <= 1:
            state['context_budget'] = dict(source_tokens=source_tokens, source_budget_tokens=source_budget,
                                           input_budget_tokens=base.input_budget_tokens,
                                           fits=source_tokens <= source_budget,
                                           requested_rows=limit, selected_rows=state['rows_in_pass'])
            if source_tokens > source_budget:
                state['context_budget_exceeded'] = True
                context = ('[ОХВАТ РАСЧЁТА] Полный контекст одной строки превышает бюджет. '
                           'Не подтверждай расчёт по неполным ресурсам; строка остаётся незавершённой.\n'
                           + context)
            return context, state
        candidate_limit = state['rows_in_pass'] - 1


def _attachment_name(text: str) -> str:
    """Имя файла из первой строки скрепки «Файл: …»."""
    first = str(text or "").splitlines()[0] if text else ""
    return first.split(":", 1)[1].strip() if first.lower().startswith("файл:") else "ведомость"


def portioned_attachment_context(
    attachment_context: str,
    *,
    rows: Sequence[Mapping[str, Any]],
    limit: int,
    name: str,
    after: str = "",
) -> str:
    """Текст вложения для одного прохода: порция строк вместо всего файла.

    Ведомость целиком вытесняет из окна карточки норм — замер 10.09: вместе с профилем
    она занимает 8 444 токена из 22 528. Порция короче в три с половиной раза и оставляет
    место тому, ради чего запрос делается.

    Если ведомость не разобралась в строки, отдаём исходный текст: работать с неудобным
    вложением лучше, чем остаться без него.
    """
    if not rows:
        return str(attachment_context or "")
    portion = attachment_portion_text(rows, limit=limit, name=name, after=after)
    return portion or str(attachment_context or "")


def selector_evidence_payload(
    *, attachment_context: str, rendered_context: str, query_plan: Mapping[str, Any] | None = None,
) -> list[Any]:
    """Return model evidence as independently packable, ordered source blocks."""

    payload: list[Any] = []
    if str(attachment_context or "").strip():
        payload.append("Текст явно прикреплённого пользователем файла:")
        payload.extend(_bounded_source_blocks(attachment_context))
    payload.append("Материалы из найденных документов:")
    if query_plan:
        note = model_rag_query_plan_note(query_plan).strip()
        if note:
            payload.append(note)
    payload.extend(
        item.payload
        for item in _text_context_objects("selector-evidence", rendered_context)
    )
    return payload


def selector_context_shortlist(
    shortlist: Sequence[Any], *, native_tool_schemas: bool,
) -> Sequence[Any]:
    """Do not duplicate native provider tool schemas inside message context."""

    return () if native_tool_schemas else shortlist


def initial_selector_context(
    rendered_context: str, *, model_authored_initial_query: bool,
) -> str:
    """Do not label a not-yet-run model-authored search as empty retrieval."""

    return "" if model_authored_initial_query else rendered_context


def profile_system_prompt(profile_snapshot: dict[str, Any] | None, *, strict: bool,
                          model_rag_refs: bool = False) -> str:
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
        citations = ('Ссылки на карточки оформляй идентификаторами Qn.Hm; навигационные карты помогают '
                     if model_rag_refs else
                     'Ссылки оформляй номерами из заголовков [Источник N]; навигационные карты помогают ')
        parts.append(
            "Для проверяемых утверждений используй только реальные материалы текущего запроса. "
            + citations +
            "выбрать файл, но сами по себе не подтверждают факт."
        )
    return "\n\n".join(parts)


def prepare_estimator_answer_contract(
    snapshot, *, canonical_mode, model_driven: bool, tools_enabled: bool,
    original_prefix: str, original_request: str, question: str, instruction: str = '',
    output_directive=None, target_doc_filter=None,
):
    """Adapt only ACTIVE estimator answer; all other stage contracts stay literal."""
    if (getattr(canonical_mode, 'value', canonical_mode) != 'active' or not model_driven
            or (snapshot or {}).get('mode') != 'estimator'):
        return original_prefix, original_request, None
    from proxy.services.chat_profile_service import render_factory_estimator_answer
    rendered, trace = render_factory_estimator_answer(snapshot, tools_enabled=tools_enabled)
    prefix = model_answer_prefix(profile_system_prompt(rendered, strict=False, model_rag_refs=True),
        instruction=instruction, output_directive=output_directive, target_doc_filter=target_doc_filter)
    request = model_answer_request(question, model_driven=True,
        active_estimator_answer=True, native_tools_enabled=tools_enabled)
    trace.update(original_system_sha256=hashlib.sha256(original_prefix.encode('utf-8')).hexdigest(),
                 rendered_system_sha256=hashlib.sha256(prefix.encode('utf-8')).hexdigest(),
                 original_request_sha256=hashlib.sha256(original_request.encode('utf-8')).hexdigest(),
                 rendered_request_sha256=hashlib.sha256(request.encode('utf-8')).hexdigest())
    return prefix, request, trace


def profile_query_prompt(profile_snapshot: dict[str, Any] | None) -> str:
    """Use the bound role/skill for research; the full answer prompt belongs to generation."""
    snapshot = profile_snapshot if isinstance(profile_snapshot, dict) else {}
    mode = str(snapshot.get('mode') or 'agent').strip() or 'agent'
    skill = str(snapshot.get('skill_text') or '').strip()
    prompt = f'Ты — Л.Е.С., профиль {mode}. Этот вызов формулирует поисковые запросы к источникам.'
    if skill:
        prompt += '\nАктивный skill профиля (правила поиска):\n' + skill
    return prompt


def profile_tool_selector_prompt(profile_snapshot: dict[str, Any] | None) -> str:
    """Compile the thin role+skill contract for one native tool decision."""

    snapshot = profile_snapshot if isinstance(profile_snapshot, dict) else {}
    mode = str(snapshot.get("mode") or "agent").strip() or "agent"
    skill = str(snapshot.get("skill_text") or "").strip()
    parts = [
        (
            f"Ты — Л.Е.С., профиль {mode}. На этом вызове выбери нужные native tools, "
            "а не формулируй итоговый ответ. Модель сама создаёт поисковые запросы и "
            "принимает предметные решения; код только исполняет вызовы и оформляет результат."
        )
    ]
    if skill:
        parts.append("Активный skill профиля:\n" + skill)
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
    model_connection_resolver: Callable | None = None
    model_connection_transport: Callable | None = None
    workbook_tool_executor: Callable | None = None
    workbook_artifact_available: Callable | None = None


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
        model_connection_resolver=runtime.model_connection_resolver,
        model_connection_transport=runtime.model_connection_transport,
        workbook_tool_executor=runtime.workbook_tool_executor,
        workbook_artifact_available=runtime.workbook_artifact_available,
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


def _bind_smeta_discipline(retrieve, *, question: str, attachment_context: str,
                           practice_mode: str = "both"):
    """Bind section and explicit archive experiment without changing retrieval order."""
    import inspect

    if practice_mode not in {"none", "frequency", "similar", "both"}:
        raise ValueError("unknown smeta_practice_mode")
    section = smeta_discipline_for_request(
        question=question, attachment_context=attachment_context
    )
    try:
        parameters = inspect.signature(retrieve).parameters
    except (TypeError, ValueError):
        parameters = {}
    accepts = "discipline" in parameters or any(
        value.kind is inspect.Parameter.VAR_KEYWORD for value in parameters.values()
    )
    bound = partial(retrieve, discipline=section) if section and accepts else retrieve
    if practice_mode in {"frequency", "both"}:
        return bound

    def without_frequency(*args, **kwargs):
        payload = bound(*args, **kwargs)
        result = {k: v for k, v in payload.items() if k != "usage_discipline"}
        result["cards"] = [
            {k: v for k, v in card.items() if k != "usage_evidence"}
            if isinstance(card, Mapping) else card
            for card in payload.get("cards", [])
        ]
        return result

    return without_frequency


def smeta_discipline_for_request(*, question: str, attachment_context: str) -> str:
    """Раздел сметы по запросу и вложению — один раз на весь разбор ведомости.

    Модель спрашивает нормы построчно, и отдельная строка дисциплины не содержит:
    «Монтаж шпильки М8» её не выдаёт, хотя раздел ведомости назван прямо. Заголовок
    раздела живёт во вложении, поэтому он и читается здесь.
    """
    from proxy.smeta_core.collection_scope import discipline_for_text
    from proxy.smeta_core.section_taxonomy import section_for_title

    # Во вложении раздел назван словами проекта («Монтаж системы структурированной
    # кабельной сети»), поэтому сперва спрашиваем таксономию разделов.
    head = " ".join(str(attachment_context or "").split())[:2000]
    for text in (head, str(question or "")):
        section = section_for_title(text)
        if section:
            return section
    for text in (str(question or ""), head):
        discipline = discipline_for_text(text)
        if discipline:
            return discipline
    return ""


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
    memory_block,
    model_connection_resolver,
    model_connection_transport,
    workbook_tool_executor,
    workbook_artifact_available,
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
    _dataset_ids = tuple(str(item) for item in (_dataset_ids or ()) if str(item))
    document_grounding_enabled = bool(
        (scope_resolution or {}).get("document_grounding_enabled", _dataset_ids)
    )
    if document_grounding_enabled:
        use_semantic_cache = False
    # Ordinary chat is model-owned: validators may not judge, retry, rewrite,
    # suppress, or relabel the model's engineering conclusion.
    use_validation = False
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
        if document_grounding_enabled and not profile_uses_model_driven_retrieval(
            profile_snapshot
        ):
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
        else:
            retrieval = _SkippedDocumentRetrieval()
        chunks = [*topic_chunks, *retrieval.chunks] if topic_chunks else list(retrieval.chunks)
    except Exception as e:
        import traceback

        tb = traceback.format_exc()
        logger.error("[CHAT] RETRIEVAL ERROR: %s\n%s", e, tb)
        raise HTTPException(500, f"Поиск по датасету не удался: {type(e).__name__}: {e}")
    t_search = time.time() - t_search_start
    retrieval_trace = retrieval.payload()
    if document_grounding_enabled and profile_uses_model_driven_retrieval(profile_snapshot):
        retrieval_trace.update(
            {
                "status": "model_driven",
                "reason": "awaiting_model_authored_query",
            }
        )
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
        # Неготовность контура (native RRF, реранкер) проходит при повторе и ответом
        # диалога не является: сохранённая заглушка попадает в контекст следующих
        # запросов сессии, и модель начинает её копировать вместо ответа.
        transient_block = is_transient_retrieval_block(error_code)
        retrieval_trace["blocker"]["transient"] = transient_block
        try:
            history_id = None if transient_block else save_chat_history(
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
                storage_root=mutable_path("./storage/datasets"),
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
    primary_document_pricing = (profile_uses_smeta_norm_retrieval(profile_snapshot)
                                and bool(str(getattr(req, 'attachment_id', '') or '').strip()))
    if primary_document_pricing:
        retrieval_trace['semantic_answer_cache'] = {
            'status': 'bypassed', 'reason': 'document_price_basis_not_yet_bound'}

    if use_semantic_cache and cache_scope and not use_validation:
        session_hit = document_price_safe_cache_lookup(
            cache,
            req.question,
            cache_scope,
            focused_fingerprint,
            req.session_id,
            primary_document=primary_document_pricing,
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

    connection_resolver = None
    connection_secret_store = None
    connection_factory_error = ""
    canonical_route = resolve_canonical_route(receipt=None)
    try:
        connection_resolver, connection_secret_store = model_connection_resolver()
        if (
            canonical_route.requested is CanonicalRouteMode.ACTIVE
            and canonical_route.effective is CanonicalRouteMode.SHADOW
        ):
            canonical_route = resolve_promoted_route(resolver=connection_resolver)
    except Exception as error:
        connection_factory_error = type(error).__name__
    candidate_acceptance = bool(getattr(req, "candidate_acceptance", False))
    canonical_execution_mode = execution_mode_for_candidate_acceptance(
        candidate_acceptance=candidate_acceptance,
        route=canonical_route,
    )
    if not candidate_acceptance and model_connection_resolver is not None:
        # The GUI-owned answer binding is authoritative for ordinary chat.
        # Shadow remains an isolated telemetry/acceptance concern only.
        canonical_execution_mode = CanonicalRouteMode.ACTIVE
    if candidate_acceptance:
        retrieval_trace["candidate_acceptance"] = {
            "enabled": True,
            "execution_mode": canonical_execution_mode.value,
            "promotion_receipt": "not_used",
            "state_root": "process_cwd_isolated",
        }
    resolved_connection = None
    connection_resolution_error = connection_factory_error
    if canonical_execution_mode is not CanonicalRouteMode.LEGACY:
        try:
            if connection_resolver is None:
                connection_resolver, connection_secret_store = model_connection_resolver()
            resolved_connection = connection_resolver.resolve(ConnectionRole.ANSWER)
        except Exception as error:  # shadow is diagnostic; active is fail-closed
            connection_resolution_error = type(error).__name__
            if canonical_execution_mode is CanonicalRouteMode.ACTIVE:
                raise HTTPException(503, f"MODEL_CONNECTION_RESOLUTION_FAILED: {error}") from error

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
        llm_runtime = configured_runtime
    cache_state: dict[str, Any] = {}
    if (
        canonical_execution_mode is not CanonicalRouteMode.ACTIVE
        and getattr(llm_runtime, "requires_cache_alignment", False)
    ):
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
    if canonical_execution_mode is CanonicalRouteMode.ACTIVE and resolved_connection is not None:
        execution_preset = resolved_connection.effective_preset
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
    memory_projection_stage = "project_memory"
    try:
        typed_memory = await asyncio.to_thread(
            project_memory,
            session_id=str(req.session_id or ""),
            project_id=memory_project_id or None,
            dataset_ids=tuple(str(item) for item in _dataset_ids if str(item)),
            limits=MemoryLimits(),
        )
        memory_projection_stage = "context_candidates"
        memory_candidates = typed_memory.as_context_candidates()
        memory_projection_stage = "trace_projection"
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
            "error_stage": memory_projection_stage,
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
    if canonical_execution_mode is CanonicalRouteMode.ACTIVE and resolved_connection is not None:
        retrieval_trace["routing"].update(
            {
                "effective_provider": "model_connection",
                "effective_model": resolved_connection.model_id,
                "downgraded": False,
                "is_cloud": resolved_connection.locality is ConnectionLocality.REMOTE,
            }
        )
    if resolved_connection is not None:
        retrieval_trace["model_connection_candidate"] = {
            "revision_id": resolved_connection.revision_id,
            "locality": resolved_connection.locality.value,
            "effective": canonical_execution_mode is CanonicalRouteMode.ACTIVE,
            "resolution_error": connection_resolution_error,
        }
    llm_model = (
        resolved_connection.model_id
        if canonical_execution_mode is CanonicalRouteMode.ACTIVE and resolved_connection is not None
        else llm_runtime.model
    )
    val_url = (
        resolved_connection.base_url.rstrip("/")
        if canonical_execution_mode is CanonicalRouteMode.ACTIVE and resolved_connection is not None
        else llm_runtime.base_url.rstrip("/")
    )
    # Локальный MLX-хост всегда держит /api/validate (coreml NLI, ~0.1с). Облачные ответы
    # валидируем им же, а не повторным промптом в облако (это давало 3-11с на P1-ответ).
    local_val_url = _mlx_runtime().base_url.rstrip("/")
    if not llm_model:
        raise HTTPException(503, f"LLM model is not configured for provider {llm_runtime.provider}")
    # W3.4-частично (вопрос оператора 2026-06-14 «почему не валидируем облаком?»):
    # у не-MLX провайдеров нет /api/validate — валидируем ТОЙ ЖЕ моделью
    # компактным промптом-вердиктом (VERIFIED/HALLUCINATION/NO_DATA).
    validate_via_llm = bool(
        use_validation
        and (
            canonical_execution_mode is CanonicalRouteMode.ACTIVE
            or not llm_runtime.supports_validation
        )
    )
    if validate_via_llm:
        logger.info("[TOSKA] validation via provider=%s (no LES /api/validate)", llm_runtime.provider)

    # The central RAG role pack already owns engineering style, source boundaries,
    # navigation-vs-evidence and human-facing wording.  Repeating those rules here
    # used to add thousands of prompt characters and, worse, made the application
    # service a second hidden prompt registry.  Keep only the source-label contract
    # that is specific to the evidence packet rendered below.
    sys_normal = profile_system_prompt(profile_snapshot, strict=False)
    sys_strict = profile_system_prompt(profile_snapshot, strict=True)

    # ADR-15 structured estimates own their output contract. Prose intent hints
    # (e.g. "сколько" inside "несколько") must not impose a one-line/256-token
    # answer on a multi-row mapping. Explicit operator length still applies.
    form_question = "" if profile_uses_smeta_norm_retrieval(profile_snapshot) else req.question
    answer_form = apply_response_length(classify_answer_form(form_question), req.response_length)
    retrieval_trace["answer_form"] = {"intent": answer_form.intent, "max_tokens": answer_form.max_tokens}
    if class_suggestions:
        retrieval_trace["class_suggestions"] = [s["class"] for s in class_suggestions]

    # Облако не держит локальный Metal-слот: отдельный пул (LES_CLOUD_LLM_CONCURRENCY).
    gen_semaphore = generation_semaphore(state.llm_semaphore)

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

    model_evidence_chunks = list(llm_chunks)

    def _build_model_evidence(current_chunks: Sequence[Any]):
        packet = build_retrieval_evidence_packet(
            question=req.question,
            chunks=current_chunks,
            retrieval_trace=retrieval_trace,
            navigation=evidence_navigation,
            deterministic_evidence=deterministic_evidence,
        )
        rendered = render_retrieval_evidence_for_model(
            packet,
            max_chars=context_chars_limit,
            include_metadata=True,
        )
        source_map = packet.source_map(
            max_chars=context_chars_limit,
            include_metadata=True,
        )
        return (
            packet,
            rendered,
            source_map,
            packet.to_dict(max_chars=context_chars_limit, include_metadata=True),
        )

    (
        initial_evidence_packet,
        context,
        answer_source_map,
        final_evidence_packet,
    ) = _build_model_evidence(model_evidence_chunks)
    retrieval_trace["evidence_packet"] = initial_evidence_packet.trace_summary(
        max_chars=context_chars_limit,
        include_metadata=True,
    )
    attachment_context = str(getattr(req, "attachment_context", "") or "").strip()
    model_driven_retrieval = profile_uses_model_driven_retrieval(profile_snapshot)
    source_attachment_id = str(getattr(req, 'attachment_id', '') or '').strip()
    document_source_attachment_sha256 = ''
    if profile_uses_smeta_norm_retrieval(profile_snapshot) and source_attachment_id.lower().startswith('read_'):
        from proxy.services.tabular_attachment_service import load_full_tabular_attachment_context
        from proxy.smeta_core.vor_rows import rows_from_attachment_text

        try:
            full_source = await asyncio.to_thread(load_full_tabular_attachment_context, source_attachment_id)
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=422, detail={
                'code': 'SMETA_ATTACHMENT_SOURCE_UNAVAILABLE',
                'message': 'Не удалось проверить исходное вложение для сметы. Прикрепи файл заново.',
            }) from error
        if full_source is not None:
            full_text, source_metadata = full_source
            document_source_attachment_sha256 = source_metadata['sha256']
            retrieval_trace['smeta_attachment_source'] = {
                'status': 'verified_full_tabular', 'attachment_id': source_attachment_id,
                'sha256': source_metadata['sha256'], 'preview_chars': len(attachment_context),
                'source_chars': len(full_text), 'source_rows': len(rows_from_attachment_text(full_text)),
            }
            attachment_context = full_text
    source_attachment_context = attachment_context

    # Let the actual source/receipt budget determine a complete-row portion.
    # Explicit row caps remain available; unseen rows never become completed.
    portion_rows = smeta_portion_rows(attachment_context)
    portion_cursors = None
    portion_state: dict[str, Any] = {}
    document_price_basis = None
    document_source_revision = ''
    if profile_uses_smeta_norm_retrieval(profile_snapshot) and source_attachment_context:
        from proxy.smeta_core.vor_rows import rows_from_attachment_text, source_revision
        from proxy.services import fgis_price_service
        portion_cursors = portion_cursor_store()
        if source_attachment_id and not document_source_attachment_sha256:
            from proxy.services.chat_attachment_service import resolve_read_attachment
            _, attachment_metadata = await asyncio.to_thread(resolve_read_attachment, source_attachment_id)
            document_source_attachment_sha256 = attachment_metadata['sha256']
        document_source_revision = document_price_source_revision(
            source_attachment_context, document_source_attachment_sha256)
        document_price_basis = await asyncio.to_thread(document_price_basis_or_error, portion_cursors,
            session_id=str(getattr(req, 'session_id', '') or ''), source_revision=document_source_revision,
            capture=fgis_price_service.capture_price_basis, http_exception=HTTPException)
        retrieval_trace['document_price_basis'] = document_price_basis
    document_price_browse = bind_document_price_browse(document_price_basis) if document_price_basis is not None else smeta_price_browse
    if profile_uses_smeta_norm_retrieval(profile_snapshot) and attachment_context and portion_rows > 0:
        portion_cursors = portion_cursor_store()
        # Строки, исчерпавшие попытки, возвращаются в оборот, если источники подсказок
        # обновились: отказ модели относился к прежнему набору свидетельств. Делается
        # до планирования порции, иначе вернувшиеся строки попали бы только в следующий
        # проход (ревью Codex 11.09, шаг 5).
        if portion_cursors is not None:
            try:
                from proxy.smeta_core.vor_rows import (
                    rows_from_attachment_text,
                    source_revision,
                )

                reopened = portion_cursors.reopen_exhausted(
                    session_id=str(getattr(req, "session_id", "") or ""),
                    source_revision=source_revision(
                        rows_from_attachment_text(attachment_context)
                    ),
                    evidence_revision=evidence_sources_revision(document_price_basis=document_price_basis),
                )
                if reopened:
                    retrieval_trace["smeta_rows_reopened"] = reopened
            except Exception:  # noqa: BLE001 — возврат строк не должен ронять проход
                logger.warning("[SMETA_PORTION] возврат строк не удался", exc_info=True)
        def plan_context(text):
            return fit_smeta_portion_context(
                text, session_id=str(getattr(req, "session_id", "") or ""),
                limit=portion_rows, cursors=portion_cursors, preset=execution_preset,
                profile_prefix=model_answer_prefix(sys_normal, instruction=answer_form.instruction,
                    output_directive=req.output_directive, target_doc_filter=target_doc_filter),
                request_payload=model_answer_request(req.question, model_driven=True),
            )
        attachment_context, portion_state = plan_context(attachment_context)
        portion_state['document_price_basis'] = document_price_basis
        retrieval_trace["smeta_portion"] = portion_state
        # Книга устарела относительно решений — пересобираем её здесь, до исследования
        # и до ответа модели. Решения приняты и неизменны, повторять их незачем: штатный
        # отказ упаковщика чинится нулём вызовов транспорта (ревью Codex 11.09).
        if (
            portion_cursors is not None
            and stored_decisions_need_a_workbook(portion_state, artifact_available=workbook_artifact_available)
            and workbook_tool_executor is not None
            and canonical_execution_mode is CanonicalRouteMode.ACTIVE
            and str(getattr(req, "attachment_id", "") or "").strip()
        ):
            logger.warning(
                "[SMETA_PORTION] пересборка книги по %s сохранённым решениям",
                len(portion_state.get("prior_decisions") or {}),
            )
            rebuilt_meta = await rebuild_workbook_from_stored_decisions(
                executor=workbook_tool_executor,
                portion_state=portion_state,
                attachment_id=str(getattr(req, "attachment_id", "") or ""),
                question=str(req.question or ""),
                context={
                    "session_id": str(req.session_id or ""),
                    "question": str(req.question or ""),
                    "dataset_ids": [str(item) for item in _dataset_ids],
                    "project_id": getattr(req, "project_id", None),
                    "attachment_id": str(getattr(req, "attachment_id", "") or ""),
                    "profile_revision_id": str(
                        (profile_snapshot or {}).get("revision_id") or ""
                    ),
                    "model_identity": "stored-decisions-rebuild",
                    "model_preset": execution_preset.preset_id,
                    "document_price_basis": document_price_basis,
                    "source_revision": document_source_revision,
                    "source_attachment_sha256": document_source_attachment_sha256,
                },
                progress=(lambda _event: asyncio.sleep(0)),
                trace=retrieval_trace,
            )
            rebuilt_revision = _workbook_revision_id(rebuilt_meta)
            if rebuilt_revision:
                try:
                    rebuilt_statuses = workbook_row_statuses(rebuilt_meta)
                    if rebuilt_statuses is not None:
                        portion_cursors.record_calculation(
                            session_id=str(req.session_id or ""),
                            source_revision=str(portion_state.get("source_revision") or ""),
                            statuses={anchor: rebuilt_statuses[str(row.get("source_row"))]
                                      for anchor, row in (portion_state.get("prior_decisions") or {}).items()
                                      if str(row.get("source_row")) in rebuilt_statuses},
                            receipts=(rebuilt_meta.get('workbook_diagnostics') or {}).get('row_calculation') or [],
                        )
                    portion_cursors.record_pass(
                        session_id=str(getattr(req, "session_id", "") or ""),
                        source_revision=str(portion_state.get("source_revision") or ""),
                        completed={},
                        artifact_revision_id=rebuilt_revision,
                        artifact_decisions_revision=_portion_decisions_revision(
                            portion_state.get("prior_decisions") or {}, document_price_basis=document_price_basis
                        ),
                        pass_id=f"rebuild:{rebuilt_revision}",
                    )
                except Exception:  # noqa: BLE001 — книга уже собрана
                    logger.warning(
                        "[SMETA_PORTION] ревизия пересобранной книги не записана",
                        exc_info=True,
                    )
                # Re-plan from actual calculation: a persisted choice can fail units
                # when the previously failed packaging finally runs.
                attachment_context, portion_state = plan_context(source_attachment_context)
                retrieval_trace["smeta_portion"] = portion_state
                portion_state["rebuilt_workbook"] = rebuilt_meta
                if portion_state.get("state") == "complete":
                    # Показывать нечего, книга пересобрана — ход закончен здесь.
                    # Продолжать до исследования и генерации значило бы звать модель
                    # ради нечего: она и так получила бы сообщение «новых строк нет»
                    # (ревью Codex 11.09). Ноль обращений к транспорту.
                    rebuilt_answer = (
                        f"Книга пересобрана по сохранённым решениям: решение принято по "
                        f"{portion_state.get('completed')} позициям из "
                        f"{portion_state.get('total')}."
                    )
                    unresolved_rows = int(portion_state.get("exhausted") or 0)
                    if unresolved_rows:
                        rebuilt_answer += (
                            f" По {unresolved_rows} позициям норма не найдена — они"
                            " остались нерешёнными."
                        )
                    retrieval_trace["smeta_portion_rebuild_terminal"] = True
                    rebuilt_response: dict[str, Any] = {
                        "answer": rebuilt_answer,
                        "crag_status": "MODEL_OUTPUT",
                        "sources": [],
                        "effective_dataset_filter": effective_dataset_filter,
                        "query_route": query_route_payload,
                        "retrieval_trace": retrieval_trace,
                        "cache": cache_marker,
                        "validation": {"enabled": False},
                        "versions": _version_stamp(),
                        "smeta_portion": {
                            "schema": "les.smeta.portion-progress.v2",
                            "pass_no": portion_state.get("pass_no"),
                            "rows_in_pass": 0,
                            "remaining": 0,
                            "total": portion_state.get("total"),
                            "decided": portion_state.get("completed"),
                            "unresolved": portion_state.get("exhausted"),
                        },
                    }
                    rebuilt_response.update(rebuilt_meta)
                    try:
                        rebuilt_response["history_id"] = save_chat_history(
                            question=req.question,
                            answer=rebuilt_answer,
                            sources=[],
                            crag_status="MODEL_OUTPUT",
                            latency_sec=0.0,
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
                            success=1,
                        )
                    except Exception as history_error:  # noqa: BLE001 — книга уже собрана
                        logger.warning("[CHAT] History save error: %s", history_error)
                        rebuilt_response["history_id"] = None
                    return rebuilt_response
        if portion_state.get("state") != "not-a-vor":
            logger.warning(
                "[SMETA_PORTION] проход %s: строк %s из %s, решено ранее %s, "
                "без нормы %s, остаток %s",
                portion_state.get("pass_no"),
                portion_state.get("rows_in_pass"),
                portion_state.get("total"),
                portion_state.get("completed"),
                portion_state.get("exhausted"),
                portion_state.get("remaining"),
            )

    selector_evidence = selector_evidence_payload(
        attachment_context=attachment_context,
        rendered_context=initial_selector_context(
            context,
            model_authored_initial_query=model_driven_retrieval,
        ),
    )
    selector_source_map = answer_source_map
    async with acquire_generation_slot(gen_semaphore, timeout_seconds=45.0):
        try:
            # trust_env=False обязателен: системный SOCKS от VPN перехватывает и
            # localhost, а httpx на схеме socks4 падает ещё при создании клиента —
            # «Unknown scheme for proxy URL socks4://127.0.0.1:10808». Весь сметный
            # путь идёт по петле, внешнему прокси в нём делать нечего (живой прогон
            # 11.09, 10:34; тот же дефект уже чинили по всему проекту 07.06).
            async with httpx.AsyncClient(timeout=300.0, trust_env=False) as client:
                answer = ""
                crag_status = "UNKNOWN"
                tokens = 0
                active_model_result = None
                active_pending_tool_calls = 0
                bound_runner = None
                if canonical_execution_mode is CanonicalRouteMode.ACTIVE:
                    if connection_resolver is None or connection_secret_store is None:
                        raise HTTPException(503, "MODEL_CONNECTION_RESOLVER_REQUIRED")
                    bound_runner = BoundModelChatRunner(
                        resolver=connection_resolver,
                        transport=model_connection_transport(client, connection_secret_store),
                    )

                async def _post_llm(runtime, model, hdrs, body, *, allow_stream: bool = True,
                                    audit_purpose: str | None = None):
                    """Один вызов LLM. token_sink задан → стрим (токены клиенту по
                    мере генерации), иначе — обычный POST (поведение неизменно).
                    Возвращает (answer_text, usage_dict)."""
                    nonlocal active_model_result, active_pending_tool_calls
                    if bound_runner is not None:
                        request_audit = None
                        if (audit_purpose in {"answer", "answer_read"}
                                and canonical_execution_mode is CanonicalRouteMode.ACTIVE
                                and model_driven_retrieval
                                and profile_uses_smeta_norm_retrieval(profile_snapshot)):
                            from proxy.services.model_request_audit_service import ModelRequestAudit
                            request_audit = ModelRequestAudit(
                                directory=mutable_path("storage/model_request_receipts"),
                                purpose=audit_purpose,
                                refs=retrieval_trace.setdefault("model_request_audit", []),
                            )
                        inference_request = InferenceRequest(
                            messages=tuple(body.get("messages") or ()),
                            max_output_tokens=max(
                                1,
                                int(
                                    body.get("max_completion_tokens")
                                    or body.get("max_tokens")
                                    or 1
                                ),
                            ),
                            temperature=body.get("temperature"),
                            tools=tuple(body.get("tools") or ()),
                            response_format=body.get("response_format"),
                            request_audit=request_audit,
                        )

                        async def no_legacy_call(_request):
                            raise RuntimeError("LEGACY_MODEL_CALL_FORBIDDEN_IN_ACTIVE_MODE")

                        sensitivities = _dataset_sensitivities(
                            set(_dataset_ids_from_chunks(chunks))
                            | {str(item) for item in (_dataset_ids or [])}
                        )
                        active_model_result = await bound_runner.complete(
                            mode=canonical_execution_mode,
                            request=inference_request,
                            legacy_complete=no_legacy_call,
                            remote_allowed=cloud_allowed(
                                sensitivities,
                                consent=_env_bool("LES_CLOUD_CONSENT", False),
                            ),
                        )
                        active_pending_tool_calls += active_model_result.pending_tool_calls
                        if token_sink is not None and allow_stream and active_model_result.response.text:
                            await token_sink(
                                {"event": "token", "data": active_model_result.response.text}
                            )
                        retrieval_trace["model_connection"] = (
                            active_model_result.public_connection_payload()
                        )
                        retrieval_trace["model_connection"]["pending_tool_calls"] = active_pending_tool_calls
                        model_text = active_model_result.response.text
                        if active_model_result.response.tool_calls:
                            canonical_calls: list[dict[str, Any]] = []
                            for raw_call in active_model_result.response.tool_calls:
                                function = raw_call.get("function") or {}
                                raw_arguments = function.get("arguments") or "{}"
                                try:
                                    arguments = (
                                        json.loads(raw_arguments)
                                        if isinstance(raw_arguments, str)
                                        else dict(raw_arguments)
                                    )
                                except (TypeError, ValueError, json.JSONDecodeError):
                                    arguments = {}
                                canonical_calls.append(
                                    {
                                        "call_id": str(raw_call.get("id") or ""),
                                        "tool": str(function.get("name") or ""),
                                        "args": arguments,
                                    }
                                )
                            model_text = json.dumps(
                                {"calls": canonical_calls},
                                ensure_ascii=False,
                                separators=(",", ":"),
                            )
                        usage = dict(active_model_result.response.usage)
                        # Причина остановки отличает законченный список запросов от
                        # оборванного по пределу генерации (проходы 3 и 5, 17.09).
                        usage.setdefault(
                            "finish_reason",
                            str(getattr(active_model_result.response, "finish_reason", "") or ""),
                        )
                        return (model_text, usage)
                    if getattr(runtime, "uses_native_chat", False):
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

                async def _post_cloud_fallback(
                    runtime, hdrs, body, *, allow_stream: bool = True,
                ):
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
                                _post_llm(
                                    runtime,
                                    m,
                                    hdrs,
                                    body,
                                    allow_stream=allow_stream,
                                ),
                                timeout=per_model,
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
                workbook_chat_meta: dict[str, Any] = {}
                tool_context = ""
                model_rag_query_hits: list[tuple[str, Sequence[Any]]] = []
                model_rag_evidence_groups: list[str] = []
                visual_tool_requested = any(
                    marker in str(req.question or "").casefold().replace("ё", "е")
                    for marker in ("посмотри глазами", "посмотри чертеж", "посмотри схему", "что видно на лист", "что изображено на лист")
                )
                profile_tools = [
                    str(name) for name in (profile_snapshot or {}).get("tools", []) if str(name).strip()
                ]
                web_research_config = capture_web_research_config()
                selected_sources_only = bool(
                    getattr(req, "selected_sources_only", False)
                )
                profile_tools = filter_profile_tools(
                    profile_tools,
                    selected_sources_only=selected_sources_only,
                )
                profile_tools = web_tools_for_request(
                    profile_tools,
                    web_research_config,
                )
                retrieval_trace["capability_scope"] = {
                    "selected_sources_only": selected_sources_only,
                    "public_web_available": not selected_sources_only,
                    "web_research": public_web_research_config(web_research_config),
                    "web_reader_available": (
                        not selected_sources_only
                        and web_research_config.mode == "extended"
                        and "web_read" in profile_tools
                    ),
                    "source": "explicit_or_frozen_request",
                }
                profile_tools = tools_for_document_scope(
                    profile_tools,
                    enabled=document_grounding_enabled,
                )
                if canonical_execution_mode is not CanonicalRouteMode.ACTIVE:
                    profile_tools = [
                        name
                        for name in profile_tools
                        if name not in {"build_lsr_workbook", "build_vor_workbook"}
                    ]
                route_trace = canonical_route_trace_payload(
                    canonical_route,
                    execution_mode=canonical_execution_mode,
                    candidate_acceptance=candidate_acceptance,
                )
                retrieval_trace["canonical_route"] = route_trace
                retrieval_trace["route_comparison"] = {
                    "schema": "les.canonical-route-comparison.v1",
                    "requested": route_trace["requested"],
                    "effective": route_trace["effective"],
                    "legacy_output_authoritative": (
                        canonical_execution_mode is not CanonicalRouteMode.ACTIVE
                    ),
                    "same_request": True,
                    "profile_revision": str(
                        (profile_snapshot or {}).get("revision_id") or ""
                    ),
                    "canonical_provider_calls_added": 0,
                    "persisted_effects": 0,
                }
                if candidate_acceptance:
                    retrieval_trace["route_comparison"]["candidate_acceptance"] = True
                canonical_shadow_recorded = False
                tool_loop_enabled = bool(profile_tools)
                if model_driven_retrieval and tool_loop_enabled:
                    retrieval_limits = effective_retrieval_policy(profile_snapshot)
                    query_headers = {}
                    if llm_runtime.api_key:
                        query_headers["Authorization"] = f"Bearer {llm_runtime.api_key}"
                    query_messages, query_packet = govern_inference_messages(
                        preset=execution_preset,
                        profile_prefix=(
                            profile_query_prompt(profile_snapshot)
                            + "\n\n" + model_rag_query_instruction(
                                profile_snapshot,
                                rows_in_pass=model_rag_query_rows(portion_state),
                            )
                        ),
                        request_payload={
                            "question": str(req.question or ""),
                            "dataset_ids": [str(item) for item in _dataset_ids],
                        },
                        checkpoint=(),
                        working_memory=(),
                        evidence=selector_evidence_payload(
                            attachment_context=query_attachment_context(source_attachment_context, portion_state),
                            rendered_context=initial_selector_context(context, model_authored_initial_query=True),
                        ),
                        source_map=selector_source_map,
                        tool_exchange=(),
                    )
                    retrieval_trace["context_governor"]["calls"].append(
                        context_packet_trace(query_packet, purpose="model_rag_queries")
                    )
                    query_body = {
                        "messages": query_messages,
                        "stream": False,
                        "temperature": 0,
                        "max_tokens": model_rag_query_max_tokens(
                            query_budget=plan_model_rag_queries(
                                (), rows_in_pass=model_rag_query_rows(portion_state),
                            )["budget"],
                            ceiling=_env_int("LES_CHAT_MODEL_RAG_QUERY_MAX_TOKENS", 1600),
                        ),
                    }
                    t_query_model = time.time()
                    query_text, query_usage = await _post_llm(
                        llm_runtime,
                        llm_model,
                        query_headers,
                        query_body,
                        allow_stream=False,
                    )
                    t_llm += time.time() - t_query_model
                    model_queries_all = parse_model_rag_queries(query_text)
                    query_plan = plan_model_rag_queries(
                        model_queries_all,
                        rows_in_pass=model_rag_query_rows(portion_state),
                        truncated=(
                            str((query_usage or {}).get("finish_reason") or "") == "length"
                            or int((query_usage or {}).get("completion_tokens") or 0)
                            >= int(query_body["max_tokens"])
                        ),
                    )
                    model_queries = list(query_plan["executed"])
                    if not model_queries:
                        raise HTTPException(
                            status_code=503,
                            detail="MODEL_RAG_QUERY_LIST_EMPTY",
                        )

                    async def _no_model_rag_fallback(_tool_name: str, _args: dict[str, Any]):
                        raise RuntimeError("MODEL_RAG_ONLY_SUPPORTS_SEARCH_SOURCES")

                    practice_mode = str(getattr(req, "smeta_practice_mode", "both") or "both")
                    retrieval_trace["smeta_practice_experiment"] = {
                        "mode": practice_mode,
                        "frequency": practice_mode in {"frequency", "both"},
                        "similar": practice_mode in {"similar", "both"},
                        "sources_revision": evidence_sources_revision(document_price_basis=document_price_basis),
                    }
                    model_research_tools = ModelResearchToolService(
                        retrieve=retrieve_chat_chunks,
                        frozen_dataset_ids=tuple(
                            str(item) for item in _dataset_ids if str(item)
                        ),
                        retrieval_kwargs={
                            "rag_backend": rag_backend,
                            "reranker_enabled": _reranker_on,
                            "reranker_available": state.reranker_available,
                            "reranker_cls": state.reranker_cls,
                            "mlx_url": os.getenv("MLX_URL", "http://127.0.0.1:8080"),
                            "logger": logger,
                            "llm_semaphore": state.llm_semaphore,
                            "return_trace": True,
                            "doc_filter": None,
                            "scope_source": str(
                                (scope_resolution or {}).get("scope_source") or "unspecified"
                            ),
                            "scope_error_code": str(
                                (scope_resolution or {}).get("error_code") or ""
                            ),
                        },
                        fallback=_no_model_rag_fallback,
                        smeta_norm_retrieve=(
                            _bind_smeta_discipline(
                                retrieve_smeta_norm_cards,
                                practice_mode=practice_mode,
                                question=str(req.question or ""),
                                attachment_context=attachment_context,
                            )
                            if profile_uses_smeta_norm_retrieval(profile_snapshot)
                            else None
                        ),
                        price_browse=(
                            document_price_browse
                            if profile_uses_smeta_norm_retrieval(profile_snapshot)
                            else None
                        ),
                        **retrieval_limits,
                    )
                    for query in model_queries:
                        research_result = await model_research_tools.execute(
                            {"tool": "search_sources", "args": {"q": query}}
                        )
                        tool_results_for_model.append(research_result.payload)
                        model_rag_query_hits.append(
                            (
                                query,
                                tuple(research_result.chunks)[
                                    : evidence_limit(research_result.chunks,
                                                     retrieval_limits["model_evidence_k"])
                                ],
                            )
                        )
                    # Optional archive examples share the production governor.
                    # Frequency is also removed from search cards in none/similar.
                    if practice_mode in {"frequency", "both"}:
                        practice_group = smeta_practice_group(
                            attachment_context=attachment_context,
                            question=str(req.question or ""),
                            already_shown=model_rag_query_hits,
                            trace=retrieval_trace,
                        )
                        if practice_group is not None:
                            model_rag_query_hits.insert(0, practice_group)
                    if practice_mode in {"similar", "both"}:
                        material_group = smeta_material_group(
                            titles=list(portion_state.get("shown_titles") or ()),
                            already_shown=model_rag_query_hits,
                            trace=retrieval_trace,
                        )
                        if material_group is not None:
                            model_rag_query_hits.insert(0, material_group)
                    # Выполненный поиск без совпадений доходит до модели как пустая выдача:
                    # решать, что с ней делать, должна та же модель (аудит Codex 17.09, P2).
                    empty_queries = model_rag_empty_queries(tool_results_for_model)
                    if empty_queries:
                        retrieval_trace["model_rag_empty_queries"] = empty_queries
                    search_failure = model_rag_failure_detail(tool_results_for_model)
                    if search_failure:
                        logger.warning("[MODEL_RAG_SEARCH_INCOMPLETE] %s", search_failure)
                        raise HTTPException(
                            status_code=503,
                            detail=search_failure,
                        )
                    (
                        model_rag_evidence_groups,
                        model_evidence_chunks,
                    ) = build_model_rag_evidence_groups(
                        model_rag_query_hits,
                        max_chars=context_chars_limit,
                        hits_per_query=retrieval_limits["model_evidence_k"],
                    )
                    context = "\n\n".join(model_rag_evidence_groups)
                    # Длинная ведомость за проход не помещается. Сообщаем это и модели, и трассе:
                    # молча потерянные строки модель закроет вслепую.
                    evidence_coverage = model_rag_evidence_coverage(
                        model_rag_query_hits, model_rag_evidence_groups
                    )
                    retrieval_trace["model_evidence_coverage"] = evidence_coverage
                    if not evidence_coverage["complete"]:
                        context += _evidence_coverage_note(evidence_coverage)
                    context += model_rag_query_plan_note(query_plan)
                    model_rag_evidence_packet = build_retrieval_evidence_packet(
                        question=req.question,
                        chunks=model_evidence_chunks,
                        retrieval_trace=retrieval_trace,
                        navigation=evidence_navigation,
                        deterministic_evidence=deterministic_evidence,
                    )
                    answer_source_map = _model_rag_source_map(model_evidence_chunks)
                    final_evidence_packet = model_rag_evidence_packet.to_dict(
                        max_chars=context_chars_limit,
                        include_metadata=True,
                    )
                    retrieval_trace["evidence_packet"] = (
                        model_rag_evidence_packet.trace_summary(
                            max_chars=context_chars_limit,
                            include_metadata=True,
                        )
                    )
                    tool_context = _format_tool_results_for_model(tool_results_for_model)
                    retrieval_trace["tool_loop"] = {
                        "schema": "les_model_rag_batch_v1",
                        "enabled": True,
                        "model_owns_queries": True,
                        "model_queries_raw": query_text,
                        "model_queries": model_queries,
                        "model_queries_total": query_plan["total"],
                        "model_queries_budget": query_plan["budget"],
                        "model_queries_skipped": query_plan["skipped"],
                        "model_queries_truncated": query_plan["truncated"],
                        "query_usage": query_usage,
                        "results": tool_results_for_model,
                        "evidence_groups": evidence_group_ids(model_rag_evidence_groups),
                        "hits_per_query": [
                            len(hits) for _query, hits in model_rag_query_hits
                        ],
                    }
                elif tool_loop_enabled:
                    retrieval_limits = effective_retrieval_policy(profile_snapshot)
                    tool_loop_stage = "harness"
                    try:
                        from proxy.services.tool_harness_service import harness

                        tool_harness = harness(web_config=web_research_config)

                        async def _fallback_model_tool(tool_name: str, args: dict[str, Any]):
                            return await asyncio.to_thread(tool_harness.call, tool_name, args)

                        model_research_tools = ModelResearchToolService(
                            retrieve=retrieve_chat_chunks,
                            frozen_dataset_ids=tuple(str(item) for item in _dataset_ids if str(item)),
                            retrieval_kwargs={
                                "rag_backend": rag_backend,
                                "reranker_enabled": _reranker_on,
                                "reranker_available": state.reranker_available,
                                "reranker_cls": state.reranker_cls,
                                "mlx_url": os.getenv("MLX_URL", "http://127.0.0.1:8080"),
                                "logger": logger,
                                "llm_semaphore": state.llm_semaphore,
                                "return_trace": True,
                                "doc_filter": None,
                                "scope_source": str(
                                    (scope_resolution or {}).get("scope_source") or "unspecified"
                                ),
                                "scope_error_code": str(
                                    (scope_resolution or {}).get("error_code") or ""
                                ),
                            },
                            fallback=_fallback_model_tool,
                            price_browse=(document_price_browse if profile_uses_smeta_norm_retrieval(profile_snapshot) else None),
                            **retrieval_limits,
                        )
                        shortlist_limit = (
                            len(profile_tools)
                            if model_driven_retrieval
                            else min(
                                execution_preset.max_tools,
                                max(1, _env_int("LES_CHAT_TOOL_SHORTLIST_LIMIT", 64)),
                            )
                        )
                        configured_call_limit = max(
                            1, _env_int("LES_CHAT_TOOL_MAX_CALLS", 48)
                        )
                        max_calls = (
                            configured_call_limit
                            if model_driven_retrieval
                            else min(execution_preset.max_batch_items, configured_call_limit)
                        )
                        workbook_phase = bool(
                            getattr(req, "attachment_id", None)
                            and {"build_lsr_workbook", "build_vor_workbook"}.intersection(profile_tools)
                        )
                        profile_tools = prioritize_workbook_tools(
                            profile_tools,
                            workbook_phase=workbook_phase,
                        )
                        tool_loop_stage = "shortlist"
                        from proxy.services.workbook_tool_service import (
                            available_chat_workbook_tools,
                        )

                        runtime_available_tools = set(profile_tools).difference(
                            {"build_lsr_workbook", "build_vor_workbook"}
                        )
                        runtime_available_tools.update(
                            available_chat_workbook_tools(
                                executor_configured=workbook_tool_executor is not None
                            )
                        )
                        runtime_available_tools.intersection_update(profile_tools)
                        shortlist = await asyncio.to_thread(
                            tool_harness.shortlist,
                            req.question,
                            mode=str(req.mode or route.intent or ""),
                            allowed_tools=profile_tools,
                            limit=shortlist_limit,
                            dataset_ids=tuple(str(item) for item in _dataset_ids if str(item)),
                            workflow_phase="draft" if workbook_phase else "research",
                            model_preset=execution_preset.preset_id,
                            runtime_available=frozenset(runtime_available_tools),
                            calls_remaining=max_calls,
                            result_chars_remaining=35_000,
                            **(
                                {"attachment_ids": (str(req.attachment_id),)}
                                if getattr(req, "attachment_id", None)
                                else {}
                            ),
                        )
                        allowed_tools = {
                            str(tool.get("name") or "")
                            for tool in shortlist.get("tools", [])
                            if isinstance(tool, dict) and tool.get("name")
                        }
                        native_tools = native_model_tool_schemas(
                            shortlist.get("tools") or []
                        )
                        selector_headers = {}
                        if llm_runtime.api_key:
                            selector_headers["Authorization"] = f"Bearer {llm_runtime.api_key}"
                        selected_calls: list[dict[str, Any]] = []
                        selector_usage: list[dict[str, Any]] = []
                        research_rounds: list[dict[str, Any]] = []
                        failed_tool_calls = FailedToolCallGuard()
                        research_deadline_seconds = max(
                            1.0,
                            _env_float("LES_CHAT_RESEARCH_DEADLINE_SECONDS", 120.0),
                        )
                        research_deadline = time.monotonic() + research_deadline_seconds
                        research_round = 0
                        calls_remaining = max_calls
                        stop_reason = "deadline"
                        while time.monotonic() < research_deadline and calls_remaining > 0:
                            research_round += 1
                            prior_results = [
                                _compact_tool_result_for_prompt(item, max_chars=2400)
                                for item in tool_results_for_model[-max_calls:]
                            ]
                            tool_call_instruction = (
                                "Вызывай предоставленные инструменты напрямую. "
                                if canonical_execution_mode is CanonicalRouteMode.ACTIVE
                                else "Верни только JSON {\"calls\":[{\"tool\":\"...\",\"args\":{...}}]}. "
                            )
                            # Одного статуса в результатах мало: модель повторяла упавший
                            # вызов в следующем раунде, и вызов селектора уходил впустую.
                            _failed_calls = failed_tool_calls.failed_summary()
                            if _failed_calls:
                                tool_call_instruction += (
                                    "Эти вызовы уже неуспешны, не повторяй их и не меняй в них "
                                    "только форматирование аргументов: "
                                    + json.dumps(list(_failed_calls), ensure_ascii=False)
                                    + ". Если других полезных вызовов нет — верни пустой список. "
                                )
                            selector_profile = "".join(
                                (
                                    profile_tool_selector_prompt(profile_snapshot),
                                    "\n\nТы управляешь коротким исследовательским чтением LES. ",
                                    "Явно прикреплённый текст ниже уже доступен тебе как evidence и не требует индексации. "
                                    "Сначала прочитай его и используй read-only инструменты, чтобы закрыть конкретные пробелы. "
                                    "Если оператор просит артефакт, после получения достаточного evidence вызови "
                                    "подходящий draft-инструмент; предметные решения и поисковые запросы выбираешь ты. ",
                                    "Не объявляй вложение отсутствующим, когда его текст присутствует в пакете. ",
                                    "Если оператор явно просит посмотреть глазами страницу или лист PDF, ",
                                    "обязательно выбери look_at_pdf_page с указанными файлом и номером страницы; ",
                                    "текстовый read_pdf_source не заменяет просмотр пикселей. ",
                                    "Инструменты не отвечают за тебя и не заменяют источники. ",
                                    tool_call_instruction,
                                    "Если evidence достаточно, заверши исследование без нового вызова. ",
                                    "Не выбирай инструмент вне списка и не выходи за выбранные dataset/file scope.",
                                )
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
                            if model_driven_retrieval:
                                # The estimator's first job is to read the
                                # attachment and author RAG queries. Advisory
                                # memory must not displace that evidence.
                                selector_working_memory = ()
                            tool_loop_stage = "context_governor"
                            selector_messages, selector_packet = govern_inference_messages(
                                preset=execution_preset,
                                profile_prefix=selector_profile,
                                request_payload=tool_selector_request_payload(
                                    question=req.question,
                                    mode=req.mode or route.intent or "",
                                    dataset_ids=_dataset_ids,
                                    target_file_ref=target_file_ref,
                                    round_no=research_round,
                                    attachment_id=getattr(req, "attachment_id", None),
                                ),
                                shortlist=selector_context_shortlist(
                                    shortlist.get("tools") or [],
                                    native_tool_schemas=(
                                        canonical_execution_mode is CanonicalRouteMode.ACTIVE
                                    ),
                                ),
                                checkpoint=selector_checkpoint,
                                working_memory=selector_working_memory,
                                evidence=selector_evidence,
                                source_map=selector_source_map,
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
                            if canonical_execution_mode is CanonicalRouteMode.ACTIVE:
                                selector_body["tools"] = native_tools
                            t_tool_selector = time.time()
                            tool_loop_stage = "selector_model"
                            selector_text, round_usage = await _post_llm(
                                llm_runtime,
                                llm_model,
                                selector_headers,
                                selector_body,
                                allow_stream=False,
                            )
                            t_llm += time.time() - t_tool_selector
                            selector_usage.append(round_usage)
                            tool_loop_stage = "selector_parse"
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
                                    max_calls=calls_remaining,
                                )
                            ]
                            if (
                                not canonical_shadow_recorded
                                and canonical_execution_mode is CanonicalRouteMode.SHADOW
                            ):
                                tool_loop_stage = "shadow_decision"
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
                            calls = [
                                call for call in proposed_calls
                                if not failed_tool_calls.repeated(call)
                            ][:calls_remaining]
                            research_rounds.append(
                                {"round": research_round, "proposed": len(proposed_calls), "executed": len(calls)}
                            )
                            if not calls:
                                stop_reason = "model_stop"
                                if proposed_calls:
                                    stop_reason = "repeated_failed_call"
                                break
                            for call in calls:
                                if failed_tool_calls.repeated(call):
                                    continue
                                tool_loop_stage = "tool_execution"
                                tool_name = str(call.get("tool") or "")
                                if (
                                    tool_name in {"build_lsr_workbook", "build_vor_workbook"}
                                    and canonical_execution_mode is CanonicalRouteMode.ACTIVE
                                    and workbook_tool_executor is not None
                                ):
                                    async def workbook_progress(event: dict[str, Any]) -> None:
                                        if token_sink is not None:
                                            await token_sink({"event": "tool_progress", "data": event})

                                    if tool_name == 'build_lsr_workbook':
                                        call = {**call, 'args': {**(call.get('args') or {}),
                                            'decisions': bind_normative_identity(
                                                (call.get('args') or {}).get('decisions') or [],
                                                chunks=model_evidence_chunks,
                                                delivered_cards=delivered_evidence_cards(
                                                    '\n'.join(str(m.get('content') or '') for m in messages),
                                                    model_evidence_chunks),
                                                packet_text='\n'.join(str(m.get('content') or '') for m in messages),
                                                prior_evidence=(portion_state or {}).get('prior_evidence') or ())}}
                                    payload = await workbook_tool_executor(
                                        call,
                                        {
                                            "session_id": str(req.session_id or ""),
                                            "question": str(req.question or ""),
                                            "dataset_ids": [str(item) for item in _dataset_ids],
                                            "project_id": getattr(req, "project_id", None),
                                            "attachment_id": str(getattr(req, "attachment_id", None) or ""),
                                            "profile_revision_id": str((profile_snapshot or {}).get("revision_id") or ""),
                                            "model_identity": str(
                                                getattr(
                                                    getattr(active_model_result, "connection", None),
                                                    "model_id",
                                                    "",
                                                )
                                                or llm_model
                                            ),
                                            "model_preset": execution_preset.preset_id,
                                            "document_price_basis": document_price_basis,
                                            "source_revision": document_source_revision,
                                            "source_attachment_sha256": document_source_attachment_sha256,
                                        },
                                        workbook_progress,
                                    )
                                else:
                                    research_result = await model_research_tools.execute(call)
                                    payload = research_result.payload
                                    if research_result.chunks:
                                        known_chunk_ids = {
                                            str((getattr(item, "meta", {}) or {}).get("chunk_id") or "")
                                            or hashlib.sha256(
                                                (
                                                    str(getattr(item, "doc_name", "") or "")
                                                    + "\x00"
                                                    + str(getattr(item, "content", "") or "")
                                                ).encode("utf-8")
                                            ).hexdigest()
                                            for item in chunks
                                        }
                                        for found_chunk in research_result.chunks:
                                            found_id = str(
                                                (getattr(found_chunk, "meta", {}) or {}).get("chunk_id") or ""
                                            ) or hashlib.sha256(
                                                (
                                                    str(getattr(found_chunk, "doc_name", "") or "")
                                                    + "\x00"
                                                    + str(getattr(found_chunk, "content", "") or "")
                                                ).encode("utf-8")
                                            ).hexdigest()
                                            if found_id not in known_chunk_ids:
                                                chunks.append(found_chunk)
                                                known_chunk_ids.add(found_id)
                                        research_windows = expand_context_windows(
                                            chunks,
                                            collection=getattr(rag_backend, "collection_name", ""),
                                            logger=logger,
                                            max_chunks=context_max_chunks,
                                            max_chars_per_chunk=context_window_chars,
                                            radius=context_radius,
                                        )
                                        model_evidence_chunks = list(research_windows.chunks)
                                        (
                                            _research_evidence_packet,
                                            context,
                                            answer_source_map,
                                            final_evidence_packet,
                                        ) = _build_model_evidence(model_evidence_chunks)
                                        retrieval_trace["evidence_packet"] = (
                                            _research_evidence_packet.trace_summary(
                                                max_chars=context_chars_limit,
                                                include_metadata=True,
                                            )
                                        )
                                        selector_evidence = selector_evidence_payload(
                                            attachment_context=attachment_context,
                                            rendered_context=context,
                                        )
                                        selector_source_map = answer_source_map
                                failed_tool_calls.record(call, payload)
                                selected_calls.append(call)
                                calls_remaining -= 1
                                safe_payload = safe_workbook_history_projection(payload)
                                tool_results_for_model.append(
                                    safe_payload if safe_payload else payload
                                )
                                answer_source_map = _merge_web_source_map(
                                    answer_source_map,
                                    tool_results_for_model,
                                )
                                selector_source_map = answer_source_map
                                harvested = harvest_workbook_tool_result(safe_payload)
                                if harvested:
                                    workbook_chat_meta = harvested
                                    stop_reason = "workbook_complete"
                                    break
                            if workbook_chat_meta:
                                break
                            if calls_remaining <= 0:
                                stop_reason = "calls_budget"
                                break
                        tool_context = _format_tool_results_for_model(tool_results_for_model)
                        web_research_trace = public_web_research_config(
                            web_research_config
                        )
                        for web_payload in tool_results_for_model:
                            if str(web_payload.get("tool") or "") != "web_search":
                                continue
                            web_result = web_payload.get("result") or {}
                            if isinstance(web_result, Mapping):
                                web_research_trace.update(
                                    {
                                        "requested_mode": str(
                                            web_result.get("requested_mode")
                                            or web_research_config.mode
                                        ),
                                        "effective_mode": str(
                                            web_result.get("effective_mode")
                                            or web_research_config.mode
                                        ),
                                        "provider": str(web_result.get("provider") or ""),
                                        "degraded": bool(web_result.get("degraded")),
                                        "fallback_reason": str(
                                            web_result.get("fallback_reason") or ""
                                        ),
                                    }
                                )
                        retrieval_trace["tool_loop"] = {
                            "schema": "les_model_research_loop_v1",
                            "enabled": True,
                            "model_owns_selection": True,
                            "selector_model": llm_model,
                            "selector_provider": llm_runtime.provider,
                            "shortlist": shortlist,
                            "selected_calls": [
                                safe_selected_call_trace(call) for call in selected_calls
                            ],
                            "selector_usage": selector_usage,
                            "results": tool_results_for_model,
                            "rounds": research_rounds,
                            "stop_reason": stop_reason,
                            "deadline_seconds": research_deadline_seconds,
                            "max_calls_per_model_response": max_calls,
                            "max_calls_total": max_calls,
                            "calls_remaining": calls_remaining,
                            "native_tool_schemas": bool(native_tools),
                            "web_research": web_research_trace,
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
                        logger.exception(
                            "[TOOLS] model tool loop skipped: %s",
                            type(tool_err).__name__,
                        )
                        retrieval_trace["tool_loop"] = {
                            "schema": "les_model_tool_loop_v1",
                            "enabled": True,
                            "status": "error",
                            "error_type": type(tool_err).__name__,
                            "error_stage": tool_loop_stage,
                        }
                else:
                    retrieval_trace["tool_loop"] = {
                        "schema": "les_model_research_loop_v1",
                        "enabled": False,
                        "reason": "disabled_by_operator",
                        "model_owns_final_answer": True,
                    }
                if (
                    canonical_execution_mode is CanonicalRouteMode.SHADOW
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
                # Keep the connection/preset-owned split between input and output.
                # Reserving 4096 tokens unconditionally for model-authored rows made
                # the profile + request overflow an 8K Qwen window before evidence
                # could reach the model at all.
                answer_execution_preset = execution_preset
                if (
                    model_driven_retrieval
                    and answer_execution_preset.input_token_limit >= 32_768
                ):
                    answer_execution_preset = replace(
                        answer_execution_preset,
                        generation_reserve_tokens=max(
                            answer_execution_preset.generation_reserve_tokens,
                            8_192,
                        ),
                        source_chain=(
                            *answer_execution_preset.source_chain,
                            "model_rag_complete_answer",
                        ),
                    )
                max_attempts = 1 if model_driven_retrieval else 2
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
                        answer_source_map = _merge_web_source_map(
                            answer_source_map,
                            tool_results_for_model,
                        )
                        sys_msg = sys_strict
                        logger.warning("[SAFERAG] Retry #2 — строгий промпт, %s чанков", len(ctx_chunks))
                    else:
                        ctx_chunks = model_evidence_chunks
                        (
                            evidence_packet,
                            context,
                            answer_source_map,
                            final_evidence_packet,
                        ) = _build_model_evidence(ctx_chunks)
                        retrieval_trace["evidence_packet"] = evidence_packet.trace_summary(
                            max_chars=context_chars_limit,
                            include_metadata=True,
                        )
                        answer_source_map = _merge_web_source_map(
                            answer_source_map,
                            tool_results_for_model,
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
                        sys_msg = model_answer_prefix(sys_normal, instruction=answer_form.instruction,
                                                      output_directive=req.output_directive, target_doc_filter=target_doc_filter)
                    question_tail = model_answer_request(req.question, model_driven=model_driven_retrieval)
                    answer_read_tools = (
                        model_rag_search_tool_schema()
                        if model_driven_retrieval and tool_loop_enabled
                        and canonical_execution_mode is CanonicalRouteMode.ACTIVE else []
                    )
                    sys_msg, question_tail, answer_contract_trace = prepare_estimator_answer_contract(
                        profile_snapshot, canonical_mode=canonical_execution_mode,
                        model_driven=model_driven_retrieval, tools_enabled=bool(answer_read_tools),
                        original_prefix=sys_msg, original_request=question_tail, question=req.question,
                        instruction=answer_form.instruction, output_directive=req.output_directive,
                        target_doc_filter=target_doc_filter,
                    )
                    if answer_contract_trace is not None:
                        retrieval_trace['answer_contract_availability'] = answer_contract_trace
                    if model_driven_retrieval:
                        fixed_model_rag_evidence = selector_evidence_payload(
                            attachment_context=attachment_context,
                            rendered_context="",
                            query_plan=query_plan,
                        )
                        _, fixed_packet = govern_inference_messages(
                            preset=answer_execution_preset,
                            profile_prefix=sys_msg,
                            request_payload=question_tail,
                            checkpoint=(),
                            working_memory=(),
                            required_evidence=fixed_model_rag_evidence,
                            native_tools=answer_read_tools,
                            source_map=(),
                            tool_exchange=(),
                            dialogue=(),
                        )
                        group_char_budget = model_rag_group_char_budget(
                            input_budget_tokens=fixed_packet.input_budget_tokens,
                            included_tokens=fixed_packet.included_tokens,
                            query_count=len(model_rag_query_hits),
                            context_chars_limit=context_chars_limit,
                        )
                        logger.warning(
                            "[MODEL_RAG_BUDGET] queries=%s hits=%s input_budget=%s "
                            "included=%s group_chars=%s notice_reserve=%s "
                            "context_chars_limit=%s",
                            len(model_rag_query_hits),
                            sum(len(hits) for _query, hits in model_rag_query_hits),
                            fixed_packet.input_budget_tokens,
                            fixed_packet.included_tokens,
                            group_char_budget,
                            coverage_note_reserve_tokens(),
                            context_chars_limit,
                        )
                        (
                            model_rag_evidence_groups,
                            model_evidence_chunks,
                        ) = build_model_rag_evidence_groups(
                            model_rag_query_hits,
                            max_chars=group_char_budget,
                            hits_per_query=retrieval_limits["model_evidence_k"],
                        )
                        context = (chr(10) * 2).join(model_rag_evidence_groups)
                        # Охват пересчитывается здесь же: пакет пересобран под остаток
                        # токенов, и модель получила бы меньше строк, чем обещает трасса,
                        # причём без предупреждения (ревью Codex 10.09).
                        evidence_coverage = model_rag_evidence_coverage(
                            model_rag_query_hits, model_rag_evidence_groups
                        )
                        retrieval_trace["model_evidence_coverage"] = evidence_coverage
                        if not evidence_coverage["complete"]:
                            context += _evidence_coverage_note(evidence_coverage)
                        answer_source_map = _model_rag_source_map(model_evidence_chunks)
                        model_rag_evidence_packet = build_retrieval_evidence_packet(
                            question=req.question,
                            chunks=model_evidence_chunks,
                            retrieval_trace=retrieval_trace,
                            navigation=evidence_navigation,
                            deterministic_evidence=deterministic_evidence,
                        )
                        final_evidence_packet = model_rag_evidence_packet.to_dict(
                            max_chars=context_chars_limit,
                            include_metadata=True,
                        )
                        retrieval_trace["grouped_model_evidence"] = {
                            "schema": "les.model-rag-grouped-evidence.v1",
                            "query_count": len(model_rag_evidence_groups),
                            "hit_count": len(model_evidence_chunks),
                            "group_ids": evidence_group_ids(model_rag_evidence_groups),
                            "rendered_chars": len(context),
                        }
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
                    if model_driven_retrieval:
                        answer_checkpoint = ()
                        answer_working_memory = ()
                    answer_tool_exchange = (
                        []
                        if model_driven_retrieval
                        else [
                            _compact_tool_result_for_prompt(item, max_chars=2400)
                            for item in tool_results_for_model
                        ]
                    )
                    answer_evidence = (
                        answer_evidence_blocks(
                            fixed_blocks=fixed_model_rag_evidence,
                            group_blocks=model_rag_evidence_groups,
                            coverage=retrieval_trace.get("model_evidence_coverage"),
                            trace=retrieval_trace,
                        )
                        if model_driven_retrieval
                        else [
                            "Материалы из найденных документов:",
                            *[
                                item.payload
                                for item in _text_context_objects("answer-evidence", context)
                            ],
                        ]
                    )
                    try:
                        if answer_read_tools:
                            messages, answer_packet = govern_model_rag_read_messages(
                                preset=answer_execution_preset, profile_prefix=sys_msg,
                                request_payload=question_tail, fixed_evidence=fixed_model_rag_evidence,
                                read_evidence=(),
                                prior_evidence=answer_evidence[len(fixed_model_rag_evidence):],
                                exchange=(), native_tools=answer_read_tools,
                            )
                        else:
                            messages, answer_packet = govern_inference_messages(
                                preset=answer_execution_preset,
                                profile_prefix=sys_msg,
                                request_payload=question_tail,
                                checkpoint=answer_checkpoint,
                                working_memory=answer_working_memory,
                                evidence=answer_evidence,
                                source_map=(() if model_driven_retrieval else answer_source_map),
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
                    if retrieval_trace.get("coverage_notice_sent"):
                        # Добавление в список блоков — ещё не доставка: свидетельства
                        # необязательны для governor'а, и хвост он отбрасывает первым.
                        # Проверяем по собранному пакету, а не по нашему намерению.
                        retrieval_trace["coverage_notice_delivered"] = (
                            coverage_notice_in_packet(answer_packet)
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
                    if model_driven_retrieval:
                        retrieval_trace['query_notice_delivered'] = '[ЗАПРОСЫ]' in user_prompt
                        retrieval_trace['smeta_evidence_delivery'] = smeta_evidence_delivery_trace(
                            model_rag_query_hits, model_evidence_chunks, user_prompt,
                        )
                    if isinstance(retrieval_trace.get("grouped_model_evidence"), dict):
                        # Собрано и доставлено — разные множества: governor отбрасывает
                        # начало пакета, и по номерам групп нельзя судить о доставке
                        # (аудит Codex 17.09).
                        retrieval_trace["grouped_model_evidence"]["delivered_group_ids"] = (
                            delivered_group_ids(user_prompt)
                        )
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
                        answer_execution_preset.generation_reserve_tokens,
                    )
                    if model_driven_retrieval:
                        # Model-driven ответы не режем эвристиками intent/attempt, но явный
                        # выбор оператора (response_length) и потолок пресета обязательны:
                        # безусловная выдача полного резерва игнорировала «короткий ответ».
                        generation_budget = min(
                            answer_form.max_tokens,
                            answer_execution_preset.generation_reserve_tokens,
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
                    if answer_read_tools:
                        chat_body["tools"] = answer_read_tools
                    # При стриминге ретрай (строгий промпт) шлёт уже новый текст —
                    # просим клиент очистить накопленное от прошлой попытки.
                    if token_sink is not None and attempt > 1:
                        await token_sink({"event": "reset", "data": ""})
                    t_llm_call = time.time()
                    try:
                        if canonical_execution_mode is CanonicalRouteMode.ACTIVE:
                            answer, usage = await _post_llm(
                                llm_runtime,
                                llm_model,
                                headers,
                                chat_body,
                                allow_stream=False,
                                audit_purpose="answer",
                            )
                            if active_model_result is not None:
                                llm_model = active_model_result.connection.model_id
                            read_count = 0
                            read_limit = max(1, _env_int("LES_CHAT_TOOL_MAX_CALLS", 48))
                            previous_reads: list[str] = []
                            read_guard = FailedToolCallGuard()
                            read_connection = active_model_result.public_connection_payload()
                            try:
                                while answer_read_tools and active_model_result.response.tool_calls:
                                    raw_calls = list(active_model_result.response.tool_calls)
                                    read_round = {
                                        "calls": raw_calls, "text": active_model_result.response.text,
                                        "usage": dict(usage), "results": [],
                                        "connection": active_model_result.public_connection_payload(),
                                        "unexecuted_call_ids": [str(c.get("id") or "") for c in raw_calls],
                                    }
                                    retrieval_trace.setdefault("model_rag_reads", []).append(read_round)
                                    if read_count + len(raw_calls) > read_limit:
                                        read_round["stop_reason"] = "read_call_budget_exhausted"
                                        raise HTTPException(422, detail={
                                            "code": "MODEL_RAG_READ_INCOMPLETE",
                                            "message": "Лимит чтений исчерпан; вызовы и остаток сохранены в trace. Строки не закрыты.",
                                        })
                                    read_groups: list[str] = []
                                    exchanges: list[dict[str, Any]] = []
                                    for raw_call in raw_calls:
                                        function = raw_call.get("function") or {}
                                        try:
                                            arguments = function.get("arguments") or "{}"
                                            arguments = json.loads(arguments) if isinstance(arguments, str) else arguments
                                            valid = (function.get("name") == "search_sources"
                                                     and isinstance(arguments, dict) and set(arguments) == {"q"}
                                                     and isinstance(arguments["q"], str) and bool(arguments["q"].strip()))
                                        except (ValueError, TypeError):
                                            arguments, valid = {}, False
                                        call = {"tool": str(function.get("name") or ""), "args": arguments}
                                        if not valid or read_guard.repeated(call):
                                            payload = {"status": "blocked", "code": (
                                                "INVALID_READ_CALL" if not valid else "REPEATED_FAILED_READ"),
                                                "missing": ["A valid, non-repeated search_sources(q) call is required."]}
                                            read_chunks = ()
                                        else:
                                            research_result = await model_research_tools.execute(call)
                                            payload, read_chunks = research_result.payload, research_result.chunks
                                        read_guard.record(call, payload)
                                        read_count += 1
                                        read_round["results"].append({"call_id": raw_call.get("id"), "payload": payload})
                                        read_round["unexecuted_call_ids"].pop(0)
                                        tool_results_for_model.append(payload)
                                        groups: list[str] = []
                                        if valid:
                                            query = arguments["q"]
                                            groups, read_evidence_chunks = build_model_rag_evidence_groups(
                                                [(query, read_chunks)], query_offset=len(model_rag_query_hits),
                                                # Formatting only: reserve the complete returned bodies.
                                                # Governor is the sole authority on actual model capacity.
                                                max_chars=len(query) + 4096 + sum(
                                                    len(str(c.content)) + len(str(c.doc_name)) + 4096 for c in read_chunks),
                                                hits_per_query=max(1, len(read_chunks)),
                                            )
                                            model_rag_query_hits.append((query, tuple(read_chunks)))
                                            model_evidence_chunks.extend(read_evidence_chunks)
                                            read_groups.extend(groups)
                                        exchanges.append({"model_call": raw_call, "status": payload.get("status"),
                                                          "code": payload.get("code"), "missing": payload.get("missing"),
                                                          "warnings": payload.get("warnings"),
                                                          "evidence_groups": evidence_group_ids(groups)})
                                    messages, answer_packet = govern_model_rag_read_messages(
                                        preset=answer_execution_preset, profile_prefix=sys_msg,
                                        request_payload=question_tail, fixed_evidence=fixed_model_rag_evidence,
                                        read_evidence=read_groups,
                                        prior_evidence=[*previous_reads, *answer_evidence[len(fixed_model_rag_evidence):]],
                                        exchange=exchanges, native_tools=answer_read_tools,
                                    )
                                    previous_reads.extend(read_groups)
                                    read_round["context"] = context_packet_trace(answer_packet, purpose="answer_read")
                                    retrieval_trace["context_governor"]["calls"].append(read_round["context"])
                                    user_prompt = next((m["content"] for m in messages if m["role"] == "user"), "")
                                    retrieval_trace["smeta_evidence_delivery"] = smeta_evidence_delivery_trace(
                                        model_rag_query_hits, model_evidence_chunks, user_prompt,
                                    )
                                    retrieval_trace["grouped_model_evidence"]["delivered_group_ids"] = delivered_group_ids(user_prompt)
                                    retrieval_trace["coverage_notice_delivered"] = coverage_notice_in_packet(answer_packet)
                                    chat_body = {**chat_body, "messages": messages}
                                    answer, usage = await _post_llm(
                                        llm_runtime, llm_model, headers, chat_body, allow_stream=False,
                                        audit_purpose="answer_read",
                                    )
                                    llm_model = active_model_result.connection.model_id
                                    read_round["continuation_response"] = {
                                        "text": active_model_result.response.text,
                                        "tool_calls": list(active_model_result.response.tool_calls),
                                        "usage": dict(usage),
                                    }
                                    continued_connection = active_model_result.public_connection_payload()
                                    if any(continued_connection.get(key) != read_connection.get(key)
                                           for key in ("revision_id", "model_id")):
                                        read_round["connection_changed"] = continued_connection
                                        raise HTTPException(409, detail={
                                            "code": "MODEL_RAG_READ_CONNECTION_CHANGED",
                                            "message": "Подключение модели изменилось во время чтения; результат не принят.",
                                        })
                                if previous_reads:
                                    answer_source_map = _model_rag_source_map(model_evidence_chunks)
                                    delivered_refs = delivered_evidence_cards(user_prompt, model_evidence_chunks)
                                    for source in answer_source_map:
                                        source["delivered_to_model"] = source.get("evidence_ref") in delivered_refs
                                    delivered_chunks = [c for c in model_evidence_chunks
                                                        if c.meta.get("model_evidence_ref") in delivered_refs]
                                    model_rag_evidence_packet = build_retrieval_evidence_packet(
                                        question=req.question, chunks=delivered_chunks,
                                        retrieval_trace=retrieval_trace, navigation=evidence_navigation,
                                        deterministic_evidence=deterministic_evidence,
                                    )
                                    final_evidence_packet = model_rag_evidence_packet.to_dict(
                                        # This is a UI source inventory, not another inference packet.
                                        # Include every source already proved present in actual messages.
                                        max_chars=sum(len(c.content) + len(c.doc_name) + 4096 for c in delivered_chunks),
                                        include_metadata=True,
                                    )
                                    retrieval_trace["prompt_layers"].update(
                                        user_total=len(user_prompt),
                                        messages_total=sum(len(str(m.get("content") or "")) for m in messages),
                                    )
                                    retrieval_trace["model_rag_read_complete"] = True
                            except BaseException as read_error:
                                if retrieval_trace.get("model_rag_reads"):
                                    receipt = persist_model_rag_read_receipt(
                                        trace=retrieval_trace, question=req.question,
                                        attachment_context=attachment_context,
                                        session_id=req.session_id, error=read_error,
                                    )
                                    logger.error("[MODEL_RAG_READ_INCOMPLETE] receipt=%s path=%s", receipt["receipt_id"], receipt["path"])
                                    if isinstance(read_error, ContextRequiredSectionOverflow):
                                        raise HTTPException(422, detail={
                                            "code": "MODEL_RAG_READ_CONTEXT_OVERFLOW",
                                            "message": "Полная карточка не помещается в контекст; чтение сохранено: " + receipt["receipt_id"],
                                        }) from read_error
                                    if isinstance(read_error, HTTPException) and isinstance(read_error.detail, dict):
                                        read_error.detail = {**read_error.detail, "message":
                                            str(read_error.detail.get("message") or "") + " receipt=" + receipt["receipt_id"]}
                                raise
                        elif is_cloud_provider(llm_runtime.provider):
                            # Облако: цепочка моделей с таймаутом на модель (зависла → следующая).
                            answer, usage, llm_model = await _post_cloud_fallback(
                                llm_runtime,
                                headers,
                                chat_body,
                                allow_stream=False,
                            )
                        else:
                            answer, usage = await _post_llm(
                                llm_runtime,
                                llm_model,
                                headers,
                                chat_body,
                                allow_stream=False,
                            )
                    except (httpx.TransportError, httpx.TimeoutException, asyncio.TimeoutError, httpx.HTTPStatusError) as net_err:
                        # W3.3/ADR-9: все облачные модели не ответили → деградация на
                        # локальный MLX. Для не-облака (MLX) ошибку прокидываем как раньше.
                        if answer_read_tools or not is_cloud_provider(llm_runtime.provider):
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
                                source_map=(
                                    () if model_driven_retrieval else answer_source_map
                                ),
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
                        answer_execution_preset = fallback_preset
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
                        if model_driven_retrieval:
                            retrieval_trace['smeta_evidence_delivery'] = smeta_evidence_delivery_trace(
                                model_rag_query_hits, model_evidence_chunks,
                                next((m['content'] for m in fallback_messages if m['role'] == 'user'), ''),
                            )
                        answer, usage, messages = await post_with_delivery_messages(
                            _post_llm,
                            llm_runtime,
                            llm_model,
                            headers,
                            fallback_body,
                            allow_stream=False,
                        )
                    t_llm += time.time() - t_llm_call
                    # Keep actual answer metadata separate from query generation,
                    # including rejected attempts. Missing provider fields stay unknown.
                    retrieval_trace.setdefault("answer_generations", []).append({
                        "attempt": attempt, "model": llm_model,
                        "output_budget": generation_budget,
                        "finish_reason": usage.get("finish_reason") or None,
                        "usage": {key: usage[key] for key in (
                            "prompt_tokens", "completion_tokens", "total_tokens",
                            "completion_tokens_details", "prompt_tokens_details",
                        ) if key in usage},
                    })
                    # Inspect the complete response before any visible token/history write.
                    # Per-delta checks cannot detect a control marker split across chunks.
                    if is_control_channel_text(answer):
                        retrieval_trace["answer_control_echo"] = {"attempt": attempt}
                        answer = ""
                    if not answer:
                        if attempt < max_attempts:
                            logger.warning("[CHAT] empty LLM answer on attempt=%s — retrying strict", attempt)
                            continue
                        raise ValueError(f"Пустой ответ LLM (stream={token_sink is not None})")
                    # Вырождение малой модели: вместо ответа дословно пересказан системный
                    # промпт. Это не ответ — обрабатываем как пустой, с той же попыткой.
                    _system_text = "\n".join(
                        str(item.get("content") or "")
                        for item in messages
                        if isinstance(item, dict) and item.get("role") == "system"
                    )
                    if answer_echoes_prompt(answer, _system_text):
                        retrieval_trace["answer_echoed_prompt"] = {"attempt": attempt}
                        if attempt < max_attempts:
                            logger.warning(
                                "[CHAT] answer echoed the system prompt on attempt=%s — retrying strict",
                                attempt,
                            )
                            continue
                        raise ValueError("Модель вернула пересказ инструкции вместо ответа")
                    # Зацикливание: модель повторяет один фрагмент (часто — свой прошлый
                    # ответ из истории сессии) до упора в лимит. Усекать такое бессмысленно.
                    if answer_is_degenerate_repetition(answer):
                        retrieval_trace["answer_degenerate_repetition"] = {"attempt": attempt}
                        if attempt < max_attempts:
                            logger.warning(
                                "[CHAT] degenerate repetition on attempt=%s — retrying strict",
                                attempt,
                            )
                            continue
                        raise ValueError("Модель зациклилась и не дала ответ на вопрос")
                    tokens = usage.get("completion_tokens", 0)
                    # Модель выдумывает адреса источников (chat_history 193:
                    # `[Раздел ПД №8 ... .pdf](https://example.com/source1)`). Фальшивая
                    # ссылка в инженерном ответе хуже её отсутствия — снимаем разметку,
                    # сохраняя имя документа.
                    if not model_driven_retrieval or not answer.lstrip().startswith(("{", "[")):
                        _known_targets = [
                            str(value)
                            for item in (answer_source_map or ())
                            if isinstance(item, Mapping)
                            for value in item.values()
                            if isinstance(value, str)
                        ]
                        answer, _stripped_links = strip_unsupported_links(answer, _known_targets)
                        if _stripped_links:
                            retrieval_trace["answer_unsupported_links"] = _stripped_links
                            logger.warning(
                                "[CHAT] stripped %s fabricated link(s) from the answer",
                                _stripped_links,
                            )
                    # Модель не знает о потолке и обрывается на полуслове: упор в бюджет
                    # закрываем по границе предложения и помечаем усечение.
                    if generation_budget and int(tokens or 0) >= int(generation_budget):
                        if not model_driven_retrieval:
                            answer = finalize_truncated_answer(answer)
                        retrieval_trace["answer_truncated"] = {
                            "completion_tokens": int(tokens or 0),
                            "generation_budget": int(generation_budget),
                        }
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

                    crag_status = "MODEL_OUTPUT"
                    if token_sink is not None and not model_driven_retrieval:
                        await token_sink({"event": "token", "data": answer})
                    logger.info("[CHAT] model answer accepted unchanged; citation check is trace-only")
                    break

                if model_driven_retrieval:
                    parsed_model_result = parse_model_rag_result(answer)
                    model_result_rows: list[dict[str, Any]] = []
                    model_result_errors: list[str] = []
                    model_result_blocking_errors: list[str] = []
                    if parsed_model_result is not None:
                        answer, model_result_rows = parsed_model_result
                        model_result_rows = withhold_unreferenced_norms(
                            model_result_rows,
                            # Только доставленные карточки: найденное, но не показанное
                            # ничего не подтверждает (аудит Codex 17.09).
                            delivered_cards=delivered_evidence_cards(
                                "\n".join(str(message.get("content") or "") for message in messages),
                                model_evidence_chunks,
                            ),
                            prior_evidence=(portion_state or {}).get('prior_evidence') or (),
                            observed_refs=[str((getattr(chunk, 'meta', {}) or {}).get('model_evidence_ref') or '')
                                           for chunk in model_evidence_chunks],
                        )
                        from proxy.services.smeta_chat_adapter_service import (
                            _smeta_source_row_count,
                        )

                        model_result_errors = validate_model_rag_result_structure(
                            model_result_rows,
                            model_evidence_chunks,
                            # Порция знает своё число строк точно. Счёт по тексту нужен
                            # только там, где порционности нет: на боевой раскладке СКС
                            # он и так возвращает ноль — между наименованием и единицей
                            # у неё стоят артикул и производитель.
                            expected_source_rows=(
                                int(portion_state.get("rows_in_pass") or 0)
                                if portion_state.get("state") == "portion"
                                else _smeta_source_row_count(attachment_context)
                            ),
                        )
                        model_result_blocking_errors = blocking_model_rag_result_errors(
                            model_result_errors
                        )
                        if model_rows_must_belong_to_sheet(portion_state):
                            portion_errors = portion_structure_errors(model_result_rows, portion_state)
                            model_result_errors.extend(portion_errors)
                            model_result_blocking_errors.extend(portion_errors)
                        if model_result_blocking_errors:
                            retrieval_trace["model_result"] = {
                                "schema": "les_model_rag_result_v1",
                                "status": "structural_error",
                                "row_count": len(model_result_rows),
                                "packaged": False,
                                "errors": model_result_errors,
                            }
                        elif model_result_errors:
                            retrieval_trace["model_result"] = {
                                "schema": "les_model_rag_result_v1",
                                "status": "accepted_with_integrity_warning",
                                "row_count": len(model_result_rows),
                                "packaged": False,
                                "warnings": model_result_errors,
                            }
                    else:
                        retrieval_trace["model_result"] = {
                            "schema": "les_model_rag_result_v1",
                            "status": "unstructured",
                            "packaged": False,
                        }
                    feedback_errors = (
                        list(model_result_blocking_errors) if parsed_model_result is not None
                        else ["unstructured_model_result"]
                    )
                    feedback_saved = False
                    if portion_state.get("state") == "portion" and portion_cursors is not None:
                        feedback_saved = _record_structural_feedback(
                            portion_cursors,
                            session_id=str(getattr(req, "session_id", "") or ""),
                            revision=str(portion_state.get("source_revision") or ""),
                            turn_id=str(getattr(req, "turn_id", "") or ""),
                            answer=answer, rows=model_result_rows, errors=feedback_errors,
                            evidence={"source_map": _model_rag_source_map(model_evidence_chunks),
                                      "portion_shown": list(portion_state.get('shown') or [])},
                        )
                    if feedback_errors:
                        retrieval_trace["model_result_notice"] = _model_result_notice(
                            feedback_errors, saved=feedback_saved,
                        )
                    attachment_id = str(getattr(req, "attachment_id", None) or "").strip()
                    packaging_tools = (
                        ["build_lsr_workbook"]
                        if "build_lsr_workbook" in profile_tools
                        else []
                    )
                    closed_anchors = (
                        closed_row_anchors(
                            model_result_rows, portion_state.get("shown") or []
                        )
                        if portion_state.get("state") == "portion"
                        else []
                    )
                    model_result_rows = bind_normative_identity(
                        model_result_rows, chunks=model_evidence_chunks,
                        delivered_cards=delivered_evidence_cards(
                            '\n'.join(str(m.get('content') or '') for m in messages), model_evidence_chunks),
                        packet_text='\n'.join(str(m.get('content') or '') for m in messages),
                        prior_evidence=(portion_state or {}).get('prior_evidence') or ())
                    merged_decisions = merged_pass_decisions(
                        model_result_rows,
                        closed=closed_anchors,
                        portion_state=portion_state,
                    )
                    # Preserve the accepted model result even if delivery or packaging
                    # is cancelled. Binding occurs before the first await; only
                    # the completed model answer is recorded, never a partial token stream.
                    packaging_attempted = False
                    try:
                        if token_sink is not None:
                            await token_sink({"event": "reset", "data": ""})
                            if answer:
                                await token_sink({"event": "token", "data": answer})
                        if (
                            parsed_model_result is not None
                            and model_result_rows
                            and not model_result_blocking_errors
                            and attachment_id
                            and packaging_tools
                            and workbook_tool_executor is not None
                            and canonical_execution_mode is CanonicalRouteMode.ACTIVE
                        ):
                            packaging_attempted = True
                            async def workbook_progress(event: dict[str, Any]) -> None:
                                if token_sink is not None:
                                    await token_sink({"event": "tool_progress", "data": event})

                            packaging_trace: list[dict[str, Any]] = []
                            workbook_files: list[dict[str, str]] = []
                            for packaging_tool in packaging_tools:
                                workbook_call = {
                                    "tool": packaging_tool,
                                    "args": {
                                        "attachment_id": attachment_id,
                                        "question": str(req.question or ""),
                                        # Книга собирается из решений всех проходов, а не
                                        # только последнего: иначе третий проход выдал бы
                                        # книгу на свои двадцать строк, потеряв пятьдесят
                                        # прежних (ревью Codex 10.09).
                                        "decisions": merged_decisions,
                                        **({'review_calculation': True} if packaging_tool == 'build_lsr_workbook' else {}),
                                        # Родословная книги: следующая ревизия знает, чья
                                        # она продолжательница.
                                        "parent_revision_id": (
                                            portion_state.get("artifact_revision_id") or None
                                        ),
                                    },
                                }
                                try:
                                    workbook_payload = await workbook_tool_executor(
                                        workbook_call,
                                        {
                                            "session_id": str(req.session_id or ""),
                                            "question": str(req.question or ""),
                                            "dataset_ids": [str(item) for item in _dataset_ids],
                                            "project_id": getattr(req, "project_id", None),
                                            "attachment_id": attachment_id,
                                            "profile_revision_id": str(
                                                (profile_snapshot or {}).get("revision_id") or ""
                                            ),
                                            "model_identity": str(
                                                getattr(
                                                    getattr(active_model_result, "connection", None),
                                                    "model_id",
                                                    "",
                                                )
                                                or llm_model
                                            ),
                                            "model_preset": execution_preset.preset_id,
                                            "document_price_basis": document_price_basis,
                                            "source_revision": document_source_revision,
                                            "source_attachment_sha256": document_source_attachment_sha256,
                                        },
                                        workbook_progress,
                                    )
                                    safe_payload = safe_workbook_history_projection(workbook_payload)
                                    harvested = harvest_workbook_tool_result(safe_payload)
                                    packaging_trace.append({
                                        "tool": packaging_tool,
                                        "status": str(safe_payload.get("status") or "empty"),
                                        "code": str(safe_payload.get("code") or ""),
                                    })
                                    if not harvested:
                                        continue
                                    artifact = (
                                        harvested.get("artifact")
                                        if isinstance(harvested.get("artifact"), dict)
                                        else {}
                                    )
                                    if artifact.get("download_url"):
                                        kind = str(artifact.get("artifact_kind") or "").strip()
                                        if kind not in {"lsr_workbook", "vor_workbook"}:
                                            kind = (
                                                "vor_workbook"
                                                if packaging_tool == "build_vor_workbook"
                                                else "lsr_workbook"
                                            )
                                        workbook_files.append({
                                            "filename": _chat_workbook_filename(
                                                artifact.get("filename"),
                                                artifact_kind=kind,
                                                tool=packaging_tool,
                                            ),
                                            "download_url": str(artifact["download_url"]),
                                            "artifact_kind": kind,
                                        })
                                    if packaging_tool == "build_lsr_workbook" or not workbook_chat_meta:
                                        workbook_chat_meta = harvested
                                except Exception as packaging_error:  # noqa: BLE001 - keep model answer visible
                                    logger.exception(
                                        "[WORKBOOK] post-model packaging failed: %s",
                                        type(packaging_error).__name__,
                                    )
                                    packaging_trace.append({
                                        "tool": packaging_tool,
                                        "status": "error",
                                        "error_type": type(packaging_error).__name__,
                                    })
                            if workbook_chat_meta:
                                artifact_meta = workbook_chat_meta.get("artifact")
                                if isinstance(artifact_meta, dict):
                                    artifact_meta["draft_rows"] = compact_estimator_draft_rows(
                                        model_result_rows
                                    )
                                    if workbook_files:
                                        artifact_meta["files"] = workbook_files
                                        artifact_meta.setdefault(
                                            "filename", workbook_files[0]["filename"]
                                        )
                            retrieval_trace["model_result"] = {
                                "schema": "les_model_rag_result_v1",
                                "status": "accepted_unchanged",
                                "row_count": len(model_result_rows),
                                "packaging": packaging_trace,
                                "warnings": model_result_errors,
                            }

                        if model_driven_retrieval and parsed_model_result is not None:
                            retrieval_trace["smeta_funnel"] = smeta_selection_funnel(
                                query_hits=model_rag_query_hits,
                                shown_chunks=model_evidence_chunks,
                                rows=model_result_rows,
                                rejected=rejected_row_reasons(workbook_chat_meta),
                                bound_rows=workbook_bound_rows(workbook_chat_meta),
                                includes_prior_rows=bool(portion_state.get("prior_decisions")),
                                row_statuses=workbook_row_statuses(workbook_chat_meta),
                            )
                    finally:
                        if (portion_state.get("state") == "portion" and portion_cursors is not None
                                and parsed_model_result is not None and not model_result_blocking_errors):
                            # Решение модели и состояние упаковки — разные вещи. Строка,
                            # для которой норма выбрана, остаётся решённой, даже если книга
                            # не собралась: иначе модель гоняли бы по уже разобранным
                            # строкам из-за занятого диска (ревью Codex 11.09). Несобранная
                            # книга видна по расхождению отпечатков решений и артефакта —
                            # её пересоберёт следующий запрос, ещё до обращения к модели.
                            packaging_failed = packaging_attempted and not workbook_chat_meta
                            if packaging_failed:
                                retrieval_trace["smeta_portion_packaging_failed"] = True
                            # Проход засчитывается по решениям, а не по показанным строкам:
                            # позиция без карточек вернётся в следующий проход.
                            built_revision = _workbook_revision_id(workbook_chat_meta)
                            record_portion_pass(
                                portion_cursors,
                                session_id=str(getattr(req, "session_id", "") or ""),
                                portion_state=portion_state,
                                rows=model_result_rows,
                                closed=closed_anchors,
                                artifact_revision_id=built_revision,
                                artifact_decisions_revision=(
                                    _portion_decisions_revision(merged_decisions, document_price_basis=document_price_basis)
                                    if built_revision else None
                                ),
                                rejected=rejected_row_reasons(workbook_chat_meta),
                                row_statuses=workbook_row_statuses(workbook_chat_meta),
                                evidence=evidence_snapshot(
                                    model_result_rows, model_evidence_chunks,
                                    delivered_cards=delivered_evidence_cards(
                                        "\n".join(str(message.get('content') or '') for message in messages),
                                        model_evidence_chunks,
                                    ),
                                ),
                                calculation_receipts=(workbook_chat_meta.get('workbook_diagnostics') or {}).get('row_calculation') or [],
                                pass_id=str(getattr(req, "turn_id", "") or "").strip(),
                                trace=retrieval_trace,
                            )
                            if retrieval_trace.get("smeta_portion_recorded"):
                                portion_state["completed"] = int(
                                    retrieval_trace.get("smeta_portion_decided") or 0
                                )
                                portion_state["exhausted"] = int(
                                    retrieval_trace.get("smeta_portion_unresolved") or 0
                                )
                                portion_state["pending"] = max(
                                    0, int(portion_state.get("total") or 0)
                                    - portion_state["completed"],
                                )
                try:
                    from proxy.services.evidence_packet_service import verify_answer_source_labels

                    citation_check = verify_answer_source_labels(answer, answer_source_map)
                    retrieval_trace["citation_check"] = citation_check
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
                elif crag_status in {"UNVALIDATED", "MODEL_OUTPUT"}:
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
                tool_candidate_counts = []
                for tool_result in tool_results_for_model:
                    tool_trace = (
                        tool_result.get("trace")
                        if isinstance(tool_result, dict)
                        and isinstance(tool_result.get("trace"), dict)
                        else {}
                    )
                    selection = (
                        tool_trace.get("candidate_selection")
                        if isinstance(tool_trace.get("candidate_selection"), dict)
                        else {}
                    )
                    if selection.get("found_count") is not None:
                        tool_candidate_counts.append(int(selection["found_count"]))
                retrieval_selection = (
                    retrieval_trace.get("candidate_selection")
                    if isinstance(retrieval_trace.get("candidate_selection"), dict)
                    else {}
                )
                found_count = (
                    sum(tool_candidate_counts)
                    if tool_candidate_counts
                    else int(
                        retrieval_selection.get("found_count")
                        or len(model_evidence_chunks)
                    )
                )
                source_counts = evidence_counts(
                    answer=answer,
                    source_map=answer_source_map,
                    found_count=found_count,
                )
                retrieval_trace["source_counts"] = source_counts
                retrieval_trace["source_map"] = answer_source_map
                evidence_manifest = build_evidence_manifest(
                    query=str(req.question or ""),
                    scope={
                        "dataset_ids": [str(item) for item in _dataset_ids],
                        "dataset_filter": str(effective_dataset_filter or ""),
                        "model_queries": list(
                            (retrieval_trace.get("tool_loop") or {}).get("model_queries")
                            or []
                        ),
                        "selected_sources_only": bool(
                            getattr(req, "selected_sources_only", False)
                        ),
                    },
                    chunks=model_evidence_chunks,
                    answer=answer,
                )
                retrieval_trace["evidence_manifest"] = evidence_manifest
                state.chat_metrics.setdefault("latency_phases", []).append(phases)
                logger.info("[METRICS] phases=%s", phases)
                for key in ("latency_search", "latency_gen", "tokens", "latency_phases"):
                    state.chat_metrics[key] = state.chat_metrics[key][-100:]

                history_chunks = model_evidence_chunks if model_evidence_chunks else chunks
                sources_list = source_names(history_chunks)
                if project_inventory_prompt:
                    sources_list = [*sources_list, "Опись файлов датасета (MetaDB documents)"]
                source_dataset_ids = _dataset_ids_from_chunks(history_chunks)
                source_dataset_names = _names_for_dataset_ids(source_dataset_ids, dataset_name_by_id)
                source_scope = {
                    "requested": [
                        str(item) for item in (getattr(req, "dataset_ids", None) or _dataset_ids)
                    ],
                    "resolved": [str(item) for item in (_dataset_ids or [])],
                    "used": source_dataset_ids,
                    "used_names": source_dataset_names,
                }
                retrieval_trace["source_scope"] = source_scope
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
                        artifact=(workbook_chat_meta.get("artifact") or None),
                        cache_type=cache_marker,
                        validation_enabled=use_validation,
                    )
                except Exception as db_err:
                    logger.warning("[CHAT] History save error: %s", db_err)

                if use_semantic_cache and not primary_document_pricing and cache_embedding and cache_scope and crag_status == "VERIFIED":
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
                elif use_semantic_cache and not primary_document_pricing and cache_scope and crag_status == "UNVALIDATED":
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
                    "source_excerpts": source_excerpts(history_chunks),
                    "source_map": answer_source_map,
                    "evidence_packet": final_evidence_packet,
                    "latency_phases": phases,
                    "class_suggestions": class_suggestions,
                    "versions": _version_stamp(),
                    "numeric_unverified": _num_unverified,
                    "source_scope": source_scope,
                    "source_counts": source_counts,
                }
                if active_model_result is not None:
                    response["model_connection"] = active_model_result.public_connection_payload()
                    response["model_connection"]["pending_tool_calls"] = active_pending_tool_calls
                if not workbook_chat_meta and portion_state.get("rebuilt_workbook"):
                    # Книгу пересобрали до обращения к модели — она и уходит в ответ.
                    workbook_chat_meta = dict(portion_state["rebuilt_workbook"])
                if workbook_chat_meta:
                    response.update(workbook_chat_meta)
                if retrieval_trace.get("model_result_notice"):
                    response["model_result_notice"] = dict(retrieval_trace["model_result_notice"])
                if portion_state.get("state") == "portion" and portion_state.get("pending"):
                    # Ведомость не закрыта — скрепку надо сохранить, иначе следующее
                    # «продолжай» придёт без вложения и продолжать будет нечего:
                    # интерфейс держит файл ровно столько, сколько просит сервер.
                    response.setdefault("attachment_retry", {})
                    attachment_id_for_retry = str(
                        getattr(req, "attachment_id", "") or ""
                    ).strip()
                    if attachment_id_for_retry:
                        response["attachment_retry"] = {
                            **response["attachment_retry"],
                            "attachment_id": attachment_id_for_retry,
                            "id": attachment_id_for_retry,
                            "preserved": True,
                        }
                    response["smeta_portion"] = {
                        "schema": "les.smeta.portion-progress.v2",
                        "pass_no": portion_state.get("pass_no"),
                        "rows_in_pass": portion_state.get("rows_in_pass"),
                        "remaining": portion_state.get("pending"),
                        "total": portion_state.get("total"),
                        # Решено и «больше не спрашиваем» — разные числа, и смешивать их
                        # в отчёте нельзя: исчерпанный лимит попыток остаётся нерешённой
                        # позицией (ревью Codex 11.09).
                        "decided": portion_state.get("completed"),
                        "unresolved": portion_state.get("exhausted"),
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
            raise HTTPException(504, "Истёк таймаут назначенной модели — проверь подключение или повтори запрос.")
        except ModelTransportError as e:
            logger.error("[CHAT] ASSIGNED MODEL ERROR: %s", e)
            raise HTTPException(502, f"Назначенная модель не ответила: {e}")
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
