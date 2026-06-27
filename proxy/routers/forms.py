"""W11.3/W19 — API типовых форм документов: дескриптор + данные объекта → документ."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from proxy.security import require_user
from proxy.services import forms_service

router = APIRouter(prefix="/api/forms", tags=["forms"])

_MEDIA = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


class FormGenerate(BaseModel):
    project_id: Optional[int] = None
    fmt: str = "docx"
    manual: Optional[dict[str, Any]] = None


@router.get("")
async def forms_list(_user=Depends(require_user)):
    return {"forms": await asyncio.to_thread(forms_service.list_forms)}


@router.get("/{form_id}/fields")
async def forms_fields(form_id: str, project_id: Optional[int] = None, _user=Depends(require_user)):
    """Поля формы с разрешёнными из объекта значениями (0 LLM); needs_input — ручной ввод."""
    resolved = await asyncio.to_thread(forms_service.resolve_fields, form_id, project_id, None)
    if resolved is None:
        raise HTTPException(404, f"Форма {form_id!r} не найдена")
    return resolved


@router.post("/{form_id}/generate")
async def forms_generate(form_id: str, req: FormGenerate, _user=Depends(require_user)):
    """Сгенерировать документ. html — инлайн-превью; docx/xlsx — путь + /download."""
    try:
        result = await asyncio.to_thread(
            forms_service.generate, form_id, req.fmt,
            project_id=req.project_id, manual=req.manual or {},
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    if result.get("path"):
        result["download"] = f"/api/forms/{form_id}/download?path={Path(result['path']).name}"
    return result


@router.get("/{form_id}/download")
async def forms_download(form_id: str, path: str = Query(...), _user=Depends(require_user)):
    """Отдать ранее сгенерированный файл (по имени, в каталоге выдачи — path-guard)."""
    out_dir = forms_service._output_dir().resolve()
    target = (out_dir / Path(path).name).resolve()
    if out_dir not in target.parents or not target.is_file():
        raise HTTPException(404, "Файл не найден")
    fmt = target.suffix.lstrip(".")
    return FileResponse(target, media_type=_MEDIA.get(fmt, "application/octet-stream"), filename=target.name)
