"""Generic document -> VOR -> model selection -> priced LSR workflow.

The estimating model owns professional choices.  LES provides typed catalog
tools, validates evidence and units, calculates deterministically, and returns
actionable diagnostics so the same model can repair malformed decisions.

Flexible interpretation is explicitly reversible:
``balanced`` repairs only unambiguous aliases to cards opened by the model;
``legacy`` retains the former permissive Gemini resolver for rollback;
``off`` disables interpretation.  Change this module only with the protected
five-row Qwen benchmark required by ``AGENTS.md``.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import math
import os
import re
from dataclasses import asdict
from pathlib import Path
from time import perf_counter
from typing import Any, Callable
from uuid import uuid4

from proxy.services import fgis_price_service, gesn_service, nr_sp_service
from proxy.services.kac_web_service import collect_quotes
from proxy.services.prompt_registry_service import (
    smeta_native_skill_prompt,
    smeta_phase_common_prompt,
    smeta_phase_instruction,
)
from proxy.services.rim_trace_xlsx_service import render_lsr_xlsx
from proxy.smeta_core.contracts import NormBinding, ResourceBinding, WorkItem
from proxy.smeta_core.norm_browser import (
    browse_norm_catalog,
    browse_norms_many,
    catalog_compass_score,
    rank_norm_catalog_collections,
    rank_norm_catalog_tables,
)
from proxy.smeta_core.norm_validator import units_compatible, validate_binding
from proxy.smeta_core.professional_review import (
    EvidenceBudget,
    MappingRevision,
    ModelScopePlan,
    detect_professional_conflicts,
    save_mapping_revision,
)
from proxy.smeta_core.resource_normalizer import normalize_norm_resources
from proxy.smeta_core.source_intake import intake_vor_document
from proxy.smeta_core.application import calculate_visible_rows, calculate_visible_rows_revision


Exchange = Callable[[list[dict[str, Any]], list[dict[str, Any]]], dict[str, Any]]
MappingExchange = Callable[[list[dict[str, Any]], dict[str, Any]], dict[str, Any]]
Progress = Callable[[dict[str, Any]], None]
AgentBatchRunner = Callable[..., dict[str, Any]]
Checkpoint = Callable[[dict[str, Any]], None]
DecisionCheckpoint = Callable[[str, dict[str, Any]], None]
WorkContextEnricher = Callable[[dict[str, Any]], dict[str, Any]]

_COMPRESSIBLE_TOOL_RESULTS = frozenset({
    "browse_norm_catalog",
    "continue_norm_catalog",
    "ask_norm_catalog_fact",
    "broaden_norm_catalog",
    "unbound_norm_catalog",
    "reuse_norm_catalog_route",
    "search_norms_batch",
    "read_norms_batch",
})
_RIM_MAX_READ_CARDS_PER_CALL = 2
MAPPING_VALIDATION_CONTRACT_VERSION = "grounded-unit-scoped-mapping-v15"
_PHASE_ORDER = (
    "family_root",
    "family_select",
    "collection",
    "section_select",
    "table_select",
    "norm_search",
    "norm_read",
    "norm_evidence",
)


class MappingTransportTimeout(RuntimeError):
    """Structured mapping timed out; the identical payload must not be retried."""


class MappingValidationExhausted(RuntimeError):
    """Bounded schema repair exhausted; keep accepted rows and continue."""


def _is_recoverable_batch_mapping_error(error: BaseException) -> bool:
    """True when a failed batch must not destroy earlier accepted decisions."""
    if isinstance(error, MappingValidationExhausted):
        return True
    text = str(error or "")
    return (
        "smeta model mapping failed validation after" in text
        or "smeta model did not submit mapping within" in text
        or "smeta agent ended without terminal mapping for:" in text
    )


def _mapping_chunk_size() -> int:
    """Bound only the JSON transport; the model still owns every decision."""
    raw = os.getenv("LES_SMETA_DOCUMENT_MAPPING_CHUNK", "8").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 8


def _mapping_evidence_repair_turns() -> int:
    """Bounded TypeChat-style return from invalid terminal JSON to tools."""
    raw = os.getenv("LES_SMETA_MAPPING_EVIDENCE_REPAIR_TURNS", "4").strip()
    try:
        return max(0, min(8, int(raw)))
    except ValueError:
        return 4


def _catalog_shortlist_menu_ready(
    cards: list[Any] | tuple[Any, ...] | None,
    *,
    rerank_status: Any = None,
) -> tuple[bool, str]:
    """Navigation menus may proceed when cards exist, even if the reranker degraded.

    Cross-encoder failure on Windows without ``windows-reranker`` still returns a
    lexical/RRF shortlist. Blocking on ``rerank_status=ok`` left local Qwen stuck
    for a dozen turns on family→collection with zero searches.
    """
    items = [
        card for card in (cards or [])
        if isinstance(card, dict) and (
            str(card.get("node_id") or card.get("key") or card.get("cipher") or "").strip()
        )
    ]
    status = str(rerank_status or "").strip() or "missing"
    if items:
        return True, status
    return False, status


def _compact_route_evidence_cache_for_model(
    routes: list[dict[str, Any]] | tuple[dict[str, Any], ...] | dict[str, dict[str, Any]],
    *,
    limit: int = 24,
) -> list[dict[str, str]]:
    """Show reusable catalog routes without shipping bulky passport payloads."""
    values: list[dict[str, Any]]
    if isinstance(routes, dict):
        values = [dict(item) for item in routes.values() if isinstance(item, dict)]
    else:
        values = [dict(item) for item in routes if isinstance(item, dict)]
    compact: list[dict[str, str]] = []
    for route in values[: max(0, int(limit))]:
        cache_id = str(route.get("cache_id") or "").strip()
        if not cache_id:
            continue
        compact.append({
            "cache_id": cache_id[:160],
            "family": str(route.get("family") or "")[:80],
            "collection": str(route.get("collection") or "")[:80],
            "section": str(route.get("section") or "")[:40],
            "table_code": str(route.get("table_code") or "")[:40],
            "source_work_id": str(route.get("source_work_id") or "")[:40],
        })
    return compact


def _is_timeout_error(error: BaseException) -> bool:
    text = f"{type(error).__name__}: {error}".casefold()
    return "readtimeout" in text or "timed out" in text or "timeout" in text


def _compress_tool_result(name: str, payload: Any) -> Any:
    """Keep traceable navigation facts while dropping stale bulky payloads."""
    if not isinstance(payload, dict):
        return {"compressed": True, "tool": name}
    envelope = {
        "compressed": True,
        "tool": name,
        **{
            key: payload.get(key)
            for key in (
                "ok", "error", "next_action", "focus_work_id",
                "deferred_work_ids",
            )
            if payload.get(key) not in (None, "", [])
        },
    }
    if name == "browse_norm_catalog":
        rows = []
        for item in payload.get("rows") or payload.get("items") or []:
            if not isinstance(item, dict):
                continue
            compact_row = {
                key: item.get(key)
                for key in (
                    "work_id", "ok", "level", "family", "collection", "section",
                    "table", "families", "collections", "sections", "tables", "error",
                )
                if item.get(key) not in (None, "", [])
            }
            shortlist = [
                {
                    key: entry.get(key)
                    for key in (
                        "key", "title", "navigation_kind", "navigation_score",
                    )
                    if entry.get(key) not in (None, "")
                }
                for entry in (item.get("items") or [])[:6]
                if isinstance(entry, dict)
            ]
            if shortlist:
                compact_row["collection_shortlist"] = shortlist
            passport = (
                item.get("collection_passport")
                if isinstance(item.get("collection_passport"), dict)
                else {}
            )
            if passport:
                compact_row["collection_passport"] = {
                    "collection": passport.get("collection"),
                    "title": passport.get("title"),
                    "representative_sections": list(
                        passport.get("representative_sections") or []
                    )[:4],
                }
            rows.append(compact_row)
        return {**envelope, "rows": rows}
    if name == "search_norms_batch":
        rows = []
        for item in payload.get("rows") or payload.get("items") or []:
            if not isinstance(item, dict):
                continue
            candidates = item.get("candidates") or []
            rows.append({
                "work_id": item.get("work_id"),
                "ok": item.get("ok"),
                "candidate_codes": [
                    str(card.get("norm_code") or "")
                    for card in candidates
                    if isinstance(card, dict) and card.get("norm_code")
                ],
                "candidates": [
                    {
                        "norm_code": str(card.get("norm_code") or ""),
                        "title": str(
                            card.get("title") or card.get("norm_name") or ""
                        )[:240],
                        "measure_unit": str(card.get("measure_unit") or ""),
                        "candidate_rank": card.get("candidate_rank"),
                    }
                    for card in candidates
                    if isinstance(card, dict) and card.get("norm_code")
                ],
                "page": item.get("page"),
                "has_more": item.get("has_more"),
                "error": item.get("error"),
            })
        return {**envelope, "rows": rows}
    if name == "read_norms_batch":
        rows = []
        for item in payload.get("rows") or []:
            if not isinstance(item, dict):
                continue
            rows.append({
                "work_id": item.get("work_id"),
                "ok": item.get("ok"),
                "norm_codes": [
                    str(card.get("norm_code") or "")
                    for card in (item.get("norms") or [])
                    if isinstance(card, dict) and card.get("norm_code")
                ],
                "error": item.get("error"),
            })
        return {**envelope, "rows": rows}
    return envelope


def _prune_stale_tool_evidence(
    conversation: list[dict[str, Any]], *, keep_recent: int = 1,
) -> None:
    """Keep only the current typed read full; compact navigation and old reads."""
    compressible: list[int] = []
    readable: list[int] = []
    for index, message in enumerate(conversation):
        if str(message.get("role") or "") != "tool":
            continue
        name = str(message.get("name") or "")
        if name in _COMPRESSIBLE_TOOL_RESULTS:
            compressible.append(index)
            if name == "read_norms_batch":
                readable.append(index)
    keep_count = max(0, int(keep_recent))
    keep = set(readable[-keep_count:]) if keep_count else set()
    for index in compressible:
        if index in keep:
            continue
        message = conversation[index]
        if message.get("_les_compressed"):
            continue
        name = str(message.get("name") or "")
        try:
            payload = json.loads(str(message.get("content") or "") or "{}")
        except json.JSONDecodeError:
            payload = {"raw": str(message.get("content") or "")[:200]}
        message["content"] = json.dumps(
            _compress_tool_result(name, payload),
            ensure_ascii=False,
            default=str,
        )
        message["_les_compressed"] = True
    for message in conversation[:-2]:
        if str(message.get("role") or "") == "assistant":
            message.pop("thinking", None)
            if message.get("tool_calls"):
                message["content"] = None
                message["_les_content_compressed"] = True


def _model_request_shape(
    conversation: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> dict[str, Any]:
    """Measure the exact serialized frame sent to one model call."""
    prompt_json = json.dumps(
        conversation,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    tools_json = json.dumps(
        tools,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    prefix_json = json.dumps(
        {"messages": conversation[:2], "tools": tools},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    working_memory_bytes = 0
    visible_children_count = 0
    for message in reversed(conversation):
        content = str(message.get("content") or "")
        if "smeta_norm_agent_working_memory_v1" not in content:
            continue
        working_memory_bytes = len(content.encode("utf-8"))
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            break
        visible_children_count = sum(
            len(item.get("catalog_visible_children") or [])
            for item in (payload.get("work_evidence_status") or [])
            if isinstance(item, dict)
        )
        break
    return {
        "prompt_bytes": len(prompt_json.encode("utf-8")),
        "tool_schema_bytes": len(tools_json.encode("utf-8")),
        "working_memory_bytes": working_memory_bytes,
        "visible_children_count": visible_children_count,
        "message_count": len(conversation),
        "system_sha256": hashlib.sha256(
            str((conversation[0] if conversation else {}).get("content") or "").encode(
                "utf-8"
            )
        ).hexdigest(),
        "tool_schema_sha256": hashlib.sha256(
            tools_json.encode("utf-8")
        ).hexdigest(),
        "stable_prefix_sha256": hashlib.sha256(
            prefix_json.encode("utf-8")
        ).hexdigest(),
    }


def _decision_name(selection: dict[str, Any]) -> str:
    if selection.get("norm_code"):
        return "bind"
    if selection.get("covered_by_work_id"):
        return "covered_by"
    return "unbound"


def _stable_unique_text(values: list[Any]) -> list[str]:
    """Normalize and sort transport text without adding professional content."""
    normalized = {
        " ".join(str(value).split())[:240]
        for value in values
        if str(value).strip()
    }
    return sorted(normalized, key=lambda value: (value.casefold(), value))


def _candidate_payload(
    work: dict[str, Any],
    query: str | list[str],
    *,
    limit: int,
    page: int = 0,
    search_results: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    page_size = max(1, int(limit))
    page_number = max(0, int(page))
    page_start = page_number * page_size
    page_end = page_start + page_size
    queries = _stable_unique_text(query if isinstance(query, list) else [query])
    cards: list[dict[str, Any]] = []
    seen: set[str] = set()
    backends: list[str] = []
    retrieval_traces: list[dict[str, Any]] = []
    source_integrity: dict[str, Any] = {}
    candidate_sets: list[tuple[str, list[dict[str, Any]]]] = []
    results = search_results or browse_norms_many(queries, limit=min(50, max(limit, limit * 3)))
    for search_query in queries:
        result = results.get(search_query) or {}
        backends.append(str(result.get("backend") or ""))
        if isinstance(result.get("retrieval_trace"), dict):
            retrieval_traces.append(dict(result["retrieval_trace"]))
        source_integrity = result.get("source_integrity") or source_integrity
        ranked = []
        for card in result.get("cards") or []:
            code = str(card.get("norm_code") or "")
            if not code:
                continue
            # Несовпадение единиц — важный сигнал для модели, но не основание
            # скрыто выкинуть кандидата: комплексная работа может требовать
            # декомпозиции или пересчёта к измерителю нормы.
            item = dict(card)
            item["unit_compatible"] = not work.get("unit") or units_compatible(
                str(work.get("unit") or ""),
                str(card.get("measure_unit") or ""),
            )
            ranked.append(item)
        candidate_sets.append((search_query, ranked))
    max_depth = max((len(items) for _, items in candidate_sets), default=0)
    for rank in range(max_depth):
        for search_query, items in candidate_sets:
            if rank >= len(items):
                continue
            card = items[rank]
            code = str(card.get("norm_code") or "")
            if code in seen:
                continue
            seen.add(code)
            cards.append({
                "norm_code": code,
                "norm_key": str(card.get("norm_key") or ""),
                "edition": str(card.get("edition") or ""),
                "base_type": str(card.get("base_type") or ""),
                "collection": str(card.get("bare_code") or "")[:2] or _norm_collection(code),
                "title": str(card.get("title") or "")[:320],
                "measure_unit": card.get("measure_unit"),
                "unit_compatible": bool(card.get("unit_compatible", True)),
                "work_steps": [str(step)[:180] for step in list(card.get("work_steps") or [])[:4]],
                "resource_count": int(card.get("resource_count") or 0),
                "resource_kinds": card.get("resource_kinds") or {},
                "resource_preview": [
                    {
                        "kind": str(value.get("kind") or ""),
                        "code": str(value.get("code") or ""),
                        "name": str(value.get("name") or "")[:160],
                        "unit": str(value.get("unit") or ""),
                    }
                    for value in (card.get("resource_preview") or [])[:6]
                    if isinstance(value, dict)
                ],
                "source_ref": str(card.get("source_ref") or "")[:320],
                "matched_query": search_query,
                "nr_sp_candidates": [
                    {
                        "rule_id": rule.get("rule_id"),
                        "label": rule.get("label"),
                        "nr_pct": rule.get("nr_pct"),
                        "sp_pct": rule.get("sp_pct"),
                        "basis": rule.get("basis"),
                    }
                    for rule in nr_sp_service.candidates(code=code)
                ],
            })
            if len(cards) >= page_end:
                break
        if len(cards) >= page_end:
            break
    page_cards = cards[page_start:page_end]
    rerank_statuses = list(dict.fromkeys(
        str(trace.get("rerank_status") or "")
        for trace in retrieval_traces
        if str(trace.get("rerank_status") or "")
    ))
    return {
        "work_id": work["work_id"],
        "source": {
            "title": work.get("title"),
            "unit": work.get("unit"),
            "quantity": work.get("quantity"),
            "section": work.get("section"),
            "note": work.get("note"),
            "neighbor_context": work.get("neighbor_context") or [],
        },
        "query": queries,
        "backend": ",".join(dict.fromkeys(backends)),
        "retrieval_policy": "native_rrf_then_rerank_required",
        "rerank_status": rerank_statuses,
        "reranked": any(bool(trace.get("reranked")) for trace in retrieval_traces),
        "source_integrity": source_integrity,
        "candidates": page_cards,
        "page": page_number,
        "page_size": page_size,
        "has_more": max_depth > page_end,
    }


def _norm_collection(code: object) -> str:
    """Expose the collection encoded by a typed norm ref without choosing scope."""
    bare = gesn_service._split_norm_ref(code)[1]
    return bare[:2] if bare else ""


def _questions_to_ask_for_norm(code: str) -> list[str]:
    """Return bounded navigation hints; they never make a norm calculable."""
    from proxy.services.smeta_norm_store import get_smeta_norm_store

    profile = get_smeta_norm_store().norm_profile(code)
    navigation = profile.get("navigation") if isinstance(profile, dict) else {}
    questions = (
        navigation.get("questions_to_ask")
        if isinstance(navigation, dict)
        else []
    )
    return [
        str(question).strip()
        for question in (questions or [])
        if str(question).strip()
    ][:8]


def _opened_norm_card(code: str, candidate: dict[str, Any]) -> dict[str, Any] | None:
    norm = gesn_service.get_norm(code, strict_family=True)
    if not norm:
        return None
    resources = []
    for resource in list(norm.get("resources") or []):
        resources.append({
            "code": resource.get("code"),
            "name": resource.get("name"),
            "unit": resource.get("unit"),
            "kind": resource.get("kind"),
            "per_unit": resource.get("per_unit"),
        })
    return {
        "norm_code": code,
        "norm_key": str(candidate.get("norm_key") or norm.get("key") or ""),
        "edition": str(candidate.get("edition") or ""),
        "base_type": str(candidate.get("base_type") or norm.get("base_type") or ""),
        "collection": str(candidate.get("collection") or _norm_collection(code)),
        "title": norm.get("name"),
        "measure_unit": norm.get("unit"),
        "work_steps": list(norm.get("work_steps") or [])[:24],
        "resources": resources,
        "resource_count": len(resources),
        "nr_sp_candidates": candidate.get("nr_sp_candidates") or [],
        "source_ref": candidate.get("source_ref") or "",
        "questions_to_ask": list(
            candidate.get("questions_to_ask") or _questions_to_ask_for_norm(code)
        )[:8],
        "card_role": "structured_normative_store_evidence",
    }


def _norm_card_for_model(card: dict[str, Any], *, include_resources: bool) -> dict[str, Any]:
    """Keep full resource evidence model-addressable without repeating it in every read."""
    payload = dict(card)
    resources = [item for item in (payload.pop("resources", []) or []) if isinstance(item, dict)]
    kinds: dict[str, int] = {}
    for resource in resources:
        kind = str(resource.get("kind") or "other")
        kinds[kind] = kinds.get(kind, 0) + 1
    payload["resource_count"] = len(resources)
    payload["resource_kinds"] = kinds
    payload["resources_included"] = bool(include_resources)
    if include_resources:
        payload["resources"] = resources
    return payload


def _compact_norm_card_for_global_review(card: dict[str, Any]) -> dict[str, Any]:
    """Build a bounded cross-row evidence map; disputed cards remain re-readable."""
    resources = [item for item in (card.get("resources") or []) if isinstance(item, dict)]
    kinds: dict[str, int] = {}
    for resource in resources:
        kind = str(resource.get("kind") or "other")
        kinds[kind] = kinds.get(kind, 0) + 1
    preview = [
        {
            "kind": str(resource.get("kind") or ""),
            "code": str(resource.get("code") or ""),
            "name": str(resource.get("name") or "")[:140],
            "unit": str(resource.get("unit") or ""),
        }
        for resource in resources
        if str(resource.get("name") or resource.get("code") or "").strip()
    ][:8]
    return {
        "norm_code": str(card.get("norm_code") or ""),
        "norm_key": str(card.get("norm_key") or ""),
        "edition": str(card.get("edition") or ""),
        "base_type": str(card.get("base_type") or ""),
        "collection": str(card.get("collection") or ""),
        "title": str(card.get("title") or "")[:320],
        "measure_unit": str(card.get("measure_unit") or ""),
        "work_steps": [str(step)[:220] for step in (card.get("work_steps") or [])[:12]],
        "resource_count": int(card.get("resource_count") or len(resources)),
        "resource_kinds": dict(card.get("resource_kinds") or kinds),
        "resource_preview": preview,
        "source_ref": str(card.get("source_ref") or "")[:360],
        "full_card_available_via": "read_norms_batch",
    }


def _compact_catalog_menu_for_model(
    items: list[dict[str, Any]],
    *,
    limit: int = 12,
    phase: str = "",
) -> list[dict[str, Any]]:
    """Keep exact selectable ids and short evidence fields in the model frame."""
    evidence_fields = (
        {
            "node_id", "parent_id", "node_type", "cipher", "title",
            "official_name", "source_ref", "norm_count", "navigation_score",
        }
        if phase in {"section_select", "table_select"}
        else {
            "node_id", "parent_id", "node_type", "cipher", "title",
            "official_name", "purpose", "typical_scope", "not_for",
            "source_ref", "norm_count", "navigation_score",
        }
    )
    compact: list[dict[str, Any]] = []
    for item in items[: max(1, int(limit))]:
        if not isinstance(item, dict):
            continue
        compact.append({
            key: copy.deepcopy(value)
            for key, value in item.items()
            if key in evidence_fields
            and value not in (None, "", [])
        })
    return compact


def _normalize_mapping_row_transport(item: dict[str, Any]) -> dict[str, Any]:
    """Repair only a misplaced row identifier; never revise model decisions."""
    normalized = dict(item)
    check = normalized.get("technology_check")
    if not str(normalized.get("work_id") or "").strip() and isinstance(check, dict):
        nested_work_id = str(check.get("work_id") or "").strip()
        if nested_work_id:
            normalized["work_id"] = nested_work_id
            normalized["technology_check"] = {
                key: value for key, value in check.items() if key != "work_id"
            }
    return normalized


def _normalize_norm_codes_transport(item: dict[str, Any]) -> list[str]:
    """Accept Gemma's scalar spelling of a one-element norm code list."""
    raw = item.get("norm_codes")
    if isinstance(raw, list):
        values = raw
    elif raw is not None:
        values = [raw]
    else:
        scalar = item.get("norm_code")
        values = [scalar] if scalar is not None else []
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


_EXACT_BIND_DENIAL_RE = re.compile(
    r"\bне\s+(?:"
    r"примен\w*"
    r"|соответств\w*"
    r"|совпад\w*"
    r"|подход\w*"
    r")\b",
    flags=re.IGNORECASE,
)


def _exact_bind_reason_self_contradiction_errors(item: dict[str, Any]) -> list[str]:
    """Reject exact binds whose own reason denies applicability.

    Transport-only guard: does not choose another norm. Not draft-eligible, so
    candidate promotion cannot keep a self-contradicting exact bind.
    """
    if str(item.get("selection_kind") or "").strip().casefold() != "exact":
        return []
    reason = " ".join(str(item.get("reason") or "").split())
    if not reason or not _EXACT_BIND_DENIAL_RE.search(reason):
        return []
    return [
        "selection_kind exact contradicts reason that denies applicability; "
        "choose unbound or broaden to another table — do not bind this norm as exact"
    ]


def _technology_check_errors(
    item: dict[str, Any], *, work_id: str = "",
) -> list[str]:
    """Validate bind evidence shape without judging the model's applicability conclusion."""
    errors: list[str] = []
    selection_kind = str(item.get("selection_kind") or "")
    applicability = str(item.get("applicability") or "")
    analog_limitations = [
        str(value).strip()
        for value in (item.get("analog_limitations") or [])
        if str(value).strip()
    ]
    if selection_kind not in {"exact", "analog"}:
        errors.append("selection_kind must be exact|analog")
    if applicability not in {"exact", "close_analog", "weak_analog"}:
        errors.append("applicability must be exact|close_analog|weak_analog")
    if selection_kind == "exact" and (
        applicability in {"close_analog", "weak_analog"} or analog_limitations
    ):
        errors.append(
            "selection_kind exact contradicts analog applicability or limitations"
        )
    if selection_kind == "analog" and applicability == "exact":
        errors.append("selection_kind analog contradicts exact applicability")
    check = item.get("technology_check")
    if not isinstance(check, dict):
        return [*errors, "technology_check must be an object"]
    list_fields = (
        "matched_operations", "missing_operations", "extra_operations", "foreign_resources",
        "overlaps_with_work_ids", "conditions_checked", "unresolved_conditions",
    )
    for field in list_fields:
        if not isinstance(check.get(field), list):
            errors.append(f"technology_check.{field} must be an array")
    if not [value for value in (check.get("matched_operations") or []) if str(value).strip()]:
        errors.append("technology_check.matched_operations must describe matched work")
    if not str(check.get("overlap_resolution") or "").strip():
        errors.append("technology_check.overlap_resolution is required")
    if not [value for value in (check.get("conditions_checked") or []) if str(value).strip()]:
        errors.append("technology_check.conditions_checked must describe checked conditions")
    if work_id and work_id in {
        str(value).strip()
        for value in (check.get("overlaps_with_work_ids") or [])
        if str(value).strip()
    }:
        errors.append("technology_check.overlaps_with_work_ids cannot contain its own work_id")
    if str(check.get("conclusion") or "") not in {"applicable", "applicable_with_limitations"}:
        errors.append("technology_check.conclusion must be applicable|applicable_with_limitations")
    if selection_kind == "exact" and (
        str(check.get("conclusion") or "") == "applicable_with_limitations"
        or any(str(value).strip() for value in (check.get("missing_operations") or []))
        or any(str(value).strip() for value in (check.get("unresolved_conditions") or []))
    ):
        errors.append(
            "selection_kind exact contradicts missing operations, unresolved conditions, "
            "or a limited technology conclusion"
        )
    return errors


_EXACT_MATCH_NOISE = frozenset({
    "монтаж", "монтажа", "установка", "установки", "установке",
    "оборудование", "оборудования", "работа", "работы", "шт", "штука",
    "помещение", "помещения", "масса", "массой", "цвет", "размер",
})


def _distinctive_exact_terms(value: object) -> set[str]:
    """Return coarse lexical anchors used only to validate an ``exact`` claim."""
    terms: set[str] = set()
    for token in re.findall(r"[0-9A-Za-zА-Яа-яЁё]+", str(value or "").casefold()):
        if len(token) < 4 or token in _EXACT_MATCH_NOISE or token.isdigit():
            continue
        terms.add(token[:4] if len(token) > 4 else token)
    return terms


def _candidate_evaluation_errors(
    item: dict[str, Any],
    *,
    candidates_for_work: dict[str, dict[str, Any]],
    opened_for_work: dict[str, dict[str, Any]],
    source_work: dict[str, Any] | None = None,
) -> list[str]:
    """Validate model-owned comparison trace without judging which norm should win."""
    evaluations = item.get("candidate_evaluations")
    if not isinstance(evaluations, list) or not evaluations:
        return ["candidate_evaluations must contain the selected candidate"]

    errors: list[str] = []
    def canonical_opened_code(value: object) -> str:
        resolved = _resolve_norm_code_transport(value, opened_for_work)
        card = opened_for_work.get(resolved) if resolved else None
        return str((card or {}).get("norm_code") or resolved or value or "").strip()

    selected_code = canonical_opened_code(item.get("norm_code"))
    opened_codes = {
        str((card or {}).get("norm_code") or code).strip()
        for code, card in opened_for_work.items()
        if str((card or {}).get("norm_code") or code).strip()
    }
    evaluated_codes: set[str] = set()
    evaluation_signatures: dict[str, tuple[Any, ...]] = {}
    selected_evaluations = 0
    selected_evaluation: dict[str, Any] | None = None
    allowed = {
        "operation_match": {"exact", "partial", "none", "unknown"},
        "object_match": {"exact", "partial", "none", "unknown"},
        "unit_match": {"compatible", "convertible", "conflict", "unknown"},
        "scope_match": {"exact", "partial", "foreign", "unknown"},
        "decision": {"selected", "rejected", "uncertain"},
    }
    for index, evaluation in enumerate(evaluations):
        prefix = f"candidate_evaluations[{index}]"
        if not isinstance(evaluation, dict):
            errors.append(f"{prefix} must be an object")
            continue
        raw_code = str(evaluation.get("candidate_code") or "").strip()
        code = canonical_opened_code(raw_code)
        if not code:
            errors.append(f"{prefix}.candidate_code is required")
            continue
        if code in evaluated_codes:
            signature = (
                str(evaluation.get("operation_match") or ""),
                str(evaluation.get("object_match") or ""),
                str(evaluation.get("unit_match") or ""),
                str(evaluation.get("scope_match") or ""),
                tuple(str(value) for value in (evaluation.get("foreign_resources") or [])),
                str(evaluation.get("decision") or ""),
            )
            if signature != evaluation_signatures.get(code):
                errors.append(f"{prefix}.candidate_code conflicts with an earlier evaluation")
            # Literal/semantically identical duplicates are a serialization
            # artifact. Keep the model payload intact in trace, but count the
            # candidate once for structural evidence validation.
            continue
        evaluated_codes.add(code)
        evaluation_signatures[code] = (
            str(evaluation.get("operation_match") or ""),
            str(evaluation.get("object_match") or ""),
            str(evaluation.get("unit_match") or ""),
            str(evaluation.get("scope_match") or ""),
            tuple(str(value) for value in (evaluation.get("foreign_resources") or [])),
            str(evaluation.get("decision") or ""),
        )
        if code not in opened_codes and code != selected_code:
            errors.append(f"{prefix}.candidate_code was not opened through read_norms_batch")
        for field, values in allowed.items():
            if str(evaluation.get(field) or "") not in values:
                errors.append(f"{prefix}.{field} has an unsupported value")
        if not isinstance(evaluation.get("foreign_resources"), list):
            errors.append(f"{prefix}.foreign_resources must be an array")
        if not str(evaluation.get("reason") or "").strip():
            errors.append(f"{prefix}.reason is required")
        decision = str(evaluation.get("decision") or "")
        if code == selected_code and decision == "selected":
            selected_evaluations += 1
            selected_evaluation = evaluation

    if selected_evaluations != 1:
        errors.append("candidate_evaluations must mark the submitted norm exactly once as selected")
    elif selected_evaluation is not None:
        selection_kind = str(item.get("selection_kind") or "")
        operation_match = str(selected_evaluation.get("operation_match") or "")
        object_match = str(selected_evaluation.get("object_match") or "")
        unit_match = str(selected_evaluation.get("unit_match") or "")
        scope_match = str(selected_evaluation.get("scope_match") or "")
        if (
            operation_match == "none"
            or object_match == "none"
            or unit_match == "conflict"
            or scope_match == "foreign"
        ):
            errors.append(
                "selected candidate contradicts bind: operation/object cannot be "
                "none, unit cannot conflict, and scope cannot be foreign"
            )
        if selection_kind == "exact" and (
            operation_match != "exact"
            or object_match != "exact"
            or scope_match != "exact"
            or unit_match not in {"compatible", "convertible"}
        ):
            errors.append(
                "selection_kind exact requires exact operation, object and scope "
                "matches plus a compatible or convertible unit"
            )
        if selection_kind == "exact":
            selected_card = opened_for_work.get(selected_code) or {}
            source_terms = _distinctive_exact_terms(" ".join(
                str((source_work or {}).get(name) or "")
                for name in ("title", "note")
            ))
            card_terms = _distinctive_exact_terms(" ".join([
                str(selected_card.get("title") or selected_card.get("norm_name") or ""),
                *[
                    str(value)
                    for value in (selected_card.get("work_steps") or [])
                    if str(value).strip()
                ],
            ]))
            if source_terms and card_terms and source_terms.isdisjoint(card_terms):
                errors.append(
                    "selection_kind exact is unsupported by opened evidence: "
                    "the source object and selected card share no distinctive term"
                )
    return errors


_CANDIDATE_DRAFT_ERROR_PREFIXES = (
    "selection_kind exact contradicts analog applicability or limitations",
    "selection_kind analog contradicts exact applicability",
    "selection_kind exact contradicts missing operations",
    "selected candidate contradicts bind",
    "selection_kind exact requires exact operation",
    "selection_kind exact is unsupported by opened evidence",
    "technology_check.overlaps_with_work_ids cannot contain its own work_id",
    "candidate_evaluations[",
    "candidate_evaluations must mark the submitted norm exactly once as selected",
)


def _candidate_draft_enabled() -> bool:
    """Allow a repeated, typed model choice to remain a visible draft.

    Setting ``LES_SMETA_CANDIDATE_DRAFT_MODE=off`` restores the strict v14
    rejection loop without changing the model-owned mapping or catalog data.
    """
    return os.getenv("LES_SMETA_CANDIDATE_DRAFT_MODE", "on").strip().casefold() not in {
        "0", "false", "no", "off",
    }


def _last_structured_mapping_rows(
    model_trace: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Recover the latest model-authored mapping rows from the agent trace."""
    for item in reversed(model_trace or []):
        if str(item.get("transport") or "") != "structured_mapping":
            continue
        assistant = item.get("assistant") or {}
        raw = assistant.get("content")
        payload: Any
        if isinstance(raw, dict):
            payload = raw
        else:
            try:
                payload = json.loads(str(raw or "") or "{}")
            except json.JSONDecodeError:
                continue
        if not isinstance(payload, dict):
            continue
        rows = _tool_array_argument(payload, "rows", aliases=("mapping",))
        if rows:
            return [dict(row) for row in rows if isinstance(row, dict)]
    return []


def _promote_terminal_unbound_candidates(
    session: "SmetaNormToolSession",
    *,
    last_submit_result: dict[str, Any],
    model_trace: list[dict[str, Any]],
) -> bool:
    """Second submit for honest unbound rows when the finite loop ends early.

    Preserves the model decision as ``model_batch_candidate`` without inventing
    search evidence. Returns True when every remaining hard failure was promoted.
    """
    if not _candidate_draft_enabled():
        return False
    errors = [
        error
        for error in (last_submit_result.get("errors") or [])
        if isinstance(error, dict)
    ]
    if not errors:
        return False
    unbound_ids = []
    for error in errors:
        work_id = str(error.get("work_id") or "").strip()
        if (
            str(error.get("error") or "") != "invalid unbound_evidence"
            or not work_id
            or session.candidate_draft_attempts.get(f"unbound:{work_id}", 0) < 1
        ):
            return False
        unbound_ids.append(work_id)
    rows = [
        row
        for row in _last_structured_mapping_rows(model_trace)
        if str(row.get("work_id") or "") in unbound_ids
        and str(row.get("decision") or "") == "unbound"
    ]
    if len(rows) != len(unbound_ids):
        return False
    result = session.execute(
        "submit_lsr_mapping",
        {"rows": rows},
        turn=max(
            (
                int(item.get("turn") or 0)
                for item in model_trace
                if isinstance(item, dict)
            ),
            default=0,
        )
        + 1,
    )
    return bool(result.get("ok")) and not session.remaining_work_ids


def _promote_terminal_bind_candidates(
    session: "SmetaNormToolSession",
    *,
    last_submit_result: dict[str, Any],
    model_trace: list[dict[str, Any]],
) -> bool:
    """Accept draft-eligible incomplete binds after bounded repair is exhausted."""
    if not _candidate_draft_enabled():
        return False
    errors = [
        error
        for error in (last_submit_result.get("errors") or [])
        if isinstance(error, dict)
    ]
    if not errors:
        return False
    bind_ids: list[str] = []
    for error in errors:
        work_id = str(error.get("work_id") or "").strip()
        details = [
            str(item) for item in (error.get("details") or []) if str(item).strip()
        ]
        if (
            str(error.get("error") or "") != "incomplete bind evidence"
            or not work_id
            or session.candidate_draft_attempts.get(work_id, 0) < 1
            or not _candidate_draft_errors(details)
            or not session.opened.get(work_id)
        ):
            return False
        bind_ids.append(work_id)
    rows = [
        row
        for row in _last_structured_mapping_rows(model_trace)
        if str(row.get("work_id") or "") in bind_ids
        and str(row.get("decision") or "") == "bind"
    ]
    if len(rows) != len(bind_ids):
        return False
    # Force the second-chance draft path even if the model repeated the same
    # incomplete evidence payload after the bounded schema repair.
    for work_id in bind_ids:
        session.candidate_draft_attempts[work_id] = max(
            1, int(session.candidate_draft_attempts.get(work_id, 0))
        )
    result = session.execute(
        "submit_lsr_mapping",
        {"rows": rows},
        turn=max(
            (
                int(item.get("turn") or 0)
                for item in model_trace
                if isinstance(item, dict)
            ),
            default=0,
        )
        + 1,
    )
    return bool(result.get("ok")) and not session.remaining_work_ids


def _promote_terminal_mapping_candidates(
    session: "SmetaNormToolSession",
    *,
    last_submit_result: dict[str, Any],
    model_trace: list[dict[str, Any]],
) -> bool:
    """Promote either unfinished unbound or draft-eligible bind failures."""
    return _promote_terminal_unbound_candidates(
        session,
        last_submit_result=last_submit_result,
        model_trace=model_trace,
    ) or _promote_terminal_bind_candidates(
        session,
        last_submit_result=last_submit_result,
        model_trace=model_trace,
    )


def _candidate_draft_errors(errors: list[str]) -> bool:
    """True only for professional/audit contradictions, never hard evidence faults."""
    if not errors:
        return False
    for error in errors:
        text = str(error)
        if text.startswith("candidate_evaluations[") and not text.endswith(
            ".candidate_code was not opened through read_norms_batch"
        ):
            return False
        if not any(text.startswith(prefix) for prefix in _CANDIDATE_DRAFT_ERROR_PREFIXES):
            return False
    return True


def _normalize_search_queries_transport(item: dict[str, Any]) -> list[str]:
    """Accept the flat Ollama-safe query contract and legacy query arrays."""
    raw = item.get("queries")
    if isinstance(raw, list):
        values = raw
    elif raw is not None:
        values = [raw]
    else:
        scalar = item.get("query")
        values = [scalar] if scalar is not None else []
    return _stable_unique_text(values)


def _resolve_norm_code_transport(code: Any, available: dict[str, Any]) -> str:
    """Resolve harmless display aliases while preserving the norm family.

    Search may expose ``ГЭСН:01-...`` while a local model returns
    ``ГЭСН01-...``.  They are the same typed norm reference; matching them by
    the canonical family-aware key is transport repair, not norm selection.
    """
    requested = str(code or "").strip()
    if requested in available:
        return requested
    requested_key = gesn_service._norm_key(requested)
    if not requested_key:
        return ""
    matches = [
        candidate_code
        for candidate_code in available
        if gesn_service._norm_key(candidate_code) == requested_key
    ]
    return matches[0] if len(matches) == 1 else ""




def _tool_arguments(call: dict[str, Any]) -> dict[str, Any]:
    function = call.get("function") if isinstance(call, dict) else {}
    raw = (function or {}).get("arguments")
    if isinstance(raw, dict):
        return raw
    text = str(raw or "{}").strip()
    parsed = _parse_json_transport(text)
    if parsed is None:
        try:
            parsed = ast.literal_eval(text)
        except (SyntaxError, ValueError):
            return {}
    return parsed if isinstance(parsed, dict) else {}


def _tool_array_argument(
    args: dict[str, Any], key: str, *, aliases: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Unwrap a model's harmless double-serialization of a tool array."""
    raw = args.get(key)
    if raw is None:
        raw = next((args.get(alias) for alias in aliases if args.get(alias) is not None), None)
    for _ in range(3):
        if not isinstance(raw, str):
            break
        text = raw.strip()
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            if "Extra data" in str(exc):
                decision_obj = _extract_trailing_decision_object(text)
                if decision_obj:
                    return [decision_obj]
                parsed_transport = _parse_json_transport(text)
                if parsed_transport is not None:
                    raw = parsed_transport
                    continue
            try:
                raw = ast.literal_eval(text)
            except (SyntaxError, ValueError):
                raw = _parse_json_transport(text)
                if raw is None:
                    return []
    return [item for item in (raw or []) if isinstance(item, dict)] if isinstance(raw, list) else []


def _nested_array_transport(value: Any) -> Any:
    """Unwrap a valid JSON/Python array serialized inside a string field."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    parsed = _parse_json_transport(text)
    if parsed is None:
        try:
            parsed = ast.literal_eval(text)
        except (SyntaxError, ValueError):
            return value
    return parsed if isinstance(parsed, list) else value


def _one_item_tool_transport(
    args: dict[str, Any],
    *,
    array_fields: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Accept Qwen's flat spelling of a one-item batch tool call."""
    normalized = copy.deepcopy(args)
    items = _tool_array_argument(normalized, "items")
    if not items and str(normalized.get("work_id") or "").strip():
        item = {
            key: value
            for key, value in normalized.items()
            if key not in {"items", "default_decision"}
        }
        normalized["items"] = [item]
        items = normalized["items"]
    for item in items:
        for field in array_fields:
            if field in item:
                item[field] = _nested_array_transport(item[field])
    return normalized


def _extract_trailing_decision_object(text: str | None) -> dict[str, Any] | None:
    """Extract the last JSON object with decision fields from a concatenated string.

    Qwen 3.5 may produce: ``[{node1}, {node2}], "work_id": "...", "selected_node_id": "..."``
    — an array of catalog nodes followed by naked dict key-value pairs, concatenated
    into one string that fails ``json.loads`` with "Extra data".
    """
    _decision_markers = {"selected_node_id", "evidence", "work_id", "confidence", "work_features"}
    text_str = str(text or "").strip()

    # 1. Look for array close ']' followed by a decision field key
    match = re.search(
        r"\]\s*,\s*(?=\"(?:current_node_id|selected_node_id|evidence|work_id|confidence)\")",
        text_str,
    )
    if match:
        idx = match.end()
        candidate = "{" + text_str[idx:]
        while candidate.endswith("]") or candidate.endswith("]\n") or candidate.endswith("]\r\n"):
            candidate = candidate.rstrip("]\r\n")
        if not candidate.endswith("}"):
            candidate += "}"
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict) and (set(obj.keys()) & _decision_markers):
                return obj
        except json.JSONDecodeError:
            repaired = _close_unterminated_json_containers(candidate)
            try:
                obj = json.loads(repaired)
                if isinstance(obj, dict) and (set(obj.keys()) & _decision_markers):
                    return obj
            except json.JSONDecodeError:
                pass

    # 2. Fallback to raw_decode scan
    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []
    idx = 0
    while idx < len(text_str):
        while idx < len(text_str) and text_str[idx] in " \t\r\n,;":
            idx += 1
        if idx >= len(text_str):
            break
        try:
            obj, end_idx = decoder.raw_decode(text_str, idx)
            if isinstance(obj, dict) and (set(obj.keys()) & _decision_markers):
                candidates.append(obj)
            idx = end_idx
        except json.JSONDecodeError:
            idx += 1
    return candidates[-1] if candidates else None


def _close_unterminated_json_containers(text: str) -> str:
    """Close only missing trailing JSON delimiters in model tool transport.

    Ollama can serialize a large ``items`` array as a string and omit its final
    ``]`` while leaving every item intact.  We may close a balanced prefix, but
    never delete, reorder or synthesize array items.
    """
    stack: list[str] = []
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "[{":
            stack.append(char)
        elif char in "]}":
            expected = "[" if char == "]" else "{"
            if not stack or stack.pop() != expected:
                return text
    if in_string or not stack or len(stack) > 3:
        return text
    return text + "".join("]" if opener == "[" else "}" for opener in reversed(stack))


def _parse_json_transport(text: str) -> Any | None:
    """Parse JSON after one unambiguous delimiter-only transport repair.

    This accepts missing trailing containers and at most two superfluous
    trailing closing delimiters.  It never changes strings, keys, values or
    array members, so professional meaning remains model-owned.
    """
    source = str(text or "").strip()
    if not source:
        return None
    for candidate in dict.fromkeys((source, _close_unterminated_json_containers(source))):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    try:
        parsed, end = json.JSONDecoder().raw_decode(source)
    except json.JSONDecodeError:
        return None
    remainder = source[end:].strip()
    if remainder and len(remainder) <= 2 and all(char in "]}" for char in remainder):
        return parsed
    return None


def _tool_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}


def _tool_string_list(value: Any) -> list[str]:
    """Accept a schema array and harmless one-value local-model transport."""
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    return list(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))

_FLEXIBLE_RESOLVER_MODES = {"balanced", "legacy", "off"}
_NORM_REFERENCE_RE = re.compile(
    r"(?:(ГЭСН(?:мр|м|п|р)?)\s*[:№]?\s*)?(\d{2}-\d{2}(?:-\d{3}(?:-\d{2})?)?)",
    re.IGNORECASE,
)
_POSITIVE_APPLICABILITY_RE = re.compile(
    r"\b(?:подходит|применим\w*|покрывает|соответствует|выбран\w*|использовать|относится\s+к)\b",
    re.IGNORECASE,
)
_NEGATIVE_APPLICABILITY_RE = re.compile(
    r"(?:\bне\s+(?:подходит|применим\w*|покрывает|соответствует|содержит|относится)\b|"
    r"\b(?:нет|не\s+найден\w*|отсутств\w*|чуж\w*)\b)",
    re.IGNORECASE,
)


def _flexible_resolver_mode(explicit: str | None = None) -> str:
    raw = str(
        explicit
        if explicit is not None
        else os.getenv("LES_SMETA_FLEXIBLE_RESOLVER_MODE", "balanced")
    ).strip().casefold()
    return raw if raw in _FLEXIBLE_RESOLVER_MODES else "balanced"


def _legacy_resolve_extracted_norm_code(
    item: dict[str, Any],
    *,
    by_id: dict[str, Any] | None,
    opened_cards: Any,
) -> dict[str, Any]:
    """Preserve the v0.27.29 Gemini resolver as an explicit rollback mode."""
    if not isinstance(item, dict):
        return item

    current_code = str(item.get("norm_code") or "").strip()
    decision = str(item.get("decision") or "").strip()

    if decision == "bind" and current_code:
        return item

    work_id = str(item.get("work_id") or "")
    cov = str(item.get("covered_by_work_id") or "")
    reason = str(item.get("reason") or item.get("coverage_reason") or "")

    search_text = f"{cov} {reason}"

    full_matches = re.findall(r"(\d{2}-\d{2}-\d{3}-\d{2})", search_text)
    table_matches = re.findall(r"(\d{2}-\d{2}-\d{3}|\d{2}-\d{2})", search_text)

    extracted_table = None
    if full_matches:
        extracted_table = full_matches[0]
    elif table_matches:
        extracted_table = table_matches[0]

    if not extracted_table:
        return item

    leaf_code = None
    best_card = None
    try:
        from proxy.smeta_core import norm_browser

        res = norm_browser.browse_norms(f"ГЭСНм {extracted_table}", limit=3)
        cards = res.get("cards") or []
        if cards:
            best_card = cards[0]
            leaf_code = str(
                best_card.get("cipher")
                or best_card.get("norm_code")
                or best_card.get("code")
                or ""
            )
    except Exception:
        pass

    if not leaf_code:
        parts = extracted_table.split("-")
        prefix = "ГЭСНр" if "ГЭСНр" in search_text or "ГЭСНр" in reason else "ГЭСНм"
        if len(parts) == 4:
            leaf_code = f"{prefix}{extracted_table}"
        elif len(parts) == 3:
            leaf_code = f"{prefix}{extracted_table}-01"
        elif len(parts) == 2:
            leaf_code = f"{prefix}{extracted_table}-001-01"
        else:
            leaf_code = f"{prefix}{extracted_table}"

    clean_reason = reason or f"Авто-привязка по результатам поиска таблицы {extracted_table} в обосновании модели"

    item["decision"] = "bind"
    item["norm_code"] = leaf_code
    item["selection_kind"] = "exact"
    item["applicability"] = "exact"
    item["analog_limitations"] = []
    item["reason"] = clean_reason

    item["technology_check"] = {
        "matched_operations": [clean_reason],
        "missing_operations": [],
        "extra_operations": [],
        "foreign_resources": [],
        "overlaps_with_work_ids": [],
        "conditions_checked": ["Нормативные условия ГЭСН соответствуют ВОР"],
        "unresolved_conditions": [],
        "overlap_resolution": "Покрывается выделенной нормой ГЭСН",
        "conclusion": "applicable",
    }
    item["candidate_evaluations"] = [
        {
            "candidate_code": leaf_code,
            "operation_match": "exact",
            "object_match": "exact",
            "unit_match": "compatible",
            "scope_match": "exact",
            "foreign_resources": [],
            "decision": "selected",
            "reason": clean_reason,
        }
    ]

    if opened_cards is not None and work_id:
        if work_id not in opened_cards:
            opened_cards[work_id] = {}
        if best_card:
            opened_cards[work_id][leaf_code] = best_card
            opened_cards[work_id][extracted_table] = best_card
        else:
            unit_val = str(by_id.get(work_id, {}).get("unit") or "шт.") if by_id else "шт."
            synthetic_card = {
                "norm_code": leaf_code,
                "cipher": leaf_code,
                "title": f"Монтажные работы (таблица {extracted_table})",
                "measure_unit": unit_val,
            }
            opened_cards[work_id][leaf_code] = synthetic_card
            opened_cards[work_id][extracted_table] = synthetic_card

    return item


def _model_norm_references(text: str) -> list[dict[str, str]]:
    references: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for match in _NORM_REFERENCE_RE.finditer(str(text or "")):
        family = str(match.group(1) or "").strip()
        bare_code = str(match.group(2) or "").strip()
        key = (family.casefold(), bare_code)
        if not bare_code or key in seen:
            continue
        seen.add(key)
        references.append({"family": family, "bare_code": bare_code})
    return references


def _unique_opened_cards(opened_cards: Any, work_id: str) -> dict[str, dict[str, Any]]:
    if not isinstance(opened_cards, dict):
        return {}
    raw = opened_cards.get(work_id) or {}
    if isinstance(raw, list):
        values = {
            str(card.get("norm_code") or card.get("cipher") or "").strip(): card
            for card in raw
            if isinstance(card, dict)
        }
    elif isinstance(raw, dict):
        values = raw
    else:
        return {}
    unique: dict[str, dict[str, Any]] = {}
    for alias, card in values.items():
        if not isinstance(card, dict):
            continue
        code = str(card.get("norm_code") or card.get("cipher") or alias).strip()
        key = gesn_service._norm_key(code)
        if code and key and key not in unique:
            unique[key] = card
    return unique


def _opened_matches_for_references(
    references: list[dict[str, str]],
    opened: dict[str, dict[str, Any]],
) -> list[str]:
    matches: list[str] = []
    for norm_key, card in opened.items():
        card_code = str(card.get("norm_code") or card.get("cipher") or "").strip()
        card_family, _, card_bare = norm_key.partition(":")
        for reference in references:
            family = str(reference.get("family") or "").casefold()
            bare = str(reference.get("bare_code") or "")
            family_matches = not family or card_family.casefold() == family
            bare_matches = card_bare == bare or card_bare.startswith(bare + "-")
            if family_matches and bare_matches and card_code:
                matches.append(card_code)
                break
    return list(dict.fromkeys(matches))


def _reason_suggests_positive_applicability(reason: str) -> bool:
    text = str(reason or "").strip()
    return bool(
        text
        and _POSITIVE_APPLICABILITY_RE.search(text)
        and not _NEGATIVE_APPLICABILITY_RE.search(text)
    )


def resolve_extracted_norm_code_flexible(
    item: dict[str, Any],
    by_id: dict[str, Any] | None = None,
    opened_cards: Any = None,
    *,
    mode: str | None = None,
) -> dict[str, Any]:
    """Interpret imperfect model mapping without inventing a decision.

    ``balanced`` repairs a missing/aliased ``norm_code`` only when the model
    submitted ``decision=bind`` and its prose resolves to exactly one card that
    the same model already opened.  Negative decisions remain negative, while
    matching opened cards are returned as an audit hint for bounded model
    clarification.  ``legacy`` preserves the aggressive Gemini resolver for an
    operator-controlled rollback; ``off`` is a byte-light bypass.
    """
    if not isinstance(item, dict):
        return item
    selected_mode = _flexible_resolver_mode(mode)
    if selected_mode == "off":
        return item
    if selected_mode == "legacy":
        return _legacy_resolve_extracted_norm_code(
            item,
            by_id=by_id,
            opened_cards=opened_cards,
        )

    work_id = str(item.get("work_id") or "")
    decision = str(item.get("decision") or "").strip().casefold()
    reason = str(item.get("reason") or item.get("coverage_reason") or "")
    current_code = str(item.get("norm_code") or "").strip()
    references = _model_norm_references(" ".join((current_code, reason)))
    opened = _unique_opened_cards(opened_cards, work_id)
    matches = _opened_matches_for_references(references, opened)

    interpretation = {
        "mode": "balanced",
        "decision_preserved": decision,
        "references": references,
        "matched_opened_codes": matches,
        "reason_suggests_positive_applicability": _reason_suggests_positive_applicability(reason),
        "repair": "none",
    }

    if decision == "bind":
        resolved_current = _resolve_norm_code_transport(
            current_code,
            {
                str(card.get("norm_code") or card.get("cipher") or key): card
                for key, card in opened.items()
            },
        )
        if resolved_current:
            if resolved_current != current_code:
                item["norm_code"] = resolved_current
                interpretation["repair"] = "normalized_opened_norm_alias"
        elif len(matches) == 1:
            item["norm_code"] = matches[0]
            interpretation["repair"] = "resolved_unique_opened_model_reference"

    item["_les_flexible_interpretation"] = interpretation
    return item


def _focus_serialization_guard(
    session: "SmetaNormToolSession",
    args: dict[str, Any],
    *,
    mapping_chunk: int,
) -> dict[str, Any] | None:
    """Keep a completed one-row focus durable before later evidence work."""
    focus_work_id = (
        session.remaining_work_ids[0]
        if session.remaining_work_ids
        else ""
    )
    requested_work_ids = {
        str(item.get("work_id") or "")
        for item in _tool_array_argument(args, "items")
        if str(item.get("work_id") or "")
    }
    deferred = requested_work_ids - {focus_work_id}
    if (
        mapping_chunk != 1
        or not focus_work_id
        or not session.opened.get(focus_work_id)
        or not deferred
    ):
        return None
    return {
        "ok": False,
        "error": (
            "finish and serialize the current focus work before "
            "using evidence tools for later rows"
        ),
        "focus_work_id": focus_work_id,
        "deferred_work_ids": sorted(deferred),
        "next_action": (
            "end the tool loop now; LES will request your own "
            "structured mapping for the focus work_id"
        ),
    }


def bounded_catalog_query_from_work_features(work_features: dict[str, Any]) -> str:
    """Derive a 2-12 word bounded estimating query from typed work features."""
    parts: list[str] = []
    for key in ("operation", "equipment", "system", "installation_context"):
        val = str((work_features or {}).get(key) or "").strip()
        if val:
            parts.append(val)
    raw_query = " ".join(parts).strip()
    tokens = re.findall(r"[0-9A-Za-zА-Яа-яЁё]+", raw_query)
    if not tokens:
        return ""
    return " ".join(tokens[:12])


def _draft_work_features_from_source(row: dict[str, Any]) -> dict[str, Any]:
    """Fill a navigation-only work_features card from the VOR row title/note.

    Does not choose a norm family or table — only unblocks catalog transport when
    local Qwen omits the typed feature object.
    """
    title = " ".join(str(row.get("title") or "").split())
    note = " ".join(str(row.get("note") or "").split())
    anchor = title or note or "работа"
    tokens = re.findall(r"[0-9A-Za-zА-Яа-яЁё]+", anchor)
    short = " ".join(tokens[:8]) if tokens else "работа"
    return {
        "domain": "unknown",
        "system": "unknown",
        "equipment": short,
        "operation": short,
        "assembly_state": "unknown",
        "installation_context": "unknown",
        "unknowns": [
            "work_features drafted from source title for catalog navigation only",
        ],
    }


def _merge_work_features_with_source_draft(
    work_features: dict[str, Any] | None,
    source_row: dict[str, Any] | None,
) -> dict[str, Any]:
    """Keep model-authored fields; fill gaps from the source-row draft."""
    merged = dict(work_features or {}) if isinstance(work_features, dict) else {}
    draft = _draft_work_features_from_source(source_row or {})
    filled_from_draft = False
    for key, value in draft.items():
        if key == "unknowns":
            continue
        if not str(merged.get(key) or "").strip():
            merged[key] = value
            filled_from_draft = True
    unknowns = [
        str(item).strip()
        for item in (merged.get("unknowns") or [])
        if str(item).strip()
    ]
    if filled_from_draft:
        for note in draft.get("unknowns") or []:
            text = str(note).strip()
            if text and text not in unknowns:
                unknowns.append(text)
    merged["unknowns"] = unknowns[:8]
    return merged


def _resolve_bounded_catalog_query(
    model_query: str,
    work_features: dict[str, Any],
) -> tuple[str, str]:
    """Resolve query: use model_query if valid 2-12 tokens, else derive from features."""
    clean_model = " ".join(str(model_query or "").split())
    tokens = re.findall(r"[0-9A-Za-zА-Яа-яЁё]+", clean_model)
    if 2 <= len(tokens) <= 12:
        return clean_model, "model"
    derived = bounded_catalog_query_from_work_features(work_features)
    derived_tokens = re.findall(r"[0-9A-Za-zА-Яа-яЁё]+", derived)
    if 2 <= len(derived_tokens) <= 12:
        return derived, "derived_from_work_features"
    return clean_model, "model"


def _search_queries_for_work_row(row: dict[str, Any]) -> list[str]:
    """Two bounded lexical queries from the VOR row (transport only, not a bind)."""
    title = " ".join(str(row.get("title") or "").split())
    note = " ".join(str(row.get("note") or "").split())
    anchor = title or note or "работа"
    tokens = re.findall(r"[0-9A-Za-zА-Яа-яЁё]+", anchor)
    primary = " ".join(tokens[:8]) if tokens else "работа"
    if "монтаж" in primary.casefold():
        secondary_tokens = tokens[:6] + ["устройство"]
    else:
        secondary_tokens = tokens[:6] + ["монтаж"]
    secondary = " ".join(secondary_tokens[:8])
    if secondary.casefold() == primary.casefold():
        secondary = f"{primary} ФСНБ"
    return [primary, secondary]


def _auto_norm_search_items(session: "SmetaNormToolSession") -> list[dict[str, Any]]:
    """Build search_norms_batch items for rows that already have a selected table."""
    items: list[dict[str, Any]] = []
    for work_id in _phase_work_ids(session, "norm_search"):
        tables = session.selected_tables.get(work_id) or set()
        if not tables:
            continue
        family_key, collection, table_code = sorted(tables)[0]
        family = family_key
        for key, meta in (session.selected_base_types.get(work_id) or {}).items():
            if str(key).casefold() == str(family_key).casefold():
                family = str((meta or {}).get("family") or family_key)
                break
        row = session.by_id.get(work_id) or {}
        items.append({
            "work_id": work_id,
            "queries": _search_queries_for_work_row(row),
            "base_types": [family],
            "collections": [str(collection)],
            "table_codes": [str(table_code)],
            "scope_mode": "scoped",
        })
    return items


def _resolve_selected_node_id(
    raw_selected: str,
    evidence_items: list[dict[str, Any]],
    visible_ids: set[str],
) -> tuple[str, str]:
    """Resolve selected_node_id: use model selection if in visible_ids, or derive from evidence."""
    clean_selected = str(raw_selected or "").strip()
    if clean_selected in visible_ids:
        return clean_selected, "model"
    for ev in evidence_items or []:
        source_id = str((ev or {}).get("source_node_id") or "").strip()
        if source_id in visible_ids:
            return source_id, "derived_from_evidence"
    return clean_selected, "model" if clean_selected else ""


class SmetaNormToolSession:
    """State shared by every smeta agent implementation.

    The session exposes evidence tools and validates only transport/reference
    integrity.  It never chooses, replaces or improves a model decision.
    """

    def __init__(
        self,
        work_rows: list[dict[str, Any]],
        *,
        candidate_limit: int,
        progress: Progress | None = None,
        evidence_budget: EvidenceBudget | None = None,
        require_scoped_search: bool = False,
        decision_checkpoint: DecisionCheckpoint | None = None,
    ) -> None:
        self.by_id = {str(row["work_id"]): row for row in work_rows}
        self.candidate_limit = max(1, int(candidate_limit))
        self.progress = progress
        self.evidence_budget = evidence_budget or EvidenceBudget.from_environment()
        self.require_scoped_search = bool(require_scoped_search)
        self.decision_checkpoint = decision_checkpoint
        self.started_at = perf_counter()
        self.evidence_usage = {
            "search_calls": 0,
            "read_calls": 0,
            "opened_cards": 0,
            "tool_elapsed_seconds": 0.0,
        }
        # Lifetime usage is immutable audit evidence and survives checkpoints.
        # A resumed process receives a fresh bounded execution slice, otherwise
        # an exhausted historical counter would make durable resume impossible.
        self._evidence_slice_baseline = dict(self.evidence_usage)
        self.catalog_trace: list[dict[str, Any]] = []
        self.catalog_seen: set[tuple[str, str, str, str, str]] = set()
        self.family_catalog_seen: set[str] = set()
        self.catalog_reject_streak: dict[str, int] = {}
        self.catalog_stall: dict[str, Any] | None = None
        self.selected_base_types: dict[str, dict[str, dict[str, Any]]] = {
            work_id: {} for work_id in self.by_id
        }
        self.selected_collections: dict[str, set[tuple[str, str]]] = {
            work_id: set() for work_id in self.by_id
        }
        self.selected_sections: dict[str, set[tuple[str, str, str]]] = {
            work_id: set() for work_id in self.by_id
        }
        self.selected_tables: dict[str, set[tuple[str, str, str]]] = {
            work_id: set() for work_id in self.by_id
        }
        self.catalog_current_nodes: dict[str, str] = {
            work_id: "catalog:root" for work_id in self.by_id
        }
        self.catalog_node_registry: dict[str, dict[str, dict[str, Any]]] = {
            work_id: {} for work_id in self.by_id
        }
        self.catalog_menus: dict[str, dict[str, list[dict[str, Any]]]] = {
            work_id: {} for work_id in self.by_id
        }
        self.catalog_terminal_decisions: dict[str, dict[str, Any]] = {}
        self.candidates: dict[str, dict[str, dict[str, Any]]] = {
            work_id: {} for work_id in self.by_id
        }
        self.opened: dict[str, dict[str, dict[str, Any]]] = {
            work_id: {} for work_id in self.by_id
        }
        for work_id, row in self.by_id.items():
            for card in row.get("opened_norm_cards") or []:
                if not isinstance(card, dict):
                    continue
                code = str(card.get("norm_code") or "").strip()
                if not code:
                    continue
                seeded = dict(card)
                self.candidates[work_id][code] = seeded
                self.opened[work_id][code] = seeded
        self.browse_trace: dict[str, list[dict[str, Any]]] = {
            work_id: [] for work_id in self.by_id
        }
        self.query_trace: list[dict[str, Any]] = []
        self.accepted_rows: dict[str, dict[str, Any]] = {}
        self.invalid_submission_attempts: dict[str, int] = {}
        self.candidate_draft_attempts: dict[str, int] = {}
        self.tool_trajectory: list[dict[str, Any]] = []
        self.route_evidence_cache: dict[str, dict[str, Any]] = {}
        for row in work_rows:
            for route in row.get("route_evidence_cache") or []:
                if not isinstance(route, dict):
                    continue
                cache_id = str(route.get("cache_id") or "").strip()
                if cache_id:
                    self.route_evidence_cache[cache_id] = copy.deepcopy(route)

    def work_fingerprint(self) -> str:
        source_rows = {
            work_id: {
                key: value
                for key, value in row.items()
                if key not in {
                    "task_state",
                    "route_evidence_cache",
                    "memory_advisory",
                }
            }
            for work_id, row in self.by_id.items()
        }
        return hashlib.sha256(
            json.dumps(
                source_rows,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()

    def checkpoint_state(self) -> dict[str, Any]:
        """Return JSON-safe state needed to resume after the last tool result."""
        return {
            "schema": "smeta_norm_tool_session_checkpoint_v1",
            "work_fingerprint": self.work_fingerprint(),
            "candidate_limit": self.candidate_limit,
            "require_scoped_search": self.require_scoped_search,
            "evidence_usage": dict(self.evidence_usage),
            "catalog_trace": copy.deepcopy(self.catalog_trace),
            "catalog_seen": [list(value) for value in sorted(self.catalog_seen)],
            "family_catalog_seen": sorted(self.family_catalog_seen),
            "selected_base_types": copy.deepcopy(self.selected_base_types),
            "selected_collections": {
                work_id: [list(value) for value in sorted(values)]
                for work_id, values in self.selected_collections.items()
            },
            "selected_sections": {
                work_id: [list(value) for value in sorted(values)]
                for work_id, values in self.selected_sections.items()
            },
            "selected_tables": {
                work_id: [list(value) for value in sorted(values)]
                for work_id, values in self.selected_tables.items()
            },
            "catalog_current_nodes": dict(self.catalog_current_nodes),
            "catalog_node_registry": copy.deepcopy(self.catalog_node_registry),
            "catalog_menus": copy.deepcopy(self.catalog_menus),
            "catalog_terminal_decisions": copy.deepcopy(
                self.catalog_terminal_decisions
            ),
            "candidates": copy.deepcopy(self.candidates),
            "opened": copy.deepcopy(self.opened),
            "browse_trace": copy.deepcopy(self.browse_trace),
            "query_trace": copy.deepcopy(self.query_trace),
            "accepted_rows": copy.deepcopy(self.accepted_rows),
            "invalid_submission_attempts": dict(self.invalid_submission_attempts),
            "candidate_draft_attempts": dict(self.candidate_draft_attempts),
            "tool_trajectory": copy.deepcopy(self.tool_trajectory),
            "route_evidence_cache": copy.deepcopy(self.route_evidence_cache),
        }

    def restore_checkpoint_state(self, state: dict[str, Any]) -> None:
        """Restore trusted server-produced state for the same immutable VOR."""
        if str(state.get("schema") or "") != "smeta_norm_tool_session_checkpoint_v1":
            raise RuntimeError("unsupported smeta norm checkpoint schema")
        if str(state.get("work_fingerprint") or "") != self.work_fingerprint():
            raise RuntimeError("smeta norm checkpoint belongs to another work revision")
        known = set(self.by_id)

        def work_mapping(name: str) -> dict[str, Any]:
            raw = state.get(name) if isinstance(state.get(name), dict) else {}
            unknown = set(str(key) for key in raw) - known
            if unknown:
                raise RuntimeError(
                    f"smeta norm checkpoint {name} has unknown work_ids: {sorted(unknown)}"
                )
            return {str(key): value for key, value in raw.items()}

        self.evidence_usage = {
            **self.evidence_usage,
            **dict(state.get("evidence_usage") or {}),
        }
        self._evidence_slice_baseline = dict(self.evidence_usage)
        self.catalog_trace = copy.deepcopy(list(state.get("catalog_trace") or []))
        self.catalog_seen = {
            (
                tuple(str(item) for item in value)
                if len(value) == 5
                else (
                    str(value[0]),
                    str(value[1]),
                    str(value[2]),
                    "",
                    str(value[3]),
                )
            )
            for value in (state.get("catalog_seen") or [])
            if isinstance(value, list) and len(value) in {4, 5}
        }
        self.family_catalog_seen = {
            str(value)
            for value in (state.get("family_catalog_seen") or [])
            if str(value) in known
        }
        restored_base_types = work_mapping("selected_base_types")
        self.selected_base_types = {
            work_id: copy.deepcopy(restored_base_types.get(work_id) or {})
            for work_id in self.by_id
        }
        restored_collections = work_mapping("selected_collections")
        self.selected_collections = {
            work_id: {
                tuple(str(item) for item in value)
                for value in (restored_collections.get(work_id) or [])
                if isinstance(value, list) and len(value) == 2
            }
            for work_id in self.by_id
        }
        restored_sections = work_mapping("selected_sections")
        self.selected_sections = {
            work_id: {
                tuple(str(item) for item in value)
                for value in (restored_sections.get(work_id) or [])
                if isinstance(value, list) and len(value) == 3
            }
            for work_id in self.by_id
        }
        restored_tables = work_mapping("selected_tables")
        self.selected_tables = {
            work_id: {
                tuple(str(item) for item in value)
                for value in (restored_tables.get(work_id) or [])
                if isinstance(value, list) and len(value) == 3
            }
            for work_id in self.by_id
        }
        restored_current_nodes = work_mapping("catalog_current_nodes")
        self.catalog_current_nodes = {
            work_id: str(
                restored_current_nodes.get(work_id) or "catalog:root"
            )
            for work_id in self.by_id
        }
        restored_node_registry = work_mapping("catalog_node_registry")
        self.catalog_node_registry = {
            work_id: copy.deepcopy(
                restored_node_registry.get(work_id) or {}
            )
            for work_id in self.by_id
        }
        restored_menus = work_mapping("catalog_menus")
        self.catalog_menus = {
            work_id: copy.deepcopy(restored_menus.get(work_id) or {})
            for work_id in self.by_id
        }
        self.catalog_terminal_decisions = {
            work_id: copy.deepcopy(value)
            for work_id, value in work_mapping(
                "catalog_terminal_decisions"
            ).items()
        }
        for name in ("candidates", "opened", "browse_trace"):
            restored = work_mapping(name)
            setattr(
                self,
                name,
                {
                    work_id: copy.deepcopy(
                        restored.get(work_id)
                        or ({} if name != "browse_trace" else [])
                    )
                    for work_id in self.by_id
                },
            )
        self.query_trace = copy.deepcopy(list(state.get("query_trace") or []))
        self.accepted_rows = {
            work_id: copy.deepcopy(value)
            for work_id, value in work_mapping("accepted_rows").items()
        }
        self.invalid_submission_attempts = {
            str(key): int(value)
            for key, value in dict(
                state.get("invalid_submission_attempts") or {}
            ).items()
        }
        self.candidate_draft_attempts = {
            str(key): int(value)
            for key, value in dict(
                state.get("candidate_draft_attempts") or {}
            ).items()
            if str(key) in known
        }
        self.tool_trajectory = copy.deepcopy(
            list(state.get("tool_trajectory") or [])
        )
        self.route_evidence_cache = {
            str(key): copy.deepcopy(value)
            for key, value in dict(
                state.get("route_evidence_cache") or {}
            ).items()
            if str(key)
            and isinstance(value, dict)
        }

    @property
    def remaining_work_ids(self) -> list[str]:
        return [work_id for work_id in self.by_id if work_id not in self.accepted_rows]

    @property
    def complete(self) -> bool:
        return bool(self.by_id) and not self.remaining_work_ids

    def evidence_slice_usage(self) -> dict[str, float | int]:
        return {
            key: max(
                0.0 if key == "tool_elapsed_seconds" else 0,
                float(self.evidence_usage.get(key) or 0)
                - float(self._evidence_slice_baseline.get(key) or 0),
            )
            for key in self.evidence_usage
        }

    def evidence_remaining(self) -> dict[str, float | int]:
        usage = self.evidence_slice_usage()
        return {
            "search_calls": max(
                0,
                int(self.evidence_budget.search_calls)
                - int(usage.get("search_calls") or 0),
            ),
            "read_calls": max(
                0,
                int(self.evidence_budget.read_calls)
                - int(usage.get("read_calls") or 0),
            ),
            "opened_cards": max(
                0,
                int(self.evidence_budget.opened_cards)
                - int(usage.get("opened_cards") or 0),
            ),
            "tool_elapsed_seconds": round(
                max(
                    0.0,
                    float(self.evidence_budget.elapsed_seconds)
                    - float(usage.get("tool_elapsed_seconds") or 0.0),
                ),
                4,
            ),
        }

    def execute(self, name: str, args: dict[str, Any], *, turn: int) -> dict[str, Any]:
        started = perf_counter()
        budget_error = self._budget_error(name, args)
        if budget_error:
            result = {
                "ok": False,
                "error": budget_error,
                "force_mapping_serialization": True,
                "evidence_usage": dict(self.evidence_usage),
                "evidence_slice_usage": self.evidence_slice_usage(),
            }
        elif name == "browse_norm_catalog":
            has_typed_transition = any(
                isinstance(item, dict) and str(item.get("decision") or "")
                for item in _tool_array_argument(args, "items")
            )
            result = (
                self._catalog_transition(args, turn=turn)
                if self.require_scoped_search and has_typed_transition
                else self._catalog(args, turn=turn)
            )
            if self.require_scoped_search:
                self._remember_catalog_result(result)
        elif name in {
            "continue_norm_catalog",
            "ask_norm_catalog_fact",
            "broaden_norm_catalog",
            "unbound_norm_catalog",
        }:
            decision = {
                "continue_norm_catalog": "continue",
                "ask_norm_catalog_fact": "ask",
                "broaden_norm_catalog": "broaden",
                "unbound_norm_catalog": "unbound",
            }[name]
            routed_args = copy.deepcopy(args)
            routed_args["default_decision"] = decision
            for item in _tool_array_argument(routed_args, "items"):
                item["decision"] = decision
            result = self._catalog_transition(routed_args, turn=turn)
            self._remember_catalog_result(result)
        elif name == "reuse_norm_catalog_route":
            # Qwen often emits flat {work_id, cache_id} without items[].
            if not _tool_array_argument(args, "items") and (
                args.get("work_id") or args.get("cache_id")
            ):
                synthetic = {
                    key: args[key]
                    for key in ("work_id", "cache_id", "reason", "confidence")
                    if key in args
                }
                if not str(synthetic.get("reason") or "").strip():
                    synthetic["reason"] = (
                        "reuse cached catalog route before scoped search"
                    )
                args = {"items": [synthetic]}
            result = self._reuse_catalog_route(args, turn=turn)
            # Table already selected in this session: reuse is a no-op. Tell the
            # model to search instead of spinning identical cache calls.
            if (
                not result.get("ok")
                and self.require_scoped_search
                and any(self.selected_tables.get(wid) for wid in self.remaining_work_ids)
            ):
                result = {
                    "ok": False,
                    "error": (
                        "route already selected for this work; call "
                        "search_norms_batch with the selected table_codes"
                    ),
                    "force_auto_norm_search": True,
                    "rows": result.get("rows") or [],
                }
        elif name == "search_norms_batch":
            result = self._search(
                _one_item_tool_transport(
                    args,
                    array_fields=(
                        "queries", "base_types", "collections", "table_codes",
                    ),
                ),
                turn=turn,
            )
        elif name == "read_norms_batch":
            result = self._read(
                _one_item_tool_transport(
                    args,
                    array_fields=("norm_codes",),
                )
            )
        elif name == "submit_lsr_mapping":
            result = self._submit(args)
        else:
            result = {"ok": False, "error": f"unknown tool: {name}"}
        elapsed_seconds = max(0.0, perf_counter() - started)
        if name != "submit_lsr_mapping":
            self.evidence_usage["tool_elapsed_seconds"] = round(
                float(self.evidence_usage["tool_elapsed_seconds"]) + elapsed_seconds,
                4,
            )
        self.tool_trajectory.append({
            "turn": turn,
            "tool": name,
            "arguments": args,
            "result": result,
            "elapsed_ms": round(elapsed_seconds * 1000, 2),
        })
        return result

    def _reuse_catalog_route(
        self,
        args: dict[str, Any],
        *,
        turn: int,
    ) -> dict[str, Any]:
        """Apply only a route explicitly selected by the model from typed cache."""
        rows_out: list[dict[str, Any]] = []
        for item in _tool_array_argument(args, "items"):
            work_id = str(item.get("work_id") or "").strip()
            cache_id = str(item.get("cache_id") or "").strip()
            reason = " ".join(str(item.get("reason") or "").split())
            route = self.route_evidence_cache.get(cache_id)
            if work_id not in self.by_id:
                rows_out.append({
                    "work_id": work_id,
                    "ok": False,
                    "error": "unknown work_id",
                })
                continue
            if not route:
                rows_out.append({
                    "work_id": work_id,
                    "ok": False,
                    "error": "route cache id was not shown to the model",
                })
                continue
            if not reason:
                rows_out.append({
                    "work_id": work_id,
                    "ok": False,
                    "error": "model-owned applicability reason is required",
                })
                continue
            family = str(route.get("family") or "").strip()
            collection = str(route.get("collection") or "").strip()
            section = str(route.get("section") or "").strip()
            table_code = str(route.get("table_code") or "").strip()
            if not all((family, collection, section, table_code)):
                rows_out.append({
                    "work_id": work_id,
                    "ok": False,
                    "error": "cached route is structurally incomplete",
                })
                continue
            self.family_catalog_seen.add(work_id)
            self.selected_base_types[work_id] = {
                family.casefold(): {
                    "family": family,
                    "reason": reason,
                    "confidence": str(item.get("confidence") or "medium"),
                    "reused_from_cache_id": cache_id,
                }
            }
            self.selected_collections[work_id] = {
                (family.casefold(), collection)
            }
            self.selected_sections[work_id] = {
                (family.casefold(), collection, section)
            }
            self.selected_tables[work_id] = {
                (family.casefold(), collection, table_code)
            }
            self.catalog_current_nodes[work_id] = (
                f"catalog:table:{family}:{table_code}"
            )
            trace = {
                "trace_id": uuid4().hex,
                "phase": "catalog_route_cache",
                "turn": turn,
                "work_id": work_id,
                "outcome": "accepted",
                "selection_owner": "model",
                "cache_id": cache_id,
                "source_work_id": str(route.get("source_work_id") or ""),
                "family": family,
                "collection": collection,
                "section": section,
                "table_code": table_code,
                "reason": reason,
            }
            self.catalog_trace.append(trace)
            rows_out.append({
                "work_id": work_id,
                "ok": True,
                "level": "norm_search",
                "cache_id": cache_id,
                "selected_route": {
                    "family": family,
                    "collection": collection,
                    "section": section,
                    "table_code": table_code,
                },
                "next_action": (
                    "call search_norms_batch for this work_id; cached navigation "
                    "does not decide norm applicability"
                ),
            })
        return {
            "ok": any(row.get("ok") is True for row in rows_out),
            "rows": rows_out,
        }

    def _budget_error(self, name: str, args: dict[str, Any]) -> str:
        # Evidence limits must force convergence, never reject the model's
        # terminal decision after it has spent the available search/read time.
        if name == "submit_lsr_mapping":
            return ""
        slice_usage = self.evidence_slice_usage()
        elapsed = float(slice_usage["tool_elapsed_seconds"])
        if elapsed > self.evidence_budget.elapsed_seconds:
            return (
                f"evidence tool time budget exhausted after {elapsed:.1f}s; "
                "submit the model-owned decision"
            )
        if name == "search_norms_batch":
            if int(slice_usage["search_calls"]) >= self.evidence_budget.search_calls:
                return "search budget exhausted; use collected evidence and submit the model-owned decision"
            self.evidence_usage["search_calls"] += 1
        elif name == "read_norms_batch":
            requested_pairs = {
                (str(item.get("work_id") or ""), str(code))
                for item in _tool_array_argument(args, "items")
                for code in _normalize_norm_codes_transport(item)
            }
            requested = sum(
                1
                for work_id, requested_code in requested_pairs
                if _resolve_norm_code_transport(
                    requested_code,
                    self.opened.get(work_id, {}),
                )
                not in self.opened.get(work_id, {})
            )
            if requested == 0 and requested_pairs:
                return (
                    "all requested typed cards are already open; "
                    "use collected evidence and submit the model-owned decision"
                )
            if self.require_scoped_search and requested > _RIM_MAX_READ_CARDS_PER_CALL:
                return (
                    "RIM read batch is limited to two full typed cards per model turn; "
                    "choose the strongest candidate and one comparison card, then continue "
                    "with another bounded read batch if evidence still requires it"
                )
            if int(slice_usage["read_calls"]) >= self.evidence_budget.read_calls:
                return "read budget exhausted; use opened cards and submit the model-owned decision"
            if (
                int(slice_usage["opened_cards"]) + requested
                > self.evidence_budget.opened_cards
            ):
                return "opened-card budget exhausted; use opened cards and submit the model-owned decision"
            self.evidence_usage["read_calls"] += 1
            self.evidence_usage["opened_cards"] += requested
        return ""

    @staticmethod
    def _catalog_node_fields(item: dict[str, Any]) -> dict[str, Any]:
        """Keep the bounded official fields that may be cited by a route decision."""
        fields = {
            key: copy.deepcopy(value)
            for key, value in item.items()
            if key
            in {
                "node_id",
                "parent_id",
                "node_type",
                "cipher",
                "key",
                "title",
                "official_name",
                "official_heading",
                "description",
                "purpose",
                "typical_scope",
                "not_for",
                "questions_to_ask",
                "hierarchy",
                "norm_name_examples",
                "source_ref",
                "edition",
                "norm_count",
                "resource_count",
                "navigation_score",
                "catalog_compass_score",
            }
            and value not in (None, "", [])
        }
        return fields

    def _remember_catalog_result(self, result: dict[str, Any]) -> None:
        """Persist the exact menu shown to Qwen; later transitions may cite only it."""
        for row in result.get("rows") or []:
            if not isinstance(row, dict) or row.get("ok") is not True:
                continue
            work_id = str(row.get("work_id") or "")
            if work_id not in self.by_id:
                continue
            current_node_id = str(
                row.get("current_node_id")
                or self.catalog_current_nodes.get(work_id)
                or "catalog:root"
            )
            items = [
                self._catalog_node_fields(item)
                for item in (row.get("items") or [])
                if isinstance(item, dict) and str(item.get("node_id") or "")
            ]
            if not items:
                continue
            self.catalog_current_nodes[work_id] = current_node_id
            self.catalog_menus[work_id][current_node_id] = items
            registry = self.catalog_node_registry[work_id]
            for node in items:
                registry[str(node["node_id"])] = copy.deepcopy(node)

    def _catalog_transition(
        self,
        args: dict[str, Any],
        *,
        turn: int,
    ) -> dict[str, Any]:
        """Execute one model-owned transition over the finite typed catalog graph."""
        # --- Flat-to-items normalization (Qwen 3.5 compatibility) -----------
        _flat_decision_keys = {
            "selected_node_id", "evidence", "rejected_nodes", "confidence",
            "work_features", "missing_facts", "question", "catalog_query",
        }
        raw_items = _tool_array_argument(args, "items")
        has_flat_decision = bool(set(args.keys()) & _flat_decision_keys)
        items_are_catalog_nodes = (
            raw_items
            and all("node_id" in item and "work_id" not in item for item in raw_items[:3])
        )
        # Local Qwen often echoes the whole family passport menu into items[].
        # That is not a decision — reject once with an actionable example.
        if items_are_catalog_nodes and not has_flat_decision:
            work_id = ""
            if len(self.by_id) == 1:
                work_id = next(iter(self.by_id))
            elif self.remaining_work_ids:
                work_id = str(self.remaining_work_ids[0])
            current = self.catalog_current_nodes.get(work_id, "catalog:root") if work_id else "catalog:root"
            visible_ids = [
                str(node.get("node_id") or "")
                for node in (self.catalog_menus.get(work_id, {}).get(current, []) if work_id else [])
                if str(node.get("node_id") or "")
            ]
            example_id = visible_ids[0] if visible_ids else str(
                (raw_items[0] or {}).get("node_id") or ""
            )
            return {
                "ok": False,
                "rows": [{
                    "work_id": work_id or str((raw_items[0] or {}).get("node_id") or ""),
                    "ok": False,
                    "error": "catalog menu echoed instead of a decision",
                    "details": [
                        "continue_norm_catalog must send one decision, not passport cards",
                        (
                            "required: items=[{work_id, selected_node_id, confidence}]; "
                            "work_features/evidence optional — LES drafts gaps from VOR title"
                        ),
                        (
                            f'example: {{"items": [{{"work_id": "{work_id}", '
                            f'"selected_node_id": "{example_id}", '
                            f'"confidence": "medium"}}]}}'
                        ),
                        "allowed selected_node_id: " + ", ".join(visible_ids[:8]),
                    ],
                    "items": [],
                    "reject_streak": 1,
                }],
            }
        _decision_transport_keys = (
            "work_id", "current_node_id", "selected_node_id",
            "evidence", "rejected_nodes", "confidence",
            "missing_facts", "work_features", "question",
            "catalog_query", "decision",
        )
        if has_flat_decision and (not raw_items or items_are_catalog_nodes):
            synthetic_item: dict[str, Any] = {}
            for key in _decision_transport_keys:
                if key in args:
                    synthetic_item[key] = args[key]
            if not synthetic_item.get("work_id") and len(self.by_id) == 1:
                synthetic_item["work_id"] = next(iter(self.by_id))
            if not synthetic_item.get("decision"):
                if args.get("default_decision"):
                    synthetic_item["decision"] = args["default_decision"]
                elif synthetic_item.get("selected_node_id"):
                    synthetic_item["decision"] = "continue"
            if not str(synthetic_item.get("confidence") or "").strip():
                synthetic_item["confidence"] = "medium"
            args["items"] = [synthetic_item]
        elif has_flat_decision and raw_items:
            # Hybrid Qwen shape: items[] present, but selected_node_id /
            # confidence live at the top level. Merge without inventing a node.
            for transport_item in raw_items:
                if not isinstance(transport_item, dict):
                    continue
                for key in _decision_transport_keys:
                    if key in args and (
                        key not in transport_item
                        or transport_item.get(key) in (None, "", [], {})
                    ):
                        transport_item[key] = args[key]
        for transport_item in _tool_array_argument(args, "items"):
            for field in ("evidence", "rejected_nodes", "missing_facts"):
                if field in transport_item:
                    transport_item[field] = _nested_array_transport(
                        transport_item[field]
                    )
            selected_node_id = str(
                transport_item.get("selected_node_id")
                or args.get("selected_node_id")
                or ""
            ).strip()
            if selected_node_id and not str(
                transport_item.get("selected_node_id") or ""
            ).strip():
                transport_item["selected_node_id"] = selected_node_id
            evidence = transport_item.get("evidence")
            if selected_node_id and isinstance(evidence, list):
                # Qwen may compare several visible nodes and serialize the
                # selected node's evidence later in the same array. Ordering is
                # transport, not judgment: preserve every model-authored item
                # while moving exact selected-node evidence to the front.
                transport_item["evidence"] = [
                    *[
                        entry for entry in evidence
                        if isinstance(entry, dict)
                        and str(entry.get("source_node_id") or "").strip()
                        == selected_node_id
                    ],
                    *[
                        entry for entry in evidence
                        if not (
                            isinstance(entry, dict)
                            and str(entry.get("source_node_id") or "").strip()
                            == selected_node_id
                        )
                    ],
                ]
        # --- End flat-to-items normalization ---------------------------------
        rows_out: list[dict[str, Any]] = []

        def failure(work_id: str, error: str, details: list[str]) -> None:
            streak_key = f"{work_id}\0{error}"
            streak = int(self.catalog_reject_streak.get(streak_key) or 0) + 1
            self.catalog_reject_streak[streak_key] = streak
            row = {
                "work_id": work_id,
                "ok": False,
                "error": error,
                "details": details,
                "items": [],
                "reject_streak": streak,
            }
            rows_out.append(row)
            self.catalog_trace.append({
                "trace_id": uuid4().hex,
                "phase": "catalog_route",
                "turn": turn,
                "work_id": work_id,
                "decision": "rejected",
                "outcome": "rejected",
                "error": error,
                "details": details,
                "reject_streak": streak,
            })
            if streak >= 3 and self.catalog_stall is None:
                detail_text = "; ".join(str(item) for item in details if item)
                self.catalog_stall = {
                    "work_id": work_id,
                    "error": error,
                    "details": list(details),
                    "reject_streak": streak,
                    "reason": (
                        "smeta catalog stalled after "
                        f"{streak} identical rejections for {work_id}: {error}"
                        + (f" ({detail_text})" if detail_text else "")
                    ),
                }

        for item in _tool_array_argument(args, "items"):
            work_id = str(item.get("work_id") or "")
            if work_id not in self.by_id:
                if len(self.by_id) == 1:
                    work_id = next(iter(self.by_id))
                else:
                    failure(work_id, "unknown work_id", [])
                    continue
            decision = str(item.get("decision") or args.get("default_decision") or "").strip().casefold()
            current_node_id = str(item.get("current_node_id") or "").strip()
            expected_current = self.catalog_current_nodes.get(
                work_id, "catalog:root"
            )
            if not current_node_id:
                current_node_id = expected_current
            elif current_node_id != expected_current:
                failure(
                    work_id,
                    "catalog transition starts from a stale or invented node",
                    [
                        f"expected current_node_id={expected_current!r}",
                        f"received current_node_id={current_node_id!r}",
                    ],
                )
                continue
            if decision in {"select", "select_node", "choose", "navigate", "next", "confirm", "accepted"}:
                decision = "continue"
            selected_hint = str(
                item.get("selected_node_id") or args.get("selected_node_id") or ""
            ).strip()
            if not decision and selected_hint:
                decision = "continue"
            if decision not in {"continue", "ask", "broaden", "unbound"}:
                failure(
                    work_id,
                    "unsupported catalog decision",
                    ["allowed decisions: continue, ask, broaden, unbound"],
                )
                continue

            registry = self.catalog_node_registry[work_id]
            visible_items = self.catalog_menus[work_id].get(
                current_node_id, []
            )
            visible_ids = {
                str(node.get("node_id") or "") for node in visible_items
            }
            if current_node_id:
                visible_ids.add(current_node_id)
            # Flat/hybrid continue often omits evidence for the selected child
            # (or only cites rejected siblings). Draft passport evidence for the
            # model-chosen node so transport can advance without inventing a pick.
            if decision == "continue" and selected_hint in visible_ids:
                evidence_values = item.get("evidence") or args.get("evidence") or []
                if not isinstance(evidence_values, list):
                    evidence_values = []
                cites_selected = any(
                    isinstance(entry, dict)
                    and str(entry.get("source_node_id") or "").strip() == selected_hint
                    for entry in evidence_values
                )
                if not cites_selected:
                    selected_node = registry.get(selected_hint) or {}
                    for field in (
                        "purpose",
                        "official_name",
                        "official_heading",
                        "title",
                        "typical_scope",
                    ):
                        value = selected_node.get(field)
                        if value in (None, "", []):
                            continue
                        claim = (
                            "; ".join(
                                str(part) for part in value if str(part).strip()
                            )
                            if isinstance(value, list)
                            else str(value)
                        )
                        if not claim.strip():
                            continue
                        drafted = {
                            "source_node_id": selected_hint,
                            "field": field,
                            "claim": claim[:240],
                        }
                        item["evidence"] = [drafted, *evidence_values]
                        break
            if not str(item.get("confidence") or "").strip():
                item["confidence"] = "medium"
            evidence_out = []
            evidence_errors = []
            evidence_values = (
                item.get("evidence")
                if "evidence" in item
                else args.get("evidence") or []
            )
            selected_for_evidence = selected_hint
            for evidence in evidence_values or []:
                if not isinstance(evidence, dict):
                    evidence_errors.append("evidence item must be an object")
                    continue
                source_node_id = str(
                    evidence.get("source_node_id") or ""
                )
                field = str(evidence.get("field") or "")
                claim = " ".join(
                    str(evidence.get("claim") or "").split()
                )
                source_node = registry.get(source_node_id)
                # Qwen often cites the parent/root passport while selecting a child.
                # Remap only when the selected visible node carries the same field.
                if (
                    (source_node_id not in visible_ids or not source_node)
                    and selected_for_evidence in visible_ids
                    and source_node_id in {
                        current_node_id,
                        expected_current,
                        "catalog:root",
                        "",
                    }
                ):
                    candidate = registry.get(selected_for_evidence)
                    if isinstance(candidate, dict) and candidate.get(field) not in (
                        None, "", [],
                    ):
                        source_node_id = selected_for_evidence
                        source_node = candidate
                if source_node_id not in visible_ids or not source_node:
                    evidence_errors.append(
                        f"evidence node {source_node_id!r} was not shown in the current menu"
                    )
                    continue
                # Normalize evidence field aliases authored by LLM engines
                if field == "title_and_purpose":
                    if "purpose" in source_node and source_node.get("purpose"):
                        field = "purpose"
                    elif "title" in source_node and source_node.get("title"):
                        field = "title"
                elif field in ("heading", "official_heading", "name"):
                    if "official_heading" in source_node and source_node.get("official_heading"):
                        field = "official_heading"
                    elif "title" in source_node and source_node.get("title"):
                        field = "title"
                elif field in ("scope", "description"):
                    if "typical_scope" in source_node and source_node.get("typical_scope"):
                        field = "typical_scope"
                    elif "purpose" in source_node and source_node.get("purpose"):
                        field = "purpose"

                if field not in source_node or source_node.get(field) in (
                    None,
                    "",
                    [],
                ):
                    evidence_errors.append(
                        f"evidence field {field!r} is absent on {source_node_id!r}"
                    )
                    continue
                clean_claim = claim.strip("\ufffd\uFFFD\xa0 ")
                if not clean_claim:
                    claim = str(source_node.get(field) or field)
                if not claim:
                    evidence_errors.append("evidence claim must not be empty")
                    continue
                evidence_out.append({
                    "source_node_id": source_node_id,
                    "field": field,
                    "claim": claim,
                    "evidence_value": copy.deepcopy(source_node[field]),
                    "source_ref": str(source_node.get("source_ref") or ""),
                })
            rejected_out = []
            rejected_values = (
                item.get("rejected_nodes")
                if "rejected_nodes" in item
                else args.get("rejected_nodes") or []
            )
            for rejected in rejected_values or []:
                if not isinstance(rejected, dict):
                    evidence_errors.append("rejected node must be an object")
                    continue
                node_id = str(rejected.get("node_id") or "")
                reason = " ".join(
                    str(rejected.get("reason") or "").split()
                )
                if node_id not in visible_ids:
                    evidence_errors.append(
                        f"rejected node {node_id!r} was not shown as a sibling"
                    )
                    continue
                if not reason:
                    evidence_errors.append(
                        f"rejection reason is empty for {node_id!r}"
                    )
                    continue
                rejected_out.append({"node_id": node_id, "reason": reason})
            # Qwen often rejects every sibling at wide table menus (10–16).
            # Hard-fail burned ~10 model turns (~80s) after a correct selection.
            # Keep the first six as audit; the selected child is what advances.
            if len(rejected_out) > 6:
                rejected_out = rejected_out[:6]
            if evidence_errors:
                failure(
                    work_id,
                    "catalog route evidence failed structural validation",
                    evidence_errors,
                )
                continue

            missing_facts = [
                " ".join(str(value).split())
                for value in (item.get("missing_facts") or [])
                if str(value).strip()
            ][:8]
            confidence = str(item.get("confidence") or "").casefold()
            if confidence not in {"low", "medium", "high"}:
                failure(
                    work_id,
                    "catalog route confidence is required",
                    ["allowed confidence values: low, medium, high"],
                )
                continue
            # Selection wins over a conflicting rejected_nodes entry (Qwen often
            # lists the chosen child in both places while comparing siblings).
            if selected_hint:
                rejected_out = [
                    entry
                    for entry in rejected_out
                    if str(entry.get("node_id") or "") != selected_hint
                ]
            audit = {
                "decision": decision,
                "current_node_id": current_node_id,
                "evidence": evidence_out,
                "rejected_nodes": rejected_out,
                "confidence": confidence,
                "missing_facts": missing_facts,
                "selection_owner": "model",
            }

            if decision == "ask":
                question = (
                    dict(item.get("question") or {})
                    if isinstance(item.get("question"), dict)
                    else {}
                )
                text_value = " ".join(str(question.get("text") or "").split())
                reason_value = " ".join(
                    str(question.get("reason") or "").split()
                )
                options = [
                    " ".join(str(value).split())
                    for value in (question.get("options") or [])
                    if str(value).strip()
                ][:8]
                if not text_value or not reason_value or len(options) < 2:
                    failure(
                        work_id,
                        "ask decision requires one practical question",
                        [
                            "question.text and question.reason are required",
                            "question.options must contain at least two variants",
                        ],
                    )
                    continue
                question_kind = str(
                    question.get("question_kind")
                    or "physical_installation"
                )
                if question_kind not in {
                    "physical_installation",
                    "project_condition",
                }:
                    failure(
                        work_id,
                        "catalog question must request a user-owned fact",
                        [
                            "allowed question_kind values: "
                            "physical_installation, project_condition"
                        ],
                    )
                    continue
                pending_question = {
                    "question_kind": question_kind,
                    "text": text_value,
                    "reason": reason_value,
                    "work_ids": [work_id],
                    "options": options,
                }
                row = {
                    "work_id": work_id,
                    "ok": True,
                    "level": "awaiting_user_input",
                    "current_node_id": current_node_id,
                    "items": [],
                    "route_decision": audit,
                    "requires_user_input": True,
                    "pending_question": pending_question,
                }
                rows_out.append(row)
                self.catalog_trace.append({
                    "trace_id": uuid4().hex,
                    "phase": "catalog_route",
                    "turn": turn,
                    "work_id": work_id,
                    "outcome": "accepted",
                    **audit,
                    "pending_question": pending_question,
                })
                continue

            if decision == "unbound":
                if not evidence_out:
                    failure(
                        work_id,
                        "unbound route requires official catalog evidence",
                        ["cite at least one shown official node"],
                    )
                    continue
                current_node = registry.get(current_node_id) or {}
                current_type = str(current_node.get("node_type") or "")
                parent_id = str(current_node.get("parent_id") or "")
                # Qwen often unbinds inside ГЭСНм after one family glance; film /
                # building rows then never reach ГЭСН. Require broaden to root.
                if (
                    current_node_id != "catalog:root"
                    and current_type in {"family", "collection"}
                    and parent_id
                ):
                    failure(
                        work_id,
                        "catalog unbound before leaving the family branch is premature",
                        [
                            "call broaden_norm_catalog toward catalog:root",
                            "consider other families before unbound",
                        ],
                    )
                    continue
                self.catalog_terminal_decisions[work_id] = audit
                rows_out.append({
                    "work_id": work_id,
                    "ok": True,
                    "level": "catalog_unbound",
                    "current_node_id": current_node_id,
                    "items": [],
                    "route_decision": audit,
                    "next_action": (
                        "submit_lsr_mapping with decision=unbound and preserve "
                        "this evidence; do not search another branch silently"
                    ),
                    "force_mapping_serialization": True,
                })
                self.catalog_trace.append({
                    "trace_id": uuid4().hex,
                    "phase": "catalog_route",
                    "turn": turn,
                    "work_id": work_id,
                    "outcome": "accepted",
                    **audit,
                })
                continue

            if decision == "broaden":
                current_node = registry.get(current_node_id)
                parent_id = str(
                    (current_node or {}).get("parent_id") or ""
                )
                if current_node_id == "catalog:root" or not parent_id:
                    failure(
                        work_id,
                        "cannot broaden above the catalog root",
                        [],
                    )
                    continue
                parent_menu = self.catalog_menus[work_id].get(parent_id) or []
                if not parent_menu:
                    failure(
                        work_id,
                        "parent catalog menu is not available in the checkpoint",
                        [f"parent_id={parent_id!r}"],
                    )
                    continue
                self._clear_catalog_descendants(work_id, parent_id)
                self._drop_routes_for_work(work_id)
                self.catalog_current_nodes[work_id] = parent_id
                row = {
                    "work_id": work_id,
                    "ok": True,
                    "level": "broadened",
                    "current_node_id": parent_id,
                    "items": copy.deepcopy(parent_menu),
                    "route_decision": audit,
                    "next_action": (
                        "choose only a real child from this parent menu; "
                        "do not jump to an unshown sibling branch"
                    ),
                }
                rows_out.append(row)
                self.catalog_trace.append({
                    "trace_id": uuid4().hex,
                    "phase": "catalog_route",
                    "turn": turn,
                    "work_id": work_id,
                    "outcome": "accepted",
                    **audit,
                    "broadened_to": parent_id,
                })
                continue

            raw_selected = str(
                item.get("selected_node_id") or args.get("selected_node_id") or ""
            ).strip()
            selected_node_id, select_source = _resolve_selected_node_id(
                raw_selected, evidence_out, visible_ids
            )
            if selected_node_id not in visible_ids:
                failure(
                    work_id,
                    "selected node is not a child shown by the current menu",
                    [
                        f"selected_node_id={selected_node_id!r}",
                        f"visible child ids={sorted(visible_ids)}",
                    ],
                )
                continue
            # After resolve, drop the chosen child from rejected audit again —
            # Qwen frequently puts the same node in both fields.
            rejected_out = [
                entry
                for entry in rejected_out
                if str(entry.get("node_id") or "") != selected_node_id
            ]
            audit["rejected_nodes"] = rejected_out
            if not evidence_out:
                failure(
                    work_id,
                    "continue decision requires official node evidence",
                    ["cite at least one field from a shown node"],
                )
                continue
            if evidence_out[0]["source_node_id"] != selected_node_id:
                failure(
                    work_id,
                    "continue evidence must start from the selected child node",
                    [
                        f"selected_node_id={selected_node_id!r}",
                        (
                            "first evidence source_node_id="
                            f"{evidence_out[0]['source_node_id']!r}"
                        ),
                    ],
                )
                continue
            selected_node = registry[selected_node_id]
            if str(selected_node.get("parent_id") or "") != current_node_id:
                failure(
                    work_id,
                    "selected node is not an immediate child of current_node_id",
                    [],
                )
                continue
            node_type = str(selected_node.get("node_type") or "")
            work_features = _merge_work_features_with_source_draft(
                item.get("work_features") if isinstance(item.get("work_features"), dict) else {},
                self.by_id.get(work_id),
            )
            item["work_features"] = work_features
            catalog_query = " ".join(
                str(item.get("catalog_query") or "").split()
            )
            if not catalog_query:
                parts = [work_features.get("operation"), work_features.get("equipment"), work_features.get("system")]
                candidate_q = " ".join(str(p).strip() for p in parts if p and str(p).strip())
                if not candidate_q or len(re.findall(r"[0-9A-Za-zА-Яа-яЁё]+", candidate_q)) < 2:
                    candidate_q = str(self.by_id.get(work_id, {}).get("title") or "")
                catalog_query = candidate_q.strip()
            query_toks = re.findall(r"[0-9A-Za-zА-Яа-яЁё]+", catalog_query)
            if len(query_toks) > 12:
                catalog_query = " ".join(query_toks[:12])
            next_items: list[dict[str, Any]] = []
            next_level = ""
            if node_type == "family":
                required_features = (
                    "domain",
                    "system",
                    "equipment",
                    "operation",
                    "assembly_state",
                    "installation_context",
                )
                if any(
                    not str(work_features.get(field) or "").strip()
                    for field in required_features
                ):
                    failure(
                        work_id,
                        "family transition requires a complete work feature card",
                        [f"required fields: {', '.join(required_features)}"],
                    )
                    continue
                allowed_assembly_states = {
                    "empty",
                    "factory_assembled",
                    "site_assembled",
                    "component",
                    "unknown",
                }
                if (
                    str(work_features.get("assembly_state") or "")
                    not in allowed_assembly_states
                ):
                    failure(
                        work_id,
                        "work feature assembly_state is outside the typed contract",
                        [
                            "allowed values: "
                            + ", ".join(sorted(allowed_assembly_states)),
                            (
                                "a complete product delivered disassembled and "
                                "assembled on site is site_assembled"
                            ),
                        ],
                    )
                    continue
                query_tokens = re.findall(
                    r"[0-9A-Za-zА-Яа-яЁё]+", catalog_query
                )
                if not 2 <= len(query_tokens) <= 12:
                    failure(
                        work_id,
                        "family transition requires a bounded estimating catalog query",
                        ["catalog_query must contain 2-12 words"],
                    )
                    continue
                family = str(selected_node.get("cipher") or "")
                shortlist = rank_norm_catalog_collections(
                    catalog_query,
                    family=family,
                    limit=6,
                )
                trace = dict(shortlist.get("retrieval_trace") or {})
                shortlist_cards = [
                    value
                    for value in (shortlist.get("cards") or [])
                    if isinstance(value, dict)
                ]
                menu_ready, rerank_status = _catalog_shortlist_menu_ready(
                    shortlist_cards,
                    rerank_status=trace.get("rerank_status"),
                )
                if not menu_ready:
                    failure(
                        work_id,
                        "collection shortlist is empty",
                        [f"rerank_status={rerank_status}"],
                    )
                    continue
                next_items = [
                    self._catalog_node_fields(value)
                    for value in shortlist_cards
                ]
                self.selected_base_types[work_id] = {
                    family.casefold(): {
                        "family": family,
                        "reason": "; ".join(
                            value["claim"] for value in evidence_out
                        ),
                        "confidence": confidence,
                        "work_features": copy.deepcopy(work_features),
                    }
                }
                self.selected_collections[work_id].clear()
                self.selected_sections[work_id].clear()
                self.selected_tables[work_id].clear()
                next_level = "collection"
            elif node_type == "collection":
                family = str(selected_node_id.split(":", 3)[2])
                collection = str(selected_node.get("cipher") or "")
                payload = browse_norm_catalog(
                    family=family,
                    collection=collection,
                    limit=1000,
                )
                next_items = [
                    self._catalog_node_fields(value)
                    for value in (payload.get("items") or [])
                    if isinstance(value, dict)
                ]
                self.selected_collections[work_id] = {
                    (family.casefold(), collection)
                }
                self.selected_sections[work_id].clear()
                self.selected_tables[work_id].clear()
                next_level = "section"
            elif node_type == "section":
                parts = selected_node_id.split(":", 3)
                family = str(parts[2])
                section = str(selected_node.get("cipher") or "")
                collection = section[:2]
                query_tokens = re.findall(
                    r"[0-9A-Za-zА-Яа-яЁё]+", catalog_query
                )
                if not 2 <= len(query_tokens) <= 12:
                    failure(
                        work_id,
                        "section transition requires a bounded work query",
                        ["catalog_query must contain 2-12 words"],
                    )
                    continue
                shortlist = rank_norm_catalog_tables(
                    catalog_query,
                    family=family,
                    collection=collection,
                    section=section,
                    limit=16,
                )
                trace = dict(shortlist.get("retrieval_trace") or {})
                shortlist_cards = [
                    value
                    for value in (shortlist.get("cards") or [])
                    if isinstance(value, dict)
                ]
                menu_ready, rerank_status = _catalog_shortlist_menu_ready(
                    shortlist_cards,
                    rerank_status=trace.get("rerank_status"),
                )
                if not menu_ready:
                    failure(
                        work_id,
                        "table shortlist is empty",
                        [f"rerank_status={rerank_status}"],
                    )
                    continue
                next_items = [
                    self._catalog_node_fields(value)
                    for value in shortlist_cards
                ]
                self.selected_sections[work_id] = {
                    (family.casefold(), collection, section)
                }
                self.selected_tables[work_id].clear()
                next_level = "table"
            elif node_type == "table":
                parts = selected_node_id.split(":", 3)
                family = str(parts[2])
                table_code = str(selected_node.get("cipher") or "")
                collection = table_code[:2]
                section = table_code[:5]
                self.selected_tables[work_id] = {
                    (family.casefold(), collection, table_code)
                }
                # Do not publish table select into route_evidence_cache.
                # A wrong first table (e.g. ГЭСНм:06-05-001) would be reused
                # by every later row before any bind proves the route.
                next_level = "norm_search"
            else:
                failure(
                    work_id,
                    "continue is unsupported for this node type",
                    [f"node_type={node_type!r}"],
                )
                continue

            self.catalog_current_nodes[work_id] = selected_node_id
            if next_items:
                self.catalog_menus[work_id][selected_node_id] = copy.deepcopy(
                    next_items
                )
                for node in next_items:
                    registry[str(node["node_id"])] = copy.deepcopy(node)
            row = {
                "work_id": work_id,
                "ok": True,
                "level": next_level,
                "current_node_id": selected_node_id,
                "items": next_items,
                "route_decision": {
                    **audit,
                    "selected_node_id": selected_node_id,
                },
                "next_action": (
                    "call search_norms_batch inside the selected table"
                    if next_level == "norm_search"
                    else "make one typed local decision over these real child nodes"
                ),
            }
            rows_out.append(row)
            self.catalog_trace.append({
                "trace_id": uuid4().hex,
                "phase": "catalog_route",
                "turn": turn,
                "work_id": work_id,
                "outcome": "accepted",
                **audit,
                "selected_node_id": selected_node_id,
                "next_level": next_level,
                "item_count": len(next_items),
            })
        result = {
            "ok": any(row.get("ok") is True for row in rows_out),
            "rows": rows_out,
        }
        if any(
            row.get("force_mapping_serialization") is True for row in rows_out
        ):
            result["force_mapping_serialization"] = True
        if self.catalog_stall is not None:
            result["catalog_stalled"] = True
            result["catalog_stall"] = dict(self.catalog_stall)
            result["error"] = str(self.catalog_stall.get("reason") or "")
            # Stop burning identical reject turns: leave catalog for mapping /
            # unbound serialization. Does not invent a norm.
            if not result["ok"]:
                result["force_mapping_serialization"] = True
        pending = next(
            (
                row.get("pending_question")
                for row in rows_out
                if row.get("requires_user_input")
            ),
            None,
        )
        if pending:
            result["requires_user_input"] = True
            result["pending_question"] = pending
        return result

    def _clear_catalog_descendants(
        self,
        work_id: str,
        parent_id: str,
    ) -> None:
        """Clear only active descendants while preserving the immutable route trace."""
        if parent_id == "catalog:root":
            self.selected_base_types[work_id].clear()
            self.selected_collections[work_id].clear()
            self.selected_sections[work_id].clear()
            self.selected_tables[work_id].clear()
            return
        node = self.catalog_node_registry[work_id].get(parent_id) or {}
        node_type = str(node.get("node_type") or "")
        if node_type == "family":
            self.selected_collections[work_id].clear()
            self.selected_sections[work_id].clear()
            self.selected_tables[work_id].clear()
        elif node_type == "collection":
            self.selected_sections[work_id].clear()
            self.selected_tables[work_id].clear()
        elif node_type == "section":
            self.selected_tables[work_id].clear()

    def _catalog(self, args: dict[str, Any], *, turn: int) -> dict[str, Any]:
        rows_out: list[dict[str, Any]] = []
        shared_catalog_owner: dict[tuple[str, str, str, str, str], str] = {}
        collection_shortlist_cache: dict[
            tuple[str, str],
            dict[str, Any],
        ] = {}
        pending_read_work_ids = [
            work_id
            for work_id in self.by_id
            if self.candidates.get(work_id) and not self.opened.get(work_id)
        ]

        def compact_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
            compacted = []
            for entry in payload.get("items") or []:
                if not isinstance(entry, dict):
                    continue
                compact = {
                    "key": entry.get("key") or entry.get("norm_code"),
                    "node_id": entry.get("node_id"),
                    "parent_id": entry.get("parent_id"),
                    "node_type": entry.get("node_type"),
                    "cipher": entry.get("cipher"),
                    "edition": entry.get("edition"),
                    "norm_count": entry.get("norm_count"),
                    "resource_count": entry.get("resource_count"),
                }
                compact = {
                    key: value
                    for key, value in compact.items()
                    if value not in (None, "", [])
                }
                for key, bound in (
                    ("official_name", 240),
                    ("official_heading", 320),
                    ("purpose", 320),
                    ("title", 240),
                    ("approval_basis", 240),
                    ("calculation_use", 320),
                    ("navigation_url", 240),
                    ("source_ref", 240),
                    ("source_example", 160),
                ):
                    value = str(entry.get(key) or "").strip()
                    if value:
                        compact[key] = value[:bound]
                for key in ("typical_scope", "not_for", "questions_to_ask"):
                    values = [
                        str(value).strip()
                        for value in (entry.get(key) or [])
                        if str(value).strip()
                    ]
                    if values:
                        compact[key] = values[:6]
                hierarchy = [
                    str(value).strip()
                    for value in (entry.get("hierarchy") or [])
                    if str(value).strip()
                ]
                if hierarchy:
                    compact["hierarchy"] = hierarchy[:6]
                norm_name_examples = [
                    str(value).strip()
                    for value in (entry.get("norm_name_examples") or [])
                    if str(value).strip()
                ]
                if norm_name_examples:
                    compact["norm_name_examples"] = norm_name_examples[:12]
                if entry.get("navigation_kind"):
                    compact["navigation_kind"] = entry.get("navigation_kind")
                if entry.get("measure_unit"):
                    compact["measure_unit"] = entry.get("measure_unit")
                if entry.get("navigation_score") is not None:
                    compact["navigation_score"] = entry.get("navigation_score")
                if entry.get("catalog_compass_score") is not None:
                    compact["catalog_compass_score"] = entry.get(
                        "catalog_compass_score"
                    )
                examples = [
                    {
                        "norm_code": str(example.get("norm_code") or "")[:40],
                        "norm_name": str(example.get("norm_name") or "")[:240],
                    }
                    for example in (entry.get("matched_norm_examples") or [])[:3]
                    if isinstance(example, dict)
                ]
                if examples:
                    compact["matched_norm_examples"] = examples
                compacted.append(compact)
            return compacted

        def reject(
            *,
            work_id: str,
            error: str,
            details: list[str],
            filters: dict[str, str],
            next_action: str = "",
        ) -> None:
            row = {
                "work_id": work_id,
                "ok": False,
                "error": error,
                "details": details,
                "filters": filters,
                "items": [],
            }
            if next_action:
                row["next_action"] = next_action
            rows_out.append(row)
            trace_row = {
                "phase": "catalog_browse",
                "turn": turn,
                "work_id": work_id,
                "level": "rejected",
                "filters": filters,
                "error": error,
                "details": details,
                "item_count": 0,
            }
            if next_action:
                trace_row["next_action"] = next_action
            self.catalog_trace.append(trace_row)

        for item in _tool_array_argument(args, "items"):
            work_id = str(item.get("work_id") or "")
            if work_id not in self.by_id:
                rows_out.append({"work_id": work_id, "ok": False, "error": "unknown work_id"})
                continue
            family = str(item.get("family") or "").strip()
            collection = re.sub(r"\D", "", str(item.get("collection") or ""))[:2]
            section_digits = re.sub(r"\D", "", str(item.get("section") or ""))[:4]
            if len(section_digits) == 2 and collection:
                section_digits = f"{collection}{section_digits}"
            section = (
                f"{section_digits[:2]}-{section_digits[2:]}"
                if len(section_digits) == 4
                else ""
            )
            table = re.sub(r"[^0-9-]", "", str(item.get("table") or "")).strip("-")[:9]
            confirm_scope = _tool_bool(item.get("confirm_scope"), False)
            scope_reason = " ".join(str(item.get("scope_reason") or "").split()).strip()
            confidence = str(item.get("confidence") or "").strip().casefold()
            requested_catalog_query = " ".join(
                str(item.get("catalog_query") or "").split()
            ).strip()
            raw_work_features = (
                dict(item.get("work_features") or {})
                if isinstance(item.get("work_features"), dict)
                else {}
            )
            work_features = {
                "domain": " ".join(
                    str(raw_work_features.get("domain") or "").split()
                ),
                "system": " ".join(
                    str(raw_work_features.get("system") or "").split()
                ),
                "equipment": " ".join(
                    str(raw_work_features.get("equipment") or "").split()
                ),
                "operation": " ".join(
                    str(raw_work_features.get("operation") or "").split()
                ),
                "assembly_state": str(
                    raw_work_features.get("assembly_state") or ""
                ).strip(),
                "installation_context": " ".join(
                    str(
                        raw_work_features.get("installation_context") or ""
                    ).split()
                ),
                "unknowns": [
                    " ".join(str(value).split())
                    for value in (raw_work_features.get("unknowns") or [])
                    if str(value).strip()
                ][:8],
            }
            filters = {
                "family": family,
                "collection": collection,
                "section": section,
                "table": table,
            }
            if (
                self.require_scoped_search
                and family
                and not collection
                and not table
            ):
                required_feature_text = (
                    "domain",
                    "system",
                    "equipment",
                    "operation",
                    "installation_context",
                )
                if (
                    any(not work_features[name] for name in required_feature_text)
                    or work_features["assembly_state"]
                    not in {
                        "empty",
                        "factory_assembled",
                        "site_assembled",
                        "component",
                        "unknown",
                    }
                ):
                    reject(
                        work_id=work_id,
                        error="family selection requires a complete work feature card",
                        details=[
                            (
                                "provide domain, system, equipment, operation, "
                                "assembly_state, installation_context and unknowns"
                            ),
                            (
                                "convert a specification item into the required work "
                                "before choosing the norm family"
                            ),
                        ],
                        filters=filters,
                        next_action="browse_norm_catalog",
                    )
                    continue
                catalog_query_tokens = re.findall(
                    r"[0-9A-Za-zА-Яа-яЁё]+",
                    requested_catalog_query,
                )
                instruction_tokens = {
                    token.casefold().replace("ё", "е")
                    for token in catalog_query_tokens
                } & {
                    "ищем",
                    "выбираем",
                    "сборник",
                    "сборники",
                    "кроме",
                    "просмотренного",
                }
                generic_catalog_tokens = {
                    "оборудование",
                    "оборудования",
                    "устройство",
                    "устройства",
                    "система",
                    "системы",
                    "шкаф",
                    "шкафа",
                    "шкафов",
                    "блок",
                    "блока",
                    "блоков",
                    "панель",
                    "панели",
                    "коробка",
                    "коробки",
                    "общего",
                    "назначения",
                }
                discriminative_tokens = [
                    token.casefold().replace("ё", "е")
                    for token in catalog_query_tokens
                    if (
                        token.casefold().replace("ё", "е")
                        not in generic_catalog_tokens
                        and len(token) >= 4
                    )
                ]
                if (
                    len(catalog_query_tokens) < 2
                    or len(catalog_query_tokens) > 12
                    or instruction_tokens
                    or not discriminative_tokens
                ):
                    reject(
                        work_id=work_id,
                        error="catalog_query must be a concise estimating query",
                        details=[
                            (
                                "provide a separate 2-12 word FSNB query with the "
                                "functional system, equipment and operation"
                            ),
                            (
                                "do not copy catalog history, exclusions or navigation "
                                "instructions into catalog_query"
                            ),
                        ],
                        filters=filters,
                        next_action="browse_norm_catalog",
                    )
                    continue
            if self.require_scoped_search and pending_read_work_ids:
                reject(
                    work_id=work_id,
                    error=(
                        "candidate cards for the current work package must be read "
                        "before further catalog navigation"
                    ),
                    details=[
                        (
                            "the current scoped batch search already returned candidates "
                            "for work_ids: "
                            + ", ".join(pending_read_work_ids)
                        ),
                        (
                            "choose at most two current candidate codes per turn for one "
                            "of those work_ids and call read_norms_batch"
                        ),
                    ],
                    filters=filters,
                    next_action="read_norms_batch",
                )
                continue
            catalog_key = (
                work_id,
                family.casefold(),
                collection,
                section,
                table,
            )
            catalog_was_seen = catalog_key in self.catalog_seen
            if (
                catalog_was_seen
                and self.require_scoped_search
                and family
                and not collection
                and not table
                and requested_catalog_query
            ):
                seen_family_queries = {
                    str(trace.get("catalog_query") or "").casefold()
                    for trace in self.catalog_trace
                    if (
                        str(trace.get("work_id") or "") == work_id
                        and str((trace.get("filters") or {}).get("family") or "").casefold()
                        == family.casefold()
                        and not str(
                            (trace.get("filters") or {}).get("collection") or ""
                        )
                    )
                }
                if requested_catalog_query.casefold() not in seen_family_queries:
                    catalog_was_seen = False
            pending_collection_confirmation = bool(
                self.require_scoped_search
                and family
                and collection
                and not section
                and not table
                and confirm_scope
                and (family.casefold(), collection)
                not in self.selected_collections[work_id]
            )
            if catalog_was_seen and not pending_collection_confirmation:
                selected_scope = (
                    (family.casefold(), collection)
                    in self.selected_collections[work_id]
                    if family and collection
                    else False
                )
                if (
                    family
                    and collection
                    and not section
                    and not table
                    and not selected_scope
                ):
                    repeated_payload = browse_norm_catalog(
                        family=family,
                        collection=collection,
                        section="",
                        table="",
                        limit=1000,
                    )
                    repeated_passport = dict(
                        repeated_payload.get("collection_passport") or {}
                    )
                    passport_examples = [
                        str(repeated_passport.get("title") or "").strip(),
                        str(repeated_passport.get("source_ref") or "").strip(),
                        *[
                            str(value).strip()
                            for value in (
                                repeated_passport.get("representative_sections")
                                or []
                            )[:2]
                        ],
                    ]
                    passport_examples = [
                        value for value in passport_examples if value
                    ]
                    reject(
                        work_id=work_id,
                        error=(
                            "collection passport was previewed but scope is not confirmed"
                        ),
                        details=[
                            "call browse_norm_catalog with confirm_scope=true",
                            (
                                "passport_evidence must quote one of: "
                                + " | ".join(passport_examples)
                            ),
                            (
                                "if the passport does not fit, preview another collection "
                                "instead of repeating this one"
                            ),
                        ],
                        filters=filters,
                        next_action="confirm_scope_or_preview_another_collection",
                    )
                    continue
                row = {
                    "work_id": work_id,
                    "ok": True,
                    "level": "already_seen",
                    "filters": filters,
                    "items": [],
                    "repeated": True,
                    "next_action": (
                        "continue through section and table; a collection cannot "
                        "be searched directly in RIM"
                    ),
                }
                rows_out.append(row)
                self.catalog_trace.append({
                    "phase": "catalog_browse", "turn": turn, "work_id": work_id,
                    "level": "already_seen", "filters": row["filters"],
                    "item_count": 0, "repeated": True,
                })
                continue

            if self.require_scoped_search and not family:
                self.family_catalog_seen.add(work_id)

            if self.require_scoped_search and family and work_id not in self.family_catalog_seen:
                reject(
                    work_id=work_id,
                    error="base type selection requires the family catalog",
                    details=[
                        "call browse_norm_catalog with only work_id first",
                        "compare the model-visible family passports before choosing a base type",
                    ],
                    filters=filters,
                )
                continue

            if (
                self.require_scoped_search
                and family
                and not section
                and not table
                and (not collection or confirm_scope)
            ):
                if not scope_reason:
                    reject(
                        work_id=work_id,
                        error="normative scope selection requires model reasoning",
                        details=[
                            (
                                "scope_reason must explain why the selected base type "
                                "or collection matches the work"
                            ),
                            "LES records the reasoning but does not choose the scope",
                        ],
                        filters=filters,
                    )
                    continue
                if confidence not in {"low", "medium", "high"}:
                    reject(
                        work_id=work_id,
                        error="normative scope selection requires confidence",
                        details=["confidence must be one of: low, medium, high"],
                        filters=filters,
                    )
                    continue

            selected_family = family.casefold()
            if self.require_scoped_search and family and collection:
                if confirm_scope and not catalog_was_seen:
                    reject(
                        work_id=work_id,
                        error="collection confirmation requires its passport preview",
                        details=[
                            (
                                "call browse_norm_catalog for this family and collection "
                                "without confirm_scope first"
                            ),
                            "read the returned collection_passport before confirming scope",
                        ],
                        filters=filters,
                    )
                    continue
                if selected_family not in self.selected_base_types[work_id]:
                    reject(
                        work_id=work_id,
                        error="collection selection requires an explicit base type selection",
                        details=[
                            (
                                f"select {family!r} first with browse_norm_catalog using "
                                "scope_reason and confidence"
                            )
                        ],
                        filters=filters,
                    )
                    continue
                requested_scope = (selected_family, collection)
                existing_scopes = set(self.selected_collections[work_id])
                if requested_scope not in existing_scopes and existing_scopes:
                    searches_by_scope = {
                        (
                            str(base_type).casefold(),
                            str(selected_collection),
                        ): trace
                        for trace in self.query_trace
                        for base_type in (
                            (trace.get("filters") or {}).get("base_types") or []
                        )
                        for selected_collection in (
                            (trace.get("filters") or {}).get("collections") or []
                        )
                        if str(trace.get("work_id") or "") == work_id
                    }
                    pending_scopes = sorted(
                        existing_scope
                        for existing_scope in existing_scopes
                        if existing_scope not in searches_by_scope
                    )
                    if pending_scopes:
                        reject(
                            work_id=work_id,
                            error="selected collection path must be completed before scope expansion",
                            details=[
                                (
                                    "select a section and table, then list that table for "
                                    + ", ".join(
                                        f"{scope_family}:{scope_collection}"
                                        for scope_family, scope_collection in pending_scopes
                                    )
                                ),
                                (
                                    "a second collection is allowed only after the model "
                                    "has tested its first scoped hypothesis"
                                ),
                            ],
                            filters=filters,
                        )
                        continue
                    shown_codes = {
                        str(code)
                        for existing_scope in existing_scopes
                        for code in (
                            searches_by_scope.get(existing_scope, {}).get(
                                "candidate_codes"
                            )
                            or []
                        )
                        if str(code)
                    }
                    opened_codes = set(self.opened.get(work_id, {}))
                    if shown_codes and shown_codes.isdisjoint(opened_codes):
                        reject(
                            work_id=work_id,
                            error="candidate cards must be read before scope expansion",
                            details=[
                                (
                                    "call read_norms_batch for at least one candidate "
                                    "from the already searched collection"
                                ),
                                (
                                    "do not abandon a populated shortlist without reading "
                                    "its typed evidence"
                                ),
                            ],
                            filters=filters,
                        )
                        continue
                if table and (selected_family, collection) not in self.selected_collections[work_id]:
                    reject(
                        work_id=work_id,
                        error="table selection requires an explicit collection selection",
                        details=[
                            (
                                f"select collection {family}:{collection} first, then choose "
                                "its section and table"
                            )
                        ],
                        filters=filters,
                    )
                    continue

                if (
                    section
                    and (selected_family, collection)
                    not in self.selected_collections[work_id]
                ):
                    reject(
                        work_id=work_id,
                        error="section selection requires an explicit collection selection",
                        details=[
                            (
                                f"confirm collection {family}:{collection} first, then "
                                f"choose section {section}"
                            )
                        ],
                        filters=filters,
                    )
                    continue

            if table and collection and not table.startswith(f"{collection}-"):
                reject(
                    work_id=work_id,
                    error="table does not belong to the selected collection",
                    details=[
                        (
                            f"table {table!r} encodes collection {table[:2]!r}, "
                            f"but selected scope is {family}:{collection}"
                        )
                    ],
                    filters=filters,
                )
                continue
            if self.require_scoped_search and table and not section:
                reject(
                    work_id=work_id,
                    error="RIM table selection requires its section node",
                    details=[
                        (
                            "call browse_norm_catalog with family, collection and "
                            "section first; choose a table only from that returned menu"
                        )
                    ],
                    filters=filters,
                )
                continue
            if section and collection and not section.startswith(f"{collection}-"):
                reject(
                    work_id=work_id,
                    error="section does not belong to the selected collection",
                    details=[
                        (
                            f"section {section!r} encodes collection {section[:2]!r}, "
                            f"but selected scope is {family}:{collection}"
                        )
                    ],
                    filters=filters,
                )
                continue
            if table and section and not table.startswith(f"{section}-"):
                reject(
                    work_id=work_id,
                    error="table does not belong to the selected section",
                    details=[
                        (
                            f"table {table!r} is outside section {section!r}; "
                            "choose a table returned by that section node"
                        )
                    ],
                    filters=filters,
                )
                continue

            payload = browse_norm_catalog(
                family=family,
                collection=collection,
                section=section,
                table=table if table else "",
                limit=1000,
            )
            if (
                self.require_scoped_search
                and family
                and not collection
                and not table
            ):
                catalog_query = requested_catalog_query
                shortlist_cache_key = (
                    family.casefold(),
                    catalog_query.casefold(),
                )
                cached_shortlist = collection_shortlist_cache.get(
                    shortlist_cache_key
                )
                if cached_shortlist is not None:
                    payload = copy.deepcopy(cached_shortlist)
                    shortlist_result = {}
                else:
                    shortlist_result = (
                        rank_norm_catalog_collections(
                            catalog_query,
                            family=family,
                            limit=24,
                        )
                        or {}
                    )
                if cached_shortlist is not None:
                    payload_items = [
                        entry
                        for entry in (payload.get("items") or [])
                        if isinstance(entry, dict)
                    ]
                    if not payload_items:
                        reject(
                            work_id=work_id,
                            error="collection catalog shortlist is empty",
                            details=[
                                "rephrase catalog_query as a concise 2-12 word estimating query",
                                "do not guess a collection number from the complete catalog",
                            ],
                            filters=filters,
                        )
                        continue
                else:
                    catalog_retrieval_trace = dict(
                        shortlist_result.get("retrieval_trace") or {}
                    )
                    shortlist_cards = [
                        entry
                        for entry in (shortlist_result.get("cards") or [])
                        if isinstance(entry, dict)
                    ]
                    menu_ready, rerank_status = _catalog_shortlist_menu_ready(
                        shortlist_cards,
                        rerank_status=catalog_retrieval_trace.get("rerank_status"),
                    )
                    if not menu_ready:
                        reject(
                            work_id=work_id,
                            error="collection catalog shortlist is empty",
                            details=[
                                f"rerank_status={rerank_status}",
                                (
                                    "rephrase catalog_query; do not guess a collection "
                                    "number from the complete catalog"
                                ),
                            ],
                            filters=filters,
                        )
                        continue
                    collection_items = {
                        str(entry.get("key") or ""): dict(entry)
                        for entry in (payload.get("items") or [])
                        if isinstance(entry, dict)
                    }
                    collection_scores: dict[str, float] = {}
                    collection_compass_scores: dict[str, float] = {}
                    collection_first_rank: dict[str, int] = {}
                    collection_examples: dict[str, list[dict[str, str]]] = {}
                    for candidate_collection, catalog_item in collection_items.items():
                        compass_score = catalog_compass_score(
                            catalog_query,
                            catalog_item,
                        )
                        if compass_score <= 0:
                            continue
                        collection_compass_scores[candidate_collection] = compass_score
                        collection_scores[candidate_collection] = compass_score
                        collection_first_rank[candidate_collection] = 10_000
                    for rank, card in enumerate(
                        shortlist_result.get("cards") or [],
                        start=1,
                    ):
                        if not isinstance(card, dict):
                            continue
                        code = str(card.get("norm_code") or "")
                        candidate_collection = str(
                            card.get("collection") or _norm_collection(code)
                        )
                        if candidate_collection not in collection_items:
                            continue
                        collection_scores[candidate_collection] = (
                            collection_scores.get(candidate_collection, 0.0)
                            + (1.0 / float(rank))
                        )
                        collection_first_rank.setdefault(
                            candidate_collection,
                            rank,
                        )
                        if str(card.get("navigation_kind") or "") != "collection":
                            examples = collection_examples.setdefault(
                                candidate_collection,
                                [],
                            )
                            if len(examples) < 3:
                                examples.append({
                                    "norm_code": code,
                                    "norm_name": str(
                                        card.get("title")
                                        or card.get("norm_name")
                                        or ""
                                    ),
                                })
                    ranked_collections = sorted(
                        collection_scores,
                        key=lambda value: (
                            -collection_scores[value],
                            collection_first_rank[value],
                            value,
                        ),
                    )[:6]
                    if not ranked_collections:
                        reject(
                            work_id=work_id,
                            error="collection catalog shortlist is empty",
                            details=[
                                "rephrase catalog_query as a concise 2-12 word estimating query",
                                "do not guess a collection number from the complete catalog",
                            ],
                            filters=filters,
                        )
                        continue
                    payload["items"] = [
                        {
                            **collection_items[value],
                            "navigation_score": round(
                                collection_scores[value],
                                6,
                            ),
                            "catalog_compass_score": collection_compass_scores.get(
                                value,
                                0.0,
                            ),
                            "matched_norm_examples": collection_examples.get(
                                value,
                                [],
                            ),
                        }
                        for value in ranked_collections
                    ]
                    payload["catalog_query"] = catalog_query
                    payload["catalog_retrieval_trace"] = {
                        **catalog_retrieval_trace,
                        "retrieval_policy": (
                            catalog_retrieval_trace.get("retrieval_policy")
                            or "typed_catalog_graph_then_rerank"
                        ),
                        "collection_compass_policy": (
                            "official_catalog_graph_plus_rerank"
                        ),
                        "shortlisted_collections": ranked_collections,
                    }
                    collection_shortlist_cache[shortlist_cache_key] = (
                        copy.deepcopy(payload)
                    )
            if (
                self.require_scoped_search
                and family
                and collection
                and section
                and not table
            ):
                section_query_tokens = re.findall(
                    r"[0-9A-Za-zА-Яа-яЁё]+",
                    requested_catalog_query,
                )
                if not 2 <= len(section_query_tokens) <= 12:
                    reject(
                        work_id=work_id,
                        error="table catalog query must describe the work inside the section",
                        details=[
                            (
                                "catalog_query must contain 2-12 words naming the "
                                "equipment, operation or measure to rank official tables"
                            ),
                            "do not send instructions, exclusions or catalog history",
                        ],
                        filters=filters,
                        next_action="browse_norm_catalog",
                    )
                    continue
                table_shortlist = rank_norm_catalog_tables(
                    requested_catalog_query,
                    family=family,
                    collection=collection,
                    section=section,
                    limit=16,
                )
                table_retrieval_trace = dict(
                    table_shortlist.get("retrieval_trace") or {}
                )
                table_cards = [
                    entry
                    for entry in (table_shortlist.get("cards") or [])
                    if isinstance(entry, dict)
                ]
                menu_ready, table_rerank_status = _catalog_shortlist_menu_ready(
                    table_cards,
                    rerank_status=table_retrieval_trace.get("rerank_status"),
                )
                if not menu_ready:
                    reject(
                        work_id=work_id,
                        error="table catalog shortlist is empty",
                        details=[
                            f"rerank_status={table_rerank_status}",
                            (
                                "rephrase catalog_query for this section; do not jump "
                                "to a norm search without a table menu"
                            ),
                        ],
                        filters=filters,
                    )
                    continue
                payload["items"] = [dict(entry) for entry in table_cards]
                payload["catalog_query"] = requested_catalog_query
                payload["catalog_retrieval_trace"] = table_retrieval_trace
            payload_items = [
                entry for entry in (payload.get("items") or [])
                if isinstance(entry, dict)
            ]
            if family and not payload_items:
                reject(
                    work_id=work_id,
                    error="selected normative catalog scope does not exist",
                    details=[
                        (
                            "the typed normative store contains no entries for "
                            f"{family}:{collection or '*'}"
                            + (f", table {table}" if table else "")
                        ),
                        "correct the base type, collection or table before searching",
                    ],
                    filters=filters,
                )
                continue

            if (
                self.require_scoped_search
                and family
                and collection
                and not section
                and not table
                and not confirm_scope
            ):
                self.catalog_seen.add(catalog_key)
                collection_passport = dict(payload.get("collection_passport") or {})
                row = {
                    "work_id": work_id,
                    "ok": True,
                    "level": "collection_previewed",
                    "filters": {
                        "family": family,
                        "collection": collection,
                        "section": "",
                        "table": "",
                    },
                    "items": [],
                    "collection_passport": collection_passport,
                    "next_action": (
                        "compare this passport with the functional system of the work. If it "
                        "fits, call browse_norm_catalog again with confirm_scope=true, "
                        "passport_evidence, scope_reason and confidence; otherwise preview "
                        "another collection"
                    ),
                }
                rows_out.append(row)
                self.catalog_trace.append({
                    "phase": "catalog_browse",
                    "turn": turn,
                    "work_id": work_id,
                    "level": "collection_previewed",
                    "filters": row["filters"],
                    "passport_source_ref": str(
                        collection_passport.get("source_ref") or ""
                    ),
                    "item_count": 0,
                    "repeated": False,
                })
                continue

            if (
                self.require_scoped_search
                and family
                and collection
                and not section
                and not table
                and confirm_scope
            ):
                passport = dict(payload.get("collection_passport") or {})
                passport_evidence = " ".join(
                    str(item.get("passport_evidence") or "").split()
                ).strip()
                missing_evidence = []
                if not passport_evidence:
                    missing_evidence.append("passport_evidence is required")
                passport_anchors = [
                    str(passport.get("title") or ""),
                    str(passport.get("source_ref") or ""),
                    *[
                        str(value)
                        for value in (
                            passport.get("representative_sections") or []
                        )
                    ],
                ]
                if passport_evidence and not any(
                    anchor
                    and (
                        anchor.casefold() in passport_evidence.casefold()
                        or passport_evidence.casefold() in anchor.casefold()
                    )
                    for anchor in passport_anchors
                ):
                    missing_evidence.append(
                        "passport_evidence must quote the returned title, source or section"
                    )
                if missing_evidence:
                    reject(
                        work_id=work_id,
                        error="collection confirmation requires passport evidence",
                        details=[
                            *missing_evidence,
                            (
                                "quote one of: "
                                + " | ".join(
                                    anchor for anchor in passport_anchors if anchor
                                )
                            ),
                        ],
                        filters=filters,
                        next_action="confirm_scope_with_returned_passport_evidence",
                    )
                    continue

            self.catalog_seen.add(catalog_key)
            if self.require_scoped_search and family and not collection:
                self.selected_base_types[work_id][selected_family] = {
                    "family": family,
                    "reason": scope_reason,
                    "confidence": confidence,
                    "work_features": copy.deepcopy(work_features),
                }
            if (
                self.require_scoped_search
                and family
                and collection
                and not section
                and not table
            ):
                self.selected_collections[work_id].add((selected_family, collection))
            if self.require_scoped_search and family and collection and section and not table:
                self.selected_sections[work_id].add(
                    (selected_family, collection, section)
                )
            if (
                self.require_scoped_search
                and family
                and collection
                and section
                and table
            ):
                if (
                    selected_family,
                    collection,
                    section,
                ) not in self.selected_sections[work_id]:
                    reject(
                        work_id=work_id,
                        error="table selection requires an explicit section selection",
                        details=[
                            (
                                f"select section {family}:{section} first and choose "
                                "a table from its returned menu"
                            )
                        ],
                        filters=filters,
                    )
                    continue
                self.selected_tables[work_id].add((selected_family, collection, table))

            if (
                self.require_scoped_search
                and family
                and collection
                and section
                and table
            ):
                row = {
                    "work_id": work_id,
                    "ok": True,
                    "level": "table_selected",
                    "filters": {
                        "family": family,
                        "collection": re.sub(r"\D", "", collection)[:2],
                        "section": section,
                        "table": table,
                    },
                    "items": [],
                    "next_action": (
                        "call search_norms_batch with this table in table_codes; "
                        "the tool returns its complete official row menu"
                    ),
                }
                rows_out.append(row)
                self.catalog_trace.append({
                    "phase": "catalog_browse", "turn": turn, "work_id": work_id,
                    "level": "scope_selected", "filters": row["filters"],
                    "item_count": 0, "repeated": False,
                })
                continue
            if (
                self.require_scoped_search
                and family
                and collection
                and section
            ):
                compacted = compact_items(payload)
                row = {
                    "work_id": work_id,
                    "ok": True,
                    "level": "section_selected",
                    "filters": {
                        "family": family,
                        "collection": collection,
                        "section": section,
                        "table": "",
                    },
                    "items": compacted,
                    "catalog_query": requested_catalog_query,
                    "catalog_retrieval_trace": dict(
                        payload.get("catalog_retrieval_trace") or {}
                    ),
                    "next_action": (
                        "choose one official table from this section shortlist, "
                        "then call browse_norm_catalog with the same family, "
                        "collection and section plus that table code"
                    ),
                }
                rows_out.append(row)
                self.catalog_trace.append({
                    "phase": "catalog_browse",
                    "turn": turn,
                    "work_id": work_id,
                    "level": "section_selected",
                    "filters": row["filters"],
                    "catalog_query": requested_catalog_query,
                    "catalog_retrieval_trace": row["catalog_retrieval_trace"],
                    "item_count": len(compacted),
                    "repeated": False,
                })
                continue
            if self.require_scoped_search and family and collection:
                compacted = compact_items(payload)
                row = {
                    "work_id": work_id,
                    "ok": True,
                    "level": "collection_selected",
                    "filters": {
                        "family": family,
                        "collection": collection,
                        "section": "",
                        "table": "",
                    },
                    "items": compacted,
                    "collection_passport": dict(
                        payload.get("collection_passport") or {}
                    ),
                    "scope_selection": {
                        "family": family,
                        "collection": collection,
                        "reason": scope_reason,
                        "confidence": confidence,
                        "selection_owner": "model",
                    },
                    "next_action": (
                        "choose one official section from this menu; call "
                        "browse_norm_catalog with family, collection, section and "
                        "a 2-12 word catalog_query to receive its table shortlist"
                    ),
                }
                rows_out.append(row)
                self.catalog_trace.append({
                    "phase": "catalog_browse",
                    "turn": turn,
                    "work_id": work_id,
                    "level": "scope_selected",
                    "filters": row["filters"],
                    "scope_reason": scope_reason,
                    "confidence": confidence,
                    "passport_source_ref": str(
                        row["collection_passport"].get("source_ref") or ""
                    ),
                    "item_count": len(compacted),
                    "repeated": False,
                })
                continue
            shared_key = (
                family.casefold(),
                collection,
                section,
                table,
                str(payload.get("catalog_query") or "").casefold(),
            )
            if self.require_scoped_search and shared_key in shared_catalog_owner:
                owner_work_id = shared_catalog_owner[shared_key]
                row = {
                    "work_id": work_id,
                    "ok": True,
                    "level": "shared_catalog",
                    "filters": {
                        "family": family,
                        "collection": collection,
                        "section": section,
                        "table": table,
                    },
                    "items": [],
                    "shared_items_with_work_id": owner_work_id,
                    "next_action": (
                        "use the identical catalog menu returned for "
                        f"{owner_work_id}; choose scope for this work_id"
                    ),
                }
                rows_out.append(row)
                self.catalog_trace.append({
                    "phase": "catalog_browse",
                    "turn": turn,
                    "work_id": work_id,
                    "level": "shared_catalog",
                    "filters": row["filters"],
                    "item_count": 0,
                    "shared_items_with_work_id": owner_work_id,
                    "repeated": False,
                })
                continue
            shared_catalog_owner[shared_key] = work_id
            compacted = compact_items(payload)
            level = payload.get("level")
            if self.require_scoped_search and family and not collection:
                level = "base_type_selected"
            row = {
                "work_id": work_id,
                "ok": True,
                "level": level,
                "filters": payload.get("filters") or {},
                "items": compacted,
                "next_action": (
                    (
                        "choose one initial collection from this reranked navigation shortlist "
                        "for every relevant work_id; preview its passport, confirm it, then "
                        "descend through section and table before listing norms"
                    )
                    if self.require_scoped_search and family
                    else (
                        "compare the family passports, then call browse_norm_catalog "
                        "with family, scope_reason and confidence"
                    )
                    if self.require_scoped_search
                    else (
                        "choose a family, collection, section and official table; then call "
                        "search_norms_batch with table_codes to receive every row of that table"
                    )
                ),
            }
            if payload.get("catalog_query"):
                row["catalog_query"] = str(payload.get("catalog_query") or "")
                row["catalog_retrieval_trace"] = dict(
                    payload.get("catalog_retrieval_trace") or {}
                )
            if self.require_scoped_search and family:
                row["scope_selection"] = {
                    "family": family,
                    "reason": scope_reason,
                    "confidence": confidence,
                    "selection_owner": "model",
                }
            rows_out.append(row)
            self.catalog_trace.append({
                "phase": "catalog_browse",
                "turn": turn,
                "work_id": work_id,
                "level": level,
                "filters": payload.get("filters") or {},
                "scope_reason": scope_reason,
                "confidence": confidence,
                "item_count": len(compacted),
                "catalog_query": str(payload.get("catalog_query") or ""),
                "catalog_retrieval_trace": dict(
                    payload.get("catalog_retrieval_trace") or {}
                ),
                "repeated": False,
            })
        result: dict[str, Any] = {
            "ok": any(row.get("ok") is True for row in rows_out),
            "rows": rows_out,
        }
        if not rows_out:
            result["error"] = "catalog items are empty or malformed"
        return result

    def _search(self, args: dict[str, Any], *, turn: int) -> dict[str, Any]:
        items = sorted(
            (
                item
                for item in _tool_array_argument(args, "items")
                if isinstance(item, dict)
            ),
            key=lambda item: (
                str(item.get("work_id") or ""),
                json.dumps(
                    _normalize_search_queries_transport(item),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            ),
        )
        batch_limit = args.get("limit")
        batch_page = args.get("page")
        default_base_types = _tool_string_list(args.get("base_types"))
        default_collections = _tool_string_list(args.get("collections"))
        default_table_codes = _tool_string_list(args.get("table_codes"))
        grouped_queries: dict[
            tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]],
            list[str],
        ] = {}
        item_filters: dict[
            int,
            tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]],
        ] = {}
        scope_plans: dict[int, ModelScopePlan] = {}
        scope_errors: dict[int, str] = {}
        for index, item in enumerate(items):
            base_types = tuple(dict.fromkeys(
                _tool_string_list(item.get("base_types")) or default_base_types
            ))
            collections = tuple(dict.fromkeys(
                _tool_string_list(item.get("collections")) or default_collections
            ))
            table_codes = tuple(dict.fromkeys(
                re.sub(r"[^0-9-]", "", value).strip("-")[:9]
                for value in (
                    _tool_string_list(item.get("table_codes")) or default_table_codes
                )
                if re.sub(r"[^0-9-]", "", value).strip("-")
            ))
            queries = tuple(_normalize_search_queries_transport(item))
            raw_scope_mode = str(item.get("scope_mode") or "").strip()
            scope_mode = raw_scope_mode or ("scoped" if base_types or collections else "global")
            try:
                scope_plans[index] = ModelScopePlan(
                    work_id=str(item.get("work_id") or ""),
                    scope_mode=scope_mode,
                    queries=queries,
                    search_intents=(
                        str(item.get("search_intent") or item.get("intent") or "unspecified"),
                    ),
                    base_types=base_types,
                    collections=collections,
                    sections=tuple(dict.fromkeys(code[:5] for code in table_codes)),
                    table_codes=table_codes,
                    explicit_scope_mode=bool(raw_scope_mode),
                )
            except ValueError as error:
                scope_errors[index] = str(error)
                continue
            if self.require_scoped_search:
                if scope_mode != "scoped" or not base_types or not collections:
                    scope_errors[index] = (
                        "RIM search requires scope_mode=scoped with non-empty "
                        "base_types and collections selected by the model"
                    )
                    continue
                if len(base_types) != 1 or len(collections) != 1:
                    scope_errors[index] = (
                        "RIM search item must contain exactly one model-selected base_type "
                        "and one collection; use another item for another scope"
                    )
                    continue
                if not table_codes:
                    scope_errors[index] = (
                        "RIM search cannot jump from collection to norms; select one "
                        "section and one official table through browse_norm_catalog, "
                        "then pass its code in table_codes"
                    )
                    continue
                work_id = str(item.get("work_id") or "")
                selected_family = base_types[0].casefold()
                selected_collection = re.sub(
                    r"\D",
                    "",
                    collections[0],
                )[:2]
                missing_base_selections = [
                    base_type
                    for base_type in base_types
                    if base_type.casefold() not in self.selected_base_types.get(work_id, {})
                ]
                if missing_base_selections:
                    scope_errors[index] = (
                        "RIM scoped search requires an explicit model-owned base type "
                        "selection with reason and confidence for: "
                        + ", ".join(missing_base_selections)
                    )
                    continue
                missing_catalog_scopes = [
                    f"{base_type}:{collection}"
                    for base_type in base_types
                    for collection in collections
                    if (
                        base_type.casefold(),
                        re.sub(r"\D", "", collection)[:2],
                    ) not in self.selected_collections.get(work_id, set())
                ]
                if missing_catalog_scopes:
                    scope_errors[index] = (
                        "RIM scoped search requires explicit collection selection "
                        "through browse_norm_catalog first for: "
                        + ", ".join(missing_catalog_scopes)
                    )
                    continue
                missing_tables = [
                    f"{base_type}:{collection}:{table_code}"
                    for base_type in base_types
                    for collection in collections
                    for table_code in table_codes
                    if (
                        base_type.casefold(),
                        re.sub(r"\D", "", collection)[:2],
                        table_code,
                    ) not in self.selected_tables.get(work_id, set())
                ]
                if missing_tables:
                    scope_errors[index] = (
                        "RIM table search requires a table validated by "
                        "browse_norm_catalog inside the selected scope first for: "
                        + ", ".join(missing_tables)
                    )
                    continue
            filter_key = (base_types, collections, table_codes)
            item_filters[index] = filter_key
            grouped_queries.setdefault(filter_key, [])
            grouped_queries[filter_key].extend(queries)
        search_results_by_filter = {
            filter_key: browse_norms_many(
                _stable_unique_text(queries),
                limit=100,
                base_types=list(filter_key[0]),
                collections=list(filter_key[1]),
                table_codes=list(filter_key[2]),
                # RIM retrieval quality is a harness invariant, not a model
                # preference.  Table listings ignore ranking; every ordinary
                # shortlist reaches the configured reranker.
                rerank=True,
                # RIM search uses only the model-authored scope/query. Generic
                # retrieval vocabulary must not add hidden domain prose.
                expand_queries=False,
            )
            for filter_key, queries in grouped_queries.items()
            if queries
        }
        rows_out = []
        for index, item in enumerate(items):
            work_id = str(item.get("work_id") or "")
            if work_id not in self.by_id:
                rows_out.append({"work_id": work_id, "ok": False, "error": "unknown work_id"})
                continue
            if index in scope_errors:
                rows_out.append({
                    "work_id": work_id,
                    "ok": False,
                    "error": "invalid model scope plan",
                    "details": [scope_errors[index]],
                })
                continue
            queries = _normalize_search_queries_transport(item)
            requested_limit = max(1, int(item.get("limit") or batch_limit or self.candidate_limit))
            # A model may copy the catalog's finite-menu limit=100 into ranked
            # evidence search. Keep one page bounded; the model still owns
            # navigation and can request the next page explicitly.
            table_codes = item_filters[index][2]
            if table_codes:
                requested_limit = max(
                    requested_limit,
                    max(
                        (
                            len(result.get("cards") or [])
                            for result in (
                                search_results_by_filter.get(item_filters[index]) or {}
                            ).values()
                        ),
                        default=0,
                    ),
                )
            limit = (
                requested_limit
                if table_codes
                else min(requested_limit, self.candidate_limit)
            )
            page = max(0, int(item.get("page") if item.get("page") is not None else batch_page or 0))
            payload = _candidate_payload(
                self.by_id[work_id], queries, limit=limit, page=page,
                search_results=search_results_by_filter.get(item_filters[index]) or {},
            )
            base_types, collections, table_codes = item_filters[index]
            payload["filters"] = {
                "base_types": list(base_types),
                "collections": list(collections),
                "table_codes": list(table_codes),
            }
            self.browse_trace[work_id].append(payload)
            compact = []
            for card in payload.get("candidates") or []:
                code = str(card.get("norm_code") or "")
                self.candidates[work_id][code] = card
                compact.append({
                    "norm_code": code,
                    "norm_key": str(card.get("norm_key") or ""),
                    "edition": str(card.get("edition") or ""),
                    "base_type": str(card.get("base_type") or ""),
                    "collection": str(card.get("collection") or _norm_collection(code)),
                    "title": str(card.get("title") or "")[:180],
                    "measure_unit": card.get("measure_unit"),
                    "unit_compatible": bool(card.get("unit_compatible", True)),
                    "source_ref": str(card.get("source_ref") or "")[:280],
                    "work_steps": [str(step)[:160] for step in (card.get("work_steps") or [])[:3]],
                    "resource_count": int(card.get("resource_count") or 0),
                    "resource_kinds": dict(card.get("resource_kinds") or {}),
                    "resource_preview": [
                        {
                            "kind": str(value.get("kind") or ""),
                            "code": str(value.get("code") or ""),
                            "name": str(value.get("name") or "")[:120],
                            "unit": str(value.get("unit") or ""),
                        }
                        for value in (card.get("resource_preview") or [])[:6]
                        if isinstance(value, dict)
                    ],
                    "matched_query": str(card.get("matched_query") or "")[:240],
                    "questions_to_ask": _questions_to_ask_for_norm(code),
                })
            search_intent = str(item.get("search_intent") or item.get("intent") or "unspecified")
            scope_plan = scope_plans[index].as_dict()
            rows_out.append({
                "work_id": work_id, "ok": True, "candidates": compact,
                "page": page, "has_more": bool(payload.get("has_more")),
                "requested_limit": requested_limit,
                "page_size": limit,
                "queries": queries,
                "search_intent": search_intent,
                "scope_plan": scope_plan,
                "filters": payload["filters"],
                "retrieval_backend": str(payload.get("backend") or ""),
                "retrieval_policy": str(payload.get("retrieval_policy") or ""),
                "rerank_status": list(payload.get("rerank_status") or []),
                "reranked": bool(payload.get("reranked")),
                "next_action": (
                    "choose at most two current candidate codes and call "
                    "read_norms_batch"
                    if compact
                    else "use a distinct model-authored search formulation"
                ),
            })
            self.query_trace.append({
                "phase": "batch_search", "turn": turn, "work_id": work_id,
                "queries": queries,
                "search_intents": [search_intent],
                "candidate_count": len(compact), "page": page,
                "requested_limit": requested_limit, "page_size": limit,
                "candidate_codes": [str(card.get("norm_code") or "") for card in compact],
                "scope_plan": scope_plan,
                "filters": payload["filters"],
                "retrieval_policy": str(payload.get("retrieval_policy") or ""),
                "rerank_status": list(payload.get("rerank_status") or []),
                "reranked": bool(payload.get("reranked")),
            })
        result: dict[str, Any] = {
            "ok": any(row.get("ok") is True for row in rows_out),
            "rows": rows_out,
        }
        if not items:
            result["error"] = "search items are empty or malformed"
        return result

    def _read(self, args: dict[str, Any]) -> dict[str, Any]:
        rows_out = []
        for item in _tool_array_argument(args, "items"):
            work_id = str(item.get("work_id") or "")
            cards = []
            include_resources = _tool_bool(item.get("include_resources"), False)
            available = self.candidates.get(work_id, {})
            for requested_code in _normalize_norm_codes_transport(item):
                code = _resolve_norm_code_transport(requested_code, available)
                candidate = available.get(code)
                card = _opened_norm_card(code, candidate) if candidate else None
                if card:
                    self.opened[work_id][code] = card
                    self.opened[work_id][requested_code] = card
                    cards.append(_norm_card_for_model(card, include_resources=include_resources))
            rows_out.append({"work_id": work_id, "ok": bool(cards), "norms": cards})
        result: dict[str, Any] = {
            "ok": any(row.get("ok") is True for row in rows_out),
            "rows": rows_out,
        }
        if not rows_out:
            result["error"] = "read items are empty or malformed"
        return result

    def _submit(self, args: dict[str, Any]) -> dict[str, Any]:
        rows = [
            _normalize_mapping_row_transport(item)
            for item in _tool_array_argument(args, "rows", aliases=("mapping",))
        ]
        proposed: dict[str, dict[str, Any]] = {}
        errors: list[dict[str, Any]] = []
        for item in rows:
            raw_model_item = copy.deepcopy(item)
            work_id = str(item.get("work_id") or "")
            if work_id not in self.by_id or work_id in proposed or work_id in self.accepted_rows:
                errors.append({"work_id": work_id, "error": "unknown or duplicate work_id"})
                continue
            resolve_extracted_norm_code_flexible(item, by_id=self.by_id, opened_cards=self.opened)
            resolver_trace = dict(item.pop("_les_flexible_interpretation", {}) or {})
            decision = str(item.get("decision") or "")
            if decision == "unbound":
                reason = str(item.get("reason") or "").strip()
                if (
                    resolver_trace.get("matched_opened_codes")
                    and resolver_trace.get("reason_suggests_positive_applicability") is True
                ):
                    errors.append({
                        "work_id": work_id,
                        "error": "unbound decision conflicts with the model's positive norm reference",
                        "details": [
                            "The prose says that an already opened typed card is applicable, "
                            "but decision=unbound. Confirm bind/covered_by/unbound explicitly; "
                            "LES will preserve the corrected model decision."
                        ],
                        "resolver_hint": resolver_trace,
                    })
                    continue
                evidence = self._align_unbound_evidence_to_trace(
                    work_id,
                    dict(item.get("unbound_evidence") or {}),
                )
                evidence_errors = self._unbound_evidence_errors(
                    work_id,
                    reason=reason,
                    evidence=evidence,
                )
                unbound_attempt_key = f"unbound:{work_id}"
                # Soft evidence gaps after real search/read used to force a second
                # 5–40s structured mapping call. Accept those as candidate once.
                # Zero-search catalog unbound must NOT close the row — that caused
                # mass "без нормы" on demo runs (vor-0001/5/6/7).
                hard_unbound_markers = (
                    "unbound is not terminal because",
                    "unbound decision conflicts with",
                    "cites norm cards not opened",
                    "collections without an opened typed card",
                    "opened_norm_codes contains cards not opened",
                )
                soft_evidence_gap = bool(evidence_errors) and not any(
                    any(marker in str(error) for marker in hard_unbound_markers)
                    for error in evidence_errors
                )
                has_tool_evidence = bool(self.opened.get(work_id)) or any(
                    str(trace.get("work_id") or "") == work_id
                    for trace in self.query_trace
                )
                prior_unbound_attempt = int(
                    self.candidate_draft_attempts.get(unbound_attempt_key, 0)
                )
                # With search/read: accept soft gap immediately (no second mapping).
                # Without tool evidence: require one prior reject so catalog-only
                # unbound cannot close the row on the first forced mapping.
                accept_unbound_candidate = (
                    _candidate_draft_enabled()
                    and bool(reason)
                    and soft_evidence_gap
                    and (has_tool_evidence or prior_unbound_attempt >= 1)
                )
                if evidence_errors and not accept_unbound_candidate:
                    if _candidate_draft_enabled() and reason:
                        self.candidate_draft_attempts[unbound_attempt_key] = (
                            prior_unbound_attempt + 1
                        )
                    errors.append({
                        "work_id": work_id,
                        "error": "invalid unbound_evidence",
                        "details": evidence_errors,
                        "allowed_evidence": self._allowed_unbound_evidence(work_id),
                        "candidate_codes_available": list(dict.fromkeys(
                            str((card or {}).get("norm_code") or code)
                            for code, card in self.candidates.get(work_id, {}).items()
                            if str((card or {}).get("norm_code") or code).strip()
                        ))[:12],
                    })
                    continue
                if accept_unbound_candidate:
                    self.candidate_draft_attempts[unbound_attempt_key] = max(
                        1,
                        int(self.candidate_draft_attempts.get(unbound_attempt_key, 0)),
                    )
                    proposed[work_id] = {
                        "norm_code": "",
                        "selection_kind": str(item.get("selection_kind") or ""),
                        "analog_limitations": list(item.get("analog_limitations") or []),
                        "reason": reason,
                        # Only real trajectory-aligned evidence survives. Missing
                        # searches stay missing and visible in the blocker below.
                        "unbound_evidence": evidence,
                        "review_status": "model_batch_candidate",
                        "candidate_validation_errors": list(evidence_errors),
                        "resource_bindings": [],
                        "precalculation_blockers": [{
                            "code": "model_candidate_unbound",
                            "work_id": work_id,
                            "reason": "; ".join(evidence_errors),
                            "severity": "warning",
                            "memory_eligible": False,
                        }],
                        "resolver_trace": resolver_trace,
                        "model_mapping_raw": raw_model_item,
                    }
                    continue
                proposed[work_id] = {
                    "norm_code": "",
                    "selection_kind": str(item.get("selection_kind") or ""),
                    "analog_limitations": list(item.get("analog_limitations") or []),
                    "reason": reason,
                    "unbound_evidence": evidence,
                    "review_status": "model_batch_unbound", "resource_bindings": [],
                    "resolver_trace": resolver_trace,
                    "model_mapping_raw": raw_model_item,
                }
                continue
            if decision == "covered_by":
                covered_by = str(item.get("covered_by_work_id") or "")
                reason = str(item.get("reason") or "").strip()
                if not covered_by or covered_by == work_id or covered_by not in self.by_id:
                    errors.append({
                        "work_id": work_id,
                        "error": "covered_by requires another existing source work_id",
                        "details": [
                            "Do not point a row to itself. If the prose names an opened norm, "
                            "confirm bind and provide its technology check; otherwise choose "
                            "a real neighboring work_id or unbound."
                        ],
                        "resolver_hint": resolver_trace,
                    })
                    continue
                proposed[work_id] = {
                    "norm_code": "",
                    "selection_kind": str(item.get("selection_kind") or ""),
                    "analog_limitations": list(item.get("analog_limitations") or []),
                    "covered_by_work_id": covered_by,
                    "coverage_reason": reason,
                    "reason": reason,
                    "review_status": "model_batch_covered", "resource_bindings": [],
                    "resolver_trace": resolver_trace,
                    "model_mapping_raw": raw_model_item,
                }
                continue
            if decision != "bind":
                errors.append({"work_id": work_id, "error": "decision must be bind|covered_by|unbound"})
                continue
            requested_code = str(item.get("norm_code") or "")
            opened_for_work = self.opened.get(work_id, {})
            opened_code = _resolve_norm_code_transport(requested_code, opened_for_work)
            opened_card = opened_for_work.get(opened_code) if opened_code else None
            bind_errors = _technology_check_errors(item, work_id=work_id)
            bind_errors.extend(_candidate_evaluation_errors(
                item,
                candidates_for_work=self.candidates.get(work_id, {}),
                opened_for_work=opened_for_work,
                source_work=self.by_id.get(work_id),
            ))
            if not str(item.get("reason") or "").strip():
                bind_errors.append("reason is required")
            bind_errors.extend(_exact_bind_reason_self_contradiction_errors(item))
            if (
                self.require_scoped_search
                and opened_card is not None
                and not units_compatible(
                    str(self.by_id[work_id].get("unit") or ""),
                    str(opened_card.get("measure_unit") or ""),
                )
            ):
                bind_errors.append(
                    "selected typed card unit is incompatible with the source work unit"
                )
            candidate_validation_errors: list[str] = []
            # Self-contradicting exact binds are never draft-eligible: a repeated
            # "не применима" reason must not become model_batch_candidate.
            semantic_draft_errors = (
                _candidate_draft_errors(bind_errors)
                and not any(
                    "denies applicability" in str(error)
                    for error in bind_errors
                )
            )
            accept_as_candidate = (
                _candidate_draft_enabled()
                and opened_card is not None
                and self.candidate_draft_attempts.get(work_id, 0) >= 1
                and semantic_draft_errors
            )
            if bind_errors and not accept_as_candidate:
                if _candidate_draft_enabled() and opened_card is not None and semantic_draft_errors:
                    self.candidate_draft_attempts[work_id] = (
                        self.candidate_draft_attempts.get(work_id, 0) + 1
                    )
                errors.append({
                    "work_id": work_id,
                    "error": "incomplete bind evidence",
                    "details": bind_errors,
                    "comparison_candidate_codes": list(dict.fromkeys(
                        str((card or {}).get("norm_code") or code)
                        for code, card in self.candidates.get(work_id, {}).items()
                        if str((card or {}).get("norm_code") or code).strip()
                    ))[:12],
                })
                continue
            if accept_as_candidate:
                candidate_validation_errors = list(bind_errors)
            code = str((opened_card or {}).get("norm_code") or requested_code)
            if self.require_scoped_search and opened_card is None:
                errors.append({
                    "work_id": work_id,
                    "error": "RIM bind requires a typed card opened by read_norms_batch",
                    "details": [
                        (
                            f"norm_code {requested_code!r} is not present in the opened "
                            "structured cards for this work_id"
                        ),
                        (
                            "call browse_norm_catalog, scoped search_norms_batch and "
                            "read_norms_batch before resubmitting this bind"
                        ),
                    ],
                    "comparison_candidate_codes": list(dict.fromkeys(
                        str((card or {}).get("norm_code") or candidate_code)
                        for candidate_code, card in self.candidates.get(work_id, {}).items()
                        if str((card or {}).get("norm_code") or candidate_code).strip()
                    ))[:12],
                })
                continue
            blockers = []
            if candidate_validation_errors:
                blockers.append({
                    "code": "model_candidate_mapping",
                    "work_id": work_id,
                    "reason": "; ".join(candidate_validation_errors),
                    "severity": "warning",
                    "memory_eligible": False,
                })
            if code and opened_card is None:
                blockers.append({
                    "code": "norm_card_not_opened", "work_id": work_id,
                    "reason": "model submitted a norm without opening its typed card",
                })
            if not code:
                blockers.append({
                    "code": "model_mapping_missing_norm_code", "work_id": work_id,
                    "reason": "model submitted bind without norm_code",
                })
            proposed[work_id] = {
                "norm_code": code,
                "selection_kind": str(item.get("selection_kind") or ""),
                "applicability": str(item.get("applicability") or ""),
                "technology_check": dict(item.get("technology_check") or {}),
                "candidate_evaluations": [
                    dict(evaluation)
                    for evaluation in (item.get("candidate_evaluations") or [])
                    if isinstance(evaluation, dict)
                ],
                "analog_limitations": [
                    str(value) for value in (item.get("analog_limitations") or []) if str(value).strip()
                ],
                "nr_sp_rule_id": str(item.get("nr_sp_rule_id") or ""),
                "reason": str(item.get("reason") or ""),
                "review_status": (
                    "model_batch_candidate"
                    if candidate_validation_errors
                    else "model_batch"
                ),
                "candidate_validation_errors": candidate_validation_errors,
                "resource_bindings": _model_resource_bindings(work_id, item, self.by_id[work_id]),
                "precalculation_blockers": blockers,
                "resolver_trace": resolver_trace,
                "model_mapping_raw": raw_model_item,
            }
        for work_id, selection in proposed.items():
            self.accepted_rows[work_id] = selection
            if (
                str(selection.get("norm_code") or "").strip()
                and str(selection.get("review_status") or "") != "model_batch_candidate"
            ):
                self._cache_bound_route(work_id)
            else:
                # Unbound/covered_by/candidate must not seed reuse for other rows.
                self._drop_routes_for_work(work_id)
            if self.decision_checkpoint is not None:
                self.decision_checkpoint(work_id, copy.deepcopy(selection))
        if self.progress:
            for work_id, selection in proposed.items():
                source = self.by_id[work_id]
                norm_code = str(selection.get("norm_code") or "")
                covered_by = str(selection.get("covered_by_work_id") or "")
                decision = "bind" if norm_code else "covered_by" if covered_by else "unbound"
                if norm_code:
                    decision_label = "Норма выбрана"
                elif covered_by:
                    decision_label = f"Покрыто строкой {covered_by}"
                else:
                    decision_label = "Оставлено без нормы"
                self.progress({
                    "phase": "row_ready",
                    "status": "done",
                    "label": f"Смета: строка {work_id} готова — {decision_label.lower()}",
                    "row": {
                        "work_id": work_id,
                        "title": str(source.get("title") or "")[:320],
                        "unit": str(source.get("unit") or "")[:80],
                        "quantity": source.get("quantity"),
                        "section": str(source.get("section") or "")[:160],
                        "decision": decision,
                        "decision_label": decision_label,
                        "norm_code": norm_code,
                        "covered_by_work_id": covered_by,
                        "reason": str(selection.get("reason") or "")[:500],
                    },
                })
        remaining = self.remaining_work_ids
        if not proposed and not errors:
            errors.append({"error": "submit rows is empty", "work_ids": remaining})
        if errors:
            failed_keys = {
                str(error.get("work_id") or "__transport__")
                if str(error.get("work_id") or "") in self.by_id else "__transport__"
                for error in errors
            }
            for failed_key in failed_keys:
                self.invalid_submission_attempts[failed_key] = (
                    self.invalid_submission_attempts.get(failed_key, 0) + 1
                )
            attempt = max(self.invalid_submission_attempts.values(), default=1)
            if self.progress:
                first_error = str((errors[0] or {}).get("error") or "некорректный mapping")
                self.progress({
                    "phase": "mapping_retry", "status": "waiting",
                    "label": f"Смета: модель исправляет решение — {first_error}",
                    "attempt": attempt, "errors": errors[:5],
                })
            return {
                "ok": False, "errors": errors,
                "accepted_work_ids": list(self.accepted_rows),
                "remaining_work_ids": remaining,
            }
        if remaining:
            return {
                "ok": True, "complete": False,
                "accepted_work_ids": list(self.accepted_rows),
                "remaining_work_ids": remaining,
            }
        return {"ok": True, "rows": len(self.accepted_rows)}

    def _allowed_unbound_evidence(self, work_id: str) -> dict[str, Any]:
        queries = list(dict.fromkeys(
            str(query).strip()
            for trace in self.query_trace
            if str(trace.get("work_id") or "") == work_id
            for query in (trace.get("queries") or [])
            if str(query).strip()
        ))
        opened_codes = list(dict.fromkeys(
            str((card or {}).get("norm_code") or code).strip()
            for code, card in self.opened.get(work_id, {}).items()
            if str((card or {}).get("norm_code") or code).strip()
        ))
        return {
            "queries_used": queries,
            "opened_norm_codes": opened_codes,
            "catalog_route_evidence": copy.deepcopy(
                (
                    self.catalog_terminal_decisions.get(work_id) or {}
                ).get("evidence")
                or []
            ),
        }

    def _align_unbound_evidence_to_trace(
        self,
        work_id: str,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        """Normalize provenance to real tool calls without creating model evidence."""
        allowed = self._allowed_unbound_evidence(work_id)
        executed_queries = [
            str(value).strip()
            for value in (allowed.get("queries_used") or [])
            if str(value).strip()
        ]
        query_by_key = {value.casefold(): value for value in executed_queries}
        submitted_queries = [
            str(value).strip()
            for value in (evidence.get("queries_used") or [])
            if str(value).strip()
        ]
        aligned_queries = list(dict.fromkeys(
            query_by_key[value.casefold()]
            for value in submitted_queries
            if value.casefold() in query_by_key
        ))

        opened_codes = [
            str(value).strip()
            for value in (allowed.get("opened_norm_codes") or [])
            if str(value).strip()
        ]
        opened_by_key = {value.casefold(): value for value in opened_codes}
        submitted_opened = [
            str(value).strip()
            for value in (evidence.get("opened_norm_codes") or [])
            if str(value).strip()
        ]
        aligned_opened = list(dict.fromkeys(
            opened_by_key[value.casefold()]
            for value in submitted_opened
            if value.casefold() in opened_by_key
        ))

        aligned = dict(evidence)
        if len({value.casefold() for value in aligned_queries}) >= 2:
            aligned["queries_used"] = aligned_queries
        elif len({value.casefold() for value in executed_queries}) >= 2:
            aligned["queries_used"] = executed_queries
        else:
            aligned["queries_used"] = aligned_queries
        if aligned_opened:
            aligned["opened_norm_codes"] = aligned_opened
        elif opened_codes:
            aligned["opened_norm_codes"] = opened_codes
        else:
            aligned["opened_norm_codes"] = []
        route_decision = self.catalog_terminal_decisions.get(work_id)
        if route_decision:
            aligned["catalog_route_evidence"] = copy.deepcopy(
                route_decision.get("evidence") or []
            )
            aligned["catalog_route_node_id"] = str(
                route_decision.get("current_node_id") or ""
            )
        return aligned

    def _unbound_evidence_errors(
        self,
        work_id: str,
        *,
        reason: str,
        evidence: dict[str, Any],
    ) -> list[str]:
        """Validate evidence provenance without judging the model's conclusion."""
        errors: list[str] = []
        queries = [
            str(value).strip()
            for value in (evidence.get("queries_used") or [])
            if str(value).strip()
        ]
        unique_queries = {value.casefold() for value in queries}
        executed_queries = {
            str(query).strip().casefold()
            for trace in self.query_trace
            if str(trace.get("work_id") or "") == work_id
            for query in (trace.get("queries") or [])
            if str(query).strip()
        }
        executed_search_signatures = {
            (
                tuple(
                    str(query).strip().casefold()
                    for query in (trace.get("queries") or [])
                    if str(query).strip()
                ),
                tuple(
                    str(value).strip().casefold()
                    for value in (
                        (trace.get("filters") or {}).get("base_types") or []
                    )
                    if str(value).strip()
                ),
                tuple(
                    str(value).strip()
                    for value in (
                        (trace.get("filters") or {}).get("collections") or []
                    )
                    if str(value).strip()
                ),
                tuple(
                    str(value).strip()
                    for value in (
                        (trace.get("filters") or {}).get("table_codes") or []
                    )
                    if str(value).strip()
                ),
            )
            for trace in self.query_trace
            if str(trace.get("work_id") or "") == work_id
        }
        opened_codes = [
            str(value).strip()
            for value in (evidence.get("opened_norm_codes") or [])
            if str(value).strip()
        ]
        actually_opened = {
            str((card or {}).get("norm_code") or code).strip()
            for code, card in self.opened.get(work_id, {}).items()
            if str((card or {}).get("norm_code") or code).strip()
        }
        rejection_reasons = [
            str(value).strip()
            for value in (evidence.get("rejection_reasons") or [])
            if str(value).strip()
        ]
        coverage_checked = str(evidence.get("coverage_checked") or "").strip()
        decision_text = " ".join(
            [reason, coverage_checked, *rejection_reasons]
        )
        catalog_route_evidence = [
            value
            for value in (evidence.get("catalog_route_evidence") or [])
            if isinstance(value, dict)
        ]
        has_valid_catalog_terminal = bool(
            self.catalog_terminal_decisions.get(work_id)
            and catalog_route_evidence
        )

        if not reason:
            errors.append("reason is required")
        if re.search(
            r"\b(?:требуется|необходимо|нужно|следует)\s+"
            r"(?:[\w-]+\s+){0,4}"
            r"(?:поиск\w*|искать|провер\w*|откры\w*|уточн\w*)\b",
            decision_text,
            flags=re.IGNORECASE,
        ):
            errors.append(
                "unbound is not terminal because its own text requires more evidence work"
            )
        if (
            not has_valid_catalog_terminal
            and not actually_opened
            and len(unique_queries) < 2
            and len(executed_search_signatures) < 2
        ):
            errors.append(
                "unbound requires at least two distinct query or scoped-search strategies"
            )
        missing_queries = sorted(value for value in unique_queries if value not in executed_queries)
        if missing_queries:
            errors.append("queries_used contains searches absent from the tool trace: " + ", ".join(missing_queries))
        unopened_codes = sorted(code for code in opened_codes if code not in actually_opened)
        if unopened_codes:
            errors.append("opened_norm_codes contains cards not opened through tools: " + ", ".join(unopened_codes))
        def compact_ref(value: object) -> str:
            return re.sub(
                r"[^а-яёa-z0-9]+",
                "",
                str(value or "").casefold(),
            )

        opened_ref_keys = {
            compact_ref((card or {}).get("norm_code") or code)
            for code, card in self.opened.get(work_id, {}).items()
            if compact_ref((card or {}).get("norm_code") or code)
        }
        cited_norms = list(dict.fromkeys(
            match.group(0).strip()
            for match in re.finditer(
                r"\bГЭСН[мрп]*\s*:?\s*\d{2}-\d{2}-\d{3}(?:-\d{2})?",
                decision_text,
                flags=re.IGNORECASE,
            )
        ))
        unsupported_norms = [
            cited
            for cited in cited_norms
            if not any(
                opened.startswith(compact_ref(cited))
                or compact_ref(cited).startswith(opened)
                for opened in opened_ref_keys
            )
        ]
        if unsupported_norms:
            errors.append(
                "unbound reasoning cites norm cards not opened through read_norms_batch: "
                + ", ".join(unsupported_norms)
            )
        opened_collections = {
            str((card or {}).get("collection") or "").zfill(2)
            for card in self.opened.get(work_id, {}).values()
            if str((card or {}).get("collection") or "").strip()
        }
        cited_collections = {
            match.group(1).zfill(2)
            for match in re.finditer(
                r"\bсборник\w*\s+(\d{1,2})\b",
                decision_text,
                flags=re.IGNORECASE,
            )
        }
        unsupported_collections = sorted(cited_collections - opened_collections)
        if unsupported_collections:
            errors.append(
                "unbound reasoning cites collections without an opened typed card: "
                + ", ".join(unsupported_collections)
            )
        available_candidates = {
            str((card or {}).get("norm_code") or code).strip()
            for code, card in self.candidates.get(work_id, {}).items()
            if str((card or {}).get("norm_code") or code).strip()
        }
        if (
            not has_valid_catalog_terminal
            and available_candidates
            and not opened_codes
        ):
            errors.append(
                "opened_norm_codes must include a read_norms_batch card when search returned candidates"
            )
        if not rejection_reasons:
            errors.append("rejection_reasons must contain at least one model reason")
        if not coverage_checked:
            errors.append("coverage_checked is required")
        return errors

    def result(
        self,
        *,
        model_trace: list[dict[str, Any]],
        agent_trace: dict[str, Any],
        allow_incomplete: bool = False,
        incomplete_blocker: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.complete and not allow_incomplete:
            raise RuntimeError(
                "smeta agent ended without terminal mapping for: "
                + ",".join(self.remaining_work_ids)
            )
        return {
            "selections": dict(self.accepted_rows),
            "browse_trace": self.browse_trace,
            "query_trace": self.query_trace,
            "catalog_trace": self.catalog_trace,
            "model_trace": model_trace,
            "valid_model_rows": len(self.accepted_rows),
            "incomplete": not self.complete,
            "remaining_work_ids": self.remaining_work_ids,
            "incomplete_blocker": dict(incomplete_blocker or {}),
            "opened_cards": {
                work_id: list({str(card.get("norm_code") or key): card for key, card in cards.items()}.values())
                for work_id, cards in self.opened.items()
            },
            "agent_trace": {
                **agent_trace,
                "validation_contract_version": MAPPING_VALIDATION_CONTRACT_VERSION,
                "tool_trajectory": self.tool_trajectory,
                "evidence_budget": asdict(self.evidence_budget),
                "evidence_usage": dict(self.evidence_usage),
            },
            "route_evidence_cache": self._completed_route_cache(),
        }

    def _route_payload_for_work(self, work_id: str) -> list[dict[str, Any]]:
        """Build compact route evidence from the work's selected table path."""
        routes: list[dict[str, Any]] = []
        tables = sorted(self.selected_tables.get(work_id) or set())
        sections = sorted(self.selected_sections.get(work_id) or set())
        for family, collection, table_code in tables:
            section = next(
                (
                    value
                    for section_family, section_collection, value in sections
                    if section_family == family
                    and section_collection == collection
                ),
                table_code[:5],
            )
            family_label = str(family)
            for base in (self.selected_base_types.get(work_id) or {}).values():
                if str(base.get("family") or "").casefold() == family.casefold():
                    family_label = str(base.get("family") or family)
                    break
            routes.append({
                "cache_id": (
                    f"route:{family.casefold()}:{collection}:"
                    f"{section}:{table_code}"
                ),
                "source_work_id": work_id,
                "family": family_label,
                "collection": collection,
                "section": section,
                "table_code": table_code,
                "source": "typed_catalog_trace",
                "decision_owner": "model",
                "applicability": "not_decided_for_other_rows",
            })
        return routes

    def _cache_bound_route(self, work_id: str) -> None:
        """Publish a route only after a successful model bind."""
        for route in self._route_payload_for_work(work_id):
            cache_id = str(route.get("cache_id") or "")
            if cache_id:
                self.route_evidence_cache[cache_id] = route

    def _drop_routes_for_work(self, work_id: str) -> None:
        """Remove cache entries sourced by a work that did not bind."""
        drop_ids = [
            cache_id
            for cache_id, route in self.route_evidence_cache.items()
            if str(route.get("source_work_id") or "") == work_id
        ]
        for cache_id in drop_ids:
            self.route_evidence_cache.pop(cache_id, None)

    def _completed_route_cache(self) -> list[dict[str, Any]]:
        """Expose only bind-proven table routes as reusable evidence."""
        routes: list[dict[str, Any]] = []
        seen: set[str] = set()
        bound_work_ids = {
            work_id
            for work_id, selection in self.accepted_rows.items()
            if str(selection.get("norm_code") or "").strip()
            and str(selection.get("review_status") or "") != "model_batch_candidate"
        }
        for work_id in bound_work_ids:
            for route in self._route_payload_for_work(work_id):
                cache_id = str(route.get("cache_id") or "")
                if not cache_id or cache_id in seen:
                    continue
                seen.add(cache_id)
                routes.append(route)
        for cache_id, route in self.route_evidence_cache.items():
            source = str(route.get("source_work_id") or "")
            if source and source not in bound_work_ids:
                continue
            if cache_id in seen:
                continue
            seen.add(cache_id)
            routes.append(copy.deepcopy(route))
        return routes


def _run_native_norm_agent(
    work_rows: list[dict[str, Any]],
    exchange: Exchange,
    *,
    mapping_exchange: MappingExchange | None = None,
    candidate_limit: int,
    max_turns: int = 64,
    batch_size: int = 0,
    progress: Progress | None = None,
    user_request: str = "",
    batch_runner: AgentBatchRunner | None = None,
    accumulate_task_state: bool = False,
    resume_result: dict[str, Any] | None = None,
    checkpoint: Checkpoint | None = None,
    require_scoped_search: bool = False,
) -> dict[str, Any]:
    """Give the model the source rows and merge its untouched decisions."""
    requested_size = int(batch_size)
    size = len(work_rows) if requested_size <= 0 else max(1, requested_size)
    resumed = dict(resume_result or {})
    resumed_selections = dict(resumed.get("selections") or {})
    ordered_work_ids = [str(row["work_id"]) for row in work_rows]
    known_work_ids = set(ordered_work_ids)
    unknown_resumed = sorted(set(resumed_selections) - known_work_ids)
    if unknown_resumed:
        raise RuntimeError(
            f"resume checkpoint contains unknown work_ids: {unknown_resumed}"
        )
    pending_rows = [
        row for row in work_rows
        if str(row["work_id"]) not in resumed_selections
    ]
    if not pending_rows:
        return {
            **resumed,
            "valid_model_rows": len(resumed_selections),
            "incomplete": False,
            "remaining_work_ids": [],
            "incomplete_blocker": {},
        }
    batches = [
        pending_rows[index:index + size]
        for index in range(0, len(pending_rows), size)
    ]
    if len(batches) <= 1 and not resumed_selections and checkpoint is None:
        task_rows = work_rows
        if accumulate_task_state:
            task_rows = [
                {
                    **row,
                    "task_state": {
                        "mode": "sequential_rows",
                        "source_rows_total": len(work_rows),
                        "completed_rows": 0,
                        "remaining_rows": len(work_rows),
                        "completed_decisions": [],
                    },
                }
                for row in work_rows
            ]
        if batch_runner is not None:
            return batch_runner(
                task_rows,
                candidate_limit=candidate_limit,
                max_turns=max_turns,
                progress=progress,
                user_request=user_request,
            )
        return _run_batch_norm_agent(
            task_rows,
            exchange,
            mapping_exchange=mapping_exchange,
            candidate_limit=candidate_limit,
            max_turns=max_turns,
            progress=progress,
            user_request=user_request,
            require_scoped_search=require_scoped_search,
        )

    merged = {
        "selections": dict(resumed_selections),
        "opened_cards": dict(resumed.get("opened_cards") or {}),
        "browse_trace": dict(resumed.get("browse_trace") or {}),
        "query_trace": list(resumed.get("query_trace") or []),
        "catalog_trace": list(resumed.get("catalog_trace") or []),
        "model_trace": list(resumed.get("model_trace") or []),
        "valid_model_rows": len(resumed_selections),
        "incomplete": True,
        "remaining_work_ids": [
            str(row["work_id"]) for row in pending_rows
        ],
        "incomplete_blocker": {},
        "route_evidence_cache": list(
            resumed.get("route_evidence_cache") or []
        ),
    }
    batch_traces: list[dict[str, Any]] = list(
        ((resumed.get("agent_trace") or {}).get("batch_traces") or [])
    )
    batches_started = perf_counter()
    source_by_id = {str(row["work_id"]): row for row in work_rows}
    for batch_index, rows in enumerate(batches, 1):
        batch_resume_checkpoint = None
        if batch_index == 1 and isinstance(resumed.get("resume_state"), dict):
            resume_tool_session = dict(
                resumed["resume_state"].get("tool_session") or {}
            )
            expected_fingerprint = SmetaNormToolSession(
                rows,
                candidate_limit=candidate_limit,
                require_scoped_search=require_scoped_search,
            ).work_fingerprint()
            if (
                str(resume_tool_session.get("work_fingerprint") or "")
                == expected_fingerprint
            ):
                batch_resume_checkpoint = resumed
        if progress:
            rows_done = int(merged["valid_model_rows"])
            elapsed_sec = round(max(0.0, perf_counter() - batches_started), 1)
            sec_per_row = (
                round(elapsed_sec / rows_done, 1) if rows_done > 0 else None
            )
            pace_suffix = (
                f" (~{sec_per_row} с/поз)" if sec_per_row is not None else ""
            )
            progress({
                "phase": "source_batch",
                "status": "started",
                "label": (
                    f"Смета: обрабатываю строки "
                    f"{rows_done + 1}–{rows_done + len(rows)} из {len(work_rows)}"
                    f"{pace_suffix}"
                ),
                "batch": batch_index,
                "batches": len(batches),
                "completed_rows": rows_done,
                "rows_done": rows_done,
                "total_rows": len(work_rows),
                "elapsed_sec": elapsed_sec,
                "sec_per_row": sec_per_row,
            })
        task_rows = [
            {
                **row,
                **(
                    {
                        "route_evidence_cache": copy.deepcopy(
                            merged["route_evidence_cache"]
                        )
                    }
                    if merged["route_evidence_cache"]
                    else {}
                ),
            }
            for row in rows
        ]
        if accumulate_task_state:
            completed_decisions = []
            for completed_work_id, selection in merged["selections"].items():
                source = source_by_id.get(str(completed_work_id)) or {}
                completed_decisions.append({
                    "work_id": completed_work_id,
                    "title": str(source.get("title") or "")[:240],
                    "norm_code": str(selection.get("norm_code") or ""),
                    "covered_by_work_id": str(selection.get("covered_by_work_id") or ""),
                    "decision": (
                        "bind" if selection.get("norm_code") else
                        "covered_by" if selection.get("covered_by_work_id") else
                        "unbound"
                    ),
                    "reason": str(selection.get("reason") or "")[:320],
                })
            task_state = {
                "mode": "sequential_rows",
                "source_rows_total": len(work_rows),
                "completed_rows": len(completed_decisions),
                "remaining_rows": len(work_rows) - len(completed_decisions),
                "completed_decisions": completed_decisions,
                "instruction": (
                    "Use completed decisions only as task memory for coverage and duplicate checks. "
                    "Do not revise them or call tools for their work_id in this row loop."
                ),
            }
            task_rows = [
                {
                    **row,
                    "task_state": task_state,
                    **(
                        {
                            "route_evidence_cache": copy.deepcopy(
                                merged["route_evidence_cache"]
                            )
                        }
                        if merged["route_evidence_cache"]
                        else {}
                    ),
                }
                for row in rows
            ]
        try:
            if batch_runner is not None:
                result = batch_runner(
                    task_rows,
                    candidate_limit=candidate_limit,
                    max_turns=max_turns,
                    progress=progress,
                    user_request=user_request,
                )
            else:
                def batch_checkpoint(partial: dict[str, Any]) -> None:
                    if checkpoint is None:
                        return
                    checkpoint(copy.deepcopy({
                        **merged,
                        "selections": {
                            **merged["selections"],
                            **dict(partial.get("selections") or {}),
                        },
                        "opened_cards": {
                            **merged["opened_cards"],
                            **dict(partial.get("opened_cards") or {}),
                        },
                        "browse_trace": {
                            **merged["browse_trace"],
                            **dict(partial.get("browse_trace") or {}),
                        },
                        "query_trace": [
                            *merged["query_trace"],
                            *list(partial.get("query_trace") or []),
                        ],
                        "catalog_trace": [
                            *merged["catalog_trace"],
                            *list(partial.get("catalog_trace") or []),
                        ],
                        "model_trace": [
                            *merged["model_trace"],
                            *[
                                {**item, "source_batch": batch_index}
                                for item in (partial.get("model_trace") or [])
                            ],
                        ],
                        "valid_model_rows": (
                            len(merged["selections"])
                            + len(partial.get("selections") or {})
                        ),
                        "incomplete": True,
                        "remaining_work_ids": [
                            work_id
                            for work_id in ordered_work_ids
                            if work_id not in merged["selections"]
                            and work_id not in (partial.get("selections") or {})
                        ],
                        "incomplete_blocker": dict(
                            partial.get("incomplete_blocker") or {}
                        ),
                        "resume_state": copy.deepcopy(
                            partial.get("resume_state") or {}
                        ),
                        "route_evidence_cache": [
                            *merged["route_evidence_cache"],
                            *list(partial.get("route_evidence_cache") or []),
                        ],
                    }))

                result = _run_batch_norm_agent(
                    task_rows,
                    exchange,
                    mapping_exchange=mapping_exchange,
                    candidate_limit=candidate_limit,
                    max_turns=max_turns,
                    progress=progress,
                    user_request=user_request,
                    checkpoint=batch_checkpoint if checkpoint is not None else None,
                    resume_checkpoint=batch_resume_checkpoint,
                    require_scoped_search=require_scoped_search,
                )
        except Exception as error:
            failed_ids = [str(row["work_id"]) for row in rows]
            blocker = {
                "code": (
                    "structured_mapping_timeout"
                    if isinstance(error, MappingTransportTimeout)
                    or _is_timeout_error(error)
                    else "batch_failed"
                ),
                "reason": str(error),
                "failed_work_ids": failed_ids,
            }
            if checkpoint is not None:
                checkpoint(copy.deepcopy({
                    **merged,
                    "incomplete": True,
                    "remaining_work_ids": [
                        work_id
                        for work_id in ordered_work_ids
                        if work_id not in merged["selections"]
                    ],
                    "incomplete_blocker": blocker,
                }))
            # Keep earlier accepted decisions; skip the stuck batch and continue.
            if _is_recoverable_batch_mapping_error(error) and (
                merged["selections"] or batch_index < len(batches)
            ):
                batch_traces.append({
                    "status": "batch_skipped_after_mapping_failure",
                    "error": str(error),
                    "failed_work_ids": failed_ids,
                })
                merged["incomplete"] = True
                merged["incomplete_blocker"] = blocker
                merged["remaining_work_ids"] = [
                    work_id
                    for work_id in ordered_work_ids
                    if work_id not in merged["selections"]
                ]
                if progress:
                    progress({
                        "phase": "source_batch",
                        "status": "degraded",
                        "label": (
                            "Смета: строка не закрыта после repair — "
                            "продолжаю следующие"
                        ),
                        "batch": batch_index,
                        "batches": len(batches),
                        "failed_work_ids": failed_ids,
                    })
                continue
            raise
        merged["selections"].update(result["selections"])
        merged["opened_cards"].update(result.get("opened_cards") or {})
        merged["browse_trace"].update(result["browse_trace"])
        merged["query_trace"].extend(result["query_trace"])
        merged["catalog_trace"].extend(result.get("catalog_trace") or [])
        merged["model_trace"].extend(
            {**item, "source_batch": batch_index} for item in result["model_trace"]
        )
        merged["valid_model_rows"] = len(merged["selections"])
        merged["remaining_work_ids"] = [
            work_id for work_id in ordered_work_ids
            if work_id not in merged["selections"]
        ]
        merged["incomplete"] = bool(merged["remaining_work_ids"])
        batch_blocker = dict(result.get("incomplete_blocker") or {})
        if merged["incomplete"] and batch_blocker:
            merged["incomplete_blocker"] = batch_blocker
        elif not merged["incomplete"]:
            merged["incomplete_blocker"] = {}
        known_cache_ids = {
            str(item.get("cache_id") or "")
            for item in merged["route_evidence_cache"]
            if isinstance(item, dict)
        }
        for route in result.get("route_evidence_cache") or []:
            cache_id = str((route or {}).get("cache_id") or "")
            if cache_id and cache_id not in known_cache_ids:
                merged["route_evidence_cache"].append(copy.deepcopy(route))
                known_cache_ids.add(cache_id)
        batch_traces.append(result.get("agent_trace") or {})
        if checkpoint is not None:
            checkpoint(copy.deepcopy(merged))
        if progress:
            rows_done = int(merged["valid_model_rows"])
            elapsed_sec = round(max(0.0, perf_counter() - batches_started), 1)
            sec_per_row = (
                round(elapsed_sec / rows_done, 1) if rows_done > 0 else None
            )
            eta_sec = round(
                (elapsed_sec / batch_index) * (len(batches) - batch_index)
            )
            pace_label = (
                f" · ~{sec_per_row} с/поз" if sec_per_row is not None else ""
            )
            eta_label = (
                f" · осталось около {max(1, round(eta_sec / 60))} мин"
                if eta_sec >= 60
                else f" · осталось около {eta_sec} с"
                if eta_sec > 0
                else ""
            )
            progress({
                "phase": "source_batch",
                "status": "done",
                "label": (
                    f"Смета: обработано {rows_done} из {len(work_rows)} строк"
                    f"{pace_label}{eta_label}"
                ),
                "batch": batch_index,
                "batches": len(batches),
                "completed_rows": rows_done,
                "rows_done": rows_done,
                "total_rows": len(work_rows),
                "elapsed_sec": elapsed_sec,
                "sec_per_row": sec_per_row,
                "eta_sec": eta_sec,
            })
    missing = [str(row["work_id"]) for row in work_rows if str(row["work_id"]) not in merged["selections"]]
    merged["agent_trace"] = {
        "mode": "model_bounded_batch_rag_tools",
        "engine": str((batch_traces[0] if batch_traces else {}).get("engine") or "native"),
        "provider": str((batch_traces[0] if batch_traces else {}).get("provider") or ""),
        "model": str((batch_traces[0] if batch_traces else {}).get("model") or ""),
        "batch_size": size,
        "task_mode": "sequential_rows" if accumulate_task_state else "independent_batches",
        "batches": len(batches),
        "source_rows": len(work_rows),
        "batch_traces": batch_traces,
        "model_turns": sum(int(trace.get("model_turns") or trace.get("turns") or 0) for trace in batch_traces),
        "tool_turns": sum(int(trace.get("tool_turns") or 0) for trace in batch_traces),
        "elapsed_ms": round(sum(float(trace.get("elapsed_ms") or 0.0) for trace in batch_traces), 2),
        "token_usage": {
            key: sum(
                int((trace.get("token_usage") or {}).get(key) or 0)
                for trace in batch_traces
            )
            for key in {key for trace in batch_traces for key in (trace.get("token_usage") or {})}
        },
    }
    if missing:
        # Keep uncovered rows open (empty selection) and still finalize Excel.
        # Code does not invent norms; open rows stay without a rate.
        for work_id in missing:
            merged["selections"].setdefault(work_id, {
                "norm_code": "",
                "reason": (
                    "row left open after mapping budget / validation exhaustion; "
                    "no model terminal decision was accepted"
                ),
                "review_status": "model_batch_open",
            })
        merged["incomplete"] = True
        merged["remaining_work_ids"] = []
        merged["valid_model_rows"] = sum(
            1
            for selection in merged["selections"].values()
            if isinstance(selection, dict)
            and (
                str(selection.get("norm_code") or "").strip()
                or str(selection.get("review_status") or "").startswith("model_batch")
            )
        )
        if not merged.get("incomplete_blocker"):
            merged["incomplete_blocker"] = {
                "code": "rows_skipped_after_mapping_failure",
                "reason": (
                    "some source rows were not mapped after bounded schema repair; "
                    "open rows preserved without invented rates"
                ),
                "missing_work_ids": missing,
            }
        merged["agent_trace"]["status"] = (
            "partial_after_mapping_failure"
            if any(
                str((merged["selections"].get(work_id) or {}).get("norm_code") or "").strip()
                or str((merged["selections"].get(work_id) or {}).get("review_status") or "")
                in {"model_batch_unbound", "model_batch_candidate", "model_batch"}
                for work_id in ordered_work_ids
                if work_id not in missing
            )
            else "all_rows_open_after_mapping_failure"
        )
        if checkpoint is not None:
            checkpoint(copy.deepcopy(merged))
        return merged
    merged["incomplete"] = False
    merged["remaining_work_ids"] = []
    merged["incomplete_blocker"] = {}
    return merged


def _conflict_work_groups(
    conflicts: list[dict[str, Any]],
) -> list[list[str]]:
    """Build deterministic connected components without judging conflicts."""
    adjacency: dict[str, set[str]] = {}
    for conflict in conflicts:
        work_ids = sorted({
            str(work_id)
            for work_id in (conflict.get("work_ids") or [])
            if str(work_id)
        })
        for work_id in work_ids:
            adjacency.setdefault(work_id, set()).update(
                other for other in work_ids if other != work_id
            )
    groups: list[list[str]] = []
    remaining = set(adjacency)
    while remaining:
        seed = min(remaining)
        component: set[str] = set()
        pending = [seed]
        while pending:
            work_id = pending.pop()
            if work_id in component:
                continue
            component.add(work_id)
            pending.extend(sorted(adjacency.get(work_id, set()) - component))
        remaining -= component
        groups.append(sorted(component))
    return groups


def _pack_conflict_groups(
    groups: list[list[str]],
    *,
    row_limit: int,
) -> list[list[str]]:
    """Pack independent groups without splitting a connected component."""
    packets: list[list[str]] = []
    current: list[str] = []
    for group in groups:
        if current and len(current) + len(group) > row_limit:
            packets.append(current)
            current = []
        current.extend(group)
        if len(current) >= row_limit:
            packets.append(current)
            current = []
    if current:
        packets.append(current)
    return packets


def _run_global_norm_review(
    work_rows: list[dict[str, Any]],
    initial_result: dict[str, Any],
    exchange: Exchange,
    *,
    mapping_exchange: MappingExchange | None,
    candidate_limit: int,
    max_turns: int,
    progress: Progress | None,
    user_request: str,
    batch_runner: AgentBatchRunner | None,
    require_scoped_search: bool = False,
) -> dict[str, Any]:
    """Review only connected conflict groups and preserve every other decision."""

    initial_selections = initial_result.get("selections") or {}
    opened_cards = initial_result.get("opened_cards") or {}
    before_conflicts = detect_professional_conflicts(
        work_rows,
        initial_selections,
        opened_cards=opened_cards,
        query_trace=initial_result.get("query_trace") or [],
    )
    conflicts_by_work: dict[str, list[dict[str, Any]]] = {}
    for conflict in before_conflicts:
        for work_id in conflict.get("work_ids") or []:
            conflicts_by_work.setdefault(str(work_id), []).append(conflict)
    groups = _conflict_work_groups(before_conflicts)
    review_row_limit = max(
        1,
        int(os.getenv("LES_SMETA_GLOBAL_REVIEW_ROWS", "8")),
    )
    packets = _pack_conflict_groups(groups, row_limit=review_row_limit)
    if progress:
        progress({
            "phase": "global_review", "status": "started",
            "label": (
                "Смета: модель проверяет только строки с межстрочными конфликтами"
            ),
            "rows": sum(len(group) for group in groups),
            "total_rows": len(work_rows),
            "groups": len(groups),
            "packets": len(packets),
            "conflicts": len(before_conflicts),
        })

    reviewed_selections = copy.deepcopy(initial_selections)
    review_results: list[dict[str, Any]] = []
    by_id = {str(row["work_id"]): row for row in work_rows}
    for packet_index, packet_work_ids in enumerate(packets, 1):
        packet_set = set(packet_work_ids)
        packet_rows = []
        group_lookup = {
            work_id: group_index
            for group_index, group in enumerate(groups, 1)
            for work_id in group
        }
        for work_id in packet_work_ids:
            row = by_id[work_id]
            selection = dict(initial_selections.get(work_id) or {})
            compact_cards = [
                _compact_norm_card_for_global_review(card)
                for card in (opened_cards.get(work_id) or [])
                if isinstance(card, dict)
            ]
            packet_rows.append({
                **row,
                "review_phase": "conflict_group_review",
                "conflict_group": group_lookup[work_id],
                "current_decision": {
                    "decision": _decision_name(selection),
                    **selection,
                },
                "opened_norm_cards": compact_cards,
                "professional_conflicts": conflicts_by_work.get(work_id, []),
            })
        review_request = (
            f"{user_request}\n\n"
            "CONFLICT-GROUP REVIEW. Review only the supplied connected conflict "
            "groups. Treat current_decision as the initial model draft. Resolve "
            "the supplied professional_conflicts for these work_ids, preserving "
            "a defensible decision and revising it only as your own professional "
            "decision. Rows outside this packet are already preserved unchanged. "
            "opened_norm_cards are compact typed summaries; reopen a full card "
            "only when this specific dispute needs it. Submit one terminal "
            "decision for every supplied work_id."
        )
        try:
            if batch_runner is not None:
                reviewed = batch_runner(
                    packet_rows,
                    candidate_limit=candidate_limit,
                    max_turns=max_turns,
                    progress=progress,
                    user_request=review_request,
                )
            else:
                reviewed = _run_batch_norm_agent(
                    packet_rows,
                    exchange,
                    mapping_exchange=mapping_exchange,
                    candidate_limit=candidate_limit,
                    max_turns=max_turns,
                    progress=progress,
                    user_request=review_request,
                    require_scoped_search=require_scoped_search,
                )
        except RuntimeError as error:
            # Row mapping already produced terminal decisions. A failed conflict
            # re-serialization must not destroy the whole LSR document.
            message = str(error)
            recoverable = any(
                marker in message
                for marker in (
                    "mapping failed validation",
                    "did not submit mapping within",
                    "returned no rows in structured mapping",
                )
            )
            if not recoverable:
                raise
            if progress:
                progress({
                    "phase": "global_review",
                    "status": "waiting",
                    "label": (
                        "Смета: конфликт-ревью не завершило mapping — "
                        "сохранены исходные решения строк"
                    ),
                    "packet": packet_index,
                    "error": message[:240],
                })
            reviewed = {
                "selections": {
                    work_id: copy.deepcopy(initial_selections[work_id])
                    for work_id in packet_work_ids
                    if work_id in initial_selections
                },
                "opened_cards": {},
                "browse_trace": {},
                "query_trace": [],
                "catalog_trace": [],
                "model_trace": [],
                "agent_trace": {
                    "mode": "model_conflict_group_review",
                    "status": "packet_preserved_after_mapping_failure",
                    "error": message[:400],
                    "preserved_work_ids": list(packet_work_ids),
                },
            }
        packet_selections = dict(reviewed.get("selections") or {})
        missing = sorted(packet_set - set(packet_selections))
        if missing:
            # Prefer preserving known initial decisions over aborting the document.
            for work_id in missing:
                if work_id in initial_selections:
                    packet_selections[work_id] = copy.deepcopy(
                        initial_selections[work_id]
                    )
            still_missing = sorted(packet_set - set(packet_selections))
            if still_missing:
                raise RuntimeError(
                    "global conflict review omitted work_ids: "
                    + ", ".join(still_missing)
                )
            reviewed = {
                **reviewed,
                "selections": packet_selections,
                "agent_trace": {
                    **dict(reviewed.get("agent_trace") or {}),
                    "status": "packet_backfilled_from_initial",
                    "backfilled_work_ids": missing,
                },
            }
        reviewed_selections.update(packet_selections)
        review_results.append(reviewed)

    reviewed = {
        "selections": reviewed_selections,
        # The conflict-only review preserves every non-conflicting decision and
        # replaces only model-reviewed packet decisions.  Keep the structural
        # completion counter aligned with that full terminal mapping; otherwise
        # the document boundary falsely reports zero valid rows after review.
        "valid_model_rows": len(reviewed_selections),
        "remaining_work_ids": [],
        "incomplete": False,
        "opened_cards": {},
        "browse_trace": {},
        "query_trace": [],
        "catalog_trace": [],
        "model_trace": [],
        "agent_trace": {
            "mode": "model_conflict_group_review",
            "group_count": len(groups),
            "packet_count": len(packets),
            "reviewed_work_ids": sorted(conflicts_by_work),
            "preserved_work_ids": sorted(
                set(initial_selections) - set(conflicts_by_work)
            ),
            "packets": [
                result.get("agent_trace") or {}
                for result in review_results
            ],
        },
    }
    for result in review_results:
        reviewed["opened_cards"].update(result.get("opened_cards") or {})
        for work_id, traces in (result.get("browse_trace") or {}).items():
            reviewed["browse_trace"].setdefault(str(work_id), []).extend(
                traces or []
            )
        reviewed["query_trace"].extend(result.get("query_trace") or [])
        reviewed["catalog_trace"].extend(result.get("catalog_trace") or [])
        reviewed["model_trace"].extend(result.get("model_trace") or [])
    after_opened = dict(opened_cards)
    for work_id, cards in (reviewed.get("opened_cards") or {}).items():
        after_opened[work_id] = [*(after_opened.get(work_id) or []), *(cards or [])]
    combined_browse = {
        str(work_id): [
            *((initial_result.get("browse_trace") or {}).get(work_id) or []),
            *((reviewed.get("browse_trace") or {}).get(work_id) or []),
        ]
        for work_id in {
            *(initial_result.get("browse_trace") or {}).keys(),
            *(reviewed.get("browse_trace") or {}).keys(),
        }
    }
    after_conflicts = detect_professional_conflicts(
        work_rows,
        reviewed.get("selections") or {},
        opened_cards=after_opened,
        query_trace=[*(initial_result.get("query_trace") or []), *(reviewed.get("query_trace") or [])],
    )
    if progress:
        progress({
            "phase": "global_review", "status": "done",
            "label": (
                f"Смета: межстрочная ревизия готова, осталось конфликтов {len(after_conflicts)}"
            ),
            "rows": len(conflicts_by_work),
            "total_rows": len(work_rows),
            "groups": len(groups),
            "conflicts_before": len(before_conflicts),
            "conflicts_after": len(after_conflicts),
        })
    return {
        **reviewed,
        "opened_cards": after_opened,
        "browse_trace": combined_browse,
        "query_trace": [
            *(initial_result.get("query_trace") or []),
            *({**item, "review_phase": "global_review"} for item in (reviewed.get("query_trace") or [])),
        ],
        "catalog_trace": [
            *(initial_result.get("catalog_trace") or []),
            *({**item, "review_phase": "global_review"} for item in (reviewed.get("catalog_trace") or [])),
        ],
        "model_trace": [
            *(initial_result.get("model_trace") or []),
            *({**item, "review_phase": "global_review"} for item in (reviewed.get("model_trace") or [])),
        ],
        "professional_conflicts_before_review": before_conflicts,
        "professional_conflicts": after_conflicts,
        "route_evidence_cache": list(
            initial_result.get("route_evidence_cache") or []
        ),
        "agent_trace": {
            "mode": "row_mapping_then_conflict_group_review",
            "initial": initial_result.get("agent_trace") or {},
            "global_review": reviewed.get("agent_trace") or {},
        },
    }


def _work_norm_phase(session: SmetaNormToolSession, work_id: str) -> str:
    """Return one row's current typed phase without making a domain decision."""
    if work_id in session.catalog_terminal_decisions:
        return "norm_evidence"
    if work_id not in session.family_catalog_seen:
        return "family_root"
    if not session.selected_base_types.get(work_id):
        return "family_select"
    if not session.selected_collections.get(work_id):
        return "collection"
    if not session.selected_sections.get(work_id):
        return "section_select"
    if not session.selected_tables.get(work_id):
        return "table_select"
    selected_table_codes = {
        table_code
        for _family, _collection, table_code in (
            session.selected_tables.get(work_id) or set()
        )
    }
    searched_table_codes = {
        str(table_code)
        for item in session.query_trace
        if str(item.get("work_id") or "") == work_id
        for table_code in ((item.get("filters") or {}).get("table_codes") or [])
    }
    if selected_table_codes.isdisjoint(searched_table_codes):
        return "norm_search"
    if session.candidates.get(work_id) and not session.opened.get(work_id):
        return "norm_read"
    return "norm_evidence"


def _norm_agent_phase(session: SmetaNormToolSession) -> str:
    """Schedule the earliest unfinished phase shared by one or more rows."""
    remaining = session.remaining_work_ids
    if not remaining:
        return "norm_evidence"
    phases = {_work_norm_phase(session, work_id) for work_id in remaining}
    return next(phase for phase in _PHASE_ORDER if phase in phases)


def _phase_work_ids(
    session: SmetaNormToolSession,
    phase: str | None = None,
) -> list[str]:
    """Return every remaining row currently ready for the scheduled phase."""
    active_phase = phase or _norm_agent_phase(session)
    return [
        work_id
        for work_id in session.remaining_work_ids
        if _work_norm_phase(session, work_id) == active_phase
    ]


def _phase_norm_tools(
    phase: str,
    *,
    include_route_cache: bool = False,
    active_work_ids: list[str] | None = None,
    current_node_ids: dict[str, str] | None = None,
    visible_child_node_ids: dict[str, list[str]] | None = None,
    visible_evidence_fields: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Expose only schemas usable in the current checkpoint phase."""
    all_tools = {
        str((tool.get("function") or {}).get("name") or ""): copy.deepcopy(tool)
        for tool in _batch_norm_tools()
        if str((tool.get("function") or {}).get("name") or "")
        != "submit_lsr_mapping"
    }
    browse = all_tools["browse_norm_catalog"]
    route_fields = (
        "work_id",
        "current_node_id",
        "decision",
        "selected_node_id",
        "evidence",
        "rejected_nodes",
        "confidence",
        "missing_facts",
        "question",
    )
    phase_fields = {
        "family_root": ("work_id",),
        "family_select": (
            *route_fields,
            "work_features",
            "catalog_query",
        ),
        "collection": route_fields,
        "section_select": (
            *route_fields,
            "catalog_query",
        ),
        "table_select": route_fields,
    }
    if phase in phase_fields:
        item_schema = (
            browse["function"]["parameters"]["properties"]["items"]["items"]
        )
        items_schema = browse["function"]["parameters"]["properties"]["items"]
        source_properties = dict(item_schema.get("properties") or {})
        fields = phase_fields[phase]
        item_schema["properties"] = {
            name: source_properties[name]
            for name in fields
            if name in source_properties
        }
        if active_work_ids:
            item_schema["properties"]["work_id"]["enum"] = list(active_work_ids)
            items_schema["minItems"] = 1
            items_schema["maxItems"] = len(active_work_ids)
        current_nodes = list(dict.fromkeys(
            str((current_node_ids or {}).get(work_id) or "").strip()
            for work_id in (active_work_ids or [])
            if str((current_node_ids or {}).get(work_id) or "").strip()
        ))
        if current_nodes and "current_node_id" in item_schema["properties"]:
            item_schema["properties"]["current_node_id"]["enum"] = current_nodes
        visible_nodes = list(dict.fromkeys(
            str(node_id).strip()
            for work_id in (active_work_ids or [])
            for node_id in ((visible_child_node_ids or {}).get(work_id) or [])
            if str(node_id).strip()
        ))
        if visible_nodes and "selected_node_id" in item_schema["properties"]:
            item_schema["properties"]["selected_node_id"]["enum"] = visible_nodes
        if visible_nodes and "evidence" in item_schema["properties"]:
            item_schema["properties"]["evidence"]["items"]["properties"][
                "source_node_id"
            ]["enum"] = visible_nodes
            if visible_evidence_fields:
                item_schema["properties"]["evidence"]["items"]["properties"][
                    "field"
                ]["enum"] = list(dict.fromkeys(visible_evidence_fields))
        if visible_nodes and "rejected_nodes" in item_schema["properties"]:
            item_schema["properties"]["rejected_nodes"]["items"]["properties"][
                "node_id"
            ]["enum"] = visible_nodes
        item_schema["required"] = (
            ["work_id"]
            if phase == "family_root"
            else [
                "work_id",
                "current_node_id",
                "decision",
                "selected_node_id",
                "evidence",
                "rejected_nodes",
                "confidence",
                "missing_facts",
                *(
                    ["work_features", "catalog_query"]
                    if phase == "family_select"
                    else ["catalog_query"]
                    if phase == "section_select"
                    else []
                ),
            ]
        )
        if phase != "family_root":
            item_schema["properties"]["evidence"]["minItems"] = 1
            continue_required = ["selected_node_id", "evidence"]
            if phase == "family_select":
                continue_required.extend(["work_features", "catalog_query"])
            elif phase == "section_select":
                continue_required.append("catalog_query")
            item_schema["allOf"] = [
                {
                    "if": {
                        "properties": {
                            "decision": {"const": "continue"}
                        },
                        "required": ["decision"],
                    },
                    "then": {
                        "required": continue_required,
                        "properties": {
                            "evidence": {"minItems": 1}
                        },
                    },
                },
                {
                    "if": {
                        "properties": {"decision": {"const": "ask"}},
                        "required": ["decision"],
                    },
                    "then": {"required": ["question"]},
                },
                {
                    "if": {
                        "properties": {
                            "decision": {"const": "unbound"}
                        },
                        "required": ["decision"],
                    },
                    "then": {
                        "properties": {
                            "evidence": {"minItems": 1}
                        },
                    },
                },
            ]
            item_schema["additionalProperties"] = False
        browse["function"]["description"] = {
            "family_root": "Return the five authoritative norm-family passports.",
            "family_select": (
                "Make one typed evidence-bound transition from the root to a "
                "shown family."
            ),
            "collection": (
                "Make one typed evidence-bound transition to a shown collection, "
                "ask for a user fact, broaden, or leave the route unbound."
            ),
            "section_select": (
                "Make one typed evidence-bound transition to a shown section."
            ),
            "table_select": (
                "Make one typed evidence-bound transition to a shown table."
            ),
        }[phase]
        if phase != "family_root":
            common_fields = (
                "work_id",
                "current_node_id",
                "evidence",
                "rejected_nodes",
                "confidence",
                "missing_facts",
            )
            continue_fields = [
                *common_fields,
                "selected_node_id",
            ]
            if phase == "section_select":
                continue_fields.append("catalog_query")
            split_continue_required = [*common_fields, "selected_node_id"]
            if phase == "section_select":
                split_continue_required.append("catalog_query")
            # family_select stays on items[] (Ollama/Qwen XML tool format). A flat
            # schema caused HTTP 500 "parameter closed by function". Keep one
            # continue tool with minimal required fields; LES drafts gaps.
            if phase == "family_select":
                route_specs = (
                    (
                        "continue_norm_catalog",
                        (
                            "Select exactly one shown family. items must contain "
                            "ONE decision object with work_id, selected_node_id, "
                            "confidence. Do NOT echo passport cards into items. "
                            "work_features/evidence optional — LES drafts from VOR title."
                        ),
                        (
                            "work_id",
                            "selected_node_id",
                            "confidence",
                            "catalog_query",
                            "work_features",
                            "evidence",
                        ),
                        ("work_id", "selected_node_id", "confidence"),
                    ),
                )
            else:
                route_specs = (
                    (
                        "continue_norm_catalog",
                        "Select one exact shown child using official evidence.",
                        continue_fields,
                        split_continue_required,
                    ),
                    (
                        "ask_norm_catalog_fact",
                        (
                            "Ask one question only about a missing observable "
                            "installation or project fact. Forbidden in "
                            "family_select: encode unknown details and choose the "
                            "norm family from the stated operation."
                        ),
                        [*common_fields, "question"],
                        [*common_fields, "question"],
                    ),
                    (
                        "broaden_norm_catalog",
                        "Return exactly to the parent node without choosing a sibling.",
                        list(common_fields),
                        list(common_fields),
                    ),
                    (
                        "unbound_norm_catalog",
                        (
                            "Stop this catalog route with official evidence; do not "
                            "invent or jump to a branch."
                        ),
                        list(common_fields),
                        list(common_fields),
                    ),
                )
            tools = []
            for name, description, fields_for_tool, required_for_tool in route_specs:
                route_tool = copy.deepcopy(browse)
                route_tool["function"]["name"] = name
                route_tool["function"]["description"] = description
                route_item = (
                    route_tool["function"]["parameters"]["properties"]["items"][
                        "items"
                    ]
                )
                route_item["properties"] = {
                    field: copy.deepcopy(source_properties[field])
                    for field in fields_for_tool
                    if field in source_properties
                }
                route_item["required"] = list(required_for_tool)
                route_item["additionalProperties"] = False
                route_item.pop("allOf", None)
                if (
                    "evidence" in route_item["properties"]
                    and "evidence" in required_for_tool
                ):
                    route_item["properties"]["evidence"]["minItems"] = 1
                if "rejected_nodes" in route_item["properties"]:
                    route_item["properties"]["rejected_nodes"]["maxItems"] = 6
                if active_work_ids:
                    route_items_schema = (
                        route_tool["function"]["parameters"]["properties"]["items"]
                    )
                    route_items_schema["minItems"] = 1
                    route_items_schema["maxItems"] = len(active_work_ids)
                tools.append(route_tool)
            if phase != "family_root" and include_route_cache:
                tools.append(all_tools["reuse_norm_catalog_route"])
            return tools
        return [browse]
    if phase == "norm_search":
        return [all_tools["search_norms_batch"]]
    if phase == "norm_read":
        return [all_tools["read_norms_batch"]]
    # norm_evidence: no reuse/browse (reuse spins). Broaden stays so the model
    # can leave a wrong table instead of mass-unbound.
    broaden = copy.deepcopy(browse)
    broaden["function"]["name"] = "broaden_norm_catalog"
    broaden["function"]["description"] = (
        "Leave the current table when opened cards are not applicable; "
        "return exactly to the parent catalog node."
    )
    broaden_item = (
        broaden["function"]["parameters"]["properties"]["items"]["items"]
    )
    broaden_fields = (
        "work_id",
        "current_node_id",
        "evidence",
        "rejected_nodes",
        "confidence",
        "missing_facts",
    )
    source_properties = broaden_item.get("properties") or {}
    broaden_item["properties"] = {
        field: copy.deepcopy(source_properties[field])
        for field in broaden_fields
        if field in source_properties
    }
    broaden_item["required"] = [
        "work_id",
        "current_node_id",
        "evidence",
        "confidence",
    ]
    broaden_item["additionalProperties"] = False
    broaden_item.pop("allOf", None)
    if "evidence" in broaden_item["properties"]:
        broaden_item["properties"]["evidence"]["minItems"] = 1
    if active_work_ids:
        broaden["function"]["parameters"]["properties"]["items"]["minItems"] = 1
        broaden["function"]["parameters"]["properties"]["items"]["maxItems"] = (
            len(active_work_ids)
        )
    return [
        all_tools["search_norms_batch"],
        all_tools["read_norms_batch"],
        broaden,
    ]


def _run_batch_norm_agent(
    work_rows: list[dict[str, Any]],
    exchange: Exchange,
    *,
    mapping_exchange: MappingExchange | None = None,
    candidate_limit: int,
    max_turns: int = 64,
    progress: Progress | None = None,
    user_request: str = "",
    checkpoint: Checkpoint | None = None,
    resume_checkpoint: dict[str, Any] | None = None,
    require_scoped_search: bool = False,
) -> dict[str, Any]:
    """Thin model tool loop: batch RAG, batch read, one model-owned mapping submission."""
    session = SmetaNormToolSession(
        work_rows,
        candidate_limit=candidate_limit,
        progress=progress,
        require_scoped_search=require_scoped_search,
    )
    resumed = dict(resume_checkpoint or {})
    resume_state = (
        dict(resumed.get("resume_state") or {})
        if isinstance(resumed.get("resume_state"), dict)
        else {}
    )
    if resume_state:
        if str(resume_state.get("schema") or "") != "smeta_norm_agent_resume_v1":
            raise RuntimeError("unsupported smeta norm agent resume schema")
        session.restore_checkpoint_state(
            dict(resume_state.get("tool_session") or {})
        )
    by_id = session.by_id
    browse_trace = session.browse_trace
    query_trace = session.query_trace
    model_trace: list[dict[str, Any]] = list(
        resume_state.get("model_trace") or []
    )
    context_metrics: list[dict[str, Any]] = list(
        resume_state.get("context_metrics") or []
    )
    # Search/read are agent tools. The model's final professional mapping is
    # serialized in a separate structured-output request, matching Ollama's
    # documented "no tool calls => end agent loop" contract.
    skill_prompt = (
        smeta_phase_common_prompt()
        if require_scoped_search
        else smeta_native_skill_prompt()
    )
    if not skill_prompt:
        raise RuntimeError("canonical smeta skill is unavailable")
    system_prompt = skill_prompt
    def visible_work_items(work_ids: list[str] | None = None) -> list[dict[str, Any]]:
        """Keep scoped navigation focused without losing the full session state."""
        if not require_scoped_search:
            return list(by_id.values())
        selected_ids = work_ids or _phase_work_ids(
            session, _norm_agent_phase(session)
        )
        return [by_id[work_id] for work_id in selected_ids if work_id in by_id]

    initial_conversation: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "user_request": str(user_request or "").strip(),
                    "work_items": visible_work_items(),
                    "batch_contract": (
                        "Use tools only for work_id values present in work_items. Each item's neighbor_context is "
                        "navigation for overlap/coverage; do not search or submit those neighboring work_ids here. "
                        + (
                            "RIM uses a server-selected phase skill and tool schema. Execute "
                            "only the current phase; the checkpoint carries prior catalog "
                            "choices and evidence. Never skip family→collection→section→table, "
                            "and never invent a code."
                            if require_scoped_search
                            else ""
                        )
                        + (
                            " memory_advisory contains prior reviewed project episodes, "
                            "not evidence for this row. Use it to navigate or compare, then "
                            "open current typed cards before deciding."
                            if any(row.get("memory_advisory") for row in by_id.values())
                            else ""
                        )
                    ),
                },
                ensure_ascii=False,
                default=str,
            ),
        },
    ]
    resume_validation_contract_changed = bool(
        resume_state
        and str(resume_state.get("validation_contract_version") or "")
        != MAPPING_VALIDATION_CONTRACT_VERSION
    )
    conversation: list[dict[str, Any]] = (
        copy.deepcopy(initial_conversation)
        if resume_validation_contract_changed
        else copy.deepcopy(list(resume_state.get("conversation") or []))
        if resume_state.get("conversation")
        else initial_conversation
    )
    if not conversation or str((conversation[0] or {}).get("role") or "") != "system":
        raise RuntimeError("smeta norm checkpoint has invalid conversation")
    if max_turns < 1:
        raise ValueError("max_turns must be positive")
    accepted_rows = session.accepted_rows
    previous_call_signature = str(
        resume_state.get("previous_call_signature") or ""
    )
    duplicate_feedback_signature = str(
        resume_state.get("duplicate_feedback_signature") or ""
    )
    structured_mapping_attempts = int(
        resume_state.get("structured_mapping_attempts") or 0
    )
    validation_contract_changed = resume_validation_contract_changed
    if validation_contract_changed:
        structured_mapping_attempts = 0
        previous_call_signature = ""
        duplicate_feedback_signature = ""
    last_submit_result: dict[str, Any] | None = (
        copy.deepcopy(resume_state.get("last_submit_result"))
        if isinstance(resume_state.get("last_submit_result"), dict)
        else None
    )
    if validation_contract_changed:
        invalidated_rows: list[dict[str, Any]] = []
        for work_id, selection in list(accepted_rows.items()):
            if str(selection.get("review_status") or "") != "model_batch_unbound":
                continue
            evidence = dict(selection.get("unbound_evidence") or {})
            validation_errors = session._unbound_evidence_errors(
                work_id,
                reason=str(selection.get("reason") or ""),
                evidence=evidence,
            )
            if not validation_errors:
                continue
            invalidated_rows.append({
                "work_id": work_id,
                "error": "stored unbound decision fails the current grounding contract",
                "details": validation_errors,
                "preserved_in_tool_trajectory": True,
            })
            del accepted_rows[work_id]
        if invalidated_rows:
            last_submit_result = {
                "ok": False,
                "errors": invalidated_rows,
                "accepted_work_ids": list(accepted_rows),
                "remaining_work_ids": session.remaining_work_ids,
            }
    focus_serialization_pending = bool(
        resume_state.get("focus_serialization_pending")
    ) and not validation_contract_changed
    focus_serialization_reason = str(
        resume_state.get("focus_serialization_reason") or ""
    )
    opened_evidence_turns = int(resume_state.get("opened_evidence_turns") or 0)
    mapping_chunk = _mapping_chunk_size()

    def submit_requires_more_evidence(result: dict[str, Any] | None) -> bool:
        """Return to tools when terminal validation names missing evidence."""
        if not result or result.get("ok"):
            return False
        evidence_markers = (
            "requires at least two distinct query or scoped-search strategies",
            "without an opened typed card",
            "was not opened through read_norms_batch",
            "requires opening at least one shown alternative",
            "selected candidate contradicts bind",
            "selection_kind exact requires exact operation, object and scope",
            "selection_kind exact is unsupported by opened evidence",
            # Self-contradict exact: return to tools for broaden/unbound, do not
            # burn the bounded schema-repair budget on the same wrong norm.
            "contradicts reason that denies applicability",
            "broaden to another table",
        )
        errors = [
            error for error in (result.get("errors") or [])
            if isinstance(error, dict)
        ]
        missing_evidence = any(
            any(
                marker in str(detail)
                for marker in evidence_markers
            )
            for error in errors
            for detail in (error.get("details") or [])
        )
        if not missing_evidence:
            # Balanced interpretation can see that the model's prose names a
            # norm positively, but it deliberately cannot open that card or
            # change covered_by/unbound into bind.  This is an evidence error,
            # not a JSON-shape error: return the same model to typed tools.
            missing_evidence = any(
                bool((error.get("resolver_hint") or {}).get("references"))
                and not bool((error.get("resolver_hint") or {}).get("matched_opened_codes"))
                and (error.get("resolver_hint") or {}).get("reason_suggests_positive_applicability") is True
                for error in errors
            )
        if not missing_evidence:
            return False
        remaining = session.evidence_remaining()
        return (
            int(remaining.get("search_calls") or 0) > 0
            and float(remaining.get("tool_elapsed_seconds") or 0.0) > 0.0
        )

    if (
        focus_serialization_pending
        and submit_requires_more_evidence(last_submit_result)
    ):
        structured_mapping_attempts = 0
        focus_serialization_pending = False
        previous_call_signature = ""
        duplicate_feedback_signature = ""

    def refresh_agent_working_memory() -> None:
        """Expose compact canonical evidence without replaying the event log."""
        conversation[:] = conversation[:2]
        conversation[:] = [
            message
            for message in conversation
            if (
                "smeta_norm_agent_working_memory_v1"
                not in str(message.get("content") or "")
            )
        ]
        work_evidence_status = []
        must_read = []
        must_search_scopes = []
        must_navigate_scopes = []
        pending_candidates: dict[str, dict[str, dict[str, Any]]] = {}
        pending_opened: dict[str, dict[str, dict[str, Any]]] = {}
        memory_phase = _norm_agent_phase(session)
        active_work_ids = _phase_work_ids(session, memory_phase)
        memory_work_ids = (
            active_work_ids
            if require_scoped_search
            else session.remaining_work_ids
        )
        for work_id in memory_work_ids:
            candidate_cards = {
                str((card or {}).get("norm_code") or code): card
                for code, card in (session.candidates.get(work_id) or {}).items()
                if str((card or {}).get("norm_code") or code)
            }
            opened_cards = {
                str((card or {}).get("norm_code") or code): card
                for code, card in (session.opened.get(work_id) or {}).items()
                if str((card or {}).get("norm_code") or code)
            }
            pending_candidates[work_id] = candidate_cards
            pending_opened[work_id] = opened_cards
            if candidate_cards and not opened_cards:
                must_read.append(work_id)
            searched_tables = {
                (
                    str(base_type).casefold(),
                    str(collection).casefold(),
                    str(table_code),
                )
                for trace in session.query_trace
                if str(trace.get("work_id") or "") == work_id
                for base_type in (
                    (trace.get("filters") or {}).get("base_types") or []
                )
                for collection in (
                    (trace.get("filters") or {}).get("collections") or []
                )
                for table_code in (
                    (trace.get("filters") or {}).get("table_codes") or []
                )
            }
            for family, collection in sorted(
                session.selected_collections.get(work_id) or set()
            ):
                family_card = (
                    session.selected_base_types.get(work_id) or {}
                ).get(family.casefold()) or {}
                selected_tables = sorted(
                    table_code
                    for table_family, table_collection, table_code in (
                        session.selected_tables.get(work_id) or set()
                    )
                    if table_family == family and table_collection == collection
                )
                if not selected_tables:
                    must_navigate_scopes.append({
                        "work_id": work_id,
                        "base_type": str(family_card.get("family") or family),
                        "collection": collection,
                        "selected_sections": [
                            section
                            for section_family, section_collection, section in sorted(
                                session.selected_sections.get(work_id) or set()
                            )
                            if (
                                section_family == family
                                and section_collection == collection
                            )
                        ],
                        "next_action": (
                            "select a section if none is selected, then select one "
                            "official table from that section"
                        ),
                    })
                    continue
                for table_code in selected_tables:
                    if (
                        family.casefold(),
                        collection.casefold(),
                        table_code,
                    ) in searched_tables:
                        continue
                    must_search_scopes.append({
                        "work_id": work_id,
                        "base_type": str(family_card.get("family") or family),
                        "collection": collection,
                        "section": table_code[:5],
                        "table_code": table_code,
                    })
        focus_work_id = (
            next(
                (work_id for work_id in must_read if work_id in active_work_ids),
                "",
            )
            or (active_work_ids[0] if active_work_ids else "")
        )
        for work_id in memory_work_ids:
            candidate_cards = pending_candidates[work_id]
            opened_cards = pending_opened[work_id]
            latest_candidate_codes = next(
                (
                    [
                        str(code)
                        for code in (trace.get("candidate_codes") or [])
                        if str(code)
                    ]
                    for trace in reversed(session.query_trace)
                    if str(trace.get("work_id") or "") == work_id
                ),
                [],
            )
            active_candidate_cards = {
                code: candidate_cards[code]
                for code in latest_candidate_codes
                if code in candidate_cards
            } or candidate_cards
            active_opened_cards = {
                code: opened_cards[code]
                for code in active_candidate_cards
                if code in opened_cards
            }
            work_evidence_status.append({
                "work_id": work_id,
                "is_focus": work_id == focus_work_id,
                "is_active_phase": work_id in active_work_ids,
                "catalog_current_node_id": session.catalog_current_nodes.get(
                    work_id, "catalog:root"
                ),
                "catalog_visible_children": _compact_catalog_menu_for_model(
                    copy.deepcopy(session.catalog_menus.get(work_id, {}).get(
                        session.catalog_current_nodes.get(
                            work_id, "catalog:root"
                        ),
                        [],
                    )),
                    phase=memory_phase,
                ) if work_id in active_work_ids else [],
                "selected_base_types": list(
                    (session.selected_base_types.get(work_id) or {}).values()
                ),
                "selected_collections": [
                    {"family": family, "collection": collection}
                    for family, collection in sorted(
                        session.selected_collections.get(work_id) or set()
                    )
                ],
                "selected_sections": [
                    {
                        "family": family,
                        "collection": collection,
                        "section": section,
                    }
                    for family, collection, section in sorted(
                        session.selected_sections.get(work_id) or set()
                    )
                ],
                "selected_tables": [
                    {
                        "family": family,
                        "collection": collection,
                        "table_code": table_code,
                    }
                    for family, collection, table_code in sorted(
                        session.selected_tables.get(work_id) or set()
                    )
                ],
                "candidate_codes": sorted(candidate_cards),
                "active_candidate_codes": list(active_candidate_cards),
                "candidates": [
                    {
                        "norm_code": code,
                        "title": str(
                            (card or {}).get("title")
                            or (card or {}).get("norm_name")
                            or ""
                        )[:240],
                        "measure_unit": str(
                            (card or {}).get("measure_unit") or ""
                        ),
                        "candidate_rank": (card or {}).get("candidate_rank"),
                        "source_ref": str((card or {}).get("source_ref") or "")[:240],
                    }
                    for code, card in active_candidate_cards.items()
                ] if work_id in active_work_ids else [],
                "opened_codes": sorted(opened_cards),
                "active_opened_codes": sorted(active_opened_cards),
                "opened_evidence": [
                    _compact_norm_card_for_global_review(card)
                    for _code, card in sorted(active_opened_cards.items())
                    if isinstance(card, dict)
                ] if work_id in active_work_ids else [],
                "search_count": sum(
                    1
                    for item in session.query_trace
                    if str(item.get("work_id") or "") == work_id
                ),
            })
        compact_route_cache = _compact_route_evidence_cache_for_model(
            session.route_evidence_cache,
            limit=24,
        )
        reuse_first_instruction = (
            " route_evidence_cache is non-empty: call reuse_norm_catalog_route "
            "with a suitable cache_id before browsing from catalog:root. Browse "
            "from root only when no cached family→collection→section→table route "
            "applies to the active work. Reuse transfers scope only; search and "
            "read remain mandatory before bind."
            if (
                compact_route_cache
                and memory_phase in {"family_root", "family_select", "collection"}
            )
            else ""
        )
        phase_instruction = (
            "Call read_norms_batch once for all active_work_ids that appear in "
            "must_read_before_more_search before any new catalog or search action. "
            "Candidate codes and opened state below are authoritative."
            if must_read
            else
            "The phase skill and latest tool result are authoritative. Execute "
            f"only phase {memory_phase} for every active_work_id in one batch tool "
            "call where possible; use the selected nodes below as checkpoint state "
            "and do not discuss or precompute later phases."
            if require_scoped_search
            and memory_phase
            in {
                "family_root",
                "family_select",
                "collection",
                "section_select",
                "table_select",
            }
            else (
                "Use the compact typed state as authoritative. Read current "
                "candidates before more navigation. Complete one focused row, "
                "then finish the tool loop when evidence supports your own "
                "mapping decision. If a selected table is empty or unsuitable, "
                "backtrack through explicit catalog nodes; never remove scope."
                if require_scoped_search
                else (
                    "This compact typed state is authoritative; historical tool "
                    "messages are only an audit log. Use the latest full "
                    "read_norms_batch result plus opened_evidence for professional "
                    "reasoning."
                )
            )
        ) + reuse_first_instruction
        if require_scoped_search and len(conversation) >= 2:
            try:
                focused_request = json.loads(
                    str(conversation[1].get("content") or "{}")
                )
            except json.JSONDecodeError:
                focused_request = {
                    "user_request": str(user_request or "").strip(),
                }
            focused_request["work_items"] = visible_work_items(active_work_ids)
            conversation[1]["content"] = json.dumps(
                focused_request,
                ensure_ascii=False,
                default=str,
            )
        conversation.append({
            "role": "user",
            "content": json.dumps(
                {
                    "working_memory_contract": (
                        "smeta_norm_agent_working_memory_v1"
                    ),
                    "active_phase": memory_phase,
                    "active_phase_instruction": smeta_phase_instruction(
                        memory_phase
                    ),
                    "remaining_work_ids": memory_work_ids,
                    "deferred_work_count": max(
                        0,
                        len(session.remaining_work_ids) - len(memory_work_ids),
                    ),
                    "focus_work_id": focus_work_id,
                    "active_work_ids": active_work_ids,
                    "work_evidence_status": work_evidence_status,
                    "must_read_before_more_search": must_read,
                    "must_navigate_selected_scopes": must_navigate_scopes,
                    "must_search_selected_scopes": must_search_scopes,
                    "route_reuse_first": bool(compact_route_cache),
                    "route_evidence_cache": compact_route_cache,
                    "last_submit_validation": (
                        copy.deepcopy(last_submit_result.get("errors") or [])
                        if submit_requires_more_evidence(last_submit_result)
                        else []
                    ),
                    "instruction": (
                        phase_instruction
                    ),
                },
                ensure_ascii=False,
                default=str,
            ),
        })

    def emit_checkpoint(
        *,
        incomplete_blocker: dict[str, Any] | None = None,
        next_turn: int | None = None,
    ) -> None:
        if checkpoint is None:
            return
        payload = session.result(
            model_trace=model_trace,
            agent_trace={
                "mode": "model_batch_rag_tools",
                "turns": len(model_trace),
                "context_metrics": context_metrics,
                "status": "turn_checkpoint",
            },
            allow_incomplete=True,
            incomplete_blocker=incomplete_blocker,
        )
        payload["resume_state"] = {
            "schema": "smeta_norm_agent_resume_v1",
            "conversation": copy.deepcopy(conversation),
            "tool_session": session.checkpoint_state(),
            "model_trace": copy.deepcopy(model_trace),
            "context_metrics": copy.deepcopy(context_metrics),
            "next_turn": int(next_turn or (len(model_trace) + 1)),
            "previous_call_signature": previous_call_signature,
            "duplicate_feedback_signature": duplicate_feedback_signature,
            "structured_mapping_attempts": structured_mapping_attempts,
            "evidence_repair_turns_remaining": evidence_repair_turns_remaining,
            "evidence_repair_granted": evidence_repair_granted,
            "last_submit_result": copy.deepcopy(last_submit_result),
            "focus_serialization_pending": focus_serialization_pending,
            "focus_serialization_reason": focus_serialization_reason,
            "opened_evidence_turns": opened_evidence_turns,
            "validation_contract_version": (
                MAPPING_VALIDATION_CONTRACT_VERSION
            ),
        }
        checkpoint(payload)

    def checkpoint_accepted_decision(
        _work_id: str,
        _selection: dict[str, Any],
    ) -> None:
        """Persist each accepted row before validating the next submitted row."""
        emit_checkpoint(next_turn=len(model_trace) + 1)

    session.decision_checkpoint = checkpoint_accepted_decision

    def structured_mapping_call(*, reason: str, turn: int) -> dict[str, Any] | None:
        nonlocal structured_mapping_attempts, last_submit_result
        if mapping_exchange is None:
            raise RuntimeError(reason)
        if structured_mapping_attempts >= 2:
            if (
                isinstance(last_submit_result, dict)
                and not last_submit_result.get("ok")
                and _promote_terminal_mapping_candidates(
                    session,
                    last_submit_result=last_submit_result,
                    model_trace=model_trace,
                )
            ):
                last_submit_result = {
                    "ok": True,
                    "accepted_work_ids": list(session.accepted_rows),
                    "remaining_work_ids": session.remaining_work_ids,
                    "promoted": "terminal_mapping_candidate",
                }
                return None
            raise MappingValidationExhausted(
                "smeta model mapping failed validation after one bounded schema repair"
            )
        remaining = [work_id for work_id in by_id if work_id not in accepted_rows]
        serialize_ids = (
            remaining[:mapping_chunk]
            if mapping_chunk > 0
            else list(remaining)
        )
        typed_bind_options: dict[str, list[dict[str, str]]] = {}
        allowed_bind_codes: dict[str, list[str]] = {}
        for work_id in serialize_ids:
            source_unit = str((by_id.get(work_id) or {}).get("unit") or "")
            seen_codes: set[str] = set()
            for candidate_code, card in (
                session.opened.get(work_id) or {}
            ).items():
                if not isinstance(card, dict):
                    continue
                code = str(card.get("norm_code") or candidate_code).strip()
                measure_unit = str(card.get("measure_unit") or "").strip()
                if (
                    not code
                    or code in seen_codes
                    or not units_compatible(source_unit, measure_unit)
                ):
                    continue
                seen_codes.add(code)
                allowed_bind_codes.setdefault(work_id, []).append(code)
                typed_bind_options.setdefault(work_id, []).append({
                    "norm_code": code,
                    "title": str(card.get("title") or "")[:240],
                    "measure_unit": measure_unit,
                    "source_ref": str(card.get("source_ref") or "")[:240],
                })
        schema = _mapping_output_schema(
            serialize_ids,
            allowed_bind_codes=allowed_bind_codes,
            allowed_coverage_targets={
                work_id: [
                    target_work_id
                    for target_work_id in by_id
                    if target_work_id != work_id
                ]
                for work_id in serialize_ids
            },
        )
        request = {
            "trigger": reason,
            "duplicate_tool_feedback": (
                "identical deterministic request already executed"
                if duplicate_feedback_signature
                else ""
            ),
            "transport_request": (
                "Serialize your own current professional decisions for every remaining_work_id "
                "listed below. Do not decide deferred_work_ids yet; LES will request those after "
                "this chunk is accepted. Do not delegate, revise or let code choose a decision. "
                "If the evidence you inspected is insufficient, record your own unbound decision. "
                "Return only the required JSON. Keep free-text fields concise: do not repeat the "
                "same card list in reason and rejection_reasons. For unbound, group candidates "
                "with the same rejection basis and return at most three grounded rejection "
                "sentences; LES attaches executed queries and opened card codes from its typed "
                "trace."
            ),
            "remaining_work_ids": serialize_ids,
            "deferred_work_ids": [
                work_id for work_id in remaining
                if work_id not in serialize_ids
            ],
            # The complete schema is already provider-enforced through Ollama's
            # ``format`` field. Repeating its several kilobytes in the prompt
            # can leave an 8K local context with too little room to close JSON.
            "output_schema": {
                "delivery": "provider_enforced_json_schema",
                "root": "rows",
                "work_ids": serialize_ids,
                "decisions": ["bind", "covered_by", "unbound"],
                "instruction": (
                    "The provider enforces the complete field-level schema; "
                    "fill every required field and return JSON only. For bind, "
                    "matched_operations, conditions_checked and overlap_resolution "
                    "must be non-empty, and candidate_evaluations must mark the "
                    "submitted norm exactly once as selected."
                ),
            },
            "validation_feedback": (
                copy.deepcopy(last_submit_result.get("errors") or [])
                if last_submit_result and not last_submit_result.get("ok")
                else []
            ),
            "typed_bind_options": typed_bind_options,
            "unit_guardrail": (
                "A bind is schema-valid only for a norm_code listed in "
                "typed_bind_options for the same work_id. Those are opened typed "
                "cards whose formal measure is convertible from the source unit. "
                "If none is professionally applicable, choose unbound; do not "
                "reinterpret a card measure or invent another norm code."
            ),
            "grounding_rule": (
                "Use only facts present in the compact opened_evidence. Do not "
                "repeat an industry, facility or application claim unless it is "
                "explicitly present in a returned title, work step, resource, unit "
                "or source_ref."
            ),
            "interpretation_help": (
                "LES tolerates harmless field/alias mistakes and can resolve a norm "
                "code mentioned in your prose only to a unique typed card that you "
                "already opened. It never creates evidence or changes your decision. "
                "Do not default to unbound because serialization is difficult: when "
                "an opened card is professionally applicable, choose bind and use its "
                "exact norm_code from typed_bind_options."
            ),
        }
        conversation.append({
            "role": "user",
            "content": json.dumps(request, ensure_ascii=False),
        })
        mapping_frame_profile = _model_request_shape(conversation, [])
        mapping_frame_profile["mapping_schema_bytes"] = len(
            json.dumps(
                schema,
                ensure_ascii=False,
                sort_keys=True,
                default=str,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        started = perf_counter()
        try:
            payload = mapping_exchange(conversation, schema) or {}
        except Exception as error:
            wait_ms = round((perf_counter() - started) * 1000, 2)
            model_trace.append({
                "turn": turn,
                "assistant": None,
                "model_wait_ms": wait_ms,
                "transport": "structured_mapping_error",
                "trigger": reason,
                "serialize_work_ids": serialize_ids,
                "error": str(error),
                "frame_profile": mapping_frame_profile,
            })
            if _is_timeout_error(error):
                blocker = {
                    "code": "structured_mapping_timeout",
                    "reason": str(error),
                    "serialize_work_ids": serialize_ids,
                }
                emit_checkpoint(incomplete_blocker=blocker)
                raise MappingTransportTimeout(str(error)) from error
            raise
        structured_mapping_attempts += 1
        wait_ms = round((perf_counter() - started) * 1000, 2)
        rows = _tool_array_argument(payload, "rows", aliases=("mapping",))
        if not rows:
            raise RuntimeError(
                "smeta model returned no rows in structured mapping response: "
                + " ".join(str(payload.get("content") or "").split())[:300]
            )
        assistant_message = {
            "role": "assistant",
            "content": json.dumps({"rows": rows}, ensure_ascii=False, default=str),
        }
        if payload.get("_les_model"):
            assistant_message["model"] = str(payload["_les_model"])
        if payload.get("_les_provider"):
            assistant_message["provider"] = str(payload["_les_provider"])
        if payload.get("_les_seed") is not None:
            assistant_message["seed"] = int(payload["_les_seed"])
        conversation.append(assistant_message)
        model_trace.append({
            "turn": turn,
            "assistant": assistant_message,
            "model_wait_ms": wait_ms,
            "transport": "structured_mapping",
            "trigger": reason,
            "serialize_work_ids": serialize_ids,
            "seed": payload.get("_les_seed"),
            "frame_profile": mapping_frame_profile,
        })
        return {
            "id": f"structured-mapping-{turn}",
            "type": "function",
            "function": {"name": "submit_lsr_mapping", "arguments": {"rows": rows}},
        }

    mapping_rows_per_call = (
        mapping_chunk if mapping_chunk > 0 else max(1, len(by_id))
    )
    evidence_repair_turn_budget = (
        _mapping_evidence_repair_turns() if mapping_exchange is not None else 0
    )
    evidence_repair_turns_remaining = (
        int(resume_state.get("evidence_repair_turns_remaining") or 0)
        if not validation_contract_changed else 0
    )
    # Grant the post-budget evidence-repair window at most once. Re-arming it on
    # every failed unbound submit kept forced remapping from running, so the
    # candidate-draft second submit never happened before the finite loop ended.
    evidence_repair_granted = bool(
        resume_state.get("evidence_repair_granted")
    ) and not validation_contract_changed
    if evidence_repair_turns_remaining > 0:
        evidence_repair_granted = True
    finalization_turns = (
        math.ceil(max(1, len(by_id)) / mapping_rows_per_call) + 1
        if mapping_exchange is not None else 0
    )
    post_repair_finalization_turns = 2 if evidence_repair_turn_budget else 0
    start_turn = max(1, int(resume_state.get("next_turn") or 1))
    for turn in range(
        start_turn,
        # After semantic repair tools the same model still needs one terminal
        # serialization turn plus one cheap schema-repair turn.  These do not
        # expand the evidence budget.
        max_turns
        + finalization_turns
        + evidence_repair_turn_budget
        + post_repair_finalization_turns
        + 1,
    ):
        started = perf_counter()
        forced_mapping = (
            (turn > max_turns and evidence_repair_turns_remaining <= 0)
            or focus_serialization_pending
        )
        active_phase = _norm_agent_phase(session)
        if (
            require_scoped_search
            and not forced_mapping
            and active_phase == "family_root"
            and session.remaining_work_ids
        ):
            root_work_ids = _phase_work_ids(session, "family_root")
            root_result = session.execute(
                "browse_norm_catalog",
                {"items": [
                    {"work_id": work_id}
                    for work_id in root_work_ids
                ]},
                turn=turn,
            )
            if not root_result.get("ok"):
                raise RuntimeError(
                    "typed FSNB root menu could not be prepared: "
                    + str(root_result.get("error") or root_result)
                )
            emit_checkpoint(next_turn=turn)
            active_phase = _norm_agent_phase(session)
        # After the model selects a table, run scoped search once without another
        # slow tool-call turn. Queries come from the VOR title; the table is the
        # model's own catalog decision.
        def _pending_auto_search_items() -> list[dict[str, Any]]:
            return [
                item
                for item in _auto_norm_search_items(session)
                if not any(
                    str(trace.get("work_id") or "") == item["work_id"]
                    for trace in session.query_trace
                )
            ]

        if (
            require_scoped_search
            and not forced_mapping
            and active_phase == "norm_search"
            and session.remaining_work_ids
        ):
            auto_items = _pending_auto_search_items()
            if auto_items:
                session.execute(
                    "search_norms_batch",
                    {"items": auto_items},
                    turn=turn,
                )
                emit_checkpoint(next_turn=turn)
                active_phase = _norm_agent_phase(session)
        if (
            require_scoped_search
            and forced_mapping
            and session.remaining_work_ids
        ):
            # Do not serialize unbound with zero searches when a table is already
            # chosen — that only burns mapping_retry on invalid unbound_evidence.
            pending_search = _pending_auto_search_items()
            if pending_search:
                session.execute(
                    "search_norms_batch",
                    {"items": pending_search},
                    turn=turn,
                )
                focus_serialization_pending = False
                forced_mapping = False
                previous_call_signature = ""
                duplicate_feedback_signature = ""
                emit_checkpoint(next_turn=turn)
                active_phase = _norm_agent_phase(session)
        # After opened cards: give one free turn (bind / broaden / more read),
        # then force mapping. Immediate force caused mass unbound when the
        # first table was wrong and broaden was unavailable.
        if (
            require_scoped_search
            and not forced_mapping
            and active_phase == "norm_evidence"
            and any(
                bool(session.opened.get(work_id))
                for work_id in _phase_work_ids(session, "norm_evidence")
            )
        ):
            opened_evidence_turns += 1
            if opened_evidence_turns >= 2:
                focus_serialization_pending = True
                forced_mapping = True
                focus_serialization_reason = (
                    "opened typed cards already reviewed; serialize "
                    "bind/covered_by/unbound for the active work_id now"
                )
        elif active_phase != "norm_evidence":
            opened_evidence_turns = 0
        active_tools = (
            _phase_norm_tools(
                active_phase,
                include_route_cache=bool(session.route_evidence_cache),
                active_work_ids=_phase_work_ids(session, active_phase),
                current_node_ids={
                    work_id: str(session.catalog_current_nodes.get(work_id) or "")
                    for work_id in _phase_work_ids(session, active_phase)
                },
                visible_child_node_ids={
                    work_id: [
                        str(child.get("node_id") or "")
                        for child in (
                            session.catalog_menus.get(work_id, {}).get(
                                session.catalog_current_nodes.get(work_id) or "",
                                [],
                            )
                        )
                        if str(child.get("node_id") or "")
                    ]
                    for work_id in _phase_work_ids(session, active_phase)
                },
                visible_evidence_fields=list(dict.fromkeys(
                    field
                    for work_id in _phase_work_ids(session, active_phase)
                    for child in (
                        session.catalog_menus.get(work_id, {}).get(
                            session.catalog_current_nodes.get(work_id) or "",
                            [],
                        )
                    )
                    for field in (
                        "title", "official_name", "purpose", "typical_scope",
                        "not_for", "source_ref", "cipher", "norm_count",
                    )
                    if child.get(field) not in (None, "", [])
                )),
            )
            if require_scoped_search
            else [
                tool
                for tool in _batch_norm_tools()
                if str((tool.get("function") or {}).get("name") or "")
                not in {
                    "submit_lsr_mapping",
                    *(
                        ()
                        if session.route_evidence_cache
                        else ("reuse_norm_catalog_route",)
                    ),
                }
            ]
        )
        if progress:
            progress({
                "phase": "model_wait", "status": "started",
                "label": (
                    "Смета: модель фиксирует mapping"
                    if forced_mapping else f"Смета: модель выполняет ход {turn}"
                ),
                "turn": turn,
            })
        assistant: dict[str, Any] = {}
        request_shape: dict[str, Any] = {}
        if forced_mapping:
            _prune_stale_tool_evidence(conversation)
            refresh_agent_working_memory()
            repair_mapping = bool(last_submit_result and not last_submit_result.get("ok"))
            try:
                mapping_call = structured_mapping_call(
                    reason=(
                        "previous structured mapping failed validation; resubmit only "
                        "the remaining work_id values using the returned errors"
                        if repair_mapping else
                        "the current one-row focus has typed evidence and later-row "
                        "tool calls were deferred; serialize your own focus decision now"
                        if focus_serialization_pending
                        and not focus_serialization_reason
                        else focus_serialization_reason
                        if focus_serialization_pending else
                        f"smeta evidence tool budget exhausted after {max_turns} model turns"
                    ),
                    turn=turn,
                )
            except MappingValidationExhausted as error:
                return session.result(
                    model_trace=model_trace,
                    agent_trace={
                        "mode": "model_batch_rag_tools",
                        "turns": turn,
                        "context_metrics": context_metrics,
                        "status": "mapping_validation_exhausted",
                    },
                    allow_incomplete=True,
                    incomplete_blocker={
                        "code": "mapping_validation_exhausted",
                        "reason": str(error),
                        "remaining_work_ids": list(session.remaining_work_ids),
                    },
                )
            if mapping_call is None:
                return session.result(
                    model_trace=model_trace,
                    agent_trace={
                        "mode": "model_batch_rag_tools",
                        "turns": turn,
                        "context_metrics": context_metrics,
                        "status": "candidate_draft_promoted",
                    },
                )
            calls = [mapping_call]
            model_wait_ms = float(model_trace[-1].get("model_wait_ms") or 0.0)
        else:
            _prune_stale_tool_evidence(conversation)
            refresh_agent_working_memory()
            request_shape = _model_request_shape(conversation, active_tools)
            assistant = exchange(conversation, active_tools) or {}
            model_wait_ms = round((perf_counter() - started) * 1000, 2)
            calls = [call for call in (assistant.get("tool_calls") or []) if isinstance(call, dict)]
            assistant_message = {
                "role": "assistant",
                "content": str(assistant.get("content") or "").strip() or None,
                "tool_calls": calls,
            }
            if assistant.get("thinking"):
                assistant_message["thinking"] = str(assistant["thinking"])
            if assistant.get("_les_model"):
                assistant_message["model"] = str(assistant["_les_model"])
            if assistant.get("_les_provider"):
                assistant_message["provider"] = str(assistant["_les_provider"])
            if assistant.get("_les_seed") is not None:
                assistant_message["seed"] = int(assistant["_les_seed"])
            if assistant.get("_les_fallback_from"):
                assistant_message["fallback_from"] = str(assistant["_les_fallback_from"])
            conversation.append(assistant_message)
            model_trace.append({
                "turn": turn,
                "phase": active_phase,
                "assistant": assistant_message,
                "model_wait_ms": model_wait_ms,
                "seed": assistant.get("_les_seed"),
                "frame_profile": {
                    **request_shape,
                    **dict(assistant.get("_les_generation_metrics") or {}),
                    "model_wait_sec": round(model_wait_ms / 1000.0, 4),
                    "tool_time_sec": 0.0,
                },
            })
            if not calls:
                xml_tool_error = str(assistant.get("_les_xml_tool_error") or "").strip()
                has_row_evidence = any(
                    any(
                        str(item.get("work_id") or "") == work_id
                        for item in session.query_trace
                    )
                    or bool(session.opened.get(work_id))
                    for work_id in session.remaining_work_ids
                )
                if xml_tool_error and not has_row_evidence:
                    conversation.append({
                        "role": "user",
                        "content": json.dumps(
                            {
                                "recovery_contract": "smeta_xml_tool_recovery_v1",
                                "instruction": (
                                    "Previous tool call XML was malformed. Call "
                                    "exactly one valid catalog/search tool now "
                                    "with well-formed parameters."
                                ),
                                "provider_error": xml_tool_error[:180],
                            },
                            ensure_ascii=False,
                        ),
                    })
                    previous_call_signature = ""
                    emit_checkpoint(next_turn=turn + 1)
                    continue
                done_reason = str(assistant.get("_les_done_reason") or "unknown")
                eval_count = assistant.get("_les_eval_count")
                model_text = " ".join(str(assistant.get("content") or "").split())[:400]
                failure = (
                    (
                        "smeta provider tool XML malformed after retry; serialize "
                        "with available evidence: "
                        + xml_tool_error[:180]
                    )
                    if xml_tool_error else
                    (
                        "smeta model ended the document workflow without a tool call: "
                        f"done_reason={done_reason}, eval_count={eval_count}, "
                        f"model_text={model_text or '<empty>'}"
                    )
                )
                try:
                    mapping_call = structured_mapping_call(reason=failure, turn=turn)
                except MappingValidationExhausted as error:
                    return session.result(
                        model_trace=model_trace,
                        agent_trace={
                            "mode": "model_batch_rag_tools",
                            "turns": turn,
                            "context_metrics": context_metrics,
                            "status": "mapping_validation_exhausted",
                        },
                        allow_incomplete=True,
                        incomplete_blocker={
                            "code": "mapping_validation_exhausted",
                            "reason": str(error),
                            "remaining_work_ids": list(session.remaining_work_ids),
                        },
                    )
                if mapping_call is None:
                    return session.result(
                        model_trace=model_trace,
                        agent_trace={
                            "mode": "model_batch_rag_tools",
                            "turns": turn,
                            "context_metrics": context_metrics,
                            "status": "candidate_draft_promoted",
                        },
                    )
                calls = [mapping_call]
        frame_profile = dict(
            (model_trace[-1] if model_trace else {}).get("frame_profile") or {}
        )
        context_metrics.append({
            "turn": turn,
            "phase": active_phase,
            "prompt_chars": len(json.dumps(conversation, ensure_ascii=False, default=str)),
            "tool_schema_chars": len(
                json.dumps(active_tools, ensure_ascii=False, default=str)
            ),
            "model_wait_ms": model_wait_ms,
            "tool_calls": len(calls),
            "structured_mapping": forced_mapping or not bool(assistant.get("tool_calls")),
            **frame_profile,
        })
        if progress:
            progress({
                "phase": "model_wait", "status": "done",
                "label": (
                    "Смета: модель зафиксировала mapping"
                    if forced_mapping else f"Смета: модель завершила ход {turn}"
                ),
                "turn": turn, "model_wait_ms": model_wait_ms,
            })
        call_signature = json.dumps(
            [
                {
                    "name": str(((call.get("function") or {}).get("name") or "")),
                    "arguments": _tool_arguments(call),
                }
                for call in calls
            ],
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        if call_signature == previous_call_signature:
            failure = (
                "smeta model repeated the same deterministic tool call without progress: "
                + call_signature[:500]
            )
            if mapping_exchange is None:
                raise RuntimeError(failure)
            has_row_evidence = any(
                any(
                    str(item.get("work_id") or "") == work_id
                    for item in session.query_trace
                )
                or bool(session.opened.get(work_id))
                for work_id in session.remaining_work_ids
            )
            # Force mapping only when search/read already happened. Early
            # identical catalog retries must not jump to unbound mapping.
            if has_row_evidence:
                if duplicate_feedback_signature != call_signature:
                    duplicate_feedback_signature = call_signature
                    for call_index, call in enumerate(calls, 1):
                        name = str(((call.get("function") or {}).get("name") or ""))
                        result = {
                            "ok": False,
                            "error": "identical deterministic request already executed; no new evidence was produced",
                            "force_mapping_serialization": True,
                        }
                        conversation.append({
                            "role": "tool",
                            "tool_call_id": str(
                                call.get("id") or f"duplicate-{turn}-{call_index}"
                            ),
                            "name": name,
                            "content": json.dumps(result, ensure_ascii=False),
                        })
                        model_trace[-1].setdefault("tool_results", []).append(
                            {"name": name, "result": result}
                        )
                    focus_serialization_pending = True
                    focus_serialization_reason = failure
                    emit_checkpoint(next_turn=turn + 1)
                    continue
                try:
                    mapping_call = structured_mapping_call(reason=failure, turn=turn)
                except MappingValidationExhausted as error:
                    return session.result(
                        model_trace=model_trace,
                        agent_trace={
                            "mode": "model_batch_rag_tools",
                            "turns": turn,
                            "context_metrics": context_metrics,
                            "status": "mapping_validation_exhausted",
                        },
                        allow_incomplete=True,
                        incomplete_blocker={
                            "code": "mapping_validation_exhausted",
                            "reason": str(error),
                            "remaining_work_ids": list(session.remaining_work_ids),
                        },
                    )
                if mapping_call is None:
                    return session.result(
                        model_trace=model_trace,
                        agent_trace={
                            "mode": "model_batch_rag_tools",
                            "turns": turn,
                            "context_metrics": context_metrics,
                            "status": "candidate_draft_promoted",
                        },
                    )
                calls = [mapping_call]
                call_signature = json.dumps([{
                    "name": "submit_lsr_mapping",
                    "arguments": _tool_arguments(calls[0]),
                }], ensure_ascii=False, sort_keys=True, default=str)
            else:
                for call_index, call in enumerate(calls, 1):
                    name = str(((call.get("function") or {}).get("name") or ""))
                    result = {
                        "ok": False,
                        "error": (
                            "identical catalog request without search/read evidence; "
                            "choose a different shown child, broaden, or continue"
                        ),
                        "force_mapping_serialization": False,
                    }
                    conversation.append({
                        "role": "tool",
                        "tool_call_id": str(
                            call.get("id") or f"duplicate-{turn}-{call_index}"
                        ),
                        "name": name,
                        "content": json.dumps(result, ensure_ascii=False),
                    })
                    model_trace[-1].setdefault("tool_results", []).append(
                        {"name": name, "result": result}
                    )
                conversation.append({
                    "role": "user",
                    "content": json.dumps(
                        {
                            "recovery_contract": "smeta_catalog_duplicate_recovery_v1",
                            "instruction": (
                                "Repeat rejected. Pick a different shown child with "
                                "evidence, broaden to the parent, or continue the "
                                "typed route. Do not submit unbound yet."
                            ),
                        },
                        ensure_ascii=False,
                    ),
                })
                previous_call_signature = ""
                duplicate_feedback_signature = ""
                emit_checkpoint(next_turn=turn + 1)
                continue
        else:
            duplicate_feedback_signature = ""
        previous_call_signature = call_signature

        submitted: dict[str, dict[str, Any]] | None = None
        pending_user_question: dict[str, Any] | None = None
        accepted_before_turn = len(accepted_rows)
        tools_started = perf_counter()
        for call_index, call in enumerate(calls, 1):
            call_id = str(call.get("id") or f"batch-{turn}-{call_index}")
            name = str(((call.get("function") or {}).get("name") or ""))
            args = _tool_arguments(call)
            focus_guard = _focus_serialization_guard(
                session,
                args,
                mapping_chunk=mapping_chunk,
            )
            if focus_guard is None:
                result = session.execute(name, args, turn=turn)
            else:
                result = focus_guard
                focus_serialization_pending = True
                focus_serialization_reason = str(
                    result.get("error") or ""
                )
            if bool(result.get("force_mapping_serialization")):
                focus_serialization_pending = True
                focus_serialization_reason = str(
                    result.get("error") or focus_serialization_reason
                )
            if bool(result.get("requires_user_input")) and isinstance(
                result.get("pending_question"), dict
            ):
                pending_user_question = copy.deepcopy(
                    result["pending_question"]
                )
            conversation.append({
                "role": "tool", "tool_call_id": call_id, "name": name,
                "content": json.dumps(result, ensure_ascii=False, default=str),
            })
            model_trace[-1].setdefault("tool_results", []).append({"name": name, "result": result})
            if name == "submit_lsr_mapping" and isinstance(result, dict):
                last_submit_result = result
                if submit_requires_more_evidence(result):
                    structured_mapping_attempts = 0
                    focus_serialization_pending = False
                    previous_call_signature = ""
                    duplicate_feedback_signature = ""
                    deny_exact = any(
                        "denies applicability" in str(detail)
                        or "broaden to another table" in str(detail)
                        for error in (result.get("errors") or [])
                        if isinstance(error, dict)
                        for detail in (error.get("details") or [])
                    )
                    if deny_exact:
                        opened_evidence_turns = 0
                        conversation.append({
                            "role": "user",
                            "content": json.dumps(
                                {
                                    "recovery_contract": (
                                        "smeta_exact_deny_broaden_v1"
                                    ),
                                    "instruction": (
                                        "Your last exact bind contradicted its own "
                                        "reason. Do not resubmit that norm as exact. "
                                        "Call broaden_norm_catalog toward catalog:root "
                                        "or another family/table, then search/read, "
                                        "or submit an honest unbound."
                                    ),
                                    "work_ids": [
                                        str(error.get("work_id") or "")
                                        for error in (result.get("errors") or [])
                                        if isinstance(error, dict)
                                        and str(error.get("work_id") or "").strip()
                                    ],
                                },
                                ensure_ascii=False,
                            ),
                        })
                    if (
                        turn >= max_turns
                        and evidence_repair_turn_budget > 0
                        and not evidence_repair_granted
                    ):
                        evidence_repair_turns_remaining = evidence_repair_turn_budget
                        evidence_repair_granted = True
            submitted = dict(session.accepted_rows) if session.complete else None
        tool_time_sec = round(max(0.0, perf_counter() - tools_started), 4)
        if model_trace:
            model_trace[-1].setdefault("frame_profile", {})[
                "tool_time_sec"
            ] = tool_time_sec
            model_trace[-1]["frame_profile"]["turn_total_sec"] = round(
                float(model_trace[-1]["frame_profile"].get("model_wait_sec") or 0.0)
                + tool_time_sec,
                4,
            )
        if context_metrics:
            context_metrics[-1]["tool_time_sec"] = tool_time_sec
            context_metrics[-1]["turn_total_sec"] = round(
                float(context_metrics[-1].get("model_wait_sec") or 0.0)
                + tool_time_sec,
                4,
            )
        if len(accepted_rows) > accepted_before_turn:
            structured_mapping_attempts = 0
            focus_serialization_pending = False
            focus_serialization_reason = ""
        if not forced_mapping and turn > max_turns:
            evidence_repair_turns_remaining = max(
                0, evidence_repair_turns_remaining - 1
            )
        emit_checkpoint(next_turn=turn + 1)
        if pending_user_question is not None:
            partial = session.result(
                model_trace=model_trace,
                agent_trace={
                    "mode": "model_batch_rag_tools",
                    "turns": turn,
                    "context_metrics": context_metrics,
                    "status": "awaiting_user_input",
                },
                allow_incomplete=True,
                incomplete_blocker={
                    "code": "awaiting_user_input",
                    "reason": pending_user_question.get("reason") or "",
                },
            )
            partial.update({
                "status": "awaiting_user_input",
                "requires_user_input": True,
                "pending_question": pending_user_question,
            })
            return partial
        if submitted is not None:
            return session.result(
                model_trace=model_trace,
                agent_trace={
                    "mode": "model_batch_rag_tools",
                    "turns": turn,
                    "context_metrics": context_metrics,
                    "seed": next(
                        (
                            item.get("seed")
                            for item in model_trace
                            if item.get("seed") is not None
                        ),
                        None,
                    ),
                },
            )
    if last_submit_result and not last_submit_result.get("ok"):
        promoted = _promote_terminal_mapping_candidates(
            session,
            last_submit_result=last_submit_result,
            model_trace=model_trace,
        )
        if promoted and session.complete:
            return session.result(
                model_trace=model_trace,
                agent_trace={
                    "mode": "model_batch_rag_tools",
                    "turns": len(model_trace),
                    "context_metrics": context_metrics,
                    "status": "candidate_draft_promoted",
                    "seed": next(
                        (
                            item.get("seed")
                            for item in model_trace
                            if item.get("seed") is not None
                        ),
                        None,
                    ),
                },
            )
        errors = json.dumps(
            (last_submit_result.get("errors") or [])[:8],
            ensure_ascii=False,
            default=str,
        )
        return session.result(
            model_trace=model_trace,
            agent_trace={
                "mode": "model_batch_rag_tools",
                "turns": len(model_trace),
                "context_metrics": context_metrics,
                "status": "mapping_validation_exhausted",
                "seed": next(
                    (
                        item.get("seed")
                        for item in model_trace
                        if item.get("seed") is not None
                    ),
                    None,
                ),
            },
            allow_incomplete=True,
            incomplete_blocker={
                "code": "mapping_validation_exhausted",
                "reason": (
                    "smeta model mapping failed validation after bounded repair: "
                    f"{errors[:800]}"
                ),
                "remaining_work_ids": list(session.remaining_work_ids),
            },
        )
    return session.result(
        model_trace=model_trace,
        agent_trace={
            "mode": "model_batch_rag_tools",
            "turns": len(model_trace),
            "context_metrics": context_metrics,
            "status": "mapping_turns_exhausted",
        },
        allow_incomplete=True,
        incomplete_blocker={
            "code": "mapping_turns_exhausted",
            "reason": (
                f"smeta model did not submit mapping within {max_turns} model turns"
            ),
            "remaining_work_ids": list(session.remaining_work_ids),
        },
    )


def _model_resource_bindings(work_id: str, item: dict[str, Any], source_row: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "work_id": work_id,
            "action": str(action.get("action") or ""),
            "selected_by": "model",
            "resource_name": str(action.get("resource_name") or ""),
            "resource_code": str(action.get("resource_code") or ""),
            "unit": str(action.get("unit") or ""),
            "quantity": action.get("quantity"),
            "quantity_basis": str(action.get("quantity_basis") or ""),
            "target_resource_code": str(action.get("target_resource_code") or ""),
            "target_resource_name": str(action.get("target_resource_name") or ""),
            "reason": str(action.get("reason") or ""),
            "basis_ref": str(action.get("basis_ref") or ""),
            "explicit_price": action.get("explicit_price"),
            "price_source_ref": str(action.get("price_source_ref") or ""),
            "source_refs": tuple(str(ref) for ref in (source_row.get("source_refs") or ()) if str(ref)),
        }
        for action in (item.get("resource_actions") or [])
        if isinstance(action, dict)
    ]


def _batch_norm_tools() -> list[dict[str, Any]]:
    string_array = {"type": "array", "items": {"type": "string"}}
    candidate_evaluation = {
        "type": "object",
        "properties": {
            "candidate_code": {"type": "string"},
            "operation_match": {
                "type": "string", "enum": ["exact", "partial", "none", "unknown"],
            },
            "object_match": {
                "type": "string", "enum": ["exact", "partial", "none", "unknown"],
            },
            "unit_match": {
                "type": "string", "enum": ["compatible", "convertible", "conflict", "unknown"],
            },
            "scope_match": {
                "type": "string", "enum": ["exact", "partial", "foreign", "unknown"],
            },
            "foreign_resources": string_array,
            "decision": {"type": "string", "enum": ["selected", "rejected", "uncertain"]},
            "reason": {"type": "string"},
        },
        "required": [
            "candidate_code", "operation_match", "object_match", "unit_match", "scope_match",
            "foreign_resources", "decision", "reason",
        ],
    }
    technology_check = {
        "type": "object",
        "properties": {
            "matched_operations": string_array,
            "missing_operations": string_array,
            "extra_operations": string_array,
            "foreign_resources": string_array,
            "overlaps_with_work_ids": string_array,
            "overlap_resolution": {"type": "string"},
            "conditions_checked": string_array,
            "unresolved_conditions": string_array,
            "conclusion": {"type": "string", "enum": ["applicable", "applicable_with_limitations"]},
        },
        "required": [
            "matched_operations", "missing_operations", "extra_operations", "foreign_resources",
            "overlaps_with_work_ids", "overlap_resolution", "conditions_checked",
            "unresolved_conditions", "conclusion",
        ],
    }
    unbound_evidence = {
        "type": "object",
        "properties": {
            "queries_used": {"type": "array", "items": {"type": "string"}, "minItems": 2},
            "opened_norm_codes": string_array,
            "rejection_reasons": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "coverage_checked": {"type": "string"},
        },
        "required": ["queries_used", "opened_norm_codes", "rejection_reasons", "coverage_checked"],
    }
    resource_action = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["add", "replace", "exclude", "reuse"]},
            "resource_name": {"type": "string"},
            "resource_code": {"type": "string"},
            "unit": {"type": "string"},
            "quantity": {"type": "number"},
            "quantity_basis": {"type": "string", "enum": ["explicit", "target_norm", "source_work"]},
            "target_resource_code": {"type": "string"},
            "target_resource_name": {"type": "string"},
            "reason": {"type": "string"},
            "basis_ref": {"type": "string"},
            "explicit_price": {"type": "number"},
            "price_source_ref": {"type": "string"},
        },
        "required": ["action", "reason", "basis_ref"],
    }
    mapping_row = {
        "type": "object",
        "properties": {
            "work_id": {"type": "string"},
            "decision": {"type": "string", "enum": ["bind", "covered_by", "unbound"]},
            "norm_code": {"type": "string"},
            "selection_kind": {"type": "string", "enum": ["exact", "analog"]},
            "applicability": {"type": "string", "enum": ["exact", "close_analog", "weak_analog"]},
            "analog_limitations": string_array,
            "candidate_evaluations": {
                "type": "array", "items": candidate_evaluation, "minItems": 1,
            },
            "technology_check": technology_check,
            "unbound_evidence": unbound_evidence,
            "nr_sp_rule_id": {"type": "string"},
            "covered_by_work_id": {"type": "string"},
            "resource_actions": {"type": "array", "items": resource_action},
            "reason": {"type": "string"},
        },
        "required": ["work_id", "decision", "reason"],
        "allOf": [
            {
                "if": {"properties": {"decision": {"const": "bind"}}, "required": ["decision"]},
                "then": {"required": [
                    "norm_code", "selection_kind", "applicability",
                    "analog_limitations", "candidate_evaluations", "technology_check",
                ]},
            },
            {
                "if": {"properties": {"decision": {"const": "covered_by"}}, "required": ["decision"]},
                "then": {"required": ["covered_by_work_id"]},
            },
            {
                "if": {"properties": {"decision": {"const": "unbound"}}, "required": ["decision"]},
                "then": {"required": ["unbound_evidence"]},
            },
        ],
    }
    return [
        {
            "type": "function",
            "function": {
                "name": "browse_norm_catalog",
                "description": (
                    "Open the typed FSNB root with only work_id. Every later call is one "
                    "evidence-bound transition over real children of current_node_id: continue, "
                    "ask, broaden or unbound. Continue may select only an exact shown node_id; "
                    "broaden returns exactly to the parent. The model supplies professional "
                    "applicability and evidence, while code validates adjacency and references. "
                    "Only family→collection→section→table unlocks scoped norm search."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "items": {"type": "array", "items": {"type": "object", "properties": {
                            "work_id": {"type": "string"},
                            "current_node_id": {
                                "type": "string",
                                "description": (
                                    "Exact current catalog node returned by the "
                                    "previous tool result."
                                ),
                            },
                            "decision": {
                                "type": "string",
                                "enum": [
                                    "continue",
                                    "ask",
                                    "broaden",
                                    "unbound",
                                ],
                            },
                            "selected_node_id": {
                                "type": "string",
                                "description": (
                                    "For continue only: one exact node_id from "
                                    "the currently shown child menu."
                                ),
                            },
                            "evidence": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "source_node_id": {"type": "string"},
                                        "field": {"type": "string"},
                                        "claim": {"type": "string"},
                                    },
                                    "required": [
                                        "source_node_id",
                                        "field",
                                        "claim",
                                    ],
                                },
                            },
                            "rejected_nodes": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "node_id": {"type": "string"},
                                        "reason": {"type": "string"},
                                    },
                                    "required": ["node_id", "reason"],
                                },
                            },
                            "missing_facts": {
                                "type": "array",
                                "items": {"type": "string"},
                                "maxItems": 8,
                            },
                            "question": {
                                "type": "object",
                                "properties": {
                                    "question_kind": {
                                        "type": "string",
                                        "enum": [
                                            "physical_installation",
                                            "project_condition",
                                        ],
                                    },
                                    "text": {"type": "string"},
                                    "reason": {"type": "string"},
                                    "options": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "minItems": 2,
                                        "maxItems": 8,
                                    },
                                },
                                "required": [
                                    "question_kind",
                                    "text",
                                    "reason",
                                    "options",
                                ],
                            },
                            "family": {"type": "string", "description": "Norm family such as ГЭСН, ГЭСНм, ГЭСНр. Empty returns families."},
                            "work_features": {
                                "type": "object",
                                "description": (
                                    "Model-authored professional feature card created before "
                                    "family selection and preserved in the checkpoint."
                                ),
                                "properties": {
                                    "domain": {"type": "string"},
                                    "system": {"type": "string"},
                                    "equipment": {"type": "string"},
                                    "operation": {"type": "string"},
                                    "assembly_state": {
                                        "type": "string",
                                        "enum": [
                                            "empty",
                                            "factory_assembled",
                                            "site_assembled",
                                            "component",
                                            "unknown",
                                        ],
                                    },
                                    "installation_context": {"type": "string"},
                                    "unknowns": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                },
                                "required": [
                                    "domain",
                                    "system",
                                    "equipment",
                                    "operation",
                                    "assembly_state",
                                    "installation_context",
                                    "unknowns",
                                ],
                            },
                            "collection": {"type": "string", "description": "Two-digit collection selected by the model. Empty returns collections."},
                            "section": {
                                "type": "string",
                                "description": (
                                    "Encoded section node selected from the collection menu, "
                                    "such as 10-04. The official source may label it 'Отдел 4'."
                                ),
                            },
                            "table": {"type": "string", "description": "Official table code selected from the chosen section, such as 10-04-067."},
                            "confirm_scope": {
                                "type": "boolean",
                                "description": (
                                    "For a collection, omit/false to read its passport. Set true "
                                    "only on the next call after checking the returned passport "
                                    "against the work's functional system."
                                ),
                            },
                            "passport_evidence": {
                                "type": "string",
                                "description": "Exact title, source or representative section copied from the previewed collection_passport.",
                            },
                            "scope_reason": {
                                "type": "string",
                                "description": (
                                    "Required when selecting family or collection: why this "
                                    "normative scope matches the work. It must come from the model, "
                                    "not LES code. This explanation is audit text and is never "
                                    "used as the catalog retrieval query."
                                ),
                            },
                            "catalog_query": {
                                "type": "string",
                                "description": (
                                    "With family only: required 2-12 word estimating query with "
                                    "functional system, equipment and operation; for example "
                                    "'монтаж напольного телекоммуникационного шкафа СКС'. "
                                    "With a selected section: "
                                    "required 2-12 word phrase naming the equipment, operation or "
                                    "measure used to rank tables inside that section. Never include "
                                    "catalog history, exclusions or instructions."
                                ),
                            },
                            "confidence": {
                                "type": "string",
                                "enum": ["low", "medium", "high"],
                                "description": "Required when selecting family or collection.",
                            },
                        }, "required": ["work_id"]}},
                    },
                    "required": ["items"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "reuse_norm_catalog_route",
                "description": (
                    "Reuse a typed family→collection→section→table route shown in "
                    "route_evidence_cache for one or more current work rows. The model "
                    "must decide and explain applicability for every target work_id. "
                    "This skips repeated navigation only; it never selects a norm and "
                    "search_norms_batch plus read_norms_batch remain mandatory."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "work_id": {"type": "string"},
                                    "cache_id": {"type": "string"},
                                    "reason": {
                                        "type": "string",
                                        "description": (
                                            "Model-authored reason why the cached "
                                            "catalog scope is applicable to this row."
                                        ),
                                    },
                                    "confidence": {
                                        "type": "string",
                                        "enum": ["low", "medium", "high"],
                                    },
                                },
                                "required": [
                                    "work_id",
                                    "cache_id",
                                    "reason",
                                    "confidence",
                                ],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["items"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_norms_batch",
                "description": (
                    "List all norms of model-selected official tables for one or more "
                    "source rows. RIM does not permit collection-wide or global search."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "items": {"type": "array", "items": {"type": "object", "properties": {
                            "work_id": {"type": "string"},
                            "query": {"type": "string", "description": "One search formulation. Repeat the work_id in another item or later call for another formulation."},
                            "search_intent": {
                                "type": "string",
                                "enum": [
                                    "source_literal", "fsnb_technology", "key_operation",
                                    "equipment_or_measure", "composite_coverage",
                                ],
                                "description": "Meaningfully distinct search strategy, not a wording permutation.",
                            },
                            "scope_mode": {
                                "type": "string",
                                "enum": ["scoped"],
                                "description": (
                                    "Model-owned scoped retrieval plan. Both base_types and "
                                    "collections must have been selected from the typed catalog. "
                                    "Global all-base search is not available in document/RIM mapping."
                                ),
                            },
                            "base_types": {"type": "array", "items": {"type": "string"}, "description": "Families chosen by the model after catalog browse. RIM uses one family per item; repeat the item for another family."},
                            "collections": {"type": "array", "items": {"type": "string"}, "description": "Collection numbers chosen by the model after catalog browse. RIM uses one collection per item; repeat the item for another collection."},
                            "table_codes": {"type": "array", "items": {"type": "string"}, "minItems": 1, "description": "Required official table code selected through family→collection→section→table. The tool returns the complete row menu without ranking."},
                            "limit": {"type": "integer", "minimum": 1}, "page": {"type": "integer", "minimum": 0},
                        }, "required": [
                            "work_id", "query", "search_intent", "scope_mode",
                            "base_types", "collections", "table_codes",
                        ]}},
                    },
                    "required": ["items"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_norms_batch",
                "description": (
                    "Read full typed norm cards selected by the model. In RIM, send at most "
                    "two cards total per call: the strongest candidate and one comparison "
                    "card, possibly for two different work rows."
                ),
                "parameters": {"type": "object", "properties": {
                    "items": {"type": "array", "items": {"type": "object", "properties": {
                        "work_id": {"type": "string"},
                        "norm_code": {"type": "string", "description": "One candidate code. Repeat the work_id in another item to open another code."},
                        "include_resources": {"type": "boolean", "description": "Return the full resource list when resource composition or edits must be reviewed."},
                    }, "required": ["work_id", "norm_code"]}},
                }, "required": ["items"]},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "submit_lsr_mapping",
                "description": "Submit one or more completed professional row decisions. Call repeatedly until every remaining work_id is accepted; LES then calculates and creates XLSX.",
                "parameters": {"type": "object", "properties": {
                    "rows": {"type": "array", "items": mapping_row},
                }, "required": ["rows"]},
            },
        },
    ]


def batch_norm_tools() -> list[dict[str, Any]]:
    """Public copy of the canonical batch norm contract for RIM agents."""
    return copy.deepcopy(_batch_norm_tools())


def _mapping_output_schema(
    remaining_work_ids: list[str],
    *,
    allowed_bind_codes: dict[str, list[str]] | None = None,
    allowed_coverage_targets: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Build a compact decision-specific transport schema for local models.

    The canonical submit contract stays rich because bind decisions need a
    complete professional comparison and technology check.  A local model must
    not, however, serialize every bind-only field when its decision is
    ``unbound`` or ``covered_by``.  The variants below preserve the model-owned
    decision while leaving executed queries and opened-card codes to the
    deterministic trace alignment in :meth:`SmetaNormToolSession._submit`.
    """
    submit_tool = next(
        tool for tool in _batch_norm_tools()
        if str((tool.get("function") or {}).get("name") or "") == "submit_lsr_mapping"
    )
    parameters = json.loads(json.dumps(submit_tool["function"]["parameters"], ensure_ascii=False))
    canonical_row = parameters["properties"]["rows"]["items"]
    properties = canonical_row["properties"]
    work_id = copy.deepcopy(properties["work_id"])
    work_id["enum"] = list(remaining_work_ids)

    def variant(
        decision: str,
        property_names: tuple[str, ...],
        required: tuple[str, ...],
        *,
        work_ids: list[str] | None = None,
        property_overrides: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        selected = {
            name: copy.deepcopy(properties[name])
            for name in property_names
        }
        selected["work_id"] = copy.deepcopy(work_id)
        selected["work_id"]["enum"] = list(work_ids or remaining_work_ids)
        for name, override in (property_overrides or {}).items():
            selected[name] = copy.deepcopy(override)
        selected["decision"] = {
            "type": "string",
            "enum": [decision],
        }
        if "reason" in selected:
            selected["reason"]["maxLength"] = 480
        if "analog_limitations" in selected:
            selected["analog_limitations"].setdefault("maxItems", 4)
            selected["analog_limitations"]["items"]["maxLength"] = 180
        if "candidate_evaluations" in selected:
            evaluations = selected["candidate_evaluations"]
            evaluations["maxItems"] = 3
            evaluations["description"] = (
                "Evaluate opened candidates only. Exactly one entry must use "
                "decision=selected and its candidate_code must equal norm_code."
            )
            evaluation_properties = evaluations["items"]["properties"]
            evaluation_properties["reason"]["maxLength"] = 280
            evaluation_properties["foreign_resources"]["maxItems"] = 5
            evaluation_properties["foreign_resources"]["items"]["maxLength"] = 160
        if "technology_check" in selected:
            technology_properties = selected["technology_check"]["properties"]
            for name in (
                "matched_operations", "missing_operations", "extra_operations",
                "foreign_resources", "overlaps_with_work_ids",
                "conditions_checked", "unresolved_conditions",
            ):
                technology_properties[name]["maxItems"] = 6
                technology_properties[name]["items"]["maxLength"] = 180
            technology_properties["matched_operations"]["minItems"] = 1
            technology_properties["conditions_checked"]["minItems"] = 1
            technology_properties["overlap_resolution"]["maxLength"] = 240
            technology_properties["overlap_resolution"]["minLength"] = 1
        return {
            "type": "object",
            "properties": selected,
            "required": ["work_id", "decision", *required],
            "additionalProperties": False,
        }

    bind_variants: list[dict[str, Any]] = []
    bind_property_names = (
        "norm_code", "selection_kind", "applicability",
        "analog_limitations", "candidate_evaluations",
        "technology_check", "nr_sp_rule_id", "resource_actions", "reason",
    )
    bind_required = (
        "norm_code", "selection_kind", "applicability",
        "analog_limitations", "candidate_evaluations",
        "technology_check", "reason",
    )

    def append_bind_variants(
        *,
        work_ids: list[str] | None = None,
        codes: list[str] | None = None,
    ) -> None:
        norm_override = (
            {"norm_code": {"type": "string", "enum": codes}}
            if codes is not None
            else {}
        )
        exact_limitations = copy.deepcopy(properties["analog_limitations"])
        exact_limitations["maxItems"] = 0
        analog_limitations = copy.deepcopy(properties["analog_limitations"])
        analog_limitations["minItems"] = 1
        bind_variants.extend([
            variant(
                "bind",
                bind_property_names,
                bind_required,
                work_ids=work_ids,
                property_overrides={
                    **norm_override,
                    "selection_kind": {"type": "string", "enum": ["exact"]},
                    "applicability": {"type": "string", "enum": ["exact"]},
                    "analog_limitations": exact_limitations,
                },
            ),
            variant(
                "bind",
                bind_property_names,
                bind_required,
                work_ids=work_ids,
                property_overrides={
                    **norm_override,
                    "selection_kind": {"type": "string", "enum": ["analog"]},
                    "applicability": {
                        "type": "string",
                        "enum": ["close_analog", "weak_analog"],
                    },
                    "analog_limitations": analog_limitations,
                },
            ),
        ])

    if allowed_bind_codes is None:
        append_bind_variants()
    else:
        for row_work_id in remaining_work_ids:
            codes = list(dict.fromkeys(
                str(code).strip()
                for code in (allowed_bind_codes.get(row_work_id) or [])
                if str(code).strip()
            ))
            if codes:
                append_bind_variants(work_ids=[row_work_id], codes=codes)
    covered_by_variants: list[dict[str, Any]] = []
    for row_work_id in remaining_work_ids:
        targets = list(dict.fromkeys(
            str(target).strip()
            for target in (
                (allowed_coverage_targets or {}).get(row_work_id)
                if allowed_coverage_targets is not None
                else remaining_work_ids
            )
            if str(target).strip() and str(target).strip() != row_work_id
        ))
        if not targets:
            continue
        covered_by_variants.append(variant(
            "covered_by",
            ("covered_by_work_id", "reason"),
            ("covered_by_work_id", "reason"),
            work_ids=[row_work_id],
            property_overrides={
                "covered_by_work_id": {"type": "string", "enum": targets},
            },
        ))
    unbound = variant(
        "unbound",
        ("unbound_evidence", "reason"),
        ("unbound_evidence", "reason"),
    )
    # Search queries and opened codes are already immutable typed tool trace.
    # Asking Qwen to repeat them produced long, failure-prone JSON without
    # adding a professional judgment.  Qwen still owns the rejection reasons
    # and the coverage conclusion.
    unbound_evidence = unbound["properties"]["unbound_evidence"]
    unbound_evidence["properties"] = {
        "rejection_reasons": {
            **copy.deepcopy(
                properties["unbound_evidence"]["properties"]["rejection_reasons"]
            ),
            "maxItems": 3,
        },
        "coverage_checked": copy.deepcopy(
            properties["unbound_evidence"]["properties"]["coverage_checked"]
        ),
    }
    unbound_evidence["properties"]["rejection_reasons"]["items"]["maxLength"] = 320
    unbound_evidence["properties"]["coverage_checked"]["maxLength"] = 320
    unbound_evidence["required"] = ["rejection_reasons", "coverage_checked"]
    unbound_evidence["additionalProperties"] = False

    parameters["properties"]["rows"]["items"] = {
        "oneOf": [*bind_variants, *covered_by_variants, unbound],
    }
    parameters["properties"]["rows"]["minItems"] = 1
    parameters["properties"]["rows"]["maxItems"] = max(1, len(remaining_work_ids))
    parameters["additionalProperties"] = False
    return parameters





def _finalize_document_workflow(
    *,
    path: str | Path,
    intake: dict[str, Any],
    work_rows: list[dict[str, Any]],
    selections: dict[str, dict[str, Any]],
    browse_trace: dict[str, list[dict[str, Any]]],
    query_trace: list[dict[str, Any]],
    model_trace: list[dict[str, Any]],
    book: str | None,
    out_xlsx: str | Path | None,
    out_report: str | Path | None,
    revision_root: str | None,
    vat_pct: float,
    progress: Progress | None,
    agent_trace: dict[str, Any] | None = None,
    source_name: str | None = None,
    lsr_meta: dict[str, Any] | None = None,
    mapping_run: dict[str, Any] | None = None,
    parent_mapping_revision_id: str = "",
    mapping_locked: bool = False,
    professional_conflicts: list[dict[str, Any]] | None = None,
    calculation_created_by: str = "model",
) -> dict[str, Any]:
    display_source_name = Path(str(source_name or Path(path).name)).name
    display_stem = Path(display_source_name).stem
    visible_rows: list[dict[str, Any]] = []
    for row in work_rows:
        selection = selections.get(row["work_id"]) or {}
        visible_rows.append({
            **row,
            "norm_code": selection.get("norm_code") or "",
            "norm_reason": selection.get("reason") or "",
            "selection_kind": selection.get("selection_kind") or "",
            "applicability": selection.get("applicability") or "",
            "technology_check": selection.get("technology_check") or {},
            "is_analog": selection.get("selection_kind") == "analog",
            "analog_limitations": selection.get("analog_limitations") or [],
            "nr_sp_rule_id": selection.get("nr_sp_rule_id") or "",
            "nr_sp_reason": selection.get("reason") or "",
            "selection_review_status": selection.get("review_status") or "",
            "resource_bindings": list(selection.get("resource_bindings") or []),
            "covered_by_work_id": selection.get("covered_by_work_id") or "",
            "coverage_reason": selection.get("coverage_reason") or "",
            "precalculation_blockers": list(selection.get("precalculation_blockers") or []),
        })
    # The native model conversation owns both norm selection and any explicit
    # resource edits. Code performs one calculation pass and never asks a
    # second contract/gate to approve, rewrite or remove the model's decision.
    if progress:
        progress({
            "phase": "calculation",
            "status": "started",
            "label": f"Смета: считаю {len(visible_rows)} строк кодом",
            "rows": len(visible_rows),
        })
    trace = calculate_visible_rows_revision(
        visible_rows,
        selected_by="model",
        created_by=calculation_created_by,
        change_note=f"Model-owned VOR workflow: {display_source_name}",
        parent_revision_id=parent_mapping_revision_id,
        revision_root=revision_root,
        book=book,
        title=f"Локальный сметный расчет — {display_stem}",
    )
    summary = trace.setdefault("summary", {})
    calculated_status = str(summary.get("result_status") or "")
    conflicts = list(professional_conflicts or [])
    summary["calculation_result_status"] = calculated_status
    summary["mapping_status"] = (
        "mapping_locked" if mapping_locked
        else str((mapping_run or {}).get("mapping_status") or "mapping_selected")
    )
    summary["approval_status"] = "user_locked" if mapping_locked else "auto_draft"
    summary["professional_conflict_count"] = len(conflicts)
    if not mapping_locked:
        summary["result_status"] = "priced_draft" if int(summary.get("bound_rows") or 0) else calculated_status
    elif conflicts:
        summary["result_status"] = "priced_partial" if int(summary.get("bound_rows") or 0) else calculated_status
    trace["professional_conflicts"] = conflicts
    trace["mapping_run"] = dict(mapping_run or {})
    if progress:
        summary = trace.get("summary") or {}
        progress({
            "phase": "calculation",
            "status": "done",
            "label": "Смета: расчёт завершён",
            "rows": len(visible_rows),
            "bound_rows": summary.get("bound_rows"),
            "unbound_rows": summary.get("unbound_rows"),
            "total_without_vat": summary.get("total_without_vat"),
            "total_with_vat": summary.get("total_with_vat"),
        })
    xlsx_path = ""
    if out_xlsx:
        if progress:
            progress({"phase": "xlsx", "status": "started", "label": "Смета: формирую Excel"})
        target = Path(out_xlsx)
        target.parent.mkdir(parents=True, exist_ok=True)
        render_meta = dict(lsr_meta or {})
        render_meta.setdefault("osnovanie", display_source_name)
        render_meta.setdefault("object", display_stem)
        render_meta.setdefault("stroika", "Не указано в исходной ВОР")
        render_meta.setdefault("lsr_no", "б/н")
        resolved_book = fgis_price_service.resolve_pricebook_path(book, allow_scratch=bool(book))
        if resolved_book:
            pricebook = fgis_price_service.get_pricebook(resolved_book)
            render_meta.setdefault("subject", pricebook.region or "Не указан")
            render_meta.setdefault("price_level", pricebook.quarter or Path(resolved_book).stem)
        render_lsr_xlsx(trace, target, meta=render_meta)
        xlsx_path = str(target)
        if progress:
            progress({
                "phase": "xlsx",
                "status": "done",
                "label": "Смета: Excel готов",
                "file_name": target.name,
            })
    result = {
        "schema": "smeta_document_workflow_v2",
        "intake": intake,
        "browse_trace": browse_trace,
        "query_trace": query_trace,
        "model_trace": model_trace,
        "agent_trace": agent_trace or {},
        "selections": selections,
        "mapping_run": dict(mapping_run or {}),
        "professional_conflicts": conflicts,
        "lsr": trace,
        "xlsx_path": xlsx_path,
        "cloud_required": False,
    }
    if out_report:
        report_path = Path(out_report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        temp = report_path.with_suffix(report_path.suffix + ".tmp")
        temp.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        temp.replace(report_path)
        result["report_path"] = str(report_path)
    return result


def run_vor_document_workflow(
    path: str | Path,
    *,
    exchange: Exchange,
    mapping_exchange: MappingExchange | None = None,
    candidate_limit: int = 8,
    book: str | None = None,
    out_xlsx: str | Path | None = None,
    out_report: str | Path | None = None,
    revision_root: str | None = None,
    vat_pct: float = 22.0,
    progress: Progress | None = None,
    source_name: str | None = None,
    lsr_meta: dict[str, Any] | None = None,
    user_request: str = "",
    batch_size: int = 0,
    max_agent_turns: int = 64,
    agent_batch_runner: AgentBatchRunner | None = None,
    accumulate_task_state: bool = False,
    require_global_review: bool = True,
    resume_agent_result: dict[str, Any] | None = None,
    batch_checkpoint: Checkpoint | None = None,
    require_scoped_search: bool = False,
    work_context_enricher: WorkContextEnricher | None = None,
) -> dict[str, Any]:
    """Run the generic workflow for a supported table-like VOR document."""
    intake = intake_vor_document(path)
    work_rows = [dict(item) for item in intake.get("work_items") or []]
    if not work_rows:
        raise RuntimeError(
            "в исходном документе не распознаны строки с наименованием, единицей измерения и количеством"
        )
    if work_context_enricher is not None:
        for row in work_rows:
            try:
                enrichment = work_context_enricher(dict(row)) or {}
            except Exception:
                enrichment = {}
            if not isinstance(enrichment, dict):
                continue
            # The adjacent module may provide hints and typed route DTOs only;
            # it cannot seed opened cards or overwrite source facts.
            advisory = enrichment.get("memory_advisory")
            routes = enrichment.get("route_evidence_cache")
            if isinstance(advisory, list) and advisory:
                row["memory_advisory"] = copy.deepcopy(advisory[:8])
            if isinstance(routes, list) and routes:
                row["route_evidence_cache"] = copy.deepcopy(routes[:8])
    query_rows: list[dict[str, Any]] = []
    for index, row in enumerate(work_rows):
        neighbors = []
        for neighbor_index in (index - 1, index + 1):
            if 0 <= neighbor_index < len(work_rows):
                neighbor = work_rows[neighbor_index]
                if str(neighbor.get("section") or "") == str(row.get("section") or ""):
                    neighbors.append({
                        "work_id": neighbor.get("work_id"),
                        "title": neighbor.get("title"),
                        "note": neighbor.get("note"),
                    })
        query_rows.append({**row, "neighbor_context": neighbors})
    initial_agent_result = _run_native_norm_agent(
        query_rows,
        exchange,
        mapping_exchange=mapping_exchange,
        candidate_limit=candidate_limit,
        max_turns=max_agent_turns,
        progress=progress,
        user_request=user_request,
        batch_size=batch_size,
        batch_runner=agent_batch_runner,
        accumulate_task_state=accumulate_task_state,
        resume_result=resume_agent_result,
        checkpoint=batch_checkpoint,
        require_scoped_search=require_scoped_search,
    )
    mapping_run_id = uuid4().hex
    from proxy.smeta_core.revision_store import DEFAULT_ROOT

    revision_dir = Path(revision_root or DEFAULT_ROOT)
    initial_conflicts = detect_professional_conflicts(
        work_rows,
        initial_agent_result.get("selections") or {},
        opened_cards=initial_agent_result.get("opened_cards") or {},
        query_trace=initial_agent_result.get("query_trace") or [],
    )
    initial_revision = MappingRevision(
        mapping_run_id=mapping_run_id,
        revision_kind="row_mapping",
        decisions=dict(initial_agent_result.get("selections") or {}),
        source_rows=tuple(work_rows),
        professional_conflicts=tuple(initial_conflicts),
        mapping_status="mapping_selected",
        change_note="Initial row decisions",
        calculation_context={
            "book": book or "",
            "vat_pct": vat_pct,
            "source_name": source_name or Path(path).name,
            "lsr_meta": dict(lsr_meta or {}),
        },
    )
    initial_revision_path = save_mapping_revision(initial_revision, root=revision_dir)
    agent_result = initial_agent_result
    current_revision = initial_revision
    current_revision_path = initial_revision_path
    if require_global_review and len(work_rows) > 1:
        agent_result = _run_global_norm_review(
            query_rows,
            initial_agent_result,
            exchange,
            mapping_exchange=mapping_exchange,
            candidate_limit=candidate_limit,
            max_turns=max_agent_turns,
            progress=progress,
            user_request=user_request,
            batch_runner=agent_batch_runner,
            require_scoped_search=require_scoped_search,
        )
        current_revision = MappingRevision(
            mapping_run_id=mapping_run_id,
            revision_kind="global_review",
            decisions=dict(agent_result.get("selections") or {}),
            source_rows=tuple(work_rows),
            professional_conflicts=tuple(agent_result.get("professional_conflicts") or ()),
            parent_revision_id=initial_revision.revision_id,
            mapping_status="mapping_globally_reviewed",
            change_note="Mandatory model-owned cross-row review",
            calculation_context=dict(initial_revision.calculation_context),
        )
        current_revision_path = save_mapping_revision(current_revision, root=revision_dir)
    mapping_run = {
        "schema": "smeta_mapping_run_v1",
        "mapping_run_id": mapping_run_id,
        "row_mapping_revision_id": initial_revision.revision_id,
        "row_mapping_revision_path": str(initial_revision_path),
        "current_mapping_revision_id": current_revision.revision_id,
        "current_mapping_revision_path": str(current_revision_path),
        "global_review_revision_id": (
            current_revision.revision_id if current_revision.revision_kind == "global_review" else ""
        ),
        "mapping_status": current_revision.mapping_status,
        "approval_status": "auto_draft",
    }
    if work_rows and int(agent_result.get("valid_model_rows") or 0) == 0:
        # Last resort: open every row without inventing a norm, then calculate.
        open_selections = {
            str(row["work_id"]): {
                "norm_code": "",
                "reason": (
                    "row left open: model returned no accepted norm-agent actions"
                ),
                "review_status": "model_batch_open",
            }
            for row in work_rows
            if str(row.get("work_id") or "").strip()
        }
        agent_result = {
            **agent_result,
            "selections": open_selections,
            "valid_model_rows": len(open_selections),
            "incomplete": True,
            "remaining_work_ids": [],
            "incomplete_blocker": {
                "code": "no_accepted_mapping_actions",
                "reason": "model returned no valid norm-agent actions",
            },
            "agent_trace": {
                **dict(agent_result.get("agent_trace") or {}),
                "status": "all_rows_open_after_empty_mapping",
            },
        }
    return _finalize_document_workflow(
        path=path,
        intake=intake,
        work_rows=work_rows,
        selections=agent_result["selections"],
        browse_trace=agent_result["browse_trace"],
        query_trace=agent_result["query_trace"],
        model_trace=agent_result["model_trace"],
        agent_trace=agent_result["agent_trace"],
        book=book,
        out_xlsx=out_xlsx,
        out_report=out_report,
        revision_root=revision_root,
        vat_pct=vat_pct,
        progress=progress,
        source_name=source_name,
        lsr_meta=lsr_meta,
        mapping_run=mapping_run,
        parent_mapping_revision_id=current_revision.revision_id,
        mapping_locked=False,
        professional_conflicts=list(agent_result.get("professional_conflicts") or initial_conflicts),
    )


def finalize_locked_mapping_revision(
    revision: MappingRevision,
    *,
    out_xlsx: str | Path,
    out_report: str | Path,
    revision_root: str | Path,
) -> dict[str, Any]:
    """Calculate only an explicit user-owned mapping lock."""

    if revision.revision_kind != "user_lock" or revision.mapping_status != "mapping_locked":
        raise ValueError("calculation requires a user-owned locked mapping revision")
    context = dict(revision.calculation_context or {})
    source_name = str(context.get("source_name") or "ВОР")
    mapping_run = {
        "schema": "smeta_mapping_run_v1",
        "mapping_run_id": revision.mapping_run_id,
        "current_mapping_revision_id": revision.revision_id,
        "mapping_status": "mapping_locked",
        "approval_status": "user_locked",
    }
    return _finalize_document_workflow(
        path=source_name,
        intake={"source_name": source_name, "work_items": list(revision.source_rows)},
        work_rows=list(revision.source_rows),
        selections=dict(revision.decisions),
        browse_trace={},
        query_trace=[],
        model_trace=[],
        agent_trace={"engine": "locked_mapping_recalculation"},
        book=str(context.get("book") or "") or None,
        out_xlsx=out_xlsx,
        out_report=out_report,
        revision_root=str(revision_root),
        vat_pct=float(context.get("vat_pct") or 22.0),
        progress=None,
        source_name=source_name,
        lsr_meta=dict(context.get("lsr_meta") or {}),
        mapping_run=mapping_run,
        parent_mapping_revision_id=revision.revision_id,
        mapping_locked=True,
        professional_conflicts=[],
        calculation_created_by="user",
    )


def run_vor_pdf_workflow(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Backward-compatible public name; the workflow now also accepts XLSX."""
    return run_vor_document_workflow(*args, **kwargs)
