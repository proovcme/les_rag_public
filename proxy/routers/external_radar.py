"""External source radar: operator overview for in-place archive intake."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends

from proxy.security import require_user
from proxy.services.external_radar_service import build_external_radar

router = APIRouter(prefix="/api/external-radar", tags=["external-radar"])


@router.get("/summary")
async def external_radar_summary(limit: int = 15, _user=Depends(require_user)):
    """No-reindex overview of external roots, file-map candidates and in-place datasets."""
    return await asyncio.to_thread(build_external_radar, candidate_limit=max(1, min(limit, 80)))

