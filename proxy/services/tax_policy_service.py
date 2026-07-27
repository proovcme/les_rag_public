"""Versioned tax rate lookup from an explicit price-period year."""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any


DEFAULT_PATH = Path("config/domain/tax_policy.json")


@lru_cache(maxsize=2)
def _load(path: str = str(DEFAULT_PATH)) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def resolve_vat(period: str, *, path: str = str(DEFAULT_PATH)) -> dict[str, Any]:
    year_match = re.search(r"\b(20\d{2})\b", str(period or ""))
    if not year_match:
        return {"status": "unresolved", "vat_pct": None, "reason": "price period has no year"}
    year = int(year_match.group(1))
    applicable = [
        item for item in (_load(path).get("rates") or [])
        if str(item.get("tax") or "").upper() == "VAT"
        and int(str(item.get("effective_from") or "9999")[:4]) <= year
    ]
    if not applicable:
        return {"status": "unresolved", "vat_pct": None, "reason": f"no VAT policy for {year}"}
    selected = max(applicable, key=lambda item: str(item.get("effective_from") or ""))
    return {**selected, "status": "resolved", "period": period}
