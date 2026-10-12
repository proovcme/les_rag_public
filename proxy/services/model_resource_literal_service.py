"""Reversible literal transport for the known typed norm-resource schema."""
from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence


RESOURCE_TABLE_PREFIX = "literal_resources_v1="
_REQUIRED = frozenset(("kind", "code", "name", "unit", "per_unit", "resource_slot"))
_OPTIONAL = frozenset(("source_ref", "price"))
_TEXT = frozenset(("kind", "code", "name", "unit", "source_ref"))


def _known_columns(rows: Sequence[Mapping]) -> list[str] | None:
    if not isinstance(rows, (list, tuple)) or not rows or not all(isinstance(row, Mapping) for row in rows):
        return None
    keys = set(rows[0])
    if not _REQUIRED <= keys <= _REQUIRED | _OPTIONAL:
        return None
    for slot, row in enumerate(rows, 1):
        if set(row) != keys or type(row["resource_slot"]) is not int or row["resource_slot"] != slot:
            return None
        if any(type(row[key]) is not str for key in keys & _TEXT):
            return None
        for key in keys & {"per_unit", "price"}:
            value = row[key]
            if value is not None and (type(value) not in (int, float)
                                      or isinstance(value, float) and not math.isfinite(value)):
                return None
    return sorted(keys)


def resource_jsonl(rows: Sequence[Mapping]) -> str:
    """The immutable legacy representation, including its fallback conversions."""
    return "\n".join(json.dumps(dict(row), ensure_ascii=False, sort_keys=True, default=str) for row in rows)


def render_resource_literals(rows: Sequence[Mapping]) -> str:
    """Only factor repeated field names when the complete schema is exactly known."""
    legacy = resource_jsonl(rows)
    columns = _known_columns(rows)
    if columns is None:
        return legacy
    compact = resource_table_literal(rows, columns)
    # A one-row card or unusually short literals may cost more with a header.
    return compact if len(compact) < len(legacy) and len(compact.encode("utf-8")) < len(legacy.encode("utf-8")) else legacy


def resource_table_literal(rows: Sequence[Mapping], columns: Sequence[str]) -> str:
    """Encode already-proven rows, including an existing literal source-catalog view."""
    return RESOURCE_TABLE_PREFIX + json.dumps({"columns": list(columns),
        "records": [[row[key] for key in columns] for row in rows]},
        ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate literal resource field")
        result[key] = value
    return result


def restore_resource_table(body: str, expected_rows: Sequence[Mapping], *,
                           source_catalog: Mapping[str, str] | None = None) -> list[dict] | None:
    """Prove the entire shown table against the original rows, including JSON types."""
    # JSON literals may contain U+2028/U+2029; only producer LF is a boundary.
    lines = [line[len(RESOURCE_TABLE_PREFIX):] for line in body.split("\n")
             if line.startswith(RESOURCE_TABLE_PREFIX)]
    columns = _known_columns(expected_rows)
    if len(lines) != 1 or columns is None:
        return None
    try:
        table = json.loads(lines[0], object_pairs_hook=_unique_object)
    except (ValueError, TypeError):
        return None
    if not isinstance(table, dict) or set(table) != {"columns", "records"} or table["columns"] != columns:
        return None
    records = table["records"]
    if not isinstance(records, list) or len(records) != len(expected_rows):
        return None
    if any(not isinstance(record, list) or len(record) != len(columns) for record in records):
        return None
    rows = [dict(zip(columns, record, strict=True)) for record in records]
    for row in rows:
        source = row.get("source_ref")
        if isinstance(source, dict):
            if set(source) != {"shared_source_pointer"} or not isinstance(source["shared_source_pointer"], str):
                return None
            literal = (source_catalog or {}).get(source["shared_source_pointer"])
            if not isinstance(literal, str):
                return None
            row["source_ref"] = literal
    if _known_columns(rows) != columns or resource_jsonl(rows) != resource_jsonl(expected_rows):
        return None
    # The full decoded list proved every type/value; keep source field order too.
    return [dict(row) for row in expected_rows]
