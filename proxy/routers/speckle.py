"""CAD/BIM (АТЛАС) routes — вьювер, граф, импорт из локального JSON/JSONL,
подсветка элементов.

Внешний коннектор Speckle (`/api/speckle/status`, `/import` из живого Speckle,
GraphQL-фетч) удалён 2026-06-14 по решению оператора. Импорт работает из
локальных файлов CAD/BIM (JSON/JSONL/DWG/DXF/RVT/IFC через конвертеры);
подсистема АТЛАС (W5.7), подсветка в чате и дифф — не затронуты.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from proxy.security import require_admin, require_user
from proxy.services.cad_bim_highlight import get_highlight, set_highlight
from proxy.services.cad_bim_graph import (
    CAD_BIM_ROOT,
    graph_summary,
    import_payload,
    latest_cad_bim_json_source,
    load_source_payload,
    lookup_element_context,
)

cad_bim_router = APIRouter(prefix="/api/cad-bim", tags=["cad-bim"])


class CadBimImportRequest(BaseModel):
    source_path: str | None = None
    source_type: str | None = None
    profile: str | None = None
    payload: dict[str, Any] | list[Any] | None = None
    max_objects: int = Field(default=5000, ge=1, le=50000)


@cad_bim_router.get("/graph/summary")
async def cad_bim_graph_summary(_user=Depends(require_user)):
    return graph_summary()


@cad_bim_router.get("/source")
async def cad_bim_source(
    source_path: Annotated[str | None, Query()] = None,
    max_elements: Annotated[int, Query(ge=1, le=50000)] = 5000,
    _user=Depends(require_user),
):
    source = _safe_cad_bim_source(source_path) if source_path else latest_cad_bim_json_source()
    if source is None:
        raise HTTPException(404, "CAD/BIM JSON source not found")
    payload = await _load_payload_async(source)
    trimmed, element_count, truncated = _trim_viewer_payload(payload, max_elements=max_elements)
    return {
        "source": source.as_posix(),
        "payload": trimmed,
        "element_count": element_count,
        "truncated": truncated,
    }


@cad_bim_router.get("/element")
async def cad_bim_element_context(
    source_id: Annotated[str, Query(min_length=1, max_length=256)],
    import_id: Annotated[str | None, Query(max_length=64)] = None,
    _user=Depends(require_user),
):
    context = await __import__("asyncio").to_thread(
        lookup_element_context,
        source_id,
        import_id=import_id,
    )
    if context is None:
        raise HTTPException(404, "CAD/BIM element not found")
    return context


class HighlightRequest(BaseModel):
    source_ids: list[str] = Field(default_factory=list)
    import_id: str | None = None
    question: str = ""


@cad_bim_router.get("/highlight")
async def cad_bim_get_highlight(_user=Depends(require_user)):
    """Последняя подсветка (W6.7): вьювер поллит и перекрашивает элементы по seq."""
    return get_highlight()


@cad_bim_router.post("/highlight")
async def cad_bim_set_highlight(req: HighlightRequest, _user=Depends(require_user)):
    """Задать подсветку вручную (другие UI / тесты); пустой список не меняет снимок."""
    snapshot = set_highlight(req.source_ids, import_id=req.import_id, question=req.question)
    return snapshot or get_highlight()


@cad_bim_router.post("/import")
async def cad_bim_import(req: CadBimImportRequest, _admin=Depends(require_admin)):
    if req.payload is not None:
        source_path = await __import__("asyncio").to_thread(
            _persist_inline_cad_bim_payload,
            req.payload,
            profile=req.profile or req.source_type,
        )
        result = await _import_payload(
            req.payload,
            source=source_path.as_posix(),
            max_objects=req.max_objects,
            profile=req.profile or req.source_type,
            source_kind="json",
        )
        return {"status": "imported", **result}

    source_path = _safe_cad_bim_source(req.source_path) if req.source_path else latest_cad_bim_json_source()
    if source_path is None:
        raise HTTPException(
            400,
            "Укажите source_path или inline payload; либо положите JSON/JSONL в RAG_Content/CAD_BIM/JSON",
        )

    payload = await _load_payload_async(source_path)
    result = await _import_payload(
        payload,
        source=source_path.as_posix(),
        max_objects=req.max_objects,
        profile=req.profile or req.source_type,
        source_kind="json",
    )
    return {"status": "imported", **result}


def _persist_inline_cad_bim_payload(payload: dict[str, Any] | list[Any], *, profile: str | None) -> Path:
    (CAD_BIM_ROOT / "JSON").mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe_profile = "".join(ch if ch.isalnum() else "_" for ch in (profile or "generic").lower()).strip("_") or "generic"
    path = CAD_BIM_ROOT / "JSON" / f"{safe_profile}_push_{timestamp}_{uuid.uuid4().hex[:8]}.cad_bim_graph.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _safe_cad_bim_source(raw_path: str) -> Path:
    path = Path(raw_path)
    if not path.is_absolute():
        direct = CAD_BIM_ROOT / raw_path
        json_path = CAD_BIM_ROOT / "JSON" / raw_path
        path = direct if direct.exists() else json_path
    resolved = path.resolve()
    root = CAD_BIM_ROOT.resolve()
    if root != resolved and root not in resolved.parents:
        raise HTTPException(400, "CAD/BIM JSON source должен лежать внутри RAG_Content/CAD_BIM")
    if resolved.suffix.lower() not in {".json", ".jsonl"}:
        raise HTTPException(400, "CAD/BIM source должен быть .json или .jsonl")
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(404, "CAD/BIM source not found")
    return resolved


async def _load_payload_async(source_path: Path) -> Any:
    try:
        return await __import__("asyncio").to_thread(load_source_payload, source_path)
    except Exception as error:
        raise HTTPException(400, f"CAD/BIM source parse failed: {error}") from error


def _trim_viewer_payload(payload: Any, *, max_elements: int) -> tuple[Any, int, bool]:
    if isinstance(payload, dict) and isinstance(payload.get("elements"), list):
        total = len(payload["elements"])
        if total <= max_elements:
            return payload, total, False
        trimmed = dict(payload)
        trimmed["elements"] = payload["elements"][:max_elements]
        relation_ids = {str(item.get("id")) for item in trimmed["elements"] if isinstance(item, dict)}
        relation_ids.add(str(trimmed.get("id") or ""))
        relations = payload.get("relations")
        if isinstance(relations, list):
            trimmed["relations"] = [
                item
                for item in relations
                if isinstance(item, dict)
                and str(item.get("source_id") or item.get("sourceId") or item.get("from") or "") in relation_ids
                and str(item.get("target_id") or item.get("targetId") or item.get("to") or "") in relation_ids
            ]
        return trimmed, total, True
    if isinstance(payload, list):
        total = len(payload)
        return payload[:max_elements], total, total > max_elements
    return payload, 1 if isinstance(payload, dict) else 0, False


async def _import_payload(
    payload: Any,
    *,
    source: str,
    max_objects: int,
    profile: str | None = None,
    source_kind: str = "json",
) -> dict[str, Any]:
    try:
        result = await __import__("asyncio").to_thread(
            import_payload,
            payload,
            source=source,
            source_kind=source_kind,
            max_objects=max_objects,
            profile=profile,
        )
    except Exception as error:
        raise HTTPException(500, f"CAD/BIM import failed: {error}") from error
    return {
        "import_id": result.import_id,
        "source": result.source,
        "profile": result.profile,
        "elements": result.elements,
        "relations": result.relations,
        "properties": result.properties,
        "projection_path": result.projection_path,
        "db_path": result.db_path,
    }
