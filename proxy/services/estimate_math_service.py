"""Small shared math helpers for estimate harnesses.

This module deliberately contains only generic arithmetic utilities. It does not
carry object compositions or user-facing estimating policy.
"""

from __future__ import annotations

import math
import re
from typing import Any

_FORMULA_NS = {"sqrt": math.sqrt, "min": min, "max": max, "round": round, "abs": abs}
_FORMULA_RE = re.compile(r"^[\sA-Za-z0-9_.+\-*/()]+$")
_FORMULA_IDENT_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")


def _f(v: Any) -> float:
    try:
        parsed = parse_ru_number(v)
        return float(parsed) if parsed is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def parse_ru_number(value: Any) -> float | None:
    """Parse Russian-formatted numbers like ``664 711,12`` or ``72,05258``.

    The helper is intentionally generic: it only normalizes a scalar number and
    does not infer what that number means for an estimate.
    """
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("\xa0", " ").replace("\u202f", " ")
    text = re.sub(r"[^\d,.\-+ ]+", "", text)
    text = text.strip()
    if not text:
        return None
    text = text.replace(" ", "")
    if "," in text and "." in text:
        # In Russian source data comma is decimal; dots are usually thousands.
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def convert_unit(value: float, from_unit: str, to_unit: str) -> float:
    """Convert a numeric value between common quantity units used by smeta audit."""
    src = str(from_unit or "").strip().lower()
    dst = str(to_unit or "").strip().lower()
    if src == dst:
        return float(value)
    if src in {"кг", "kg"} and dst in {"т", "t"}:
        return float(value) / 1000.0
    if src in {"т", "t"} and dst in {"кг", "kg"}:
        return float(value) * 1000.0
    raise ValueError(f"Нельзя перевести {from_unit!r} в {to_unit!r}")


def _round_audit(value: float, unit: str | None = None) -> float:
    digits = 5 if str(unit or "").strip().lower() in {"т", "t"} else 2
    return round(float(value), digits)


def _normalized_quantity(item: dict[str, Any], result_unit: str) -> dict[str, Any]:
    raw_value = parse_ru_number(item.get("value"))
    if raw_value is None:
        raise ValueError(f"Не удалось разобрать число для {item.get('label') or item!r}")
    unit = str(item.get("unit") or result_unit)
    value = convert_unit(raw_value, unit, result_unit) if unit != result_unit else raw_value
    return {
        "label": str(item.get("label") or ""),
        "value": _round_audit(value, result_unit),
        "unit": result_unit,
    }


def quantity_sum_audit(
    *,
    name: str,
    inputs: list[dict[str, Any]],
    unit: str,
    compared_to: list[dict[str, Any]] | None = None,
    partial_groups: list[dict[str, Any]] | None = None,
    tolerance: float = 0.001,
) -> dict[str, Any]:
    """Return deterministic trace for a quantity sum and source comparisons.

    The result is a calculator/provenance object. It deliberately does not
    decide which conflicting quantity is contractual and does not select works
    or norms.
    """
    normalized = [_normalized_quantity(item, unit) for item in inputs]
    total = sum(float(item["value"]) for item in normalized)
    result = {"value": _round_audit(total, unit), "unit": unit}
    alt_units: list[dict[str, Any]] = []
    if str(unit).lower() in {"кг", "kg"}:
        alt_units.append({"value": _round_audit(convert_unit(total, unit, "т"), "т"), "unit": "т"})
    elif str(unit).lower() in {"т", "t"}:
        alt_units.append({"value": _round_audit(convert_unit(total, unit, "кг"), "кг"), "unit": "кг"})

    comparisons: list[dict[str, Any]] = []
    has_conflict = False
    for item in compared_to or []:
        normalized_cmp = _normalized_quantity(item, unit)
        delta = total - float(normalized_cmp["value"])
        comparisons.append({
            "label": normalized_cmp["label"],
            "value": normalized_cmp["value"],
            "unit": unit,
            "delta": _round_audit(delta, unit),
        })
        if abs(delta) > tolerance:
            has_conflict = True

    by_label = {item["label"]: float(item["value"]) for item in normalized}
    partial_matches: list[dict[str, Any]] = []
    for group in partial_groups or []:
        labels = [str(label) for label in group.get("input_labels") or []]
        partial_total = sum(by_label[label] for label in labels if label in by_label)
        match_label = ""
        for cmp_item in comparisons:
            if abs(partial_total - float(cmp_item["value"])) <= tolerance:
                match_label = str(cmp_item["label"])
                break
        partial_matches.append({
            "label": str(group.get("label") or ""),
            "value": _round_audit(partial_total, unit),
            "unit": unit,
            "matches": match_label,
        })

    return {
        "name": str(name),
        "operation": "sum",
        "inputs": normalized,
        "result": result,
        "result_alt_units": alt_units,
        "compared_to": comparisons,
        "partial_matches": partial_matches,
        "status": "conflict" if has_conflict else "ok",
    }


def percentage_audit(*, name: str, base: Any, percent: Any, unit: str = "шт") -> dict[str, Any]:
    """Return a trace for a simple percentage calculation."""
    base_value = parse_ru_number(base)
    percent_value = parse_ru_number(percent)
    if base_value is None or percent_value is None:
        raise ValueError("Не удалось разобрать base/percent для процентного расчёта")
    result = base_value * percent_value / 100.0
    return {
        "name": str(name),
        "operation": "percent",
        "inputs": [
            {"label": "base", "value": _round_audit(base_value, unit), "unit": unit},
            {"label": "percent", "value": _round_audit(percent_value, "%"), "unit": "%"},
        ],
        "result": {"value": _round_audit(result, unit), "unit": unit},
        "status": "ok",
    }


def formula_quantity_audit(
    *,
    name: str,
    factors: list[dict[str, Any]],
    operation: str = "multiply",
    unit: str = "шт",
) -> dict[str, Any]:
    """Trace a simple model-provided formula such as joints * bolts * percent."""
    values: list[dict[str, Any]] = []
    result = 1.0 if operation == "multiply" else 0.0
    for item in factors:
        raw = parse_ru_number(item.get("value"))
        if raw is None:
            raise ValueError(f"Не удалось разобрать множитель {item.get('label') or item!r}")
        values.append({"label": str(item.get("label") or ""), "value": _round_audit(raw), "unit": item.get("unit") or ""})
        if operation == "multiply":
            result *= raw
        elif operation == "sum":
            result += raw
        else:
            raise ValueError(f"Неподдерживаемая операция: {operation!r}")
    return {
        "name": str(name),
        "operation": operation,
        "inputs": values,
        "result": {"value": _round_audit(result, unit), "unit": unit},
        "status": "ok",
    }


def quantity_audit_report(audits: list[dict[str, Any]]) -> dict[str, Any]:
    """Wrap audit entries in the shared payload shape used by tests and callers."""
    return {"audits": audits}


def _geometry(area: float, floors: int, constants: dict[str, Any] | None = None) -> dict[str, float]:
    """Derive coarse geometry namespace from area/floor count plus optional constants."""
    S = max(_f(area), 0.0)
    N = max(int(floors or 1), 1)
    S1 = S / N if N else S
    a = math.sqrt(S1) if S1 > 0 else 0.0
    P = 4.0 * a
    ns: dict[str, float] = {"S": S, "N": float(N), "S1": S1, "a": a, "P": P}
    for k, v in (constants or {}).get("geometry", {}).items():
        ns[k] = _f(v)
    return ns


def _eval_formula(formula: str, ns: dict[str, float]) -> float:
    """Evaluate a validated arithmetic formula in the provided numeric namespace."""
    expr = str(formula or "").strip()
    if not expr or not _FORMULA_RE.match(expr):
        raise ValueError(f"Недопустимая формула объёма: {formula!r}")
    env = {**_FORMULA_NS, **ns}
    return round(float(eval(expr, {"__builtins__": {}}, env)), 6)  # noqa: S307


def _formula_values(formula: str, ns: dict[str, float]) -> dict[str, float]:
    values: dict[str, float] = {}
    for token in _FORMULA_IDENT_RE.findall(str(formula or "")):
        if token in ns:
            values[token] = round(_f(ns[token]), 6)
    return values
