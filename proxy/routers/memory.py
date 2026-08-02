"""Root-admin API for the isolated Memory Core v1."""

from __future__ import annotations

from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from proxy.memory_core.config import load_memory_config, update_memory_config
from proxy.memory_core.store import MemoryStore
from proxy.security import require_root_admin
from proxy.services.memory_runtime_service import get_memory_store


router = APIRouter(
    prefix="/api/memory",
    tags=["memory"],
    dependencies=[Depends(require_root_admin)],
)


class MemoryConfigUpdate(BaseModel):
    mode: Literal["off", "shadow", "on"]
    smeta_capture: bool = True
    smeta_recall: Literal["off", "advisory", "route_reuse"] = "off"


class EntryReviewRequest(BaseModel):
    action: Literal["confirm", "reject", "mark_disputed"]


class PromotionRequest(BaseModel):
    scope: Literal["function", "global"]


class SmetaTraceReviewRequest(BaseModel):
    action: Literal["confirm", "reject"]
    note: str


def _store() -> MemoryStore:
    return get_memory_store(create=True)


@router.get("/status")
def get_memory_status():
    store = _store()
    config = load_memory_config(store)
    return {
        "status": "ok",
        "mode": config.mode.value,
        "smeta_capture_enabled": config.smeta_capture,
        "smeta_recall_mode": config.smeta_recall.value,
        "configuration_sources": config.sources or {},
        "restart_required_after_change": True,
        **store.status(),
    }


@router.put("/config")
def put_memory_config(request: MemoryConfigUpdate):
    if request.mode != "on" and request.smeta_recall != "off":
        raise HTTPException(400, "smeta recall requires Memory mode=on")
    update_memory_config(
        _store(),
        mode=request.mode,
        smeta_capture=request.smeta_capture,
        smeta_recall=request.smeta_recall,
    )
    return {"status": "saved", "restart_required": True, **request.model_dump()}


@router.get("/entries")
def get_memory_entries(project_id: int = Query(gt=0), limit: int = Query(100, ge=1, le=500)):
    entries = _store().get_entries_by_project(project_id, limit=limit)
    return {
        "status": "ok",
        "project_id": project_id,
        "entries": [
            {**asdict(entry), "kind": entry.kind.value, "validation_status": entry.validation_status.value}
            for entry in entries
        ],
    }


@router.post("/entries/{entry_id}/review")
def review_memory_entry(entry_id: str, request: EntryReviewRequest):
    if not _store().review_entry(entry_id, request.action):
        raise HTTPException(404, "Memory entry not found")
    return {"status": "ok", "entry_id": entry_id, "action": request.action}


@router.post("/entries/{entry_id}/promote")
def promote_memory_entry(entry_id: str, request: PromotionRequest):
    try:
        promoted_id = _store().promote_non_fact(entry_id, request.scope)
    except KeyError as error:
        raise HTTPException(404, "Memory entry not found") from error
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    return {"status": "ok", "entry_id": promoted_id, "scope": request.scope}


@router.get("/smeta-traces")
def get_smeta_traces(project_id: int = Query(gt=0), limit: int = Query(100, ge=1, le=200)):
    traces = _store().get_smeta_traces(project_id, limit=limit)
    return {
        "status": "ok",
        "project_id": project_id,
        "traces": [
            {
                **asdict(trace),
                "trust_level": trace.trust_level.value,
            }
            for trace in traces
        ],
    }


@router.post("/smeta-traces/{trace_id}/review")
def review_smeta_trace(trace_id: str, request: SmetaTraceReviewRequest):
    if not request.note.strip():
        raise HTTPException(400, "Review note is required")
    if not _store().review_smeta_trace(trace_id, request.action, request.note):
        raise HTTPException(404, "Smeta trace not found")
    return {"status": "ok", "trace_id": trace_id, "action": request.action}
