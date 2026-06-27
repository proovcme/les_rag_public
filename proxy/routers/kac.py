"""КАЦ — API конъюнктурного анализа цен: котировки поставщиков → выбор → цена в ЛСР.

Регламент: для материалов, отсутствующих в ФГИС ЦС, ≥3 КП на материал → экономичный вариант.
0 LLM (детерминированное ядро kac_service). Извлечение котировок из PDF-КП — отдельный шаг.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from proxy.security import require_user
from proxy.services import kac_service

router = APIRouter(prefix="/api/kac", tags=["kac"])

_OUT_DIR = Path("data/kac_out")
_XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class KacRequest(BaseModel):
    quotes: list[dict[str, Any]]
    min_suppliers: int = kac_service.DEFAULT_MIN_SUPPLIERS
    strategy: str = "min"  # min | median


@router.post("/analyze")
async def kac_analyze(req: KacRequest, _user=Depends(require_user)):
    """Котировки → КАЦ по материалам (выбор, достаточность ≥N, разброс цен)."""
    return await asyncio.to_thread(
        kac_service.analyze_kac, req.quotes,
        min_suppliers=req.min_suppliers, strategy=req.strategy,
    )


@router.post("/lsr-lines")
async def kac_lsr_lines(req: KacRequest, _user=Depends(require_user)):
    """Выбранные цены КАЦ → линии для позиций ЛСР (неучтённый материал)."""
    result = await asyncio.to_thread(
        kac_service.analyze_kac, req.quotes,
        min_suppliers=req.min_suppliers, strategy=req.strategy,
    )
    return {"lines": kac_service.kac_to_lsr_lines(result)}


@router.post("/generate")
async def kac_generate(req: KacRequest, _user=Depends(require_user)):
    """Сформировать КАЦ-таблицу xlsx; вернуть путь + ссылку на скачивание."""
    result = await asyncio.to_thread(
        kac_service.analyze_kac, req.quotes,
        min_suppliers=req.min_suppliers, strategy=req.strategy,
    )
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    name = f"kac_{int(time.time())}.xlsx"
    out = _OUT_DIR / name
    await asyncio.to_thread(kac_service.to_xlsx, result, str(out))
    return {"summary": result["summary"], "path": str(out),
            "download": f"/api/kac/download?path={name}"}


@router.get("/download")
async def kac_download(path: str = Query(...), _user=Depends(require_user)):
    out_dir = _OUT_DIR.resolve()
    target = (out_dir / Path(path).name).resolve()
    if out_dir not in target.parents or not target.is_file():
        raise HTTPException(404, "Файл не найден")
    return FileResponse(target, media_type=_XLSX_MEDIA, filename=target.name)


@router.get("/needs")
async def kac_needs(
    code: str = Query(..., description="Код ресурса"),
    book: Optional[str] = None,
    _user=Depends(require_user),
):
    """Нужен ли КАЦ для ресурса — отсутствует ли код в ФГИС ЦС."""
    return await asyncio.to_thread(kac_service.needs_kac, code, book=book)
