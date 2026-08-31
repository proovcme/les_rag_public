"""Deterministic policy intersection for model-visible LES tools."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from proxy.services.tool_contract_service import EffectClass, ToolContract
from proxy.services.tool_registry_service import ToolRegistry


_PHASE_EFFECTS: dict[str, frozenset[EffectClass]] = {
    "research": frozenset({EffectClass.READ, EffectClass.COMPUTE}),
    "draft": frozenset({EffectClass.READ, EffectClass.COMPUTE, EffectClass.DRAFT}),
    "commit": frozenset(
        {EffectClass.READ, EffectClass.COMPUTE, EffectClass.DRAFT, EffectClass.COMMIT}
    ),
    "external": frozenset(
        {
            EffectClass.READ,
            EffectClass.COMPUTE,
            EffectClass.DRAFT,
            EffectClass.COMMIT,
            EffectClass.EXTERNAL,
        }
    ),
    "destructive": frozenset(EffectClass),
}
_EXTENDED_PRESETS = {"qwen-35b", "qwen-35b-extended"}


@dataclass(frozen=True)
class BrokerRequest:
    profile_tools: tuple[str, ...]
    dataset_ids: tuple[str, ...]
    workflow_phase: str
    model_preset: str
    runtime_available: frozenset[str]
    calls_remaining: int
    result_chars_remaining: int
    attachment_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class CapabilityShortlist:
    contracts: tuple[ToolContract, ...]
    omitted_by_reason: Mapping[str, tuple[str, ...]]
    call_limit: int
    result_chars_limit: int

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(contract.name for contract in self.contracts)


class CapabilityBroker:
    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def shortlist(self, request: BrokerRequest) -> CapabilityShortlist:
        preset_limit = 12 if request.model_preset in _EXTENDED_PRESETS else 5
        # The preset bounds how many different tool definitions a small model
        # sees.  It must not also truncate a batch of calls authored by that
        # model (ten estimate rows may legitimately require ten searches).
        call_limit = max(0, int(request.calls_remaining))
        result_chars_limit = max(0, int(request.result_chars_remaining))
        allowed_effects = _PHASE_EFFECTS.get(request.workflow_phase, frozenset())
        omitted: dict[str, list[str]] = {}
        eligible: list[ToolContract] = []
        seen: set[str] = set()

        def omit(reason: str, name: str) -> None:
            omitted.setdefault(reason, []).append(name)

        for raw_name in request.profile_tools:
            name = str(raw_name).strip()
            if not name or name in seen:
                continue
            seen.add(name)
            registration = self._registry.get(name)
            if registration is None:
                omit("unknown", name)
                continue
            if name not in request.runtime_available:
                omit("runtime", name)
                continue
            availability = registration.availability(
                {
                    "dataset_ids": request.dataset_ids,
                    "model_preset": request.model_preset,
                    "workflow_phase": request.workflow_phase,
                }
            )
            if not availability.available:
                omit("runtime", name)
                continue
            contract = registration.contract
            if contract.effect not in allowed_effects:
                omit("phase", name)
                continue
            if (
                "dataset" in contract.scopes
                and "chat_attachment" not in contract.scopes
                and not request.dataset_ids
            ):
                omit("scope", name)
                continue
            if "chat_attachment" in contract.scopes and not request.attachment_ids:
                omit("scope", name)
                continue
            if call_limit <= 0:
                omit("calls_budget", name)
                continue
            if result_chars_limit <= 0:
                omit("result_budget", name)
                continue
            if len(eligible) >= preset_limit:
                omit("preset_limit", name)
                continue
            eligible.append(contract)

        frozen_omissions = MappingProxyType(
            {reason: tuple(names) for reason, names in omitted.items()}
        )
        return CapabilityShortlist(
            contracts=tuple(eligible),
            omitted_by_reason=frozen_omissions,
            call_limit=call_limit,
            result_chars_limit=result_chars_limit,
        )
