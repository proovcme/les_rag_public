"""Provider-neutral contracts for tools exposed to LES models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
import re
from types import MappingProxyType
from typing import Any


_TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value


def _public_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _public_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_public_json(item) for item in value]
    return value


class EffectClass(str, Enum):
    READ = "read"
    COMPUTE = "compute"
    DRAFT = "draft"
    COMMIT = "commit"
    EXTERNAL = "external"
    DESTRUCTIVE = "destructive"


class RetryPolicy(str, Enum):
    NEVER = "never"
    SAFE = "safe"
    IDEMPOTENCY_KEY = "idempotency_key"


class IdempotencyPolicy(str, Enum):
    NONE = "none"
    DERIVED = "derived"
    REQUIRED = "required"


@dataclass(frozen=True)
class ResultBudget:
    max_chars: int
    max_items: int

    def __post_init__(self) -> None:
        if self.max_chars <= 0 or self.max_items <= 0:
            raise ValueError("result budget values must be positive")

    def public_payload(self) -> dict[str, int]:
        return {"max_chars": self.max_chars, "max_items": self.max_items}


@dataclass(frozen=True)
class ToolContract:
    name: str
    version: str
    title: str
    category: str
    summary: str
    input_schema: Mapping[str, Any]
    result_schema: str
    effect: EffectClass
    scopes: tuple[str, ...]
    timeout_seconds: int
    retry: RetryPolicy
    idempotency: IdempotencyPolicy
    result_budget: ResultBudget
    model_owned_fields: tuple[str, ...]
    provenance: str
    tags: tuple[str, ...] = field(default_factory=tuple)
    legacy_returns: str = ""
    approval_required: bool = False

    def __post_init__(self) -> None:
        if not _TOOL_NAME_RE.fullmatch(self.name):
            raise ValueError("tool name must be lower_snake_case")
        if not _SEMVER_RE.fullmatch(self.version):
            raise ValueError("semantic version must be MAJOR.MINOR.PATCH")
        if not self.title.strip() or not self.category.strip() or not self.summary.strip():
            raise ValueError("tool title, category and summary are required")
        if not isinstance(self.input_schema, Mapping):
            raise ValueError("input schema must be an object")
        object.__setattr__(self, "input_schema", _freeze_json(self.input_schema))
        if not self.result_schema.strip():
            raise ValueError("result schema is required")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout must be positive")
        if not self.provenance.strip():
            raise ValueError("provenance policy is required")

    def public_payload(self) -> dict[str, Any]:
        side_effects = "none" if self.effect in {EffectClass.READ, EffectClass.COMPUTE} else self.effect.value
        return {
            "name": self.name,
            "version": self.version,
            "title": self.title,
            "category": self.category,
            "summary": self.summary,
            "input_schema": _public_json(self.input_schema),
            "args_schema": _public_json(self.input_schema),
            "result_schema": self.result_schema,
            "returns": self.legacy_returns or self.result_schema,
            "effect": self.effect.value,
            "side_effects": side_effects,
            "scopes": list(self.scopes),
            "timeout_seconds": self.timeout_seconds,
            "retry": self.retry.value,
            "idempotency": self.idempotency.value,
            "result_budget": self.result_budget.public_payload(),
            "model_owned_fields": list(self.model_owned_fields),
            "provenance": self.provenance,
            "approval_required": self.approval_required,
            "tags": list(self.tags),
        }
