"""Карта файлового архива — W15.1 (LES3_PLAN). Без LLM, без чтения содержимого."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from proxy.security import require_admin, require_user
from proxy.services.file_map_service import map_stats, scan_root, search_map

router = APIRouter(prefix="/api/filemap", tags=["filemap"])


class ScanRequest(BaseModel):
    path: str
    max_files: int = 500_000


@router.post("/scan")
async def filemap_scan(req: ScanRequest, _admin=Depends(require_admin)):
    """Скан/рескан корня (инкрементальный по mtime). Только метаданные."""
    try:
        return await asyncio.to_thread(scan_root, Path(req.path), max_files=req.max_files)
    except ValueError as err:
        raise HTTPException(400, str(err))


@router.get("/search")
async def filemap_search(q: str = "", ext: str = "", cipher: str = "", limit: int = 100, _user=Depends(require_user)):
    """Поиск по карте: имя/путь/шифр (LIKE), фильтр расширения."""
    if not (q or ext or cipher):
        raise HTTPException(400, "укажи q, ext или cipher")
    return {"results": await asyncio.to_thread(search_map, q, ext, cipher, limit)}


@router.get("/stats")
async def filemap_stats(_user=Depends(require_user)):
    """Корни, топ расширений, файлы с распознанными шифрами."""
    return await asyncio.to_thread(map_stats)
