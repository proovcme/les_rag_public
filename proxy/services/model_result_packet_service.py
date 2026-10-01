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
