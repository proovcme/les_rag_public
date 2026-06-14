"""W17.2 — API типизированных рёбер графа знаний + backfill."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Query

from proxy.security import require_admin, require_user
from proxy.services import edge_service

router = APIRouter(prefix="/api/edges", tags=["edges"])


@router.get("")
async def edges_list(
    method: str = "",
    limit: int = Query(default=500, ge=1, le=5000),
    _user=Depends(require_user),
):
    return {"edges": await asyncio.to_thread(edge_service.list_edges, limit, method or None)}


@router.get("/for")
async def edges_for(kind: str, id: str, _user=Depends(require_user)):
    return await asyncio.to_thread(edge_service.edges_for, kind, id)


@router.post("/backfill")
async def edges_backfill(_admin=Depends(require_admin)):
    """Перестроить детерминированные рёбра по всем заметкам и задачам (0 LLM).
    Идемпотентно (derive_edges_from_text чистит прежние авто-рёбра узла)."""
    def _run() -> dict:
        from proxy.services.memory_service import list_notes
        from proxy.services.task_service import list_tasks

        notes = list_notes(limit=10000)
        tasks = list_tasks("", 10000)
        edges = 0
        for n in notes:
            edges += len(edge_service.derive_edges_from_text(
                "note", str(n.get("id")), n.get("text") or "", provenance=f"note#{n.get('id')}"
            ))
        for t in tasks:
            edges += len(edge_service.derive_edges_from_text(
                "task", str(t.get("id")), f"{t.get('title') or ''}\n{t.get('details') or ''}",
                provenance=f"task#{t.get('id')}",
            ))
        return {"notes": len(notes), "tasks": len(tasks), "edges": edges}

    return await asyncio.to_thread(_run)
