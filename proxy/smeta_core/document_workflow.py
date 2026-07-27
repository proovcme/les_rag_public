"""Generic document -> VOR -> model selection -> priced LSR workflow."""

from __future__ import annotations

import ast
import json
import os
import re
from dataclasses import asdict
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from proxy.services import fgis_price_service, gesn_service, nr_sp_service
from proxy.services.kac_web_service import collect_quotes
from proxy.services.prompt_registry_service import smeta_native_skill_prompt
from proxy.services.rim_trace_xlsx_service import render_lsr_xlsx
from proxy.smeta_core.contracts import NormBinding, ResourceBinding, WorkItem
from proxy.smeta_core.norm_browser import browse_norms_many
from proxy.smeta_core.norm_validator import units_compatible, validate_binding
from proxy.smeta_core.resource_normalizer import normalize_norm_resources
from proxy.smeta_core.source_intake import intake_vor_document
from proxy.smeta_core.application import calculate_visible_rows, calculate_visible_rows_revision


Exchange = Callable[[list[dict[str, Any]], list[dict[str, Any]]], dict[str, Any]]
MappingExchange = Callable[[list[dict[str, Any]], dict[str, Any]], dict[str, Any]]
Progress = Callable[[dict[str, Any]], None]
AgentBatchRunner = Callable[..., dict[str, Any]]


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
    queries = sorted(
        dict.fromkeys(
            str(item).strip()
            for item in (query if isinstance(query, list) else [query])
            if str(item).strip()
        )
    )
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
                "title": str(card.get("title") or "")[:320],
                "measure_unit": card.get("measure_unit"),
                "unit_compatible": bool(card.get("unit_compatible", True)),
                "work_steps": [str(step)[:180] for step in list(card.get("work_steps") or [])[:4]],
                "resource_kinds": card.get("resource_kinds") or {},
                "resource_preview": [str(value)[:120] for value in (card.get("resource_preview") or [])[:6]],
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
    # Keep fused order; break residual ties by norm_code so the model always
    # sees the same menu for the same query set (fresh run, no past mapping).
    ordered = list(enumerate(cards))
    ordered.sort(key=lambda pair: (pair[0], str(pair[1].get("norm_code") or "")))
    cards = [card for _, card in ordered]
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


def _opened_norm_card(code: str, candidate: dict[str, Any]) -> dict[str, Any] | None:
    norm = gesn_service.get_norm(code, strict_family=True)
    if not norm:
        return None
    resources = []
    for resource in list(norm.get("resources") or [])[:30]:
        resources.append({
            "code": resource.get("code"),
            "name": resource.get("name"),
            "unit": resource.get("unit"),
            "kind": resource.get("kind"),
            "per_unit": resource.get("per_unit"),
        })
    return {
        "norm_code": code,
        "title": norm.get("name"),
        "measure_unit": norm.get("unit"),
        "work_steps": list(norm.get("work_steps") or [])[:24],
        "resources": resources,
        "nr_sp_candidates": candidate.get("nr_sp_candidates") or [],
        "source_ref": candidate.get("source_ref") or "",
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
    return sorted(dict.fromkeys(
        " ".join(str(value).split())[:240]
        for value in values if str(value).strip()
    ))


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
    ) -> None:
        self.by_id = {str(row["work_id"]): row for row in work_rows}
        self.candidate_limit = max(1, int(candidate_limit))
        self.progress = progress
        self.candidates: dict[str, dict[str, dict[str, Any]]] = {
            work_id: {} for work_id in self.by_id
        }
        self.opened: dict[str, dict[str, dict[str, Any]]] = {
            work_id: {} for work_id in self.by_id
        }
        self.browse_trace: dict[str, list[dict[str, Any]]] = {
            work_id: [] for work_id in self.by_id
        }
        self.query_trace: list[dict[str, Any]] = []
        self.accepted_rows: dict[str, dict[str, Any]] = {}
        self.invalid_submission_attempts: dict[str, int] = {}
        self.tool_trajectory: list[dict[str, Any]] = []

    @property
    def remaining_work_ids(self) -> list[str]:
        return [work_id for work_id in self.by_id if work_id not in self.accepted_rows]

    @property
    def complete(self) -> bool:
        return bool(self.by_id) and not self.remaining_work_ids

    def execute(self, name: str, args: dict[str, Any], *, turn: int) -> dict[str, Any]:
        started = perf_counter()
        if name == "search_norms_batch":
            result = self._search(args, turn=turn)
        elif name == "read_norms_batch":
            result = self._read(args)
        elif name == "submit_lsr_mapping":
            result = self._submit(args)
        else:
            result = {"ok": False, "error": f"unknown tool: {name}"}
        self.tool_trajectory.append({
            "turn": turn,
            "tool": name,
            "arguments": args,
            "result": result,
            "elapsed_ms": round((perf_counter() - started) * 1000, 2),
        })
        return result

    def _search(self, args: dict[str, Any], *, turn: int) -> dict[str, Any]:
        items = sorted(
            [
                item for item in _tool_array_argument(args, "items")
                if isinstance(item, dict)
            ],
            key=lambda item: (
                str(item.get("work_id") or ""),
                str(item.get("query") or ""),
                json.dumps(item.get("queries") or [], ensure_ascii=False, sort_keys=True),
            ),
        )
        batch_limit = args.get("limit")
        batch_page = args.get("page")
        all_queries = sorted(dict.fromkeys(
            query
            for item in items for query in _normalize_search_queries_transport(item)
        ))
        search_results = browse_norms_many(
            all_queries,
            limit=100,
            rerank=bool(args.get("rerank", False)),
        ) if all_queries else {}
        rows_out = []
        for item in items:
            work_id = str(item.get("work_id") or "")
            if work_id not in self.by_id:
                rows_out.append({"work_id": work_id, "ok": False, "error": "unknown work_id"})
                continue
            queries = _normalize_search_queries_transport(item)
            limit = max(1, int(item.get("limit") or batch_limit or self.candidate_limit))
            page = max(0, int(item.get("page") if item.get("page") is not None else batch_page or 0))
            payload = _candidate_payload(
                self.by_id[work_id], queries, limit=limit, page=page,
                search_results=search_results,
            )
            self.browse_trace[work_id].append(payload)
            compact = []
            for card in payload.get("candidates") or []:
                code = str(card.get("norm_code") or "")
                self.candidates[work_id][code] = card
                compact.append({
                    "norm_code": code,
                    "title": str(card.get("title") or "")[:180],
                    "measure_unit": card.get("measure_unit"),
                })
            rows_out.append({
                "work_id": work_id, "ok": True, "candidates": compact,
                "page": page, "has_more": bool(payload.get("has_more")),
            })
            self.query_trace.append({
                "phase": "batch_search", "turn": turn, "work_id": work_id,
                "queries": queries, "candidate_count": len(compact), "page": page,
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
                evidence = dict(item.get("unbound_evidence") or {})
                queries_used = [
                    str(value).strip()
                    for value in (evidence.get("queries_used") or [])
                    if str(value).strip()
                ]
                rejection_reasons = [
                    str(value).strip()
                    for value in (evidence.get("rejection_reasons") or [])
                    if str(value).strip()
                ]
                opened_norm_codes = [
                    str(value).strip()
                    for value in (evidence.get("opened_norm_codes") or [])
                    if str(value).strip()
                ]
                coverage_checked = str(evidence.get("coverage_checked") or "").strip()
                available_codes = {
                    str(code)
                    for code in (self.candidates.get(work_id) or {})
                    if str(code).strip()
                }
                opened_codes = {
                    str(code)
                    for code in (self.opened.get(work_id) or {})
                    if str(code).strip()
                }
                blockers: list[dict[str, Any]] = []
                if len(queries_used) < 2:
                    blockers.append({
                        "code": "unbound_evidence_queries_incomplete",
                        "work_id": work_id,
                        "reason": "unbound requires at least two distinct search formulations",
                    })
                if not rejection_reasons:
                    blockers.append({
                        "code": "unbound_evidence_rejection_missing",
                        "work_id": work_id,
                        "reason": "unbound requires explicit rejection reasons",
                    })
                if not coverage_checked:
                    blockers.append({
                        "code": "unbound_evidence_coverage_missing",
                        "work_id": work_id,
                        "reason": "unbound requires coverage_checked note",
                    })
                if available_codes and not opened_norm_codes and not opened_codes:
                    blockers.append({
                        "code": "unbound_without_opened_candidates",
                        "work_id": work_id,
                        "reason": (
                            "search returned candidates; unbound should open and reject "
                            "close cards instead of skipping them"
                        ),
                    })
                unknown_opened = [
                    code for code in opened_norm_codes
                    if code not in available_codes and code not in opened_codes
                ]
                if unknown_opened:
                    blockers.append({
                        "code": "unbound_opened_codes_not_in_session",
                        "work_id": work_id,
                        "reason": "opened_norm_codes must come from search/read evidence",
                        "unknown_codes": unknown_opened[:8],
                    })
                proposed[work_id] = {
                    "norm_code": "",
                    "selection_kind": str(item.get("selection_kind") or ""),
                    "analog_limitations": list(item.get("analog_limitations") or []),
                    "reason": reason,
                    "unbound_evidence": {
                        "queries_used": queries_used,
                        "opened_norm_codes": opened_norm_codes,
                        "rejection_reasons": rejection_reasons,
                        "coverage_checked": coverage_checked,
                    },
                    "review_status": "model_batch_unbound",
                    "resource_bindings": [],
                    "precalculation_blockers": blockers,
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
            opened_code = _resolve_norm_code_transport(requested_code, opened_for_work)
            opened_card = opened_for_work.get(opened_code) if opened_code else None
            code = str((opened_card or {}).get("norm_code") or requested_code)
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
            exhausted = [
                key for key, count in self.invalid_submission_attempts.items() if count >= 4
            ]
            if exhausted:
                raise RuntimeError(
                    "smeta model repeated an invalid mapping 4 times for "
                    f"{','.join(exhausted)}: "
                    + json.dumps(errors[:5], ensure_ascii=False, default=str)
                )
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

    def result(
        self,
        *,
        model_trace: list[dict[str, Any]],
        agent_trace: dict[str, Any],
    ) -> dict[str, Any]:
        if not self.complete:
            raise RuntimeError(
                "smeta agent ended without terminal mapping for: "
                + ",".join(self.remaining_work_ids)
            )
        return {
            "selections": dict(self.accepted_rows),
            "browse_trace": self.browse_trace,
            "query_trace": self.query_trace,
            "model_trace": model_trace,
            "valid_model_rows": len(self.accepted_rows),
            "agent_trace": {**agent_trace, "tool_trajectory": self.tool_trajectory},
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
) -> dict[str, Any]:
    """Give the model the source rows and merge its untouched decisions."""
    requested_size = int(batch_size)
    size = len(work_rows) if requested_size <= 0 else max(1, requested_size)
    batches = [work_rows[index:index + size] for index in range(0, len(work_rows), size)]
    if len(batches) <= 1:
        if batch_runner is not None:
            return batch_runner(
                work_rows,
                candidate_limit=candidate_limit,
                max_turns=max_turns,
                progress=progress,
                user_request=user_request,
            )
        return _run_batch_norm_agent(
            work_rows,
            exchange,
            mapping_exchange=mapping_exchange,
            candidate_limit=candidate_limit,
            max_turns=max_turns,
            progress=progress,
            user_request=user_request,
        )

    merged = {
        "selections": {},
        "browse_trace": {},
        "query_trace": [],
        "model_trace": [],
        "valid_model_rows": 0,
    }
    batch_traces: list[dict[str, Any]] = []
    batches_started = perf_counter()
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
        if batch_runner is not None:
            result = batch_runner(
                rows,
                candidate_limit=candidate_limit,
                max_turns=max_turns,
                progress=progress,
                user_request=user_request,
            )
        else:
            result = _run_batch_norm_agent(
                rows,
                exchange,
                mapping_exchange=mapping_exchange,
                candidate_limit=candidate_limit,
                max_turns=max_turns,
                progress=progress,
                user_request=user_request,
            )
        merged["selections"].update(result["selections"])
        merged["browse_trace"].update(result["browse_trace"])
        merged["query_trace"].extend(result["query_trace"])
        merged["model_trace"].extend(
            {**item, "source_batch": batch_index} for item in result["model_trace"]
        )
        merged["valid_model_rows"] += int(result.get("valid_model_rows") or 0)
        batch_traces.append(result.get("agent_trace") or {})
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
    merged["agent_trace"] = {
        "mode": "model_bounded_batch_rag_tools",
        "engine": str((batch_traces[0] if batch_traces else {}).get("engine") or "native"),
        "provider": str((batch_traces[0] if batch_traces else {}).get("provider") or ""),
        "model": str((batch_traces[0] if batch_traces else {}).get("model") or ""),
        "batch_size": size,
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


def _run_batch_norm_agent(
    work_rows: list[dict[str, Any]],
    exchange: Exchange,
    *,
    mapping_exchange: MappingExchange | None = None,
    candidate_limit: int,
    max_turns: int = 64,
    progress: Progress | None = None,
    user_request: str = "",
) -> dict[str, Any]:
    """Thin model tool loop: batch RAG, batch read, one model-owned mapping submission."""
    session = SmetaNormToolSession(
        work_rows, candidate_limit=candidate_limit, progress=progress,
    )
    by_id = session.by_id
    browse_trace = session.browse_trace
    query_trace = session.query_trace
    model_trace: list[dict[str, Any]] = []
    context_metrics: list[dict[str, Any]] = []
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
    conversation: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps({
            "user_request": str(user_request or "").strip(),
            "work_items": list(by_id.values()),
            "batch_contract": (
                "Use tools only for work_id values present in work_items. Each item's neighbor_context is "
                "navigation for overlap/coverage; do not search or submit those neighboring work_ids here."
            ),
        }, ensure_ascii=False, default=str)},
    ]

    if max_turns < 1:
        raise ValueError("max_turns must be positive")
    accepted_rows = session.accepted_rows
    previous_call_signature = ""
    duplicate_feedback_signature = ""

    def structured_mapping_call(*, reason: str, turn: int) -> dict[str, Any]:
        if mapping_exchange is None:
            raise RuntimeError(reason)
        remaining = [work_id for work_id in by_id if work_id not in accepted_rows]
        schema = _mapping_output_schema(remaining)
        request = {
            "transport_request": (
                "Serialize your own current professional decisions for every remaining_work_id. "
                "Do not delegate, revise or let code choose a decision. If the evidence you inspected "
                "is insufficient, record your own unbound decision. Return only the required JSON."
            ),
            "remaining_work_ids": remaining,
            # Ollama explicitly recommends grounding a structured-output call
            # with the same schema in the prompt as well as in `format`.
            "output_schema": schema,
        }
        conversation.append({
            "role": "user",
            "content": json.dumps(request, ensure_ascii=False),
        })
        started = perf_counter()
        payload = mapping_exchange(conversation, schema) or {}
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
        conversation.append(assistant_message)
        model_trace.append({
            "turn": turn,
            "assistant": assistant_message,
            "model_wait_ms": wait_ms,
            "transport": "structured_mapping",
            "trigger": reason,
        })
        return {
            "id": f"structured-mapping-{turn}",
            "type": "function",
            "function": {"name": "submit_lsr_mapping", "arguments": {"rows": rows}},
        }

    finalization_turns = 1 if mapping_exchange is not None else 0
    for turn in range(1, max_turns + finalization_turns + 1):
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
            calls = [structured_mapping_call(
                reason=f"smeta evidence tool budget exhausted after {max_turns} model turns",
                turn=turn,
            )]
            model_wait_ms = float(model_trace[-1].get("model_wait_ms") or 0.0)
        else:
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
            if assistant.get("_les_fallback_from"):
                assistant_message["fallback_from"] = str(assistant["_les_fallback_from"])
            conversation.append(assistant_message)
            model_trace.append({"turn": turn, "assistant": assistant_message, "model_wait_ms": model_wait_ms})
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
            submitted = dict(session.accepted_rows) if session.complete else None
        if submitted is not None:
            return session.result(
                model_trace=model_trace,
                agent_trace={
                    "mode": "model_batch_rag_tools",
                    "turns": turn,
                    "context_metrics": context_metrics,
                },
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
                    "analog_limitations", "technology_check",
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
                "name": "search_norms_batch",
                "description": "Search RRF norm candidates for any number of independent source rows in one tool call.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "items": {"type": "array", "items": {"type": "object", "properties": {
                            "work_id": {"type": "string"},
                            "query": {"type": "string", "description": "One search formulation. Repeat the work_id in another item or later call for another formulation."},
                            "limit": {"type": "integer", "minimum": 1}, "page": {"type": "integer", "minimum": 0},
                        }, "required": ["work_id", "query"]}},
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


def _env_flag(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().casefold() in {"1", "true", "yes", "on"}


def _norm_table_stem(code: str) -> str:
    """Strip the final numeric position suffix: ГЭСНр62-01-017-05 -> ГЭСНр62-01-017."""
    text = str(code or "").strip()
    match = re.match(r"^(.*)-(\d+)$", text)
    return match.group(1) if match else text


def _browse_candidate_codes(
    browse_trace: dict[str, list[dict[str, Any]]],
    work_id: str,
) -> list[str]:
    codes: list[str] = []
    for payload in browse_trace.get(work_id) or []:
        if not isinstance(payload, dict):
            continue
        for card in payload.get("candidates") or []:
            if not isinstance(card, dict):
                continue
            code = str(card.get("norm_code") or "").strip()
            if code:
                codes.append(code)
    return list(dict.fromkeys(codes))


def _self_check_output_schema(work_ids: list[str]) -> dict[str, Any]:
    string_array = {"type": "array", "items": {"type": "string"}}
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
    return {
        "type": "object",
        "properties": {
            "rows": {
                "type": "array",
                "minItems": len(work_ids),
                "maxItems": len(work_ids),
                "items": {
                    "type": "object",
                    "properties": {
                        "work_id": {"type": "string", "enum": list(work_ids)},
                        "action": {"type": "string", "enum": ["keep", "change"]},
                        "decision": {"type": "string", "enum": ["bind", "covered_by", "unbound"]},
                        "norm_code": {"type": "string"},
                        "selection_kind": {"type": "string", "enum": ["exact", "analog"]},
                        "applicability": {
                            "type": "string",
                            "enum": ["exact", "close_analog", "weak_analog"],
                        },
                        "sibling_criterion": {"type": "string"},
                        "covered_by_work_id": {"type": "string"},
                        "unbound_evidence": unbound_evidence,
                        "reason": {"type": "string"},
                    },
                    "required": ["work_id", "action", "reason"],
                },
            }
        },
        "required": ["rows"],
    }


def _selection_from_self_check_change(
    item: dict[str, Any],
    *,
    previous: dict[str, Any],
) -> dict[str, Any] | None:
    decision = str(item.get("decision") or "").strip()
    reason = str(item.get("reason") or "").strip()
    if decision == "bind":
        code = str(item.get("norm_code") or "").strip()
        if not code:
            return None
        return {
            "norm_code": code,
            "selection_kind": str(item.get("selection_kind") or previous.get("selection_kind") or "analog"),
            "applicability": str(item.get("applicability") or previous.get("applicability") or "close_analog"),
            "technology_check": dict(previous.get("technology_check") or {}),
            "analog_limitations": list(previous.get("analog_limitations") or []),
            "nr_sp_rule_id": str(previous.get("nr_sp_rule_id") or ""),
            "reason": reason,
            "review_status": "model_self_check",
            "resource_bindings": list(previous.get("resource_bindings") or []),
            "precalculation_blockers": [],
            "sibling_criterion": str(item.get("sibling_criterion") or "").strip(),
        }
    if decision == "covered_by":
        covered_by = str(item.get("covered_by_work_id") or "").strip()
        if not covered_by:
            return None
        return {
            "norm_code": "",
            "selection_kind": str(item.get("selection_kind") or ""),
            "analog_limitations": list(previous.get("analog_limitations") or []),
            "covered_by_work_id": covered_by,
            "coverage_reason": reason,
            "reason": reason,
            "review_status": "model_self_check_covered",
            "resource_bindings": [],
            "precalculation_blockers": [],
        }
    if decision == "unbound":
        evidence = dict(item.get("unbound_evidence") or previous.get("unbound_evidence") or {})
        return {
            "norm_code": "",
            "selection_kind": str(item.get("selection_kind") or previous.get("selection_kind") or ""),
            "analog_limitations": list(previous.get("analog_limitations") or []),
            "reason": reason,
            "unbound_evidence": evidence,
            "review_status": "model_self_check_unbound",
            "resource_bindings": [],
            "precalculation_blockers": list(previous.get("precalculation_blockers") or []),
        }
    return None


def _apply_mapping_self_check(
    selections: dict[str, dict[str, Any]],
    *,
    work_rows: list[dict[str, Any]],
    browse_trace: dict[str, list[dict[str, Any]]],
    rows: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    work_ids = [str(row.get("work_id") or "") for row in work_rows if str(row.get("work_id") or "")]
    by_reply = {
        str(item.get("work_id") or ""): item
        for item in rows
        if isinstance(item, dict) and str(item.get("work_id") or "") in work_ids
    }
    if set(by_reply.keys()) != set(work_ids):
        return selections, {
            "status": "skipped_incomplete",
            "expected_rows": len(work_ids),
            "returned_rows": len(by_reply),
        }

    updated = {key: dict(value) for key, value in selections.items()}
    applied: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for work_id in work_ids:
        item = by_reply[work_id]
        action = str(item.get("action") or "").strip()
        if action != "change":
            continue
        previous = dict(updated.get(work_id) or {})
        candidate = _selection_from_self_check_change(item, previous=previous)
        if candidate is None:
            rejected.append({"work_id": work_id, "reason": "incomplete_change_payload"})
            continue
        decision = str(item.get("decision") or "")
        if decision == "bind":
            new_code = str(candidate.get("norm_code") or "")
            allowed = set(_browse_candidate_codes(browse_trace, work_id))
            old_code = str(previous.get("norm_code") or "").strip()
            if old_code:
                allowed.add(old_code)
            if new_code not in allowed:
                rejected.append({
                    "work_id": work_id,
                    "reason": "norm_code_outside_current_run_evidence",
                    "norm_code": new_code,
                })
                continue
            if (
                old_code
                and new_code
                and old_code != new_code
                and _norm_table_stem(old_code) == _norm_table_stem(new_code)
                and not str(item.get("sibling_criterion") or "").strip()
            ):
                rejected.append({
                    "work_id": work_id,
                    "reason": "sibling_flip_without_criterion",
                    "from": old_code,
                    "to": new_code,
                })
                continue
        updated[work_id] = candidate
        applied.append({
            "work_id": work_id,
            "from": previous.get("norm_code") or previous.get("review_status"),
            "to": candidate.get("norm_code") or candidate.get("review_status"),
            "decision": decision,
        })
    return updated, {
        "status": "applied",
        "changed_rows": len(applied),
        "rejected_rows": len(rejected),
        "changes": applied,
        "rejected": rejected,
    }


def _run_mapping_self_check(
    *,
    work_rows: list[dict[str, Any]],
    selections: dict[str, dict[str, Any]],
    browse_trace: dict[str, list[dict[str, Any]]],
    mapping_exchange: MappingExchange | None,
    user_request: str = "",
    progress: Progress | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    """Same-run model confirmation before calculation; no past-file memory."""
    if mapping_exchange is None:
        return selections, {"status": "skipped_no_mapping_exchange"}, []
    if not _env_flag("LES_SMETA_DOCUMENT_SELF_CHECK", True):
        return selections, {"status": "skipped_disabled"}, []
    work_ids = [str(row.get("work_id") or "") for row in work_rows if str(row.get("work_id") or "")]
    if not work_ids or len(selections) < len(work_ids):
        return selections, {"status": "skipped_incomplete_selections"}, []

    review_rows = []
    for row in work_rows:
        work_id = str(row.get("work_id") or "")
        selection = selections.get(work_id) or {}
        review_rows.append({
            "work_id": work_id,
            "title": row.get("title"),
            "unit": row.get("unit"),
            "quantity": row.get("quantity"),
            "current": {
                "norm_code": selection.get("norm_code") or "",
                "review_status": selection.get("review_status"),
                "selection_kind": selection.get("selection_kind"),
                "reason": selection.get("reason"),
                "precalculation_blockers": selection.get("precalculation_blockers") or [],
            },
            "candidate_norm_codes": _browse_candidate_codes(browse_trace, work_id)[:12],
        })
    schema = _self_check_output_schema(work_ids)
    messages = [
        {
            "role": "system",
            "content": (
                "Ты тот же сметчик внутри текущего прогона. Это self-check, не память прошлого файла. "
                "Для каждой строки верни action=keep или change. "
                "Меняй только при явной ошибке соседнего шифра одной таблицы или слабом unbound. "
                "При смене на соседний шифр обязателен sibling_criterion (крепление/размер/тип/измеритель). "
                "Новый norm_code только из candidate_norm_codes или текущего кода. "
                "Код не выбирает норму за тебя."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": "confirm_or_correct_mapping",
                    "user_request": str(user_request or "").strip(),
                    "rows": review_rows,
                    "output_schema": schema,
                },
                ensure_ascii=False,
                default=str,
            ),
        },
    ]
    if progress:
        progress({
            "phase": "self_check",
            "status": "started",
            "label": "Смета: модель проверяет свои решения в этом же прогоне",
            "rows": len(work_ids),
        })
    started = perf_counter()
    try:
        payload = mapping_exchange(messages, schema) or {}
    except Exception as error:  # keep first mapping if transport fails
        trace = {
            "status": "skipped_transport_error",
            "error": f"{type(error).__name__}: {error}",
            "elapsed_ms": round((perf_counter() - started) * 1000, 2),
        }
        if progress:
            progress({
                "phase": "self_check",
                "status": "error",
                "label": "Смета: self-check пропущен из‑за ошибки транспорта",
            })
        return selections, trace, []
    wait_ms = round((perf_counter() - started) * 1000, 2)
    rows = _tool_array_argument(payload, "rows", aliases=("mapping",))
    updated, apply_trace = _apply_mapping_self_check(
        selections,
        work_rows=work_rows,
        browse_trace=browse_trace,
        rows=rows,
    )
    apply_trace = {
        **apply_trace,
        "elapsed_ms": wait_ms,
        "model": payload.get("_les_model"),
        "provider": payload.get("_les_provider"),
    }
    model_trace_item = {
        "turn": "self_check",
        "assistant": {
            "role": "assistant",
            "content": json.dumps({"rows": rows}, ensure_ascii=False, default=str),
            "model": payload.get("_les_model"),
        },
        "model_wait_ms": wait_ms,
        "transport": "structured_self_check",
        "apply": apply_trace,
    }
    if progress:
        progress({
            "phase": "self_check",
            "status": "done",
            "label": (
                f"Смета: self-check готов, изменено {apply_trace.get('changed_rows', 0)} строк"
            ),
            "changed_rows": apply_trace.get("changed_rows"),
            "rejected_rows": apply_trace.get("rejected_rows"),
        })
    return updated, apply_trace, [model_trace_item]


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
        created_by="model",
        change_note=f"Model-owned VOR workflow: {display_source_name}",
        revision_root=revision_root,
        book=book,
        title=f"Локальный сметный расчет — {display_stem}",
    )
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
    agent_result = _run_native_norm_agent(
        query_rows,
        exchange,
        mapping_exchange=mapping_exchange,
        candidate_limit=candidate_limit,
        max_turns=max_agent_turns,
        progress=progress,
        user_request=user_request,
        batch_size=batch_size,
        batch_runner=agent_batch_runner,
    )
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
    selections = dict(agent_result["selections"] or {})
    model_trace = list(agent_result.get("model_trace") or [])
    agent_trace = dict(agent_result.get("agent_trace") or {})
    selections, self_check_trace, self_check_model_trace = _run_mapping_self_check(
        work_rows=work_rows,
        selections=selections,
        browse_trace=agent_result.get("browse_trace") or {},
        mapping_exchange=mapping_exchange,
        user_request=user_request,
        progress=progress,
    )
    model_trace.extend(self_check_model_trace)
    agent_trace["self_check"] = self_check_trace
    return _finalize_document_workflow(
        path=path,
        intake=intake,
        work_rows=work_rows,
        selections=selections,
        browse_trace=agent_result["browse_trace"],
        query_trace=agent_result["query_trace"],
        model_trace=model_trace,
        agent_trace=agent_trace,
        book=book,
        out_xlsx=out_xlsx,
        out_report=out_report,
        revision_root=revision_root,
        vat_pct=vat_pct,
        progress=progress,
        source_name=source_name,
        lsr_meta=lsr_meta,
    )


def run_vor_pdf_workflow(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Backward-compatible public name; the workflow now also accepts XLSX."""
    return run_vor_document_workflow(*args, **kwargs)
