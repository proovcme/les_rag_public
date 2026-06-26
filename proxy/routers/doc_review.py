"""СПДС-нормоконтроль (doc-review) API — Phase 4. RAG-led review поверх review-map + document_set_model.

  GET  /api/doc-review/rulepacks             — доступные review-map
  POST /api/doc-review/{dataset_id}/run      — прогон комплекта → review-items + summary
  GET  /api/doc-review/{dataset_id}/download — отчёт xlsx|json|html

Тонкий слой над doc_review_service (вся логика и инвариант «движок не финализирует» — там).
Контракт нормоконтроля v1 (/api/normcontrol) НЕ трогается — это следующий вертикальный слой.
Имена файлов берутся из MetaDB (работает и для in-place датасетов), ведомость — из Parquet.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from proxy.security import require_user
from proxy.services import doc_review_service as dr
from proxy.services.normcontrol_review_map_service import list_review_maps, load_review_map

router = APIRouter(prefix="/api/doc-review", tags=["doc-review"])

_OUT_DIR = Path("storage/doc_review")
_STORAGE_ROOT = Path("storage/datasets")
_XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class DocReviewRequest(BaseModel):
    rulepack: str = "gost_r_21_101_2026"
    mode: str = "rag_review"
    project_stage: Optional[str] = None       # PD | RD | unknown
    discipline: Optional[str] = None          # auto | AR | KR | OV | ...
    strictness: str = "normal"                # normal | strict


async def _build_review(dataset_id: str, rulepack: str):
    # Оркестрация — в сервисе (dr.review_dataset): тот же путь, что у чат-инструмента doc_review.
    try:
        return await asyncio.to_thread(dr.review_dataset, dataset_id, rulepack=rulepack)
    except ValueError as e:
        if str(e) == "no_documents":
            raise HTTPException(404, f"в датасете {dataset_id} нет документов (MetaDB)")
        raise HTTPException(400, f"rulepack: {e}")
    except FileNotFoundError as e:
        raise HTTPException(400, f"rulepack: {e}")


@router.get("/rulepacks")
async def doc_review_rulepacks(_user=Depends(require_user)):
    out = []
    for name in list_review_maps():
        try:
            m = load_review_map(name)
            out.append({"name": m.name, "standard": m.standard, "title": m.title,
                        "version": m.version, "supersedes": m.supersedes, "targets": len(m.targets)})
        except Exception as e:  # noqa: BLE001
            out.append({"name": name, "error": str(e)})
    return {"rulepacks": out}


@router.post("/{dataset_id}/run")
async def doc_review_run(dataset_id: str, req: DocReviewRequest, _user=Depends(require_user)):
    """RAG-led review комплекта по review-map. Статусы — proposed issues/evidence; финал ставит инженер."""
    review_map, items = await _build_review(dataset_id, req.rulepack)
    payload = dr.review_to_json(items, review_map)
    payload["dataset_id"] = dataset_id
    try:
        out_dir = _OUT_DIR / dataset_id
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"doc_review_{int(time.time())}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return payload


@router.get("/{dataset_id}/download")
async def doc_review_download(dataset_id: str, fmt: str = Query("xlsx"),
                              rulepack: str = Query("gost_r_21_101_2026"), _user=Depends(require_user)):
    """Отчёт по текущему комплекту: xlsx | json | html (перестраивается детерминированно)."""
    fmt = (fmt or "xlsx").lower()
    if fmt not in {"xlsx", "json", "html"}:
        raise HTTPException(400, "fmt: xlsx | json | html")
    review_map, items = await _build_review(dataset_id, rulepack)
    if fmt == "json":
        return dr.review_to_json(items, review_map)
    if fmt == "html":
        return Response(dr.review_to_html(items, review_map), media_type="text/html; charset=utf-8")
    out_dir = _OUT_DIR / dataset_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"doc_review_{int(time.time())}.xlsx"
    await asyncio.to_thread(dr.review_to_xlsx, items, out, review_map)
    return FileResponse(out, media_type=_XLSX_MEDIA, filename=out.name)
