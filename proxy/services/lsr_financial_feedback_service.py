"""Exact calculator observations for an explicitly requested document review.

No search, calculation or professional selection happens here. An observation
belongs to one issued revision, price basis, source scope and accepted operation.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Callable, Mapping, Sequence

from proxy.services.lsr_source_coverage_service import inferred_row_role, operation_identity


_SCOPE_FIELDS = ("source_sha256", "source_frame_contract_sha256", "dataset_ids")


def _basis(price_basis: Mapping[str, Any] | None) -> dict[str, Any]:
    basis = price_basis or {}
    return {"pricebook": basis.get("actual_book") or basis.get("pricebook") or "",
            "region": basis.get("actual_region") or basis.get("region") or "",
            "quarter": basis.get("actual_quarter") or basis.get("quarter") or "",
            "pricebook_sha256": basis.get("pricebook_sha256") or ""}


def _scope(identity: Mapping[str, Any]) -> dict[str, Any]:
    return {key: sorted(identity.get(key) or ()) if key == "dataset_ids" else identity.get(key) or ""
            for key in _SCOPE_FIELDS}


def _row_sha(row: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(dict(row), ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def incomplete_financial_operations(
    rows: Sequence[Mapping[str, Any]], projection: Sequence[Mapping[str, Any]], *,
    canonicalize_locator: Callable[[Any], Any] = str,
) -> list[tuple[Mapping[str, Any], Mapping[str, Any]]]:
    """Join the revision's incomplete projection to one exact accepted identity."""
    result = []
    for item in projection:
        if not isinstance(item, Mapping) or item.get("position_calculated") is not False:
            continue
        if item.get("row_role") in {"header", "unresolved"}:
            continue
        reasons = item.get("open_reasons")
        uncomputed_components = isinstance(reasons, (list, tuple)) and "norm_components_not_calculated" in reasons
        if item.get("status") == "covered" and not uncomputed_components:
            continue
        identity = str(item.get("operation_id") or "")
        if not identity:
            continue
        matches = [row for row in rows if isinstance(row, Mapping)
                   and identity in {operation_identity(row), str(row.get("operation_id") or "")} - {""}
                   and canonicalize_locator(item.get("locator")) == canonicalize_locator(row.get("source_row"))
                   and inferred_row_role(row) not in {"header", "unresolved"}]
        if len(matches) == 1 and not any(old[0] is matches[0] for old in result):
            result.append((matches[0], item))
    return result


def financial_feedback_snapshot(
    rows: Sequence[Mapping[str, Any]], projection: Sequence[Mapping[str, Any]], *,
    revision_id: str, price_basis: Mapping[str, Any] | None, identity: Mapping[str, Any],
) -> dict[str, Any]:
    """Save exact open projection records, stamped by their accepted row revisions."""
    if not revision_id:
        return {}
    records = []
    for row, item in incomplete_financial_operations(rows, projection):
        revision = row.get("revision")
        if not row.get("operation_id") or isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            continue
        records.append({"operation_id": row["operation_id"], "revision": revision,
                        "row_sha256": _row_sha(row), "projection": copy.deepcopy(dict(item))})
    return {"schema": "les.lsr-financial-feedback.v1", "revision_id": revision_id,
            "source_scope": _scope(identity), "price_basis": _basis(price_basis), "records": records}


def financial_feedback_for_rows(
    snapshot: Mapping[str, Any] | None, rows: Sequence[Mapping[str, Any]], *,
    price_basis: Mapping[str, Any] | None, identity: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Replay only an unchanged baseline in the same source and price scope."""
    if (not isinstance(snapshot, Mapping) or snapshot.get("schema") != "les.lsr-financial-feedback.v1"
            or not snapshot.get("revision_id") or snapshot.get("source_scope") != _scope(identity)
            or snapshot.get("price_basis") != _basis(price_basis)):
        return []
    # A named book without a pinned content hash cannot prove that a later
    # same-named book is the one used by the issued calculation.
    basis = _basis(price_basis)
    if basis["pricebook"] and not basis["pricebook_sha256"]:
        return []
    facts = []
    for record in snapshot.get("records") or ():
        if not isinstance(record, Mapping) or not isinstance(record.get("projection"), Mapping):
            continue
        matching = [row for row in rows if row.get("operation_id") == record.get("operation_id")
                    and row.get("revision") == record.get("revision") and _row_sha(row) == record.get("row_sha256")]
        if len(matching) == 1:
            facts.append({"operation_id": record["operation_id"], "source_row": matching[0].get("source_row"),
                          "accepted_revision": record["revision"], "document_revision_id": snapshot["revision_id"],
                          "projection": copy.deepcopy(dict(record["projection"]))})
    return facts
