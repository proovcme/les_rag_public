"""Ведомости объёмов работ (ВОР) из спецификаций — W11.1 (LES3_PLAN). Без LLM."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from proxy.security import require_user
from proxy.services.bor_service import build_bor, collect_spec_rows, generate_bor
from proxy.services.plan_fact_service import generate_plan_fact

router = APIRouter(prefix="/api/bor", tags=["bor"])

_STORAGE_ROOT = Path("storage/datasets")


@router.get("/{dataset_id}/preview")
async def bor_preview(dataset_id: str, limit: int = 50, _user=Depends(require_user)):
    """Свод ВОР по датасету в JSON (первые `limit` строк) — для UI и проверки."""
    rows = collect_spec_rows(dataset_id, storage_root=_STORAGE_ROOT)
    lines = build_bor(rows)
    return {
        "dataset_id": dataset_id,
        "source_rows": len(rows),
        "bor_lines": len(lines),
        "lines": [line.payload() for line in lines[:limit]],
    }


@router.post("/{dataset_id}/generate")
async def bor_generate(dataset_id: str, _user=Depends(require_user)):
    """Генерация xlsx-ВОР в storage/datasets/{id}/_bor/."""
    output_dir = _STORAGE_ROOT / dataset_id / "_bor"
    result = generate_bor(dataset_id, storage_root=_STORAGE_ROOT, output_dir=output_dir)
    if not result["bor_lines"]:
        raise HTTPException(404, f"В датасете {dataset_id} нет строк спецификаций/ведомостей (_parquet)")
    result.pop("lines", None)  # полный список — через /preview
    return result


@router.get("/{dataset_id}/download")
async def bor_download(dataset_id: str, _user=Depends(require_user)):
    """Последний сгенерированный xlsx-файл ВОР."""
    bor_dir = _STORAGE_ROOT / dataset_id / "_bor"
    files = sorted(bor_dir.glob("bor_*.xlsx")) if bor_dir.exists() else []
    if not files:
        raise HTTPException(404, "ВОР ещё не генерировалась — вызови POST /api/bor/{dataset_id}/generate")
    latest = files[-1]
    return FileResponse(
        latest,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=latest.name,
    )


# ── План/факт: ВОР ↔ журнал полевых объёмов (W11.2) ──

@router.get("/{dataset_id}/plan-fact")
async def plan_fact_preview(dataset_id: str, zahvatka: str = "", limit: int = 200, _user=Depends(require_user)):
    """Сверка плана (ВОР) и факта (confirmed-объёмы журнала) в JSON. Без LLM."""
    result = generate_plan_fact(dataset_id, storage_root=_STORAGE_ROOT, zahvatka=zahvatka)
    result["rows"] = result["rows"][:limit]
    return result


@router.post("/{dataset_id}/plan-fact/generate")
async def plan_fact_generate(dataset_id: str, zahvatka: str = "", _user=Depends(require_user)):
    """Генерация xlsx план/факт в storage/datasets/{id}/_bor/."""
    output_dir = _STORAGE_ROOT / dataset_id / "_bor"
    result = generate_plan_fact(dataset_id, storage_root=_STORAGE_ROOT, zahvatka=zahvatka, output_dir=output_dir)
    if not result["rows"]:
        raise HTTPException(404, f"Нет данных для план/факт по {dataset_id}: нужны ВОР (_parquet) и/или журнал объёмов")
    result.pop("rows", None)  # полный список — через GET /plan-fact
    return result


@router.get("/{dataset_id}/plan-fact/download")
async def plan_fact_download(dataset_id: str, _user=Depends(require_user)):
    """Последний сгенерированный xlsx план/факт."""
    bor_dir = _STORAGE_ROOT / dataset_id / "_bor"
    files = sorted(bor_dir.glob("plan_fact_*.xlsx")) if bor_dir.exists() else []
    if not files:
        raise HTTPException(404, "План/факт ещё не генерировался — вызови POST /api/bor/{dataset_id}/plan-fact/generate")
    latest = files[-1]
    return FileResponse(
        latest,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=latest.name,
    )
