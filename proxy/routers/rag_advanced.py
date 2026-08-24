"""Operator-visible RAPTOR/ColBERT policy API."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from proxy.security import require_admin
from proxy.services.rag_advanced_policy_service import (
    AdvancedPolicyError,
    operator_snapshot,
    save_policy,
)
from proxy.services.rag_advanced_preflight_service import advanced_preflight
from proxy.services.raptor_publication_service import run_raptor_publication


router = APIRouter(prefix="/api/rag/advanced", tags=["rag-advanced"])
_raptor_task: asyncio.Task | None = None
_colbert_task: asyncio.Task | None = None


class AdvancedPolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    policy_schema: str | None = Field(default=None, alias="schema")
    revision: int | None = None
    execution: dict[str, Any]
    raptor: dict[str, Any]
    colbert: dict[str, Any]
    reranker: dict[str, Any]


@router.get("")
async def get_advanced_policy(_admin=Depends(require_admin)):
    try:
        return operator_snapshot()
    except AdvancedPolicyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.put("")
async def put_advanced_policy(request: AdvancedPolicyRequest, _admin=Depends(require_admin)):
    try:
        save_policy(request.model_dump(exclude_none=True, by_alias=True))
        return operator_snapshot()
    except AdvancedPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/preflight")
async def get_advanced_preflight(_admin=Depends(require_admin)):
    """Capacity/dependency audit that never loads RAPTOR or ColBERT models."""
    from proxy.routers.datasets import get_dataset_state

    snapshot = await get_dataset_state().backend.health_snapshot()
    return advanced_preflight(snapshot)


async def _run_raptor_background(backend: Any) -> None:
    try:
        await asyncio.to_thread(run_raptor_publication, backend)
    except Exception:
        # The durable status contains the stable error code and bounded detail.
        return


@router.post("/raptor/build")
async def start_raptor_build(_admin=Depends(require_admin)):
    """Start or resume the explicit heavy RAPTOR publication job."""
    global _raptor_task
    if _raptor_task is not None and not _raptor_task.done():
        raise HTTPException(status_code=409, detail="RAPTOR_BUILD_ALREADY_RUNNING")
    from proxy.routers.datasets import get_dataset_state
    from proxy.services.rag_advanced_policy_service import load_policy, save_status

    policy = load_policy()
    if policy["raptor"]["mode"] == "off":
        raise HTTPException(status_code=409, detail="RAPTOR_DISABLED_IN_GUI")
    backend = get_dataset_state().backend
    save_status({"raptor": {"readiness": "queued", "last_error_code": ""}})
    _raptor_task = asyncio.create_task(_run_raptor_background(backend))
    return {"status": "queued", "operation": "raptor_publication"}


@router.get("/raptor/status")
async def get_raptor_status(_admin=Depends(require_admin)):
    from proxy.services.rag_advanced_policy_service import load_status

    return load_status()["raptor"]


async def _run_colbert_background(backend: Any) -> None:
    try:
        from proxy.services.colbert_generation_service import run_colbert_generation

        await asyncio.to_thread(run_colbert_generation, backend)
    except Exception as error:
        from proxy.services.rag_advanced_policy_service import save_status

        save_status(
            {
                "colbert": {
                    "readiness": "blocked",
                    "last_error_code": "COLBERT_GENERATION_FAILED",
                    "last_error_detail": f"{type(error).__name__}: {error}"[:500],
                }
            }
        )


@router.post("/colbert/build")
async def start_colbert_build(_admin=Depends(require_admin)):
    """Start the gated sibling-generation; never backfill the active index in place."""
    global _colbert_task
    if _colbert_task is not None and not _colbert_task.done():
        raise HTTPException(status_code=409, detail="COLBERT_BUILD_ALREADY_RUNNING")
    from proxy.routers.datasets import get_dataset_state
    from proxy.services.rag_advanced_policy_service import load_policy

    policy = load_policy()
    if policy["colbert"]["mode"] == "off":
        raise HTTPException(status_code=409, detail="COLBERT_DISABLED_IN_GUI")
    backend = get_dataset_state().backend
    snapshot = await backend.health_snapshot()
    preflight = advanced_preflight(snapshot)
    blockers = (preflight.get("colbert") or {}).get("blockers") or []
    if blockers:
        raise HTTPException(
            status_code=409,
            detail={"error_code": "COLBERT_PREFLIGHT_BLOCKED", "blockers": blockers},
        )
    _colbert_task = asyncio.create_task(_run_colbert_background(backend))
    return {"status": "queued", "operation": "colbert_sibling_generation"}


@router.get("/colbert/status")
async def get_colbert_status(_admin=Depends(require_admin)):
    from proxy.services.rag_advanced_policy_service import load_status

    return load_status()["colbert"]
