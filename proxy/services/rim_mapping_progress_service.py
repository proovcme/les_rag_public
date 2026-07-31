"""Read-only projection of durable Qwen norm-mapping progress."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from proxy.smeta_core.document_workflow import MAPPING_VALIDATION_CONTRACT_VERSION


def _human_project_source(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    path, separator, locator = raw.partition("#")
    filename = Path(path).name
    if re.fullmatch(r"[0-9a-fA-F]{32,}\.[A-Za-z0-9]+", filename):
        filename = ""
    fields: dict[str, str] = {}
    if separator:
        for item in locator.split(";"):
            key, equals, field_value = item.partition("=")
            if equals and key and field_value:
                fields[key.strip().casefold()] = field_value.strip()
    parts = [filename] if filename else []
    if fields.get("sheet"):
        parts.append(f"лист «{fields['sheet']}»")
    if fields.get("row"):
        parts.append(f"строка {fields['row']}")
    elif fields.get("page"):
        parts.append(f"страница {fields['page']}")
    return " · ".join(parts) or filename or raw


def _norm_source_display(card: dict[str, Any]) -> str:
    edition = str(card.get("edition") or "").strip()
    code = str(card.get("norm_code") or "").strip()
    source = str(card.get("source_ref") or "").strip()
    if edition and code:
        return f"{edition} · {code}"
    if code:
        return f"Структурированная ФСНБ · {code}"
    return source


def _compact_card(card: dict[str, Any], *, rank: int) -> dict[str, Any]:
    try:
        candidate_rank = int(card.get("rank") or rank)
    except (TypeError, ValueError):
        candidate_rank = rank
    return {
        "norm_key": str(card.get("norm_key") or ""),
        "norm_code": str(card.get("norm_code") or ""),
        "title": str(card.get("title") or ""),
        "unit": str(card.get("measure_unit") or card.get("unit") or ""),
        "base_type": str(card.get("base_type") or ""),
        "collection": str(card.get("collection") or ""),
        "rank": candidate_rank,
        "source_ref": str(card.get("source_ref") or ""),
        "source_display": _norm_source_display(card),
    }


def _unique_cards(raw: object) -> list[dict[str, Any]]:
    cards = raw if isinstance(raw, dict) else {}
    unique: dict[str, dict[str, Any]] = {}
    for key, value in cards.items():
        if not isinstance(value, dict):
            continue
        code = str(value.get("norm_code") or key or "").strip()
        if code:
            unique[code.casefold()] = {**value, "norm_code": code}
    return list(unique.values())


def _error_map(last_submit_result: object) -> dict[str, list[str]]:
    result = last_submit_result if isinstance(last_submit_result, dict) else {}
    mapped: dict[str, list[str]] = {}
    for error in result.get("errors") or []:
        if not isinstance(error, dict):
            continue
        work_id = str(error.get("work_id") or "").strip()
        if not work_id:
            continue
        details = [
            str(value).strip()
            for value in (error.get("details") or [])
            if str(value).strip()
        ]
        summary = str(error.get("error") or "").strip()
        mapped[work_id] = ([summary] if summary else []) + details
    return mapped


def _compact_decision(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    norm_code = str(value.get("norm_code") or "")
    covered_by = str(value.get("covered_by_work_id") or "")
    return {
        "decision": "bind" if norm_code else "covered_by" if covered_by else "unbound",
        "norm_code": norm_code,
        "covered_by_work_id": covered_by,
        "selection_kind": str(value.get("selection_kind") or ""),
        "applicability": str(value.get("applicability") or ""),
        "review_status": str(value.get("review_status") or ""),
        "reason": str(value.get("reason") or value.get("coverage_reason") or ""),
    }


def build_mapping_progress(
    vor_rows: list[dict[str, Any]],
    checkpoint: dict[str, Any] | None,
) -> dict[str, Any]:
    """Expose compact durable progress without changing checkpoint or decisions."""
    record = dict(checkpoint or {})
    payload = dict(record.get("payload") or {})
    resume = dict(payload.get("resume_state") or {})
    tool_state = dict(resume.get("tool_session") or {})
    accepted = dict(tool_state.get("accepted_rows") or {})
    candidates_by_work = dict(tool_state.get("candidates") or {})
    opened_by_work = dict(tool_state.get("opened") or {})
    selected_scopes = dict(tool_state.get("selected_collections") or {})
    catalog_trace = [
        item
        for item in (tool_state.get("catalog_trace") or [])
        if isinstance(item, dict)
    ]
    catalog_nodes = dict(tool_state.get("catalog_node_registry") or {})
    current_nodes = dict(tool_state.get("catalog_current_nodes") or {})
    model_trace = [
        item
        for item in (resume.get("model_trace") or [])
        if isinstance(item, dict)
    ]
    model_wait_by_turn = {
        int(item.get("turn") or 0): round(
            float(item.get("model_wait_ms") or 0.0) / 1000.0, 2
        )
        for item in model_trace
        if int(item.get("turn") or 0) > 0
    }
    model_profile_by_turn = {
        int(item.get("turn") or 0): dict(item.get("frame_profile") or {})
        for item in model_trace
        if int(item.get("turn") or 0) > 0
        and isinstance(item.get("frame_profile"), dict)
    }
    query_trace = [
        item
        for item in (tool_state.get("query_trace") or [])
        if isinstance(item, dict)
    ]
    validation_version = str(resume.get("validation_contract_version") or "")
    stale_contract = bool(
        accepted and validation_version != MAPPING_VALIDATION_CONTRACT_VERSION
    )
    errors = _error_map(resume.get("last_submit_result"))

    rows: list[dict[str, Any]] = []
    accepted_count = 0
    stale_count = 0
    accepted_route_count = 0
    rejected_route_count = 0
    for source in vor_rows:
        work_id = str(source.get("work_id") or "").strip()
        if not work_id:
            continue
        candidates = _unique_cards(candidates_by_work.get(work_id))
        opened = _unique_cards(opened_by_work.get(work_id))
        traces = [
            item
            for item in query_trace
            if str(item.get("work_id") or "") == work_id
        ]
        route_traces = [
            item
            for item in catalog_trace
            if str(item.get("work_id") or "") == work_id
            and str(item.get("phase") or "") == "catalog_route"
        ]
        accepted_routes = [
            item
            for item in route_traces
            if str(item.get("outcome") or "") == "accepted"
            and str(item.get("selected_node_id") or "")
        ]
        rejected_routes = [
            item
            for item in route_traces
            if str(item.get("outcome") or "") == "rejected"
        ]
        accepted_route_count += len(accepted_routes)
        rejected_route_count += len(rejected_routes)
        registry = (
            dict(catalog_nodes.get(work_id) or {})
            if isinstance(catalog_nodes.get(work_id), dict)
            else {}
        )
        selected_trace_by_node = {
            str(trace.get("selected_node_id") or ""): trace
            for trace in accepted_routes
        }
        active_node_ids: list[str] = []
        active_node_id = str(current_nodes.get(work_id) or "catalog:root")
        seen_node_ids: set[str] = set()
        while active_node_id and active_node_id != "catalog:root":
            if active_node_id in seen_node_ids:
                break
            seen_node_ids.add(active_node_id)
            node = (
                dict(registry.get(active_node_id) or {})
                if isinstance(registry.get(active_node_id), dict)
                else {}
            )
            if not node:
                break
            active_node_ids.append(active_node_id)
            active_node_id = str(node.get("parent_id") or "")
        active_node_ids.reverse()

        route_path = []
        for node_id in active_node_ids:
            node = dict(registry.get(node_id) or {})
            trace = selected_trace_by_node.get(node_id) or {}
            cipher = str(node.get("cipher") or "")
            title = str(
                node.get("title")
                or node.get("official_name")
                or node.get("official_heading")
                or ""
            )
            label = " · ".join(value for value in [cipher, title] if value)
            route_path.append({
                "node_id": node_id,
                "node_type": str(node.get("node_type") or ""),
                "cipher": cipher,
                "title": title,
                "label": label or node_id,
                "source_ref": str(node.get("source_ref") or ""),
                "trace_id": str(trace.get("trace_id") or ""),
                "model_wait_seconds": model_wait_by_turn.get(
                    int(trace.get("turn") or 0)
                ),
                "frame_profile": model_profile_by_turn.get(
                    int(trace.get("turn") or 0), {}
                ),
            })
        route_events = [
            {
                "trace_id": str(trace.get("trace_id") or ""),
                "outcome": str(trace.get("outcome") or ""),
                "decision": str(trace.get("decision") or ""),
                "current_node_id": str(trace.get("current_node_id") or ""),
                "selected_node_id": str(trace.get("selected_node_id") or ""),
                "model_wait_seconds": model_wait_by_turn.get(
                    int(trace.get("turn") or 0)
                ),
                "frame_profile": model_profile_by_turn.get(
                    int(trace.get("turn") or 0), {}
                ),
                "error": str(trace.get("error") or ""),
                "details": [
                    str(value)
                    for value in (trace.get("details") or [])
                    if str(value).strip()
                ][:3],
            }
            for trace in route_traces[-4:]
        ]
        scopes: list[dict[str, Any]] = []
        for trace in traces:
            filters = dict(trace.get("filters") or {})
            scope = {
                "base_types": list(filters.get("base_types") or []),
                "collections": list(filters.get("collections") or []),
                "table_codes": list(filters.get("table_codes") or []),
                "queries": list(trace.get("queries") or [])[:4],
            }
            if scope not in scopes:
                scopes.append(scope)
        if not scopes:
            for value in selected_scopes.get(work_id) or []:
                if isinstance(value, list) and len(value) == 2:
                    scopes.append(
                        {
                            "base_types": [str(value[0])],
                            "collections": [str(value[1])],
                            "table_codes": [],
                            "queries": [],
                        }
                    )

        decision = (
            dict(accepted.get(work_id) or {})
            if isinstance(accepted.get(work_id), dict)
            else None
        )
        blockers = list(errors.get(work_id) or [])
        if blockers:
            stage = "decision_rejected"
            stage_label = "Решение отклонено проверкой"
        elif decision is not None and stale_contract:
            stage = "needs_revalidation"
            stage_label = "Нужна повторная проверка"
            stale_count += 1
        elif decision is not None:
            stage = "decision_accepted"
            stage_label = "Решение Qwen сохранено"
            accepted_count += 1
        elif route_traces and str(route_traces[-1].get("outcome") or "") == "rejected":
            stage = "route_rejected"
            stage_label = "Переход отклонён; сохранён предыдущий путь"
        elif opened:
            stage = "cards_opened"
            stage_label = "Карточки прочитаны"
        elif candidates:
            stage = "candidates_found"
            stage_label = "Кандидаты найдены"
        elif traces:
            stage = "searched"
            stage_label = "Поиск выполнен"
        elif accepted_routes:
            stage = "route_progress"
            stage_label = "Маршрут по ФСНБ сохранён"
        elif scopes:
            stage = "scope_selected"
            stage_label = "Каталог выбран"
        else:
            stage = "not_started"
            stage_label = "Ещё не начато"

        source_ref = str(
            source.get("source_ref")
            or next(iter(source.get("source_refs") or []), "")
        )
        rows.append(
            {
                "work_id": work_id,
                "work_name": str(source.get("work_name") or source.get("title") or ""),
                "unit": str(source.get("unit") or ""),
                "quantity": source.get("quantity"),
                "source_ref": source_ref,
                "source_display": _human_project_source(source_ref),
                "stage": stage,
                "stage_label": stage_label,
                "search_count": len(traces),
                "scopes": scopes,
                "catalog_current_node_id": str(
                    current_nodes.get(work_id) or "catalog:root"
                ),
                "route_path": route_path,
                "route_display": " → ".join(
                    item["label"] for item in route_path
                ),
                "route_timing_display": " → ".join(
                    (
                        f"{item['label']} ({item['model_wait_seconds']:.2f} с)"
                        if item.get("model_wait_seconds") is not None
                        else item["label"]
                    )
                    for item in route_path
                ),
                "route_events": route_events,
                "candidate_count": len(candidates),
                "candidates": [
                    _compact_card(card, rank=index)
                    for index, card in enumerate(candidates[:4], 1)
                ],
                "opened_count": len(opened),
                "opened_cards": [
                    _compact_card(card, rank=index)
                    for index, card in enumerate(opened[:4], 1)
                ],
                "decision": _compact_decision(decision),
                "blockers": blockers[:8],
            }
        )

    stage_counts: dict[str, int] = {}
    for row in rows:
        stage = str(row["stage"])
        stage_counts[stage] = stage_counts.get(stage, 0) + 1
    completed = accepted_count
    return {
        "schema": "rim_mapping_progress_v1",
        "active": bool(checkpoint),
        "checkpoint_updated_at": str(record.get("updated_at") or ""),
        "base_revision_id": str(record.get("base_revision_id") or ""),
        "validation_contract_version": validation_version,
        "current_validation_contract_version": MAPPING_VALIDATION_CONTRACT_VERSION,
        "requires_revalidation": stale_contract,
        "summary": {
            "total_rows": len(rows),
            "completed_rows": completed,
            "remaining_rows": max(0, len(rows) - completed),
            "needs_revalidation_rows": stale_count,
            "accepted_route_transitions": accepted_route_count,
            "rejected_route_transitions": rejected_route_count,
            "stage_counts": stage_counts,
        },
        "rows": rows,
    }
