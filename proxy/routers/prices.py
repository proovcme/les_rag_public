"""ФГИС ЦС — API ценовой базы: импорт «Сплит-формы» + exact-match lookup цены по коду.

Закрывает узкое место `table_query top-k не SQL` для автоценообразования ЛСР:
точный поиск сметной цены/индекса по коду ресурса из in-memory индекса поверх Parquet.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from proxy.security import require_user
from proxy.services import etm_price_service as etm
from proxy.services import fgis_price_fetch_service as pf
from proxy.services import fgis_price_service as fps

router = APIRouter(prefix="/api/prices", tags=["prices"])


def _resolve_book(book: Optional[str]) -> Path:
    """Имя книги (stem) → путь к Parquet в data/price_base. Без имени — системный дефолт."""
    path = fps.resolve_pricebook_path(book, allow_scratch=bool(book))
    if path:
        return Path(path)
    books = fps.available_pricebooks()
    if not books:
        raise HTTPException(404, "Ценовых баз нет — импортируйте «Сплит-форму» через /api/prices/import")
    if book:
        raise HTTPException(404, f"Книга цен {book!r} не найдена")
    raise HTTPException(404, "Системная книга цен не найдена")


class PriceImport(BaseModel):
    xlsx_path: str
    name: str                       # имя книги (stem parquet), напр. spb_2kv2025
    region: Optional[str] = None
    quarter: Optional[str] = None


class PriceLookupBatch(BaseModel):
    codes: list[str] = Field(min_length=1, max_length=500)
    book: Optional[str] = None
    method: str = Field(default="index", pattern="^(index|base)$")

    @field_validator("codes")
    @classmethod
    def normalize_codes(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for raw in values:
            code = str(raw or "").strip()
            if not code:
                raise ValueError("Пустой код ресурса")
            if len(code) > 120:
                raise ValueError("Код ресурса слишком длинный")
            if code not in seen:
                result.append(code)
                seen.add(code)
        return result


class EtmPriceItem(BaseModel):
    code: str = Field(min_length=1, max_length=120)
    material: str = Field(min_length=1, max_length=500)
    unit: str = Field(min_length=1, max_length=40)


class EtmPriceLookupBatch(BaseModel):
    items: list[EtmPriceItem] = Field(min_length=1, max_length=500)
    code_type: str = Field(default="etm", pattern="^(cli|etm|mnf)$")
    manufacturer_code: Optional[str] = Field(default=None, max_length=120)
    price_field: str = Field(
        default="pricewnds",
        pattern="^(price|pricewnds|price_tarif|price_retail)$",
    )


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


@router.post("/lookup-batch")
async def prices_lookup_batch(req: PriceLookupBatch, _user=Depends(require_user)):
    """Одна загрузка книги и один пакет точных цен для расчётного хода модели."""
    path = _resolve_book(req.book)
    pb = await asyncio.to_thread(fps.get_pricebook, str(path))
    records = await asyncio.to_thread(pb.lookup_many, req.codes)
    rows: list[dict[str, Any]] = []
    found = 0
    for code in req.codes:
        rec = records.get(code)
        if rec is None:
            rows.append({"found": False, "code": code})
            continue
        found += 1
        rows.append(
            {
                "found": True,
                "code": code,
                "price": rec.get("price_current_eff") if req.method == "index" else rec.get("price_base"),
                "row": rec,
            }
        )
    return {
        "schema": "fgis_price_lookup_batch_v1",
        "book": path.stem,
        "region": pb.region,
        "quarter": pb.quarter,
        "method": req.method,
        "requested": len(req.codes),
        "found": found,
        "missing": len(req.codes) - found,
        "rows": rows,
    }


@router.get("/etm/status")
async def prices_etm_status(_user=Depends(require_user)):
    """Report ETM readiness without exposing credentials or a live session."""
    return etm.configuration_status()


@router.post("/etm/lookup-batch")
async def prices_etm_lookup_batch(
    req: EtmPriceLookupBatch,
    _user=Depends(require_user),
):
    """Return provenance-bearing quotes; material selection remains model-owned."""
    try:
        return await asyncio.to_thread(
            etm.get_client().collect_quotes,
            [item.model_dump() for item in req.items],
            code_type=req.code_type,
            manufacturer_code=req.manufacturer_code,
            price_field=req.price_field,
        )
    except etm.EtmNotConfiguredError as error:
        raise HTTPException(503, str(error)) from error
    except etm.EtmPriceError as error:
        raise HTTPException(502, str(error)) from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@router.get("/search")
async def prices_search(
    q: str = Query(..., min_length=2, description="Подстрока наименования/кода"),
    book: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    _user=Depends(require_user),
):
    """Model-visible кандидаты ФГИС по коду/наименованию; endpoint не выбирает ресурс."""
    path = _resolve_book(book)
    pb = await asyncio.to_thread(fps.get_pricebook, str(path))
    hits = pb.browse(q, limit=limit)
    return {
        "schema": "fgis_price_browse_v1",
        "book": path.stem,
        "region": pb.region,
        "quarter": pb.quarter,
        "selection_owner": "model_or_user",
        "count": len(hits),
        "rows": hits,
    }


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


# ─────────────────────────────────────────
# НАПОЛНЕНИЕ из ФГИС ЦС (канал — только для обновления базы, недоверенный)
# ─────────────────────────────────────────

class PriceUpdate(BaseModel):
    subject: str = "Петербург"      # подстрока субъекта РФ
    quarter: str = "2 квартал 2025"  # подстрока периода
    name: str = "spb_2kv2025"        # stem Parquet-книги


@router.get("/sources/subjects")
async def prices_sources_subjects(_user=Depends(require_user)):
    """Субъекты РФ из ФГИС ЦС (открытые метаданные). Сетевой запрос — короткий таймаут."""
    try:
        subjects = await asyncio.to_thread(pf.list_subjects)
    except Exception as e:                           # noqa: BLE001 — недоверенный канал
        raise HTTPException(502, f"ФГИС ЦС недоступен: {e}")
    return {"count": len(subjects), "subjects": subjects}


@router.get("/sources/periods")
async def prices_sources_periods(
    subject: str = Query(..., description="Субъект РФ (подстрока, напр. 'Петербург')"),
    _user=Depends(require_user),
):
    """Доступные кварталы зоны субъекта из ФГИС ЦС (для выбора при обновлении)."""
    def _periods() -> dict[str, Any]:
        subj = pf.resolve_subject(subject)
        if not subj:
            return {"error": f"субъект {subject!r} не найден"}
        zones = pf.price_zones(subj["id"])
        if not zones:
            return {"error": f"нет зон у {subj['name']!r}"}
        return {"subject": subj, "zone": zones[0], "periods": pf.periods(zones[0]["id"])}
    try:
        res = await asyncio.to_thread(_periods)
    except Exception as e:                           # noqa: BLE001
        raise HTTPException(502, f"ФГИС ЦС недоступен: {e}")
    if "error" in res:
        raise HTTPException(404, res["error"])
    return res


@router.post("/update")
async def prices_update(req: PriceUpdate, _user=Depends(require_user)):
    """Обновить локальную книгу цен из ФГИС ЦС (Сплит-форма → Parquet).

    Канал-безопасно: сбой → graceful 502, локальная база не повреждается.
    Источник — ТОЛЬКО файл-выгрузка (per-code price API закрыт, 401).
    """
    res = await asyncio.to_thread(
        pf.import_region, subject=req.subject, quarter=req.quarter, name=req.name,
    )
    if not res.get("ok"):
        raise HTTPException(502, f"ФГИС ЦС: {res.get('stage')} — {res.get('note')}")
    return res


@router.get("/needs")
async def prices_needs(
    code: str = Query(..., description="Код ресурса ФГИС ЦС"),
    book: Optional[str] = None,
    refresh: bool = Query(False, description="Промах → добрать книгу из ФГИС ЦС (наполнение)"),
    _user=Depends(require_user),
):
    """Локаль-первый вердикт по коду: ценится локально / нужен добор / корректный КАЦ.

    refresh=False (дефолт) — query-time, канал НЕ дёргаем. refresh=True — наполнение.
    """
    res = await asyncio.to_thread(
        pf.lookup_local_first, code, book=book, refresh_on_miss=refresh,
    )
    return res
