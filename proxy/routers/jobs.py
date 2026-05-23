"""Durable and in-memory job routes."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from fastapi import APIRouter, Depends

from proxy.security import require_user

router = APIRouter(prefix="/api", tags=["jobs"])
logger = logging.getLogger(__name__)


@dataclass
class JobsRouterState:
    job_service: Any
    job_tracker: dict


_state: JobsRouterState | None = None


def set_jobs_state(state: JobsRouterState) -> None:
    global _state
    _state = state


def get_jobs_state() -> JobsRouterState:
    if _state is None:
        raise RuntimeError("jobs router state is not configured")
    return _state


@router.get("/jobs")
async def get_jobs(_user=Depends(require_user)):
    state = get_jobs_state()
    try:
        durable = state.job_service.list()
    except Exception as error:
        logger.warning("[JOBS] durable list failed: %s", error)
        durable = {}
    merged = dict(durable)
    merged.update(state.job_tracker)
    return merged
