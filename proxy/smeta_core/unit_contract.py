"""Formal smeta measure conversion shared by adapters.

This module only parses a normative measure and checks physical convertibility.
It never ranks or selects a norm.
"""

from __future__ import annotations

import re
from typing import Any

from proxy.smeta_core.norm_validator import units_compatible


def norm_measure(value: Any) -> tuple[float, str]:
    """Return ``(measure_factor, base_unit)`` for values such as ``100 m2``."""
    text = str(value or "").strip()
    match = re.match(r"\s*(\d+(?:[.,]\d+)?)?\s*(.+?)\s*$", text)
    if not match:
        return 1.0, text
    factor = float((match.group(1) or "1").replace(",", "."))
    return factor, str(match.group(2) or "").strip()


def measure_units_compatible(source_unit: str, norm_measure_value: str) -> bool:
    """Formal unit compatibility for a physical quantity and full norm measure."""
    return units_compatible(source_unit, norm_measure_value)
