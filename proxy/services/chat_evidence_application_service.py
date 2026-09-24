"""General evidence/RAG application execution extracted from the HTTP router.

The caller resolves request scope and deterministic tools first. This service owns the
unchanged retrieval -> context/evidence -> model -> sources/trace execution branch.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field, replace
from itertools import combinations
from pathlib import Path
from backend.runtime_paths import mutable_path
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
from proxy.services.answer_form_service import apply_response_length
from proxy.services.cad_bim_highlight import extract_highlight, set_highlight
from proxy.services.canonical_route_service import (
    BoundModelChatRunner,
    CanonicalRouteMode,
    canonical_route_trace_payload,
    one_model_decision_from_calls,
    resolve_canonical_route,
)
from proxy.services.attachment_source_catalog_service import (
    AttachmentSourceCatalog,
    catalog_sheet_pack_lines,
    catalog_sheet_work_locators,
    catalog_work_sheet_names,
    compare_model_row_to_catalog,
    coverage_errors,
    load_catalog_from_attachment_id,
    locators_missing_from_text,
    sheet_coverage_from_missing,
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
from proxy.services.chat_profile_service import effective_retrieval_policy
from proxy.services.retrieval_service import required_reranker_policy, retrieve_chat_chunks
from proxy.services.runtime_admission import (
    acquire_generation_slot,
    generation_semaphore,
    generation_slot_timeout_seconds,
)
from proxy.services.saferag_service import (
    build_validation_context,
    concentrate_sources,
    rank_chunks_for_question,
    source_names,
)
from proxy.services.table_query_service import maybe_answer_table_query
from proxy.services.memory_port import get_memory_port
from proxy.services.workbook_research_job_service import WorkbookResearchJobService
from proxy.services.lsr_result_readiness_service import (
    build_lsr_result_readiness,
    format_lsr_readiness_notice,
)
from proxy.services.lsr_norm_quality_gate_service import (
    LsrResearchRoundResult,
    aggregate_norms_status,
    build_blind_review_evidence_items,
    invented_source_row,
    lsr_coefficient_instruction,
    lsr_format_retry_instruction,
    lsr_research_query_instruction,
    lsr_research_result_evidence,
    lsr_result_table_instruction,
    lsr_verifier_format_retry_instruction,
    lsr_verifier_instruction,
    mark_research_exhausted,
    merge_format_retry_rows,
    merge_quality_gated_rows,
    prepare_selection_row,
    rejected_codes_clause,
    row_is_quality_terminal,
    run_coefficient_review,
    run_lsr_norm_quality_loop,
    verifier_generation_tokens,
)
from proxy.services.llm_transport_profile_service import (
    assistant_delta_text,
    resolve_connection_execution_profile,
    resolve_transport_execution_profile,
)


_WORKBOOK_TOOL_NAMES = frozenset({"build_lsr_workbook", "build_vor_workbook"})


_VOR_INTENT_TERMS = (
    "вор", "ведомость объ", "ведомость работ", "spec to bor", "spec_to_bor",
)
_LSR_INTENT_TERMS = ("лср", "смет", "локальн")


def workbook_artifact_intent(question: str) -> str:
    """Classify the artifact the operator's own words ask to produce.

    This is intent, not a filename rule and not a norm choice. A сметa/ЛСР noun
    wins over a ВОР noun so "собери ЛСР из ВОР" stays the priced route; a bare
    ВОР/ведомость request means the row-preserving route. Returns "vor", "lsr"
    or "both" (unspecified -> leave the decision to the model).
    """
    q = (question or "").casefold()
    if any(term in q for term in _LSR_INTENT_TERMS):
        return "lsr"
    if any(term in q for term in _VOR_INTENT_TERMS):
        return "vor"
    return "both"


def prioritize_workbook_tools(
    profile_tools: Sequence[str],
    *,
    workbook_phase: bool,
    question: str = "",
) -> list[str]:
    """Keep attachment-bound workbook choices inside a small-model shortlist.

    When the operator explicitly names the target artifact, only that workbook
    tool stays visible for the turn: a ВОР/ведомость request must not be answered
    with a priced ЛСР (materials silently becoming costed works), while a
    ЛСР/смета request is the priced route. This still never executes a tool on the
    model's behalf and never selects a norm; an unspecified request keeps both.
    """
    tools = [str(name) for name in profile_tools if str(name).strip()]
    if not workbook_phase:
        return tools
    hidden = {
        "vor": "build_lsr_workbook",
        "lsr": "build_vor_workbook",
    }.get(workbook_artifact_intent(question))
    if hidden:
        tools = [name for name in tools if name != hidden]
    workbook = [name for name in tools if name in _WORKBOOK_TOOL_NAMES]
    other = [name for name in tools if name not in _WORKBOOK_TOOL_NAMES]
    return workbook + other


def workbook_packaging_tool(profile_tools: Sequence[str], question: str) -> list[str]:
    """Choose the packaging tool for the sheet-pass result by intent.

    The operator's own words decide the artifact, checked before any profile
    list membership: a ВОР/ведомость request is packaged as a row-preserving
    ВОР even when an un-narrowed profile list still contains
    build_lsr_workbook (the sheet-pass and durable-resume routes never run
    prioritize_workbook_tools), while a ЛСР/смета request keeps the priced
    route. An unspecified request defaults to the priced packager only when it
    is available. Returns at most one tool name; never executes a tool and
    never selects a norm.
    """
    tools = set(profile_tools)
    intent = workbook_artifact_intent(question)
    if intent == "vor":
        # The operator named a ВОР: package the row-preserving ВОР even when an
        # un-narrowed profile list still carries build_lsr_workbook (sheet-pass
        # and durable-resume routes). A material line must not silently become a
        # priced монтажная работа.
        return ["build_vor_workbook"] if "build_vor_workbook" in tools else []
    if intent == "lsr":
        return ["build_lsr_workbook"] if "build_lsr_workbook" in tools else []
    # Unspecified ("both"): keep the priced route when it is actually available.
    if "build_lsr_workbook" in tools:
        return ["build_lsr_workbook"]
    return []


def workbook_packaging_args(
    *,
    packaging_tool: str,
    attachment_id: str,
    question: str,
    decisions: Sequence[Mapping[str, Any]],
    operator_overrides: Mapping[str, Any] | None,
    draft: bool = False,
    parent_revision_id: str | None = None,
) -> dict[str, Any]:
    """Build contract-valid args for the sheet-pass auto-packaging call.

    Both workbook packagers receive the row-preserving decisions; only the
    priced ЛСР tool consumes operator overlays. The ВОР contract declares
    additionalProperties False without confirmed_data, so sending the overlay
    there fails schema validation (TOOL_SCHEMA_INVALID) and drops the artifact.
    ``draft`` and ``parent_revision_id`` are emitted only when set: an ordinary
    final call keeps the identity it had before durable packaging existed, a
    paused intermediate is explicitly marked, and a terminal repack continues
    the same revision chain.
    """
    args: dict[str, Any] = {
        "attachment_id": attachment_id,
        "question": question,
        "decisions": [dict(item) for item in decisions or []],
    }
    if packaging_tool == "build_lsr_workbook":
        args["confirmed_data"] = dict(operator_overrides or {})
    if draft:
        args["draft"] = True
    if parent_revision_id:
        args["parent_revision_id"] = str(parent_revision_id)
    return args


# Events that can change the durable decision set a packaged workbook is built
# from.  Terminal bookkeeping is deliberately absent: every pass that re-finishes
# an already complete job appends another ``complete`` event *before* it packages,
# so treating it as a change made a re-open of a finished job write one more copy
# of the same document (live regression on job wrj_2b0fff82, events 38-41).
PACKAGING_DECISION_CHANGE_EVENTS = frozenset({
    "packet_checkpoint",
    "rows_replaced",
    "decision_revision",
    "locators_reopened",
    "operator_overrides",
})


def workbook_packaging_lineage(
    events: Sequence[Mapping[str, Any]],
    *,
    durable_decisions: bool,
) -> tuple[dict[str, str], dict[str, str | None]]:
    """Revision lineage for durable workbook packaging.

    ``parents`` is the last revision each packager wrote for this job, so a new
    decision set continues the same downloadable document. ``settled`` marks a
    packager whose last revision is a final one that was written after the last
    event able to change the saved durable decisions: replaying that call with
    the parent it built on (recorded in the event, or read back from the
    packaging chain for events written before the parent was recorded) keeps the
    existing call identity (which already covers ``decisions``), so opening a
    finished job again serves the same file instead of duplicating it.
    """

    parents: dict[str, str] = {}
    settled: dict[str, str | None] = {}
    last_change_sequence = max(
        (
            int(event.get("sequence") or 0)
            for event in events
            if str(event.get("event_type") or "") in PACKAGING_DECISION_CHANGE_EVENTS
        ),
        default=0,
    )
    for event in events:
        if str(event.get("event_type") or "") != "workbook_packaged":
            continue
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            continue
        tool = str(payload.get("tool") or "")
        revision_id = str(payload.get("revision_id") or "")
        if not tool or not revision_id:
            continue
        built_on = parents.get(tool)
        parents[tool] = revision_id
        if (
            durable_decisions
            and not bool(payload.get("draft"))
            and int(event.get("sequence") or 0) >= last_change_sequence
        ):
            settled[tool] = str(payload.get("parent_revision_id") or "") or built_on
    return parents, settled


def terminal_research_packaging_rows(
    research_job: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Return the durable accepted decisions of a completed research job.

    A terminal job's saved set is authoritative: the final workbook revision
    must be packaged from the full saved decisions even when the per-call
    re-validation of the answer reports integrity noise. The decisions are
    forwarded unchanged; no model call happens here. Returns nothing for a
    paused/running job or when durability is unavailable, so an intermediate
    file can never masquerade as the finished document.
    """
    if not isinstance(research_job, Mapping):
        return []
    if str(research_job.get("status") or "") != "complete":
        return []
    return [
        dict(item)
        for item in (research_job.get("accepted_rows") or ())
        if isinstance(item, Mapping)
    ]


def model_answer_timeout_seconds() -> float:
    """One end-to-end window for an explicitly assigned answer connection.

    Mirrors model_connection_timeout() in routers/chat.py and the registered
    LES_MODEL_CONNECTION_TIMEOUT_SEC runtime-config knob. The agent-loop client
    previously hardcoded 300s, so a remote-model latency spike aborted a live
    workbook pass with ReadTimeout/502 and the operator setting changed nothing.
    """
    try:
        return max(1.0, float(os.getenv("LES_MODEL_CONNECTION_TIMEOUT_SEC", "300")))
    except (TypeError, ValueError):
        return 300.0



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
    ModelResearchToolService,
    retrieve_smeta_norm_cards,
)
from proxy.services.source_locator_service import evidence_counts, source_map_item
from proxy.services.chat_evidence_manifest_service import build_evidence_manifest
from proxy.services.chat_capability_scope_service import filter_profile_tools
from proxy.services.typed_memory_projection_service import (
    MemoryLimits,
    project_memory,
    resolve_session_memory_scope,
)
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

    safe = selected(
        result,
        (
            "schema", "tool", "status", "code", "pricing_status", "norms_status",
            "calculated_positions", "confirmed_amount", "preliminary_amount",
        ),
    )
    if safe.get("status") in {"complete", "partial"}:
        for field in ("missing", "blockers"):
            values = result.get(field)
            safe[field] = [str(value)[:500] for value in values[:100]] if isinstance(values, list) else []
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
    return {
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
        "workbook_status": str(result.get("status") or ""),
        "pricing_status": str(result.get("pricing_status") or ""),
        "norms_status": str(result.get("norms_status") or ""),
        "missing": list(result.get("missing") or []),
        "price_gaps": list(result.get("price_gaps") or []),
        "price_basis": dict(result.get("price_basis") or {}),
        "blockers": list(result.get("blockers") or []),
    }


async def execute_workbook_with_bounded_retry(
    executor,
    call: dict[str, Any],
    request_context: dict[str, Any],
    progress_sink,
    *,
    max_attempts: int = 2,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Retry only the idempotent packaging step, preserving model decisions."""

    traces: list[dict[str, Any]] = []
    safe_payload: dict[str, Any] = {}
    for attempt in range(1, max(1, int(max_attempts)) + 1):
        payload = await executor(call, request_context, progress_sink)
        safe_payload = safe_workbook_history_projection(payload)
        checkpoint = (
            dict(safe_payload.get("checkpoint") or {})
            if isinstance(safe_payload.get("checkpoint"), dict)
            else {}
        )
        trace = {
            "tool": str(call.get("tool") or ""),
            "attempt": attempt,
            "status": str(safe_payload.get("status") or "empty"),
            "code": str(safe_payload.get("code") or ""),
        }
        if checkpoint.get("checkpoint_id"):
            trace["checkpoint_id"] = str(checkpoint["checkpoint_id"])
            trace["resumed"] = bool(checkpoint.get("resumed"))
        traces.append(trace)
        if safe_payload.get("status") != "failed":
            break
    return safe_payload, traces


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


def workspace_note_objects(
    candidates: Sequence[ContextCandidate], *, registered: bool,
) -> tuple[ContextObject, ...]:
    """Explicit workspace notes remain optional advisory context, never evidence."""
    if not registered:
        return ()
    return tuple(
        item for candidate in candidates
        if candidate.kind == ContextKind.WORKING_MEMORY
        for item in candidate.objects if item.object_id.startswith("note:")
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
    """Expose exact model-visible evidence while keeping private prompt/memory redacted."""
    visible_kinds = {ContextKind.EVIDENCE, ContextKind.SOURCE_MAP}

    def section_trace(section) -> dict[str, Any]:
        item = {
            "kind": section.kind.value,
            "items": len(section.objects),
            "tokens": section.token_count,
            "object_ids": list(section.object_ids),
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


TABULAR_ATTACHMENT_ESTIMATOR_BRIDGE = "tabular_attachment_estimator_path_v1"
_TABULAR_ESTIMATOR_TOOLS = ("search_sources", "read_source", "build_lsr_workbook")
_TABULAR_LSR_VOLUME_INSTRUCTION = (
    "Пустые колонки Материал/Работа/Итого во вложенной ведомости — это объёмы, "
    "не запрет собирать таблицу строк. Не отказывайся из‑за пустых цен и не проси "
    "прайс вместо таблицы. Цену считает код только после выбранной нормы. "
    "В таблице нужны source_row, row_role, work_row, title, unit, quantity, norm_code, "
    "norm_status, open_gap, evidence_refs Qx.Hy. Поля supply_kind, calc_quantity, "
    "conversion_factor, conversion_source добавляй только когда применяются. "
    "quantity — исходное количество; расчётное не подменяет его. Перевод единиц "
    "только с conversion_source. Отсутствие цены не делает строку MISSING."
    " Если исходник — спецификация изделий, самостоятельно определи по задаче "
    "и источникам необходимые монтажные работы, их объёмы и нормы; название "
    "изделия не заменяет работу. Работу можно обосновать исходным source_row, "
    "даже если монтаж не записан отдельной строкой исходника. Не назначай "
    "отдельную работу каждому изделию автоматически: учитывай состав нормы "
    "и избегай двойного учёта. work_row ресурса ссылается на source_row "
    "реально возвращённой работы с row_role=work, а не на шифр или материал. "
    "Выбранный по карточке шифр и Qx.Hy перенеси в norm_code и evidence_refs "
    "итоговой строки; упоминания только в пояснении недостаточно. Если "
    "работу нельзя определить, верни unresolved с конкретным open_gap."
)
_MODEL_RAG_QUERY_INSTRUCTION = (
    "Прочитай приложенный материал целиком. Сформулируй поисковые "
    "запросы к выбранным датасетам, необходимые для подбора evidence "
    "по всем фактическим строкам исходного материала. Число запросов "
    "определяешь ты; фиксированного лимита нет. В запросах сохраняй язык "
    "и профессиональную терминологию исходных строк; не переводи и не "
    "транслитерируй их. Сейчас не выбирай нормы "
    "и не отвечай по существу — верни только сами поисковые запросы, "
    "каждый с новой строки. Без обращения к собеседнику, без описания "
    "плана и без ожидания подтверждения."
)
_MODEL_RAG_QUERY_REPAIR_INSTRUCTION = (
    "Предыдущий ответ не содержал поисковых строк. Верни только поисковые "
    "запросы к датасетам, каждый с новой строки. Без обращения, плана и "
    "подтверждения. Нормы пока не выбирай."
)
_MODEL_RAG_QUERY_VOLUME_HINT = (
    "Пустые ценовые колонки исходника не ищи. Запросы — по работам и "
    "измерителям строк, не по прайсу."
)
_ROW_PACKET_MIN = 8
_ROW_PACKET_TARGET = 10
_ROW_PACKET_MAX = 12
_ROW_PACKET_MAX_ATTEMPTS = 2


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


def profile_uses_tabular_estimator_path(
    profile_snapshot: dict[str, Any] | None,
) -> bool:
    """True when this turn overlays estimator evidence because of a table file."""

    snapshot = profile_snapshot if isinstance(profile_snapshot, dict) else {}
    bridges = snapshot.get("effective_capability_bridges") or []
    return bool(snapshot.get("tabular_estimator_path")) or (
        TABULAR_ATTACHMENT_ESTIMATOR_BRIDGE in bridges
        if isinstance(bridges, list)
        else False
    )


def profile_uses_smeta_norm_retrieval(
    profile_snapshot: dict[str, Any] | None,
) -> bool:
    """Route estimator and tabular-attachment turns to the normative-card index."""

    snapshot = profile_snapshot if isinstance(profile_snapshot, dict) else {}
    return (
        str(snapshot.get("mode") or "").strip().casefold() == "estimator"
        or profile_uses_tabular_estimator_path(snapshot)
    )


def attachment_enables_tabular_estimator_path(
    source_catalog: AttachmentSourceCatalog | None,
) -> bool:
    """A loaded sheet catalog is the only signal; the question text is not."""

    return source_catalog is not None and bool(source_catalog.rows)


def overlay_tabular_estimator_snapshot(
    profile_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    """Enable model-authored RAG and LSR packaging for this turn only.

    Saved UI mode and the immutable profile revision are not rewritten. The
    overlay is the table file, not a keyword in the question.
    """

    snapshot = dict(profile_snapshot or {})
    rag_policy = dict(snapshot.get("rag_policy") or {})
    rag_policy["model_authored_initial_query"] = True
    modules = [
        str(item) for item in (rag_policy.get("system_datasets") or []) if str(item)
    ]
    if "smeta" not in modules:
        modules.append("smeta")
    rag_policy["system_datasets"] = modules
    snapshot["rag_policy"] = rag_policy
    tools = [str(name) for name in (snapshot.get("tools") or []) if str(name).strip()]
    for name in _TABULAR_ESTIMATOR_TOOLS:
        if name not in tools:
            tools.append(name)
    snapshot["tools"] = tools
    bridges = [
        str(item)
        for item in (snapshot.get("effective_capability_bridges") or [])
        if str(item)
    ]
    if TABULAR_ATTACHMENT_ESTIMATOR_BRIDGE not in bridges:
        bridges.append(TABULAR_ATTACHMENT_ESTIMATOR_BRIDGE)
    snapshot["effective_capability_bridges"] = bridges
    snapshot["tabular_estimator_path"] = True
    return snapshot


def bind_tabular_estimator_profile(
    profile_snapshot: dict[str, Any] | None,
    *,
    attachment_id: str = "",
    source_catalog: AttachmentSourceCatalog | None = None,
) -> tuple[dict[str, Any], AttachmentSourceCatalog | None, bool]:
    """Load the attachment catalog and overlay estimator evidence for this request."""

    catalog = source_catalog
    if catalog is None:
        catalog = load_catalog_from_attachment_id(str(attachment_id or ""))
    snapshot = dict(profile_snapshot or {})
    if not attachment_enables_tabular_estimator_path(catalog):
        return snapshot, catalog, False
    return overlay_tabular_estimator_snapshot(snapshot), catalog, True


def model_rag_query_instruction(profile_snapshot: dict[str, Any] | None) -> str:
    """Search-query call contract; empty VOR prices are not a price-list search."""

    parts = [_MODEL_RAG_QUERY_INSTRUCTION]
    snapshot = profile_snapshot if isinstance(profile_snapshot, dict) else {}
    if (
        str(snapshot.get("mode") or "").strip().casefold() == "estimator"
        or profile_uses_tabular_estimator_path(snapshot)
    ):
        parts.append(_MODEL_RAG_QUERY_VOLUME_HINT)
    return "\n\n".join(parts)


def sheet_pass_should_run(
    catalog: AttachmentSourceCatalog | None,
    *,
    tabular_estimator_bound: bool,
    model_driven: bool,
) -> bool:
    """Same packet order for small and large tabular sources: queries → sources → decisions."""

    if not tabular_estimator_bound or not model_driven or catalog is None:
        return False
    names = catalog_work_sheet_names(catalog)
    if not names:
        return False
    return bool(catalog.work_locators())


def sheet_pass_query_instruction(
    profile_snapshot: dict[str, Any] | None,
    *,
    sheet: str,
    sheet_index: int,
    sheet_count: int,
    research_round: int = 0,
) -> str:
    extra = ""
    if research_round > 0:
        extra = "\n" + lsr_research_query_instruction(research_round)
    return (
        model_rag_query_instruction(profile_snapshot)
        + f"\nСейчас только лист «{sheet}» ({sheet_index}/{sheet_count}). "
        "Другие листы манифеста будут отдельными шагами; не составляй запросы по ним."
        + extra
    )


def sheet_pass_question_tail(
    question: str,
    *,
    sheet: str,
    sheet_index: int,
    sheet_count: int,
    remaining_work: Sequence[str] | None = None,
) -> str:
    remaining = [str(item).strip() for item in (remaining_work or ()) if str(item).strip()]
    remainder = ""
    if remaining:
        preview = ", ".join(remaining[:40])
        extra = f" и ещё {len(remaining) - 40}" if len(remaining) > 40 else ""
        remainder = f" Остались только строки: {preview}{extra}."
    sheet_clause = (
        f"Вопрос: {question}\n\n"
        "/no_think\n"
        "Дай итоговый инженерный ответ. Не выдумывай факты и используй только существующие "
        "номера [Источник N]. Если материалов недостаточно, отдели это от подтверждённых выводов."
        f"\nСейчас только лист «{sheet}» ({sheet_index}/{sheet_count}). "
        "Дай таблицу по всем строкам ЭТОГО листа исходного ВОР. "
        "Не обрабатывай другие листы манифеста. "
    )
    remaining_clause = (
        remainder
        + " Ответ должен вместить все строки текущего листа: без вводного обзора "
        "и итоговых рекомендаций, кратко по одной строке ВОР."
    )
    return lsr_result_table_instruction(
        sheet_clause=sheet_clause,
        remaining_clause=remaining_clause,
    )


def cited_source_row_keys(
    rows: Sequence[Mapping[str, Any]],
    catalog: AttachmentSourceCatalog | None = None,
) -> set[str]:
    keys: set[str] = set()
    for row in rows:
        raw = row.get("source_row")
        if raw in (None, ""):
            continue
        keys.add(str(raw).strip())
        if catalog is not None:
            found = catalog.lookup(raw)
            if found is not None:
                keys.add(found.locator)
    return keys


def _source_locator_aliases(
    raw: Any,
    catalog: AttachmentSourceCatalog | None = None,
) -> set[str]:
    aliases = {str(raw).strip()} if raw not in (None, "") else set()
    if catalog is not None and raw not in (None, ""):
        found = catalog.lookup(raw)
        if found is not None:
            aliases.add(found.locator)
    return {item for item in aliases if item}


def _decision_role_key(row: Mapping[str, Any]) -> str:
    """Stable role for merge/duplicate identity. Prefer authored row_role."""

    from proxy.services.lsr_source_coverage_service import inferred_row_role

    return inferred_row_role(row) or "work"


def _decision_identity_sha(row: Mapping[str, Any]) -> str:
    """Content fingerprint of one decision, identity bookkeeping excluded."""

    from proxy.services.workbook_research_job_service import _decision_content_sha

    return _decision_content_sha(row)


def merge_model_rag_rows(
    existing: Sequence[Mapping[str, Any]],
    incoming: Sequence[Mapping[str, Any]],
    catalog: AttachmentSourceCatalog | None = None,
) -> list[dict[str, Any]]:
    """Decision identity wins: operation_id first, else locator+role+content.

    A specification line may legally carry several distinct operations on the
    same locator; those are different decisions, not duplicates. A redelivered
    identical packet is the same decision again and never enters twice. Code
    does not rewrite cells and does not fuse operations by title.
    """

    merged = [dict(row) for row in existing if isinstance(row, Mapping)]
    seen_ops: set[str] = set()
    seen_keys: set[tuple[str, str, str]] = set()
    # Index rows for in-place volatile-field refresh when a redelivery carries
    # newer note / evidence_refs / status. Directive 2.1: those updates must
    # not spawn a new operation but must not be silently discarded either.
    by_op: dict[str, dict[str, Any]] = {}
    by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in merged:
        op = str(row.get("operation_id") or "").strip()
        if op:
            seen_ops.add(op)
            by_op[op] = row
        role = _decision_role_key(row)
        digest = _decision_identity_sha(row)
        for alias in _source_locator_aliases(row.get("source_row"), catalog):
            key = (alias, role, digest)
            seen_keys.add(key)
            by_key.setdefault(key, row)
    _volatile_refresh = ("note", "evidence_refs", "status")
    for row in incoming:
        if not isinstance(row, Mapping):
            continue
        payload = dict(row)
        raw = payload.get("source_row")
        if raw in (None, ""):
            continue
        op = str(payload.get("operation_id") or "").strip()
        role = _decision_role_key(payload)
        digest = _decision_identity_sha(payload)
        aliases = _source_locator_aliases(raw, catalog)
        target: dict[str, Any] | None = None
        if op and op in seen_ops:
            target = by_op.get(op)
        elif not op:
            for alias in aliases:
                candidate = by_key.get((alias, role, digest))
                if candidate is not None:
                    target = candidate
                    break
        if target is not None:
            # Same decision, refresh volatile metadata only. Identity, quantity,
            # unit, norm_code, title and locator stay as the first-authority.
            for field in _volatile_refresh:
                if field in payload:
                    target[field] = payload[field]
            continue
        if op:
            seen_ops.add(op)
            by_op[op] = payload
        for alias in aliases:
            key = (alias, role, digest)
            seen_keys.add(key)
            by_key.setdefault(key, payload)
        merged.append(payload)
    return merged


ACTUAL_MODEL_CALLS_SCHEMA = "les.actual_model_calls.v1"


def ensure_actual_model_calls(trace: dict[str, Any] | None) -> dict[str, Any]:
    payload = trace if isinstance(trace, dict) else {}
    bucket = payload.get("actual_model_calls")
    if not isinstance(bucket, dict):
        bucket = {
            "schema": ACTUAL_MODEL_CALLS_SCHEMA,
            "calls": [],
            "search_executions": 0,
            "search_cache_hits": 0,
            "search_hits": 0,
        }
        payload["actual_model_calls"] = bucket
    bucket.setdefault("calls", [])
    bucket.setdefault("search_executions", 0)
    bucket.setdefault("search_cache_hits", 0)
    bucket.setdefault("search_hits", 0)
    return bucket


def append_actual_model_call(
    trace: dict[str, Any] | None,
    *,
    purpose: str,
    finish_reason: str = "",
    completion_tokens: int = 0,
) -> None:
    bucket = ensure_actual_model_calls(trace)
    bucket["calls"].append(
        {
            "purpose": str(purpose or ""),
            "finish_reason": str(finish_reason or ""),
            "completion_tokens": int(completion_tokens or 0),
        }
    )


def append_actual_search(
    trace: dict[str, Any] | None,
    *,
    cached: bool,
    hit_count: int,
) -> None:
    bucket = ensure_actual_model_calls(trace)
    if cached:
        bucket["search_cache_hits"] = int(bucket.get("search_cache_hits") or 0) + 1
    else:
        bucket["search_executions"] = int(bucket.get("search_executions") or 0) + 1
    bucket["search_hits"] = int(bucket.get("search_hits") or 0) + int(hit_count or 0)


def durable_research_hit(hit: Any) -> dict[str, Any]:
    if isinstance(hit, Mapping):
        meta = hit.get("meta") if isinstance(hit.get("meta"), Mapping) else {}
        return {
            "content": str(hit.get("content") or ""),
            "doc_id": str(hit.get("doc_id") or ""),
            "doc_name": str(hit.get("doc_name") or ""),
            "score": float(hit.get("score") or 0.0),
            "meta": dict(meta),
        }
    meta = getattr(hit, "meta", {}) or {}
    return {
        "content": str(getattr(hit, "content", "") or ""),
        "doc_id": str(getattr(hit, "doc_id", "") or ""),
        "doc_name": str(getattr(hit, "doc_name", "") or ""),
        "score": float(getattr(hit, "score", 0.0) or 0.0),
        "meta": dict(meta) if isinstance(meta, Mapping) else {},
    }


def research_hit_from_record(record: Mapping[str, Any]) -> _ModelRagEvidenceChunk:
    meta = dict(record.get("meta") or {}) if isinstance(record.get("meta"), Mapping) else {}
    return _ModelRagEvidenceChunk(
        content=str(record.get("content") or ""),
        doc_id=str(record.get("doc_id") or ""),
        doc_name=str(record.get("doc_name") or ""),
        score=float(record.get("score") or 0.0),
        meta=meta,
    )


def restore_query_hits_from_cache(
    queries: Sequence[str],
    cache: Mapping[str, Any],
) -> list[tuple[str, Sequence[Any]]]:
    restored: list[tuple[str, Sequence[Any]]] = []
    for query in queries:
        key = str(query or "").strip()
        records = cache.get(key) if isinstance(cache, Mapping) else None
        if not key or not isinstance(records, list):
            continue
        hits = tuple(
            research_hit_from_record(item)
            for item in records
            if isinstance(item, Mapping)
        )
        restored.append((key, hits))
    return restored


_MODEL_SEARCH_CONTINUE_STATUSES = frozenset({"ok", "missing", "degraded_sparse_only"})


def model_search_result_blocks_packet(payload: Mapping[str, Any] | None) -> bool:
    """Abort a packet only on search infrastructure failure.

    Zero hits (`missing`) is a model-visible fact: remaining queries and the
    terminal row table still run. The model may mark those rows MISSING.
    """

    status = str((payload or {}).get("status") or "").strip().casefold()
    return status not in _MODEL_SEARCH_CONTINUE_STATUSES


def stamp_empty_retrieval(
    trace: dict[str, Any],
    *,
    model_driven: bool,
    chunks: Sequence[Any],
) -> None:
    """Do not label an awaiting model-authored search as empty retrieval."""

    if chunks or model_driven:
        trace.pop("empty_retrieval", None)
        return
    trace["empty_retrieval"] = {
        "schema": "empty_retrieval_model_first_v1",
        "model_final_allowed": True,
        "note": "No retrieved chunks; continue to model with memory/navigation instead of code NO_DATA final.",
    }


def finalize_actual_retrieval_emptiness(
    trace: dict[str, Any],
    *,
    evidence_count: int,
    searches_executed: int,
    search_hits: int,
) -> None:
    if int(evidence_count or 0) > 0 or int(search_hits or 0) > 0:
        trace.pop("empty_retrieval", None)
        return
    if int(searches_executed or 0) <= 0:
        return
    trace["empty_retrieval"] = {
        "schema": "empty_retrieval_model_first_v1",
        "model_final_allowed": True,
        "note": "model-authored searches returned no chunks",
    }


def sheet_pass_keep_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    sheet: str,
    catalog: AttachmentSourceCatalog,
    errors: Sequence[str],
) -> list[dict[str, Any]]:
    """Keep this sheet's rows that passed per-pass Qx.Hy/quantity checks."""

    wanted = str(sheet or "").strip()
    on_sheet: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        payload = dict(row)
        catalog_row = catalog.lookup(payload.get("source_row"))
        if catalog_row is not None:
            if catalog_row.sheet != wanted:
                continue
        else:
            # Keep the raw answer in history, but a partial/unknown locator
            # cannot become an accepted source decision or a workbook row.
            continue
        on_sheet.append(payload)
    work_count = sum(1 for row in on_sheet if model_rag_row_kind(row) == "work")
    blocking = blocking_model_rag_result_errors(errors, work_row_count=work_count)
    kept: list[dict[str, Any]] = []
    for row in on_sheet:
        if model_rag_row_kind(row) == "work" and _sheet_pass_row_blocked(row, blocking):
            continue
        kept.append(row)
    return kept


def _sheet_pass_row_blocked(row: Mapping[str, Any], blocking_errors: Sequence[str]) -> bool:
    key = str(row.get("source_row") or "").strip()
    refs = {
        str(item or "").strip().upper()
        for item in (row.get("evidence_refs") or [])
        if str(item or "").strip()
    }
    for error in blocking_errors:
        text = str(error)
        if text == "invalid_source_row":
            continue
        if ":" not in text:
            continue
        prefix, rest = text.split(":", 1)
        rest = rest.strip()
        if prefix in {
            "missing_evidence_ref",
            "source_quantity_mismatch",
            "duplicate_source_row",
        } and rest == key:
            return True
        if prefix == "unknown_evidence_ref" and rest.upper() in refs:
            return True
    return False


def remaining_sheet_work_locators(
    catalog: AttachmentSourceCatalog,
    sheet: str,
    cited: Sequence[str],
) -> list[str]:
    known = {str(item).strip() for item in cited if str(item).strip()}
    return [
        locator
        for locator in catalog_sheet_work_locators(catalog, sheet)
        if locator not in known
    ]


def structurally_complete_source_keys(rows, catalog):
    """Only complete source records finish a packet; norms remain model-owned."""
    from proxy.services.lsr_source_coverage_service import build_source_coverage

    keys = cited_source_row_keys(rows, catalog)
    coverage = build_source_coverage(catalog_locators=catalog.work_locators(), rows=rows)
    invalid = set(coverage["incomplete_locators"])
    return keys - invalid

def adjudicated_source_keys(rows, catalog):
    """Locators the model gave a terminal role to (work/material/equipment/resource/
    unresolved/header).

    A classified row is *decided* even when a quality gap (no norm, no work_row link,
    no open_gap sentence) remains — those gaps belong in the reported ``missing`` list,
    not in an endless resume.  Completion must not re-queue positions that legitimately
    have no applicable norm, or a large document can never finalize.
    """
    from proxy.services.lsr_source_coverage_service import inferred_row_role

    keys: set[str] = set()
    for row in rows:
        if not hasattr(row, "get"):
            continue
        raw = row.get("source_row")
        if raw in (None, ""):
            continue
        if not inferred_row_role(row):
            continue
        keys.add(str(raw).strip())
        if catalog is not None:
            found = catalog.lookup(raw)
            if found is not None:
                keys.add(found.locator)
    return keys


def adaptive_row_packet(
    remaining: Sequence[str],
    *,
    generation_reserve_tokens: int,
    already_offered: Sequence[str] = (),
    offer_counts: Mapping[str, int] | None = None,
) -> list[str]:
    """Bound one model result by row count and the available output budget.

    This is technical orchestration only: order and row content come unchanged
    from the exact catalog.  The model still owns queries and every decision.

    Rows are ordered by how often they have already been put to the model,
    least offered first, with the catalog position breaking ties.  A row the
    model classified but that keeps a quality gap stays in the completeness
    denominator, so a plain head slice re-sent the same leading rows on every
    packet and never reached the rows behind them; those unseen rows then ended
    the document with no decision from the model at all.  The rows offered in
    this pass alone are not enough: a sheet pass stops after a few packets, so
    the counts taken from the durable checkpoints are what keep the rotation
    going across resumes instead of restarting it at the head of the sheet.
    """

    locators = [str(item).strip() for item in remaining if str(item).strip()]
    if not locators:
        return []
    reserve = max(1, int(generation_reserve_tokens or 0))
    # Leave room for table headers and prose, then budget complete decision
    # rows including roles, links and provenance. Low-capacity backends must
    # be allowed packets smaller than eight rows.
    budget_rows = max(1, (reserve - 400) // 250)
    size = min(_ROW_PACKET_MAX, budget_rows, len(locators))
    offered = {str(item).strip() for item in already_offered if str(item).strip()}
    durable_counts = {
        str(key).strip(): max(0, int(value or 0))
        for key, value in (offer_counts or {}).items()
        if str(key).strip()
    }
    if offered or durable_counts:
        position = {locator: index for index, locator in enumerate(locators)}

        def _times_put_to_model(locator: str) -> int:
            return durable_counts.get(locator, 0) + (1 if locator in offered else 0)

        locators = sorted(
            locators,
            key=lambda locator: (_times_put_to_model(locator), position[locator]),
        )
    return locators[:size]


def row_packet_id(
    catalog: AttachmentSourceCatalog,
    *,
    sheet: str,
    locators: Sequence[str],
) -> str:
    payload = "\x1f".join(
        [catalog.source_file_id or catalog.original_name, str(sheet), *map(str, locators)]
    )
    return "packet_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


_SHIFR_RE = re.compile(r"\u0428\u0438\u0444\u0440:\s*([^\s,;]+)")


def _card_code_from_body(body: str, doc_name: str) -> str:
    match = _SHIFR_RE.search(body or "")
    return match.group(1) if match else str(doc_name or "")


def row_evidence_provenance_check(
    row,
    bindings,
    alias_to_card,
    alias_to_query,
):
    """Structural citation check only: never rewrites the model's decision."""

    norm_code = str(row.get("norm_code") or "").strip()
    if not norm_code:
        return None
    cited = [
        {
            "ref": alias,
            "card": alias_to_card.get(alias, ""),
            "query": alias_to_query.get(alias, ""),
        }
        for alias in sorted(bindings)
    ]
    unresolved = sorted(
        {
            str(ref).strip().upper()
            for ref in row.get("evidence_refs") or ()
            if str(ref).strip() and str(ref).strip().upper() not in bindings
        }
    )
    codes = [item["card"] for item in cited if item["card"]]
    return {
        "norm_code": norm_code,
        "cited": cited,
        "unresolved_refs": unresolved,
        "code_not_in_refs": not any(
            norm_code in code or code in norm_code for code in codes
        ),
    }


def model_rag_budget_omitted_cards(included_hits, chunks, omitted_refs):
    """Cards found by search but dropped by the evidence budget: name them."""

    if not omitted_refs:
        return []
    wanted = {str(ref).strip().upper() for ref in omitted_refs}
    shown = {
        str((getattr(chunk, "meta", {}) or {}).get("model_evidence_ref") or "")
        .strip()
        .upper()
        for chunk in chunks
    }
    detail = []
    for query_index, (query_text, hits) in enumerate(list(included_hits), 1):
        for hit_index, hit in enumerate(list(hits), 1):
            ref = f"Q{query_index}.H{hit_index}"
            if ref not in wanted or ref in shown:
                continue
            detail.append(
                {
                    "ref": ref,
                    "query": str(query_text or ""),
                    "card": _card_code_from_body(
                        str(getattr(hit, "content", "") or ""),
                        str(getattr(hit, "doc_name", "") or ""),
                    ),
                }
            )
    return detail[:300]


def bind_row_evidence_ids(
    rows: Sequence[Mapping[str, Any]],
    evidence_chunks: Sequence[Any],
) -> list[dict[str, Any]]:
    alias_to_global: dict[str, str] = {}
    alias_to_card: dict[str, str] = {}
    alias_to_query: dict[str, str] = {}
    for chunk in evidence_chunks:
        meta = getattr(chunk, "meta", {}) or {}
        alias = str(meta.get("model_evidence_ref") or "").strip().upper()
        global_id = str(meta.get("global_evidence_id") or "").strip()
        if alias and alias not in alias_to_card:
            alias_to_card[alias] = _card_code_from_body(
                str(getattr(chunk, "content", "") or ""),
                str(getattr(chunk, "doc_name", "") or ""),
            )
            alias_to_query[alias] = str(meta.get("model_query_text") or "")
        if alias and global_id and alias not in alias_to_global:
            alias_to_global[alias] = global_id
    bound: list[dict[str, Any]] = []
    for row in rows:
        payload = dict(row)
        current = payload.get("evidence_bindings")
        merged = {
            str(alias).strip().upper(): str(global_id).strip()
            for alias, global_id in (current.items() if isinstance(current, Mapping) else ())
            if str(alias).strip() and str(global_id).strip()
        }
        for ref in payload.get("evidence_refs") or ():
            alias = str(ref).strip().upper()
            global_id = alias_to_global.get(alias, "")
            if alias and global_id and alias not in merged:
                merged[alias] = global_id
        payload["evidence_bindings"] = merged
        evidence_check = row_evidence_provenance_check(
            payload, merged, alias_to_card, alias_to_query
        )
        if evidence_check is not None:
            payload["_evidence_check"] = evidence_check
        bound.append(payload)
    return bound


def durable_evidence_record(chunk: _ModelRagEvidenceChunk) -> dict[str, Any]:
    return {
        "global_evidence_id": str(chunk.meta.get("global_evidence_id") or ""),
        "model_evidence_ref": str(chunk.meta.get("model_evidence_ref") or ""),
        "content": chunk.content,
        "doc_id": chunk.doc_id,
        "doc_name": chunk.doc_name,
        "score": chunk.score,
        "meta": dict(chunk.meta),
    }


def evidence_chunk_from_record(record: Mapping[str, Any]) -> _ModelRagEvidenceChunk:
    meta = dict(record.get("meta") or {}) if isinstance(record.get("meta"), Mapping) else {}
    for key in ("global_evidence_id", "model_evidence_ref"):
        if record.get(key) not in (None, ""):
            meta[key] = record[key]
    return _ModelRagEvidenceChunk(
        content=str(record.get("content") or ""),
        doc_id=str(record.get("doc_id") or ""),
        doc_name=str(record.get("doc_name") or ""),
        score=float(record.get("score") or 0.0),
        meta=meta,
    )


def sheet_pass_progress_label(
    sheet: str,
    *,
    sheet_index: int,
    sheet_count: int,
    stage: str,
    resumed: bool = False,
) -> str:
    prefix = "Продолжаю: " if resumed else ""
    return f"{prefix}Лист «{sheet}» ({sheet_index}/{sheet_count}): {stage}"


_LIVE_SHEET_PASS_GATES: dict[str, asyncio.Event] = {}


async def claim_or_join_sheet_pass(job_id: str) -> bool:
    """Serialize packet loops on one research job inside this process.

    Returns True when this request owns the loop. A second Continue while the
    first is still running waits, then returns False so it does not dual-run.
    """

    key = str(job_id or "").strip()
    if not key:
        return True
    gate = _LIVE_SHEET_PASS_GATES.get(key)
    if gate is not None:
        await gate.wait()
        return False
    _LIVE_SHEET_PASS_GATES[key] = asyncio.Event()
    return True


def release_sheet_pass(job_id: str) -> None:
    """Allow the next Continue after this process-local sheet-pass ends."""

    key = str(job_id or "").strip()
    gate = _LIVE_SHEET_PASS_GATES.pop(key, None)
    if gate is not None:
        gate.set()


def sheet_pass_progress_counts(
    *,
    accepted_now: int,
    work_total: int,
    session_accepted_start: int,
    prior_elapsed_seconds: float = 0.0,
) -> dict[str, Any]:
    """Row counters for the sheet-pass bubble: display vs session ETA."""

    total = max(int(work_total or 0), 1)
    accepted = max(0, int(accepted_now or 0))
    started = max(0, int(session_accepted_start or 0))
    remaining_n = max(0, int(work_total or 0) - accepted)
    return {
        "completed": accepted,
        "total": total,
        "eta_completed": max(0, accepted - started),
        "eta_total": max(0, int(work_total or 0) - started),
        "resumed": started > 0,
        "remaining": remaining_n,
        "prior_completed": started,
        "prior_elapsed_seconds": float(prior_elapsed_seconds or 0.0),
    }


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
            "work_id": str(source_row),
            "source_row": source_row,
            "section": str(item.get("section") or "").strip(),
            "title": str(item.get("title") or "").strip(),
            "quantity": item.get("quantity"),
            "unit": str(item.get("unit") or "").strip(),
            "norm_code": str(item.get("norm_code") or "").strip(),
        }
        for field_name in (
            "analogue",
            "coverage",
            "coefficient",
            "evidence_refs",
            "norm_status",
            "action_match",
            "object_match",
            "_quality_gate",
            "_evidence_check",
            "quality_message",
            "row_role",
            "work_row",
            "supply_kind",
            "open_gap",
            "conversion_factor",
            "conversion_source",
            "calc_quantity",
            "confirmed_price",
            "price_source",
        ):
            if field_name in item:
                row[field_name] = item[field_name]
        compact.append(row)
    return compact


_NARRATIVE_QUERY_PREFIXES = (
    "слушай ",
    "слушайте ",
    "коллега,",
    "коллега ",
    "что я делаю",
    "я сейчас ",
    "я делаю ",
    "жду подтверждения",
    "вот список",
    "сейчас сформирую",
    "это все запросы",
)
_NARRATIVE_QUERY_EXACT = {
    "ок",
    "хорошо",
    "понял",
    "готово",
    "сейчас",
    "коллега",
}
_TABULAR_TRUNCATION_MARK = "[Табличный контекст усечён"
_PASTE_TRUNCATION_MARK = "[Исходник усечён"
_MIN_MODEL_RAG_EVIDENCE_BODY_CHARS = 400
_LENGTH_FINISH_REASONS = {"length", "max_tokens", "length_truncated"}


def _unwrap_model_rag_query_lines(raw: str) -> list[str]:
    """Strip fences and explicit wrappers; do not invent replacement queries."""

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
        if query:
            queries.append(query)
    return queries


def is_model_rag_search_query_line(line: str) -> bool:
    """Reject conversational preamble; keep the remaining model-authored search lines."""

    folded = " ".join(str(line or "").split()).casefold()
    if not folded:
        return False
    if folded in _NARRATIVE_QUERY_EXACT:
        return False
    return not any(folded.startswith(prefix) for prefix in _NARRATIVE_QUERY_PREFIXES)


def classify_model_rag_query_lines(raw: str) -> tuple[list[str], list[str]]:
    """Split unwrapped lines into executable queries and rejected narrative."""

    accepted: list[str] = []
    rejected: list[str] = []
    for query in _unwrap_model_rag_query_lines(raw):
        if is_model_rag_search_query_line(query):
            accepted.append(query)
        else:
            rejected.append(query)
    return accepted, rejected


def parse_model_rag_queries(raw: str) -> list[str]:
    """Return the model-authored search lines without presentation wrappers or narrative."""

    accepted, _rejected = classify_model_rag_query_lines(raw)
    return accepted


_MODEL_EVIDENCE_REF = re.compile(r"^Q(\d+)\.H(\d+)$", re.IGNORECASE)


def extract_model_evidence_refs(value: Any) -> list[str]:
    """Keep only real Qn.Hm handles. Prose notes are not evidence."""

    if isinstance(value, (list, tuple)) and not isinstance(value, (str, bytes)):
        texts = [str(item or "") for item in value]
    else:
        texts = [str(value or "")]
    found: list[str] = []
    for text in texts:
        separated = text.replace("<br>", " ").replace("<br/>", " ")
        for marker in "[](),;":
            separated = separated.replace(marker, " ")
        for token in separated.split():
            candidate = token.strip(".*_`:").upper()
            if _MODEL_EVIDENCE_REF.fullmatch(candidate):
                found.append(candidate)
    return list(dict.fromkeys(found))


def unresolved_evidence_placeholder(value: Any) -> bool:
    marker = " ".join(str(value or "").casefold().replace("ё", "е").split())
    return "qx.hy" in marker or "отсутствует в выдаче" in marker


def parse_model_rag_result(raw: str) -> tuple[str, list[dict[str, Any]]] | None:
    """Decode only an unambiguous table; preserve the authored answer and cell values."""

    required_fields = {"title", "unit", "norm_code"}
    numeric_fields = {
        "quantity",
        "coefficient",
        "conversion_factor",
        "calc_quantity",
        "confirmed_price",
    }
    header_fields = {
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
        "наименование работы": "title",
        "unit": "unit",
        "ед. изм.": "unit",
        "ед. изм": "unit",
        "ед изм": "unit",
        "ед": "unit",
        "единица": "unit",
        "quantity": "quantity",
        "кол-во": "quantity",
        "кол.": "quantity",
        "кол": "quantity",
        "количество": "quantity",
        "row_role": "row_role",
        "роль": "row_role",
        "роль строки": "row_role",
        "work_row": "work_row",
        "строка работы": "work_row",
        "supply_kind": "supply_kind",
        "вид поставки": "supply_kind",
        "open_gap": "open_gap",
        "открытый вопрос": "open_gap",
        "conversion_factor": "conversion_factor",
        "коэффициент перевода": "conversion_factor",
        "conversion_source": "conversion_source",
        "источник перевода": "conversion_source",
        "calc_quantity": "calc_quantity",
        "расчётное количество": "calc_quantity",
        "confirmed_price": "confirmed_price",
        "подтверждённая цена": "confirmed_price",
        "price_source": "price_source",
        "источник цены": "price_source",
        "norm_code": "norm_code",
        "norm_code (выбранная норма)": "norm_code",
        "norm_code (возможная норма монтажа)": "norm_code",
        "norm_code (шифр)": "norm_code",
        "нормативная база (шифр нормы)": "norm_code",
        "нормативная база (norm code)": "norm_code",
        "нормативный код (гэсн/ер)": "norm_code",
        "шифр нормы": "norm_code",
        "шифр": "norm_code",
        "выбранная норма": "norm_code",
        "код нормы": "norm_code",
        "гэсн": "norm_code",
        "позиция": "source_row",
        "строка": "source_row",
        "locator": "source_row",
        "код строки": "source_row",
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
        "norm_status": "norm_status",
        "статус нормы": "norm_status",
        "verdict": "norm_status",
        "action_match": "action_match",
        "object_match": "object_match",
        "condition_match": "condition_match",
        "unit_compatible": "unit_compatible",
        "composition_covers": "composition_covers",
        "extra_ops": "extra_ops",
        "missing_ops": "missing_ops",
        "contradictions": "contradictions",
        "coefficient": "coefficient",
        "coefficient (кэф.)": "coefficient",
        "коэфф.": "coefficient",
        "coefficient_applies_to": "coefficient_applies_to",
        "norm_components": "norm_components",
        "evidence_refs": "evidence_refs",
        "evidence_refs (источник)": "evidence_refs",
    }

    def field_name(value: str) -> str:
        normalized = " ".join(value.replace("**", "").strip().split()).casefold()
        return header_fields.get(normalized, "")

    def cells(line: str) -> list[str]:
        stripped = line.strip()
        if not stripped.startswith("|"):
            return []
        inner = stripped[1:-1] if stripped.endswith("|") else stripped[1:]
        return [item.strip() for item in inner.split("|")]

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
        return extract_model_evidence_refs(value)

    def applies_to_token(value: str) -> bool:
        folded = " ".join(value.casefold().replace("ё", "е").split())
        return folded in {
            "",
            "labor",
            "machine",
            "labor_and_machine",
            "озп",
            "эм",
            "озп и эм",
        } or absence_marker(value)

    def aligned_row_fits(values: list[str]) -> bool:
        if len(values) != len(mapped_header):
            return False
        by = {
            name: values[index]
            for index, name in enumerate(mapped_header)
            if name
        }
        quantity = by.get("quantity", "")
        if quantity and not absence_marker(quantity) and number(quantity) is None:
            return False
        # Alignment preserves model text, including unresolved source labels.
        # Evidence validation is a separate step and must not erase work rows.
        applies = by.get("coefficient_applies_to", "")
        if applies and not applies_to_token(applies):
            return False
        return True

    def align_row_values(values: list[str]) -> list[str] | None:
        if len(values) < len(header):
            return values + [""] * (len(header) - len(values))
        if len(values) == len(header):
            return values
        extra = len(values) - len(header)
        title_at = next(
            (index for index, name in enumerate(mapped_header) if name == "title"),
            -1,
        )
        # Product titles often contain "|" (Hyperline dims). Fold surplus cells
        # back into the title column instead of discarding the whole row.
        if title_at >= 0 and extra >= 1:
            title_end = title_at + 1 + extra
            if title_end <= len(values):
                merged_title = " | ".join(
                    item for item in values[title_at:title_end] if str(item).strip()
                )
                trial = values[:title_at] + [merged_title] + values[title_end:]
                if len(trial) == len(header) and aligned_row_fits(trial):
                    return trial
        if extra > 3:
            return None
        coeff_at = next(
            (index for index, name in enumerate(mapped_header) if name == "coefficient"),
            -1,
        )
        if (
            extra == 1
            and "contradictions" not in mapped_header
            and 0 <= coeff_at < len(values)
            and absence_marker(values[coeff_at])
        ):
            trial = values[:coeff_at] + values[coeff_at + 1 :]
            if aligned_row_fits(trial):
                return trial
        if (
            extra == 1
            and "contradictions" not in mapped_header
            and 0 <= coeff_at < len(values) - 3
            and evidence_refs(values[-1])
            and applies_to_token(values[-2])
            and number(values[-3]) is not None
            and number(values[coeff_at]) is None
            and not absence_marker(values[coeff_at])
        ):
            trial = values[:coeff_at] + values[coeff_at + 1 :]
            if aligned_row_fits(trial):
                return trial
        trimmed = list(values)
        while len(trimmed) > len(header) and trimmed and (
            not trimmed[-1].strip() or absence_marker(trimmed[-1])
        ):
            if evidence_refs(trimmed[-1]):
                break
            trimmed = trimmed[:-1]
        if len(trimmed) == len(header) and aligned_row_fits(trimmed):
            return trimmed
        drop_at = [
            index
            for index, item in enumerate(values)
            if index >= 6 and absence_marker(item)
        ]
        matched: list[list[str]] = []
        for combo in combinations(drop_at, extra):
            skip = set(combo)
            trial = [item for index, item in enumerate(values) if index not in skip]
            if aligned_row_fits(trial):
                matched.append(trial)
                if len(matched) > 1:
                    return None
        return matched[0] if matched else None

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
        # A display ordinal is not a second source locator when the model
        # explicitly supplies source_row. Keep the explicit identity verbatim.
        normalized_header = [
            " ".join(item.replace("**", "").strip().split()).casefold()
            for item in header
        ]
        if "source_row" in normalized_header:
            mapped_header = [
                "" if label in {"№", "№ п/п", "№ пп"} else field
                for label, field in zip(normalized_header, mapped_header, strict=True)
            ]
        if "coverage_fallback" in mapped_header:
            fallback_name = "" if "coverage" in mapped_header else "coverage"
            mapped_header = [
                fallback_name if item == "coverage_fallback" else item
                for item in mapped_header
            ]
        if (
            not header
            or not required_fields.issubset(set(mapped_header))
            or len([item for item in mapped_header if item])
            != len(set(item for item in mapped_header if item))
        ):
            header_index += 1
            continue
        if header_index + 1 >= len(lines):
            break
        divider = cells(lines[header_index + 1])
        while len(divider) > len(header) and divider and divider_cell(divider[-1]):
            divider = divider[:-1]
        # Divider cells are presentation, not the schema. Models sometimes emit
        # one fewer separator than labelled columns; the header still provides
        # the unambiguous mapping for every actual row.
        if not divider or not all(divider_cell(item) for item in divider):
            header_index += 1
            continue
        table_section = current_section
        row_index = header_index + 2
        while row_index < len(lines):
            values = cells(lines[row_index])
            if not values:
                break
            if len(values) != len(header):
                values = align_row_values(values) or []
                if len(values) != len(header):
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
            row: dict[str, Any] = {}
            for name, value in raw_row.items():
                if not value:
                    continue
                if name == "source_row":
                    parsed_source_row = source_row_identity(value)
                    if parsed_source_row is None:
                        # One broken locator must not erase the rest of the table.
                        row.clear()
                        break
                    row[name] = parsed_source_row
                elif name in numeric_fields:
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
                        # Preserve the authored cell. Numeric validation belongs
                        # to calculation; one bad cell must not erase other rows.
                        row[name] = value
                        continue
                    row[name] = parsed_number
                elif name == "evidence_refs":
                    refs = evidence_refs(value)
                    if not refs and unresolved_evidence_placeholder(value):
                        refs = [value.strip()]
                    if refs:
                        row[name] = refs
                elif name:
                    row[name] = value
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
        "source_row": "source_row",
        "section": "section",
        "title": "title",
        "unit": "unit",
        "quantity": "quantity",
        "row_role": "row_role",
        "work_row": "work_row",
        "supply_kind": "supply_kind",
        "open_gap": "open_gap",
        "открытый вопрос": "open_gap",
        "conversion_factor": "conversion_factor",
        "conversion_source": "conversion_source",
        "calc_quantity": "calc_quantity",
        "confirmed_price": "confirmed_price",
        "price_source": "price_source",
        "norm_code": "norm_code",
        "analogue": "analogue",
        "coverage": "coverage",
        "norm_status": "norm_status",
        "action_match": "action_match",
        "object_match": "object_match",
        "condition_match": "condition_match",
        "unit_compatible": "unit_compatible",
        "composition_covers": "composition_covers",
        "extra_ops": "extra_ops",
        "missing_ops": "missing_ops",
        "contradictions": "contradictions",
        "coefficient": "coefficient",
        "coefficient_applies_to": "coefficient_applies_to",
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
        key = block_fields.get(label.strip().strip("*_` ").casefold())
        clean = value.strip().lstrip("*_` ").strip()
        if not key or not clean:
            continue
        if key == "source_row":
            parsed_source_row = source_row_identity(clean)
            if parsed_source_row is None:
                invalid_block = True
                continue
            current_block[key] = parsed_source_row
        elif key in numeric_fields:
            if clean.casefold() in {
                "—", "-", "–", "−", "нет", "н/д", "n/a", "na",
            }:
                continue
            parsed_number = number(clean)
            if parsed_number is None and key == "coefficient":
                first_token = clean.split(maxsplit=1)[0].rstrip(".,;")
                parsed_number = number(first_token)
            if parsed_number is None:
                current_block[key] = clean
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
        "row_role": "row_role",
        "work_row": "work_row",
        "supply_kind": "supply_kind",
        "open_gap": "open_gap",
        "открытый вопрос": "open_gap",
        "conversion_factor": "conversion_factor",
        "conversion_source": "conversion_source",
        "calc_quantity": "calc_quantity",
        "confirmed_price": "confirmed_price",
        "price_source": "price_source",
        "norm_code": "norm_code",
        "шифр нормы": "norm_code",
        "аналог": "analogue",
        "обоснование": "coverage",
        "coverage": "coverage",
        "коэффициент": "coefficient",
        "coefficient": "coefficient",
        "coefficient_applies_to": "coefficient_applies_to",
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
            key = labelled_fields.get(" ".join(label.strip().split()).casefold())
            clean = value.strip()
            if not key or not clean:
                continue
            if key in numeric_fields:
                parsed_number = number(clean)
                if parsed_number is None:
                    row[key] = clean
                    continue
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


def model_rag_group_char_budget(
    *,
    context_chars_limit: int,
    remaining_group_tokens: int,
) -> int:
    """Char ceiling for Q/H headers: leftover tokens at 2 chars/token, capped by context."""

    remaining_chars = max(0, int(remaining_group_tokens)) * 2
    limit = max(0, int(context_chars_limit))
    if not remaining_chars:
        return 0
    if not limit:
        return remaining_chars
    return min(limit, remaining_chars)


def _model_rag_capped_hits(raw_hits: Sequence[Any], hits_per_query: int) -> list[Any]:
    return list(raw_hits)[: max(1, int(hits_per_query))]


def _model_rag_query_header(query_index: int, query: str) -> str:
    return f"[Поисковый запрос Q{query_index}] {str(query or '').strip()}"


def _model_rag_source_header(query_index: int, hit_index: int, hit: Any) -> str:
    doc_name = str(getattr(hit, "doc_name", "") or "")
    score = float(getattr(hit, "score", 0.0) or 0.0)
    return f"[Q{query_index}.H{hit_index} | {doc_name} | score={score:.4f}]"


def model_rag_evidence_header_chars(
    query_hits: Sequence[tuple[str, Sequence[Any]]],
    *,
    hits_per_query: int,
    query_offset: int = 0,
) -> int:
    """Character tax of query and hit headers, matching grouped evidence layout."""

    fixed_chars = 0
    segment_count = 0
    cap = max(1, int(hits_per_query))
    for query_index, (raw_query, raw_hits) in enumerate(
        query_hits, max(0, query_offset) + 1
    ):
        fixed_chars += len(_model_rag_query_header(query_index, str(raw_query or "")))
        segment_count += 1
        for hit_index, hit in enumerate(list(raw_hits)[:cap], 1):
            fixed_chars += len(_model_rag_source_header(query_index, hit_index, hit)) + 2
            segment_count += 1
    return fixed_chars + max(0, segment_count - 1) * 2


def model_rag_query_hit_refs(
    query_hits: Sequence[tuple[str, Sequence[Any]]],
    *,
    hits_per_query: int,
    query_offset: int = 0,
) -> list[str]:
    """Stable Q/H ids for queries that stay intact for a later packet or honest omit."""

    refs: list[str] = []
    cap = max(1, int(hits_per_query))
    for query_index, (_query, raw_hits) in enumerate(
        query_hits, max(0, query_offset) + 1
    ):
        refs.append(f"Q{query_index}")
        for hit_index, _hit in enumerate(list(raw_hits)[:cap], 1):
            refs.append(f"Q{query_index}.H{hit_index}")
    return refs


def select_model_rag_query_hits_for_budget(
    query_hits: Sequence[tuple[str, Sequence[Any]]],
    *,
    max_chars: int,
    hits_per_query: int,
    query_offset: int = 0,
) -> tuple[
    list[tuple[str, Sequence[Any]]],
    list[tuple[str, Sequence[Any]]],
    list[str],
]:
    """Prefix whose headers fit; leftover queries stay whole for the next packet.

    Technical orchestration only: query text and hit order are unchanged. If even
    the first query's hit headers exceed the budget, keep the query identity and
    drop trailing hit headers of that query. An empty budget omits this packet
    rather than raising.
    """

    items = [
        (str(query or "").strip(), tuple(_model_rag_capped_hits(hits, hits_per_query)))
        for query, hits in query_hits
    ]
    if not items:
        return [], [], []
    if max_chars <= 0:
        return [], items, []

    taken = 0
    for count in range(1, len(items) + 1):
        tax = model_rag_evidence_header_chars(
            items[:count],
            hits_per_query=hits_per_query,
            query_offset=query_offset,
        )
        if tax <= max_chars:
            taken = count
            continue
        break
    if taken:
        return items[:taken], items[taken:], []

    query, hits = items[0]
    query_index = max(0, query_offset) + 1
    kept_hits = list(hits)
    omitted_refs: list[str] = []
    while kept_hits:
        trial = [(query, tuple(kept_hits))]
        if (
            model_rag_evidence_header_chars(
                trial,
                hits_per_query=hits_per_query,
                query_offset=query_offset,
            )
            <= max_chars
        ):
            break
        kept_hits.pop()
        omitted_refs.append(f"Q{query_index}.H{len(kept_hits) + 1}")
    if not kept_hits:
        omitted_refs = [
            f"Q{query_index}.H{hit_index}" for hit_index in range(1, len(hits) + 1)
        ]
    return [(query, tuple(kept_hits))], items[1:], omitted_refs


def build_model_rag_evidence_groups(
    query_hits: Sequence[tuple[str, Sequence[Any]]],
    *,
    max_chars: int,
    hits_per_query: int,
    min_body_chars: int = _MIN_MODEL_RAG_EVIDENCE_BODY_CHARS,
    evidence_namespace: str = "",
    query_offset: int = 0,
) -> tuple[list[str], list[_ModelRagEvidenceChunk], list[str]]:
    """Keep query headers; omit leftover queries and cards rather than crash."""

    included, leftover, omitted_refs = select_model_rag_query_hits_for_budget(
        query_hits,
        max_chars=max_chars,
        hits_per_query=hits_per_query,
        query_offset=query_offset,
    )
    omitted_refs = list(omitted_refs)
    omitted_refs.extend(
        model_rag_query_hit_refs(
            leftover,
            hits_per_query=hits_per_query,
            query_offset=query_offset + len(included),
        )
    )
    if not included:
        return [], [], omitted_refs

    prepared: list[tuple[int, str, str, list[tuple[int, Any, str, str]]]] = []
    source_index = 0
    fixed_chars = 0
    segment_count = 0
    for query_index, (raw_query, raw_hits) in enumerate(
        included, max(0, query_offset) + 1
    ):
        query = str(raw_query or "").strip()
        query_header = _model_rag_query_header(query_index, query)
        hits: list[tuple[int, Any, str, str]] = []
        fixed_chars += len(query_header)
        segment_count += 1
        for hit_index, hit in enumerate(list(raw_hits), 1):
            source_index += 1
            source_header = _model_rag_source_header(query_index, hit_index, hit)
            body = str(getattr(hit, "content", "") or "").strip()
            hits.append((hit_index, hit, source_header, body))
            fixed_chars += len(source_header) + 2
            segment_count += 1
        prepared.append((query_index, query_header, query, hits))

    fixed_chars += max(0, segment_count - 1) * 2

    bodies = [
        body for _qi, _qh, _q, hits in prepared for _hi, _hit, _sh, body in hits
    ]
    body_budget = max(0, int(max_chars) - fixed_chars)
    low, high = 0, max((len(body) for body in bodies), default=0)
    while low < high:
        cap = (low + high + 1) // 2
        if sum(min(len(body), cap) for body in bodies) <= body_budget:
            low = cap
        else:
            high = cap - 1
    body_cap = low
    min_body = max(0, int(min_body_chars))
    omit_mode = bool(bodies) and body_cap < min_body

    included_caps: dict[tuple[int, int], int] = {}
    if omit_mode:
        used = 0
        max_rank = max((len(hits) for _qi, _qh, _q, hits in prepared), default=0)
        for rank in range(1, max_rank + 1):
            for query_index, _query_header, _query, hits in prepared:
                match = next((item for item in hits if item[0] == rank), None)
                if match is None:
                    continue
                hit_index, _hit, _source_header, body = match
                ref = f"Q{query_index}.H{hit_index}"
                full = len(body)
                if used + full <= body_budget:
                    included_caps[(query_index, hit_index)] = full
                    used += full
                    continue
                if min_body and full > min_body and used + min_body <= body_budget:
                    included_caps[(query_index, hit_index)] = min_body
                    used += min_body
                    continue
                omitted_refs.append(ref)

    groups: list[str] = []
    chunks: list[_ModelRagEvidenceChunk] = []
    source_index = 0
    for query_index, query_header, query, hits in prepared:
        group_parts = [query_header]
        for hit_index, hit, source_header, body in hits:
            if omit_mode and (query_index, hit_index) not in included_caps:
                continue
            visible_cap = (
                included_caps[(query_index, hit_index)] if omit_mode else body_cap
            )
            visible_body = body
            if len(visible_body) > visible_cap:
                visible_body = (
                    visible_body[: max(0, visible_cap - 1)].rstrip() + "…"
                    if visible_cap
                    else ""
                )
            source_index += 1
            group_parts.append(f"{source_header}:\n{visible_body}")
            meta = dict(getattr(hit, "meta", {}) or {})
            alias = f"Q{query_index}.H{hit_index}"
            identity_payload = "\x1f".join(
                (
                    str(evidence_namespace or "ordinary"),
                    alias,
                    str(getattr(hit, "doc_id", "") or ""),
                    str(meta.get("source_ref") or meta.get("chunk_id") or ""),
                    hashlib.sha256(visible_body.encode("utf-8")).hexdigest(),
                )
            )
            meta.update(
                {
                    "model_query_index": query_index,
                    "model_query_text": query,
                    "model_hit_index": hit_index,
                    "model_evidence_ref": alias,
                    "global_evidence_id": (
                        "evidence_"
                        + hashlib.sha256(identity_payload.encode("utf-8")).hexdigest()[:32]
                    ),
                    "evidence_namespace": str(evidence_namespace or "ordinary"),
                    "model_source_index": source_index,
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
    return groups, chunks, omitted_refs


def _model_rag_source_map(chunks: Sequence[_ModelRagEvidenceChunk]) -> list[dict[str, Any]]:
    return [source_map_item(chunk, index=index) for index, chunk in enumerate(chunks, 1)]


def _explicit_absence_value(value: Any) -> bool:
    if value is None:
        return True
    marker = str(value).strip().strip("*_` ").strip()
    if len(marker) >= 2 and (marker[0], marker[-1]) in {
        ("(", ")"),
        ("[", "]"),
    }:
        marker = marker[1:-1].strip()
    return marker.casefold() in {
        "",
        "—",
        "-",
        "–",
        "−",
        "нет",
        "н/д",
        "n/a",
        "na",
        "none",
        "группировка",
        "заголовок",
    }


def model_rag_row_kind(row: Mapping[str, Any]) -> str:
    """Classify a parsed row without rewriting model cells.

    Authored ``row_role`` wins when present so material/equipment decisions are
    not treated as install works for evidence/duplicate gates.
    """

    from proxy.services.lsr_source_coverage_service import canonicalize_row_role

    explicit = canonicalize_row_role(row.get("row_role"))
    if explicit in {"material", "equipment", "resource", "unresolved"}:
        return explicit
    if explicit == "work":
        return "work"

    unit_absent = _explicit_absence_value(row.get("unit"))
    quantity_absent = row.get("quantity") is None or _explicit_absence_value(
        row.get("quantity")
    )
    norm_absent = _explicit_absence_value(row.get("norm_code"))
    if unit_absent and quantity_absent and norm_absent:
        return "section_header"
    coverage = " ".join(
        str(row.get(name) or "") for name in ("analogue", "coverage", "note")
    )
    if norm_absent and "MISSING" in coverage.upper():
        return "missing"
    return "work"


def llm_usage_finish_reason(usage: Mapping[str, Any] | None) -> str:
    payload = usage if isinstance(usage, Mapping) else {}
    return str(payload.get("finish_reason") or payload.get("done_reason") or "").strip()


def finish_reason_is_length(reason: str) -> bool:
    return str(reason or "").strip().casefold() in _LENGTH_FINISH_REASONS


def packet_evidence_text(packet: ContextPacket) -> str:
    return "\n".join(
        obj.render()
        for section in packet.sections
        if section.kind is ContextKind.EVIDENCE
        for obj in section.objects
    )


def usage_with_finish_reason(
    usage: Mapping[str, Any] | None,
    finish_reason: str,
) -> dict[str, Any]:
    payload = dict(usage or {})
    reason = str(finish_reason or "").strip()
    if reason:
        payload["finish_reason"] = reason
    return payload


def attachment_context_is_truncated(text: str) -> bool:
    raw = str(text or "")
    return _TABULAR_TRUNCATION_MARK in raw or _PASTE_TRUNCATION_MARK in raw


def parse_attachment_sheet_coverage(text: str) -> dict[str, list[str]]:
    included: list[str] = []
    omitted: list[str] = []
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("Переданы листы:"):
            rest = stripped.split(":", 1)[1].strip()
            if rest and rest.casefold() != "нет":
                included = [item.strip() for item in rest.split(",") if item.strip()]
        elif stripped.startswith("Не переданы листы:"):
            rest = stripped.split(":", 1)[1].strip()
            if rest:
                omitted = [item.strip() for item in rest.split(",") if item.strip()]
    return {"included": included, "omitted": omitted}


def model_rag_answer_is_truncated(raw: str) -> bool:
    lines = [line.rstrip() for line in str(raw or "").splitlines() if line.strip()]
    if not lines:
        return False
    last = lines[-1]
    return last.startswith("|") and not last.endswith("|")


def _lsr_packaging_reasons(
    *,
    errors: Sequence[str],
    attachment_truncated: bool = False,
    included_sheets: Sequence[str] = (),
    omitted_sheets: Sequence[str] = (),
    rejected_queries: int = 0,
    omitted_evidence: int = 0,
) -> list[str]:
    reasons: list[str] = []
    if attachment_truncated or omitted_sheets:
        included = ", ".join(included_sheets) if included_sheets else "часть листов"
        omitted = ", ".join(omitted_sheets) if omitted_sheets else "остальные листы"
        reasons.append(f"исходник усечён (переданы: {included}; не переданы: {omitted})")
    if "answer_truncated" in errors:
        reasons.append("ответ модели оборван")
    incomplete = [
        error
        for error in errors
        if str(error).startswith("source_incomplete:")
    ]
    if incomplete or "source_incomplete" in errors:
        reasons.append("модели не переданы все строки исходника")
    qty_mismatch = [
        error.split(":", 1)[1]
        for error in errors
        if str(error).startswith("source_quantity_mismatch:")
    ]
    if qty_mismatch:
        preview = ", ".join(qty_mismatch[:5])
        extra = f" и ещё {len(qty_mismatch) - 5}" if len(qty_mismatch) > 5 else ""
        reasons.append(f"количество не совпадает с исходником у {preview}{extra}")
    missing_refs = [
        error.split(":", 1)[1]
        for error in errors
        if str(error).startswith("missing_evidence_ref:")
    ]
    if missing_refs:
        preview = ", ".join(missing_refs[:5])
        extra = f" и ещё {len(missing_refs) - 5}" if len(missing_refs) > 5 else ""
        reasons.append(f"нет evidence_ref у строк {preview}{extra}")
    skipped_prefixes = (
        "missing_evidence_ref:",
        "norm_code_not_in_referenced_evidence:",
        "source_quantity_mismatch:",
        "source_incomplete:",
        "source_coverage_incomplete:",
        "source_row_not_in_catalog:",
        "source_unit_mismatch:",
    )
    other = [
        str(error)
        for error in errors
        if error not in {"attachment_truncated", "answer_truncated"}
        and not any(str(error).startswith(prefix) for prefix in skipped_prefixes)
    ]
    if other:
        reasons.append(", ".join(other[:6]))
    if rejected_queries:
        reasons.append(f"отброшены повествовательные query-строки: {rejected_queries}")
    if omitted_evidence:
        reasons.append(f"не поместились полные карточки: {omitted_evidence}")
    coverage = [
        error.split(":", 1)[1]
        for error in errors
        if str(error).startswith("source_coverage_incomplete:")
    ]
    if coverage:
        reasons.append(f"покрытие исходника {coverage[0]}")
    return reasons or ["структурная проверка не пройдена"]


def format_lsr_not_created_notice(
    *,
    errors: Sequence[str],
    row_count: int,
    attachment_truncated: bool = False,
    included_sheets: Sequence[str] = (),
    omitted_sheets: Sequence[str] = (),
    rejected_queries: int = 0,
    omitted_evidence: int = 0,
) -> str:
    """Operator-visible reason that a workbook was not published."""

    reasons = _lsr_packaging_reasons(
        errors=errors,
        attachment_truncated=attachment_truncated,
        included_sheets=included_sheets,
        omitted_sheets=omitted_sheets,
        rejected_queries=rejected_queries,
        omitted_evidence=omitted_evidence,
    )
    return (
        f"ЛСР не создана: {'; '.join(reasons)}. "
        f"Строк в ответе модели: {row_count}."
    )


def format_lsr_partial_notice(
    *,
    errors: Sequence[str],
    row_count: int,
    attachment_truncated: bool = False,
    included_sheets: Sequence[str] = (),
    omitted_sheets: Sequence[str] = (),
    rejected_queries: int = 0,
    omitted_evidence: int = 0,
) -> str:
    """Visible reason that a workbook was published from an incomplete source/answer."""

    reasons = _lsr_packaging_reasons(
        errors=errors,
        attachment_truncated=attachment_truncated,
        included_sheets=included_sheets,
        omitted_sheets=omitted_sheets,
        rejected_queries=rejected_queries,
        omitted_evidence=omitted_evidence,
    )
    return (
        f"ЛСР собрана частично: {'; '.join(reasons)}. "
        f"В расчёт вошли {row_count} строк ответа модели; полный файл по всем "
        "листам исходника не утверждается."
    )


def format_lsr_unstructured_notice(*, sheet_pass_empty: bool = False) -> str:
    """Visible reason when the model answer is not an LSR row table."""

    if sheet_pass_empty:
        return (
            "ЛСР не создана: после поиска источников таблица строк не получена. "
            "Пустой поиск по запросу модели не считается ошибкой формата; "
            "незакрытые строки исходника остаются в задании."
        )
    return (
        "ЛСР не создана: ответ не разобран как таблица строк "
        "(нужны колонки наименования, единицы и шифра)."
    )


def format_lsr_packaged_notice(
    *,
    filename: str = "",
    status: str = "",
    pricing_status: str = "",
    norms_status: str = "",
    missing: Sequence[str] = (),
    blockers: Sequence[str] = (),
    readiness: Mapping[str, Any] | None = None,
) -> str:
    """Visible packaging outcome next to the workbook link."""

    if isinstance(readiness, Mapping) and readiness.get("dimensions"):
        return format_lsr_readiness_notice(readiness, filename=filename)

    missing_items = [str(item).strip() for item in missing if str(item).strip()]
    blocker_items = [str(item).strip() for item in blockers if str(item).strip()]
    unbound = [item for item in missing_items if item.startswith("row:")]
    unpriced = [item for item in missing_items if item.startswith("price_missing:")]
    other = [
        item for item in missing_items if item not in unbound and item not in unpriced
    ]
    file_bit = f" Файл: {filename}." if filename else ""
    incomplete = bool(
        unbound
        or unpriced
        or other
        or blocker_items
        or status == "partial"
        or pricing_status in {"priced_partial", "norm_selection_required"}
        or (norms_status and norms_status != "norms_verified")
    )
    if not incomplete:
        return f"ЛСР собрана.{file_bit}".strip()
    fallback = build_lsr_result_readiness(
        packaged=True,
        packaging_failed=False,
        rows=(),
        missing=missing_items,
        pricing_status=pricing_status,
    )
    notice = format_lsr_readiness_notice(fallback, filename=filename)
    if blocker_items:
        notice += " Блокеры: " + ", ".join(blocker_items[:6]) + "."
    if other:
        notice += " Замечания: " + ", ".join(other[:6]) + "."
    return notice


def validate_model_rag_result_structure(
    rows: Sequence[dict[str, Any]],
    evidence_chunks: Sequence[Any],
    *,
    expected_source_rows: int,
    attachment_truncated: bool = False,
    answer_truncated: bool = False,
    source_catalog: AttachmentSourceCatalog | None = None,
    source_incomplete_locators: Sequence[str] = (),
    finish_reason: str = "",
    validate_evidence_refs: bool = True,
) -> list[str]:
    """Validate references before packaging without changing model decisions."""

    errors: list[str] = []
    if attachment_truncated:
        errors.append("attachment_truncated")
    if answer_truncated or finish_reason_is_length(finish_reason):
        errors.append("answer_truncated")
    if source_incomplete_locators:
        errors.append(
            "source_incomplete:"
            + ",".join(list(source_incomplete_locators)[:8])
        )
    observed_keys: set[tuple[str, str, str, str]] = set()
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
        # One locator may legally carry several distinct operations, even with
        # the same role. Duplicate means the identical content was authored
        # twice; distinct content on one locator is the two-operations pattern.
        source_key = (
            type(source_row).__name__,
            str(source_row),
            _decision_role_key(row),
            _decision_identity_sha(row),
        )
        if source_key in observed_keys:
            errors.append(f"duplicate_source_row:{source_row}")
        observed_keys.add(source_key)

    evidence_by_ref: dict[str, dict[str, Any]] = {}
    evidence_by_global_id: dict[str, dict[str, Any]] = {}
    for chunk in evidence_chunks:
        meta = dict(getattr(chunk, "meta", {}) or {})
        evidence_ref = str(meta.get("model_evidence_ref") or "").strip().upper()
        if evidence_ref:
            evidence_by_ref[evidence_ref] = meta
        global_id = str(meta.get("global_evidence_id") or "").strip()
        if global_id:
            evidence_by_global_id[global_id] = meta

    def code_identity(value: Any) -> str:
        return "".join(
            character
            for character in str(value or "").strip().casefold()
            if not character.isspace() and character != ":"
        )

    for row in rows:
        if model_rag_row_kind(row) != "work":
            continue
        source_row = row.get("source_row")
        if source_catalog is not None:
            errors.extend(compare_model_row_to_catalog(row, source_catalog))
        if not validate_evidence_refs:
            continue
        refs = extract_model_evidence_refs(row.get("evidence_refs"))
        if not refs:
            errors.append(f"missing_evidence_ref:{source_row}")
            continue
        raw_bindings = row.get("evidence_bindings")
        bindings = (
            {
                str(alias).strip().upper(): str(global_id).strip()
                for alias, global_id in raw_bindings.items()
                if str(alias).strip() and str(global_id).strip()
            }
            if isinstance(raw_bindings, Mapping)
            else {}
        )
        if bindings:
            unknown_refs: list[str] = []
            referenced_meta: list[dict[str, Any]] = []
            for ref in refs:
                global_id = bindings.get(ref, "")
                if global_id and global_id in evidence_by_global_id:
                    referenced_meta.append(evidence_by_global_id[global_id])
                    continue
                if not global_id and ref in evidence_by_ref:
                    referenced_meta.append(evidence_by_ref[ref])
                    continue
                unknown_refs.append(ref)
        else:
            unknown_refs = [ref for ref in refs if ref not in evidence_by_ref]
            referenced_meta = [
                evidence_by_ref[ref] for ref in refs if ref in evidence_by_ref
            ]
        errors.extend(f"unknown_evidence_ref:{ref}" for ref in unknown_refs)
        selected_code = (
            ""
            if _explicit_absence_value(row.get("norm_code"))
            else code_identity(row.get("norm_code"))
        )
        if selected_code and not any(
            (
                (evidence_code := code_identity(meta.get("norm_code")))
                and evidence_code in selected_code
            )
            for meta in referenced_meta
        ):
            errors.append(f"norm_code_not_in_referenced_evidence:{source_row}")
    if source_catalog is not None:
        errors.extend(coverage_errors(rows, source_catalog))
    return list(dict.fromkeys(errors))


def blocking_model_rag_result_errors(
    errors: Sequence[str],
    *,
    work_row_count: int = 0,
) -> list[str]:
    """Keep evidence-code disagreement visible without withholding the model draft.

    Governor omissions and a cut-off last table line do not drop already parsed
    work rows. A missing or unknown Qx.Hy on one work row stays visible and
    unpriced; it does not withhold the workbook when other work rows exist.
    Quantity mismatch still blocks the file.
    """

    advisory_prefixes = (
        "norm_code_not_in_referenced_evidence:",
        "source_row_not_in_catalog:",
        "source_coverage_incomplete:",
        "source_unit_mismatch:",
        "source_incomplete:",
    )
    if int(work_row_count or 0) > 0:
        advisory_prefixes = (
            *advisory_prefixes,
            "missing_evidence_ref:",
            "unknown_evidence_ref:",
        )
    advisory_exact = {"answer_truncated", "workbook_research_cancelled"} if int(work_row_count or 0) > 0 else {"workbook_research_cancelled"}
    return [
        error
        for error in errors
        if not str(error).startswith(advisory_prefixes)
        and str(error) not in advisory_exact
    ]


def model_rag_search_tool_schema() -> list[dict[str, Any]]:
    """Expose the selected datasets as one native search tool."""

    return native_model_tool_schemas(
        [
            {
                "name": "search_sources",
                "summary": "Искать evidence в явно выбранных датасетах",
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


def selector_evidence_payload(
    *,
    attachment_context: str,
    rendered_context: str,
    source_catalog: AttachmentSourceCatalog | None = None,
    sheet: str = "",
    remaining_work: Sequence[str] | None = None,
) -> list[Any]:
    """Return model evidence as independently packable, ordered source blocks."""

    payload: list[Any] = []
    if source_catalog is not None and source_catalog.rows:
        payload.append(source_catalog.manifest_text())
        wanted_sheet = str(sheet or "").strip()
        if wanted_sheet:
            names = catalog_work_sheet_names(source_catalog) or [
                name for name, _count in source_catalog.sheets
            ]
            index = names.index(wanted_sheet) + 1 if wanted_sheet in names else 1
            payload.append(
                f"Текущий шаг: лист «{wanted_sheet}» ({index}/{len(names) or 1}). "
                "Другие листы манифеста будут отдельными шагами; не отказывайся из‑за них."
            )
            payload.extend(
                catalog_sheet_pack_lines(
                    source_catalog,
                    wanted_sheet,
                    remaining_work=remaining_work,
                )
            )
        else:
            payload.extend(source_catalog.interleaved_row_lines())
    elif str(attachment_context or "").strip():
        payload.append("Текст явно прикреплённого пользователем файла:")
        payload.extend(_bounded_source_blocks(attachment_context))
    payload.append("Материалы из найденных документов:")
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
    if (
        str(snapshot.get("mode") or "").strip().casefold() == "estimator"
        or profile_uses_tabular_estimator_path(snapshot)
    ):
        parts.append(_TABULAR_LSR_VOLUME_INSTRUCTION)
    return "\n\n".join(parts)


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
    profile_snapshot, source_catalog, tabular_estimator_bound = bind_tabular_estimator_profile(
        profile_snapshot,
        attachment_id=str(getattr(req, "attachment_id", "") or ""),
    )
    document_grounding_enabled = bool(
        (scope_resolution or {}).get("document_grounding_enabled", _dataset_ids)
    )
    if tabular_estimator_bound:
        document_grounding_enabled = True
        from proxy.services.chat_profile_service import resolve_profile_system_dataset_ids

        _dataset_ids = tuple(
            resolve_profile_system_dataset_ids(
                profile_snapshot,
                current_dataset_ids=_dataset_ids,
            )
        )
    if document_grounding_enabled:
        use_semantic_cache = False
    # Ordinary chat is model-owned: validators may not judge, retry, rewrite,
    # suppress, or relabel the model's engineering conclusion.
    use_validation = False
    memory_project_id = 0
    workspace_memory_registered = False
    project_memory_advisory = ""
    try:
        memory_project_id, workspace_memory_registered = resolve_session_memory_scope(
            str(req.session_id or ""), int(getattr(req, "project_id", 0) or 0) or None,
        )
        memory_project_id = int(memory_project_id or 0)
        if memory_project_id > 0 and not workspace_memory_registered:
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

    stamp_empty_retrieval(
        retrieval_trace,
        model_driven=profile_uses_model_driven_retrieval(profile_snapshot),
        chunks=chunks,
    )

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
    from proxy.services.freetoken_cache_profile_service import cache_alignment_target

    active_connection = (
        resolved_connection if canonical_execution_mode is CanonicalRouteMode.ACTIVE else None
    )
    gen_semaphore = (
        state.llm_semaphore
        if active_connection is not None and active_connection.locality is not ConnectionLocality.REMOTE
        else generation_semaphore(state.llm_semaphore)
    )
    cache_target = cache_alignment_target(llm_runtime, active_connection=active_connection)
    cache_state: dict[str, Any] = {}
    if cache_target is not None:
        cache_base_url, cache_model = cache_target
        from proxy.services.freetoken_cache_profile_service import (
            DEFAULT_FREETOKEN_CONTEXT_TOKENS,
            admitted_cache_call,
            align_freetoken_cache_for_turn,
            desired_kv_for_answer_model,
            reconcile_freetoken_cache,
        )
        from proxy.services.model_execution_preset_service import (
            MIN_EXTENDED_35B_CONTEXT_TOKENS,
            is_qwen_35b,
        )

        desired_kv = desired_kv_for_answer_model(
            cache_model,
            _env_int("FREETOKEN_CONTEXT_TOKENS", DEFAULT_FREETOKEN_CONTEXT_TOKENS),
        )
        if (
            resolved_connection is not None
            and resolved_connection.requested_context_tokens
        ):
            desired_kv = desired_kv_for_answer_model(
                cache_model,
                int(resolved_connection.requested_context_tokens),
            )
        if canonical_execution_mode is CanonicalRouteMode.ACTIVE:
            # Rebuild once at HTTP-turn start if 35B is still on a legacy 8k
            # window. Packet loops must not call this; mid-generation rebuild
            # is still forbidden.
            cache_state = await admitted_cache_call(
                align_freetoken_cache_for_turn,
                cache_base_url,
                semaphore=gen_semaphore,
                timeout_seconds=generation_slot_timeout_seconds(),
                model_id=cache_model,
                requested_kv=desired_kv,
                allow_rebuild=True,
            )
            try:
                live_kv = int(cache_state.get("effective_kv_tokens") or 0)
            except (TypeError, ValueError):
                live_kv = 0
            if is_qwen_35b(cache_model) and (
                cache_state.get("status") not in {"aligned", "synchronized"}
                or live_kv < MIN_EXTENDED_35B_CONTEXT_TOKENS
            ):
                raise HTTPException(
                    503,
                    "FreeToken KV не готов для 35B: "
                    + str(cache_state.get("reason") or cache_state.get("status")),
                )
        else:
            cache_state = await admitted_cache_call(
                reconcile_freetoken_cache,
                cache_base_url,
                desired_kv,
                semaphore=gen_semaphore,
                timeout_seconds=generation_slot_timeout_seconds(),
            )
            if cache_state.get("status") not in {"aligned", "synchronized"}:
                raise HTTPException(
                    503,
                    "FreeToken KV не синхронизирован: "
                    + str(cache_state.get("reason") or cache_state.get("status")),
                )
        retrieval_trace["freetoken_cache"] = cache_state
    observed_context_tokens = None
    observed_context = False
    observed_source = "unavailable"
    if cache_state.get("status") in {"aligned", "synchronized", "mismatch"}:
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
        if observed_context_tokens is not None:
            execution_preset = resolve_connection_execution_profile(
                model_id=resolved_connection.model_id,
                requested_context_tokens=resolved_connection.requested_context_tokens,
                observed_context_tokens=observed_context_tokens,
                observed_source=observed_source,
            )
        else:
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
            "project_id": typed_memory.project_id,
            "registered_session": workspace_memory_registered,
            "item_ids": [item.item_id for item in typed_memory.items],
            "omitted_item_ids": list(typed_memory.omitted_item_ids),
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

    # ADR-12 слой 2: форму ответа диктует интент вопроса (детерминированно, до генерации).
    answer_form = apply_response_length(classify_answer_form(req.question), req.response_length)
    retrieval_trace["answer_form"] = {"intent": answer_form.intent, "max_tokens": answer_form.max_tokens}
    if class_suggestions:
        retrieval_trace["class_suggestions"] = [s["class"] for s in class_suggestions]

    # Облако не держит локальный Metal-слот: отдельный пул (LES_CLOUD_LLM_CONCURRENCY).

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
    source_incomplete_locators: list[str] = []
    answer_finish_reason = ""
    model_driven_retrieval = profile_uses_model_driven_retrieval(profile_snapshot)
    sheet_pass_active = sheet_pass_should_run(
        source_catalog,
        tabular_estimator_bound=tabular_estimator_bound,
        model_driven=model_driven_retrieval,
    )
    comparative_variant = str(
        getattr(req, "comparative_acceptance_variant", "") or ""
    ).upper()
    if comparative_variant == "B0_DIRECT":
        sheet_pass_active = False
    if comparative_variant:
        retrieval_trace["comparative_acceptance"] = {
            "variant": comparative_variant,
            "sheet_packet_harness": comparative_variant == "B1_CANDIDATE",
            "model_owned_query_rag_result": True,
        }
    sheet_pass_names = (
        catalog_work_sheet_names(source_catalog)
        if sheet_pass_active and source_catalog is not None
        else []
    )
    sheet_pass_first = sheet_pass_names[0] if sheet_pass_names else ""

    selector_evidence = selector_evidence_payload(
        attachment_context=attachment_context,
        rendered_context=initial_selector_context(
            context,
            model_authored_initial_query=model_driven_retrieval,
        ),
        source_catalog=source_catalog,
        sheet=sheet_pass_first,
        remaining_work=(
            catalog_sheet_work_locators(source_catalog, sheet_pass_first)
            if sheet_pass_first and source_catalog is not None
            else None
        ),
    )
    selector_source_map = answer_source_map
    async with acquire_generation_slot(
        gen_semaphore,
        timeout_seconds=generation_slot_timeout_seconds(),
    ):
        try:
            async with httpx.AsyncClient(timeout=model_answer_timeout_seconds()) as client:
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

                async def _post_llm(runtime, model, hdrs, body, *, allow_stream: bool = True):
                    """Один вызов LLM. token_sink задан → стрим (токены клиенту по
                    мере генерации), иначе — обычный POST (поведение неизменно).
                    Возвращает (answer_text, usage_dict)."""
                    nonlocal active_model_result, active_pending_tool_calls
                    if bound_runner is not None:
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
                        return (
                            model_text,
                            usage_with_finish_reason(
                                dict(active_model_result.response.usage),
                                active_model_result.response.finish_reason,
                            ),
                        )
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
                        stream_finish = ""
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
                                if choices:
                                    stream_finish = str(
                                        choices[0].get("finish_reason") or stream_finish
                                    )
                                if chunk.get("usage"):
                                    usage_d = chunk["usage"]
                        return "".join(acc), usage_with_finish_reason(usage_d, stream_finish)
                    r = await client.post(runtime.chat_url, headers=hdrs, json={**_body, "model": model})
                    r.raise_for_status()
                    rj = r.json()
                    choice = (rj.get("choices") or [{}])[0]
                    return (
                        _assistant_text(choice.get("message", {})),
                        usage_with_finish_reason(
                            rj.get("usage", {}) or {},
                            str(choice.get("finish_reason") or ""),
                        ),
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
                rejected_model_queries: list[str] = []
                omitted_evidence_refs: list[str] = []
                model_rag_evidence_groups: list[str] = []
                sheet_pass_done = False
                sheet_pass_rows: list[dict[str, Any]] = []
                research_cancelled = False
                # Durable research-job handles stay unbound unless the sheet-pass
                # route initializes them; the packaging tail reads them regardless,
                # so they are pre-bound to None here (local annotations are not
                # evaluated at runtime).
                research_job_service: WorkbookResearchJobService | None = None
                research_job: dict[str, Any] | None = None
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
                query_headers: dict[str, str] = {}
                model_research_tools = None
                retrieval_limits = effective_retrieval_policy(profile_snapshot)
                if model_driven_retrieval and tool_loop_enabled and not sheet_pass_active:
                    retrieval_limits = effective_retrieval_policy(profile_snapshot)
                    query_headers = {}
                    if llm_runtime.api_key:
                        query_headers["Authorization"] = f"Bearer {llm_runtime.api_key}"
                    query_instructions = [
                        model_rag_query_instruction(profile_snapshot),
                        (
                            model_rag_query_instruction(profile_snapshot)
                            + "\n\n"
                            + _MODEL_RAG_QUERY_REPAIR_INSTRUCTION
                        ),
                    ]
                    model_queries = []
                    rejected_model_queries = []
                    for query_attempt, query_instruction in enumerate(query_instructions, start=1):
                        query_messages, query_packet = govern_inference_messages(
                            preset=execution_preset,
                            profile_prefix=(
                                profile_system_prompt(profile_snapshot, strict=False)
                                + "\n\n"
                                + query_instruction
                            ),
                            request_payload={
                                "question": str(req.question or ""),
                                "dataset_ids": [str(item) for item in _dataset_ids],
                            },
                            checkpoint=(),
                            working_memory=workspace_note_objects(
                                memory_candidates, registered=workspace_memory_registered,
                            ),
                            evidence=selector_evidence,
                            source_map=selector_source_map,
                            tool_exchange=(),
                        )
                        retrieval_trace["context_governor"]["calls"].append(
                            context_packet_trace(
                                query_packet,
                                purpose=(
                                    "model_rag_queries"
                                    if query_attempt == 1
                                    else "model_rag_query_repair"
                                ),
                            )
                        )
                        query_body = {
                            "messages": query_messages,
                            "stream": False,
                            "temperature": 0,
                            "max_tokens": max(
                                256,
                                _env_int("LES_CHAT_MODEL_RAG_QUERY_MAX_TOKENS", 1600),
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
                        model_queries, rejected_model_queries = classify_model_rag_query_lines(
                            query_text
                        )
                        if model_queries:
                            break
                    if not model_queries:
                        raise HTTPException(
                            status_code=503,
                            detail="MODEL_RAG_QUERY_LIST_EMPTY",
                        )

                    async def _no_model_rag_fallback(_tool_name: str, _args: dict[str, Any]):
                        raise RuntimeError("MODEL_RAG_ONLY_SUPPORTS_SEARCH_SOURCES")

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
                            retrieve_smeta_norm_cards
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
                                    : retrieval_limits["model_evidence_k"]
                                ],
                            )
                        )
                    blocked_queries = [
                        index
                        for index, payload in enumerate(tool_results_for_model, 1)
                        if model_search_result_blocks_packet(payload)
                    ]
                    if blocked_queries:
                        raise HTTPException(
                            status_code=503,
                            detail={
                                "error": "MODEL_RAG_SEARCH_INCOMPLETE",
                                "blocked_queries": blocked_queries,
                            },
                        )
                    (
                        model_rag_evidence_groups,
                        model_evidence_chunks,
                        omitted_evidence_refs,
                    ) = build_model_rag_evidence_groups(
                        model_rag_query_hits,
                        max_chars=context_chars_limit,
                        hits_per_query=retrieval_limits["model_evidence_k"],
                    )
                    context = "\n\n".join(model_rag_evidence_groups)
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
                        "model_queries": model_queries,
                        "query_usage": query_usage,
                        "results": tool_results_for_model,
                        "evidence_groups": [
                            f"Q{index}" for index in range(1, len(model_rag_evidence_groups) + 1)
                        ],
                        "hits_per_query": [
                            len(hits) for _query, hits in model_rag_query_hits
                        ],
                        "rejected_queries": rejected_model_queries,
                        "omitted_evidence_refs": omitted_evidence_refs,
                    }
                elif model_driven_retrieval and tool_loop_enabled and sheet_pass_active:
                    retrieval_limits = effective_retrieval_policy(profile_snapshot)
                    query_headers = {}
                    if llm_runtime.api_key:
                        query_headers["Authorization"] = f"Bearer {llm_runtime.api_key}"

                    async def _no_model_rag_fallback(_tool_name: str, _args: dict[str, Any]):
                        raise RuntimeError("MODEL_RAG_ONLY_SUPPORTS_SEARCH_SOURCES")

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
                            retrieve_smeta_norm_cards
                            if profile_uses_smeta_norm_retrieval(profile_snapshot)
                            else None
                        ),
                        **retrieval_limits,
                    )
                    retrieval_trace["tool_loop"] = {
                        "schema": "les_model_rag_sheet_pass_v1",
                        "enabled": True,
                        "model_owns_queries": True,
                        "passes": [],
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
                            question=str(getattr(req, "question", "") or ""),
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
                            selector_profile = "".join(
                                (
                                    profile_tool_selector_prompt(profile_snapshot),
                                    "\n\nТы управляешь коротким исследовательским чтением LES. ",
                                    "Явно прикреплённый текст ниже уже доступен тебе как evidence и не требует индексации. "
                                    "Сначала прочитай его и используй read-only инструменты, чтобы закрыть конкретные пробелы. "
                                    "Если оператор просит артефакт, после получения достаточного evidence вызови "
                                    "подходящий draft-инструмент; предметные решения и поисковые запросы выбираешь ты. "
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
                            calls = list(proposed_calls[:calls_remaining])
                            research_rounds.append(
                                {"round": research_round, "proposed": len(proposed_calls), "executed": len(calls)}
                            )
                            if not calls:
                                stop_reason = "model_stop"
                                break
                            for call in calls:
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
                                            source_catalog=source_catalog,
                                        )
                                        selector_source_map = answer_source_map
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
                if (
                    sheet_pass_active
                    and model_driven_retrieval
                    and tool_loop_enabled
                    and source_catalog is not None
                    and sheet_pass_names
                ):
                    async def _emit_sheet_progress(
                        label: str,
                        *,
                        completed: int,
                        total: int,
                        extra: Mapping[str, Any] | None = None,
                    ) -> None:
                        if token_sink is None:
                            return
                        await token_sink(
                            {
                                "event": "tool_progress",
                                "data": {
                                    "label": label,
                                    "completed": completed,
                                    "total": total,
                                    **dict(extra or {}),
                                    **(
                                        {
                                            "workbook_research_job_id": str(
                                                research_job.get("job_id") or ""
                                            )
                                        }
                                        if research_job is not None
                                        else {}
                                    ),
                                },
                            }
                        )

                    async def _sheet_pass_llm(chat_body, *, purpose: str = "sheet_pass_answer"):
                        nonlocal llm_model
                        if canonical_execution_mode is CanonicalRouteMode.ACTIVE:
                            text, usage = await _post_llm(
                                llm_runtime,
                                llm_model,
                                (
                                    {"Authorization": f"Bearer {llm_runtime.api_key}"}
                                    if llm_runtime.api_key
                                    else {}
                                ),
                                chat_body,
                                allow_stream=False,
                            )
                            if active_model_result is not None:
                                llm_model = active_model_result.connection.model_id
                        elif is_cloud_provider(llm_runtime.provider):
                            text, usage, llm_model = await _post_cloud_fallback(
                                llm_runtime,
                                (
                                    {"Authorization": f"Bearer {llm_runtime.api_key}"}
                                    if llm_runtime.api_key
                                    else {}
                                ),
                                chat_body,
                                allow_stream=False,
                            )
                        else:
                            text, usage = await _post_llm(
                                llm_runtime,
                                llm_model,
                                (
                                    {"Authorization": f"Bearer {llm_runtime.api_key}"}
                                    if llm_runtime.api_key
                                    else {}
                                ),
                                chat_body,
                                allow_stream=False,
                            )
                        append_actual_model_call(
                            retrieval_trace,
                            purpose=purpose,
                            finish_reason=llm_usage_finish_reason(usage),
                            completion_tokens=int(
                                (usage or {}).get("completion_tokens") or 0
                            ),
                        )
                        return text, usage

                    sheet_sys_msg = sys_normal + (
                        f" {answer_form.instruction}" if answer_form.instruction else ""
                    )
                    if req.output_directive and req.output_directive.strip():
                        sheet_sys_msg += " " + req.output_directive.strip()
                    research_job_service: WorkbookResearchJobService | None = None
                    research_job: dict[str, Any] | None = None
                    attachment_id = str(getattr(req, "attachment_id", "") or "")
                    if attachment_id and source_catalog.source_file_sha256:
                        try:
                            research_job_service = WorkbookResearchJobService()
                            research_identity = research_job_service.identity(
                                session_id=str(req.session_id or ""),
                                attachment_id=attachment_id,
                                source_sha256=source_catalog.source_file_sha256,
                                dataset_ids=[str(item) for item in _dataset_ids],
                                profile_revision_id=str(
                                    (profile_snapshot or {}).get("revision_id") or ""
                                ),
                                model_identity=str(
                                    getattr(
                                        getattr(active_model_result, "connection", None),
                                        "model_id",
                                        "",
                                    )
                                    or llm_model
                                ),
                                question=str(req.question or ""),
                            )
                            research_job = research_job_service.begin_or_resume(
                                research_identity
                            )
                        except Exception as job_error:  # noqa: BLE001 - durability degrades visibly
                            logger.exception(
                                "[WORKBOOK_RESEARCH] durable checkpoint unavailable: %s",
                                type(job_error).__name__,
                            )
                            retrieval_trace["workbook_research_job"] = {
                                "schema": "les.workbook-research-job.v1",
                                "status": "durability_unavailable",
                                "error_type": type(job_error).__name__,
                            }
                            research_job_service = None
                            research_job = None
                    accumulated_rows: list[dict[str, Any]] = [
                        dict(item)
                        for item in ((research_job or {}).get("accepted_rows") or ())
                        if isinstance(item, Mapping)
                    ]
                    sheet_pass_evidence_chunks: list[_ModelRagEvidenceChunk] = [
                        evidence_chunk_from_record(item)
                        for item in ((research_job or {}).get("evidence") or ())
                        if isinstance(item, Mapping)
                    ]
                    answer_parts: list[str] = []
                    any_sheet_queries = False
                    last_finish = ""
                    last_truncated = False
                    pass_rejected: list[str] = []
                    pass_omitted: list[str] = list(
                        (research_job or {}).get("omitted") or ()
                    )
                    research_cancelled = False
                    sheet_query_cache: dict[str, list[dict[str, Any]]] = {
                        str(key): [
                            dict(item)
                            for item in (value or [])
                            if isinstance(item, Mapping)
                        ]
                        for key, value in (
                            ((research_job or {}).get("query_cache") or {})
                            if isinstance((research_job or {}).get("query_cache"), dict)
                            else {}
                        ).items()
                        if str(key).strip()
                    }
                    stored_held = (
                        (research_job or {}).get("held_packet")
                        if isinstance((research_job or {}).get("held_packet"), dict)
                        else {}
                    )
                    sheet_count = len(sheet_pass_names)
                    work_total = len(source_catalog.work_locators())
                    session_accepted_start = len(
                        structurally_complete_source_keys(
                            accumulated_rows, source_catalog
                        )
                    )
                    prior_elapsed = float(
                        (research_job or {}).get("prior_elapsed_seconds") or 0.0
                    )

                    async def _emit_row_progress(
                        stage: str, *, sheet: str, index: int
                    ) -> None:
                        accepted_now = len(
                            structurally_complete_source_keys(
                                accumulated_rows, source_catalog
                            )
                        )
                        counts = sheet_pass_progress_counts(
                            accepted_now=accepted_now,
                            work_total=work_total,
                            session_accepted_start=session_accepted_start,
                            prior_elapsed_seconds=prior_elapsed,
                        )
                        extra = {
                            key: value
                            for key, value in counts.items()
                            if key not in {"completed", "total"}
                        }
                        await _emit_sheet_progress(
                            sheet_pass_progress_label(
                                sheet,
                                sheet_index=index,
                                sheet_count=sheet_count,
                                stage=stage,
                                resumed=bool(counts["resumed"]),
                            ),
                            completed=int(counts["completed"]),
                            total=int(counts["total"]),
                            extra=extra,
                        )

                    if session_accepted_start > 0 and sheet_pass_names:
                        await _emit_row_progress(
                            "поиск норм",
                            sheet=sheet_pass_names[0],
                            index=1,
                        )
                    owns_sheet_pass = True
                    live_job_id = str((research_job or {}).get("job_id") or "")
                    if live_job_id:
                        owns_sheet_pass = await claim_or_join_sheet_pass(live_job_id)
                    try:
                      if not owns_sheet_pass:
                        logger.info(
                            "[SHEET_PASS] joined live job=%s; skip duplicate packet loop",
                            live_job_id,
                        )
                        if research_job_service is not None and live_job_id:
                            research_job = research_job_service.get(live_job_id) or research_job
                        accumulated_rows = [
                            dict(item)
                            for item in ((research_job or {}).get("accepted_rows") or ())
                            if isinstance(item, Mapping)
                        ]
                        sheet_pass_names = ()
                      for sheet_index, sheet_name in enumerate(sheet_pass_names, start=1):
                        if (
                            research_job_service is not None
                            and research_job is not None
                            and research_job_service.should_cancel(research_job["job_id"])
                        ):
                            research_cancelled = True
                            break
                        remaining = remaining_sheet_work_locators(
                            source_catalog,
                            sheet_name,
                            structurally_complete_source_keys(accumulated_rows, source_catalog),
                        )
                        exhausted_locators: set[str] = set()
                        # Rows already put to the model in this sheet pass.  The
                        # packet pool is ordered least-offered-first so no row can
                        # be starved by a leading row that keeps a quality gap.
                        offered_locators: set[str] = set()
                        packet_attempts: dict[tuple[str, ...], int] = {}
                        offer_counts: dict[str, int] = {}
                        if (
                            research_job_service is not None
                            and isinstance(research_job, Mapping)
                            and research_job.get("job_id")
                        ):
                            # A restarted process must continue attempt numbering
                            # from the durable checkpoints, so a Qx.Hy reference
                            # can never address another attempt's cards.  The same
                            # checkpoints carry how often each row was already put
                            # to the model, which is what keeps the rotation across
                            # the pass boundary instead of restarting it at the head
                            # of the sheet.
                            checkpoint_events = research_job_service.list_events(
                                str(research_job["job_id"]),
                                event_type="packet_checkpoint",
                            )
                            packet_attempts = packet_attempt_seed(checkpoint_events)
                            offer_counts = packet_offer_counts(checkpoint_events)
                        locator_research_round: dict[str, int] = {}
                        inner = 0
                        deferred_query_hits: list[tuple[str, Sequence[Any]]] = []
                        held_packet: list[str] = []
                        if (
                            str(stored_held.get("sheet") or "") == sheet_name
                            and stored_held.get("queries")
                        ):
                            held_packet = [
                                locator
                                for locator in (stored_held.get("locators") or [])
                                if locator in remaining
                            ]
                            deferred_query_hits = restore_query_hits_from_cache(
                                [
                                    str(item)
                                    for item in (stored_held.get("queries") or [])
                                    if str(item).strip()
                                ],
                                sheet_query_cache,
                            )
                            stored_held = {}
                        while remaining:
                            if (
                                research_job_service is not None
                                and research_job is not None
                                and research_job_service.should_cancel(
                                    research_job["job_id"]
                                )
                            ):
                                research_cancelled = True
                                break
                            reuse_hits = list(deferred_query_hits)
                            deferred_query_hits = []
                            if reuse_hits:
                                packet = [
                                    locator
                                    for locator in held_packet
                                    if locator in remaining
                                ]
                                if not packet:
                                    pass_omitted.extend(
                                        model_rag_query_hit_refs(
                                            reuse_hits,
                                            hits_per_query=retrieval_limits[
                                                "model_evidence_k"
                                            ],
                                            query_offset=0,
                                        )
                                    )
                                    held_packet = []
                                    continue
                                offered_locators.update(packet)
                                fingerprint = tuple(packet)
                                packet_attempts.setdefault(fingerprint, 1)
                                inner += 1
                                cited_before = structurally_complete_source_keys(
                                    accumulated_rows, source_catalog
                                )
                                pass_evidence = selector_evidence_payload(
                                    attachment_context=attachment_context,
                                    rendered_context="",
                                    source_catalog=source_catalog,
                                    sheet=sheet_name,
                                    remaining_work=packet,
                                )
                                selector_evidence = pass_evidence
                                pass_hits = reuse_hits
                                model_rag_query_hits = pass_hits
                                model_queries = [
                                    query for query, _hits in pass_hits
                                ]
                                any_sheet_queries = True
                            else:
                                held_packet = []
                                packet = adaptive_row_packet(
                                    remaining,
                                    generation_reserve_tokens=(
                                        answer_execution_preset.generation_reserve_tokens
                                    ),
                                    already_offered=tuple(sorted(offered_locators)),
                                    offer_counts=offer_counts,
                                )
                                if not packet:
                                    break
                                offered_locators.update(packet)
                                fingerprint = tuple(packet)
                                packet_attempts[fingerprint] = packet_attempts.get(fingerprint, 0) + 1
                                inner += 1
                                cited_before = structurally_complete_source_keys(
                                    accumulated_rows, source_catalog
                                )
                                await _emit_row_progress(
                                    "поиск норм",
                                    sheet=sheet_name,
                                    index=sheet_index,
                                )
                                pass_evidence = selector_evidence_payload(
                                    attachment_context=attachment_context,
                                    rendered_context="",
                                    source_catalog=source_catalog,
                                    sheet=sheet_name,
                                    remaining_work=packet,
                                )
                                selector_evidence = pass_evidence
                                query_text = ""
                                model_queries = []
                                rejected_now: list[str] = []
                                packet_round = max(
                                    (locator_research_round.get(str(item), 0) for item in packet),
                                    default=0,
                                )
                                query_instructions = [
                                    sheet_pass_query_instruction(
                                        profile_snapshot,
                                        sheet=sheet_name,
                                        sheet_index=sheet_index,
                                        sheet_count=sheet_count,
                                        research_round=packet_round,
                                    ),
                                    (
                                        sheet_pass_query_instruction(
                                            profile_snapshot,
                                            sheet=sheet_name,
                                            sheet_index=sheet_index,
                                            sheet_count=sheet_count,
                                            research_round=packet_round,
                                        )
                                        + "\n\n"
                                        + _MODEL_RAG_QUERY_REPAIR_INSTRUCTION
                                    ),
                                ]
                                try:
                                    for query_attempt, query_instruction in enumerate(
                                        query_instructions, start=1
                                    ):
                                        query_messages, query_packet = govern_inference_messages(
                                            preset=execution_preset,
                                            profile_prefix=(
                                                profile_system_prompt(
                                                    profile_snapshot, strict=False
                                                )
                                                + "\n\n"
                                                + query_instruction
                                            ),
                                            request_payload={
                                                "question": str(req.question or ""),
                                                "dataset_ids": [
                                                    str(item) for item in _dataset_ids
                                                ],
                                            },
                                            checkpoint=(),
                                            working_memory=workspace_note_objects(
                                                memory_candidates,
                                                registered=workspace_memory_registered,
                                            ),
                                            evidence=pass_evidence,
                                            source_map=selector_source_map,
                                            tool_exchange=(),
                                        )
                                        retrieval_trace["context_governor"]["calls"].append(
                                            context_packet_trace(
                                                query_packet,
                                                purpose=(
                                                    "model_rag_sheet_queries"
                                                    if query_attempt == 1
                                                    else "model_rag_sheet_query_repair"
                                                ),
                                            )
                                        )
                                        query_body = {
                                            "messages": query_messages,
                                            "stream": False,
                                            "temperature": 0,
                                            "max_tokens": max(
                                                256,
                                                _env_int(
                                                    "LES_CHAT_MODEL_RAG_QUERY_MAX_TOKENS",
                                                    1600,
                                                ),
                                            ),
                                        }
                                        t_query_model = time.time()
                                        query_text, query_usage = await _sheet_pass_llm(
                                            query_body,
                                            purpose=(
                                                "model_rag_sheet_queries"
                                                if query_attempt == 1
                                                else "model_rag_sheet_query_repair"
                                            ),
                                        )
                                        t_llm += time.time() - t_query_model
                                        model_queries, rejected_now = (
                                            classify_model_rag_query_lines(query_text)
                                        )
                                        if model_queries:
                                            break
                                except ContextRequiredSectionOverflow as context_error:
                                    logger.warning(
                                        "[SHEET_PASS] query overflow sheet=%s: %s",
                                        sheet_name,
                                        context_error.code,
                                    )
                                    break
                                pass_rejected.extend(rejected_now)
                                if not model_queries:
                                    break
                                any_sheet_queries = True
                                pass_hits: list[tuple[str, Sequence[Any]]] = []
                                pass_tools: list[dict[str, Any]] = []
                                search_blocked = False
                                search_block_status = ""
                                cache_updates: dict[str, list[dict[str, Any]]] = {}
                                for query in model_queries:
                                    cached_hits = restore_query_hits_from_cache(
                                        [query], sheet_query_cache
                                    )
                                    if cached_hits:
                                        hits = cached_hits[0][1]
                                        pass_hits.append((query, hits))
                                        pass_tools.append(
                                            {
                                                "schema": "les_tool_result_v1",
                                                "tool": "search_sources",
                                                "status": "ok" if hits else "missing",
                                                "result": {
                                                    "count": len(hits),
                                                    "cached": True,
                                                },
                                            }
                                        )
                                        append_actual_search(
                                            retrieval_trace,
                                            cached=True,
                                            hit_count=len(hits),
                                        )
                                        continue
                                    research_result = await model_research_tools.execute(
                                        {"tool": "search_sources", "args": {"q": query}}
                                    )
                                    pass_tools.append(research_result.payload)
                                    if model_search_result_blocks_packet(
                                        research_result.payload
                                    ):
                                        search_blocked = True
                                        search_block_status = str(
                                            research_result.payload.get("status") or ""
                                        )
                                        break
                                    hits = tuple(research_result.chunks)[
                                        : retrieval_limits["model_evidence_k"]
                                    ]
                                    pass_hits.append((query, hits))
                                    records = [durable_research_hit(item) for item in hits]
                                    sheet_query_cache[str(query)] = records
                                    cache_updates[str(query)] = records
                                    append_actual_search(
                                        retrieval_trace,
                                        cached=False,
                                        hit_count=len(hits),
                                    )
                                if search_blocked:
                                    logger.warning(
                                        "[SHEET_PASS] search incomplete sheet=%s status=%s",
                                        sheet_name,
                                        search_block_status,
                                    )
                                    break
                                if (
                                    cache_updates
                                    and research_job_service is not None
                                    and research_job is not None
                                ):
                                    research_job = research_job_service.record_search_cache(
                                        research_job["job_id"],
                                        cache_updates,
                                        context={
                                            "sheet": sheet_name,
                                            "packet_id": row_packet_id(
                                                source_catalog,
                                                sheet=sheet_name,
                                                locators=packet,
                                            ),
                                            "locators": list(packet),
                                            "queries": list(cache_updates),
                                        },
                                    )
                                tool_results_for_model = pass_tools
                                model_rag_query_hits = pass_hits
                            leftover_query_hits: list[tuple[str, Sequence[Any]]] = []
                            included_hits: list[tuple[str, Sequence[Any]]] = []
                            await _emit_row_progress(
                                "таблица строк",
                                sheet=sheet_name,
                                index=sheet_index,
                            )
                            question_tail = sheet_pass_question_tail(
                                str(req.question or ""),
                                sheet=sheet_name,
                                sheet_index=sheet_index,
                                sheet_count=sheet_count,
                                remaining_work=packet,
                            )
                            _, fixed_packet = govern_inference_messages(
                                preset=answer_execution_preset,
                                profile_prefix=sheet_sys_msg,
                                request_payload=question_tail,
                                checkpoint=(),
                                working_memory=(),
                                evidence=pass_evidence,
                                source_map=(),
                                tool_exchange=(),
                                dialogue=(),
                            )
                            remaining_group_tokens = max(
                                0,
                                fixed_packet.input_budget_tokens
                                - fixed_packet.included_tokens
                                - len(pass_hits)
                                - 2,
                            )
                            group_max_chars = model_rag_group_char_budget(
                                context_chars_limit=context_chars_limit,
                                remaining_group_tokens=remaining_group_tokens,
                            )
                            logger.warning(
                                "[MODEL_RAG_BUDGET] sheet=%s queries=%s hits=%s "
                                "input_budget=%s included=%s remaining_group_tokens=%s "
                                "context_chars_limit=%s group_max_chars=%s",
                                sheet_name,
                                len(pass_hits),
                                sum(len(hits) for _query, hits in pass_hits),
                                fixed_packet.input_budget_tokens,
                                fixed_packet.included_tokens,
                                remaining_group_tokens,
                                context_chars_limit,
                                group_max_chars,
                            )
                            included_hits, leftover_query_hits, trim_omitted = (
                                select_model_rag_query_hits_for_budget(
                                    pass_hits,
                                    max_chars=group_max_chars,
                                    hits_per_query=retrieval_limits["model_evidence_k"],
                                    query_offset=0,
                                )
                            )
                            pass_omitted.extend(trim_omitted)
                            if not included_hits:
                                pass_omitted.extend(
                                    model_rag_query_hit_refs(
                                        leftover_query_hits,
                                        hits_per_query=retrieval_limits[
                                            "model_evidence_k"
                                        ],
                                        query_offset=0,
                                    )
                                )
                                leftover_query_hits = []
                                model_rag_evidence_groups = []
                                model_evidence_chunks = []
                                omitted_now: list[str] = []
                            else:
                                (
                                    model_rag_evidence_groups,
                                    model_evidence_chunks,
                                    omitted_now,
                                ) = build_model_rag_evidence_groups(
                                    included_hits,
                                    max_chars=group_max_chars,
                                    hits_per_query=retrieval_limits["model_evidence_k"],
                                    evidence_namespace=(
                                        row_packet_id(
                                            source_catalog,
                                            sheet=sheet_name,
                                            locators=packet,
                                        )
                                        + f":a{packet_attempts[fingerprint]}"
                                    ),
                                )
                            sheet_pass_evidence_chunks.extend(model_evidence_chunks)
                            pass_omitted.extend(omitted_now)
                            omitted_cards = model_rag_budget_omitted_cards(
                                included_hits,
                                model_evidence_chunks,
                                omitted_now,
                            )
                            context = "\n\n".join(model_rag_evidence_groups)
                            answer_source_map = _model_rag_source_map(
                                model_evidence_chunks
                            )
                            selector_source_map = answer_source_map
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
                            answer_evidence = [
                                *pass_evidence,
                                *model_rag_evidence_groups,
                            ]
                            try:
                                messages, answer_packet = govern_inference_messages(
                                    preset=answer_execution_preset,
                                    profile_prefix=sheet_sys_msg,
                                    request_payload=question_tail,
                                    checkpoint=(),
                                    working_memory=workspace_note_objects(
                                        memory_candidates,
                                        registered=workspace_memory_registered,
                                    ),
                                    evidence=answer_evidence,
                                    source_map=(),
                                    tool_exchange=[],
                                    dialogue=[session_block] if session_block else [],
                                )
                            except ContextRequiredSectionOverflow as context_error:
                                logger.warning(
                                    "[SHEET_PASS] answer overflow sheet=%s: %s",
                                    sheet_name,
                                    context_error.code,
                                )
                                break
                            retrieval_trace["context_governor"]["calls"].append(
                                context_packet_trace(
                                    answer_packet, purpose="sheet_pass_answer"
                                )
                            )
                            source_incomplete_locators = locators_missing_from_text(
                                source_catalog,
                                packet_evidence_text(answer_packet),
                                locators=packet,
                            )
                            generation_budget = (
                                answer_execution_preset.generation_reserve_tokens
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
                            t_llm_call = time.time()
                            pass_answer, usage = await _sheet_pass_llm(chat_body)
                            t_llm += time.time() - t_llm_call
                            if not pass_answer:
                                break
                            tokens = int(tokens or 0) + int(
                                usage.get("completion_tokens") or 0
                            )
                            last_finish = llm_usage_finish_reason(usage)
                            last_truncated = (
                                finish_reason_is_length(last_finish)
                                or model_rag_answer_is_truncated(pass_answer)
                            )
                            parsed_pass = parse_model_rag_result(pass_answer)
                            pass_rows: list[dict[str, Any]] = []
                            if parsed_pass is not None:
                                _visible, pass_rows = parsed_pass
                            pass_rows = bind_row_evidence_ids(
                                pass_rows, model_evidence_chunks
                            )
                            pass_errors = validate_model_rag_result_structure(
                                pass_rows,
                                model_evidence_chunks,
                                expected_source_rows=len(packet),
                                source_catalog=source_catalog,
                                source_incomplete_locators=source_incomplete_locators,
                                finish_reason=last_finish,
                                answer_truncated=last_truncated,
                            )
                            kept = sheet_pass_keep_rows(
                                pass_rows,
                                sheet=sheet_name,
                                catalog=source_catalog,
                                errors=pass_errors,
                            )
                            accumulated_rows = merge_model_rag_rows(
                                accumulated_rows,
                                kept,
                                source_catalog,
                            )
                            if pass_answer:
                                answer_parts.append(pass_answer)
                            retrieval_trace["tool_loop"]["passes"].append(
                                {
                                    "sheet": sheet_name,
                                    "sheet_index": sheet_index,
                                    "inner": inner,
                                    "packet_id": row_packet_id(
                                        source_catalog,
                                        sheet=sheet_name,
                                        locators=packet,
                                    ),
                                    "packet_locators": list(packet),
                                    "packet_attempt": packet_attempts[fingerprint],
                                    "queries": model_queries,
                                    "shown_queries": len(included_hits),
                                    "leftover_queries": len(leftover_query_hits),
                                    "leftover_query_texts": [
                                        str(query) for query, _hits in leftover_query_hits
                                    ][:100],
                                    "omitted_cards": omitted_cards,
                                    "kept_rows": len(kept),
                                    "parsed_rows": len(pass_rows),
                                    "row_errors": list(pass_errors),
                                    "finish_reason": last_finish,
                                    "truncated": last_truncated,
                                }
                            )
                            remaining = remaining_sheet_work_locators(
                                source_catalog,
                                sheet_name,
                                structurally_complete_source_keys(
                                    accumulated_rows, source_catalog
                                ),
                            )
                            remaining = [
                                locator
                                for locator in remaining
                                if locator not in exhausted_locators
                            ]
                            still_in_packet = [
                                locator
                                for locator in packet
                                if locator in remaining
                            ]
                            defer_query_packet = bool(
                                leftover_query_hits and still_in_packet
                            )
                            if defer_query_packet:
                                deferred_query_hits = leftover_query_hits
                                held_packet = still_in_packet
                                logger.warning(
                                    "[SHEET_PASS] defer leftover query headers "
                                    "sheet=%s shown=%s leftover=%s remaining_rows=%s",
                                    sheet_name,
                                    len(included_hits),
                                    len(leftover_query_hits),
                                    len(still_in_packet),
                                )
                            elif leftover_query_hits:
                                pass_omitted.extend(
                                    model_rag_query_hit_refs(
                                        leftover_query_hits,
                                        hits_per_query=retrieval_limits[
                                            "model_evidence_k"
                                        ],
                                        query_offset=len(included_hits),
                                    )
                                )
                                held_packet = []
                            cited_after = structurally_complete_source_keys(
                                accumulated_rows, source_catalog
                            )
                            made_progress = bool(cited_after - cited_before)
                            if not made_progress and not defer_query_packet:
                                if (
                                    packet_attempts[fingerprint]
                                    >= _ROW_PACKET_MAX_ATTEMPTS
                                ):
                                    exhausted_locators.update(packet)
                                    remaining = [
                                        locator
                                        for locator in remaining
                                        if locator not in exhausted_locators
                                    ]
                            held_payload = (
                                {
                                    "sheet": sheet_name,
                                    "locators": list(still_in_packet),
                                    "queries": [
                                        str(query)
                                        for query, _hits in leftover_query_hits
                                        if str(query).strip()
                                    ],
                                }
                                if defer_query_packet
                                else {}
                            )
                            if leftover_query_hits and research_job_service is not None and research_job is not None:
                                leftover_cache = {
                                    str(query): [durable_research_hit(item) for item in hits]
                                    for query, hits in leftover_query_hits
                                    if str(query).strip()
                                }
                                if leftover_cache:
                                    for query, records in leftover_cache.items():
                                        sheet_query_cache[query] = records
                                    research_job = research_job_service.record_search_cache(
                                        research_job["job_id"],
                                        leftover_cache,
                                        context={
                                            "sheet": sheet_name,
                                            "packet_id": row_packet_id(
                                                source_catalog,
                                                sheet=sheet_name,
                                                locators=packet,
                                            ),
                                            "locators": list(packet),
                                            "queries": list(leftover_cache),
                                        },
                                    )
                            if (
                                research_job_service is not None
                                and research_job is not None
                            ):
                                research_job = research_job_service.record_packet(
                                    research_job["job_id"],
                                    sheet=sheet_name,
                                    packet_locators=packet,
                                    accepted_rows=[
                                        {
                                            **dict(row),
                                            "row_classification": str(
                                                getattr(
                                                    source_catalog.lookup(
                                                        row.get("source_row")
                                                    ),
                                                    "row_classification",
                                                    "",
                                                )
                                            ),
                                        }
                                        for row in kept
                                    ],
                                    evidence=[
                                        durable_evidence_record(chunk)
                                        for chunk in model_evidence_chunks
                                    ],
                                    omitted=pass_omitted,
                                    remaining=remaining,
                                    held_packet=held_payload,
                                )
                            if defer_query_packet:
                                continue
                            if not made_progress:
                                continue
                            if not remaining:
                                break
                    except asyncio.CancelledError:
                        logger.warning("[SHEET_PASS] cancelled; preserving accepted packets")
                        research_cancelled = True
                    finally:
                        if live_job_id and owns_sheet_pass:
                            release_sheet_pass(live_job_id)
                    if not any_sheet_queries and not accumulated_rows and not research_cancelled:
                        raise HTTPException(
                            status_code=503,
                            detail="MODEL_RAG_QUERY_LIST_EMPTY",
                        )
                    complete_keys = structurally_complete_source_keys(
                        accumulated_rows, source_catalog
                    )
                    # A row the model adjudicated with any terminal role is finished for
                    # completion purposes even if a quality gap remains; only rows that
                    # received NO decision at all are re-queued for the next resume pass.
                    adjudicated_keys = adjudicated_source_keys(
                        accumulated_rows, source_catalog
                    )
                    unfinished_locators = [
                        locator
                        for locator in source_catalog.work_locators()
                        if locator not in complete_keys and locator not in adjudicated_keys
                    ]
                    if research_job_service is not None and research_job is not None:
                        if owns_sheet_pass:
                            if research_cancelled or unfinished_locators:
                                research_job = research_job_service.pause(
                                    research_job["job_id"],
                                    remaining=unfinished_locators,
                                    phase="packets",
                                )
                            else:
                                research_job = research_job_service.finish(
                                    research_job["job_id"],
                                    status="complete",
                                    phase="research_complete",
                                )
                        retrieval_trace["workbook_research_job"] = {
                            "schema": "les.workbook-research-job.v1",
                            "job_id": research_job["job_id"],
                            "status": research_job["status"],
                            "phase": research_job["phase"],
                            "resumable": bool(research_job.get("resumable")),
                            "accepted_rows": len(research_job["accepted_rows"]),
                            "omitted": len(research_job["omitted"]),
                            "remaining": len(research_job.get("remaining") or []),
                            "remaining_locators": list(research_job.get("remaining") or [])[:80],
                            "cached_queries": len(research_job.get("query_cache") or {}),
                            "operator_overrides": dict(research_job.get("operator_overrides") or {}),
                        }
                    await _emit_row_progress(
                        "сборка файла",
                        sheet=sheet_pass_names[-1] if sheet_pass_names else "",
                        index=max(sheet_count, 1),
                    )
                    sheet_pass_done = True
                    sheet_pass_rows = accumulated_rows
                    model_evidence_chunks = sheet_pass_evidence_chunks
                    answer = "\n\n".join(part.strip() for part in answer_parts if part.strip())
                    answer_finish_reason = last_finish
                    rejected_model_queries = pass_rejected
                    omitted_evidence_refs = pass_omitted
                    crag_status = "MODEL_OUTPUT"
                    cited_all = cited_source_row_keys(accumulated_rows, source_catalog)
                    source_incomplete_locators = [
                        locator
                        for locator in source_catalog.work_locators()
                        if locator not in cited_all
                    ]
                    retrieval_trace["tool_loop"]["sheet_count"] = sheet_count
                    retrieval_trace["tool_loop"]["accumulated_rows"] = len(
                        accumulated_rows
                    )
                    logger.info(
                        "[SHEET_PASS] sheets=%s rows=%s truncated=%s missing=%s",
                        sheet_count,
                        len(accumulated_rows),
                        last_truncated,
                        len(source_incomplete_locators),
                    )
                max_attempts = 1 if model_driven_retrieval else 2
                if not sheet_pass_done:
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
                    if model_driven_retrieval:
                        question_tail = lsr_result_table_instruction(
                            sheet_clause=question_tail + "\n",
                            remaining_clause=(
                                " Ответ должен вместить все строки: без вводного обзора "
                                "и итоговых рекомендаций, кратко по одной строке ВОР."
                            ),
                        )
                        fixed_model_rag_evidence = selector_evidence_payload(
                            attachment_context=attachment_context,
                            rendered_context="",
                            source_catalog=source_catalog,
                        )
                        _, fixed_packet = govern_inference_messages(
                            preset=answer_execution_preset,
                            profile_prefix=sys_msg,
                            request_payload=question_tail,
                            checkpoint=(),
                            working_memory=(),
                            evidence=fixed_model_rag_evidence,
                            source_map=(),
                            tool_exchange=(),
                            dialogue=(),
                        )
                        remaining_group_tokens = max(
                            0,
                            fixed_packet.input_budget_tokens
                            - fixed_packet.included_tokens
                            - len(model_rag_query_hits)
                            - 2,
                        )
                        logger.warning(
                            "[MODEL_RAG_BUDGET] queries=%s hits=%s input_budget=%s "
                            "included=%s remaining_group_tokens=%s context_chars_limit=%s "
                            "group_max_chars=%s",
                            len(model_rag_query_hits),
                            sum(len(hits) for _query, hits in model_rag_query_hits),
                            fixed_packet.input_budget_tokens,
                            fixed_packet.included_tokens,
                            remaining_group_tokens,
                            context_chars_limit,
                            model_rag_group_char_budget(
                                context_chars_limit=context_chars_limit,
                                remaining_group_tokens=remaining_group_tokens,
                            ),
                        )
                        (
                            model_rag_evidence_groups,
                            model_evidence_chunks,
                            omitted_evidence_refs,
                        ) = build_model_rag_evidence_groups(
                            model_rag_query_hits,
                            max_chars=model_rag_group_char_budget(
                                context_chars_limit=context_chars_limit,
                                remaining_group_tokens=remaining_group_tokens,
                            ),
                            hits_per_query=retrieval_limits["model_evidence_k"],
                        )
                        context = "\n\n".join(model_rag_evidence_groups)
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
                            "group_ids": [
                                f"Q{index}"
                                for index in range(1, len(model_rag_evidence_groups) + 1)
                            ],
                            "rendered_chars": len(context),
                            "omitted_evidence_refs": omitted_evidence_refs,
                            "min_body_chars": _MIN_MODEL_RAG_EVIDENCE_BODY_CHARS,
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
                        answer_working_memory = workspace_note_objects(
                            memory_candidates, registered=workspace_memory_registered,
                        )
                    answer_tool_exchange = (
                        []
                        if model_driven_retrieval
                        else [
                            _compact_tool_result_for_prompt(item, max_chars=2400)
                            for item in tool_results_for_model
                        ]
                    )
                    answer_evidence = (
                        [*fixed_model_rag_evidence, *model_rag_evidence_groups]
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
                    if source_catalog is not None:
                        source_incomplete_locators = locators_missing_from_text(
                            source_catalog,
                            packet_evidence_text(answer_packet),
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
                        answer_execution_preset.generation_reserve_tokens,
                    )
                    if model_driven_retrieval:
                        generation_budget = answer_execution_preset.generation_reserve_tokens

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
                        if canonical_execution_mode is CanonicalRouteMode.ACTIVE:
                            answer, usage = await _post_llm(
                                llm_runtime,
                                llm_model,
                                headers,
                                chat_body,
                                allow_stream=not model_driven_retrieval,
                            )
                            if active_model_result is not None:
                                llm_model = active_model_result.connection.model_id
                        elif is_cloud_provider(llm_runtime.provider):
                            # Облако: цепочка моделей с таймаутом на модель (зависла → следующая).
                            answer, usage, llm_model = await _post_cloud_fallback(
                                llm_runtime,
                                headers,
                                chat_body,
                                allow_stream=not model_driven_retrieval,
                            )
                        else:
                            answer, usage = await _post_llm(
                                llm_runtime,
                                llm_model,
                                headers,
                                chat_body,
                                allow_stream=not model_driven_retrieval,
                            )
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
                        answer, usage = await _post_llm(
                            llm_runtime,
                            llm_model,
                            headers,
                            fallback_body,
                            allow_stream=not model_driven_retrieval,
                        )
                    t_llm += time.time() - t_llm_call
                    if not answer:
                        if attempt < max_attempts:
                            logger.warning("[CHAT] empty LLM answer on attempt=%s — retrying strict", attempt)
                            continue
                        raise ValueError(f"Пустой ответ LLM (stream={token_sink is not None})")
                    tokens = usage.get("completion_tokens", 0)
                    answer_finish_reason = llm_usage_finish_reason(usage)
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
                    logger.info("[CHAT] model answer accepted unchanged; citation check is trace-only")
                    break

                if model_driven_retrieval:
                    if sheet_pass_done:
                        parsed_model_result = (
                            (answer, sheet_pass_rows) if sheet_pass_rows else None
                        )
                    else:
                        parsed_model_result = parse_model_rag_result(answer)
                        expected_format_locators = (
                            list(source_catalog.work_locators())
                            if source_catalog is not None
                            else []
                        )
                        first_rows = (
                            parsed_model_result[1] if parsed_model_result is not None else []
                        )
                        first_keys = {
                            str(item.get("source_row") or "").strip()
                            for item in first_rows
                            if str(item.get("source_row") or "").strip()
                        }
                        # The ordinary active path has one terminal professional
                        # model result (ADR-15).  A format-repair call is useful for
                        # isolated diagnostics, but may not silently replace that
                        # result in the user's workbook path.
                        need_format_retry = comparative_variant == "QUALITY_DIAGNOSTIC" and (
                            parsed_model_result is None
                            or any(invented_source_row(key) for key in first_keys)
                            or (
                                bool(expected_format_locators)
                                and first_keys != set(expected_format_locators)
                            )
                        )
                        if need_format_retry:
                            retry_messages, retry_packet = govern_inference_messages(
                                preset=answer_execution_preset,
                                profile_prefix=lsr_format_retry_instruction(),
                                request_payload={
                                    "expected_locators": expected_format_locators
                                    or sorted(first_keys),
                                },
                                checkpoint=(),
                                working_memory=(),
                                evidence=[answer],
                                source_map=(),
                                tool_exchange=(),
                                dialogue=(),
                            )
                            retrieval_trace["context_governor"]["calls"].append(
                                context_packet_trace(
                                    retry_packet, purpose="lsr_format_retry"
                                )
                            )
                            retry_text, retry_usage = await _post_llm(
                                llm_runtime,
                                llm_model,
                                query_headers,
                                {
                                    "messages": retry_messages,
                                    "stream": False,
                                    "temperature": 0,
                                    "max_tokens": answer_execution_preset.generation_reserve_tokens,
                                },
                                allow_stream=False,
                            )
                            tokens = int(tokens or 0) + int(
                                (retry_usage or {}).get("completion_tokens") or 0
                            )
                            retry_parsed = parse_model_rag_result(retry_text or "")
                            if parsed_model_result is None:
                                parsed_model_result = retry_parsed
                                if retry_parsed is not None:
                                    answer = retry_parsed[0]
                            elif retry_parsed is not None:
                                parsed_model_result = (
                                    parsed_model_result[0],
                                    merge_format_retry_rows(
                                        first_rows,
                                        retry_parsed[1],
                                        expected_format_locators or None,
                                    ),
                                )
                            retrieval_trace["format_retry"] = {
                                "needed": True,
                                "recovered": parsed_model_result is not None,
                            }
                    model_result_rows: list[dict[str, Any]] = []
                    model_result_errors: list[str] = []
                    model_result_blocking_errors: list[str] = []
                    # The durable job, not the re-parsed answer, decides what the
                    # final revision contains once the job reached its terminal
                    # state; a not-yet-terminal durable job makes the packaged
                    # file an explicitly marked draft.
                    durable_packaging_rows = terminal_research_packaging_rows(
                        research_job
                    )
                    packaging_is_draft = bool(research_job) and not durable_packaging_rows
                    if parsed_model_result is not None:
                        answer, model_result_rows = parsed_model_result
                        # The model's first complete result is the terminal professional
                        # decision in the active estimator path (ADR-15).  The historical
                        # verifier/research loop remains available only for an explicit
                        # isolated diagnostic run; it must never rewrite or block the
                        # ordinary user workbook.
                        quality_diagnostic = comparative_variant == "QUALITY_DIAGNOSTIC"
                        if model_driven_retrieval and model_result_rows and quality_diagnostic:
                            async def _verify_quality_rows(rows_to_check, previous_response=None):
                                evidence_items = build_blind_review_evidence_items(
                                    rows_to_check, model_evidence_chunks
                                )
                                messages, packet = govern_inference_messages(
                                    preset=answer_execution_preset,
                                    profile_prefix=lsr_verifier_instruction(),
                                    request_payload={
                                        "task": "Проверь применимость выбранных норм к строкам ВОР.",
                                        **({
                                            "format_repair": lsr_verifier_format_retry_instruction(),
                                            "previous_response": previous_response,
                                        } if previous_response is not None else {}),
                                    },
                                    checkpoint=(),
                                    working_memory=(),
                                    evidence=evidence_items,
                                    source_map=(),
                                    tool_exchange=(),
                                    dialogue=(),
                                )
                                retrieval_trace["context_governor"]["calls"].append(
                                    context_packet_trace(
                                        packet, purpose="lsr_norm_verifier"
                                    )
                                )
                                if packet.omissions and len(rows_to_check) > 1:
                                    midpoint = len(rows_to_check) // 2
                                    left = await _verify_quality_rows(rows_to_check[:midpoint], previous_response)
                                    right = await _verify_quality_rows(rows_to_check[midpoint:], previous_response)
                                    return left + "\n\n" + right
                                if packet.omissions:
                                    raise ValueError("LSR_VERIFIER_EVIDENCE_INCOMPLETE")
                                text, usage = await _post_llm(
                                    llm_runtime,
                                    llm_model,
                                    query_headers,
                                    {
                                        "messages": messages,
                                        "stream": False,
                                        "temperature": 0,
                                        "max_tokens": verifier_generation_tokens(
                                            len(rows_to_check),
                                            answer_execution_preset.generation_reserve_tokens,
                                        ),
                                    },
                                    allow_stream=False,
                                )
                                tokens_now = int((usage or {}).get("completion_tokens") or 0)
                                nonlocal tokens
                                tokens = int(tokens or 0) + tokens_now
                                retrieval_trace.setdefault("norm_quality_model_calls", []).append({
                                    "stage": "verify_format_repair" if previous_response is not None else "verify",
                                    "locators": [item.get("source_row") for item in rows_to_check],
                                    "finish_reason": llm_usage_finish_reason(usage),
                                    "completion_tokens": tokens_now,
                                    "response": str(text or "")[:32000],
                                    "response_truncated": len(str(text or "")) > 32000,
                                })
                                return text or ""

                            async def _repair_quality_rows(rows_to_check, previous_response):
                                return await _verify_quality_rows(rows_to_check, previous_response)

                            async def _research_quality_rows(rows_to_check, round_index):
                                nonlocal model_evidence_chunks
                                # Bound work by row packets, never by dropping evidence.
                                if len(rows_to_check) > 3:
                                    partials = []
                                    for offset in range(0, len(rows_to_check), 3):
                                        partials.append(await _research_quality_rows(rows_to_check[offset:offset + 3], round_index))
                                    return LsrResearchRoundResult(
                                        rows=[row for part in partials for row in part.rows],
                                        queries=tuple(q for part in partials for q in part.queries),
                                        hit_ids=tuple(i for part in partials for i in part.hit_ids),
                                        card_ids=tuple(i for part in partials for i in part.card_ids),
                                    )
                                locators = [
                                    str(item.get("source_row") or "").strip()
                                    for item in rows_to_check
                                    if str(item.get("source_row") or "").strip()
                                ]
                                if model_research_tools is None:
                                    return LsrResearchRoundResult(rows=list(rows_to_check))
                                query_messages, query_packet = govern_inference_messages(
                                    preset=execution_preset,
                                    profile_prefix=(
                                        profile_system_prompt(
                                            profile_snapshot, strict=False
                                        )
                                        + "\n\n"
                                        + lsr_research_query_instruction(
                                            round_index, rows_to_check
                                        )
                                    ),
                                    request_payload={
                                        "question": str(req.question or ""),
                                        "unresolved": locators,
                                        "rows": [
                                            {
                                                "source_row": item.get("source_row"),
                                                "title": item.get("title"),
                                                "unit": item.get("unit"),
                                                "rejected_norm_codes": list(
                                                    item.get("_rejected_codes") or []
                                                ),
                                            }
                                            for item in rows_to_check
                                        ],
                                    },
                                    checkpoint=(),
                                    working_memory=(),
                                    evidence=selector_evidence,
                                    source_map=(),
                                    tool_exchange=(),
                                )
                                retrieval_trace["context_governor"]["calls"].append(
                                    context_packet_trace(
                                        query_packet,
                                        purpose="lsr_norm_research_queries",
                                    )
                                )
                                query_text, _query_usage = await _post_llm(
                                    llm_runtime,
                                    llm_model,
                                    query_headers,
                                    {
                                        "messages": query_messages,
                                        "stream": False,
                                        "temperature": 0,
                                        "max_tokens": 1600,
                                    },
                                    allow_stream=False,
                                )
                                queries, _rejected = classify_model_rag_query_lines(
                                    query_text
                                )
                                hits: list[tuple[str, Sequence[Any]]] = []
                                hit_ids: list[str] = []
                                card_ids: list[str] = []
                                for query in queries:
                                    research_result = await model_research_tools.execute(
                                        {"tool": "search_sources", "args": {"q": query}}
                                    )
                                    chunk_tuple = tuple(research_result.chunks)[
                                        : retrieval_limits["model_evidence_k"]
                                    ]
                                    hits.append((query, chunk_tuple))
                                    for chunk in chunk_tuple:
                                        hit_ids.append(
                                            str(
                                                getattr(chunk, "doc_id", "")
                                                or getattr(chunk, "doc_name", "")
                                            )
                                        )
                                        meta = dict(getattr(chunk, "meta", {}) or {})
                                        if meta.get("norm_code"):
                                            card_ids.append(str(meta["norm_code"]))
                                if not hits:
                                    return LsrResearchRoundResult(
                                        rows=list(rows_to_check),
                                        queries=tuple(queries),
                                    )
                                groups, chunks, _omitted = build_model_rag_evidence_groups(
                                    hits,
                                    max_chars=context_chars_limit,
                                    hits_per_query=retrieval_limits["model_evidence_k"],
                                    query_offset=max((int((getattr(chunk, "meta", {}) or {}).get("model_query_index") or 0) for chunk in model_evidence_chunks), default=0),
                                )
                                model_evidence_chunks.extend(list(chunks))
                                result_tail = lsr_result_table_instruction(
                                    sheet_clause="Повторный подбор только для неподтверждённых строк.\n",
                                    remaining_clause=" Остались строки: "
                                    + ", ".join(locators[:40])
                                    + rejected_codes_clause(rows_to_check),
                                )
                                messages, packet = govern_inference_messages(
                                    preset=answer_execution_preset,
                                    profile_prefix=profile_system_prompt(
                                        profile_snapshot, strict=False
                                    ),
                                    request_payload={
                                        "task": result_tail,
                                        "question": str(req.question or ""),
                                        "rows": [dict(item) for item in rows_to_check],
                                    },
                                    checkpoint=(),
                                    working_memory=(),
                                    evidence=lsr_research_result_evidence(
                                        rows_to_check, groups
                                    ),
                                    source_map=(),
                                    tool_exchange=(),
                                )
                                retrieval_trace["context_governor"]["calls"].append(
                                    context_packet_trace(
                                        packet, purpose="lsr_norm_research_result"
                                    )
                                )
                                text, _usage = await _post_llm(
                                    llm_runtime,
                                    llm_model,
                                    query_headers,
                                    {
                                        "messages": messages,
                                        "stream": False,
                                        "temperature": profile_temperature(
                                            profile_snapshot, fallback=0.2
                                        ),
                                        "max_tokens": (
                                            answer_execution_preset.generation_reserve_tokens
                                        ),
                                    },
                                    allow_stream=False,
                                )
                                parsed = parse_model_rag_result(text or "")
                                new_rows = parsed[1] if parsed else list(rows_to_check)
                                new_rows = bind_row_evidence_ids(new_rows, chunks)
                                new_rows = bind_row_evidence_ids(
                                    new_rows, model_evidence_chunks
                                )
                                return LsrResearchRoundResult(
                                    rows=new_rows,
                                    queries=tuple(queries),
                                    hit_ids=tuple(hit_ids),
                                    card_ids=tuple(card_ids),
                                )

                            async def _review_coefficients(rows_to_check):
                                evidence_items = [
                                    "\n".join(
                                        [
                                            f"## source_row={item.get('source_row')}",
                                            f"ВОР: {item.get('title') or ''}",
                                            f"Шифр: {item.get('norm_code') or ''}",
                                            f"Коэффициент: {item.get('coefficient')}",
                                            f"applies_to: {item.get('coefficient_applies_to') or ''}",
                                        ]
                                    )
                                    for item in rows_to_check
                                ]
                                messages, packet = govern_inference_messages(
                                    preset=answer_execution_preset,
                                    profile_prefix=lsr_coefficient_instruction(),
                                    request_payload="Проверь только коэффициенты указанных строк.",
                                    checkpoint=(),
                                    working_memory=(),
                                    evidence=evidence_items,
                                    source_map=(),
                                    tool_exchange=(),
                                    dialogue=(),
                                )
                                retrieval_trace["context_governor"]["calls"].append(
                                    context_packet_trace(
                                        packet, purpose="lsr_coefficient_review"
                                    )
                                )
                                text, usage = await _post_llm(
                                    llm_runtime,
                                    llm_model,
                                    query_headers,
                                    {
                                        "messages": messages,
                                        "stream": False,
                                        "temperature": 0,
                                        "max_tokens": verifier_generation_tokens(
                                            len(rows_to_check),
                                            answer_execution_preset.generation_reserve_tokens,
                                        ),
                                    },
                                    allow_stream=False,
                                )
                                tokens_now = int((usage or {}).get("completion_tokens") or 0)
                                nonlocal tokens
                                tokens = int(tokens or 0) + tokens_now
                                return text or ""

                            try:
                                if sheet_pass_done:
                                    leftover = [
                                        row
                                        for row in model_result_rows
                                        if not row_is_quality_terminal(row)
                                    ]
                                    if leftover:
                                        model_result_rows = merge_quality_gated_rows(
                                            model_result_rows,
                                            [
                                                mark_research_exhausted(row)
                                                for row in leftover
                                            ],
                                            source_catalog,
                                        )
                                    retrieval_trace["norm_quality_gate"] = {
                                        "schema": "les.lsr-norm-quality-gate.v1",
                                        "norms_status": aggregate_norms_status(
                                            model_result_rows
                                        ),
                                        "events": [{"stage": "sheet_pass_terminal"}],
                                    }
                                else:
                                    gate = await run_lsr_norm_quality_loop(
                                    model_result_rows,
                                        verify=_verify_quality_rows,
                                        repair_verification=_repair_quality_rows,
                                        research=_research_quality_rows,
                                        evidence_chunks=model_evidence_chunks,
                                        source_locators=(
                                            source_catalog.work_locators()
                                            if source_catalog is not None
                                            else None
                                        ),
                                    )
                                    model_result_rows = bind_row_evidence_ids(
                                        gate.rows, model_evidence_chunks
                                    )
                                    model_result_rows, coef_events = await run_coefficient_review(
                                        model_result_rows,
                                        review=_review_coefficients,
                                    )
                                    retrieval_trace["norm_quality_gate"] = {
                                        "schema": "les.lsr-norm-quality-gate.v1",
                                        "norms_status": gate.norms_status,
                                        "events": [*gate.events, *coef_events],
                                    }
                            except Exception:
                                logger.exception(
                                    "[LSR_QUALITY] gate failed; rows stay unverified"
                                )
                                model_result_rows = [
                                    prepare_selection_row(row)
                                    for row in model_result_rows
                                ]
                                retrieval_trace["norm_quality_gate"] = {
                                    "schema": "les.lsr-norm-quality-gate.v1",
                                    "status": "error",
                                    "norms_status": "norms_unverified",
                                }
                        elif model_driven_retrieval and model_result_rows:
                            retrieval_trace["norm_quality_gate"] = {
                                "schema": "les.lsr-norm-quality-gate.v1",
                                "status": "not_run",
                                "reason": "terminal_model_result_preserved",
                                "norms_status": "model_authored",
                            }
                        from proxy.services.smeta_chat_adapter_service import (
                            _smeta_source_row_count,
                        )

                        if source_catalog is not None:
                            sheet_coverage = sheet_coverage_from_missing(
                                source_catalog,
                                source_incomplete_locators,
                            )
                            # Catalog is complete on disk. Omitted Governor rows
                            # are recorded, but they do not count as a silent cut.
                            attachment_truncated = False
                        else:
                            attachment_truncated = attachment_context_is_truncated(
                                attachment_context
                            )
                            sheet_coverage = parse_attachment_sheet_coverage(
                                attachment_context
                            )
                        retrieval_trace["attachment_integrity"] = {
                            "truncated": bool(source_incomplete_locators)
                            if source_catalog is not None
                            else attachment_truncated,
                            "included_sheets": sheet_coverage["included"],
                            "omitted_sheets": sheet_coverage["omitted"],
                            "catalog_rows": (
                                len(source_catalog.rows) if source_catalog is not None else 0
                            ),
                            "omitted_source_count": len(source_incomplete_locators),
                            "omitted_source_locators": list(source_incomplete_locators[:40]),
                            "finish_reason": answer_finish_reason,
                            "sheet_pass": sheet_pass_done,
                        }
                        model_result_rows = bind_row_evidence_ids(
                            model_result_rows, model_evidence_chunks
                        )
                        model_result_errors = validate_model_rag_result_structure(
                            model_result_rows,
                            model_evidence_chunks,
                            expected_source_rows=_smeta_source_row_count(
                                attachment_context
                            ),
                            attachment_truncated=attachment_truncated,
                            answer_truncated=model_rag_answer_is_truncated(answer),
                            source_catalog=source_catalog,
                            source_incomplete_locators=source_incomplete_locators,
                            finish_reason=answer_finish_reason,
                            validate_evidence_refs=True,
                        )
                        if research_cancelled:
                            model_result_errors.append("workbook_research_cancelled")
                        work_row_count = sum(
                            1
                            for row in model_result_rows
                            if model_rag_row_kind(row) == "work"
                        )
                        model_result_blocking_errors = blocking_model_rag_result_errors(
                            model_result_errors,
                            work_row_count=work_row_count,
                        )
                        if durable_packaging_rows:
                            # Terminal durable state wins over the ephemeral
                            # re-parse: the accepted decisions are already saved
                            # and the final revision is packaged from that full
                            # set unchanged (no model re-call). Re-parse noise
                            # stays visible in model_result_errors but can no
                            # longer suppress the complete artifact.
                            model_result_rows = durable_packaging_rows
                            model_result_blocking_errors = []
                        notice_kwargs = {
                            "errors": model_result_errors,
                            "row_count": len(model_result_rows),
                            "attachment_truncated": bool(
                                attachment_truncated or sheet_coverage["omitted"]
                            ),
                            "included_sheets": sheet_coverage["included"],
                            "omitted_sheets": sheet_coverage["omitted"],
                            "rejected_queries": len(rejected_model_queries),
                            "omitted_evidence": len(omitted_evidence_refs),
                        }
                        if model_result_blocking_errors:
                            notice = format_lsr_not_created_notice(**notice_kwargs)
                            if notice not in answer:
                                answer = f"{answer.rstrip()}\n\n{notice}"
                            retrieval_trace["model_result"] = {
                                "schema": "les_model_rag_result_v1",
                                "status": "structural_error",
                                "row_count": len(model_result_rows),
                                "packaged": False,
                                "errors": model_result_errors,
                                "notice": notice,
                            }
                        elif model_result_errors or sheet_coverage["omitted"]:
                            notice = format_lsr_partial_notice(**notice_kwargs)
                            if notice not in answer:
                                answer = f"{answer.rstrip()}\n\n{notice}"
                            retrieval_trace["model_result"] = {
                                "schema": "les_model_rag_result_v1",
                                "status": "accepted_with_integrity_warning",
                                "row_count": len(model_result_rows),
                                "packaged": False,
                                "warnings": model_result_errors,
                                "notice": notice,
                            }
                    else:
                        notice = format_lsr_unstructured_notice(
                            sheet_pass_empty=bool(sheet_pass_done)
                        )
                        if notice not in answer:
                            answer = f"{answer.rstrip()}\n\n{notice}"
                        retrieval_trace["model_result"] = {
                            "schema": "les_model_rag_result_v1",
                            "status": "unstructured",
                            "packaged": False,
                            "notice": notice,
                        }
                    result_meta = retrieval_trace.get("model_result")
                    if isinstance(result_meta, dict):
                        result_meta["finish_reason"] = answer_finish_reason
                    if token_sink is not None:
                        await token_sink({"event": "reset", "data": ""})
                        if answer:
                            await token_sink({"event": "token", "data": answer})
                    attachment_id = str(getattr(req, "attachment_id", None) or "").strip()
                    packaging_tools = workbook_packaging_tool(
                        profile_tools, str(getattr(req, "question", "") or "")
                    )
                    if (
                        (parsed_model_result is not None or bool(durable_packaging_rows))
                        and (
                            bool(model_result_rows)
                            or bool(durable_packaging_rows)
                            or packaging_tools == ["build_vor_workbook"]
                        )
                        and not model_result_blocking_errors
                        and attachment_id
                        and packaging_tools
                        and workbook_tool_executor is not None
                        and canonical_execution_mode is CanonicalRouteMode.ACTIVE
                    ):
                        async def workbook_progress(event: dict[str, Any]) -> None:
                            if token_sink is not None:
                                await token_sink({"event": "tool_progress", "data": event})

                        packaging_trace: list[dict[str, Any]] = []
                        packaging_failures: list[dict[str, Any]] = []
                        workbook_files: list[dict[str, str]] = []
                        # Keep one downloadable document per durable job: a new
                        # decision set chains from the last revision this job
                        # packaged; an already-settled final revision is replayed
                        # with its own identity so a re-open serves the same file.
                        packaging_parents: dict[str, str] = {}
                        packaging_settled: dict[str, str | None] = {}
                        if research_job_service is not None and research_job is not None:
                            packaging_parents, packaging_settled = (
                                workbook_packaging_lineage(
                                    research_job_service.list_events(
                                        str(research_job.get("job_id") or "")
                                    ),
                                    durable_decisions=bool(durable_packaging_rows),
                                )
                            )
                        for packaging_tool in packaging_tools:
                            packaging_parent = (
                                packaging_settled[packaging_tool]
                                if packaging_tool in packaging_settled
                                else packaging_parents.get(packaging_tool)
                            )
                            workbook_call = {
                                "tool": packaging_tool,
                                "args": workbook_packaging_args(
                                    packaging_tool=packaging_tool,
                                    attachment_id=attachment_id,
                                    question=str(req.question or ""),
                                    decisions=(
                                        durable_packaging_rows or model_result_rows
                                    ),
                                    operator_overrides=(
                                        retrieval_trace.get("workbook_research_job") or {}
                                    ).get("operator_overrides"),
                                    draft=packaging_is_draft,
                                    parent_revision_id=packaging_parent,
                                ),
                            }
                            execution_context = {
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
                            }
                            try:
                                # One bounded retry is safe here: the workbook tool
                                # is idempotent and resumes the same persisted
                                # checkpoint.  No model or professional decision is
                                # called again.
                                safe_payload, attempt_traces = (
                                    await execute_workbook_with_bounded_retry(
                                        workbook_tool_executor,
                                        workbook_call,
                                        execution_context,
                                        workbook_progress,
                                    )
                                )
                                packaging_trace.extend(attempt_traces)
                                if safe_payload.get("status") == "failed":
                                    packaging_failures.append(dict(safe_payload))
                                    continue
                                harvested = harvest_workbook_tool_result(safe_payload)
                                if not harvested:
                                    continue
                                artifact = (
                                    harvested.get("artifact")
                                    if isinstance(harvested.get("artifact"), dict)
                                    else {}
                                )
                                if (
                                    research_job_service is not None
                                    and research_job is not None
                                    and str(artifact.get("revision_id") or "")
                                ):
                                    try:
                                        research_job_service.record_packaging(
                                            str(research_job["job_id"]),
                                            tool=packaging_tool,
                                            revision_id=str(artifact["revision_id"]),
                                            draft=packaging_is_draft,
                                            parent_revision_id=packaging_parent,
                                        )
                                    except Exception as record_error:  # noqa: BLE001 - lineage hint is best-effort
                                        logger.warning(
                                            "[WORKBOOK] packaging event not recorded: %s",
                                            type(record_error).__name__,
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
                                        "draft": "true" if packaging_is_draft else "false",
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
                                    "attempt": 1,
                                    "status": "error",
                                    "error_type": type(packaging_error).__name__,
                                })
                                packaging_failures.append({
                                    "status": "error",
                                    "code": type(packaging_error).__name__,
                                })
                        if workbook_chat_meta:
                            artifact_meta = workbook_chat_meta.get("artifact")
                            if isinstance(artifact_meta, dict):
                                artifact_meta["draft"] = bool(packaging_is_draft)
                                artifact_meta["draft_rows"] = compact_estimator_draft_rows(
                                    model_result_rows
                                )
                                if workbook_files:
                                    artifact_meta["files"] = workbook_files
                                    artifact_meta.setdefault(
                                        "filename", workbook_files[0]["filename"]
                                    )
                        packaging_warnings = list(model_result_errors or [])
                        packaged_notice = ""
                        job_meta = (
                            retrieval_trace.get("workbook_research_job")
                            if isinstance(retrieval_trace.get("workbook_research_job"), dict)
                            else {}
                        )
                        remaining_locators = list(
                            job_meta.get("remaining_locators")
                            or source_incomplete_locators
                            or []
                        )
                        lsr_readiness = build_lsr_result_readiness(
                            packaged=bool(workbook_files),
                            packaging_failed=bool(packaging_failures) and not workbook_files,
                            packaging_code=str(
                                (packaging_failures[-1] or {}).get("code")
                                if packaging_failures
                                else ""
                            ),
                            rows=model_result_rows,
                            missing=list(workbook_chat_meta.get("missing") or [])
                            if workbook_chat_meta
                            else [],
                            pricing_status=str(
                                (workbook_chat_meta or {}).get("pricing_status") or ""
                            ),
                            paused=str(job_meta.get("status") or "") == "paused"
                            or "workbook_research_cancelled" in model_result_errors,
                            remaining_locators=remaining_locators,
                            catalog_work_count=(
                                len(source_catalog.work_locators())
                                if source_catalog is not None
                                else 0
                            ),
                            catalog_locators=(
                                list(source_catalog.work_locators())
                                if source_catalog is not None
                                else []
                            ),
                            price_gaps=list(
                                (workbook_chat_meta or {}).get("price_gaps") or []
                            ),
                            price_basis=dict(
                                (workbook_chat_meta or {}).get("price_basis") or {}
                            ),
                            calculated_positions=(
                                int((safe_payload or {})["calculated_positions"])
                                if isinstance(
                                    (safe_payload or {}).get("calculated_positions"), (int, float)
                                )
                                else -1
                            ),
                            confirmed_amount=(
                                float((safe_payload or {})["confirmed_amount"])
                                if isinstance(
                                    (safe_payload or {}).get("confirmed_amount"), (int, float)
                                )
                                else -1.0
                            ),
                            preliminary_amount=(
                                float((safe_payload or {})["preliminary_amount"])
                                if isinstance(
                                    (safe_payload or {}).get("preliminary_amount"), (int, float)
                                )
                                else -1.0
                            ),
                        )
                        retrieval_trace["result_readiness"] = lsr_readiness
                        if isinstance(workbook_chat_meta, dict):
                            artifact_meta = workbook_chat_meta.get("artifact")
                            if isinstance(artifact_meta, dict):
                                artifact_meta["result_readiness"] = lsr_readiness
                                artifact_meta["resume"] = {
                                    "job_id": str(job_meta.get("job_id") or ""),
                                    "question": str(req.question or ""),
                                    "attachment_id": attachment_id,
                                    "session_id": str(req.session_id or ""),
                                    "remaining_locators": list(
                                        lsr_readiness.get("remaining_locators") or []
                                    )[:80],
                                    "catalog_work_count": int(
                                        lsr_readiness.get("catalog_work_count") or 0
                                    ),
                                }
                        if workbook_chat_meta:
                            harvested_missing = [
                                str(item)
                                for item in (workbook_chat_meta.get("missing") or [])
                                if str(item).strip()
                            ]
                            harvested_blockers = [
                                str(item)
                                for item in (workbook_chat_meta.get("blockers") or [])
                                if str(item).strip()
                            ]
                            packaged_notice = format_lsr_packaged_notice(
                                filename=(
                                    workbook_files[0]["filename"] if workbook_files else ""
                                ),
                                status=str(workbook_chat_meta.get("workbook_status") or ""),
                                pricing_status=str(
                                    workbook_chat_meta.get("pricing_status") or ""
                                ),
                                norms_status=str(
                                    workbook_chat_meta.get("norms_status") or ""
                                ),
                                missing=harvested_missing,
                                blockers=harvested_blockers,
                                readiness=lsr_readiness,
                            )
                            packaging_warnings.extend(harvested_missing)
                            packaging_warnings.extend(harvested_blockers)
                            if packaged_notice and packaged_notice not in answer:
                                answer = f"{answer.rstrip()}\n\n{packaged_notice}"
                                if token_sink is not None:
                                    await token_sink({"event": "reset", "data": ""})
                                    await token_sink({"event": "token", "data": answer})
                        elif packaging_failures:
                            failure = packaging_failures[-1]
                            failure_checkpoint = (
                                failure.get("checkpoint")
                                if isinstance(failure.get("checkpoint"), dict)
                                else {}
                            )
                            checkpoint_id = str(
                                failure_checkpoint.get("checkpoint_id") or ""
                            )
                            checkpoint_bit = (
                                f" Контрольная точка: {checkpoint_id}."
                                if checkpoint_id
                                else ""
                            )
                            packaged_notice = (
                                "ЛСР не создана: техническая ошибка упаковки "
                                f"({str(failure.get('code') or 'WORKBOOK_GENERATION_FAILED')})."
                                f"{checkpoint_bit} Строки решения модели сохранены в истории; "
                                "нормы повторно не пересматриваются."
                            )
                            if packaged_notice not in answer:
                                answer = f"{answer.rstrip()}\n\n{packaged_notice}"
                                if token_sink is not None:
                                    await token_sink({"event": "reset", "data": ""})
                                    await token_sink({"event": "token", "data": answer})
                        retrieval_trace["model_result"] = {
                            "schema": "les_model_rag_result_v1",
                            "status": "accepted_unchanged",
                            "row_count": len(model_result_rows),
                            "packaged": bool(workbook_files),
                            "packaging": packaging_trace,
                            "decision_rows": compact_estimator_draft_rows(model_result_rows),
                            "warnings": packaging_warnings,
                            "notice": packaged_notice,
                            "finish_reason": answer_finish_reason,
                        }

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
                calls_bucket = ensure_actual_model_calls(retrieval_trace)
                finalize_actual_retrieval_emptiness(
                    retrieval_trace,
                    evidence_count=len(model_evidence_chunks or []),
                    searches_executed=int(calls_bucket.get("search_executions") or 0),
                    search_hits=int(calls_bucket.get("search_hits") or 0),
                )
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
                if workbook_chat_meta:
                    response.update(workbook_chat_meta)
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
                    if not workspace_memory_registered:
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



def packet_attempt_seed(
    events: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, ...], int]:
    """Rebuild per-packet attempt counters from durable checkpoint events.

    A restarted process must not number a second delivery of the same packet
    as the first one: the Qx.Hy evidence namespace is keyed by the attempt, so
    resuming from zero would let a fresh reference address another attempt's
    cards.
    """

    seeded: dict[tuple[str, ...], int] = {}
    for event in events or ():
        if not isinstance(event, Mapping):
            continue
        if str(event.get("event_type") or "") != "packet_checkpoint":
            continue
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            continue
        locators = tuple(
            str(item) for item in (payload.get("packet_locators") or []) if str(item)
        )
        if not locators:
            continue
        seeded[locators] = seeded.get(locators, 0) + 1
    return seeded


def packet_offer_counts(
    events: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    """How many times each source row was already put to the model.

    Derived only from durable ``packet_checkpoint`` events, which record the
    exact locator set of every packet that was sent.  This is the fairness
    memory of the packet rotation: without it a resumed sheet pass restarts at
    the head of the sheet and rows that sit behind a permanently gapped row are
    never offered.
    """

    counts: dict[str, int] = {}
    for event in events or ():
        if not isinstance(event, Mapping):
            continue
        if str(event.get("event_type") or "") != "packet_checkpoint":
            continue
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            continue
        for item in payload.get("packet_locators") or []:
            locator = str(item).strip()
            if locator:
                counts[locator] = counts.get(locator, 0) + 1
    return counts
