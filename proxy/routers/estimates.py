"""W20.1 — API смет (ЛСР → позиции, свод по разделам). 0 LLM."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from proxy.security import require_admin, require_user
from proxy.services import estimate_service as es

router = APIRouter(prefix="/api/estimates", tags=["estimates"])


class ImportIn(BaseModel):
    path: str
    name: str = ""


@router.get("/{project_id}")
async def estimates_list(project_id: int, _user=Depends(require_user)):
    """Сметы объекта + итог (для КАРТЫ ОБЪЕКТА)."""
    estimates = await asyncio.to_thread(es.list_estimates, project_id)
    total = await asyncio.to_thread(es.project_total, project_id)
    return {"estimates": estimates, **total}


@router.get("/item/{estimate_id}")
async def estimate_get(estimate_id: int, _user=Depends(require_user)):
    result = await asyncio.to_thread(es.get_estimate, estimate_id)
    if not result:
        raise HTTPException(404, "Смета не найдена")
    return result


@router.post("/{project_id}/import")
async def estimate_import(project_id: int, req: ImportIn, _admin=Depends(require_admin)):
    try:
        return await asyncio.to_thread(es.import_estimate, req.path, project_id, req.name)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(400, str(exc))
