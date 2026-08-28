"""Guarded, isolated execution for a pre-promotion canonical candidate."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from proxy.services.canonical_route_service import CanonicalRouteDecision, CanonicalRouteMode


class CandidateAcceptanceError(ValueError):
    """The request is not allowed to run the isolated acceptance candidate."""


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
    if Path(configured_root).expanduser().resolve() != Path.cwd().resolve():
        raise CandidateAcceptanceError("CANDIDATE_ACCEPTANCE_STATE_ROOT_NOT_PROCESS_CWD")
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
