"""Service source registry API — visible required data for LES workflows."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from proxy.security import require_user
from proxy.services import fgis_update_service, gesn_update_service
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


@router.get("/gesn_base/fgis-update/status")
async def gesn_fgis_update_status(_user=Depends(require_user)):
    return gesn_update_service.status()


@router.post("/gesn_base/fgis-update")
async def gesn_fgis_update(_user=Depends(require_user)):
    return gesn_update_service.start()


@router.get("/fgis/update/status")
async def fgis_update_status(_user=Depends(require_user)):
    return fgis_update_service.status()


@router.post("/fgis/update")
async def fgis_update(_user=Depends(require_user)):
    """Refresh all public FGIS sources; current price books are the safe default."""
    return fgis_update_service.start(include_gesn=True, all_periods=False)
