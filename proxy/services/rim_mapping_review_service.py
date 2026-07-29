"""Deterministic structural review of a model/user RIM mapping draft.

This service flags conflicts and completeness gaps.  It never changes a
professional mapping decision.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from proxy.smeta_core.norm_validator import units_compatible


def review_mapping(
    work_rows: list[dict[str, Any]],
    mapping_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_work: dict[str, list[dict[str, Any]]] = {}
    for row in mapping_rows:
        by_work.setdefault(str(row.get("work_id") or ""), []).append(row)
    conflicts: list[dict[str, Any]] = []

    def add(code: str, severity: str, *, work_ids: list[str], reason: str) -> None:
        conflicts.append(
            {
                "conflict_id": uuid4().hex,
                "code": code,
                "severity": severity,
                "work_ids": work_ids,
                "reason": reason,
            }
        )

    for work in work_rows:
        work_id = str(work.get("work_id") or "")
        rows = by_work.get(work_id, [])
        chosen = [
            row
            for row in rows
            if str(row.get("selection_status") or "") in {"selected", "accepted"}
        ]
        if not chosen:
            add(
                "mapping_work_uncovered",
                "blocking",
                work_ids=[work_id],
                reason="Для строки ВОР нет выбранной нормы или подтверждённого coverage.",
            )
            continue
        if len(chosen) > 1:
            add(
                "mapping_multiple_selected",
                "blocking",
                work_ids=[work_id],
                reason="Для одной строки ВОР выбрано более одной нормы.",
            )
        for row in chosen:
            kind = str(row.get("selection_kind") or "direct")
            if kind == "unbound":
                add(
                    "norm_confirmation_required",
                    "blocking",
                    work_ids=[work_id],
                    reason=str(row.get("reason") or "Норма не подтверждена."),
                )
                continue
            if kind == "covered_by":
                continue
            if not bool(row.get("card_opened")):
                add(
                    "selected_norm_card_not_opened",
                    "blocking",
                    work_ids=[work_id],
                    reason="Выбранная норма не открыта из структурированной базы.",
                )
            work_unit = str(work.get("unit") or "")
            norm_unit = str(row.get("norm_unit") or "")
            if work_unit and norm_unit and not units_compatible(work_unit, norm_unit):
                add(
                    "mapping_unit_incompatible",
                    "blocking",
                    work_ids=[work_id],
                    reason=f"Единица ВОР {work_unit!r} несовместима с измерителем нормы {norm_unit!r}.",
                )

    selected_direct = [
        row
        for row in mapping_rows
        if str(row.get("selection_status") or "") in {"selected", "accepted"}
        and str(row.get("selection_kind") or "") not in {"covered_by", "unbound"}
    ]
    work_ids_by_norm: dict[str, list[str]] = {}
    for row in selected_direct:
        work_ids_by_norm.setdefault(str(row.get("norm_key") or ""), []).append(
            str(row.get("work_id") or "")
        )
    for norm_key, work_ids in work_ids_by_norm.items():
        unique = sorted(set(work_ids))
        if norm_key and len(unique) > 1:
            add(
                "possible_duplicate_norm_binding",
                "warning",
                work_ids=unique,
                reason=(
                    f"Одна норма {norm_key} выбрана для нескольких строк ВОР; "
                    "проверьте двойной учёт или комплексное покрытие."
                ),
            )
    return conflicts

