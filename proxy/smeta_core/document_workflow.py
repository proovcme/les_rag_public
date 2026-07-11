"""Generic document -> VOR -> model selection -> priced LSR workflow."""

from __future__ import annotations

import json
import re
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
from proxy.smeta_core.source_intake import intake_vor_pdf
from proxy.smeta_core.workflow import calculate_visible_rows, calculate_visible_rows_revision


Complete = Callable[[list[dict[str, str]]], str]
Exchange = Callable[[list[dict[str, Any]], list[dict[str, Any]]], dict[str, Any]]
Progress = Callable[[dict[str, Any]], None]


def document_execution_budget(
    source_rows: int,
    *,
    base_calls: int = 16,
    base_deadline_sec: float = 360.0,
) -> dict[str, float | int]:
    """Scale transport capacity by VOR size without changing professional decisions."""
    rows = max(1, int(source_rows or 0))
    batches = max(1, (rows + 19) // 20)
    return {
        "source_rows": rows,
        "batches": batches,
        "max_calls": max(int(base_calls), 12 + batches * 4),
        "deadline_sec": max(float(base_deadline_sec), 240.0 + batches * 120.0),
    }


def _json_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL | re.IGNORECASE)
    if fence:
        raw = fence.group(1)
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        payload = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _candidate_payload(
    work: dict[str, Any],
    query: str | list[str],
    *,
    limit: int,
    search_results: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
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
            if len(cards) >= limit:
                break
        if len(cards) >= limit:
            break
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
        "candidates": cards,
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


def _native_norm_tools() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "search_norms",
                "description": "Search the typed GESN norm base for one source work item.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "work_id": {"type": "string"},
                        "queries": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 3},
                        "base_types": {
                            "type": "array",
                            "items": {"type": "string", "enum": ["ГЭСН", "ГЭСНм", "ГЭСНмр", "ГЭСНп", "ГЭСНр"]},
                            "maxItems": 3,
                        },
                        "collections": {
                            "type": "array",
                            "items": {"type": "string", "pattern": "^[0-9]{2}$"},
                            "maxItems": 5,
                        },
                        "rerank": {
                            "type": "boolean",
                            "description": "Use expensive reranking only for a narrow disputed shortlist.",
                        },
                        "search_reason": {
                            "type": "string",
                            "description": "Required only after the soft search budget for this work item is exhausted.",
                        },
                    },
                    "required": ["work_id", "queries"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_norm",
                "description": "Open full work steps and resources for candidate norm codes before deciding.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "work_id": {"type": "string"},
                        "norm_codes": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 4},
                    },
                    "required": ["work_id", "norm_codes"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "bind_norm",
                "description": (
                    "Bind an opened candidate norm to one source row. Source quantity and conversion to the norm "
                    "measure are calculated only by code; this tool accepts no quantity multiplier. Call this only "
                    "when the final decision is to use the norm; otherwise call leave_unbound."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "work_id": {"type": "string"},
                        "decision": {"type": "string", "enum": ["selected"]},
                        "norm_code": {"type": "string"},
                        "selection_kind": {"type": "string", "enum": ["exact", "analog"]},
                        "applicability": {"type": "string", "enum": ["exact", "close_analog", "weak_analog"]},
                        "analog_limitations": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
                        "technology_check": {
                            "type": "object",
                            "properties": {
                                "matched_operations": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                                "missing_operations": {"type": "array", "items": {"type": "string"}},
                                "extra_operations": {"type": "array", "items": {"type": "string"}},
                                "foreign_resources": {"type": "array", "items": {"type": "string"}},
                                "conclusion": {
                                    "type": "string",
                                    "enum": ["applicable", "applicable_with_limitations"],
                                },
                            },
                            "required": ["matched_operations", "missing_operations", "extra_operations", "foreign_resources", "conclusion"],
                        },
                        "nr_sp_rule_id": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": [
                        "work_id", "decision", "norm_code", "selection_kind", "reason"
                    ],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "mark_covered_by",
                "description": (
                    "Mark a source row as already included in the work steps/resources of an earlier selected norm. "
                    "Use only when the compact decision registry proves both the work and every physical material/"
                    "fastener from the source row. Partial labor-only coverage must remain visible via leave_unbound."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "work_id": {"type": "string"},
                        "covered_by_work_id": {"type": "string"},
                        "covered_components": {
                            "type": "array",
                            "items": {"type": "string", "enum": ["labor", "material", "fastener", "machine", "testing"]},
                            "minItems": 1,
                        },
                        "remaining_components": {
                            "type": "array",
                            "items": {"type": "string", "enum": ["labor", "material", "fastener", "machine", "testing"]},
                        },
                        "reason": {"type": "string"},
                    },
                    "required": ["work_id", "covered_by_work_id", "reason"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "leave_unbound",
                "description": "Keep a source row visible with missing/null price when no defensible norm exists.",
                "parameters": {
                    "type": "object",
                    "properties": {"work_id": {"type": "string"}, "reason": {"type": "string"}},
                    "required": ["work_id", "reason"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "finish_norm_selection",
                "description": "Finish only after every source work item has either a norm binding or an explicit unbound decision.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]


def _tool_arguments(call: dict[str, Any]) -> dict[str, Any]:
    function = call.get("function") if isinstance(call, dict) else {}
    raw = (function or {}).get("arguments")
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(str(raw or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _run_native_norm_agent(
    work_rows: list[dict[str, Any]],
    exchange: Exchange,
    *,
    candidate_limit: int,
    max_turns: int = 64,
    progress: Progress | None = None,
) -> dict[str, Any]:
    """Give the model the source and RAG tools; code only executes and compacts state."""
    by_id = {str(row["work_id"]): row for row in work_rows}
    candidates: dict[str, dict[str, dict[str, Any]]] = {work_id: {} for work_id in by_id}
    candidate_order: dict[str, list[str]] = {work_id: [] for work_id in by_id}
    opened: dict[str, dict[str, dict[str, Any]]] = {work_id: {} for work_id in by_id}
    opened_pending_delivery: dict[str, list[str]] = {work_id: [] for work_id in by_id}
    browse_trace: dict[str, list[dict[str, Any]]] = {work_id: [] for work_id in by_id}
    search_history: dict[str, list[dict[str, Any]]] = {work_id: [] for work_id in by_id}
    search_cache: dict[tuple[tuple[str, ...], tuple[str, ...], bool, str], dict[str, Any]] = {}
    selections: dict[str, dict[str, Any]] = {}
    query_trace: list[dict[str, Any]] = []
    model_trace: list[dict[str, Any]] = []
    context_metrics: list[dict[str, Any]] = []
    system_prompt = (
        "Ты сметчик. Получи привязки норм для денежной ЛСР по всем строкам исходной ВОР. "
        "Самостоятельно используй search_norms и read_norm, выбирай точную норму или разумный аналог, "
        "а при отсутствии защищаемого варианта вызывай leave_unbound. Если одна выбранная норма действительно "
        "покрывает другую исходную строку, используй mark_covered_by. Модель принимает все профессиональные "
        "решения; код только показывает RAG, проверяет существование выбранного кода, переводит количество в "
        "измеритель нормы, считает РИМ и формирует Excel. Не передавай множитель количества: код применит "
        "исходный объём один раз. Обрабатывай независимые строки параллельными tool calls. Когда решения по "
        "всем строкам приняты, вызови finish_norm_selection."
    )
    skill_excerpt = smeta_native_skill_excerpt()
    if skill_excerpt:
        system_prompt += "\n\n" + skill_excerpt

    active_candidate_limit = max(4, min(6, candidate_limit))
    # Serial delivery is more expensive than one larger evidence snapshot for a
    # cloud model: the previous BAP needed 20 paid turns. Keep the registry
    # external, but deliver all cards explicitly requested in the previous turn.
    soft_query_budget = 10_000

    def candidate_summary(card: dict[str, Any]) -> dict[str, Any]:
        previews = []
        for value in list(card.get("resource_preview") or [])[:2]:
            if isinstance(value, dict):
                previews.append({
                    "kind": value.get("kind"),
                    "code": value.get("code"),
                    "name": str(value.get("name") or "")[:120],
                    "unit": value.get("unit"),
                })
            else:
                previews.append(str(value)[:160])
        return {
            "norm_code": card.get("norm_code"),
            "title": str(card.get("title") or "")[:240],
            "measure_unit": card.get("measure_unit"),
            "unit_compatible": card.get("unit_compatible"),
            "resource_kinds": card.get("resource_kinds") or {},
            "resource_preview": previews,
        }

    def opened_summary(card: dict[str, Any]) -> dict[str, Any]:
        return {
            "norm_code": card.get("norm_code"),
            "title": str(card.get("title") or "")[:240],
            "measure_unit": card.get("measure_unit"),
            "status": "opened",
            "work_steps": [str(value)[:160] for value in (card.get("work_steps") or [])[:6]],
            "resource_kinds": {
                kind: sum(1 for item in (card.get("resources") or []) if str(item.get("kind") or "") == kind)
                for kind in ("labor", "machine", "machinist", "material")
            },
        }

    def working_payload() -> tuple[dict[str, Any], list[tuple[str, str]]]:
        pending = [work_id for work_id in by_id if work_id not in selections]
        working_set = []
        for work_id in pending:
            full_values = list(opened[work_id].values())
            active_codes = list(candidates[work_id]) if not full_values else []
            working_set.append({
                "source": by_id[work_id],
                "candidates": [candidate_summary(candidates[work_id][code]) for code in active_codes],
                "opened_norms": full_values,
                "opened_norm_summaries": [],
                "pending_full_cards": 0,
                "search_summary": search_history[work_id][-6:],
            })
        compact_decisions = []
        for work_id, decision in selections.items():
            code = str(decision.get("norm_code") or "")
            selected_card = opened.get(work_id, {}).get(code) or {}
            included_materials = [
                str(resource.get("name") or "")[:120]
                for resource in (selected_card.get("resources") or [])
                if str(resource.get("kind") or "") == "material" and str(resource.get("name") or "").strip()
            ][:6]
            compact_decisions.append({
                "work_id": work_id,
                "source_row": by_id[work_id].get("source_row"),
                "selected_norm": code or None,
                "applicability": decision.get("applicability") or None,
                "covered_by_work_id": decision.get("covered_by_work_id") or None,
                "covered_scope": decision.get("coverage_reason") or decision.get("reason") or "",
                "uncovered_scope": list(decision.get("analog_limitations") or []),
                "included_operations": [str(value)[:160] for value in (selected_card.get("work_steps") or [])[:8]],
                "included_materials": included_materials,
                "excluded_resources": list((decision.get("technology_check") or {}).get("foreign_resources") or []),
                "conflicts": list(decision.get("analog_limitations") or []),
                "source_refs": list(by_id[work_id].get("source_refs") or [])[:3],
            })
        return {
            "working_set": working_set,
            "remaining_total": len(pending),
            "compact_decision_registry": compact_decisions,
            "transport_policy": {
                "full_cards_delivered_once": True,
                "active_candidate_limit_per_work": active_candidate_limit,
                "soft_unique_query_budget_per_work": soft_query_budget,
            },
        }, []

    tools = _native_norm_tools()
    finished = False
    for turn in range(1, max_turns + 1):
        if progress:
            progress({"phase": "native_norm_agent", "turn": turn, "max_turns": max_turns, "done": len(selections), "total": len(work_rows)})
        # Rebuild only the transport state every turn so tool payloads do not grow
        # linearly. The model still sees every pending row and chooses all actions.
        payload, delivered_cards = working_payload()
        payload_json = json.dumps(payload, ensure_ascii=False, default=str)
        context_metrics.append({
            "turn": turn,
            "prompt_chars": len(system_prompt) + len(payload_json),
            "working_rows": len(payload.get("working_set") or []),
            "candidate_cards": sum(len(item.get("candidates") or []) for item in (payload.get("working_set") or [])),
            "opened_cards": sum(len(item.get("opened_norms") or []) for item in (payload.get("working_set") or [])),
            "compact_decisions": len(payload.get("compact_decision_registry") or []),
        })
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": payload_json},
        ]
        model_started = perf_counter()
        assistant = exchange(messages, tools) or {}
        for work_id, code in delivered_cards:
            if code in opened_pending_delivery[work_id]:
                opened_pending_delivery[work_id].remove(code)
        context_metrics[-1]["model_wait_ms"] = round((perf_counter() - model_started) * 1000, 2)
        model_trace.append({"turn": turn, "assistant": assistant})
        calls = [call for call in (assistant.get("tool_calls") or []) if isinstance(call, dict)]
        if not calls:
            raise RuntimeError("smeta model stopped before finish_norm_selection")
        parsed_calls = [(call, _tool_arguments(call)) for call in calls]
        tool_started = perf_counter()
        search_groups: dict[tuple[tuple[str, ...], tuple[str, ...], bool], list[str]] = {}
        budget_blocked_calls: set[str] = set()
        planned_queries: dict[str, set[str]] = {work_id: set() for work_id in by_id}
        for call, args in parsed_calls:
            if str(((call.get("function") or {}).get("name") or "")) != "search_norms":
                continue
            work_id = str(args.get("work_id") or "")
            call_id = str(call.get("id") or f"call-{turn}")
            queries = [
                " ".join(str(value).split())[:240]
                for value in (args.get("queries") or []) if str(value).strip()
            ][:3]
            prior_unique = {
                str(item.get("query") or "").casefold()
                for item in search_history.get(work_id, [])
                if str(item.get("query") or "").strip()
            }
            proposed = {query.casefold() for query in queries}
            if (
                work_id in by_id
                and len(prior_unique | planned_queries[work_id] | proposed) > soft_query_budget
                and not str(args.get("search_reason") or "").strip()
            ):
                budget_blocked_calls.add(call_id)
                continue
            if work_id in planned_queries:
                planned_queries[work_id].update(proposed)
            base_types = tuple(dict.fromkeys(str(value).strip() for value in (args.get("base_types") or []) if str(value).strip()))
            collections = tuple(dict.fromkeys(re.sub(r"\D", "", str(value))[:2] for value in (args.get("collections") or []) if re.sub(r"\D", "", str(value))))
            key = (base_types, collections, bool(args.get("rerank")))
            search_groups.setdefault(key, [])
            search_groups[key].extend(
                " ".join(str(value).split())[:240]
                for value in (args.get("queries") or []) if str(value).strip()
            )
        batch_search_results: dict[tuple[tuple[str, ...], tuple[str, ...], bool], dict[str, dict[str, Any]]] = {}
        executed_queries: set[tuple[tuple[str, ...], tuple[str, ...], bool, str]] = set()
        fresh_search_results: list[dict[str, Any]] = []
        for key, grouped_queries in search_groups.items():
            unique_queries = list(dict.fromkeys(grouped_queries))
            missing_queries = [query for query in unique_queries if (*key, query.casefold()) not in search_cache]
            search_kwargs: dict[str, Any] = {
                "limit": min(50, max(candidate_limit, candidate_limit * 3)),
            }
            if key[2]:
                search_kwargs["rerank"] = True
            if key[0]:
                search_kwargs["base_types"] = list(key[0])
            if key[1]:
                search_kwargs["collections"] = list(key[1])
            fresh = browse_norms_many(missing_queries, **search_kwargs) if missing_queries else {}
            fresh_search_results.extend(fresh.values())
            for query, value in fresh.items():
                cache_key = (*key, query.casefold())
                search_cache[cache_key] = value
                executed_queries.add(cache_key)
            batch_search_results[key] = {
                query: search_cache[(*key, query.casefold())]
                for query in unique_queries if (*key, query.casefold()) in search_cache
            }
        batch_queries = list(dict.fromkeys(query for values in search_groups.values() for query in values))
        context_metrics[-1]["queries_count"] = sum(
            len(args.get("queries") or [])
            for call, args in parsed_calls
            if str(((call.get("function") or {}).get("name") or "")) == "search_norms"
        )
        context_metrics[-1]["unique_queries_count"] = len(batch_queries)
        context_metrics[-1]["executed_unique_queries_count"] = len(executed_queries)
        context_metrics[-1]["search_cache_hits"] = max(0, len(batch_queries) - len(executed_queries))
        context_metrics[-1]["rerank_requested"] = any(key[2] for key in search_groups)
        if fresh_search_results:
            traces = [
                result.get("retrieval_trace") or {} for result in fresh_search_results
            ]
            for metric in ("embedding_ms", "retrieval_ms", "rerank_ms"):
                context_metrics[-1][metric] = sum(float(trace.get(metric) or 0.0) for trace in traces)
        for call, args in parsed_calls:
            call_id = str(call.get("id") or f"call-{turn}")
            function = call.get("function") or {}
            name = str(function.get("name") or "")
            work_id = str(args.get("work_id") or "")
            result: dict[str, Any]
            if name == "search_norms":
                if work_id not in by_id:
                    result = {"ok": False, "error": "unknown work_id"}
                elif call_id in budget_blocked_calls:
                    result = {
                        "ok": False,
                        "error": "soft search budget exhausted",
                        "guidance": "choose reviewed candidates, leave unresolved, or repeat with a concrete search_reason",
                        "reviewed_candidates": [
                            candidate_summary(candidates[work_id][code])
                            for code in candidate_order[work_id][-active_candidate_limit:]
                            if code in candidates[work_id]
                        ],
                    }
                else:
                    queries = [" ".join(str(value).split())[:240] for value in (args.get("queries") or []) if str(value).strip()][:3]
                    base_types = tuple(dict.fromkeys(str(value).strip() for value in (args.get("base_types") or []) if str(value).strip()))
                    collections = tuple(dict.fromkeys(re.sub(r"\D", "", str(value))[:2] for value in (args.get("collections") or []) if re.sub(r"\D", "", str(value))))
                    rerank = bool(args.get("rerank"))
                    normalized_queries = list(dict.fromkeys(query.casefold() for query in queries))
                    prior_unique = {
                        str(item.get("query") or "").casefold()
                        for item in search_history[work_id]
                        if str(item.get("query") or "").strip()
                    }
                    new_unique = [query for query in normalized_queries if query not in prior_unique]
                    payload = _candidate_payload(
                        by_id[work_id], queries, limit=candidate_limit,
                        search_results=batch_search_results.get((base_types, collections, rerank), {}),
                    )
                    browse_trace[work_id].append(payload)
                    for card in payload.get("candidates") or []:
                        code = str(card.get("norm_code") or "")
                        candidates[work_id][code] = card
                        if code in candidate_order[work_id]:
                            candidate_order[work_id].remove(code)
                        candidate_order[work_id].append(code)
                    cached_queries = [
                        query for query in queries
                        if (*((base_types, collections, rerank)), query.casefold()) not in executed_queries
                    ]
                    similar_prior = []
                    for query in queries:
                        words = set(query.casefold().split())
                        for prior in prior_unique:
                            prior_words = set(prior.split())
                            if words and prior_words and len(words & prior_words) / len(words | prior_words) >= 0.8 and query.casefold() != prior:
                                similar_prior.append(prior)
                    for query in queries:
                        search_history[work_id].append({
                            "query": query,
                            "result": f"{len(payload.get('candidates') or [])} candidates",
                            "cached": query in cached_queries,
                            "reranked": rerank,
                        })
                    query_trace.append({
                        "phase": "native_agent_search", "turn": turn, "work_id": work_id,
                        "queries": queries, "base_types": list(base_types), "collections": list(collections),
                        "rerank": rerank, "cached_queries": cached_queries,
                        "candidate_count": len(payload.get("candidates") or []),
                    })
                    search_view = [
                        {
                            "norm_code": card.get("norm_code"),
                            "title": card.get("title"),
                            "measure_unit": card.get("measure_unit"),
                            "unit_compatible": card.get("unit_compatible"),
                            "resource_kinds": card.get("resource_kinds") or {},
                            "resource_preview": card.get("resource_preview") or [],
                        }
                        for card in (payload.get("candidates") or [])
                    ]
                    result = {
                        "ok": True, "work_id": work_id, "candidates": search_view,
                        "backend": payload.get("backend"), "cached_queries": cached_queries,
                        "near_duplicate_queries": list(dict.fromkeys(similar_prior))[:3],
                    }
            elif name == "read_norm":
                if work_id not in by_id:
                    result = {"ok": False, "error": "unknown work_id"}
                else:
                    cards = []
                    cached_codes = []
                    for code in [str(value) for value in (args.get("norm_codes") or [])][:4]:
                        candidate = candidates[work_id].get(code)
                        card = opened[work_id].get(code)
                        if card:
                            cached_codes.append(code)
                        elif candidate:
                            card = _opened_norm_card(code, candidate)
                        if card:
                            opened[work_id][code] = card
                            if code not in opened_pending_delivery[work_id]:
                                opened_pending_delivery[work_id].append(code)
                            cards.append(card)
                    result = {
                        "ok": bool(cards), "work_id": work_id, "norms": cards,
                        "cached_codes": cached_codes,
                        "error": "codes must come from search results" if not cards else "",
                    }
            elif name == "bind_norm":
                code = str(args.get("norm_code") or "")
                decision = str(args.get("decision") or "").casefold()
                kind = str(args.get("selection_kind") or "").casefold()
                applicability = str(args.get("applicability") or ("exact" if kind == "exact" else "close_analog")).casefold()
                technology_check = args.get("technology_check") if isinstance(args.get("technology_check"), dict) else {}
                limitations = [str(value).strip() for value in (args.get("analog_limitations") or []) if str(value).strip()][:3]
                candidate = candidates.get(work_id, {}).get(code)
                contract_valid = (
                    decision == "selected"
                    and kind in {"exact", "analog"}
                )
                if work_id not in by_id or not candidate or code not in opened.get(work_id, {}) or not contract_valid:
                    result = {"ok": False, "error": "binding requires a norm code shown by RAG and opened by the model"}
                else:
                    rule_id = str(args.get("nr_sp_rule_id") or "")
                    allowed_rules = {str(rule.get("rule_id") or "") for rule in (candidate.get("nr_sp_candidates") or [])}
                    selections[work_id] = {
                        "norm_code": code,
                        "selection_kind": kind,
                        "applicability": applicability,
                        "technology_check": technology_check,
                        "analog_limitations": limitations,
                        "nr_sp_rule_id": rule_id if rule_id in allowed_rules else "",
                        "reason": str(args.get("reason") or ""),
                        "review_status": "native_agent",
                    }
                    result = {"ok": True, "work_id": work_id, "bound": code}
            elif name == "mark_covered_by":
                provider = str(args.get("covered_by_work_id") or "")
                provider_decision = selections.get(provider) or {}
                reason = str(args.get("reason") or "").strip()
                covered_components = list(dict.fromkeys(str(value) for value in (args.get("covered_components") or []) if str(value)))
                remaining_components = list(dict.fromkeys(str(value) for value in (args.get("remaining_components") or []) if str(value)))
                if work_id not in by_id or provider not in by_id or not provider_decision.get("norm_code"):
                    result = {"ok": False, "error": "coverage requires an earlier source row with a selected norm"}
                elif not reason:
                    result = {"ok": False, "error": "coverage reason is required"}
                else:
                    selections[work_id] = {
                        "norm_code": "",
                        "selection_kind": "",
                        "analog_limitations": [],
                        "nr_sp_rule_id": "",
                        "covered_by_work_id": provider,
                        "coverage_reason": reason,
                        "covered_components": covered_components,
                        "remaining_components": remaining_components,
                        "reason": reason,
                        "review_status": "native_agent_covered",
                    }
                    result = {"ok": True, "work_id": work_id, "covered_by_work_id": provider}
            elif name == "leave_unbound":
                if work_id not in by_id:
                    result = {"ok": False, "error": "unknown work_id"}
                else:
                    selections[work_id] = {"norm_code": "", "selection_kind": "", "analog_limitations": [], "nr_sp_rule_id": "", "reason": str(args.get("reason") or "норма не найдена"), "review_status": "native_agent_unbound"}
                    result = {"ok": True, "work_id": work_id, "unbound": True}
            elif name == "finish_norm_selection":
                missing = [work_id for work_id in by_id if work_id not in selections]
                finished = not missing
                result = {"ok": finished, "missing_work_ids": missing}
            else:
                result = {"ok": False, "error": f"unknown tool: {name}"}
            model_trace[-1].setdefault("tool_results", []).append({
                "tool_call_id": call_id,
                "name": name,
                "result": result,
            })
        context_metrics[-1]["tool_total_ms"] = round((perf_counter() - tool_started) * 1000, 2)
        if finished:
            break
    if not finished:
        missing = [work_id for work_id in by_id if work_id not in selections]
        raise RuntimeError(f"smeta model did not finish native tool conversation; missing work_ids: {missing}")
    return {
        "selections": selections,
        "browse_trace": browse_trace,
        "query_trace": query_trace,
        "model_trace": model_trace,
        "valid_model_rows": len(selections),
        "agent_trace": {
            "mode": "model_direct_rag_tool_loop",
            "turns": len(model_trace),
            "finished": finished,
            "context_metrics": context_metrics,
            "search_calls": sum(1 for item in query_trace if item.get("phase") == "native_agent_search"),
            "search_cache_entries": len(search_cache),
            "opened_cards_total": sum(len(values) for values in opened.values()),
            "opened_norm_codes": {work_id: list(values) for work_id, values in opened.items()},
        },
    }


def _resource_plan_batch(batch: list[dict[str, Any]], complete: Complete) -> tuple[list[dict[str, Any]], str]:
    messages = [
        {
            "role": "system",
            "content": (
                "Ты инженер-сметчик. Для каждой уже выбранной нормы отдельно проверь труд, машины "
                "и материалы против исходной операции. В cost_driver_preview уже посчитаны итоговые "
                "чел.-ч и маш.-ч на исходный объем: явно оцени их технологическую правдоподобность. "
                "Верни ровно одну строку на каждый work_id: "
                "{\"rows\":[{\"work_id\":\"...\",\"resource_review_status\":"
                "\"keep_all_confirmed|actions_confirmed|unresolved\",\"resource_review_reason\":\"...\","
                "\"labor_review_status\":\"confirmed|not_present|unresolved|rejected\","
                "\"labor_review_reason\":\"...\",\"machine_review_status\":"
                "\"confirmed|not_present|unresolved|rejected\",\"machine_review_reason\":\"...\","
                "\"material_review_status\":\"confirmed|not_present|unresolved|rejected\","
                "\"material_review_reason\":\"...\","
                "\"resource_actions\":[...]}]}. keep_all_confirmed означает, что все ресурсы нормы "
                "осознанно применимы; actions_confirmed требует хотя бы одно действие; unresolved используй, "
                "если состав подтвердить нельзя. Для аналога пустой resource_actions не означает согласие. "
                "Допустимые action: add, replace, exclude, reuse. Каждый action использует только поля: "
                "action; target_resource_code или точный target_resource_name для replace/exclude/reuse; "
                "resource_name и unit для add/replace; quantity_basis строго explicit|target_norm|source_work; "
                "quantity только при explicit; price_query для add/replace; reason. Для replace обычно используй "
                "quantity_basis=target_norm. Для add материала из исходной ВОР используй quantity_basis=source_work. "
                "Для присутствующего компонента not_present запрещен. Если трудоемкость или машины аналога "
                "не защищаемы, поставь unresolved/rejected: неподтвержденный компонент не войдет даже в "
                "известную стоимость. Не пиши свободный текст вместо enum и не используй поля "
                "resource/material. Не меняй работы, нормы и исходные количества."
            ),
        },
        {"role": "user", "content": json.dumps({"work_rows": batch}, ensure_ascii=False, default=str)},
    ]
    raw = complete(messages) or ""
    payload = _json_object(raw)
    rows = [item for item in (payload.get("rows") or []) if isinstance(item, dict)]
    return rows, raw


def _choose_price_candidate(action: dict[str, Any], candidates: list[dict[str, Any]], complete: Complete) -> tuple[dict[str, Any], str]:
    compact = [
        {
            "code": item.get("code"),
            "name": item.get("name"),
            "unit": item.get("unit"),
            "price_current_eff": item.get("price_current_eff"),
            "region": item.get("region"),
            "quarter": item.get("quarter"),
            "match": item.get("match"),
        }
        for item in candidates
    ]
    messages = [
        {
            "role": "system",
            "content": (
                "Выбери точную строку ФГИС ЦС для уже принятого проектного материала. Код не выбирает. "
                "Верни только JSON {\"resource_code\":\"код только из candidates или пусто\","
                "\"needs_kac\":true|false,\"reason\":\"...\"}. Выбирай код только если совпадают назначение, "
                "существенные характеристики и единица/пересчитываемая кратность. Иначе resource_code пуст, "
                "needs_kac=true."
            ),
        },
        {"role": "user", "content": json.dumps({"material": action, "candidates": compact}, ensure_ascii=False)},
    ]
    raw = complete(messages) or ""
    return _json_object(raw), raw


def _choose_price_candidates_batch(
    items: list[dict[str, Any]],
    complete: Complete,
) -> tuple[dict[str, dict[str, Any]], str]:
    """Let the model resolve many independent FGIS menus in one paid call."""
    compact_items = []
    for item in items:
        compact_items.append({
            "choice_id": item["choice_id"],
            "material": item["action"],
            "candidates": [
                {
                    "code": candidate.get("code"),
                    "name": candidate.get("name"),
                    "unit": candidate.get("unit"),
                    "price_current_eff": candidate.get("price_current_eff"),
                    "region": candidate.get("region"),
                    "quarter": candidate.get("quarter"),
                    "match": candidate.get("match"),
                }
                for candidate in item["candidates"]
            ],
        })
    messages = [
        {
            "role": "system",
            "content": (
                "Независимо выбери строку ФГИС ЦС для каждого уже принятого проектного материала. "
                "Код не выбирает. Верни только JSON {\"rows\":[{\"choice_id\":\"...\","
                "\"resource_code\":\"код только из candidates или пусто\",\"needs_kac\":true|false,"
                "\"reason\":\"...\"}]}. Верни ровно одну строку на каждый choice_id. Выбирай код "
                "только при совпадении назначения, существенных характеристик и единицы или доказуемой "
                "кратности; иначе оставь код пустым и needs_kac=true."
            ),
        },
        {"role": "user", "content": json.dumps({"items": compact_items}, ensure_ascii=False, default=str)},
    ]
    raw = complete(messages) or ""
    payload = _json_object(raw)
    rows = {
        str(item.get("choice_id") or ""): item
        for item in (payload.get("rows") or []) if isinstance(item, dict)
    }
    return rows, raw


def _apply_model_resource_plan(
    visible_rows: list[dict[str, Any]],
    complete: Complete,
    *,
    book: str | None,
    batch_size: int,
    vat_pct: float,
    progress: Progress | None = None,
) -> dict[str, Any]:
    by_id = {str(row.get("work_id") or ""): row for row in visible_rows}
    evidence: list[dict[str, Any]] = []
    for row in visible_rows:
        norm_code = str(row.get("norm_code") or "")
        if not norm_code:
            continue
        norm = gesn_service.get_norm(norm_code, strict_family=True) if norm_code else None
        validation: dict[str, Any] = {}
        try:
            validation = validate_binding(
                WorkItem(
                    work_id=str(row.get("work_id") or ""),
                    title=str(row.get("title") or ""),
                    quantity=float(row.get("quantity")) if row.get("quantity") is not None else None,
                    unit=str(row.get("unit") or ""),
                ),
                NormBinding(
                    work_id=str(row.get("work_id") or ""),
                    norm_code=norm_code,
                    selected_by="model",
                    selection_kind=str(row.get("selection_kind") or "exact"),
                    is_analog=str(row.get("selection_kind") or "") == "analog",
                    reason=str(row.get("norm_reason") or "выбор модели"),
                    analog_limitations=tuple(
                        str(value) for value in (row.get("analog_limitations") or ["требуется ресурсная проверка"])
                        if str(value).strip()
                    ) if str(row.get("selection_kind") or "") == "analog" else (),
                    applicability=str(row.get("applicability") or ("close_analog" if str(row.get("selection_kind") or "") == "analog" else "exact")),
                ),
            )
        except (TypeError, ValueError):
            validation = {}
        norm_quantity = float(validation.get("norm_quantity") or 0.0)
        resources = list((norm or {}).get("resources") or [])
        component_totals = {
            "labor_hours": round(sum(
                float(item.get("per_unit") or 0.0) * norm_quantity
                for item in resources if str(item.get("kind") or "") == "labor"
            ), 6),
            "machine_hours": round(sum(
                float(item.get("per_unit") or 0.0) * norm_quantity
                for item in resources if str(item.get("kind") or "") == "machine"
            ), 6),
            "machinist_hours": round(sum(
                float(item.get("per_unit") or 0.0) * norm_quantity
                for item in resources if str(item.get("kind") or "") == "machinist"
            ), 6),
            "material_rows": sum(1 for item in resources if str(item.get("kind") or "") == "material"),
            "norm_quantity": norm_quantity,
        }
        component_presence = {
            "labor": any(str(item.get("kind") or "") == "labor" for item in resources),
            "machine": any(str(item.get("kind") or "") in {"machine", "machinist"} for item in resources),
            "material": any(str(item.get("kind") or "") == "material" for item in resources),
        }
        evidence.append({
            "work_id": row.get("work_id"),
            "source": {
                "title": row.get("title"), "unit": row.get("unit"), "quantity": row.get("quantity"),
                "section": row.get("section"), "note": row.get("note"), "source_refs": row.get("source_refs"),
            },
            "selected_norm": {
                "code": norm_code,
                "name": (norm or {}).get("name"),
                "unit": (norm or {}).get("unit"),
                "work_steps": list((norm or {}).get("work_steps") or [])[:40],
                "resources": list((norm or {}).get("resources") or [])[:80],
            },
            "cost_driver_preview": component_totals,
            "component_presence": component_presence,
            "selected_decision": {
                "selection_kind": row.get("selection_kind"),
                "applicability": row.get("applicability"),
                "reason": row.get("norm_reason"),
                "analog_limitations": list(row.get("analog_limitations") or []),
                "technology_check": row.get("technology_check") or {},
            },
            "all_work_ids": list(by_id),
        })

    plan_rows: list[dict[str, Any]] = []
    model_trace: list[dict[str, Any]] = []
    for offset in range(0, len(evidence), max(1, batch_size)):
        if progress:
            progress({"phase": "resource_plan", "done": offset, "total": len(evidence)})
        model_started = perf_counter()
        selected, raw = _resource_plan_batch(evidence[offset : offset + max(1, batch_size)], complete)
        model_wait_ms = round((perf_counter() - model_started) * 1000, 2)
        plan_rows.extend(selected)
        model_trace.append({
            "work_ids": [item["work_id"] for item in evidence[offset : offset + max(1, batch_size)]],
            "model_wait_ms": model_wait_ms,
            "raw": raw,
        })

    price_path = fgis_price_service.resolve_pricebook_path(book, allow_scratch=bool(book))
    pricebook = fgis_price_service.get_pricebook(price_path) if price_path else None
    price_trace: list[dict[str, Any]] = []
    price_model_trace: list[dict[str, Any]] = []
    pending_price_choices: list[dict[str, Any]] = []
    accepted: dict[str, dict[str, Any]] = {
        str(item["work_id"]): {
            "work_id": str(item["work_id"]),
            "resource_bindings": [],
            "resource_review_status": "unresolved",
            "resource_review_reason": "модель не вернула подтверждение ресурсного состава",
            "labor_review_status": "unresolved",
            "labor_review_reason": "модель не вернула решение по труду",
            "machine_review_status": "unresolved",
            "machine_review_reason": "модель не вернула решение по машинам",
            "material_review_status": "unresolved",
            "material_review_reason": "модель не вернула решение по материалам",
        }
        for item in evidence
    }
    decided: set[str] = set()
    for decision in plan_rows:
        work_id = str(decision.get("work_id") or "")
        if work_id not in accepted or work_id in decided:
            continue
        decided.add(work_id)
        requested_status = str(decision.get("resource_review_status") or "unresolved").strip()
        review_reason = str(decision.get("resource_review_reason") or "").strip()
        row_out: dict[str, Any] = {
            "work_id": work_id,
            "resource_bindings": [],
            "resource_review_status": requested_status,
            "resource_review_reason": review_reason,
        }
        evidence_row = next(item for item in evidence if str(item.get("work_id") or "") == work_id)
        presence = dict(evidence_row.get("component_presence") or {})
        component_statuses: dict[str, str] = {}
        component_reasons: dict[str, str] = {}
        allowed_component_statuses = {"confirmed", "not_present", "unresolved", "rejected"}
        for component in ("labor", "machine", "material"):
            status_key = f"{component}_review_status"
            reason_key = f"{component}_review_reason"
            component_status = str(decision.get(status_key) or "unresolved").strip()
            component_reason = str(decision.get(reason_key) or "").strip()
            if component_status not in allowed_component_statuses:
                component_status, component_reason = "unresolved", "неизвестный статус компонента"
            if component_status == "not_present" and bool(presence.get(component)):
                component_status, component_reason = "unresolved", "компонент присутствует в норме"
            if component_status in {"confirmed", "rejected"} and not component_reason:
                component_status, component_reason = "unresolved", "решение по компоненту не обосновано"
            component_statuses[component] = component_status
            component_reasons[component] = component_reason
            row_out[status_key] = component_status
            row_out[reason_key] = component_reason
        for action in decision.get("resource_actions") or []:
            if not isinstance(action, dict):
                continue
            binding_data = {
                "work_id": work_id,
                "action": str(action.get("action") or ""),
                "selected_by": "model",
                "resource_name": str(action.get("resource_name") or ""),
                "resource_code": "",
                "unit": str(action.get("unit") or ""),
                "quantity": action.get("quantity"),
                "quantity_basis": str(action.get("quantity_basis") or "explicit"),
                "target_resource_code": str(action.get("target_resource_code") or ""),
                "target_resource_name": str(action.get("target_resource_name") or ""),
                "reason": str(action.get("reason") or ""),
                "source_refs": tuple(str(ref) for ref in (by_id[work_id].get("source_refs") or ()) if str(ref)),
            }
            if binding_data["action"] in {"add", "replace"}:
                query = str(action.get("price_query") or binding_data["resource_name"]).strip()
                if query.casefold().strip(" .:;,-") in {"нет", "не требуется", "none", "n/a", "na"}:
                    price_trace.append({
                        "work_id": work_id,
                        "query": query,
                        "candidates": [],
                        "status": "price_lookup_skipped_by_model",
                    })
                    try:
                        binding = ResourceBinding(**binding_data)
                    except (TypeError, ValueError):
                        continue
                    row_out["resource_bindings"].append(asdict(binding))
                    continue
                candidates = pricebook.browse(query, limit=12) if pricebook and query else []
                if progress:
                    progress({"phase": "price_binding", "work_id": work_id, "query": query})
            try:
                binding = ResourceBinding(**binding_data)
            except (TypeError, ValueError):
                continue
            binding_out = asdict(binding)
            row_out["resource_bindings"].append(binding_out)
            if binding_data["action"] in {"add", "replace"} and query.casefold().strip(" .:;,-") not in {"нет", "не требуется", "none", "n/a", "na"}:
                pending_price_choices.append({
                    "choice_id": f"price-{len(pending_price_choices) + 1}",
                    "work_id": work_id,
                    "query": query,
                    "action": action,
                    "candidates": candidates,
                    "binding": binding_out,
                })
        if requested_status == "actions_confirmed" and not row_out["resource_bindings"]:
            row_out["resource_review_status"] = "unresolved"
            row_out["resource_review_reason"] = review_reason or "actions_confirmed без валидных действий"
        elif requested_status == "keep_all_confirmed" and row_out["resource_bindings"]:
            row_out["resource_review_status"] = "unresolved"
            row_out["resource_review_reason"] = review_reason or "keep_all_confirmed содержит действия"
        elif requested_status not in {"keep_all_confirmed", "actions_confirmed", "unresolved"}:
            row_out["resource_review_status"] = "unresolved"
            row_out["resource_review_reason"] = review_reason or "неизвестный статус проверки ресурсов"
        elif requested_status != "unresolved" and not review_reason:
            row_out["resource_review_status"] = "unresolved"
            row_out["resource_review_reason"] = "подтверждение ресурсов не обосновано"
        if any(status not in {"confirmed", "not_present"} for status in component_statuses.values()):
            row_out["resource_review_status"] = "unresolved"
            unresolved = [
                f"{name}: {component_statuses[name]}"
                for name in ("labor", "machine", "material")
                if component_statuses[name] not in {"confirmed", "not_present"}
            ]
            row_out["resource_review_reason"] = review_reason or "; ".join(unresolved)
        accepted[work_id] = row_out

    for offset in range(0, len(pending_price_choices), 20):
        batch = pending_price_choices[offset : offset + 20]
        model_started = perf_counter()
        choices, raw = _choose_price_candidates_batch(batch, complete)
        price_model_trace.append({
            "choice_ids": [item["choice_id"] for item in batch],
            "model_wait_ms": round((perf_counter() - model_started) * 1000, 2),
            "raw": raw,
        })
        for item in batch:
            choice = choices.get(item["choice_id"]) or {}
            candidates = item["candidates"]
            allowed = {str(candidate.get("code") or "") for candidate in candidates}
            selected_code = str(choice.get("resource_code") or "")
            binding_out = item["binding"]
            item_trace: dict[str, Any] = {
                "work_id": item["work_id"], "query": item["query"], "candidates": candidates,
                "model_choice": choice, "choice_id": item["choice_id"],
            }
            if selected_code in allowed and selected_code:
                binding_out["resource_code"] = selected_code
                binding_out["price_source_ref"] = f"ФГИС ЦС {Path(price_path).stem if price_path else ''}: {selected_code}"
            else:
                try:
                    kac = collect_quotes(
                        item["query"],
                        material=str(binding_out.get("resource_name") or ""),
                        unit=str(binding_out.get("unit") or ""),
                        vat_pct=vat_pct,
                    )
                except Exception as error:  # web failure is row-level, never a fake price
                    kac = {"status": "error", "error": f"{type(error).__name__}: {error}", "quotes": []}
                item_trace["kac"] = kac
                material_kac = ((kac.get("kac") or {}).get("materials") or [{}])[0]
                if kac.get("status") == "sufficient" and material_kac.get("chosen_price") is not None:
                    binding_out["explicit_price"] = float(material_kac["chosen_price"])
                    binding_out["price_source_ref"] = str(material_kac.get("chosen_source") or "КАЦ web")
            price_trace.append(item_trace)

    for work_id, decision in accepted.items():
        row = by_id[work_id]
        row.update(decision)
    return {
        "rows": visible_rows,
        "decisions": accepted,
        "model_trace": model_trace,
        "price_model_trace": price_model_trace,
        "price_trace": price_trace,
    }


def _review_dominant_positions(
    visible_rows: list[dict[str, Any]],
    preliminary_trace: dict[str, Any],
    browse_trace: dict[str, list[dict[str, Any]]],
    complete: Complete,
) -> dict[str, Any]:
    """One compact model audit of top cost drivers; code ranks money but never judges applicability."""
    positions = [
        position
        for section in (preliminary_trace.get("sections") or [])
        for position in (section.get("positions") or [])
        if str(position.get("work_id") or "")
    ]
    total = sum(float((position.get("summary") or {}).get("known_amount") or 0.0) for position in positions)
    ranked = sorted(
        positions,
        key=lambda item: float((item.get("summary") or {}).get("known_amount") or 0.0),
        reverse=True,
    )
    dominant = [
        item for index, item in enumerate(ranked)
        if index < 3 or (total > 0 and float((item.get("summary") or {}).get("known_amount") or 0.0) / total >= 0.15)
    ]
    if not dominant:
        return {"rows": visible_rows, "decisions": {}, "model_raw": "", "reviewed_work_ids": []}

    by_id = {str(row.get("work_id") or ""): row for row in visible_rows}
    registry = []
    for row in visible_rows:
        code = str(row.get("norm_code") or "")
        norm = gesn_service.get_norm(code, strict_family=True) if code else None
        registry.append({
            "work_id": row.get("work_id"),
            "source_title": row.get("title"),
            "selected_norm": code or None,
            "selected_work_steps": list((norm or {}).get("work_steps") or [])[:16],
            "covered_by_work_id": row.get("covered_by_work_id") or None,
        })

    review_rows = []
    for position in dominant:
        work_id = str(position.get("work_id") or "")
        row = by_id.get(work_id) or {}
        alternatives: list[dict[str, Any]] = []
        seen: set[str] = set()
        for search in browse_trace.get(work_id) or []:
            for card in search.get("candidates") or []:
                code = str(card.get("norm_code") or "")
                if not code or code in seen or code == str(row.get("norm_code") or ""):
                    continue
                seen.add(code)
                alternatives.append({
                    "norm_code": code,
                    "title": card.get("title"),
                    "measure_unit": card.get("measure_unit"),
                    "work_steps": list(card.get("work_steps") or [])[:6],
                    "resource_preview": list(card.get("resource_preview") or [])[:8],
                })
        summary = position.get("summary") or {}
        review_rows.append({
            "work_id": work_id,
            "source": {"title": row.get("title"), "quantity": row.get("quantity"), "unit": row.get("unit")},
            "selected_norm": {
                "code": row.get("norm_code"), "selection_kind": row.get("selection_kind"),
                "reason": row.get("norm_reason"), "limitations": row.get("analog_limitations") or [],
            },
            "amount": float(summary.get("known_amount") or 0.0),
            "share": round(float(summary.get("known_amount") or 0.0) / total, 6) if total else 0.0,
            "labor_hours": summary.get("labor_qty"),
            "machinist_hours": summary.get("machinist_qty"),
            "component_review": summary.get("component_review") or {},
            "flags": summary.get("flags") or [],
            "alternative_candidates": alternatives[:8],
        })

    messages = [
        {
            "role": "system",
            "content": (
                "Ты повторно проверяешь только доминирующие позиции предварительной ЛСР. Они входят в top-3 "
                "или дают не менее 15% известной суммы. Для каждой позиции заново сравни исходную операцию, "
                "технологию выбранной нормы, итоговый труд, машины, материалы, альтернативы и operation_registry "
                "на двойной учет. Верни JSON {\"rows\":[{\"work_id\":\"...\",\"status\":"
                "\"confirmed|unresolved\",\"reason\":\"...\",\"labor_review_status\":"
                "\"confirmed|unresolved|rejected\",\"machine_review_status\":"
                "\"confirmed|not_present|unresolved|rejected\",\"material_review_status\":"
                "\"confirmed|not_present|unresolved|rejected\"}]}. confirmed допустим только если позиция "
                "профессионально защищаема после проверки влияния. При сомнении или двойном учете — unresolved; "
                "код уберет неподтвержденные компоненты из известной суммы. Не выбирай норму кодом и не меняй объем."
            ),
        },
        {"role": "user", "content": json.dumps({"dominant_rows": review_rows, "operation_registry": registry}, ensure_ascii=False, default=str)},
    ]
    model_started = perf_counter()
    raw = complete(messages) or ""
    model_wait_ms = round((perf_counter() - model_started) * 1000, 2)
    payload = _json_object(raw)
    returned = {
        str(item.get("work_id") or ""): item
        for item in (payload.get("rows") or []) if isinstance(item, dict)
    }
    decisions: dict[str, dict[str, Any]] = {}
    for position in dominant:
        work_id = str(position.get("work_id") or "")
        row = by_id[work_id]
        decision = returned.get(work_id) or {}
        status = str(decision.get("status") or "unresolved")
        reason = str(decision.get("reason") or "доминирующая позиция не получила повторного подтверждения")
        prior_confirmed = all(
            str(row.get(f"{component}_review_status") or "") in {"confirmed", "not_present"}
            for component in ("labor", "machine", "material")
        )
        if status == "confirmed" and prior_confirmed and reason.strip():
            row["dominant_review_status"] = "confirmed"
            row["dominant_review_reason"] = reason
        else:
            row["dominant_review_status"] = "unresolved"
            row["dominant_review_reason"] = reason
            row["resource_review_status"] = "unresolved"
            row["resource_review_reason"] = reason
            for component in ("labor", "machine", "material"):
                returned_status = str(decision.get(f"{component}_review_status") or "unresolved")
                if returned_status not in {"confirmed", "not_present"}:
                    row[f"{component}_review_status"] = returned_status if returned_status in {"unresolved", "rejected"} else "unresolved"
                    row[f"{component}_review_reason"] = reason
            if all(
                str(row.get(f"{component}_review_status") or "") in {"confirmed", "not_present"}
                for component in ("labor", "machine", "material")
            ):
                for component in ("labor", "machine", "material"):
                    if str(row.get(f"{component}_review_status") or "") == "confirmed":
                        row[f"{component}_review_status"] = "unresolved"
                        row[f"{component}_review_reason"] = reason
        decisions[work_id] = {
            "status": row.get("dominant_review_status"),
            "reason": row.get("dominant_review_reason"),
        }
    return {
        "rows": visible_rows,
        "decisions": decisions,
        "model_raw": raw,
        "model_wait_ms": model_wait_ms,
        "reviewed_work_ids": [str(item.get("work_id") or "") for item in dominant],
    }


def _finalize_document_workflow(
    *,
    path: str | Path,
    intake: dict[str, Any],
    work_rows: list[dict[str, Any]],
    selections: dict[str, dict[str, Any]],
    browse_trace: dict[str, list[dict[str, Any]]],
    query_trace: list[dict[str, Any]],
    model_trace: list[dict[str, Any]],
    complete: Complete,
    batch_size: int,
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
            "covered_by_work_id": selection.get("covered_by_work_id") or "",
            "coverage_reason": selection.get("coverage_reason") or "",
        })
    # First useful result follows the last known-working 4/10 contract: once
    # the model has selected norms, calculate and render immediately. Resource
    # and dominant reviews are refinement stages and must not gate the first LSR.
    resource_plan = {
        "rows": visible_rows,
        "decisions": {},
        "model_trace": [],
        "price_model_trace": [],
        "price_trace": [],
        "status": "deferred_after_first_lsr",
    }
    dominant_review = {
        "rows": visible_rows,
        "decisions": {},
        "model_raw": "",
        "model_wait_ms": 0.0,
        "reviewed_work_ids": [],
        "status": "deferred_after_first_lsr",
    }
    trace = calculate_visible_rows_revision(
        visible_rows,
        selected_by="model",
        created_by="model",
        change_note=f"VOR PDF workflow: {display_source_name}",
        revision_root=revision_root,
        book=book,
        title=f"Локальный сметный расчет — {display_stem}",
    )
    xlsx_path = ""
    if out_xlsx:
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
    result = {
        "schema": "smeta_document_workflow_v2",
        "intake": intake,
        "browse_trace": browse_trace,
        "query_trace": query_trace,
        "model_trace": model_trace,
        "agent_trace": agent_trace or {},
        "selections": selections,
        "resource_plan": resource_plan,
        "dominant_review": dominant_review,
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


def run_vor_pdf_workflow(
    path: str | Path,
    complete: Complete,
    *,
    exchange: Exchange,
    candidate_limit: int = 8,
    batch_size: int = 6,
    book: str | None = None,
    out_xlsx: str | Path | None = None,
    out_report: str | Path | None = None,
    revision_root: str | None = None,
    vat_pct: float = 22.0,
    progress: Progress | None = None,
    source_name: str | None = None,
    lsr_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the same generic workflow for any table-like VOR PDF using a caller-provided model."""
    intake = intake_vor_pdf(path)
    work_rows = [dict(item) for item in intake.get("work_items") or []]
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
        complete=complete,
        batch_size=batch_size,
        book=book,
        out_xlsx=out_xlsx,
        out_report=out_report,
        revision_root=revision_root,
        vat_pct=vat_pct,
        progress=progress,
        source_name=source_name,
        lsr_meta=lsr_meta,
    )
