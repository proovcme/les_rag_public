"""Ручная верификация распознанных таблиц объёмов — API.

Сплит-режим Совушки: слева рендер скана, справа извлечённая таблица. Оператор
подтверждает «всё ок» или правит — результат становится принятой выпиской и
ground truth для бенча извлечения. См. proxy/services/verify_service.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from proxy.security import require_user
from proxy.services import verify_service

router = APIRouter(prefix="/api/verify", tags=["verify"])


class ExtractRequest(BaseModel):
    path: str
    page: int = 0
    engine: str = "local"
    region: list[float] | None = None  # [x0,y0,x1,y1] 0..1 — выделенная таблица на чертеже


class SaveRequest(BaseModel):
    path: str
    page: int = 0
    rows: list[dict]
    verdict: str = "ok"  # ok | corrected | rejected
    pred_rows: list[dict] | None = None  # исходное извлечение модели (до правок)


@router.post("/extract")
async def verify_extract(req: ExtractRequest, _user=Depends(require_user)) -> dict:
    try:
        return verify_service.render_and_extract(req.path, req.page, req.engine, req.region)
    except FileNotFoundError:
        raise HTTPException(404, "файл не найден")
    except Exception as exc:
        raise HTTPException(400, f"не удалось обработать страницу: {exc}")


@router.get("/image")
async def verify_image(token: str, _user=Depends(require_user)):
    p = verify_service.image_path(token)
    if p is None:
        raise HTTPException(404, "рендер не найден — сначала /extract")
    return FileResponse(p, media_type="image/png")


@router.post("/save")
async def verify_save(req: SaveRequest, _user=Depends(require_user)) -> dict:
    record = verify_service.save_verification(
        req.path, req.page, req.rows, req.verdict, pred_rows=req.pred_rows
    )
    return {"ok": True, "token": record["token"], "n_rows": len(record["rows"])}


@router.get("/list")
async def verify_list(_user=Depends(require_user)) -> dict:
    return {"items": verify_service.list_verifications()}
