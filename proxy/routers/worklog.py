"""W20.3 — API общего журнала работ (ОЖР, РД-11-05-2007)."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from proxy.security import require_admin, require_user
from proxy.services import work_log_service

router = APIRouter(prefix="/api/worklog", tags=["worklog"])


class WorkLogMeta(BaseModel):
    object_name: Optional[str] = None
    customer: Optional[str] = None
    contractor: Optional[str] = None
    permit: Optional[str] = None
    itr: Optional[list[str]] = None
    spec_journals: Optional[list[str]] = None


@router.get("/{project_id}")
async def worklog_get(project_id: int, _user=Depends(require_user)):
    """Собранный ОЖР объекта (раздел 3 — из журнала объёмов, 0 LLM)."""
    return await asyncio.to_thread(work_log_service.build_work_log, project_id)


@router.patch("/{project_id}/meta")
async def worklog_set_meta(project_id: int, req: WorkLogMeta, _admin=Depends(require_admin)):
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    return await asyncio.to_thread(lambda: work_log_service.set_work_log_meta(project_id, **fields))


@router.post("/{project_id}/export")
async def worklog_export(project_id: int, _user=Depends(require_user)):
    path = await asyncio.to_thread(work_log_service.export_xlsx, project_id)
    return {"path": str(path), "download": f"/api/worklog/{project_id}/download?path={Path(path).name}"}


@router.get("/{project_id}/download")
async def worklog_download(project_id: int, path: str = Query(...), _user=Depends(require_user)):
    out_dir = work_log_service._output_dir().resolve()
    target = (out_dir / Path(path).name).resolve()
    if out_dir not in target.parents or not target.is_file():
        raise HTTPException(404, "Файл не найден")
    return FileResponse(
        target,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=target.name,
    )
