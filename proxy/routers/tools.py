"""Tool harness API.

These endpoints expose controlled LES tools for GUI/CLI dry-runs. They do not
grant the model autonomous filesystem access.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from proxy.security import require_admin, require_user
from proxy.services.tool_harness_service import harness

router = APIRouter(prefix="/api/tools", tags=["tools"])


class ToolCallRequest(BaseModel):
    tool: str = Field(min_length=1, max_length=120)
    args: dict[str, Any] = Field(default_factory=dict)


class ToolShortlistRequest(BaseModel):
    question: str = Field(default="", max_length=4000)
    mode: str = Field(default="", max_length=120)
    limit: int = Field(default=5, ge=1, le=12)


@router.get("/registry")
async def tool_registry(category: str = "", _user=Depends(require_user)):
    return harness().registry(category=category)


@router.post("/shortlist")
async def tool_shortlist(req: ToolShortlistRequest, _user=Depends(require_user)):
    return harness().shortlist(req.question, mode=req.mode, limit=req.limit)


@router.post("/call")
async def tool_call(req: ToolCallRequest, _admin=Depends(require_admin)):
    return harness().call(req.tool, req.args)


@router.get("/filesystem/roots")
async def filesystem_roots(_user=Depends(require_user)):
    return harness().call("filesystem_roots", {})


@router.get("/filesystem/list")
async def filesystem_list(
    root: str = Query(default="docs", max_length=80),
    path: str = Query(default="", max_length=2000),
    depth: int = Query(default=1, ge=0, le=4),
    _user=Depends(require_user),
):
    return harness().call("filesystem_list", {"root": root, "path": path, "depth": depth})
