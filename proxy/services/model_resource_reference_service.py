"""Literal resource addresses within immutable, delivered norm cards."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping


def resource_slot_records(card: Mapping) -> list[dict]:
    """Keep original resource fields and add the one-based source position."""
    return [{**dict(row), "resource_slot": index}
            for index, row in enumerate(card.get("resources") or [], 1) if isinstance(row, Mapping)]


def parse_resource_reference(value) -> tuple[str, int] | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"(Q[1-9][0-9]*\.H[1-9][0-9]*)#resource=([1-9][0-9]{0,5})", value.strip(), re.I)
    return (match[1].upper(), int(match[2])) if match else None


def shown_resource_record(meta: Mapping, body: str, slot: int) -> dict | None:
    """Metadata alone is insufficient: the literal full record must be shown."""
    if meta.get("exact_card_read") is not True:
        return None
    rows = [row for row in meta.get("resources") or []
            if isinstance(row, Mapping) and row.get("resource_slot") == slot]
    if len(rows) != 1:
        return None
    row = dict(rows[0])
    if json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) not in body:
        return None
    row.pop("resource_slot", None)
    return row
