"""W17.4 — API слоя решений проекта (DecisionRecord, типизированные рёбра)."""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from proxy.security import require_admin, require_user
from proxy.services import decision_service

router = APIRouter(prefix="/api/decisions", tags=["decisions"])


class DecisionCreate(BaseModel):
    decision: str
    question: Optional[str] = ""
    rationale: Optional[str] = ""
    status: Optional[str] = "decided"
    tags: Optional[str] = ""
    project_id: Optional[int] = 0
    at: Optional[str] = ""


class DecisionStatus(BaseModel):
    status: str


@router.get("")
async def decisions_list(
    project_id: Optional[int] = None, status: str = "",
    limit: int = Query(default=100, ge=1, le=1000), _user=Depends(require_user),
):
    return {"decisions": await asyncio.to_thread(
        decision_service.list_decisions, project_id, status or None, limit
    )}


@router.get("/{decision_id}")
async def decisions_get(decision_id: int, _user=Depends(require_user)):
    """Решение + бэклинки, сгруппированные по типу ребра (W17.4)."""
    rec = await asyncio.to_thread(decision_service.get_decision, decision_id)
    if rec is None:
        raise HTTPException(404, "Решение не найдено")
    return rec


@router.post("")
async def decisions_create(req: DecisionCreate, _admin=Depends(require_admin)):
    try:
        return await asyncio.to_thread(
            decision_service.create_decision, req.decision,
            question=req.question or "", rationale=req.rationale or "",
            status=req.status or "decided", tags=req.tags or "",
            project_id=req.project_id or 0, at=req.at or "",
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.patch("/{decision_id}")
async def decisions_status(decision_id: int, req: DecisionStatus, _admin=Depends(require_admin)):
    try:
        rec = await asyncio.to_thread(decision_service.update_status, decision_id, req.status)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if rec is None:
        raise HTTPException(404, "Решение не найдено")
    return rec


@router.post("/{new_id}/supersedes/{old_id}")
async def decisions_supersede(new_id: int, old_id: int, _admin=Depends(require_admin)):
    rec = await asyncio.to_thread(decision_service.supersede_decision, new_id, old_id)
    if rec is None:
        raise HTTPException(404, "Решение не найдено")
    return rec
