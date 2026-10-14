"""Immutable contracts for global model connections.

Provider and engine names are deliberately absent from inference identity.
They may exist only as optional extension labels on a saved connection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import math
from types import MappingProxyType
from typing import Any, Mapping


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
_REASONING_MODES = frozenset({"unconfigured", "effort", "enabled", "enable_thinking"})
_ENABLED_EFFORTS = frozenset({"minimal", "low", "medium", "high", "xhigh", "max"})


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
class ChatOptions:
    """Operator-declared Chat Completions wire controls, never provider facts."""

    max_output_field: str | None = None
    reasoning_mode: str = "unconfigured"
    enabled_effort: str | None = None
    temperature_mode: str = "profile"
    requested_output_tokens: int | None = None
    top_p: float | None = None
    top_k: int | None = None
    presence_penalty: float | None = None

    def __post_init__(self) -> None:
        if self.max_output_field is not None and self.max_output_field not in _MAX_OUTPUT_FIELDS:
            raise ValueError("unsupported max_output_field")
        if self.reasoning_mode not in _REASONING_MODES:
            raise ValueError("unsupported reasoning_mode")
        if self.temperature_mode not in {"profile", "omit"}:
            raise ValueError("unsupported temperature_mode")
        if self.reasoning_mode == "effort":
            if self.enabled_effort not in _ENABLED_EFFORTS:
                raise ValueError("effort mode requires declared enabled_effort")
        elif self.enabled_effort is not None:
            raise ValueError("enabled_effort requires effort mode")
        value = self.requested_output_tokens
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 1):
            raise ValueError("requested_output_tokens must be a positive integer")
        value = self.top_p
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                  or not 0 < value <= 1 or not math.isfinite(value)):
            raise ValueError("INVALID_TOP_P")
        value = self.top_k
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)
                                  or (value != -1 and value < 1)):
            raise ValueError("INVALID_TOP_K")
        value = self.presence_penalty
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                  or not -2 <= value <= 2 or not math.isfinite(value)):
            raise ValueError("INVALID_PRESENCE_PENALTY")

    @classmethod
    def from_value(cls, value: ChatOptions | Mapping[str, Any] | None) -> ChatOptions:
        return value if isinstance(value, cls) else cls(**dict(value or {}))

    def to_dict(self) -> dict[str, Any]:
        defaults = ChatOptions()
        return {name: getattr(self, name) for name in self.__dataclass_fields__
                if getattr(self, name) != getattr(defaults, name)}

    def output_field(self, legacy_field: str = "max_tokens") -> str:
        return self.max_output_field or legacy_field

    def sampling_parameters(self) -> dict[str, int | float]:
        """Same declared controls in OpenAI fields and native Ollama options."""
        return {name: value for name in ("top_p", "top_k", "presence_penalty")
                if (value := getattr(self, name)) is not None}

    def parameters(
        self, *, max_output_tokens: int, temperature: float | None,
        reasoning_enabled: bool, legacy_field: str = "max_tokens",
        include_reasoning: bool = True,
    ) -> dict[str, Any]:
        """One renderer for probe and inference; omission is intentional."""
        output = min(max_output_tokens, self.requested_output_tokens or max_output_tokens)
        result: dict[str, Any] = {self.output_field(legacy_field): output}
        if temperature is not None and self.temperature_mode == "profile":
            result["temperature"] = temperature
        result.update(self.sampling_parameters())
        if include_reasoning and self.reasoning_mode == "effort":
            result["reasoning_effort"] = self.enabled_effort if reasoning_enabled else "none"
        elif include_reasoning and self.reasoning_mode == "enabled":
            result["reasoning"] = {"enabled": reasoning_enabled}
        elif include_reasoning and self.reasoning_mode == "enable_thinking":
            result["enable_thinking"] = reasoning_enabled
        return result


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
    chat_options: ChatOptions = field(default_factory=ChatOptions)

    def __post_init__(self) -> None:
        object.__setattr__(self, "chat_options", ChatOptions.from_value(self.chat_options))
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
