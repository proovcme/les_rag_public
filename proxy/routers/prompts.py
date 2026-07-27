"""Prompt registry API for operator/admin UI."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from proxy.security import require_admin, require_user
from proxy.services.prompt_registry_service import (
    prompt_registry_snapshot,
    reset_prompt_override,
    update_prompt_override,
)

router = APIRouter(prefix="/api/prompts", tags=["prompts"])


class PromptUpdateRequest(BaseModel):
    value: str


@router.get("")
async def list_prompts(_user=Depends(require_user)):
    return prompt_registry_snapshot()


@router.patch("/{prompt_key:path}")
async def update_prompt(prompt_key: str, req: PromptUpdateRequest, _admin=Depends(require_admin)):
    try:
        return update_prompt_override(prompt_key, req.value)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err


@router.delete("/{prompt_key:path}")
async def reset_prompt(prompt_key: str, _admin=Depends(require_admin)):
    try:
        return reset_prompt_override(prompt_key)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
