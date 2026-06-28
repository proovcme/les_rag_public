"""Service source registry API — visible required data for LES workflows."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from proxy.security import require_user
from proxy.services.notebook_service import service_source_notebooks
from proxy.services.service_source_registry import process_service_source, service_source, service_sources

router = APIRouter(prefix="/api/service-sources", tags=["service-sources"])


@router.get("")
async def list_service_sources(_user=Depends(require_user)):
    return service_sources()


@router.get("/notebooks")
async def list_service_source_notebooks(_user=Depends(require_user)):
    return service_source_notebooks()


@router.get("/{source_id}")
async def get_service_source(source_id: str, _user=Depends(require_user)):
    item = service_source(source_id)
    if item is None:
        raise HTTPException(404, "service source not found")
    return item


@router.post("/{source_id}/process")
async def process_source(source_id: str, _user=Depends(require_user)):
    result = process_service_source(source_id)
    if result.get("status") == "not_found":
        raise HTTPException(404, "service source not found")
    return result
