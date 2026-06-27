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
from datetime import datetime, timezone
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


class DocReviewDecisionRequest(BaseModel):
    rule_id: str
    decision: str = "unset"                   # unset | confirmed | rejected | needs_more_evidence
    comment: Optional[str] = None


def _safe_dataset_dir(dataset_id: str) -> Path:
    safe = "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in str(dataset_id))[:160]
    return _OUT_DIR / (safe or "dataset")


def _decision_path(dataset_id: str) -> Path:
    return _safe_dataset_dir(dataset_id) / "human_decisions.json"


def _load_decisions(dataset_id: str) -> dict:
    path = _decision_path(dataset_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception:
        return {}
    decisions = payload.get("decisions") if isinstance(payload, dict) else None
    return decisions if isinstance(decisions, dict) else {}


def _save_decisions(dataset_id: str, decisions: dict) -> dict:
    out_dir = _safe_dataset_dir(dataset_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {"schema": "doc_review_human_decisions_v1", "dataset_id": dataset_id, "decisions": decisions}
    _decision_path(dataset_id).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


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
    decisions = _load_decisions(dataset_id)
    dr.apply_human_decisions(items, decisions)
    payload = dr.review_to_json(items, review_map)
    payload["dataset_id"] = dataset_id
    payload["human_decisions"] = decisions
    try:
        out_dir = _safe_dataset_dir(dataset_id)
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
    decisions = _load_decisions(dataset_id)
    dr.apply_human_decisions(items, decisions)
    if fmt == "json":
        payload = dr.review_to_json(items, review_map)
        payload["dataset_id"] = dataset_id
        payload["human_decisions"] = decisions
        return payload
    if fmt == "html":
        return Response(dr.review_to_html(items, review_map), media_type="text/html; charset=utf-8")
    out_dir = _safe_dataset_dir(dataset_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"doc_review_{int(time.time())}.xlsx"
    await asyncio.to_thread(dr.review_to_xlsx, items, out, review_map)
    return FileResponse(out, media_type=_XLSX_MEDIA, filename=out.name)


@router.get("/{dataset_id}/decisions")
async def doc_review_decisions(dataset_id: str, _user=Depends(require_user)):
    return {"schema": "doc_review_human_decisions_v1", "dataset_id": dataset_id,
            "decisions": _load_decisions(dataset_id)}


@router.post("/{dataset_id}/decision")
async def doc_review_set_decision(dataset_id: str, req: DocReviewDecisionRequest, _user=Depends(require_user)):
    rule_id = (req.rule_id or "").strip()
    decision = (req.decision or "unset").strip()
    if not rule_id:
        raise HTTPException(400, "rule_id required")
    if decision not in dr.HUMAN_DECISIONS:
        raise HTTPException(400, f"decision must be one of: {', '.join(sorted(dr.HUMAN_DECISIONS))}")
    decisions = _load_decisions(dataset_id)
    if decision == "unset":
        decisions.pop(rule_id, None)
    else:
        decisions[rule_id] = {
            "decision": decision,
            "comment": (req.comment or "").strip(),
            "decided_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    payload = _save_decisions(dataset_id, decisions)
    return {"ok": True, **payload}
