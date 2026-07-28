"""Quantity trace helpers for specification -> BOR workflows.

The service is a calculator/provenance layer.  It does not decide which works
belong in a BOR and does not choose norms; callers pass an already model-chosen
work title and source quantity relation.
"""

from __future__ import annotations

from typing import Any

from proxy.services.estimate_math_service import parse_ru_number as parse_ru_number


TRACE_STATUSES = (
    "direct_from_spec",
    "parent_child_calculated",
    "unit_conversion",
    "needs_geometry",
    "needs_estimator_decision",
    "source_conflict",
    "assumption",
    "missing_quantity",
)

_UNIT_ALIASES = {
    "м.п.": "м",
    "мп": "м",
    "пог.м": "м",
    "пог. м": "м",
    "погонный метр": "м",
    "kg": "кг",
    "t": "т",
    "тонна": "т",
    "тонн": "т",
    "штука": "шт",
    "штуки": "шт",
    "порт": "порт",
    "точка": "точка",
}


def normalize_unit(unit: Any) -> str:
    raw = str(unit or "").strip().lower()
    return _UNIT_ALIASES.get(raw, raw)


def convert_unit(value: float, from_unit: str, to_unit: str) -> float:
    """Convert common specification units into BOR units."""
    src = normalize_unit(from_unit)
    dst = normalize_unit(to_unit)
    if not dst or src == dst:
        return float(value)
    if src == "кг" and dst == "т":
        return float(value) / 1000.0
    if src == "т" and dst == "кг":
        return float(value) * 1000.0
    compatible_piece_units = {"шт", "порт", "точка", "комплект", "пара"}
    if src in compatible_piece_units and dst in compatible_piece_units:
        return float(value)
    raise ValueError(f"Нельзя перевести {from_unit!r} в {to_unit!r}")


def multiply_parent_child_quantity(parent_quantity: Any, qty_per_parent: Any) -> float | None:
    parent = parse_ru_number(parent_quantity)
    child = parse_ru_number(qty_per_parent)
    if parent is None or child is None:
        return None
    return parent * child


def _format_number(value: float | None) -> str:
    if value is None:
        return "?"
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:g}"


def _round_quantity(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)


def build_quantity_trace(
    *,
    work_title: str,
    source_item: str,
    source_quantity: Any = None,
    source_unit: str = "",
    bor_unit: str | None = None,
    parent_quantity: Any = None,
    qty_per_parent: Any = None,
    status: str | None = None,
    formula: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic quantity trace row for a model-selected BOR item."""
    src_unit = normalize_unit(source_unit)
    out_unit = normalize_unit(bor_unit if bor_unit is not None else source_unit)
    source_value = parse_ru_number(source_quantity)
    parent_value = parse_ru_number(parent_quantity)
    per_parent_value = parse_ru_number(qty_per_parent)

    calculated = None
    inferred_status = status
    if parent_value is not None and per_parent_value is not None:
        calculated = parent_value * per_parent_value
        inferred_status = inferred_status or "parent_child_calculated"
        formula = formula or (
            f"{_format_number(per_parent_value)} {src_unit} × "
            f"{_format_number(parent_value)} = {_format_number(calculated)} {src_unit}"
        )
    elif source_value is not None:
        calculated = source_value
        inferred_status = inferred_status or "direct_from_spec"
        formula = formula or f"{_format_number(source_value)} {src_unit}".strip()
    else:
        inferred_status = inferred_status or "missing_quantity"
        formula = formula or "missing_quantity"

    bor_quantity = None
    if calculated is not None:
        if out_unit and src_unit and out_unit != src_unit:
            bor_quantity = convert_unit(calculated, src_unit, out_unit)
            if inferred_status == "direct_from_spec":
                inferred_status = "unit_conversion"
        else:
            bor_quantity = calculated

    if inferred_status not in TRACE_STATUSES:
        inferred_status = "needs_estimator_decision"

    return {
        "work_title": str(work_title or ""),
        "source_item": str(source_item or ""),
        "source_quantity": source_value,
        "source_unit": src_unit,
        "parent_quantity": parent_value,
        "qty_per_parent": per_parent_value,
        "formula": formula,
        "bor_quantity": _round_quantity(bor_quantity),
        "bor_unit": out_unit,
        "status": inferred_status,
    }
