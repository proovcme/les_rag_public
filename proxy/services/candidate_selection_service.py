"""Generic candidate shortlist/selection contract.

This layer ranks and explains already-found candidates. It does not create domain scope, invent
facts or replace the model's choice when the shortlist is ambiguous.
"""

from __future__ import annotations

from typing import Any

SCHEMA = "candidate_selection_v1"


DEFAULT_REASON_LABELS: dict[str, tuple[str, str]] = {
    "collection": ("источник соответствует запросу", "источник не соответствует запросу"),
    "unit": ("единица измерения совпадает", "единица измерения не совпадает"),
    "element": ("есть признаки нужного элемента", "есть признаки другого элемента"),
    "family": ("есть признаки семейства работ", "нет признаков семейства работ"),
    "action": ("совпало действие", "действие не совпало"),
    "forbidden": ("", "есть признаки специального/неподходящего кандидата"),
    "denied_subsection": ("", "подраздел/тип источника запрещён для этого запроса"),
}


def _num(value: Any) -> float:
    try:
        return float(str(value).replace(",", ".").replace(" ", ""))
    except (TypeError, ValueError):
        return 0.0


def candidate_reason_labels(
    candidate: dict[str, Any],
    *,
    reason_labels: dict[str, tuple[str, str]] | None = None,
) -> list[str]:
    """Translate score parts and applicability into human-readable reasons."""
    labels_map = {**DEFAULT_REASON_LABELS, **(reason_labels or {})}
    parts = candidate.get("score_parts") if isinstance(candidate.get("score_parts"), dict) else {}
    labels: list[str] = []
    applicability = str(candidate.get("applicability_status") or candidate.get("status") or "")
    if applicability == "accepted":
        labels.append("применимость подтверждена")
    elif applicability == "ambiguous":
        labels.append("применимость требует выбора модели")
    elif applicability == "rejected":
        labels.append("кандидат отклонён фильтром применимости")
    for key, raw_value in parts.items():
        value = _num(raw_value)
        if not value:
            continue
        positive, negative = labels_map.get(str(key), (f"{key}: положительный сигнал", f"{key}: отрицательный сигнал"))
        label = positive if value > 0 else negative
        if label and label not in labels:
            labels.append(label)
    return labels[:6]


def candidate_shortlist(
    candidates: list[dict[str, Any]],
    *,
    limit: int = 5,
    reason_labels: dict[str, tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Compact shortlist for model/operator review."""
    short: list[dict[str, Any]] = []
    for c in candidates[:limit]:
        short.append({
            "norm_code": c.get("norm_code") or c.get("code") or c.get("id") or "",
            "title": c.get("title") or c.get("name") or "",
            "measure_unit": c.get("measure_unit") or c.get("unit") or "",
            "score_total": c.get("score_total", 0),
            "score_parts": c.get("score_parts", {}),
            "applicability_status": c.get("applicability_status") or c.get("status") or "",
            "unit_compatible": c.get("unit_compatible", True),
            "reasons": candidate_reason_labels(c, reason_labels=reason_labels),
        })
    return short


def select_candidates(
    candidates: list[dict[str, Any]],
    *,
    clear_gap: float = 2.0,
    shortlist_limit: int = 5,
    reason_labels: dict[str, tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Return a reusable decision contract for an already-ranked candidate list."""
    if not candidates:
        return {
            "schema": SCHEMA,
            "status": "not_found",
            "action": "refine_search",
            "selected_code": "",
            "score_gap": None,
            "reason": "по запросу не найдено кандидатов",
            "shortlist": [],
        }
    top = candidates[0]
    second = candidates[1] if len(candidates) > 1 else None
    gap = None if second is None else round(_num(top.get("score_total")) - _num(second.get("score_total")), 2)
    top_status = str(top.get("applicability_status") or top.get("status") or "")
    top_ok = top_status == "accepted" and top.get("unit_compatible") is not False
    clear_lead = second is None or (gap is not None and gap >= clear_gap)
    if top_ok and clear_lead:
        status = "clear"
        action = "bind_top_candidate"
        selected = str(top.get("norm_code") or top.get("code") or top.get("id") or "")
        reason = (
            "лидер применим и заметно сильнее ближайшей альтернативы"
            if second else "единственный применимый кандидат"
        )
    elif top_ok:
        status = "needs_model_choice"
        action = "ask_model_to_choose_or_request_input"
        selected = ""
        reason = "есть применимый лидер, но отрыв от альтернатив мал"
    else:
        status = "needs_model_choice"
        action = "ask_model_to_choose_or_request_input"
        selected = ""
        reason = "верхний кандидат не прошёл применимость или единицу измерения"
    return {
        "schema": SCHEMA,
        "status": status,
        "action": action,
        "selected_code": selected,
        "score_gap": gap,
        "reason": reason,
        "top_reasons": candidate_reason_labels(top, reason_labels=reason_labels),
        "shortlist": candidate_shortlist(
            candidates,
            limit=shortlist_limit,
            reason_labels=reason_labels,
        ),
    }
