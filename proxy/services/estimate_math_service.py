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
        return float(str(v).replace("\xa0", "").replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


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
