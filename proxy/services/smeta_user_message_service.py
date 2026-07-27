"""Human-facing messages for completed smeta workflows.

The formatter translates an already calculated result into ordinary Russian. It
does not choose norms, change decisions, recalculate money or expose machine
contract field names.
"""

from __future__ import annotations

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


def format_document_lsr_message(source_name: str, summary: dict[str, Any]) -> str:
    total_rows = int(summary.get("input_rows") or 0)
    priced_rows = int(summary.get("bound_rows") or 0)
    covered_rows = int(summary.get("covered_rows") or 0)
    open_rows = int(summary.get("open_rows", summary.get("unbound_rows")) or 0)
    amount_is_partial = open_rows > 0 or (
        "full_amount" in summary and summary.get("full_amount") is None
    )
    total_without_vat = summary.get("total_without_vat", summary.get("total"))
    total_with_vat = summary.get("total_with_vat")

    parts = [f"Смету собрал с нуля по ведомости «{source_name}». "]
    if open_rows:
        coverage = f"Из {_positions(total_rows)} рассчитаны {priced_rows}"
        if covered_rows:
            coverage += ", " + _covered(covered_rows, lead="ещё ")
        coverage += f", {_positions(open_rows)} оставлены незакрытыми. "
        parts.append(coverage)
    elif total_rows and covered_rows:
        parts.append(
            f"Все {_positions(total_rows)} учтены: {priced_rows} рассчитаны, "
            f"{_covered(covered_rows, lead='')}. "
        )
    elif total_rows:
        parts.append(f"Все {_positions(total_rows)} рассчитаны. ")

    if total_without_vat is not None and total_with_vat is not None:
        label = "Стоимость рассчитанной части" if amount_is_partial else "Стоимость сметы"
        parts.append(
            f"{label} составляет {format_rub(total_without_vat)} без НДС "
            f"и {format_rub(total_with_vat)} с НДС. "
        )
    elif total_without_vat is not None:
        label = "Стоимость рассчитанной части" if amount_is_partial else "Стоимость сметы"
        parts.append(f"{label} без НДС составляет {format_rub(total_without_vat)}. ")

    parts.append(
        "Формульная ЛСР приложена в Excel, замечания и позиции, требующие уточнения, "
        "вынесены на лист «Проверка»."
    )
    return "".join(parts)
