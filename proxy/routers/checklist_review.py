"""Checklist-review API (Glorax, Phase 4, T4.1) — тонкий роутер над checklist_review_service.

  GET  /api/checklist-review/templates                          — доступные templates
  POST /api/checklist-review/{dataset_id}/run                    — прогон -> durable run_id + summary
  GET  /api/checklist-review/{dataset_id}/runs/{run_id}          — полный результат (items)
  GET  /api/checklist-review/{dataset_id}/runs/{run_id}/download — отчёт json/xlsx/html (T4.2:
                                                                    checklist_report_service)
  POST /api/checklist-review/{dataset_id}/runs/{run_id}/items/{item_id}/decision — human decision

Паттерн — зеркало ``proxy/routers/doc_review.py`` (см. ``_safe_dataset_dir``/persist decisions):
вся логика движка — в ``checklist_review_service`` (T2.1-T3.2), роутер только оркестрирует +
персистит на диск. Синхронный run (T4.1 scope): background job для items>50 — TODO, отдельная
подзадача (T4.x), см. implementation_plan.md §5 "Run на 500+ пунктов — background job через
job_service". Параметр ``limit`` обязателен для smoke на большом template уже сейчас.

Persist-слой (файловая система, JSON, без БД — тот же паттерн, что doc_review human_decisions):
  storage/checklist_review/{safe_dataset_id}/{run_id}/run.json        — schema checklist_review_v1
  storage/checklist_review/{safe_dataset_id}/{run_id}/decisions.json  — schema
      checklist_review_human_decisions_v1, {item_id: {human_answer, human_note, decided_at}}

``run_id`` = ``uuid4().hex`` (durable, генерируется роутером — сервис не знает о run_id).
При чтении run'а (``GET .../runs/{run_id}``) decisions применяются поверх сохранённых items:
human_answer сильнее suggested_answer (docs/CHECKLIST_REVIEW_PD_TASK.md §5 правило) — добавляется
блок ``summary.human`` (yes/no/not_required/unset counts) поверх исходного summary движка.
"""

from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from backend.runtime_paths import mutable_path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, field_validator

from proxy.security import require_user
from proxy.services.checklist_report_service import report_to_html, report_to_xlsx
from proxy.services.checklist_review_service import (
    default_doc_review_provider,
    default_inventory_provider,
    default_search_provider,
    default_workbook_provider,
    load_checklist_template,
    run_checklist_review,
)

router = APIRouter(prefix="/api/checklist-review", tags=["checklist-review"])

_OUT_DIR = mutable_path("storage/checklist_review")

_HUMAN_ANSWERS = {"yes", "no", "not_required", "unset"}


class ChecklistRunRequest(BaseModel):
    template: str
    source_dataset_ids: list[str] = []
    discipline: Optional[str] = None
    limit: Optional[int] = None


class ChecklistDecisionRequest(BaseModel):
    human_answer: str = "unset"
    human_note: Optional[str] = ""

    @field_validator("human_answer")
    @classmethod
    def _validate_answer(cls, v: str) -> str:
        if v not in _HUMAN_ANSWERS:
            raise ValueError(f"human_answer must be one of: {', '.join(sorted(_HUMAN_ANSWERS))}")
        return v


# ── path-guard (по образцу _safe_dataset_dir в doc_review.py) ──────────────────────────────


def _safe_segment(value: str) -> str:
    """Санитизирует один сегмент пути: только alnum/._- , без `..`/слэшей. Пустой/подозрительный
    ввод -> ValueError (роутер конвертирует в 400), НЕ молчаливая подмена на дефолт — иначе
    dataset_id="../../etc" тихо получил бы валидную (но чужую) директорию "etc"."""
    raw = str(value or "")
    if not raw or raw in (".", "..") or "/" in raw or "\\" in raw:
        raise ValueError("invalid path segment")
    safe = "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in raw)[:160]
    if not safe or safe in (".", ".."):
        raise ValueError("invalid path segment")
    return safe


def _safe_dataset_dir(dataset_id: str) -> Path:
    try:
        safe = _safe_segment(dataset_id)
    except ValueError:
        raise HTTPException(400, "invalid dataset_id")
    return _OUT_DIR / safe


def _safe_run_dir(dataset_id: str, run_id: str) -> Path:
    try:
        safe_run = _safe_segment(run_id)
    except ValueError:
        raise HTTPException(400, "invalid run_id")
    return _safe_dataset_dir(dataset_id) / safe_run


def _run_path(dataset_id: str, run_id: str) -> Path:
    return _safe_run_dir(dataset_id, run_id) / "run.json"


# Review-fix 2026-07-07 (гонка read-modify-write decisions.json): последовательные
# decision'ы разных items одного run из параллельных запросов могли терять записи
# (last-write-wins всем файлом). Однопроцессный uvicorn => threading.Lock достаточен;
# запись атомарна через tmp+os.replace.
_DECISIONS_LOCK = threading.Lock()


def _decisions_path(dataset_id: str, run_id: str) -> Path:
    return _safe_run_dir(dataset_id, run_id) / "decisions.json"


# ── persist: run.json ───────────────────────────────────────────────────────────────────────


def _save_run(dataset_id: str, run_id: str, payload: dict) -> None:
    out_dir = _safe_run_dir(dataset_id, run_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    _run_path(dataset_id, run_id).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_run(dataset_id: str, run_id: str) -> dict:
    path = _run_path(dataset_id, run_id)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise HTTPException(404, f"run {run_id} не найден для датасета {dataset_id}")
    except Exception:
        raise HTTPException(404, f"run {run_id} повреждён или не найден")


# ── persist: decisions.json (schema checklist_review_human_decisions_v1) ───────────────────


def _load_decisions(dataset_id: str, run_id: str) -> dict:
    path = _decisions_path(dataset_id, run_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception:
        return {}
    decisions = payload.get("decisions") if isinstance(payload, dict) else None
    return decisions if isinstance(decisions, dict) else {}


def _save_decisions(dataset_id: str, run_id: str, decisions: dict) -> dict:
    out_dir = _safe_run_dir(dataset_id, run_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "checklist_review_human_decisions_v1",
        "dataset_id": dataset_id,
        "run_id": run_id,
        "decisions": decisions,
    }
    target = _decisions_path(dataset_id, run_id)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    import os
    os.replace(tmp, target)  # атомарная подмена — читатель не увидит полфайла
    return payload


def _apply_decisions(result: dict, decisions: dict) -> dict:
    """Применяет human-решения поверх сохранённого run'а: human_answer сильнее suggested_answer
    (docs/CHECKLIST_REVIEW_PD_TASK.md §5) — не переписывает suggested_answer/status движка (это
    были бы результаты автопроверки), а заполняет human_answer/human_note на item'е + добавляет
    сводный блок summary.human (yes/no/not_required/unset counts) для UI/отчётов."""
    human_counts = {"yes": 0, "no": 0, "not_required": 0, "unset": 0}
    for item in result.get("items", []):
        decision = decisions.get(item.get("item_id"))
        if decision:
            item["human_answer"] = decision.get("human_answer", "unset")
            item["human_note"] = decision.get("human_note", "")
            item["human_decision"] = (
                "unset" if item["human_answer"] == "unset" else "human_decided"
            )
        answer = item.get("human_answer", "unset")
        if answer not in human_counts:
            answer = "unset"
        human_counts[answer] += 1
    summary = result.setdefault("summary", {})
    summary["human"] = human_counts
    return result


# ── эндпоинты ────────────────────────────────────────────────────────────────────────────────


@router.get("/templates")
async def checklist_review_templates(_user=Depends(require_user)):
    from proxy.services.checklist_review_service import _CHECKLISTS_DIR

    out = []
    if _CHECKLISTS_DIR.exists():
        for path in sorted(_CHECKLISTS_DIR.glob("*.json")):
            name = path.stem
            if name.endswith("_overrides"):
                continue
            try:
                tpl = load_checklist_template(name)
            except Exception as e:  # noqa: BLE001
                out.append({"name": name, "error": str(e)})
                continue
            items = tpl.get("items") or []
            out.append({
                "name": tpl.get("name", name),
                "stage": tpl.get("stage", ""),
                "title": tpl.get("title", ""),
                "items_count": len(items),
                "disciplines": tpl.get("disciplines", []),
            })
    return {"templates": out}


@router.post("/{dataset_id}/run")
async def checklist_review_run(dataset_id: str, req: ChecklistRunRequest, _user=Depends(require_user)):
    _safe_dataset_dir(dataset_id)  # валидирует dataset_id (400 при traversal), директория позже

    try:
        template = load_checklist_template(req.template)
    except FileNotFoundError:
        raise HTTPException(404, f"template '{req.template}' не найден")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"template: {e}")

    if req.limit is not None and req.limit >= 0:
        limited = dict(template)
        limited["items"] = list(template.get("items", []))[: req.limit]
        template = limited

    result = run_checklist_review(
        template,
        dataset_id=dataset_id,
        source_dataset_ids=req.source_dataset_ids,
        discipline=req.discipline,
        inventory_provider=default_inventory_provider,
        search_provider=default_search_provider,
        workbook_provider=default_workbook_provider,
        doc_review_provider=default_doc_review_provider,
    )

    run_id = uuid.uuid4().hex
    result["run_id"] = run_id
    _save_run(dataset_id, run_id, result)

    return result


@router.get("/{dataset_id}/runs/{run_id}")
async def checklist_review_get_run(dataset_id: str, run_id: str, _user=Depends(require_user)):
    result = _load_run(dataset_id, run_id)
    decisions = _load_decisions(dataset_id, run_id)
    return _apply_decisions(result, decisions)


@router.get("/{dataset_id}/runs/{run_id}/download")
async def checklist_review_download(dataset_id: str, run_id: str,
                                     fmt: str = Query("json"), _user=Depends(require_user)):
    fmt = (fmt or "json").lower()
    if fmt not in {"json", "xlsx", "html"}:
        raise HTTPException(400, "fmt: json | xlsx | html")

    result = _load_run(dataset_id, run_id)
    decisions = _load_decisions(dataset_id, run_id)
    result = _apply_decisions(result, decisions)

    if fmt == "json":
        return result

    if fmt == "html":
        html_body = report_to_html(result)
        return HTMLResponse(content=html_body)

    # fmt == "xlsx" — рендерим во временный файл и отдаём как бинарный ответ (без диска
    # storage/, отчёт не персистится отдельно от run.json — генерируется по требованию).
    import tempfile

    with tempfile.TemporaryDirectory() as tmp_dir:
        xlsx_path = Path(tmp_dir) / f"checklist_review_{run_id}.xlsx"
        report_to_xlsx(result, xlsx_path)
        content = xlsx_path.read_bytes()

    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="checklist_review_{run_id}.xlsx"',
        },
    )


@router.post("/{dataset_id}/runs/{run_id}/items/{item_id}/decision")
async def checklist_review_set_decision(dataset_id: str, run_id: str, item_id: str,
                                         req: ChecklistDecisionRequest, _user=Depends(require_user)):
    result = _load_run(dataset_id, run_id)  # 404, если run не существует
    items = result.get("items", [])
    if not any(it.get("item_id") == item_id for it in items):
        raise HTTPException(404, f"item {item_id} не найден в run {run_id}")

    with _DECISIONS_LOCK:
        decisions = _load_decisions(dataset_id, run_id)
        human_answer = req.human_answer
        if human_answer == "unset":
            decisions.pop(item_id, None)
        else:
            from datetime import datetime, timezone

            decisions[item_id] = {
                "human_answer": human_answer,
                "human_note": (req.human_note or "").strip(),
                "decided_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        payload = _save_decisions(dataset_id, run_id, decisions)
    return {"ok": True, **payload}
