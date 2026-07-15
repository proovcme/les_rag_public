"""Generic document -> VOR -> model selection -> priced LSR workflow."""

from __future__ import annotations

import ast
import json
from dataclasses import asdict
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from proxy.services import fgis_price_service, gesn_service, nr_sp_service
from proxy.services.kac_web_service import collect_quotes
from proxy.services.prompt_registry_service import smeta_native_skill_excerpt
from proxy.services.rim_trace_xlsx_service import render_lsr_xlsx
from proxy.smeta_core.contracts import NormBinding, ResourceBinding, WorkItem
from proxy.smeta_core.norm_browser import browse_norms_many
from proxy.smeta_core.norm_validator import units_compatible, validate_binding
from proxy.smeta_core.resource_normalizer import normalize_norm_resources
from proxy.smeta_core.source_intake import intake_vor_document
from proxy.smeta_core.application import calculate_visible_rows, calculate_visible_rows_revision


Exchange = Callable[[list[dict[str, Any]], list[dict[str, Any]]], dict[str, Any]]
Progress = Callable[[dict[str, Any]], None]


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
    queries = [str(item).strip() for item in (query if isinstance(query, list) else [query]) if str(item).strip()]
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


_TECHNOLOGY_CHECK_FIELDS = {
    "matched_operations": list,
    "missing_operations": list,
    "extra_operations": list,
    "foreign_resources": list,
    "overlaps_with_work_ids": list,
    "overlap_resolution": str,
    "conditions_checked": list,
    "unresolved_conditions": list,
    "conclusion": str,
}


def _bind_submission_errors(item: dict[str, Any]) -> list[str]:
    """Validate completeness of the model's evidence, never its professional choice."""
    errors: list[str] = []
    reason = str(item.get("reason") or "").strip()
    if not reason:
        errors.append("bind requires a non-empty reason")
    kind = str(item.get("selection_kind") or "")
    if not isinstance(item.get("analog_limitations"), list):
        errors.append("bind requires explicit analog_limitations array")
    limitations = [str(value).strip() for value in (item.get("analog_limitations") or []) if str(value).strip()]
    if kind not in {"exact", "analog"}:
        errors.append("bind requires explicit selection_kind exact|analog")
    elif kind == "analog" and not limitations:
        errors.append("analog requires explicit analog_limitations")
    elif kind == "exact" and limitations:
        errors.append("exact binding cannot carry analog_limitations")
    applicability = str(item.get("applicability") or "")
    if applicability not in {"exact", "close_analog", "weak_analog"}:
        errors.append("bind requires explicit applicability")
    elif kind == "exact" and applicability != "exact":
        errors.append("exact selection requires exact applicability")
    elif kind == "analog" and applicability not in {"close_analog", "weak_analog"}:
        errors.append("analog selection requires analog applicability")

    check = item.get("technology_check")
    if check is not None and not isinstance(check, dict):
        errors.append("technology_check must be an object when provided")
    elif isinstance(check, dict):
        for field, expected_type in _TECHNOLOGY_CHECK_FIELDS.items():
            if field in check and not isinstance(check.get(field), expected_type):
                errors.append(f"technology_check.{field} has invalid type")
        conclusion = str(check.get("conclusion") or "")
        if conclusion and conclusion not in {"applicable", "applicable_with_limitations"}:
            errors.append("technology_check.conclusion must be applicable|applicable_with_limitations")
        overlap_ids = [str(value) for value in (check.get("overlaps_with_work_ids") or []) if str(value)]
        if overlap_ids and not str(check.get("overlap_resolution") or "").strip():
            errors.append("technology_check.overlap_resolution is required for overlaps")

    for index, action in enumerate(item.get("resource_actions") or []):
        if not isinstance(action, dict):
            errors.append(f"resource_actions[{index}] must be an object")
            continue
        if not str(action.get("reason") or "").strip():
            errors.append(f"resource_actions[{index}].reason is required")
        if not str(action.get("basis_ref") or "").strip():
            errors.append(f"resource_actions[{index}].basis_ref is required")
    return errors


def _normalize_mapping_row_transport(item: dict[str, Any]) -> dict[str, Any]:
    """Repair a harmless tool-schema placement error without changing model decisions."""
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


def _tool_array_argument(args: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """Unwrap a model's harmless double-serialization of a tool array."""
    raw = args.get(key)
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
                return []
    return [item for item in (raw or []) if isinstance(item, dict)] if isinstance(raw, list) else []


def _tool_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}


def _run_native_norm_agent(
    work_rows: list[dict[str, Any]],
    exchange: Exchange,
    *,
    candidate_limit: int,
    max_turns: int = 64,
    batch_size: int = 0,
    progress: Progress | None = None,
    user_request: str = "",
) -> dict[str, Any]:
    """Give the model the source rows and merge its untouched decisions."""
    requested_size = int(batch_size)
    size = len(work_rows) if requested_size <= 0 else max(1, requested_size)
    batches = [work_rows[index:index + size] for index in range(0, len(work_rows), size)]
    if len(batches) <= 1:
        return _run_batch_norm_agent(
            work_rows,
            exchange,
            candidate_limit=candidate_limit,
            max_turns=max_turns,
            progress=progress,
            user_request=user_request,
            context_rows=work_rows,
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
        result = _run_batch_norm_agent(
            rows,
            exchange,
            candidate_limit=candidate_limit,
            max_turns=max_turns,
            progress=progress,
            user_request=user_request,
            context_rows=work_rows,
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
        "batch_size": size,
        "batches": len(batches),
        "source_rows": len(work_rows),
        "batch_traces": batch_traces,
    }
    return merged


def _run_batch_norm_agent(
    work_rows: list[dict[str, Any]],
    exchange: Exchange,
    *,
    candidate_limit: int,
    max_turns: int = 64,
    progress: Progress | None = None,
    user_request: str = "",
    context_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Thin model tool loop: batch RAG, batch read, one model-owned mapping submission."""
    by_id = {str(row["work_id"]): row for row in work_rows}
    all_rows = context_rows or work_rows
    all_work_ids = {str(row["work_id"]) for row in all_rows}
    candidates: dict[str, dict[str, dict[str, Any]]] = {work_id: {} for work_id in by_id}
    opened: dict[str, dict[str, dict[str, Any]]] = {work_id: {} for work_id in by_id}
    browse_trace: dict[str, list[dict[str, Any]]] = {work_id: [] for work_id in by_id}
    query_trace: list[dict[str, Any]] = []
    model_trace: list[dict[str, Any]] = []
    context_metrics: list[dict[str, Any]] = []
    tools = _batch_norm_tools()
    skill_excerpt = smeta_native_skill_excerpt()
    system_prompt = (
        "Ты сметчик. Самостоятельно собери mapping для денежной ЛСР. Используй batch RAG tools в любом "
        "нужном порядке, прочитай фактические карточки и одним submit_lsr_mapping передай решения по всем "
        "строкам текущего пакета work_items. Код не выбирает нормы, аналоги, coverage или ресурсы — после submit он только "
        "проверит ссылки и единицы, рассчитает твоё решение и сформирует XLSX. "
        "Для decision=bind передай поля norm_code, selection_kind, applicability, "
        "analog_limitations (пустой массив только для exact; для analog минимум одно конкретное ограничение), "
        "resource_actions только если нужно изменить ресурсы нормы и кратко объясни технологическое решение. "
        "technology_check можно добавить для операций, условий и пересечений, но это не обязательная анкета."
    )
    if skill_excerpt:
        system_prompt += "\n\n" + skill_excerpt
    full_source_context = [] if set(by_id) == all_work_ids else [
        {
            "work_id": row.get("work_id"),
            "title": str(row.get("title") or "")[:180],
            "unit": row.get("unit"),
            "quantity": row.get("quantity"),
            "section": str(row.get("section") or "")[:100],
        }
        for row in all_rows
    ]
    conversation: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps({
            "user_request": str(user_request or "").strip(),
            "work_items": list(by_id.values()),
            "all_source_rows_context": full_source_context,
            "batch_contract": (
                "submit decisions for every work_id in work_items only; all_source_rows_context is navigation "
                "for overlap/coverage and is not an instruction to submit other batches"
            ),
        }, ensure_ascii=False, default=str)},
    ]

    if max_turns < 1:
        raise ValueError("max_turns must be positive")
    consecutive_non_tool_turns = 0
    invalid_submission_attempts = 0
    for turn in range(1, max_turns + 1):
        started = perf_counter()
        last_tool_name = next(
            (
                str(message.get("name") or "")
                for message in reversed(conversation)
                if str(message.get("role") or "") == "tool"
            ),
            "",
        )
        turn_tools = (
            [tool for tool in tools if str((tool.get("function") or {}).get("name") or "") != "submit_lsr_mapping"]
            if last_tool_name == "search_norms_batch"
            else tools
        )
        assistant = exchange(conversation, turn_tools) or {}
        model_wait_ms = round((perf_counter() - started) * 1000, 2)
        calls = [call for call in (assistant.get("tool_calls") or []) if isinstance(call, dict)]
        assistant_message = {
            "role": "assistant",
            "content": str(assistant.get("content") or "").strip() or None,
            "tool_calls": calls,
        }
        if assistant.get("_les_model"):
            assistant_message["model"] = str(assistant["_les_model"])
        if assistant.get("_les_fallback_from"):
            assistant_message["fallback_from"] = str(assistant["_les_fallback_from"])
        conversation.append(assistant_message)
        model_trace.append({"turn": turn, "assistant": assistant_message, "model_wait_ms": model_wait_ms})
        context_metrics.append({
            "turn": turn,
            "prompt_chars": len(json.dumps(conversation, ensure_ascii=False, default=str)),
            "model_wait_ms": model_wait_ms,
            "tool_calls": len(calls),
        })
        if progress:
            progress({
                "phase": "model_wait", "status": "done",
                "label": f"Смета: модель завершила ход {turn}",
                "turn": turn, "model_wait_ms": model_wait_ms,
            })
        if not calls:
            consecutive_non_tool_turns += 1
            if consecutive_non_tool_turns <= 3 and turn < max_turns:
                conversation.append({
                    "role": "user",
                    "content": (
                        "Предыдущий ответ не был вызовом инструмента. Исправь последнюю ошибку из "
                        "результата tool и продолжи только вызовом подходящего предоставленного инструмента; "
                        "не объясняй ответ текстом."
                    ),
                })
                continue
            raise RuntimeError("smeta model returned no tool calls after correction attempts")
        consecutive_non_tool_turns = 0

        submitted: dict[str, dict[str, Any]] | None = None
        for call_index, call in enumerate(calls, 1):
            call_id = str(call.get("id") or f"batch-{turn}-{call_index}")
            name = str(((call.get("function") or {}).get("name") or ""))
            args = _tool_arguments(call)
            result: dict[str, Any]
            if name == "search_norms_batch":
                items = _tool_array_argument(args, "items")
                all_queries = list(dict.fromkeys(
                    " ".join(str(query).split())[:240]
                    for item in items for query in (item.get("queries") or []) if str(query).strip()
                ))
                search_results = browse_norms_many(
                    all_queries,
                    limit=100,
                    rerank=bool(args.get("rerank", False)),
                ) if all_queries else {}
                rows_out = []
                for item in items:
                    work_id = str(item.get("work_id") or "")
                    if work_id not in by_id:
                        rows_out.append({"work_id": work_id, "ok": False, "error": "unknown work_id"})
                        continue
                    queries = [" ".join(str(query).split())[:240] for query in (item.get("queries") or []) if str(query).strip()]
                    limit = max(1, int(item.get("limit") or candidate_limit))
                    page = max(0, int(item.get("page") or 0))
                    payload = _candidate_payload(
                        by_id[work_id], queries, limit=limit, page=page,
                        search_results=search_results,
                    )
                    browse_trace[work_id].append(payload)
                    compact = []
                    for card in payload.get("candidates") or []:
                        code = str(card.get("norm_code") or "")
                        candidates[work_id][code] = card
                        compact.append({
                            "norm_code": code,
                            "title": str(card.get("title") or "")[:180],
                            "measure_unit": card.get("measure_unit"),
                        })
                    rows_out.append({
                        "work_id": work_id, "ok": True, "candidates": compact,
                        "page": page, "has_more": bool(payload.get("has_more")),
                    })
                    query_trace.append({
                        "phase": "batch_search", "turn": turn, "work_id": work_id,
                        "queries": queries, "candidate_count": len(compact), "page": page,
                    })
                result = {"ok": True, "rows": rows_out}
            elif name == "read_norms_batch":
                rows_out = []
                for item in _tool_array_argument(args, "items"):
                    work_id = str(item.get("work_id") or "")
                    cards = []
                    include_resources = _tool_bool(
                        item.get("include_resources"),
                        _tool_bool(args.get("include_resources"), False),
                    )
                    for code in _normalize_norm_codes_transport(item):
                        candidate = candidates.get(work_id, {}).get(code)
                        card = _opened_norm_card(code, candidate) if candidate else None
                        if card:
                            opened[work_id][code] = card
                            cards.append(_norm_card_for_model(card, include_resources=include_resources))
                    rows_out.append({"work_id": work_id, "ok": bool(cards), "norms": cards})
                result = {"ok": True, "rows": rows_out}
            elif name == "submit_lsr_mapping":
                rows = [
                    _normalize_mapping_row_transport(item)
                    for item in _tool_array_argument(args, "rows")
                ]
                proposed: dict[str, dict[str, Any]] = {}
                errors: list[dict[str, Any]] = []
                for item in rows:
                    work_id = str(item.get("work_id") or "")
                    decision = str(item.get("decision") or "")
                    if work_id not in by_id or work_id in proposed:
                        errors.append({"work_id": work_id, "error": "unknown or duplicate work_id"})
                        continue
                    if decision == "unbound":
                        reason = str(item.get("reason") or "").strip()
                        if not reason:
                            errors.append({"work_id": work_id, "error": "unbound requires a non-empty reason"})
                            continue
                        proposed[work_id] = {
                            "norm_code": "", "selection_kind": "", "analog_limitations": [],
                            "reason": reason,
                            "review_status": "model_batch_unbound", "resource_bindings": [],
                        }
                        continue
                    if decision == "covered_by":
                        covered_by = str(item.get("covered_by_work_id") or "")
                        reason = str(item.get("reason") or "").strip()
                        if not covered_by or covered_by == work_id or covered_by not in all_work_ids or not reason:
                            errors.append({"work_id": work_id, "error": "covered_by requires another work_id and a non-empty reason"})
                            continue
                        proposed[work_id] = {
                            "norm_code": "", "selection_kind": "", "analog_limitations": [],
                            "covered_by_work_id": covered_by,
                            "coverage_reason": reason,
                            "reason": reason,
                            "review_status": "model_batch_covered", "resource_bindings": [],
                        }
                        continue
                    code = str(item.get("norm_code") or "")
                    if decision != "bind" or code not in opened.get(work_id, {}):
                        errors.append({"work_id": work_id, "error": "bound norm must be returned by RAG and opened by the model"})
                        continue
                    bind_errors = _bind_submission_errors(item)
                    if bind_errors:
                        errors.extend({"work_id": work_id, "error": error} for error in bind_errors)
                        continue
                    kind = str(item.get("selection_kind") or "")
                    proposed[work_id] = {
                        "norm_code": code,
                        "selection_kind": kind,
                        "applicability": str(item.get("applicability") or ("exact" if kind == "exact" else "close_analog")),
                        "technology_check": dict(item.get("technology_check") or {}),
                        "analog_limitations": [str(value) for value in (item.get("analog_limitations") or []) if str(value).strip()],
                        "nr_sp_rule_id": str(item.get("nr_sp_rule_id") or ""),
                        "reason": str(item.get("reason") or ""),
                        "review_status": "model_batch",
                        "resource_bindings": _model_resource_bindings(work_id, item, by_id[work_id]),
                    }
                missing = [work_id for work_id in by_id if work_id not in proposed]
                if missing:
                    errors.append({"error": "missing work_ids", "work_ids": missing})
                for work_id, item in proposed.items():
                    if item.get("covered_by_work_id") and item["covered_by_work_id"] not in all_work_ids:
                        errors.append({"work_id": work_id, "error": "covered_by_work_id is absent"})
                if errors:
                    invalid_submission_attempts += 1
                    result = {"ok": False, "errors": errors}
                    if progress:
                        first_error = str((errors[0] or {}).get("error") or "некорректный mapping")
                        progress({
                            "phase": "mapping_retry",
                            "status": "waiting",
                            "label": f"Смета: модель исправляет решение — {first_error}",
                            "attempt": invalid_submission_attempts,
                            "errors": errors[:5],
                        })
                    if invalid_submission_attempts >= 4:
                        raise RuntimeError(
                            "smeta model could not produce a valid mapping after 4 correction attempts: "
                            + json.dumps(errors[:5], ensure_ascii=False, default=str)
                        )
                else:
                    submitted = proposed
                    result = {"ok": True, "rows": len(proposed)}
            else:
                result = {"ok": False, "error": f"unknown tool: {name}"}
            tool_message = {
                "role": "tool", "tool_call_id": call_id, "name": name,
                "content": json.dumps(result, ensure_ascii=False, default=str),
            }
            conversation.append(tool_message)
            model_trace[-1].setdefault("tool_results", []).append({"name": name, "result": result})
        if submitted is not None:
            return {
                "selections": submitted,
                "browse_trace": browse_trace,
                "query_trace": query_trace,
                "model_trace": model_trace,
                "valid_model_rows": len(submitted),
                "agent_trace": {
                    "mode": "model_batch_rag_tools",
                    "turns": turn,
                    "context_metrics": context_metrics,
                },
            }
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
            "quantity_basis": str(action.get("quantity_basis") or "explicit"),
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
        and str(action.get("action") or "") in {"add", "replace", "exclude", "reuse"}
        and str(action.get("reason") or "").strip()
        and str(action.get("basis_ref") or "").strip()
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
        "required": list(_TECHNOLOGY_CHECK_FIELDS),
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
                    "norm_code",
                    "selection_kind",
                    "applicability",
                    "analog_limitations",
                ]},
            },
            {
                "if": {"properties": {"decision": {"const": "covered_by"}}, "required": ["decision"]},
                "then": {"required": ["covered_by_work_id"]},
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
                            "work_id": {"type": "string"}, "queries": {"type": "array", "items": {"type": "string"}},
                            "limit": {"type": "integer", "minimum": 1}, "page": {"type": "integer", "minimum": 0},
                        }, "required": ["work_id", "queries"]}},
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
                        "work_id": {"type": "string"}, "norm_codes": {"type": "array", "items": {"type": "string"}},
                        "include_resources": {"type": "boolean", "description": "Return the full resource list when resource composition or edits must be reviewed."},
                    }, "required": ["work_id", "norm_codes"]}},
                }, "required": ["items"]},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "submit_lsr_mapping",
                "description": "Submit the model's complete professional decision for all source rows; LES then calculates and creates XLSX.",
                "parameters": {"type": "object", "properties": {
                    "rows": {"type": "array", "items": mapping_row},
                }, "required": ["rows"]},
            },
        },
    ]





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
            "selection_kind": selection.get("selection_kind") or "exact",
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
        candidate_limit=candidate_limit,
        progress=progress,
        user_request=user_request,
        batch_size=batch_size,
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
    )


def run_vor_pdf_workflow(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Backward-compatible public name; the workflow now also accepts XLSX."""
    return run_vor_document_workflow(*args, **kwargs)
