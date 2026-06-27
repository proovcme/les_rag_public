"""Ведомости объёмов работ (ВОР) из спецификаций — W11.1 (LES3_PLAN). Без LLM."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from proxy.security import require_user
from proxy.services.bor_service import build_bor, collect_spec_rows, generate_bor
from proxy.services.plan_fact_service import generate_plan_fact
from proxy.services.reconcile_service import reconcile_datasets
from proxy.services.spec_to_bor_service import generate_spec_bor

router = APIRouter(prefix="/api/bor", tags=["bor"])

_STORAGE_ROOT = Path("storage/datasets")
_RECONCILE_DIR = Path("storage/reconcile")


def _parse_datasets(datasets: str) -> list[str]:
    ids = [d.strip() for d in (datasets or "").split(",") if d.strip()]
    if not ids:
        raise HTTPException(400, "Укажи датасеты для сверки: ?datasets=id1,id2,...")
    return ids


def _dataset_names(ids: list[str]) -> dict[str, str]:
    """id→имя датасета из метабазы (для читаемых ярлыков оси «по документу»)."""
    import sqlite3

    from backend.rag_config import rag_meta_db_path

    names: dict[str, str] = {}
    try:
        con = sqlite3.connect(rag_meta_db_path())
        try:
            placeholders = ",".join("?" * len(ids))
            for did, name in con.execute(
                f"SELECT id, name FROM datasets WHERE id IN ({placeholders})", ids
            ):
                names[str(did)] = str(name or did)
        finally:
            con.close()
    except Exception:  # имя — косметика; без него ось «по документу» покажет id
        pass
    return names


# ── Сверка ВОР↔КС-2↔смета↔ИД по позициям (W11.4) ──
# Объявлены ДО параметрических /{dataset_id}/* — иначе FastAPI сматчит dataset_id="reconcile".

@router.get("/reconcile")
async def reconcile_preview(datasets: str, limit: int = 500, by: str = "dataset", _user=Depends(require_user)):
    """Сверка количеств в JSON. Без LLM.

    `datasets` — id датасетов через запятую. `by="dataset"` (по умолчанию) сравнивает
    документы между собой (ведомость↔акт), `by="doc_type"` — группирует по типу.
    """
    ids = _parse_datasets(datasets)
    result = reconcile_datasets(ids, storage_root=_STORAGE_ROOT, by=by, dataset_names=_dataset_names(ids))
    if not result["rows"]:
        raise HTTPException(404, "Нет табличных позиций для сверки в указанных датасетах (нужен _parquet)")
    result["rows"] = result["rows"][:limit]
    return result


@router.post("/reconcile/generate")
async def reconcile_generate(datasets: str, by: str = "dataset", _user=Depends(require_user)):
    """Генерация xlsx-сверки в storage/reconcile/."""
    ids = _parse_datasets(datasets)
    result = reconcile_datasets(
        ids, storage_root=_STORAGE_ROOT, output_dir=_RECONCILE_DIR, by=by, dataset_names=_dataset_names(ids)
    )
    if not result["rows"]:
        raise HTTPException(404, "Нет табличных позиций для сверки в указанных датасетах (нужен _parquet)")
    result.pop("rows", None)  # полный список — через GET /reconcile
    return result


@router.get("/reconcile/download")
async def reconcile_download(_user=Depends(require_user)):
    """Последний сгенерированный xlsx-файл сверки."""
    files = sorted(_RECONCILE_DIR.glob("reconcile_*.xlsx")) if _RECONCILE_DIR.exists() else []
    if not files:
        raise HTTPException(404, "Сверка ещё не генерировалась — вызови POST /api/bor/reconcile/generate")
    latest = files[-1]
    return FileResponse(
        latest,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=latest.name,
    )


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


# ── ВОР из спецификации (форма 9, ГОСТ 21.110) — работы из позиций (W11.10) ──

@router.get("/{dataset_id}/from-spec")
async def spec_bor_preview(dataset_id: str, limit: int = 300, _user=Depends(require_user)):
    """Превью ВОР работ из спецификации (Ф9) в JSON. Алгоритм — docs/ALGO-spec-to-bor.md. Без LLM."""
    result = generate_spec_bor(dataset_id, storage_root=_STORAGE_ROOT)
    result["lines"] = result["lines"][:limit]
    return result


@router.post("/{dataset_id}/from-spec/generate")
async def spec_bor_generate(dataset_id: str, _user=Depends(require_user)):
    """Генерация xlsx ВОР-из-спецификации в storage/datasets/{id}/_bor/."""
    output_dir = _STORAGE_ROOT / dataset_id / "_bor"
    result = generate_spec_bor(dataset_id, storage_root=_STORAGE_ROOT, output_dir=output_dir)
    if not result["bor_lines"]:
        raise HTTPException(404, f"В датасете {dataset_id} нет строк спецификации (_parquet SPEC/VEDOMOST)")
    result.pop("lines", None)
    return result


@router.get("/{dataset_id}/from-spec/download")
async def spec_bor_download(dataset_id: str, _user=Depends(require_user)):
    """Последний сгенерированный xlsx ВОР-из-спецификации."""
    bor_dir = _STORAGE_ROOT / dataset_id / "_bor"
    files = sorted(bor_dir.glob("specbor_*.xlsx")) if bor_dir.exists() else []
    if not files:
        raise HTTPException(404, "ВОР-из-спецификации ещё не генерировалась — POST /api/bor/{id}/from-spec/generate")
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
