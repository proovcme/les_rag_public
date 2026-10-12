"""Immutable facts exchanged with the Lemonade infrastructure extension."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


LemonadeBackend = Literal["llama_cpp", "flm"]
LemonadeModelRole = Literal["chat", "validation", "embedding", "rerank"]
_KNOWN_BACKENDS = frozenset({"llama_cpp", "flm"})
_KNOWN_ROLES = frozenset({"chat", "validation", "embedding", "rerank"})


@dataclass(frozen=True, slots=True)
class LemonadeModelDescriptor:
    """Observed Lemonade model identity used by transport and health policy."""

    model_id: str
    backend: LemonadeBackend | None
    role: LemonadeModelRole = "chat"
    loaded: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.model_id, str) or not self.model_id.strip():
            raise ValueError("Lemonade model_id must not be blank")
        if self.backend is not None and self.backend not in _KNOWN_BACKENDS:
            raise ValueError(f"unknown Lemonade backend: {self.backend!r}")
        if self.role not in _KNOWN_ROLES:
            raise ValueError(f"unknown Lemonade model role: {self.role!r}")


@dataclass(frozen=True, slots=True)
class LemonadeHealth:
    """Factual Lemonade availability snapshot without inferred loaded state."""

    available: bool
    models: tuple[LemonadeModelDescriptor, ...] = ()
    detail: str | None = None
