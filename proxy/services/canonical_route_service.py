"""Fail-closed rollout contract for the canonical ordinary-chat candidate."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import os
import re
from typing import Any, Iterable, Mapping


class CanonicalRouteMode(str, Enum):
    LEGACY = "legacy"
    SHADOW = "shadow"
    ACTIVE = "active"


@dataclass(frozen=True)
class PromotionReceipt:
    source_commit: str
    build_number: int
    preset_id: str
    observed_model_identity: str
    acceptance_sha256: str
    passed: bool


@dataclass(frozen=True)
class CanonicalRouteDecision:
    requested: CanonicalRouteMode
    effective: CanonicalRouteMode
    source: str
    reason: str
    restart_required: bool

    def public_payload(self) -> dict[str, Any]:
        return {
            "requested": self.requested.value,
            "effective": self.effective.value,
            "source": self.source,
            "reason": self.reason,
            "restart_required": self.restart_required,
        }


@dataclass(frozen=True)
class CanonicalModelDecision:
    call: Mapping[str, Any] | None
    executed_calls: int
    pending_calls: int
    proposed_calls: int


def resolve_canonical_route(
    *,
    receipt: PromotionReceipt | None,
    requested: str | CanonicalRouteMode | None = None,
    expected_commit: str = "",
    expected_build: int = 0,
    expected_preset: str = "",
    expected_model_identity: str = "",
    expected_acceptance_sha256: str = "",
) -> CanonicalRouteDecision:
    raw = str(requested or os.getenv("LES_CANONICAL_AGENT_ROUTE_MODE", "shadow")).strip().lower()
    try:
        requested_mode = CanonicalRouteMode(raw)
        reason = "requested"
    except ValueError:
        requested_mode = CanonicalRouteMode.SHADOW
        reason = "invalid_setting_defaulted_to_shadow"
    source = "argument" if requested is not None else (
        "process" if "LES_CANONICAL_AGENT_ROUTE_MODE" in os.environ else "default"
    )
    if requested_mode is not CanonicalRouteMode.ACTIVE:
        return CanonicalRouteDecision(
            requested=requested_mode,
            effective=requested_mode,
            source=source,
            reason=reason,
            restart_required=False,
        )
    exact = bool(
        receipt
        and receipt.passed
        and expected_commit
        and expected_build > 0
        and expected_preset
        and expected_model_identity
        and re.fullmatch(r"[0-9a-f]{64}", expected_acceptance_sha256)
        and receipt.source_commit == expected_commit
        and receipt.build_number == expected_build
        and receipt.preset_id == expected_preset
        and receipt.observed_model_identity == expected_model_identity
        and receipt.acceptance_sha256 == expected_acceptance_sha256
    )
    return CanonicalRouteDecision(
        requested=requested_mode,
        effective=(CanonicalRouteMode.ACTIVE if exact else CanonicalRouteMode.SHADOW),
        source=source,
        reason=("promotion_receipt_exact" if exact else "promotion_receipt_missing_or_stale"),
        restart_required=False,
    )


def one_model_decision_from_calls(
    calls: Iterable[Mapping[str, Any]],
    *,
    allowed: set[str] | frozenset[str],
) -> CanonicalModelDecision:
    valid: list[dict[str, Any]] = []
    proposed = 0
    for raw in calls:
        proposed += 1
        if not isinstance(raw, Mapping):
            continue
        tool = str(raw.get("tool") or "")
        arguments = raw.get("args")
        if tool not in allowed or not isinstance(arguments, Mapping):
            continue
        valid.append({"tool": tool, "args": dict(arguments)})
    call = valid[0] if valid else None
    return CanonicalModelDecision(
        call=call,
        executed_calls=1 if call else 0,
        pending_calls=max(0, len(valid) - (1 if call else 0)),
        proposed_calls=proposed,
    )
