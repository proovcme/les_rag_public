"""W17.3 — API доменной онтологии: классификационный хребет + состояния CDE."""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from proxy.security import require_admin, require_user
from proxy.services import ontology_service

router = APIRouter(prefix="/api/ontology", tags=["ontology"])


@router.get("/backbone")
async def ontology_backbone(import_id: str = "", _user=Depends(require_user)):
    """Классификационный хребет Floor→System→Category (количества), 0 LLM."""
    return await asyncio.to_thread(ontology_service.classification_backbone, import_id or None)


@router.get("/elements")
async def ontology_elements(
    floor: str = "", system: str = "", category: str = "", import_id: str = "",
    limit: int = Query(default=200, ge=1, le=2000),
    _user=Depends(require_user),
):
    """Обход хребта: «элементы системы вентиляции на этаже 3» (0 LLM)."""
    elements = await asyncio.to_thread(
        ontology_service.elements_in,
        floor=floor or None, system=system or None, category=category or None,
        import_id=import_id or None, limit=limit,
    )
    return {"count": len(elements), "elements": elements}


@router.get("/lbs")
async def ontology_lbs(status: str = "confirmed", _user=Depends(require_user)):
    """Захватки как LBS-хабы (своды журнала объёмов), 0 LLM."""
    return {"hubs": await asyncio.to_thread(ontology_service.lbs_hubs, status)}


# ── контейнеры (состояния CDE ISO 19650) ─────────────────────────────

class ContainerRegister(BaseModel):
    ref: str
    kind: Optional[str] = "document"
    title: Optional[str] = ""
    project_id: Optional[int] = 0
    revision: Optional[str] = ""
    state: Optional[str] = "WIP"


class ContainerState(BaseModel):
    ref: str
    state: str


class ContainerSupersede(BaseModel):
    new_ref: str
    old_ref: str
    kind: Optional[str] = "document"
    title: Optional[str] = ""
    project_id: Optional[int] = 0
    revision: Optional[str] = ""


@router.get("/containers")
async def containers_list(
    project_id: Optional[int] = None, state: str = "", _user=Depends(require_user)
):
    return {"containers": await asyncio.to_thread(
        ontology_service.list_containers, project_id, state or None
    )}


@router.get("/cde-summary")
async def containers_cde_summary(project_id: Optional[int] = None, _user=Depends(require_user)):
    return await asyncio.to_thread(ontology_service.cde_summary, project_id)


@router.post("/containers")
async def containers_register(req: ContainerRegister, _admin=Depends(require_admin)):
    try:
        return await asyncio.to_thread(
            ontology_service.register_container, req.ref,
            kind=req.kind or "document", title=req.title or "",
            project_id=req.project_id or 0, revision=req.revision or "", state=req.state or "WIP",
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/containers/state")
async def containers_set_state(req: ContainerState, _admin=Depends(require_admin)):
    try:
        return await asyncio.to_thread(ontology_service.set_container_state, req.ref, req.state)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/containers/supersede")
async def containers_supersede(req: ContainerSupersede, _admin=Depends(require_admin)):
    try:
        return await asyncio.to_thread(
            ontology_service.supersede_container, req.new_ref, req.old_ref,
            kind=req.kind or "document", title=req.title or "",
            project_id=req.project_id or 0, revision=req.revision or "",
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
