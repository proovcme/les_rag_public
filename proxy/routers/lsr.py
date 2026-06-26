"""ЛСР — API сметных расчётов. Сейчас: коэффициент стеснённости (усложняющих условий).

Применяет коэф. к ОЗП/ЭМ позиций и пересчитывает ФОТ→НР→СП→Всего. 0 LLM (детерминированно).
Namespace `/api/lsr` — задел под движок сборки ЛСР (позиции→ресурсы→начисления→итоги).
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from fastapi import Query

from proxy.security import require_user
from proxy.services import gesn_service as gesn
from proxy.services import lsr_assembly_service as la
from proxy.services import rim_lsr_trace_service as rim
from proxy.services import stesnennost_service as st

router = APIRouter(prefix="/api/lsr", tags=["lsr"])

_EXPORT_DIR = Path("storage/lsr")
_XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class StesnRequest(BaseModel):
    positions: list[dict[str, Any]]
    condition: Optional[str] = None
    k_ozp: Optional[float] = None
    k_em: Optional[float] = None


class AssembleRequest(BaseModel):
    positions: list[dict[str, Any]]
    book: Optional[str] = None                 # книга цен ФГИС ЦС (lookup ресурсов по коду)
    kac_prices: Optional[dict[str, float]] = None  # цены КАЦ {наименование: цена}
    condition: Optional[str] = None
    k_ozp: Optional[float] = None
    k_em: Optional[float] = None


class ExportRequest(AssembleRequest):
    fmt: str = "xlsx"                         # xlsx | csv
    title: Optional[str] = None


class RimTraceRequest(BaseModel):
    position: dict[str, Any]                  # одна позиция ЛСР: code ГЭСН + qty (+ опц. resources/nr_pct/sp_pct)
    book: Optional[str] = None                # книга цен ФГИС ЦС
    kac_prices: Optional[dict[str, float]] = None
    k_ozp: Optional[float] = None
    k_em: Optional[float] = None
    coefficient_basis: Optional[str] = None


@router.get("/stesnennost/conditions")
async def stesn_conditions(_user=Depends(require_user)):
    """Каталог условий стеснённости (коэф. к ОЗП/ЭМ) — из config/domain/stesnennost.yaml."""
    return {"conditions": await asyncio.to_thread(st.list_conditions)}


@router.post("/stesnennost/apply")
async def stesn_apply(req: StesnRequest, _user=Depends(require_user)):
    """Применить стеснённость к позициям: по условию каталога или явным k_ozp/k_em."""
    try:
        return await asyncio.to_thread(
            st.apply, req.positions,
            condition=req.condition, k_ozp=req.k_ozp, k_em=req.k_em,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/gesn")
async def gesn_list(_user=Depends(require_user)):
    """Каталог норм ГЭСН (семя) — код/наименование/единица/число ресурсов."""
    return {"norms": await asyncio.to_thread(gesn.list_norms)}


@router.get("/gesn/{code}/expand")
async def gesn_expand(code: str, qty: float = Query(1.0), _user=Depends(require_user)):
    """Норма ГЭСН + объём → строки ресурсов (расход × объём)."""
    lines = await asyncio.to_thread(gesn.expand_position, code, qty)
    if lines is None:
        raise HTTPException(404, f"Норма ГЭСН {code!r} не найдена")
    return {"code": code, "qty": qty, "resources": lines}


@router.post("/assemble")
async def lsr_assemble(req: AssembleRequest, _user=Depends(require_user)):
    """Собрать ЛСР из позиций: ресурсы→цены (ФГИС ЦС/КАЦ)→стеснённость→НР/СП→Всего→свод."""
    try:
        return await asyncio.to_thread(
            la.assemble, req.positions,
            book=req.book, kac_prices=req.kac_prices,
            condition=req.condition, k_ozp=req.k_ozp, k_em=req.k_em,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/rim-trace")
async def lsr_rim_trace(req: RimTraceRequest, _user=Depends(require_user)):
    """РИМ-трасса ОДНОЙ позиции ЛСР: доказательные строки по графам Приложения 3 к 421/пр
    (происхождение цены fgis_current/base_index/manual/kac/missing). Read-only evidence-слой —
    контракт /assemble НЕ меняется (handoff Codex, шаг #1). 0 LLM: код считает, missing виден."""
    try:
        pricebook = await asyncio.to_thread(la._resolve_book, req.book)
        return await asyncio.to_thread(
            rim.build_position_trace, req.position,
            pricebook=pricebook,
            kac_map=req.kac_prices,
            k_ozp=(req.k_ozp if req.k_ozp is not None else 1.0),
            k_em=(req.k_em if req.k_em is not None else 1.0),
            coefficient_basis=(req.coefficient_basis or ""),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/export")
async def lsr_export(req: ExportRequest, _user=Depends(require_user)):
    """Собрать ЛСР и сохранить CSV/XLSX-файл для скачивания."""
    fmt = (req.fmt or "xlsx").lower()
    if fmt not in {"xlsx", "csv"}:
        raise HTTPException(400, "fmt должен быть xlsx или csv")
    try:
        result = await asyncio.to_thread(
            la.assemble, req.positions,
            book=req.book, kac_prices=req.kac_prices,
            condition=req.condition, k_ozp=req.k_ozp, k_em=req.k_em,
        )
        _EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        name = f"lsr_{int(time.time())}.{fmt}"
        out = _EXPORT_DIR / name
        await asyncio.to_thread(
            la.export_assembled,
            result,
            out,
            fmt=fmt,
            title=req.title or "Локальный сметный расчёт",
        )
        return {
            "summary": result["summary"],
            "path": str(out),
            "download": f"/api/lsr/download?path={name}",
        }
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/download")
async def lsr_download(path: str = Query(...), _user=Depends(require_user)):
    """Скачать последнюю/указанную выгрузку ЛСР."""
    out_dir = _EXPORT_DIR.resolve()
    target = (out_dir / Path(path).name).resolve()
    if out_dir not in target.parents or not target.is_file():
        raise HTTPException(404, "Файл не найден")
    media = _XLSX_MEDIA if target.suffix.lower() == ".xlsx" else "text/csv; charset=utf-8"
    return FileResponse(target, media_type=media, filename=target.name)
