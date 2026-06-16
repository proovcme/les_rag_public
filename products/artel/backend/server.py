"""АРТЕЛЬ Фабрика семейств — локальный бэкенд (FastAPI, тонкая обёртка над сервисом).

Хаб пакета: морда (Electron) и Revit-плагин ходят сюда по `127.0.0.1:5057`.
Логика — в `tools/artel_backend_service` (тестируется офлайн). Запуск:

    uv run uvicorn products.artel.backend.server:app --host 127.0.0.1 --port 5057

Дизайн: products/artel/docs/family-factory-package.md
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

try:
    from tools import artel_backend_service as service
except ImportError:  # pragma: no cover
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from tools import artel_backend_service as service

app = FastAPI(title="ARTEL Family Factory", version="0.1.0")
# Локальная морда (Electron) ходит с file:// / localhost — CORS открыт для localhost.
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


class TableExtractIn(BaseModel):
    matrix: list[list[Any]]
    name: str
    category: str = "Specialty Equipment"


class PdfExtractIn(BaseModel):
    path: str
    name: str
    category: str = "Specialty Equipment"


class SpecUpdateIn(BaseModel):
    spec: Optional[dict[str, Any]] = None
    geometry: Optional[dict[str, Any]] = None


class JobIn(BaseModel):
    spec_id: int


class ReportIn(BaseModel):
    report: dict[str, Any]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "product": "ARTEL Family Factory"}


# ── Извлечение / спецификации ───────────────────────────────────────────────

@app.post("/api/extract/table")
def extract_table(req: TableExtractIn):
    rec = service.extract_spec_from_table(req.matrix, req.name, req.category)
    if rec is None:
        raise HTTPException(422, "Габаритная таблица не распознана")
    return rec


@app.post("/api/extract/pdf")
def extract_pdf(req: PdfExtractIn):
    if not Path(req.path).exists():
        raise HTTPException(400, "PDF не найден")
    rec = service.extract_spec_from_pdf(req.path, req.name, req.category)
    if rec is None:
        raise HTTPException(422, "Габаритная таблица в PDF не распознана")
    return rec


@app.get("/api/specs")
def list_specs():
    return service.list_specs()


@app.get("/api/specs/{spec_id}")
def get_spec(spec_id: int):
    rec = service.get_spec(spec_id)
    if not rec:
        raise HTTPException(404, "Спецификация не найдена")
    return rec


@app.put("/api/specs/{spec_id}")
def update_spec(spec_id: int, req: SpecUpdateIn):
    return service.update_spec(spec_id, req.spec, req.geometry)


@app.post("/api/specs/{spec_id}/approve")
def approve_spec(spec_id: int):
    return service.approve_spec(spec_id)


@app.post("/api/specs/{spec_id}/plan")
def compile_plan(spec_id: int):
    try:
        return service.compile_plan(spec_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


# ── Очередь заданий для Revit-плагина ───────────────────────────────────────

@app.post("/api/revit/jobs")
def create_job(req: JobIn):
    try:
        return service.create_job(req.spec_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@app.get("/api/revit/jobs/next")
def next_job():
    """Плагин на Idling поллит задание; null если очередь пуста."""
    return service.next_job()


@app.post("/api/revit/jobs/{job_id}/report")
def submit_report(job_id: int, req: ReportIn):
    return service.submit_report(job_id, req.report)


@app.get("/api/revit/jobs")
def list_jobs():
    return service.list_jobs()


@app.get("/api/revit/jobs/{job_id}")
def get_job(job_id: int):
    rec = service.get_job(job_id)
    if not rec:
        raise HTTPException(404, "Задание не найдено")
    return rec
