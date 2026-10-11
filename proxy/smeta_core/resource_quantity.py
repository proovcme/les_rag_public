"""Source resource quantities: explicit zero is known; absent/invalid is not."""

from math import isfinite
from typing import Any


def resource_consumption(value: Any) -> float | None:
    """Read a finite nonnegative consumption without inventing a numeric fallback."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace("\xa0", "").replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) and number >= 0 else None
