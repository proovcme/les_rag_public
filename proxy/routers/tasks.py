"""Рабочая память: задачник (W16.2) и заметки оператора (W16.3). SQL, без LLM."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from proxy.security import require_user
from proxy.services.memory_service import create_note, delete_note, list_notes
from proxy.services.task_service import TASK_STATUSES, create_task, get_task, list_tasks, update_task

router = APIRouter(prefix="/api/tasks", tags=["tasks"])
notes_router = APIRouter(prefix="/api/notes", tags=["notes"])


class TaskCreate(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    details: str = ""
    dataset_filter: str = ""
    link: str = ""


class TaskPatch(BaseModel):
    status: str | None = None
    title: str | None = None
    details: str | None = None


@router.post("")
async def tasks_create(req: TaskCreate, _user=Depends(require_user)):
    return await asyncio.to_thread(create_task, req.title, req.details, req.dataset_filter, req.link)


@router.get("")
async def tasks_list(status: str = "", limit: int = 50, _user=Depends(require_user)):
    if status and status not in TASK_STATUSES:
        raise HTTPException(400, f"status: {TASK_STATUSES}")
    return {"tasks": await asyncio.to_thread(list_tasks, status, min(limit, 200))}


@router.patch("/{task_id}")
async def tasks_patch(task_id: int, req: TaskPatch, _user=Depends(require_user)):
    if not await asyncio.to_thread(get_task, task_id):
        raise HTTPException(404, f"задачи #{task_id} нет")
    try:
        return await asyncio.to_thread(
            lambda: update_task(task_id, status=req.status, title=req.title, details=req.details)
        )
    except ValueError as err:
        raise HTTPException(400, str(err))


class NoteCreate(BaseModel):
    text: str = Field(min_length=3, max_length=1000)
    dataset_filter: str = ""


@notes_router.post("")
async def notes_create(req: NoteCreate, _user=Depends(require_user)):
    return await asyncio.to_thread(create_note, req.text, req.dataset_filter)


@notes_router.get("")
async def notes_list(limit: int = 50, _user=Depends(require_user)):
    return {"notes": await asyncio.to_thread(list_notes, min(limit, 200))}


@notes_router.delete("/{note_id}")
async def notes_delete(note_id: int, _user=Depends(require_user)):
    if not await asyncio.to_thread(delete_note, note_id):
        raise HTTPException(404, f"заметки #{note_id} нет")
    return {"deleted": note_id}
