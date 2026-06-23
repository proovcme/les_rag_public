"""ЛСР — API сметных расчётов. Сейчас: коэффициент стеснённости (усложняющих условий).

Применяет коэф. к ОЗП/ЭМ позиций и пересчитывает ФОТ→НР→СП→Всего. 0 LLM (детерминированно).
Namespace `/api/lsr` — задел под движок сборки ЛСР (позиции→ресурсы→начисления→итоги).
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from fastapi import Query

from proxy.security import require_user
from proxy.services import gesn_service as gesn
from proxy.services import lsr_assembly_service as la
from proxy.services import stesnennost_service as st

router = APIRouter(prefix="/api/lsr", tags=["lsr"])


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
