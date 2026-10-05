"""Read candidates from the task's chosen price book without binding a resource."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from proxy.services.fgis_price_service import PriceBookSourceChanged


@dataclass(frozen=True)
class PriceBookEvidenceSource:
    book: Any
    source_sha256: str
    source_name: str
    source_byte_size: int


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _scope_text(value: str) -> str:
    return "".join(char for char in value.casefold() if char.isalnum())


def _period(value: str) -> str:
    token = re.fullmatch(r"([1-4]):(20\d{2})", value.strip())
    if token:
        return f"{token[2]}:q{token[1]}"
    match = re.search(r"([1-4])\s*(?:квартал|kv|q)\s*(20\d{2})", value.casefold())
    return f"{match[2]}:q{match[1]}" if match else _scope_text(value)


def _known_price(value: Any) -> bool:
    if value in (None, "") or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _provider(book: str):
    from proxy.services import fgis_price_service

    path = fgis_price_service.resolve_pricebook_path(book, explicit_only=True)
    if not path:
        return None
    loaded = fgis_price_service.get_pricebook(path)
    return PriceBookEvidenceSource(loaded, getattr(loaded, "source_sha256", ""),
                                   getattr(loaded, "source_name", ""), getattr(loaded, "source_byte_size", -1))


def _current_quote(record: Mapping[str, Any]) -> tuple[float | None, str]:
    """A base price or any other number in the body is not a current quote."""
    if record.get("price_conflict"):
        return None, "conflict"
    if _known_price(record.get("price_current")) and float(record["price_current"]) >= 0:
        return round(float(record["price_current"]), 2), "published_current_price"
    if (record.get("price_current") in (None, "")
            and _known_price(record.get("price_base")) and float(record["price_base"]) >= 0
            and _known_price(record.get("index")) and float(record["index"]) > 0):
        value = float(record["price_base"]) * float(record["index"])
        if math.isfinite(value):
            return round(value, 2), "indexed_base_price"
    return None, "unresolved"


def read_pricebook_evidence(
    tool: str,
    args: Mapping[str, Any],
    *,
    price_basis: Mapping[str, Any],
    pricebook_provider: Callable[[str], Any] | None = None,
    limit: int = 6,
) -> dict[str, Any]:
    """Return exact book facts; neither a candidate nor its price is a decision."""

    payload: dict[str, Any] = {
        "schema": "les_tool_result_v1",
        "tool": tool,
        "operation": "typed_pricebook_read",
        "inputs": [dict(args)],
        "status": "missing",
        "result": {"hits": [], "count": 0},
        "sources": [],
        "missing": [],
        "warnings": [],
        "trace": {"scope_source": "stored_task_price_basis", "resource_selection": "model_required"},
        "decision_required_from_model": True,
    }

    def fail(message: str, *, conflict: bool = False) -> dict[str, Any]:
        payload["status"] = "conflict" if conflict else "missing"
        payload["missing"] = [message]
        return payload

    def bound_value(field: str, aliases: tuple[str, ...]) -> tuple[str, str]:
        values = []
        for alias in aliases:
            value = price_basis.get(alias)
            if value is None or value == "":
                continue
            if not isinstance(value, str):
                return "", f"stored-task {alias} must be a string"
            if value.strip():
                values.append(value.strip())
        normalize = _period if field == "quarter" else str.casefold if field == "pricebook" else _scope_text
        if len({normalize(value) for value in values}) > 1:
            return "", f"stored-task {field} aliases conflict"
        return (values[0] if values else ""), ""

    bound = {}
    for field, aliases in (("pricebook", ("pricebook", "actual_book", "pricebook_id")),
                           ("region", ("region", "actual_region", "requested_region")),
                           ("quarter", ("quarter", "actual_quarter", "requested_quarter"))):
        value, error = bound_value(field, aliases)
        if error:
            return fail(error, conflict="conflict" in error)
        bound[field] = value
    book_name, region, quarter = bound["pricebook"], bound["region"], bound["quarter"]
    if not book_name:
        return fail("explicit stored-task pricebook is required")
    for field, bound in (("pricebook", book_name), ("region", region), ("quarter", quarter)):
        if field not in args:
            continue
        requested = _text(args[field])
        if not requested:
            return fail(f"{field} must be a nonempty string")
        equal = (_period(requested) == _period(bound) if field == "quarter" else
                 requested.casefold() == bound.casefold() if field == "pricebook" else
                 _scope_text(requested) == _scope_text(bound))
        if not bound or not equal:
            return fail(f"{field} differs from stored-task price basis", conflict=True)
    selector = "q" if tool == "search_pricebook_resources" else "code"
    value = _text(args.get(selector))
    if not value:
        return fail(f"{selector} must be a nonempty string")
    try:
        source = (pricebook_provider or _provider)(book_name)
    except PriceBookSourceChanged as error:
        return fail(str(error), conflict=True)
    except OSError:
        return fail(f"chosen pricebook source is unavailable: {book_name}")
    if source is None:
        return fail(f"chosen pricebook is unavailable: {book_name}")
    if (not isinstance(source, PriceBookEvidenceSource) or not isinstance(source.source_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", source.source_sha256)
            or not source.source_name or not isinstance(source.source_byte_size, int)
            or source.source_byte_size < 0):
        return fail("chosen pricebook source identity is unavailable")
    expected_sha = _text(price_basis.get("pricebook_sha256"))
    if price_basis.get("pricebook_sha256") and not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
        return fail("stored-task pricebook_sha256 must be a SHA-256 string")
    if expected_sha and expected_sha != source.source_sha256:
        return fail("chosen pricebook bytes differ from stored-task source hash", conflict=True)
    book = source.book
    actual_region = _text(getattr(book, "region", ""))
    actual_quarter = _text(getattr(book, "quarter", ""))
    for field, expected, actual in (("region", region, actual_region), ("quarter", quarter, actual_quarter)):
        if not expected:
            continue
        equal = _period(expected) == _period(actual) if field == "quarter" else _scope_text(expected) == _scope_text(actual)
        if not actual or not equal:
            return fail(f"chosen pricebook {field} does not match stored task", conflict=True)
    if tool == "search_pricebook_resources":
        rows = list(book.browse(value, limit=limit))
    else:
        row = book.lookup(value)
        if isinstance(row, Mapping) and row.get("price_conflict"):
            payload["trace"]["price_conflict"] = dict(row["price_conflict"])
            return fail("exact resource has conflicting records in the chosen pricebook", conflict=True)
        rows = [row] if isinstance(row, Mapping) else []
    hits = []
    for row in rows:
        if not isinstance(row, Mapping) or not _text(row.get("code")):
            continue
        record = dict(row)
        source_ref = f"fgis_pricebook:{book_name}@sha256:{source.source_sha256}#resource={record['code']}"
        current, resolution = _current_quote(record)
        quote = ({"confirmed_price": current, "price_unit": record.get("unit"),
                  "price_source": source_ref} if current is not None else None)
        evidence = {
            "schema": "les.pricebook-resource-evidence.v1",
            "pricebook": book_name,
            "region": actual_region,
            "quarter": actual_quarter,
            "source_ref": source_ref,
            "source_sha256": source.source_sha256,
            "source_name": source.source_name,
            "source_byte_size": source.source_byte_size,
            "resource": record,
            "price_evidence": quote,
            "price_resolution_method": resolution,
            "semantic_applicability": "model_decision_required",
        }
        content = json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str)
        meta = {
            "source_ref": source_ref,
            "source_sha256": source.source_sha256,
            "pricebook_sha256": source.source_sha256,
            "source_hash_kind": "file_sha256",
            "source_name": source.source_name,
            "source_byte_size": source.source_byte_size,
            "pricebook": book_name,
            "region": actual_region,
            "quarter": actual_quarter,
            "resource_code": record["code"],
            "title": record.get("name"),
            "measure_unit": record.get("unit"),
            "resource_evidence_complete": bool(record.get("code") and record.get("unit")),
            "price_available": current is not None,
            "price_evidence": quote,
            "price_resolution_method": resolution,
            "semantic_applicability": "model_decision_required",
            "minimum_evidence_body_chars": len(content),
            "global_evidence_id": "pricebook_" + hashlib.sha256(content.encode("utf-8")).hexdigest(),
        }
        hits.append({"content": content, "doc_name": "fgis_pricebook_resources.v1", "score": 1.0, "meta": meta})
    payload["status"] = "ok" if hits else "missing"
    payload["result"] = {"hits": hits, "count": len(hits), "pricebook": book_name, "resource_selection": "model_required"}
    payload["sources"] = [{"source_ref": hit["meta"]["source_ref"], "pricebook": book_name,
                           "source_sha256": source.source_sha256, "source_name": source.source_name} for hit in hits]
    payload["trace"].update({"pricebook": book_name, "region": actual_region, "quarter": actual_quarter,
                             "pricebook_sha256": source.source_sha256})
    if not hits:
        payload["missing"] = [f"no resource matched in chosen pricebook: {value}"]
    return payload
