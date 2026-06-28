"""Prompt registry API for operator/admin UI."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from proxy.security import require_user
from proxy.services.prompt_registry_service import prompt_registry_snapshot

router = APIRouter(prefix="/api/prompts", tags=["prompts"])


@router.get("")
async def list_prompts(_user=Depends(require_user)):
    return prompt_registry_snapshot()
