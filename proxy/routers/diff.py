"""Дифф CAD/BIM-импортов и текстовых документов — W12.1 (LES3_PLAN). Без LLM."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from proxy.security import require_user
from proxy.services.cad_bim_graph import CAD_BIM_DB_PATH
from proxy.services.diff_service import diff_cad_imports, diff_texts

router = APIRouter(prefix="/api/diff", tags=["diff"])


@router.get("/cad-bim")
async def cad_bim_diff(import_a: str, import_b: str, _user=Depends(require_user)):
    """Сравнение двух импортов модели: добавлено/удалено/изменено по source_id."""
    if not CAD_BIM_DB_PATH.exists():
        raise HTTPException(404, "Граф CAD/BIM пуст — нет ни одного импорта")
    try:
        with sqlite3.connect(CAD_BIM_DB_PATH) as conn:
            known = {
                row[0]
                for row in conn.execute(
                    "SELECT id FROM cad_bim_imports WHERE id IN (?, ?)",
                    (import_a, import_b),
                )
            }
    except sqlite3.Error as db_err:
        raise HTTPException(500, f"Граф CAD/BIM недоступен: {db_err}")
    missing = {import_a, import_b} - known
    if missing:
        raise HTTPException(404, f"Импорт(ы) не найдены: {', '.join(sorted(missing))}")
    return diff_cad_imports(import_a, import_b).payload()


class TextDiffRequest(BaseModel):
    text_a: str = Field(min_length=1)
    text_b: str = Field(min_length=1)
    label_a: str = "A"
    label_b: str = "B"


@router.post("/text")
async def text_diff(req: TextDiffRequest, _user=Depends(require_user)):
    """Структурный дифф двух ревизий документа: по пунктам ГОСТ/СП + difflib."""
    return diff_texts(req.text_a, req.text_b, label_a=req.label_a, label_b=req.label_b).payload()
