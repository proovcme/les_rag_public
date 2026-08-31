"""Immutable contracts for global model connections.

Provider and engine names are deliberately absent from inference identity.
They may exist only as optional extension labels on a saved connection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class ConnectionLocality(str, Enum):
    LOOPBACK = "loopback"
    PRIVATE_NETWORK = "private_network"
    REMOTE = "remote"


class ConnectionRole(str, Enum):
    ANSWER = "answer"
    EMBEDDINGS = "embeddings"
    LOCAL_FALLBACK = "local_fallback"


class CapabilityName(str, Enum):
    CHAT_COMPLETIONS = "chat_completions"
    STREAMING = "streaming"
    TOOLS = "tools"
    STRUCTURED_OUTPUT = "structured_output"
    RESPONSES = "responses"
    EMBEDDINGS = "embeddings"
    MODELS = "models"
    TOKEN_COUNT = "token_count"
    RERANK = "rerank"


class CapabilityState(str, Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


_EVIDENCE_SOURCES = frozenset({"probe", "operator_declaration", "template_default", "unavailable"})
_MAX_OUTPUT_FIELDS = frozenset({"max_tokens", "max_completion_tokens"})
_CHAT_PROTOCOLS = frozenset({"openai_chat_v1", "native_chat_v1"})


def _required_text(value: str, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


@dataclass(frozen=True)
class ModelConnectionRevision:
    connection_id: str
    revision_id: str
    revision_no: int
    display_name: str
    protocol: str
    base_url: str
    model_id: str
    locality: ConnectionLocality
    requested_context_tokens: int | None
    secret_ref: str | None
    extension_type: str | None
    enabled: bool
    created_at: str
    created_by: str

    def __post_init__(self) -> None:
        for name in ("connection_id", "revision_id", "display_name", "base_url", "model_id", "created_at", "created_by"):
            object.__setattr__(self, name, _required_text(getattr(self, name), name))
        if self.revision_no < 1:
            raise ValueError("revision_no must be positive")
        if self.protocol != "openai_compatible":
            raise ValueError("protocol must be openai_compatible")
        if self.requested_context_tokens is not None and self.requested_context_tokens < 1:
            raise ValueError("requested_context_tokens must be positive")
        if self.secret_ref is not None:
            object.__setattr__(self, "secret_ref", _required_text(self.secret_ref, "secret_ref"))
        if self.extension_type is not None:
            object.__setattr__(self, "extension_type", _required_text(self.extension_type, "extension_type"))


@dataclass(frozen=True)
class CapabilityObservation:
    capability: CapabilityName
    state: CapabilityState
    evidence_source: str
    observed_at: datetime
    detail: str = ""

    def __post_init__(self) -> None:
        source = _required_text(self.evidence_source, "evidence_source")
        if source not in _EVIDENCE_SOURCES:
            raise ValueError(f"unsupported evidence_source: {source}")
        object.__setattr__(self, "evidence_source", source)
        object.__setattr__(self, "observed_at", _aware(self.observed_at, "observed_at"))
        object.__setattr__(self, "detail", str(self.detail or "").strip())


@dataclass(frozen=True)
class CapabilitySnapshot:
    snapshot_id: str
    connection_revision_id: str
    observations: tuple[CapabilityObservation, ...]
    observed_at: datetime
    expires_at: datetime
    transport_options: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "snapshot_id", _required_text(self.snapshot_id, "snapshot_id"))
        object.__setattr__(
            self,
            "connection_revision_id",
            _required_text(self.connection_revision_id, "connection_revision_id"),
        )
        object.__setattr__(self, "observed_at", _aware(self.observed_at, "observed_at"))
        object.__setattr__(self, "expires_at", _aware(self.expires_at, "expires_at"))
        if self.expires_at <= self.observed_at:
            raise ValueError("expires_at must be after observed_at")
        observations = tuple(self.observations)
        names = [item.capability for item in observations]
        if len(names) != len(set(names)):
            raise ValueError("capability observations must be unique")
        object.__setattr__(self, "observations", observations)
        options = {str(key): str(value) for key, value in dict(self.transport_options).items()}
        max_output_field = options.get("max_output_field")
        if max_output_field is not None and max_output_field not in _MAX_OUTPUT_FIELDS:
            raise ValueError("unsupported max_output_field")
        chat_protocol = options.get("chat_protocol")
        if chat_protocol is not None and chat_protocol not in _CHAT_PROTOCOLS:
            raise ValueError("unsupported chat_protocol")
        object.__setattr__(self, "transport_options", MappingProxyType(options))

    def observation(self, capability: CapabilityName) -> CapabilityObservation:
        for item in self.observations:
            if item.capability is capability:
                return item
        return CapabilityObservation(
            capability=capability,
            state=CapabilityState.UNKNOWN,
            evidence_source="unavailable",
            observed_at=self.observed_at,
            detail="not_observed",
        )

    def state(self, capability: CapabilityName) -> CapabilityState:
        return self.observation(capability).state


@dataclass(frozen=True)
class RoleBinding:
    role: ConnectionRole
    binding_revision: int
    connection_revision_id: str
    bound_at: str
    bound_by: str

    def __post_init__(self) -> None:
        if self.binding_revision < 1:
            raise ValueError("binding_revision must be positive")
        for name in ("connection_revision_id", "bound_at", "bound_by"):
            object.__setattr__(self, name, _required_text(getattr(self, name), name))
