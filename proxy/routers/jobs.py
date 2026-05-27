"""Durable and in-memory job routes."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

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


ACTIVE_STATUSES = {"QUEUED", "PARSING", "RUNNING"}


def summarize_job(job_id: str, job: Any) -> dict[str, Any]:
    if not isinstance(job, dict):
        return {"id": job_id, "status": str(job)}

    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    summary = {
        "id": job.get("id") or job_id,
        "type": job.get("type", ""),
        "status": job.get("status", ""),
        "source": job.get("source", ""),
        "dataset_id": job.get("dataset_id", ""),
        "dataset_name": job.get("dataset_name", ""),
        "total": job.get("total", 0),
        "processed": job.get("processed", 0),
        "errors": job.get("errors", 0),
        "message": job.get("message", ""),
        "started_at": job.get("started_at", ""),
        "updated_at": job.get("updated_at", ""),
        "finished_at": job.get("finished_at", ""),
    }
    if result:
        summary["result_summary"] = {
            "status": result.get("status"),
            "batches_run": result.get("batches_run"),
            "remaining_pending": result.get("remaining_pending"),
            "errors": result.get("errors"),
            "stop_reason": result.get("stop_reason", ""),
            "batches_count": len(result.get("batches") or []) if isinstance(result.get("batches"), list) else 0,
        }
    return summary


def merged_jobs(state: JobsRouterState, *, limit: int = 200) -> dict[str, Any]:
    try:
        durable = state.job_service.list(limit=limit)
    except Exception as error:
        logger.warning("[JOBS] durable list failed: %s", error)
        durable = {}
    merged = dict(durable)
    for job_id, memory_job in state.job_tracker.items():
        if isinstance(memory_job, dict):
            merged[job_id] = {**merged.get(job_id, {}), **memory_job}
        else:
            merged[job_id] = memory_job
    return merged


@router.get("/jobs/summary")
async def get_jobs_summary(
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    active_only: bool = False,
    _user=Depends(require_user),
):
    state = get_jobs_state()
    summaries = [summarize_job(job_id, job) for job_id, job in merged_jobs(state, limit=limit).items()]
    if active_only:
        summaries = [
            job
            for job in summaries
            if str(job.get("status", "")).upper() in ACTIVE_STATUSES
        ]
    summaries.sort(key=lambda item: str(item.get("updated_at") or item.get("started_at") or ""), reverse=True)
    summaries = summaries[:limit]
    return {
        "count": len(summaries),
        "active_count": sum(1 for job in summaries if str(job.get("status", "")).upper() in ACTIVE_STATUSES),
        "jobs": summaries,
    }


@router.get("/jobs")
async def get_jobs(_user=Depends(require_user)):
    state = get_jobs_state()
    return merged_jobs(state)
