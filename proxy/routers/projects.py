"""W17.1 — API объектов строительства (проектный режим ЛЕС)."""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from proxy.security import require_admin, require_user
from proxy.services import project_service

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    name: str
    code: Optional[str] = ""
    address: Optional[str] = ""


class ProjectStatus(BaseModel):
    status: str


class ProjectLink(BaseModel):
    kind: str
    ref: str


@router.get("")
async def projects_list(_user=Depends(require_user)):
    return {"projects": await asyncio.to_thread(project_service.list_projects)}


@router.post("")
async def projects_create(req: ProjectCreate, _admin=Depends(require_admin)):
    try:
        return await asyncio.to_thread(project_service.create_project, req.name, req.code or "", req.address or "")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/{project_id}")
async def projects_get(project_id: int, _user=Depends(require_user)):
    project = await asyncio.to_thread(project_service.get_project, project_id)
    if project is None:
        raise HTTPException(404, "Объект не найден")
    return project


@router.patch("/{project_id}")
async def projects_status(project_id: int, req: ProjectStatus, _admin=Depends(require_admin)):
    try:
        project = await asyncio.to_thread(project_service.set_project_status, project_id, req.status)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if project is None:
        raise HTTPException(404, "Объект не найден")
    return project


@router.delete("/{project_id}")
async def projects_delete(project_id: int, _admin=Depends(require_admin)):
    return {"deleted": await asyncio.to_thread(project_service.delete_project, project_id)}


@router.post("/{project_id}/links")
async def projects_link(project_id: int, req: ProjectLink, _admin=Depends(require_admin)):
    try:
        return await asyncio.to_thread(project_service.link_entity, project_id, req.kind, req.ref)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/{project_id}/links")
async def projects_links(project_id: int, kind: str = "", _user=Depends(require_user)):
    return {"links": await asyncio.to_thread(project_service.list_links, project_id, kind or None)}


@router.delete("/{project_id}/links")
async def projects_unlink(project_id: int, req: ProjectLink, _admin=Depends(require_admin)):
    return {"unlinked": await asyncio.to_thread(project_service.unlink_entity, project_id, req.kind, req.ref)}
