"""W20.4 — API входного контроля (ГОСТ 24297): акты, журнал, реестр документов качества."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from proxy.security import require_admin, require_user
from proxy.services import incoming_control_service as ics

router = APIRouter(prefix="/api/incoming-control", tags=["incoming-control"])


class QualityDocIn(BaseModel):
    doc_type: str = "сертификат"
    number: str = ""
    material: str = ""
    issued_by: str = ""
    valid_until: str = ""
    file_id: Optional[str] = None


class ControlIn(BaseModel):
    material: str
    batch: str = ""
    control_date: str = ""
    spec_id: Optional[int] = None
    quality_doc_id: Optional[int] = None
    quantity: Optional[float] = None
    unit: str = ""
    result: str = ""
    decision: str = ics.ADMITTED
    inspector: str = ""
    zahvatka: str = ""
    notes: str = ""


@router.get("/{project_id}/journal")
async def journal(project_id: int, _user=Depends(require_user)):
    """Журнал входного контроля объекта (0 LLM)."""
    return await asyncio.to_thread(ics.build_journal, project_id)


@router.post("/{project_id}/records")
async def add_record(project_id: int, req: ControlIn, _admin=Depends(require_admin)):
    return await asyncio.to_thread(lambda: ics.add_incoming_control(project_id, **req.model_dump()))


@router.get("/{project_id}/act/{control_id}")
async def act(project_id: int, control_id: int, _user=Depends(require_user)):
    result = await asyncio.to_thread(ics.build_act, project_id, control_id)
    if not result:
        raise HTTPException(404, "Запись входного контроля не найдена")
    return result


@router.get("/{project_id}/quality-docs")
async def quality_docs(project_id: int, query: Optional[str] = None, _user=Depends(require_user)):
    """Реестр документов о качестве (поиск; флаг expired для «красных»)."""
    return await asyncio.to_thread(ics.list_quality_docs, project_id, query)


@router.post("/{project_id}/quality-docs")
async def add_quality_doc(project_id: int, req: QualityDocIn, _admin=Depends(require_admin)):
    return await asyncio.to_thread(lambda: ics.add_quality_doc(project_id, **req.model_dump()))


@router.post("/{project_id}/export")
async def export(project_id: int, _user=Depends(require_user)):
    path = await asyncio.to_thread(ics.export_journal_xlsx, project_id)
    return {"path": str(path), "download": f"/api/incoming-control/{project_id}/download?path={Path(path).name}"}


@router.get("/{project_id}/download")
async def download(project_id: int, path: str = Query(...), _user=Depends(require_user)):
    out_dir = ics._output_dir().resolve()
    target = (out_dir / Path(path).name).resolve()
    if out_dir not in target.parents or not target.is_file():
        raise HTTPException(404, "Файл не найден")
    return FileResponse(
        target,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=target.name,
    )
