"""LES.md — файл-контекст папки (CLAUDE.md для ЛЕС): чтение/привязка/черновик/контекст.

Разбор 0 LLM (YAML+regex). Сервис — `les_md_service`. path — внутри LES_EXTERNAL_SOURCE_ROOTS.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from proxy.security import require_admin, require_user
from proxy.services.les_md_service import context_for_chat, generate_draft, read_and_bind

router = APIRouter(prefix="/api/les-md", tags=["les_md"])


class LesMdReadReq(BaseModel):
    path: str = Field(min_length=1)
    write_draft: bool = False     # нет LES.md → собрать черновик и записать


def _guard(raw: str) -> Path:
    from proxy.config import external_source_roots

    roots = external_source_roots()
    if not roots:
        raise HTTPException(403, "внешний доступ выключен: LES_EXTERNAL_SOURCE_ROOTS пуст")
    try:
        cand = Path((raw or "").strip()).expanduser().resolve(strict=True)
    except FileNotFoundError as err:
        raise HTTPException(404, f"путь не найден: {raw}") from err
    except (OSError, RuntimeError) as err:
        raise HTTPException(400, f"некорректный путь: {raw}") from err
    if not any(cand == r or r in cand.parents for r in roots):
        raise HTTPException(403, f"путь вне одобренных корней: {cand}")
    return cand


@router.post("/read")
async def les_md_read(req: LesMdReadReq, _admin=Depends(require_admin)):
    """Найти/прочитать LES.md в папке → привязать к проекту (+ опц. собрать черновик)."""
    path = _guard(req.path)
    return await asyncio.to_thread(read_and_bind, path, write_draft=req.write_draft)


@router.post("/draft")
async def les_md_draft(req: LesMdReadReq, _admin=Depends(require_admin)):
    """Собрать черновик LES.md из скана папки (без записи) — превью."""
    path = _guard(req.path)
    return {"path": str(path), "draft": await asyncio.to_thread(generate_draft, path)}


@router.get("/context/{project_id}")
async def les_md_context(project_id: int, _user=Depends(require_user)):
    """Контекст-блок LES.md, который подмешивается в чат по проекту."""
    return {"project_id": project_id, "context": await asyncio.to_thread(context_for_chat, project_id)}
