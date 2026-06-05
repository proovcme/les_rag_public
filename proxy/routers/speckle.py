"""Speckle integration routes for BIM/CAD bridge status."""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from proxy.security import require_admin, require_user
from proxy.services.cad_bim_graph import (
    CAD_BIM_ROOT,
    graph_summary,
    import_payload,
    latest_cad_bim_json_source,
    latest_speckle_source,
    load_source_payload,
)

router = APIRouter(prefix="/api/speckle", tags=["speckle"])
cad_bim_router = APIRouter(prefix="/api/cad-bim", tags=["cad-bim"])


class SpeckleImportRequest(BaseModel):
    source_path: str | None = None
    stream_id: str | None = None
    object_id: str | None = None
    source_type: str | None = None
    profile: str | None = None
    payload: dict[str, Any] | list[Any] | None = None
    max_objects: int = Field(default=5000, ge=1, le=50000)


def _bool_env(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _base_url() -> str:
    return os.getenv("SPECKLE_BASE_URL", "https://speckle.ovc.me").strip().rstrip("/")


def _graphql_url(base_url: str) -> str:
    return os.getenv("SPECKLE_GRAPHQL_URL", "").strip() or f"{base_url}/graphql"


def _timeout_sec() -> float:
    try:
        return max(0.5, min(60.0, float(os.getenv("SPECKLE_WAKE_TIMEOUT_SEC", "5") or "5")))
    except ValueError:
        return 5.0


def _status_for_http(code: int) -> str:
    if 200 <= code < 400:
        return "ok"
    if code in {401, 403}:
        return "auth_required"
    if code in {502, 503, 504}:
        return "sleeping"
    return "unhealthy"


@router.get("/status")
async def speckle_status(_user=Depends(require_user)):
    base_url = _base_url()
    if not base_url.startswith(("http://", "https://")):
        raise HTTPException(400, "SPECKLE_BASE_URL должен начинаться с http:// или https://")

    enabled = _bool_env("SPECKLE_ENABLED", "true")
    timeout = _timeout_sec()
    token = os.getenv("SPECKLE_API_TOKEN", "").strip()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(base_url, headers=headers)
        elapsed_ms = round((time.monotonic() - started) * 1000, 1)
        return {
            "enabled": enabled,
            "status": _status_for_http(response.status_code) if enabled else "disabled",
            "http_status": response.status_code,
            "base_url": base_url,
            "graphql_url": _graphql_url(base_url),
            "api_token_set": bool(token),
            "supported_formats": ["json", "jsonl", "dwg", "dxf", "rvt", "ifc"],
            "elapsed_ms": elapsed_ms,
        }
    except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as error:
        elapsed_ms = round((time.monotonic() - started) * 1000, 1)
        return {
            "enabled": enabled,
            "status": "sleeping_or_unreachable" if enabled else "disabled",
            "http_status": 0,
            "base_url": base_url,
            "graphql_url": _graphql_url(base_url),
            "api_token_set": bool(token),
            "supported_formats": ["json", "jsonl", "dwg", "dxf", "rvt", "ifc"],
            "elapsed_ms": elapsed_ms,
            "detail": error.__class__.__name__,
        }


@router.get("/graph/summary")
async def speckle_graph_summary(_user=Depends(require_user)):
    return graph_summary()


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


@router.post("/import")
async def speckle_import(req: SpeckleImportRequest, _admin=Depends(require_admin)):
    if req.payload is not None:
        result = await _import_payload(
            req.payload,
            source="inline_payload",
            max_objects=req.max_objects,
            profile=req.profile or req.source_type,
        )
        return {"status": "imported", **result}

    if req.source_path:
        source_path = _safe_cad_bim_source(req.source_path)
    else:
        source_path = latest_speckle_source()

    if source_path is not None:
        payload = await _load_payload_async(source_path)
        result = await _import_payload(
            payload,
            source=source_path.as_posix(),
            max_objects=req.max_objects,
            profile=req.profile or req.source_type,
        )
        return {"status": "imported", **result}

    if req.stream_id and req.object_id:
        payload = await _fetch_speckle_object(req.stream_id, req.object_id)
        result = await _import_payload(
            payload,
            source=f"{_base_url()}/streams/{req.stream_id}/objects/{req.object_id}",
            max_objects=req.max_objects,
            profile=req.profile or req.source_type,
        )
        return {"status": "imported", **result}

    raise HTTPException(
        400,
        "Укажите source_path, inline payload или stream_id+object_id; либо положите JSON/JSONL в RAG_Content/CAD_BIM/Speckle",
    )


@cad_bim_router.post("/import")
async def cad_bim_import(req: SpeckleImportRequest, _admin=Depends(require_admin)):
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
        speckle_path = CAD_BIM_ROOT / "Speckle" / raw_path
        path = direct if direct.exists() else json_path if json_path.exists() else speckle_path
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
    source_kind: str = "speckle",
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


async def _fetch_speckle_object(stream_id: str, object_id: str) -> Any:
    base_url = _base_url()
    graphql_url = _graphql_url(base_url)
    token = os.getenv("SPECKLE_API_TOKEN", "").strip()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    query = """
    query LesSpeckleObject($streamId: String!, $objectId: String!) {
      stream(id: $streamId) {
        object(id: $objectId) {
          id
          speckleType
          totalChildrenCount
          data
        }
      }
    }
    """
    try:
        async with httpx.AsyncClient(timeout=_timeout_sec(), follow_redirects=True) as client:
            response = await client.post(
                graphql_url,
                json={"query": query, "variables": {"streamId": stream_id, "objectId": object_id}},
                headers=headers,
            )
    except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as error:
        raise HTTPException(503, f"Speckle sleeping_or_unreachable: {error.__class__.__name__}") from error
    if response.status_code in {502, 503, 504}:
        raise HTTPException(503, "Speckle sleeping")
    if response.status_code in {401, 403}:
        raise HTTPException(403, "Speckle auth required")
    if response.status_code >= 400:
        raise HTTPException(502, f"Speckle GraphQL HTTP {response.status_code}: {response.text[:300]}")
    data = response.json()
    if data.get("errors"):
        raise HTTPException(502, {"speckle_errors": data["errors"]})
    obj = (((data.get("data") or {}).get("stream") or {}).get("object") or {})
    payload = obj.get("data") or obj
    if isinstance(payload, str):
        try:
            payload = __import__("json").loads(payload)
        except ValueError:
            payload = {"id": object_id, "speckleType": obj.get("speckleType", ""), "raw": payload}
    return payload
