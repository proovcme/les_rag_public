"""Generic document -> VOR -> model selection -> priced LSR workflow."""

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
from proxy.services.prompt_registry_service import smeta_native_skill_prompt
from proxy.services.rim_trace_xlsx_service import render_lsr_xlsx
from proxy.smeta_core.contracts import NormBinding, ResourceBinding, WorkItem
from proxy.smeta_core.norm_browser import browse_norm_catalog, browse_norms_many
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

_COMPRESSIBLE_TOOL_RESULTS = frozenset({
    "browse_norm_catalog",
    "search_norms_batch",
    "read_norms_batch",
})


class MappingTransportTimeout(RuntimeError):
    """Structured mapping timed out; the identical payload must not be retried."""


def _mapping_chunk_size() -> int:
    """Bound only the JSON transport; the model still owns every decision."""
    raw = os.getenv("LES_SMETA_DOCUMENT_MAPPING_CHUNK", "8").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 8


def _is_timeout_error(error: BaseException) -> bool:
    text = f"{type(error).__name__}: {error}".casefold()
    return "readtimeout" in text or "timed out" in text or "timeout" in text


def _compress_tool_result(name: str, payload: Any) -> Any:
    """Keep traceable navigation facts while dropping stale bulky payloads."""
    if not isinstance(payload, dict):
        return {"compressed": True, "tool": name}
    if name == "browse_norm_catalog":
        rows = []
        for item in payload.get("rows") or payload.get("items") or []:
            if not isinstance(item, dict):
                continue
            rows.append({
                key: item.get(key)
                for key in (
                    "work_id", "ok", "level", "family", "collection", "table",
                    "families", "collections", "tables", "error",
                )
                if item.get(key) not in (None, "", [])
            })
        return {"compressed": True, "tool": name, "rows": rows}
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
                "page": item.get("page"),
                "has_more": item.get("has_more"),
                "error": item.get("error"),
            })
        return {"compressed": True, "tool": name, "rows": rows}
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
        return {"compressed": True, "tool": name, "rows": rows}
    return {"compressed": True, "tool": name}


def _prune_stale_tool_evidence(
    conversation: list[dict[str, Any]], *, keep_recent: int = 1,
) -> None:
    """Compact old tool payloads and thinking without changing model decisions."""
    by_name: dict[str, list[int]] = {}
    for index, message in enumerate(conversation):
        if str(message.get("role") or "") != "tool":
            continue
        name = str(message.get("name") or "")
        if name in _COMPRESSIBLE_TOOL_RESULTS:
            by_name.setdefault(name, []).append(index)
    keep: set[int] = set()
    for indices in by_name.values():
        keep.update(indices[-max(1, keep_recent):])
    for name, indices in by_name.items():
        for index in indices:
            if index in keep:
                continue
            message = conversation[index]
            if message.get("_les_compressed"):
                continue
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
    source_integrity: dict[str, Any] = {}
    candidate_sets: list[tuple[str, list[dict[str, Any]]]] = []
    results = search_results or browse_norms_many(queries, limit=min(50, max(limit, limit * 3)))
    for search_query in queries:
        result = results.get(search_query) or {}
        backends.append(str(result.get("backend") or ""))
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


def _technology_check_errors(item: dict[str, Any]) -> list[str]:
    """Validate bind evidence shape without judging the model's applicability conclusion."""
    errors: list[str] = []
    if str(item.get("selection_kind") or "") not in {"exact", "analog"}:
        errors.append("selection_kind must be exact|analog")
    if str(item.get("applicability") or "") not in {"exact", "close_analog", "weak_analog"}:
        errors.append("applicability must be exact|close_analog|weak_analog")
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
    if str(check.get("conclusion") or "") not in {"applicable", "applicable_with_limitations"}:
        errors.append("technology_check.conclusion must be applicable|applicable_with_limitations")
    return errors


def _candidate_evaluation_errors(
    item: dict[str, Any],
    *,
    candidates_for_work: dict[str, dict[str, Any]],
    opened_for_work: dict[str, dict[str, Any]],
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
    candidate_codes = {
        str((card or {}).get("norm_code") or code).strip()
        for code, card in candidates_for_work.items()
        if str((card or {}).get("norm_code") or code).strip()
    }
    evaluated_codes: set[str] = set()
    evaluation_signatures: dict[str, tuple[Any, ...]] = {}
    selected_evaluations = 0
    compared_alternatives = 0
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
        elif decision in {"rejected", "uncertain"}:
            compared_alternatives += 1

    if selected_evaluations != 1:
        errors.append("candidate_evaluations must mark the submitted norm exactly once as selected")
    if len(candidate_codes) >= 2 and len(opened_codes) < 2:
        errors.append(
            "candidate_evaluations requires opening at least one shown alternative before bind"
        )
    elif len(candidate_codes) >= 2 and (len(evaluated_codes) < 2 or compared_alternatives < 1):
        errors.append(
            "candidate_evaluations must compare at least one rejected or uncertain opened alternative"
        )
    return errors


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
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
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
        except json.JSONDecodeError:
            try:
                raw = ast.literal_eval(text)
            except (SyntaxError, ValueError):
                repaired = _close_unterminated_json_containers(text)
                if repaired == text:
                    return []
                try:
                    raw = json.loads(repaired)
                except json.JSONDecodeError:
                    return []
    return [item for item in (raw or []) if isinstance(item, dict)] if isinstance(raw, list) else []


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
    ) -> None:
        self.by_id = {str(row["work_id"]): row for row in work_rows}
        self.candidate_limit = max(1, int(candidate_limit))
        self.progress = progress
        self.evidence_budget = evidence_budget or EvidenceBudget.from_environment()
        self.require_scoped_search = bool(require_scoped_search)
        self.started_at = perf_counter()
        self.evidence_usage = {
            "search_calls": 0,
            "read_calls": 0,
            "opened_cards": 0,
            "tool_elapsed_seconds": 0.0,
        }
        self.catalog_trace: list[dict[str, Any]] = []
        self.catalog_seen: set[tuple[str, str, str, str]] = set()
        self.family_catalog_seen: set[str] = set()
        self.selected_base_types: dict[str, dict[str, dict[str, str]]] = {
            work_id: {} for work_id in self.by_id
        }
        self.selected_collections: dict[str, set[tuple[str, str]]] = {
            work_id: set() for work_id in self.by_id
        }
        self.selected_tables: dict[str, set[tuple[str, str, str]]] = {
            work_id: set() for work_id in self.by_id
        }
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
        self.tool_trajectory: list[dict[str, Any]] = []

    def work_fingerprint(self) -> str:
        return hashlib.sha256(
            json.dumps(
                self.by_id,
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
            "selected_tables": {
                work_id: [list(value) for value in sorted(values)]
                for work_id, values in self.selected_tables.items()
            },
            "candidates": copy.deepcopy(self.candidates),
            "opened": copy.deepcopy(self.opened),
            "browse_trace": copy.deepcopy(self.browse_trace),
            "query_trace": copy.deepcopy(self.query_trace),
            "accepted_rows": copy.deepcopy(self.accepted_rows),
            "invalid_submission_attempts": dict(self.invalid_submission_attempts),
            "tool_trajectory": copy.deepcopy(self.tool_trajectory),
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
        self.catalog_trace = copy.deepcopy(list(state.get("catalog_trace") or []))
        self.catalog_seen = {
            tuple(str(item) for item in value)
            for value in (state.get("catalog_seen") or [])
            if isinstance(value, list) and len(value) == 4
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
        restored_tables = work_mapping("selected_tables")
        self.selected_tables = {
            work_id: {
                tuple(str(item) for item in value)
                for value in (restored_tables.get(work_id) or [])
                if isinstance(value, list) and len(value) == 3
            }
            for work_id in self.by_id
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
        self.tool_trajectory = copy.deepcopy(
            list(state.get("tool_trajectory") or [])
        )

    @property
    def remaining_work_ids(self) -> list[str]:
        return [work_id for work_id in self.by_id if work_id not in self.accepted_rows]

    @property
    def complete(self) -> bool:
        return bool(self.by_id) and not self.remaining_work_ids

    def execute(self, name: str, args: dict[str, Any], *, turn: int) -> dict[str, Any]:
        started = perf_counter()
        budget_error = self._budget_error(name, args)
        if budget_error:
            result = {"ok": False, "error": budget_error, "evidence_usage": dict(self.evidence_usage)}
        elif name == "browse_norm_catalog":
            result = self._catalog(args, turn=turn)
        elif name == "search_norms_batch":
            result = self._search(args, turn=turn)
        elif name == "read_norms_batch":
            result = self._read(args)
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

    def _budget_error(self, name: str, args: dict[str, Any]) -> str:
        # Evidence limits must force convergence, never reject the model's
        # terminal decision after it has spent the available search/read time.
        if name == "submit_lsr_mapping":
            return ""
        elapsed = float(self.evidence_usage["tool_elapsed_seconds"])
        if elapsed > self.evidence_budget.elapsed_seconds:
            return (
                f"evidence tool time budget exhausted after {elapsed:.1f}s; "
                "submit the model-owned decision"
            )
        if name == "search_norms_batch":
            if self.evidence_usage["search_calls"] >= self.evidence_budget.search_calls:
                return "search budget exhausted; use collected evidence and submit the model-owned decision"
            self.evidence_usage["search_calls"] += 1
        elif name == "read_norms_batch":
            requested = sum(
                len(_normalize_norm_codes_transport(item))
                for item in _tool_array_argument(args, "items")
            )
            if self.evidence_usage["read_calls"] >= self.evidence_budget.read_calls:
                return "read budget exhausted; use opened cards and submit the model-owned decision"
            if self.evidence_usage["opened_cards"] + requested > self.evidence_budget.opened_cards:
                return "opened-card budget exhausted; use opened cards and submit the model-owned decision"
            self.evidence_usage["read_calls"] += 1
            self.evidence_usage["opened_cards"] += requested
        return ""

    def _catalog(self, args: dict[str, Any], *, turn: int) -> dict[str, Any]:
        rows_out: list[dict[str, Any]] = []
        shared_catalog_owner: dict[tuple[str, str, str], str] = {}

        def compact_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
            compacted = []
            for entry in payload.get("items") or []:
                if not isinstance(entry, dict):
                    continue
                compact = {
                    "key": entry.get("key") or entry.get("norm_code"),
                    "norm_count": entry.get("norm_count"),
                    "resource_count": entry.get("resource_count"),
                }
                for key, bound in (
                    ("official_name", 240),
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
                if entry.get("measure_unit"):
                    compact["measure_unit"] = entry.get("measure_unit")
                compacted.append(compact)
            return compacted

        def reject(
            *,
            work_id: str,
            error: str,
            details: list[str],
            filters: dict[str, str],
        ) -> None:
            rows_out.append({
                "work_id": work_id,
                "ok": False,
                "error": error,
                "details": details,
                "filters": filters,
                "items": [],
            })
            self.catalog_trace.append({
                "phase": "catalog_browse",
                "turn": turn,
                "work_id": work_id,
                "level": "rejected",
                "filters": filters,
                "error": error,
                "details": details,
                "item_count": 0,
            })

        for item in _tool_array_argument(args, "items"):
            work_id = str(item.get("work_id") or "")
            if work_id not in self.by_id:
                rows_out.append({"work_id": work_id, "ok": False, "error": "unknown work_id"})
                continue
            family = str(item.get("family") or "").strip()
            collection = re.sub(r"\D", "", str(item.get("collection") or ""))[:2]
            table = re.sub(r"[^0-9-]", "", str(item.get("table") or "")).strip("-")[:9]
            scope_reason = " ".join(str(item.get("scope_reason") or "").split()).strip()
            confidence = str(item.get("confidence") or "").strip().casefold()
            filters = {"family": family, "collection": collection, "table": table}
            catalog_key = (
                work_id,
                family.casefold(),
                collection,
                table,
            )
            if catalog_key in self.catalog_seen:
                row = {
                    "work_id": work_id,
                    "ok": True,
                    "level": "already_seen",
                    "filters": filters,
                    "items": [],
                    "repeated": True,
                    "next_action": "choose a table or call search_norms_batch with the selected scope",
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

            if self.require_scoped_search and family and not table:
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
                if table and (selected_family, collection) not in self.selected_collections[work_id]:
                    reject(
                        work_id=work_id,
                        error="table selection requires an explicit collection selection",
                        details=[
                            (
                                f"select collection {family}:{collection} first, then choose "
                                "or omit the optional table"
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

            payload = browse_norm_catalog(
                family=family,
                collection=collection,
                table=table if table else "",
                limit=1000,
            )
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

            self.catalog_seen.add(catalog_key)
            if self.require_scoped_search and family and not collection:
                self.selected_base_types[work_id][selected_family] = {
                    "family": family,
                    "reason": scope_reason,
                    "confidence": confidence,
                }
            if self.require_scoped_search and family and collection and not table:
                self.selected_collections[work_id].add((selected_family, collection))
            if self.require_scoped_search and family and collection and table:
                self.selected_tables[work_id].add((selected_family, collection, table))

            if self.require_scoped_search and family and collection and table:
                row = {
                    "work_id": work_id,
                    "ok": True,
                    "level": "table_selected",
                    "filters": {
                        "family": family,
                        "collection": re.sub(r"\D", "", collection)[:2],
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
            if self.require_scoped_search and family and collection:
                row = {
                    "work_id": work_id,
                    "ok": True,
                    "level": "collection_selected",
                    "filters": {
                        "family": family,
                        "collection": collection,
                        "table": "",
                    },
                    "items": [],
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
                        "call search_norms_batch now with scope_mode=scoped, this "
                        "base_type and collection; table_codes are optional"
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
                    "item_count": 0,
                    "repeated": False,
                })
                continue
            shared_key = (
                family.casefold(),
                collection,
                table,
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
                        "choose one or more collections only inside this selected base type; "
                        "then call browse_norm_catalog with family and collection"
                    )
                    if self.require_scoped_search and family
                    else (
                        "compare the family passports, then call browse_norm_catalog "
                        "with family, scope_reason and confidence"
                    )
                    if self.require_scoped_search
                    else (
                        "choose a family, collection and official table; then call "
                        "search_norms_batch with table_codes to receive every row of that table"
                    )
                ),
            }
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
                "repeated": False,
            })
        result: dict[str, Any] = {"ok": bool(rows_out), "rows": rows_out}
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
                work_id = str(item.get("work_id") or "")
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
                rerank=_tool_bool(args.get("rerank"), True),
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
            })
        result: dict[str, Any] = {"ok": bool(items), "rows": rows_out}
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
        result: dict[str, Any] = {"ok": bool(rows_out), "rows": rows_out}
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
            work_id = str(item.get("work_id") or "")
            decision = str(item.get("decision") or "")
            if work_id not in self.by_id or work_id in proposed or work_id in self.accepted_rows:
                errors.append({"work_id": work_id, "error": "unknown or duplicate work_id"})
                continue
            if decision == "unbound":
                reason = str(item.get("reason") or "").strip()
                evidence = self._align_unbound_evidence_to_trace(
                    work_id,
                    dict(item.get("unbound_evidence") or {}),
                )
                evidence_errors = self._unbound_evidence_errors(
                    work_id,
                    reason=reason,
                    evidence=evidence,
                )
                if evidence_errors:
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
                proposed[work_id] = {
                    "norm_code": "",
                    "selection_kind": str(item.get("selection_kind") or ""),
                    "analog_limitations": list(item.get("analog_limitations") or []),
                    "reason": reason,
                    "unbound_evidence": evidence,
                    "review_status": "model_batch_unbound", "resource_bindings": [],
                }
                continue
            if decision == "covered_by":
                covered_by = str(item.get("covered_by_work_id") or "")
                reason = str(item.get("reason") or "").strip()
                proposed[work_id] = {
                    "norm_code": "",
                    "selection_kind": str(item.get("selection_kind") or ""),
                    "analog_limitations": list(item.get("analog_limitations") or []),
                    "covered_by_work_id": covered_by,
                    "coverage_reason": reason,
                    "reason": reason,
                    "review_status": "model_batch_covered", "resource_bindings": [],
                }
                continue
            if decision != "bind":
                errors.append({"work_id": work_id, "error": "decision must be bind|covered_by|unbound"})
                continue
            requested_code = str(item.get("norm_code") or "")
            opened_for_work = self.opened.get(work_id, {})
            bind_errors = _technology_check_errors(item)
            bind_errors.extend(_candidate_evaluation_errors(
                item,
                candidates_for_work=self.candidates.get(work_id, {}),
                opened_for_work=opened_for_work,
            ))
            if not str(item.get("reason") or "").strip():
                bind_errors.append("reason is required")
            if bind_errors:
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
            opened_code = _resolve_norm_code_transport(requested_code, opened_for_work)
            opened_card = opened_for_work.get(opened_code) if opened_code else None
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
                "review_status": "model_batch",
                "resource_bindings": _model_resource_bindings(work_id, item, self.by_id[work_id]),
                "precalculation_blockers": blockers,
            }
        self.accepted_rows.update(proposed)
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

        if not reason:
            errors.append("reason is required")
        if len(unique_queries) < 2:
            errors.append("queries_used must contain at least two distinct searches")
        missing_queries = sorted(value for value in unique_queries if value not in executed_queries)
        if missing_queries:
            errors.append("queries_used contains searches absent from the tool trace: " + ", ".join(missing_queries))
        unopened_codes = sorted(code for code in opened_codes if code not in actually_opened)
        if unopened_codes:
            errors.append("opened_norm_codes contains cards not opened through tools: " + ", ".join(unopened_codes))
        available_candidates = {
            str((card or {}).get("norm_code") or code).strip()
            for code, card in self.candidates.get(work_id, {}).items()
            if str((card or {}).get("norm_code") or code).strip()
        }
        if available_candidates and not opened_codes:
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
                "tool_trajectory": self.tool_trajectory,
                "evidence_budget": asdict(self.evidence_budget),
                "evidence_usage": dict(self.evidence_usage),
            },
        }


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
    }
    batch_traces: list[dict[str, Any]] = list(
        ((resumed.get("agent_trace") or {}).get("batch_traces") or [])
    )
    batches_started = perf_counter()
    source_by_id = {str(row["work_id"]): row for row in work_rows}
    for batch_index, rows in enumerate(batches, 1):
        if progress:
            progress({
                "phase": "source_batch",
                "status": "started",
                "label": f"Смета: обрабатываю строки {merged['valid_model_rows'] + 1}–{merged['valid_model_rows'] + len(rows)} из {len(work_rows)}",
                "batch": batch_index,
                "batches": len(batches),
                "completed_rows": merged["valid_model_rows"],
                "total_rows": len(work_rows),
            })
        task_rows = rows
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
            task_rows = [{**row, "task_state": task_state} for row in rows]
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
                )
        except Exception as error:
            if checkpoint is not None:
                checkpoint(copy.deepcopy({
                    **merged,
                    "incomplete": True,
                    "remaining_work_ids": [
                        work_id
                        for work_id in ordered_work_ids
                        if work_id not in merged["selections"]
                    ],
                    "incomplete_blocker": {
                        "code": (
                            "structured_mapping_timeout"
                            if isinstance(error, MappingTransportTimeout)
                            or _is_timeout_error(error)
                            else "batch_failed"
                        ),
                        "reason": str(error),
                    },
                }))
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
        merged["incomplete_blocker"] = {}
        batch_traces.append(result.get("agent_trace") or {})
        if checkpoint is not None:
            checkpoint(copy.deepcopy(merged))
        if progress:
            elapsed_sec = max(0.0, perf_counter() - batches_started)
            eta_sec = round((elapsed_sec / batch_index) * (len(batches) - batch_index))
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
                "label": f"Смета: обработано {merged['valid_model_rows']} из {len(work_rows)} строк{eta_label}",
                "batch": batch_index,
                "batches": len(batches),
                "completed_rows": merged["valid_model_rows"],
                "total_rows": len(work_rows),
                "eta_sec": eta_sec,
            })
    missing = [str(row["work_id"]) for row in work_rows if str(row["work_id"]) not in merged["selections"]]
    if missing:
        raise RuntimeError(f"model batches did not cover source rows: {missing}")
    merged["incomplete"] = False
    merged["remaining_work_ids"] = []
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
    return merged


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
) -> dict[str, Any]:
    """Run one model-owned cross-row revision; code only supplies conflicts."""

    initial_selections = initial_result.get("selections") or {}
    opened_cards = initial_result.get("opened_cards") or {}
    before_conflicts = detect_professional_conflicts(
        work_rows,
        initial_selections,
        opened_cards=opened_cards,
        query_trace=initial_result.get("query_trace") or [],
    )
    review_rows = []
    conflicts_by_work: dict[str, list[dict[str, Any]]] = {}
    for conflict in before_conflicts:
        for work_id in conflict.get("work_ids") or []:
            conflicts_by_work.setdefault(str(work_id), []).append(conflict)
    for row in work_rows:
        work_id = str(row["work_id"])
        selection = dict(initial_selections.get(work_id) or {})
        compact_cards = [
            _compact_norm_card_for_global_review(card)
            for card in (opened_cards.get(work_id) or [])
            if isinstance(card, dict)
        ]
        review_rows.append({
            **row,
            "review_phase": "global_cross_row_review",
            "current_decision": {"decision": _decision_name(selection), **selection},
            "opened_norm_cards": compact_cards,
            "professional_conflicts": conflicts_by_work.get(work_id, []),
        })
    if progress:
        progress({
            "phase": "global_review", "status": "started",
            "label": f"Смета: модель проверяет связи между {len(review_rows)} строками",
            "rows": len(review_rows), "conflicts": len(before_conflicts),
        })
    review_request = (
        f"{user_request}\n\n"
        "GLOBAL CROSS-ROW REVIEW. Treat current_decision as the initial model draft. Review the whole "
        "mapping for forward and backward coverage, duplicate work/resources, operation direction, "
        "analog/exact consistency and supplied professional_conflicts. Preserve a decision when it is "
        "defensible. Revise it only as your own professional decision. Previously opened_norm_cards are "
        "compact typed evidence summaries; call read_norms_batch to reopen the full card only for disputed "
        "rows that need more evidence. Submit one "
        "terminal decision for every work_id. This produces a new immutable model revision."
    )
    if batch_runner is not None:
        reviewed = batch_runner(
            review_rows,
            candidate_limit=candidate_limit,
            max_turns=max_turns,
            progress=progress,
            user_request=review_request,
        )
    else:
        reviewed = _run_batch_norm_agent(
            review_rows,
            exchange,
            mapping_exchange=mapping_exchange,
            candidate_limit=candidate_limit,
            max_turns=max_turns,
            progress=progress,
            user_request=review_request,
        )
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
            "rows": len(review_rows), "conflicts_before": len(before_conflicts),
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
        "agent_trace": {
            "mode": "row_mapping_then_global_model_review",
            "initial": initial_result.get("agent_trace") or {},
            "global_review": reviewed.get("agent_trace") or {},
        },
    }


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
    tools = [
        tool for tool in _batch_norm_tools()
        if str((tool.get("function") or {}).get("name") or "") != "submit_lsr_mapping"
    ]
    skill_prompt = smeta_native_skill_prompt()
    if not skill_prompt:
        raise RuntimeError("canonical smeta skill is unavailable")
    system_prompt = skill_prompt
    initial_conversation: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "user_request": str(user_request or "").strip(),
                    "work_items": list(by_id.values()),
                    "batch_contract": (
                        "Use tools only for work_id values present in work_items. Each item's neighbor_context is "
                        "navigation for overlap/coverage; do not search or submit those neighboring work_ids here. "
                        + (
                            "RIM invariant: for every work_id call browse_norm_catalog, then search_norms_batch "
                            "first compare the returned family passports. Select a family in a separate "
                            "browse_norm_catalog call with your own scope_reason and confidence; then select "
                            "one collection inside that family with its own scope_reason and confidence. "
                            "Read the returned collection_passport before search. Call search_norms_batch with scope_mode=scoped "
                            "and explicit base_types plus collections selected by you, "
                            "then read_norms_batch before any bind. RAG candidates are navigation only; only a "
                            "full typed card opened by read_norms_batch may support submit_lsr_mapping."
                            if require_scoped_search
                            else ""
                        )
                    ),
                },
                ensure_ascii=False,
                default=str,
            ),
        },
    ]
    conversation: list[dict[str, Any]] = (
        copy.deepcopy(list(resume_state.get("conversation") or []))
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
    last_submit_result: dict[str, Any] | None = (
        copy.deepcopy(resume_state.get("last_submit_result"))
        if isinstance(resume_state.get("last_submit_result"), dict)
        else None
    )
    mapping_chunk = _mapping_chunk_size()

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
            "last_submit_result": copy.deepcopy(last_submit_result),
        }
        checkpoint(payload)

    def structured_mapping_call(*, reason: str, turn: int) -> dict[str, Any]:
        nonlocal structured_mapping_attempts
        if mapping_exchange is None:
            raise RuntimeError(reason)
        if structured_mapping_attempts >= 2:
            raise RuntimeError(
                "smeta model mapping failed validation after one bounded schema repair"
            )
        structured_mapping_attempts += 1
        remaining = [work_id for work_id in by_id if work_id not in accepted_rows]
        serialize_ids = (
            remaining[:mapping_chunk]
            if mapping_chunk > 0
            else list(remaining)
        )
        schema = _mapping_output_schema(serialize_ids)
        request = {
            "transport_request": (
                "Serialize your own current professional decisions for every remaining_work_id "
                "listed below. Do not decide deferred_work_ids yet; LES will request those after "
                "this chunk is accepted. Do not delegate, revise or let code choose a decision. "
                "If the evidence you inspected is insufficient, record your own unbound decision. "
                "Return only the required JSON."
            ),
            "remaining_work_ids": serialize_ids,
            "deferred_work_ids": [
                work_id for work_id in remaining
                if work_id not in serialize_ids
            ],
            # Ollama explicitly recommends grounding a structured-output call
            # with the same schema in the prompt as well as in `format`.
            "output_schema": schema,
        }
        conversation.append({
            "role": "user",
            "content": json.dumps(request, ensure_ascii=False),
        })
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
        })
        return {
            "id": f"structured-mapping-{turn}",
            "type": "function",
            "function": {"name": "submit_lsr_mapping", "arguments": {"rows": rows}},
        }

    mapping_rows_per_call = (
        mapping_chunk if mapping_chunk > 0 else max(1, len(by_id))
    )
    finalization_turns = (
        math.ceil(max(1, len(by_id)) / mapping_rows_per_call) + 1
        if mapping_exchange is not None else 0
    )
    start_turn = max(1, int(resume_state.get("next_turn") or 1))
    for turn in range(start_turn, max_turns + finalization_turns + 1):
        started = perf_counter()
        forced_mapping = turn > max_turns
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
        if forced_mapping:
            repair_mapping = bool(last_submit_result and not last_submit_result.get("ok"))
            calls = [structured_mapping_call(
                reason=(
                    "previous structured mapping failed validation; resubmit only "
                    "the remaining work_id values using the returned errors"
                    if repair_mapping else
                    f"smeta evidence tool budget exhausted after {max_turns} model turns"
                ),
                turn=turn,
            )]
            model_wait_ms = float(model_trace[-1].get("model_wait_ms") or 0.0)
        else:
            _prune_stale_tool_evidence(conversation)
            assistant = exchange(conversation, tools) or {}
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
                "assistant": assistant_message,
                "model_wait_ms": model_wait_ms,
                "seed": assistant.get("_les_seed"),
            })
            if not calls:
                done_reason = str(assistant.get("_les_done_reason") or "unknown")
                eval_count = assistant.get("_les_eval_count")
                model_text = " ".join(str(assistant.get("content") or "").split())[:400]
                failure = (
                    "smeta model ended the document workflow without a tool call: "
                    f"done_reason={done_reason}, eval_count={eval_count}, "
                    f"model_text={model_text or '<empty>'}"
                )
                calls = [structured_mapping_call(reason=failure, turn=turn)]
        context_metrics.append({
            "turn": turn,
            "prompt_chars": len(json.dumps(conversation, ensure_ascii=False, default=str)),
            "model_wait_ms": model_wait_ms,
            "tool_calls": len(calls),
            "structured_mapping": forced_mapping or not bool(assistant.get("tool_calls")),
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
            if duplicate_feedback_signature != call_signature:
                duplicate_feedback_signature = call_signature
                for call_index, call in enumerate(calls, 1):
                    name = str(((call.get("function") or {}).get("name") or ""))
                    result = {
                        "ok": False,
                        "error": "identical deterministic request already executed; no new evidence was produced",
                    }
                    conversation.append({
                        "role": "tool",
                        "tool_call_id": str(call.get("id") or f"duplicate-{turn}-{call_index}"),
                        "name": name,
                        "content": json.dumps(result, ensure_ascii=False),
                    })
                    model_trace[-1].setdefault("tool_results", []).append({"name": name, "result": result})
                emit_checkpoint(next_turn=turn + 1)
                continue
            calls = [structured_mapping_call(reason=failure, turn=turn)]
            call_signature = json.dumps([{
                "name": "submit_lsr_mapping",
                "arguments": _tool_arguments(calls[0]),
            }], ensure_ascii=False, sort_keys=True, default=str)
        else:
            duplicate_feedback_signature = ""
        previous_call_signature = call_signature

        submitted: dict[str, dict[str, Any]] | None = None
        accepted_before_turn = len(accepted_rows)
        for call_index, call in enumerate(calls, 1):
            call_id = str(call.get("id") or f"batch-{turn}-{call_index}")
            name = str(((call.get("function") or {}).get("name") or ""))
            args = _tool_arguments(call)
            result = session.execute(name, args, turn=turn)
            conversation.append({
                "role": "tool", "tool_call_id": call_id, "name": name,
                "content": json.dumps(result, ensure_ascii=False, default=str),
            })
            model_trace[-1].setdefault("tool_results", []).append({"name": name, "result": result})
            if name == "submit_lsr_mapping" and isinstance(result, dict):
                last_submit_result = result
            submitted = dict(session.accepted_rows) if session.complete else None
        if len(accepted_rows) > accepted_before_turn:
            structured_mapping_attempts = 0
        emit_checkpoint(next_turn=turn + 1)
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
        errors = json.dumps(
            (last_submit_result.get("errors") or [])[:8],
            ensure_ascii=False,
            default=str,
        )
        raise RuntimeError(
            "smeta model mapping failed validation after bounded repair: "
            f"{errors[:800]}"
        )
    raise RuntimeError(f"smeta model did not submit mapping within {max_turns} model turns")


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
                    "Browse the typed normative menu before searching. First call with only work_id "
                    "and compare the authoritative family passports. Then select a family with "
                    "scope_reason and confidence to receive only its collections. Select a collection "
                    "in a later call; an official table is optional. Catalog navigation records the "
                    "model's scope decision but never chooses a professional norm."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "items": {"type": "array", "items": {"type": "object", "properties": {
                            "work_id": {"type": "string"},
                            "family": {"type": "string", "description": "Norm family such as ГЭСН, ГЭСНм, ГЭСНр. Empty returns families."},
                            "collection": {"type": "string", "description": "Two-digit collection selected by the model. Empty returns collections."},
                            "table": {"type": "string", "description": "Official table code selected by the model, such as 08-02-001."},
                            "scope_reason": {
                                "type": "string",
                                "description": (
                                    "Required when selecting family or collection: why this "
                                    "normative scope matches the work. It must come from the model, "
                                    "not LES code."
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
                "name": "search_norms_batch",
                "description": "Search RRF norm candidates for any number of independent source rows in one tool call.",
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
                                "enum": ["scoped", "global"],
                                "description": (
                                    "Model-owned retrieval plan. scoped requires both base_types and "
                                    "collections selected from the catalog; global requires both empty."
                                ),
                            },
                            "base_types": {"type": "array", "items": {"type": "string"}, "description": "Families chosen by the model after catalog browse. RIM uses one family per item; repeat the item for another family."},
                            "collections": {"type": "array", "items": {"type": "string"}, "description": "Collection numbers chosen by the model after catalog browse. RIM uses one collection per item; repeat the item for another collection."},
                            "table_codes": {"type": "array", "items": {"type": "string"}, "description": "Official table codes shown by browse_norm_catalog. Selecting a table returns its complete row menu without ranking."},
                            "limit": {"type": "integer", "minimum": 1}, "page": {"type": "integer", "minimum": 0},
                        }, "required": ["work_id", "query", "search_intent", "scope_mode"]}},
                        "rerank": {"type": "boolean"},
                    },
                    "required": ["items"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_norms_batch",
                "description": "Read full typed norm cards for any number of source rows in one tool call.",
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


def _mapping_output_schema(remaining_work_ids: list[str]) -> dict[str, Any]:
    """Reuse the declared mapping row as a provider-enforced transport schema."""
    submit_tool = next(
        tool for tool in _batch_norm_tools()
        if str((tool.get("function") or {}).get("name") or "") == "submit_lsr_mapping"
    )
    parameters = json.loads(json.dumps(submit_tool["function"]["parameters"], ensure_ascii=False))
    row_schema = parameters["properties"]["rows"]["items"]
    # Conditional validation remains in the ordinary submit processor. Ollama's
    # grammar accepts a simpler schema more consistently; this only constrains
    # serialization and never creates or changes a professional decision.
    row_schema.pop("allOf", None)
    row_schema["properties"]["work_id"]["enum"] = list(remaining_work_ids)
    parameters["properties"]["rows"]["minItems"] = 1
    parameters["properties"]["rows"]["maxItems"] = max(1, len(remaining_work_ids))
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
) -> dict[str, Any]:
    """Run the generic workflow for a supported table-like VOR document."""
    intake = intake_vor_document(path)
    work_rows = [dict(item) for item in intake.get("work_items") or []]
    if not work_rows:
        raise RuntimeError(
            "в исходном документе не распознаны строки с наименованием, единицей измерения и количеством"
        )
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
        if out_report:
            report_path = Path(out_report)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            failure = {
                "schema": "smeta_document_workflow_failure_v2",
                "status": "failed_before_calculation",
                "error": "model returned no valid norm-agent actions",
                "intake": intake,
                **agent_result,
            }
            temp = report_path.with_suffix(report_path.suffix + ".tmp")
            temp.write_text(json.dumps(failure, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            temp.replace(report_path)
        raise RuntimeError("model returned no valid norm-agent actions; no estimate was calculated")
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
