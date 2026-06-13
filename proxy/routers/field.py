"""Журнал полевых объёмов — CRUD, агрегации и экспорт (W8.1/W8.4).

ADR-11: числа считает SQL, не LLM. Сервис — `field_intake_service` (как `tasks`,
роутер импортирует сервис напрямую, без инъекции состояния).
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from proxy.security import require_user
from proxy.services.field_intake_service import (
    FIELD_STATUSES,
    aggregate_volumes,
    create_entry,
    delete_entry,
    export_xlsx,
    get_entry,
    list_entries,
    update_entry,
)

router = APIRouter(prefix="/api/field", tags=["field"])

_EXPORT_DIR = Path("storage/field/_exports")


class FieldEntryCreate(BaseModel):
    position: str = Field(min_length=1, max_length=300)
    volume: float
    unit: str = ""
    entry_date: str = ""
    zahvatka: str = ""
    doc_id: str = ""
    element_id: str = ""
    author: str = ""
    status: str = "confirmed"
    notes: str = ""


class FieldEntryPatch(BaseModel):
    position: str | None = None
    volume: float | None = None
    unit: str | None = None
    entry_date: str | None = None
    zahvatka: str | None = None
    doc_id: str | None = None
    element_id: str | None = None
    status: str | None = None
    notes: str | None = None


@router.post("")
async def field_create(req: FieldEntryCreate, _user=Depends(require_user)):
    if req.status not in FIELD_STATUSES:
        raise HTTPException(400, f"status: {FIELD_STATUSES}")
    return await asyncio.to_thread(
        create_entry,
        req.position,
        req.volume,
        req.unit,
        entry_date=req.entry_date,
        zahvatka=req.zahvatka,
        doc_id=req.doc_id,
        element_id=req.element_id,
        author=req.author,
        status=req.status,
        notes=req.notes,
    )


@router.get("")
async def field_list(
    status: str = "",
    zahvatka: str = "",
    position: str = "",
    date_from: str = "",
    date_to: str = "",
    limit: int = 200,
    _user=Depends(require_user),
):
    if status and status not in FIELD_STATUSES:
        raise HTTPException(400, f"status: {FIELD_STATUSES}")
    entries = await asyncio.to_thread(
        list_entries,
        status,
        zahvatka=zahvatka,
        position=position,
        date_from=date_from,
        date_to=date_to,
        limit=min(limit, 1000),
    )
    return {"entries": entries, "count": len(entries)}


@router.get("/summary")
async def field_summary(
    status: str = "confirmed",
    zahvatka: str = "",
    position: str = "",
    date_from: str = "",
    date_to: str = "",
    _user=Depends(require_user),
):
    if status not in FIELD_STATUSES:
        raise HTTPException(400, f"status: {FIELD_STATUSES}")
    rows = await asyncio.to_thread(
        aggregate_volumes,
        status=status,
        zahvatka=zahvatka,
        position=position,
        date_from=date_from,
        date_to=date_to,
    )
    return {"rows": rows, "groups": len(rows)}


@router.patch("/{entry_id}")
async def field_patch(entry_id: int, req: FieldEntryPatch, _user=Depends(require_user)):
    if not await asyncio.to_thread(get_entry, entry_id):
        raise HTTPException(404, f"записи #{entry_id} нет")
    try:
        return await asyncio.to_thread(
            lambda: update_entry(
                entry_id,
                position=req.position,
                volume=req.volume,
                unit=req.unit,
                entry_date=req.entry_date,
                zahvatka=req.zahvatka,
                doc_id=req.doc_id,
                element_id=req.element_id,
                status=req.status,
                notes=req.notes,
            )
        )
    except ValueError as err:
        raise HTTPException(400, str(err))


@router.delete("/{entry_id}")
async def field_delete(entry_id: int, _user=Depends(require_user)):
    ok = await asyncio.to_thread(delete_entry, entry_id)
    if not ok:
        raise HTTPException(404, f"записи #{entry_id} нет")
    return {"deleted": entry_id}


@router.post("/export")
async def field_export(status: str = "confirmed", _user=Depends(require_user)):
    if status not in FIELD_STATUSES:
        raise HTTPException(400, f"status: {FIELD_STATUSES}")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = _EXPORT_DIR / f"field_{status}_{stamp}.xlsx"
    rows = await asyncio.to_thread(export_xlsx, out, status=status)
    return {"rows": rows, "xlsx_path": str(out)}


@router.get("/download")
async def field_download(_user=Depends(require_user)):
    files = sorted(_EXPORT_DIR.glob("field_*.xlsx")) if _EXPORT_DIR.exists() else []
    if not files:
        raise HTTPException(404, "экспорт ещё не сформирован — сначала POST /api/field/export")
    latest = files[-1]
    return FileResponse(
        latest,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=latest.name,
    )
