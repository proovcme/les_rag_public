"""ФГИС ЦС — API ценовой базы: импорт «Сплит-формы» + exact-match lookup цены по коду.

Закрывает узкое место `table_query top-k не SQL` для автоценообразования ЛСР:
точный поиск сметной цены/индекса по коду ресурса из in-memory индекса поверх Parquet.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from proxy.security import require_user
from proxy.services import fgis_price_service as fps

router = APIRouter(prefix="/api/prices", tags=["prices"])


def _resolve_book(book: Optional[str]) -> Path:
    """Имя книги (stem) → путь к Parquet в data/price_base. Без имени — единственная."""
    books = fps.available_pricebooks()
    if not books:
        raise HTTPException(404, "Ценовых баз нет — импортируйте «Сплит-форму» через /api/prices/import")
    if book:
        for path in books:
            if Path(path).stem == book:
                return Path(path)
        raise HTTPException(404, f"Книга цен {book!r} не найдена")
    if len(books) > 1:
        names = ", ".join(Path(p).stem for p in books)
        raise HTTPException(400, f"Уточните book — доступно: {names}")
    return Path(books[0])


class PriceImport(BaseModel):
    xlsx_path: str
    name: str                       # имя книги (stem parquet), напр. spb_2kv2025
    region: Optional[str] = None
    quarter: Optional[str] = None


@router.get("/books")
async def prices_books(_user=Depends(require_user)):
    """Список доступных ценовых баз (книг)."""
    books = []
    for path in fps.available_pricebooks():
        books.append({"name": Path(path).stem, "path": path})
    return {"books": books}


@router.get("/lookup")
async def prices_lookup(
    code: str = Query(..., description="Код ресурса ФГИС ЦС, напр. 91.05.01-017"),
    book: Optional[str] = None,
    method: str = Query("index", pattern="^(index|base)$"),
    _user=Depends(require_user),
):
    """Точная цена по коду ресурса. method=index — текущая (база×индекс/прямая), base — базовая."""
    path = _resolve_book(book)
    pb = await asyncio.to_thread(fps.get_pricebook, str(path))
    rec = pb.lookup(code)
    if rec is None:
        return {"found": False, "code": code, "book": path.stem}
    return {
        "found": True,
        "book": path.stem,
        "region": pb.region,
        "quarter": pb.quarter,
        "method": method,
        "price": rec.get("price_current_eff") if method == "index" else rec.get("price_base"),
        "row": rec,
    }


@router.get("/search")
async def prices_search(
    q: str = Query(..., min_length=2, description="Подстрока наименования/кода"),
    book: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    _user=Depends(require_user),
):
    """Поиск позиций по наименованию — когда точный код неизвестен."""
    path = _resolve_book(book)
    pb = await asyncio.to_thread(fps.get_pricebook, str(path))
    hits = pb.search(q, limit=limit)
    return {"book": path.stem, "count": len(hits), "rows": hits}


@router.post("/import")
async def prices_import(req: PriceImport, _user=Depends(require_user)):
    """Импорт «Сплит-формы» xlsx → Parquet-книга цен в data/price_base/{name}.parquet."""
    src = Path(req.xlsx_path)
    if not src.is_file() or src.suffix.lower() not in (".xlsx", ".xls"):
        raise HTTPException(400, f"Не xlsx-файл: {req.xlsx_path}")
    out = fps.DEFAULT_PRICE_ROOT / f"{Path(req.name).name}.parquet"
    try:
        summary: dict[str, Any] = await asyncio.to_thread(
            fps.build_price_parquet, str(src), str(out),
            region=req.region, quarter=req.quarter,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    fps.get_pricebook.cache_clear()
    summary["name"] = out.stem
    return summary
