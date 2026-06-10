"""Формальный нормоконтроль комплекта — W13.1 (LES3_PLAN). Без LLM."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from proxy.security import require_user
from proxy.services.normcontrol_service import run_normcontrol

router = APIRouter(prefix="/api/normcontrol", tags=["normcontrol"])

_STORAGE_ROOT = Path("storage/datasets")


@router.post("/{dataset_id}/run")
async def normcontrol_run(dataset_id: str, _user=Depends(require_user)):
    """Прогон формальных проверок (NK-01…NK-04) по файлам датасета, отчёт в _normcontrol/."""
    files_dir = _STORAGE_ROOT / dataset_id
    if not files_dir.exists():
        raise HTTPException(404, f"Датасет {dataset_id} не найден в storage")
    result = run_normcontrol(
        dataset_id,
        files_dir=files_dir,
        storage_root=_STORAGE_ROOT,
        output_dir=files_dir / "_normcontrol",
    )
    if not result["files_checked"]:
        raise HTTPException(404, f"В датасете {dataset_id} нет PDF-файлов для проверки")
    result["findings"] = result["findings"][:200]  # полный список — в xlsx
    return result


@router.get("/{dataset_id}/download")
async def normcontrol_download(dataset_id: str, _user=Depends(require_user)):
    """Последний xlsx-отчёт нормоконтроля."""
    report_dir = _STORAGE_ROOT / dataset_id / "_normcontrol"
    files = sorted(report_dir.glob("normcontrol_*.xlsx")) if report_dir.exists() else []
    if not files:
        raise HTTPException(404, "Отчёт ещё не сформирован — вызови POST /api/normcontrol/{dataset_id}/run")
    latest = files[-1]
    return FileResponse(
        latest,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=latest.name,
    )
