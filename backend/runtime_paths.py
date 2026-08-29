"""Canonical ownership boundary for mutable LES runtime paths."""

from __future__ import annotations

import os
from pathlib import Path


MUTABLE_ROOTS = frozenset({"data", "storage", "logs", "RAG_Content", "artifacts"})


class MutablePathError(ValueError):
    """Raised when a mutable path escapes the registered state roots."""


def mutable_path(relative: str | Path) -> Path:
    """Return a mutable path owned by persistent Windows state when configured."""

    candidate = Path(relative)
    if candidate.is_absolute():
        raise MutablePathError("mutable path must be relative")
    if not candidate.parts or candidate.parts[0] not in MUTABLE_ROOTS:
        raise MutablePathError("mutable path must use a registered mutable root")
    state = os.getenv("LES_WINDOWS_STATE_ROOT", "").strip()
    return Path(state).joinpath(*candidate.parts) if state else candidate


def mutable_root(name: str) -> Path:
    """Return one registered mutable root."""

    return mutable_path(name)
