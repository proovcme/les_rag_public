"""Immutable registrations for the canonical LES tool registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from proxy.services.tool_contract_service import ToolContract


ToolHandler = Callable[[dict[str, Any]], Any]
AvailabilityPredicate = Callable[[Mapping[str, Any]], "Availability"]


@dataclass(frozen=True)
class Availability:
    available: bool
    reason: str

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("availability reason is required")


def always_available(_runtime: Mapping[str, Any]) -> Availability:
    return Availability(available=True, reason="available")


@dataclass(frozen=True)
class ToolRegistration:
    contract: ToolContract
    handler: ToolHandler
    availability: AvailabilityPredicate = always_available

    def __post_init__(self) -> None:
        if not callable(self.handler):
            raise ValueError("tool handler must be callable")
        if not callable(self.availability):
            raise ValueError("availability predicate must be callable")


class ToolRegistry:
    def __init__(self, registrations: Iterable[ToolRegistration] = ()) -> None:
        self._registrations: dict[str, ToolRegistration] = {}
        for registration in registrations:
            self.register(registration)

    def register(self, registration: ToolRegistration) -> None:
        name = registration.contract.name
        if name in self._registrations:
            existing = self._registrations[name].contract.version
            raise ValueError(
                f"duplicate tool {name!r}: active version {existing}, attempted {registration.contract.version}"
            )
        self._registrations[name] = registration

    def get(self, name: str) -> ToolRegistration | None:
        return self._registrations.get(name)

    def require(self, name: str) -> ToolRegistration:
        registration = self.get(name)
        if registration is None:
            raise KeyError(f"unknown tool: {name}")
        return registration

    def registrations(self) -> tuple[ToolRegistration, ...]:
        return tuple(
            sorted(
                self._registrations.values(),
                key=lambda item: (item.contract.category, item.contract.name),
            )
        )

    def __len__(self) -> int:
        return len(self._registrations)


def canonical_tool_registry() -> ToolRegistry:
    """Build the registry from existing handlers without copying their logic."""
    from proxy.services.tool_harness_service import _build_canonical_tool_registry

    return _build_canonical_tool_registry()
