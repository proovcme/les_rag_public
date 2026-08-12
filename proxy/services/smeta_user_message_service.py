"""Human-facing messages for completed smeta workflows.

The formatter translates an already calculated result into ordinary Russian. It
does not choose norms, change decisions, recalculate money or expose machine
contract field names.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def format_rub(value: Any) -> str:
    amount = float(value)
    return f"{amount:,.2f}".replace(",", " ").replace(".", ",") + " руб."


def _positions(count: int) -> str:
    value = abs(int(count)) % 100
    last = value % 10
    if 11 <= value <= 14:
        word = "позиций"
    elif last == 1:
        word = "позиция"
    elif 2 <= last <= 4:
        word = "позиции"
    else:
        word = "позиций"
    return f"{int(count)} {word}"


def _covered(count: int, *, lead: str) -> str:
    verb = "учтена" if int(count) == 1 else "учтены"
    return f"{lead}{_positions(count)} {verb} в составе других работ"


def build_mapping_fingerprint(
    *,
    work_rows: list[dict[str, Any]] | None,
    selections: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compact row→norm digest for comparing fresh document LSR runs."""
    rows = [row for row in (work_rows or []) if isinstance(row, dict)]
    selected = selections if isinstance(selections, dict) else {}
    entries: list[dict[str, str]] = []
    demotions: list[dict[str, str]] = []
    for row in rows:
        work_id = str(row.get("work_id") or "").strip()
        if not work_id:
            continue
        selection = selected.get(work_id) if isinstance(selected.get(work_id), dict) else {}
        code = str((selection or {}).get("norm_code") or "").strip() or "MISSING"
        entries.append({"work_id": work_id, "norm_code": code})
        for blocker in (selection or {}).get("precalculation_blockers") or []:
            if not isinstance(blocker, dict):
                continue
            if str(blocker.get("code") or "") != "repair_collection_without_intent":
                continue
            demotions.append({
                "work_id": work_id,
                "rejected_norm_code": str(blocker.get("rejected_norm_code") or ""),
            })
    payload = json.dumps(entries, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    bound = sum(1 for item in entries if item["norm_code"] != "MISSING")
    return {
        "schema": "les.smeta_mapping_fingerprint.v1",
        "digest": digest,
        "entries": entries,
        "bound_rows": bound,
        "open_rows": max(0, len(entries) - bound),
        "repair_collection_demotions": demotions,
    }


def coverage_gate(summary: dict[str, Any] | None) -> dict[str, Any]:
    """Structural coverage signal — does not judge which norms should be chosen."""
    data = summary if isinstance(summary, dict) else {}
    total_rows = int(data.get("input_rows") or 0)
    bound_rows = int(data.get("bound_rows") or 0)
    covered_rows = int(data.get("covered_rows") or 0)
    open_rows = int(data.get("open_rows", data.get("unbound_rows")) or 0)
    if total_rows <= 0:
        return {
            "low_coverage": False,
            "total_rows": 0,
            "bound_rows": 0,
            "covered_rows": 0,
            "open_rows": 0,
            "bound_ratio": 1.0,
            "open_ratio": 0.0,
        }
    closed = bound_rows + covered_rows
    bound_ratio = closed / total_rows
    open_ratio = open_rows / total_rows
    # Low coverage: many open rows or less than ~70% closed — money is not the estimate.
    low_coverage = open_rows > 0 and (open_ratio >= 0.30 or bound_ratio < 0.70)
    return {
        "low_coverage": low_coverage,
        "total_rows": total_rows,
        "bound_rows": bound_rows,
        "covered_rows": covered_rows,
        "open_rows": open_rows,
        "bound_ratio": bound_ratio,
        "open_ratio": open_ratio,
    }


def format_mapping_stability_note(fingerprint: dict[str, Any] | None) -> str:
    """Human note about draft instability / repair demotions (no machine jargon)."""
    if not isinstance(fingerprint, dict) or not fingerprint.get("digest"):
        return ""
    parts: list[str] = []
    demotions = fingerprint.get("repair_collection_demotions") or []
    if isinstance(demotions, list) and demotions:
        parts.append(
            f"Ремонтные сборники без признака ремонта в тексте ведомости не приняты "
            f"({_positions(len(demotions))}) — эти строки оставлены без нормы, другая норма "
            f"кодом не подставлялась."
        )
    open_rows = int(fingerprint.get("open_rows") or 0)
    is_partial = open_rows > 0 or bool(demotions)
    if is_partial:
        parts.append(
            f"Повторный прогон той же ведомости может выбрать другие нормы на незакрытых "
            f"строках. Код текущих привязок: {fingerprint['digest']}. "
            f"Для стабильной суммы проверьте черновик и зафиксируйте ревизию."
        )
    elif str(fingerprint.get("digest") or ""):
        parts.append(
            f"Код текущих привязок: {fingerprint['digest']}. "
            f"До фиксации ревизии повторный прогон всё ещё может изменить выбор норм."
        )
    return (" " + " ".join(parts)) if parts else ""


def format_document_lsr_message(
    source_name: str,
    summary: dict[str, Any],
    *,
    fingerprint: dict[str, Any] | None = None,
) -> str:
    total_rows = int(summary.get("input_rows") or 0)
    priced_rows = int(summary.get("bound_rows") or 0)
    covered_rows = int(summary.get("covered_rows") or 0)
    open_rows = int(summary.get("open_rows", summary.get("unbound_rows")) or 0)
    gate = coverage_gate(summary)
    amount_is_partial = open_rows > 0 or (
        "full_amount" in summary and summary.get("full_amount") is None
    )
    total_without_vat = summary.get("total_without_vat", summary.get("total"))
    total_with_vat = summary.get("total_with_vat")
    is_draft = (
        str(summary.get("result_status") or "") == "priced_draft"
        or str(summary.get("approval_status") or "") == "auto_draft"
    )

    opening = "Проверяемый черновик сметы собрал" if is_draft else "Смету собрал"
    parts = [f"{opening} с нуля по ведомости «{source_name}». "]
    if open_rows:
        coverage = f"Из {_positions(total_rows)} рассчитаны {priced_rows}"
        if covered_rows:
            coverage += ", " + _covered(covered_rows, lead="ещё ")
        coverage += f", {_positions(open_rows)} оставлены незакрытыми. "
        parts.append(coverage)
        if gate["low_coverage"]:
            parts.append(
                "Покрытие низкое: сумма ниже — только по привязанным строкам, "
                "это не итог сметы по всей ведомости. "
            )
    elif total_rows and covered_rows:
        parts.append(
            f"Все {_positions(total_rows)} учтены: {priced_rows} рассчитаны, "
            f"{_covered(covered_rows, lead='')}. "
        )
    elif total_rows:
        parts.append(f"Все {_positions(total_rows)} рассчитаны. ")

    if total_without_vat is not None and total_with_vat is not None:
        if gate["low_coverage"]:
            label = (
                f"Сумма только по {priced_rows} из {total_rows} привязанных строк"
            )
        else:
            label = (
                "Стоимость рассчитанного черновика" if is_draft and not amount_is_partial
                else "Стоимость рассчитанной части" if amount_is_partial
                else "Стоимость сметы"
            )
        parts.append(
            f"{label} составляет {format_rub(total_without_vat)} без НДС "
            f"и {format_rub(total_with_vat)} с НДС. "
        )
    elif total_without_vat is not None:
        if gate["low_coverage"]:
            label = (
                f"Сумма только по {priced_rows} из {total_rows} привязанных строк"
            )
        else:
            label = (
                "Стоимость рассчитанного черновика" if is_draft and not amount_is_partial
                else "Стоимость рассчитанной части" if amount_is_partial
                else "Стоимость сметы"
            )
        parts.append(f"{label} без НДС составляет {format_rub(total_without_vat)}. ")

    parts.append(
        "Формульная ЛСР приложена в Excel, замечания и позиции, требующие уточнения, "
        "вынесены на лист «Проверка»."
    )
    if is_draft:
        parts.append(" До пользовательской проверки и фиксации mapping-ревизии документ не является финальным.")
    parts.append(format_mapping_stability_note(fingerprint))
    return "".join(parts)
