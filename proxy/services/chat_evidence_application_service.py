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
from pathlib import Path
from backend.runtime_paths import mutable_path
from typing import Any, Callable, Sequence

import httpx
from fastapi import HTTPException

from backend.inference.routing import (
    cloud_allowed,
    decide_provider,
    is_cloud_provider,
    memory_aware_provider,
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
    ModelResearchToolService,
    retrieve_smeta_norm_cards,
)
from proxy.services.source_locator_service import evidence_counts, source_map_item
from proxy.services.chat_evidence_manifest_service import build_evidence_manifest
from proxy.services.chat_capability_scope_service import filter_profile_tools
from proxy.services.typed_memory_projection_service import MemoryLimits, project_memory

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

    safe = selected(result, ("schema", "tool", "status", "code"))
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
    }


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
    """Expose exact model-visible evidence while keeping private prompt/memory redacted."""
    visible_kinds = {ContextKind.EVIDENCE, ContextKind.SOURCE_MAP}

    def section_trace(section) -> dict[str, Any]:
        item = {
            "kind": section.kind.value,
            "items": len(section.objects),
            "tokens": section.token_count,
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
            "work_id": str(source_row),
            "source_row": source_row,
            "section": str(item.get("section") or "").strip(),
            "title": str(item.get("title") or "").strip(),
            "quantity": item.get("quantity"),
            "unit": str(item.get("unit") or "").strip(),
            "norm_code": str(item.get("norm_code") or "").strip(),
        }
        for field_name in ("analogue", "coverage", "coefficient", "evidence_refs"):
            if field_name in item:
                row[field_name] = item[field_name]
        compact.append(row)
    return compact


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
    quoted_lines = [
        line[1:-1].strip()
        for line in visible_lines
        if len(line) >= 2 and line[0] == line[-1] and line[0] in {'"', "'"}
    ]
    raw_queries = quoted_lines or visible_lines

    queries: list[str] = []
    for item in raw_queries:
        if not isinstance(item, str):
            continue
        query = item.strip()
        if query:
            queries.append(query)
    return queries


def parse_model_rag_result(raw: str) -> tuple[str, list[dict[str, Any]]] | None:
    """Decode only an unambiguous table; preserve the authored answer and cell values."""

    required_fields = {"title", "unit", "quantity", "norm_code"}
    header_fields = {
        "source_row": "source_row",
        "№": "source_row",
        "№ п/п": "source_row",
        "№ пп": "source_row",
        "section": "section",
        "раздел": "section",
        "title": "title",
        "наименование": "title",
        "наименование работ": "title",
        "наименование работ (из вор)": "title",
        "unit": "unit",
        "ед. изм.": "unit",
        "ед. изм": "unit",
        "quantity": "quantity",
        "кол-во": "quantity",
        "norm_code": "norm_code",
        "norm_code (шифр)": "norm_code",
        "нормативная база (шифр нормы)": "norm_code",
        "нормативная база (norm code)": "norm_code",
        "analogue": "analogue",
        "analogue / coverage": "analogue",
        "аналог/обоснование": "analogue",
        "обоснование выбора и аналог": "analogue",
        "coverage": "coverage",
        "coverage (соответствие)": "coverage",
        "примечание инженера": "coverage",
        "примечания к составу работ": "coverage",
        "примечания к выбору": "coverage",
        "coefficient": "coefficient",
        "coefficient (кэф.)": "coefficient",
        "evidence_refs": "evidence_refs",
    }

    def field_name(value: str) -> str:
        normalized = " ".join(value.replace("**", "").strip().split()).casefold()
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
        if len(divider) != len(header) or not all(divider_cell(item) for item in divider):
            header_index += 1
            continue
        table_section = current_section
        row_index = header_index + 2
        while row_index < len(lines):
            values = cells(lines[row_index])
            if not values:
                break
            if len(values) != len(header):
                return None
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
                    parsed_source_row = number(value)
                    if not isinstance(parsed_source_row, int):
                        return None
                    row[name] = parsed_source_row
                elif name in {"quantity", "coefficient"}:
                    parsed_number = number(value)
                    if parsed_number is None:
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
            key = labelled_fields.get(" ".join(label.strip().split()).casefold())
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


def build_model_rag_evidence_groups(
    query_hits: Sequence[tuple[str, Sequence[Any]]],
    *,
    max_chars: int,
    hits_per_query: int,
) -> tuple[list[str], list[_ModelRagEvidenceChunk]]:
    """Render the profile-owned hit count without letting early queries crowd out later ones."""

    prepared: list[tuple[int, str, list[tuple[int, Any, str, str]]]] = []
    source_index = 0
    fixed_chars = 0
    segment_count = 0
    for query_index, (raw_query, raw_hits) in enumerate(query_hits, 1):
        query = str(raw_query or "").strip()
        query_header = f"[Поисковый запрос Q{query_index}] {query}"
        hits: list[tuple[int, Any, str, str]] = []
        fixed_chars += len(query_header)
        segment_count += 1
        for hit_index, hit in enumerate(list(raw_hits)[: max(1, int(hits_per_query))], 1):
            source_index += 1
            doc_name = str(getattr(hit, "doc_name", "") or "")
            score = float(getattr(hit, "score", 0.0) or 0.0)
            source_header = (
                f"[Q{query_index}.H{hit_index} | {doc_name} | score={score:.4f}]"
            )
            body = str(getattr(hit, "content", "") or "").strip()
            hits.append((hit_index, hit, source_header, body))
            fixed_chars += len(source_header) + 2
            segment_count += 1
        prepared.append((query_index, query_header, hits))

    fixed_chars += max(0, segment_count - 1) * 2
    if fixed_chars > max_chars:
        raise ValueError("MODEL_RAG_EVIDENCE_BUDGET_TOO_SMALL_FOR_ALL_QUERY_HEADERS")

    bodies = [body for _qi, _qh, hits in prepared for _hi, _hit, _sh, body in hits]
    body_budget = max_chars - fixed_chars
    low, high = 0, max((len(body) for body in bodies), default=0)
    while low < high:
        cap = (low + high + 1) // 2
        if sum(min(len(body), cap) for body in bodies) <= body_budget:
            low = cap
        else:
            high = cap - 1
    body_cap = low

    groups: list[str] = []
    chunks: list[_ModelRagEvidenceChunk] = []
    source_index = 0
    for query_index, query_header, hits in prepared:
        group_parts = [query_header]
        for hit_index, hit, source_header, body in hits:
            source_index += 1
            visible_body = body
            if len(visible_body) > body_cap:
                visible_body = (
                    visible_body[: max(0, body_cap - 1)].rstrip() + "…"
                    if body_cap
                    else ""
                )
            group_parts.append(f"{source_header}:\n{visible_body}")
            meta = dict(getattr(hit, "meta", {}) or {})
            meta.update(
                {
                    "model_query_index": query_index,
                    "model_hit_index": hit_index,
                    "model_evidence_ref": f"Q{query_index}.H{hit_index}",
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
    observed: list[int] = []
    for row in rows:
        source_row = row.get("source_row")
        if not isinstance(source_row, int) or source_row <= 0:
            errors.append("invalid_source_row")
            continue
        observed.append(source_row)
    observed_set = set(observed)
    for source_row in sorted(observed_set):
        if observed.count(source_row) > 1:
            errors.append(f"duplicate_source_row:{source_row}")
    if expected_source_rows > 0:
        expected = set(range(1, expected_source_rows + 1))
        errors.extend(
            f"missing_source_row:{source_row}"
            for source_row in sorted(expected - observed_set)
        )
        errors.extend(
            f"unexpected_source_row:{source_row}"
            for source_row in sorted(observed_set - expected)
        )

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

    for row in rows:
        source_row = row.get("source_row")
        refs = [
            str(item or "").strip().upper()
            for item in (row.get("evidence_refs") or [])
            if str(item or "").strip()
        ]
        if not refs:
            errors.append(f"missing_evidence_ref:{source_row}")
            continue
        unknown_refs = [ref for ref in refs if ref not in evidence_by_ref]
        errors.extend(f"unknown_evidence_ref:{ref}" for ref in unknown_refs)
        selected_code = code_identity(row.get("norm_code"))
        if selected_code and not any(
            code_identity(evidence_by_ref[ref].get("norm_code")) == selected_code
            for ref in refs
            if ref in evidence_by_ref
        ):
            errors.append(f"norm_code_not_in_referenced_evidence:{source_row}")
    return list(dict.fromkeys(errors))


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
    *, attachment_context: str, rendered_context: str,
) -> list[Any]:
    """Return model evidence as independently packable, ordered source blocks."""

    payload: list[Any] = []
    if str(attachment_context or "").strip():
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

    table_result = maybe_answer_table_query(
        req.question,
        chunks,
        storage_root=mutable_path("./storage/datasets"),
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
        storage_root=mutable_path("./storage/datasets"),
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

    # ADR-12 слой 2: форму ответа диктует интент вопроса (детерминированно, до генерации).
    answer_form = apply_response_length(classify_answer_form(req.question), req.response_length)
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
            async with httpx.AsyncClient(timeout=300.0) as client:
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
                            dict(active_model_result.response.usage),
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
                selected_sources_only = bool(
                    getattr(req, "selected_sources_only", False)
                )
                profile_tools = filter_profile_tools(
                    profile_tools,
                    selected_sources_only=selected_sources_only,
                )
                retrieval_trace["capability_scope"] = {
                    "selected_sources_only": selected_sources_only,
                    "public_web_available": not selected_sources_only,
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
                            profile_system_prompt(profile_snapshot, strict=False)
                            + "\n\nПрочитай приложенный материал целиком. Сформулируй поисковые "
                            "запросы к выбранным датасетам, необходимые для подбора evidence "
                            "по всем фактическим строкам исходного материала. Число запросов "
                            "определяешь ты; фиксированного лимита нет. Сейчас не выбирай нормы "
                            "и не отвечай по существу — верни только сами поисковые запросы, "
                            "каждый с новой строки."
                        ),
                        request_payload={
                            "question": str(req.question or ""),
                            "dataset_ids": [str(item) for item in _dataset_ids],
                        },
                        checkpoint=(),
                        working_memory=(),
                        evidence=selector_evidence,
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
                    model_queries = parse_model_rag_queries(query_text)
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
                        if str(payload.get("status") or "") != "ok"
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
                    }
                elif tool_loop_enabled:
                    retrieval_limits = effective_retrieval_policy(profile_snapshot)
                    tool_loop_stage = "harness"
                    try:
                        from proxy.services.tool_harness_service import harness

                        tool_harness = harness()

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
                                        )
                                        selector_source_map = answer_source_map
                                selected_calls.append(call)
                                calls_remaining -= 1
                                safe_payload = safe_workbook_history_projection(payload)
                                tool_results_for_model.append(
                                    safe_payload if safe_payload else payload
                                )
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
                        question_tail += (
                            "\nДай итоговый ответ обычным текстом по всем строкам исходного ВОР. Для каждой "
                            "строки явно укажи source_row, section, title, unit, quantity, выбранный тобой "
                            "norm_code, analogue, coverage, coefficient и evidence_refs Qx.Hy. Не добавляй "
                            "status и не ограничивай количество строк. Если выбираешь карточку как норму "
                            "или инженерный аналог, укажи её точный шифр в norm_code; оставляй его пустым "
                            "только если не выбрана ни одна карточка. Для каждой строки обязательно укажи "
                            "точную evidence_refs Qx.Hy выбранной карточки; не сокращай её до Qx. Не выводи "
                            "JSON. Код не подтверждает и не меняет твой выбор. Ответ должен вместить все "
                            "строки: без вводного обзора и итоговых рекомендаций, кратко по одной строке ВОР."
                        )
                        fixed_model_rag_evidence = selector_evidence_payload(
                            attachment_context=attachment_context,
                            rendered_context="",
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
                        (
                            model_rag_evidence_groups,
                            model_evidence_chunks,
                        ) = build_model_rag_evidence_groups(
                            model_rag_query_hits,
                            max_chars=min(
                                context_chars_limit,
                                remaining_group_tokens * 2,
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
                    parsed_model_result = parse_model_rag_result(answer)
                    model_result_rows: list[dict[str, Any]] = []
                    model_result_errors: list[str] = []
                    if parsed_model_result is not None:
                        answer, model_result_rows = parsed_model_result
                        from proxy.services.smeta_chat_adapter_service import (
                            _smeta_source_row_count,
                        )

                        model_result_errors = validate_model_rag_result_structure(
                            model_result_rows,
                            model_evidence_chunks,
                            expected_source_rows=_smeta_source_row_count(
                                attachment_context
                            ),
                        )
                        if model_result_errors:
                            retrieval_trace["model_result"] = {
                                "schema": "les_model_rag_result_v1",
                                "status": "structural_error",
                                "row_count": len(model_result_rows),
                                "packaged": False,
                                "errors": model_result_errors,
                            }
                    else:
                        retrieval_trace["model_result"] = {
                            "schema": "les_model_rag_result_v1",
                            "status": "unstructured",
                            "packaged": False,
                        }
                    if token_sink is not None:
                        await token_sink({"event": "reset", "data": ""})
                        if answer:
                            await token_sink({"event": "token", "data": answer})
                    attachment_id = str(getattr(req, "attachment_id", None) or "").strip()
                    packaging_tools = (
                        ["build_lsr_workbook"]
                        if "build_lsr_workbook" in profile_tools
                        else []
                    )
                    if (
                        parsed_model_result is not None
                        and model_result_rows
                        and not model_result_errors
                        and attachment_id
                        and packaging_tools
                        and workbook_tool_executor is not None
                        and canonical_execution_mode is CanonicalRouteMode.ACTIVE
                    ):
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
                                    "decisions": model_result_rows,
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
