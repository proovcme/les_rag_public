"""Service source registry API — visible required data for LES workflows."""

from __future__ import annotations

import asyncio
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from proxy.security import require_user
from proxy.services import fgis_update_service, gesn_update_service
from proxy.services.notebook_service import service_source_notebooks
from proxy.services.service_source_registry import process_service_source, service_source, service_sources

router = APIRouter(prefix="/api/service-sources", tags=["service-sources"])


class EtmCatalogRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    page: int = Field(default=1, ge=1, le=10000)
    rows: int = Field(default=20, ge=1, le=50)


class EtmQuotesRequest(BaseModel):
    codes: list[str] = Field(min_length=1, max_length=500)


async def _etm_read(operation, *args, **kwargs):
    from proxy.services.etm_supplier_service import EtmError, error_message, get_client
    try:
        def read():
            return operation(get_client(), *args, **kwargs)
        return await asyncio.to_thread(read)
    except EtmError as error:
        raise HTTPException(503, detail={"code": str(error), "message": error_message(str(error))}) from None


@router.post("/etm/catalog")
async def etm_catalog(req: EtmCatalogRequest, _user=Depends(require_user)):
    from proxy.services.etm_supplier_service import EtmClient
    return await _etm_read(EtmClient.search, req.query, page=req.page, rows=req.rows)


@router.post("/etm/quotes")
async def etm_quotes(req: EtmQuotesRequest, _user=Depends(require_user)):
    from proxy.services.etm_supplier_service import EtmClient
    return await _etm_read(EtmClient.quotes, req.codes)


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
    result = await asyncio.to_thread(process_service_source, source_id)
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
