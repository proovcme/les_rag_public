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


def shown_resource_record(meta: Mapping, body: str, slot: int, *,
                          source_catalog: Mapping[str, str] | None = None) -> dict | None:
    """Metadata alone is insufficient: the literal full record must be shown."""
    from proxy.services.model_resource_literal_service import RESOURCE_TABLE_PREFIX, restore_resource_table

    if meta.get("exact_card_read") is not True:
        return None
    all_rows = meta.get("resources") or []
    table_shown = any(line.startswith(RESOURCE_TABLE_PREFIX) for line in body.split("\n"))
    if table_shown:
        all_rows = restore_resource_table(body, all_rows, source_catalog=source_catalog)
        if all_rows is None:
            return None
    rows = [row for row in all_rows
            if isinstance(row, Mapping) and row.get("resource_slot") == slot]
    if len(rows) != 1:
        return None
    row = dict(rows[0])
    if not table_shown and json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) not in body:
        return None
    row.pop("resource_slot", None)
    return row
