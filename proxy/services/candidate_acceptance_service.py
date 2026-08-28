"""Guarded, isolated execution for a pre-promotion canonical candidate."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from proxy.services.canonical_route_service import CanonicalRouteDecision, CanonicalRouteMode


class CandidateAcceptanceError(ValueError):
    """The request is not allowed to run the isolated acceptance candidate."""


def _effective_state_paths() -> tuple[Path, ...]:
    """Persistent state touched by the candidate workbook workflow."""
    return (
        Path(os.getenv("LES_CHAT_ATTACHMENT_ROOT", "storage/chat_attachments")),
        Path(os.getenv("RAG_META_DB_PATH", "data/les_meta.db")),
        Path(os.getenv("LES_IDEMPOTENCY_DB", "storage/request_idempotency.db")),
        # The chat evidence application still reads this legacy fixed location
        # alongside the configurable RAG metadata path.
        Path("data/les_meta.db"),
        Path("storage/workbook_checkpoints.db"),
        Path("storage/artifacts/meta.db"),
        Path("storage/artifacts/files"),
    )


def _resolve_under_root(path: Path, root: Path) -> Path:
    resolved = path.expanduser().resolve() if path.is_absolute() else (root / path).resolve()
    if resolved != root and root not in resolved.parents:
        raise CandidateAcceptanceError("CANDIDATE_ACCEPTANCE_STATE_PATH_OUTSIDE_ROOT")
    return resolved


def require_candidate_acceptance(*, requested: bool, user: Any) -> bool:
    """Authorize a candidate only in the process's explicitly isolated state root."""
    if not requested:
        return False
    if not bool(getattr(user, "is_root_admin", False)):
        raise CandidateAcceptanceError("CANDIDATE_ACCEPTANCE_ROOT_ADMIN_REQUIRED")
    # Keep the literal visible to the GUI-first runtime-factor registry AST scan.
    configured_root = os.getenv("LES_CANONICAL_ACCEPTANCE_STATE_ROOT", "").strip()
    if not configured_root:
        raise CandidateAcceptanceError("CANDIDATE_ACCEPTANCE_STATE_ROOT_REQUIRED")
    root = Path(configured_root).expanduser().resolve()
    if root != Path.cwd().resolve():
        raise CandidateAcceptanceError("CANDIDATE_ACCEPTANCE_STATE_ROOT_NOT_PROCESS_CWD")
    for state_path in _effective_state_paths():
        _resolve_under_root(state_path, root)
    return True


def execution_mode_for_candidate_acceptance(
    *,
    candidate_acceptance: bool,
    route: CanonicalRouteDecision,
) -> CanonicalRouteMode:
    """Enable the canonical executor without altering the public route decision."""
    if candidate_acceptance:
        return CanonicalRouteMode.ACTIVE
    return route.effective
