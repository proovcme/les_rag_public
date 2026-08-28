"""Fail-closed rollout contract for the canonical ordinary-chat candidate."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import inspect
import os
import re
from typing import Any, Awaitable, Callable, Iterable, Mapping

from proxy.services.model_connection_contracts import ConnectionLocality, ConnectionRole
from proxy.services.model_connection_resolver_service import (
    ModelConnectionResolver,
    ResolvedModelConnection,
)
from proxy.services.openai_compatible_transport_service import (
    InferenceRequest,
    InferenceResponse,
    ModelTransportError,
    OpenAICompatibleTransport,
)


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


@dataclass(frozen=True)
class ModelChatResult:
    response: InferenceResponse
    connection: ResolvedModelConnection | Any | None
    fallback_used: bool
    pending_tool_calls: int = 0

    def public_connection_payload(self) -> dict[str, Any] | None:
        if self.connection is None:
            return None
        locality = self.connection.locality
        return {
            "connection_id": self.connection.connection_id,
            "revision_id": self.connection.revision_id,
            "display_name": self.connection.display_name,
            "model_id": self.connection.model_id,
            "locality": locality.value if isinstance(locality, ConnectionLocality) else str(locality),
            "fallback_used": self.fallback_used,
        }


LegacyComplete = Callable[
    [InferenceRequest],
    InferenceResponse | Awaitable[InferenceResponse],
]


class BoundModelChatRunner:
    """Execute one ordinary model turn without provider or registry scans."""

    def __init__(
        self,
        *,
        resolver: ModelConnectionResolver,
        transport: OpenAICompatibleTransport,
    ):
        self.resolver = resolver
        self.transport = transport

    @staticmethod
    def _bounded_result(
        response: InferenceResponse,
        *,
        connection: ResolvedModelConnection | Any | None,
        fallback_used: bool,
    ) -> ModelChatResult:
        calls = tuple(response.tool_calls)
        bounded = InferenceResponse(
            text=response.text,
            tool_calls=calls[:1],
            finish_reason=response.finish_reason,
            usage=response.usage,
        )
        return ModelChatResult(
            response=bounded,
            connection=connection,
            fallback_used=fallback_used,
            pending_tool_calls=max(0, len(calls) - 1),
        )

    @staticmethod
    async def _legacy(
        legacy_complete: LegacyComplete,
        request: InferenceRequest,
    ) -> InferenceResponse:
        result = legacy_complete(request)
        if inspect.isawaitable(result):
            result = await result
        return result

    async def complete(
        self,
        *,
        mode: CanonicalRouteMode,
        request: InferenceRequest,
        legacy_complete: LegacyComplete,
        remote_allowed: bool = True,
    ) -> ModelChatResult:
        canonical_mode = CanonicalRouteMode(mode)
        if canonical_mode is CanonicalRouteMode.LEGACY:
            return self._bounded_result(
                await self._legacy(legacy_complete, request),
                connection=None,
                fallback_used=False,
            )
        if canonical_mode is CanonicalRouteMode.SHADOW:
            try:
                self.resolver.resolve(ConnectionRole.ANSWER)
            except Exception:
                pass
            return self._bounded_result(
                await self._legacy(legacy_complete, request),
                connection=None,
                fallback_used=False,
            )

        primary = self.resolver.resolve(ConnectionRole.ANSWER)
        if primary.locality is ConnectionLocality.REMOTE and not remote_allowed:
            fallback = self.resolver.resolve_fallback(primary.revision_id)
            response = await self.transport.complete(fallback, request)
            return self._bounded_result(response, connection=fallback, fallback_used=True)
        try:
            response = await self.transport.complete(primary, request)
            return self._bounded_result(response, connection=primary, fallback_used=False)
        except ModelTransportError:
            fallback = self.resolver.resolve_fallback(primary.revision_id)
            response = await self.transport.complete(fallback, request)
            return self._bounded_result(response, connection=fallback, fallback_used=True)


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
