"""Mechanical normalization of norm resources before review and calculation.

This module never decides whether a resource is professionally applicable.  It
only removes alternative representations of the same labor total that can be
present together in imported FSNB tables.
"""

from __future__ import annotations

from typing import Any


def _text(value: Any) -> str:
    return " ".join(str(value or "").casefold().replace("ё", "е").split())


def _code(resource: dict[str, Any]) -> str:
    return _text(resource.get("code") or resource.get("resource_code")).replace(" ", "")


def normalize_norm_resources(resources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Choose one labor representation while preserving every non-labor row.

    Imported norms may expose simultaneously:
    - an average-grade row (``1-100-*``);
    - a textual aggregate row (``Затраты труда рабочих, всего``);
    - a grade breakdown (``2-100-*``).

    These are alternative representations, not additive work.  Prefer the
    grade breakdown when present, otherwise the average-grade row, otherwise
    retain the source rows unchanged.  No semantic resource is invented or
    removed by name outside this representation contract.
    """
    copied = [dict(item) for item in resources]
    labor = [item for item in copied if _text(item.get("kind")) == "labor"]
    detailed = [item for item in labor if _code(item).startswith("2-100-")]
    average = [item for item in labor if _code(item).startswith("1-100-")]
    if detailed:
        selected_ids = {id(item) for item in detailed}
    elif average:
        selected_ids = {id(item) for item in average}
    else:
        return copied
    return [
        item
        for item in copied
        if _text(item.get("kind")) != "labor" or id(item) in selected_ids
    ]
