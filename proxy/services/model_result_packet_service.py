"""Admit only model decisions owned by the current mechanical packet.

This boundary never evaluates a norm, quantity, role or title. Unowned rows
remain complete, visible proposals instead of becoming new billable operations.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence


@dataclass
class PacketAdmission:
    accepted_rows: list[dict[str, Any]] = field(default_factory=list)
    unapplied_proposals: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)


def _locator_key(value: Any) -> str:
    text = str(value or "").strip()
    if text.upper().startswith("LOCATOR:"):
        text = text[len("LOCATOR:"):].strip()
    return text.casefold()


def _positive_revision(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None


_MODEL_REVISION_SNAPSHOT_SCHEMA = "les.model-revision-snapshot.v1"
_MODEL_REVISION_FIELDS = ("revision", "base_revision", "expected_revision")


def model_revision_snapshot_valid(
    snapshot: Any, *, packet_id: str | None = None,
    packet_locators: Sequence[str] | None = None,
) -> bool:
    """Validate an immutable application snapshot, never infer a missing base."""
    if (not isinstance(snapshot, Mapping)
            or set(snapshot) != {"schema", "packet_id", "packet_locators", "operations"}
            or snapshot.get("schema") != _MODEL_REVISION_SNAPSHOT_SCHEMA
            or not isinstance(snapshot.get("packet_id"), str)
            or not snapshot["packet_id"].strip()
            or not isinstance(snapshot.get("packet_locators"), list)
            or not isinstance(snapshot.get("operations"), list)):
        return False
    locators = snapshot["packet_locators"]
    if (not all(isinstance(value, str) and value.strip() for value in locators)
            or len(set(locators)) != len(locators)):
        return False
    if packet_id is not None and snapshot["packet_id"] != packet_id:
        return False
    if packet_locators is not None:
        if (not isinstance(packet_locators, Sequence) or isinstance(packet_locators, (str, bytes))
                or list(packet_locators) != locators):
            return False
    owned = {_locator_key(value) for value in locators}
    seen: set[str] = set()
    for operation in snapshot["operations"]:
        if (not isinstance(operation, Mapping)
                or set(operation) != {"operation_id", "source_row", "revision"}
                or not isinstance(operation.get("operation_id"), str)
                or not operation["operation_id"].strip()
                or not isinstance(operation.get("source_row"), str)
                or not operation["source_row"].strip()
                or _locator_key(operation["source_row"]) not in owned
                or type(operation.get("revision")) is not int or operation["revision"] <= 0):
            return False
        identity = operation["operation_id"].strip()
        if identity in seen:
            return False
        seen.add(identity)
    return True


def capture_model_revision_snapshot(
    prior_operations: Sequence[Mapping[str, Any]], *, packet_id: str,
    packet_locators: Sequence[str],
    canonicalize_locator: Callable[[Any], Any] | None = None,
) -> dict[str, Any]:
    """Capture only the exact durable identities offered for this packet.

    No ID means no committed update address. Known operations outside the
    packet do not gain an update target through an accepted-work index. A
    consistent duplicate identity contributes one mechanical base; inconsistent
    duplicate addresses/revisions fail closed without consulting subject fields.
    """
    if not isinstance(packet_locators, Sequence) or isinstance(packet_locators, (str, bytes)):
        raise ValueError("MODEL_REVISION_SNAPSHOT_INVALID")
    snapshot: dict[str, Any] = {
        "schema": _MODEL_REVISION_SNAPSHOT_SCHEMA,
        "packet_id": packet_id,
        "packet_locators": copy.deepcopy(list(packet_locators)),
        "operations": [],
    }
    if not model_revision_snapshot_valid(snapshot):
        raise ValueError("MODEL_REVISION_SNAPSHOT_INVALID")

    def canonical_source(value: Any) -> Any:
        return canonicalize_locator(value) if canonicalize_locator is not None else value

    owned = {_locator_key(value) for value in packet_locators}
    captured: dict[str, dict[str, Any]] = {}
    for row in prior_operations:
        if not isinstance(row, Mapping):
            raise ValueError("MODEL_REVISION_SNAPSHOT_INVALID")
        identifier = row.get("operation_id")
        if identifier is None or identifier == "":
            continue
        if not isinstance(identifier, str) or not identifier.strip():
            raise ValueError("MODEL_REVISION_SNAPSHOT_INVALID")
        source = canonical_source(row.get("source_row"))
        operation = {"operation_id": identifier, "source_row": source,
                     "revision": row.get("revision")}
        key = identifier.strip()
        if key in captured:
            if captured[key] != operation:
                raise ValueError("MODEL_REVISION_SNAPSHOT_INVALID")
            continue
        captured[key] = operation
        if _locator_key(source) not in owned:
            continue
        snapshot["operations"].append(operation)
    if not model_revision_snapshot_valid(snapshot):
        raise ValueError("MODEL_REVISION_SNAPSHOT_INVALID")
    return snapshot


def bind_model_result_revisions(
    rows: Sequence[Mapping[str, Any]], snapshot: Mapping[str, Any],
    *, canonicalize_locator: Callable[[Any], Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Bind normal model transport to its captured base, preserving raw CAS audit.

    This helper performs no durable/latest lookup and chooses no operation by
    locator, title, norm or quantity. Unknown, foreign and new identities stay
    literal for the existing packet/store guards. Those guards still compare
    the application-owned expected revision with the actual durable revision.
    """
    if not model_revision_snapshot_valid(snapshot):
        raise ValueError("MODEL_REVISION_SNAPSHOT_INVALID")
    known = {operation["operation_id"].strip(): operation for operation in snapshot["operations"]}
    bound: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, Mapping):
            raise ValueError("MODEL_REVISION_ROW_INVALID")
        row = copy.deepcopy(dict(item))
        identifier = row.get("operation_id")
        operation = known.get(identifier.strip()) if isinstance(identifier, str) else None
        source = row.get("source_row")
        canonical_source = (canonicalize_locator(source)
                            if canonicalize_locator is not None and operation is not None else source)
        if operation is not None and _locator_key(canonical_source) == _locator_key(operation["source_row"]):
            authored = {name: copy.deepcopy(row[name]) for name in _MODEL_REVISION_FIELDS if name in row}
            for name in _MODEL_REVISION_FIELDS:
                row.pop(name, None)
            row["expected_revision"] = operation["revision"]
            audit.append({"action": "bound_to_snapshot", "source_row": row.get("source_row"),
                          "operation_id": row.get("operation_id"), "snapshot_revision": operation["revision"],
                          "authored_revision_fields": authored})
        bound.append(row)
    return bound, audit


def admit_model_result_packet(
    rows: Sequence[Mapping[str, Any]],
    *,
    packet_locators: Sequence[str],
    prior_operations: Sequence[Mapping[str, Any]] = (),
    canonicalize_locator: Callable[[Any], Any] | None = None,
) -> PacketAdmission:
    """Preserve owned rows and buffer unknown/out-of-scope decisions unchanged.

    ``prior_operations`` is the explicit set whose identities were offered to
    the model for revision. A known identity must keep its source address and
    match any authored expected/base revision. With no identity, an operation
    is new and must belong to the requested packet. Multiple operations on the
    same address remain legal; titles and professional content never pick IDs.
    """

    def key(value: Any) -> str:
        canonical = canonicalize_locator(value) if canonicalize_locator is not None else value
        return _locator_key(canonical)

    owned = {key(value) for value in packet_locators if key(value)}
    prior_by_id = {
        str(row.get("operation_id") or "").strip(): row
        for row in prior_operations
        if isinstance(row, Mapping) and str(row.get("operation_id") or "").strip()
    }
    result = PacketAdmission()
    for item in rows:
        if not isinstance(item, Mapping):
            continue
        decision = copy.deepcopy(dict(item))
        source = key(decision.get("source_row"))
        operation_id = str(decision.get("operation_id") or "").strip()
        reason = ""
        if not source:
            reason = "invalid_source_row"
        elif operation_id:
            prior = prior_by_id.get(operation_id)
            if prior is None:
                reason = "unknown_operation_id"
            elif source != key(prior.get("source_row")):
                reason = "operation_source_mismatch"
            else:
                revision_field = next(
                    (name for name in ("expected_revision", "base_revision", "revision") if name in decision),
                    None,
                )
                if revision_field is not None:
                    expected = _positive_revision(decision[revision_field])
                    current = _positive_revision(prior.get("revision", 1))
                    if expected is None:
                        reason = "invalid_expected_revision"
                    elif expected != current:
                        # Delivery of an already committed identical decision is
                        # idempotent, even if its old base revision is replayed.
                        from proxy.services.workbook_research_job_service import _decision_content_sha

                        if _decision_content_sha(decision) != _decision_content_sha(prior):
                            reason = "operation_revision_mismatch"
        elif source not in owned:
            reason = "outside_packet_without_identity"
        if not reason:
            result.accepted_rows.append(decision)
            continue
        proposal = {
            "schema": "les.model-result-unapplied-proposal.v1",
            "reason": reason,
            "source_row": decision.get("source_row"),
            "operation_id": operation_id,
            "packet_locators": list(packet_locators),
            "decision": decision,
        }
        encoded = json.dumps(proposal, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        proposal["proposal_id"] = "proposal_" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]
        result.unapplied_proposals.append(proposal)
        result.diagnostics.append(
            f"unapplied_model_proposal:{reason}:{decision.get('source_row') or ''}:{operation_id}"
        )
    return result
