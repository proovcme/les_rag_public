"""Fail-closed NR/SP catalog lookup from Orders 812/pr and 774/pr."""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any


DEFAULT_CATALOG = Path("config/domain/nr_sp_catalog.json")
LEGACY_PATH = Path("config/domain/nr_sp.yaml")


def _code_norm(value: Any) -> str:
    return str(value or "").strip().casefold().replace(" ", "").replace(":", "")


def _collection_key(code: Any) -> str:
    match = re.match(r"^(гэснмр|гэснм|гэснп|гэснр|гэсн)(\d{1,2})(?:-|$)", _code_norm(code))
    if not match:
        return ""
    family_raw, number = match.groups()
    family = {
        "гэсн": "ГЭСН",
        "гэснм": "ГЭСНм",
        "гэснмр": "ГЭСНмр",
        "гэснп": "ГЭСНп",
        "гэснр": "ГЭСНр",
    }[family_raw]
    return f"{family}:{int(number):02d}"


@lru_cache(maxsize=4)
def _load(path: str | None = None) -> dict[str, Any]:
    target = Path(path) if path else DEFAULT_CATALOG
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def candidates(*, code: str, path: str | None = None) -> list[dict[str, Any]]:
    collection = _collection_key(code)
    if not collection:
        return []
    return [
        dict(rule)
        for rule in (_load(path).get("rules") or [])
        if collection in (rule.get("collections") or [])
    ]


def resolve(
    name: str = "",
    *,
    code: str | None = None,
    rule_id: str | None = None,
    path: str | None = None,
) -> dict[str, Any]:
    """Resolve only an exact explicit rule or a single unambiguous collection rule."""
    del name  # title matching must not silently choose a legal rate row
    options = candidates(code=str(code or ""), path=path)
    if rule_id:
        selected = next((rule for rule in options if rule.get("rule_id") == rule_id), None)
        if selected is None:
            return {
                "nr_pct": None,
                "sp_pct": None,
                "status": "rejected",
                "default": True,
                "reason": "nr_sp_rule_id is not valid for norm collection",
                "candidates": options,
            }
        return {**selected, "status": "resolved_explicit", "default": False}
    if len(options) == 1:
        return {**options[0], "status": "resolved_unique", "default": False}
    return {
        "nr_pct": None,
        "sp_pct": None,
        "label": "нужен явный выбор НР/СП" if options else "норматив НР/СП не найден",
        "basis": "",
        "status": "ambiguous" if options else "unresolved",
        "default": True,
        "candidates": options,
    }


def machinist_rate(*, path: str | None = None) -> float:
    del path
    return 0.0
