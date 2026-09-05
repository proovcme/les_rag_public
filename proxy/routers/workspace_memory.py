"""Explicit local-user controls for advisory notes, never model-generated memory."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from proxy.security import require_user
from proxy.services import memory_service, project_service

router = APIRouter(prefix='/api/workspace/memory', tags=['workspace'])


class NoteCreate(BaseModel):
    text: str = Field(max_length=2000)
    project_id: int = Field(default=0, ge=0)
    source_session_id: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator('text')
    @classmethod
    def validate_text(cls, value: str) -> str:
        return memory_service.validate_note_text(value)


class NoteUpdate(BaseModel):
    project_id: int = Field(ge=0)
    text: str | None = Field(default=None, max_length=2000)
    enabled: bool | None = None

    @field_validator('text')
    @classmethod
    def validate_text(cls, value: str | None) -> str | None:
        return memory_service.validate_note_text(value) if value is not None else None


async def _check_project(project_id: int) -> None:
    if project_id and await asyncio.to_thread(project_service.get_project, project_id) is None:
        raise HTTPException(404, 'Объект не найден')


@router.get('')
async def list_memory(project_id: int = Query(default=0, ge=0), _user=Depends(require_user)):
    return {'notes': await asyncio.to_thread(memory_service.list_notes, limit=500, project_id=project_id)}


@router.post('')
async def create_memory(req: NoteCreate, _user=Depends(require_user)):
    await _check_project(req.project_id)
    if req.source_session_id is not None:
        from proxy.services import chat_session_service
        session = await asyncio.to_thread(chat_session_service.get_session, req.source_session_id)
        if session is None or int(session.get('project_id') or 0) != req.project_id:
            raise HTTPException(422, 'Исходный чат должен принадлежать выбранной области памяти')
    return await asyncio.to_thread(memory_service.create_note, req.text,
                                   project_id=req.project_id, source_session_id=req.source_session_id)


@router.patch('/{note_id}')
async def update_memory(note_id: int, req: NoteUpdate, _user=Depends(require_user)):
    await _check_project(req.project_id)
    note = await asyncio.to_thread(memory_service.update_note, note_id, project_id=req.project_id,
                                   text=req.text, enabled=req.enabled)
    if note is None:
        raise HTTPException(404, 'Заметка не найдена в выбранной области')
    return note


@router.delete('/{note_id}')
async def delete_memory(note_id: int, project_id: int = Query(ge=0), _user=Depends(require_user)):
    deleted = await asyncio.to_thread(memory_service.delete_note, note_id, project_id=project_id)
    if not deleted:
        raise HTTPException(404, 'Заметка не найдена в выбранной области')
    return {'deleted': True}
