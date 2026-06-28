"""Notebook API: unified navigation/passport layer for datasets."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from proxy.security import require_admin, require_user
from proxy.services.notebook_service import build_dataset_notebook, warmup_dataset_notebooks

router = APIRouter(prefix="/api/notebooks", tags=["notebooks"])


class NotebookWarmupRequest(BaseModel):
    dataset_ids: list[str] = Field(default_factory=list)
    depth: str = "deep"
    force: bool = False
    limit: int = 0


@router.post("/warmup")
async def warmup_notebooks(req: NotebookWarmupRequest, _admin=Depends(require_admin)):
    return warmup_dataset_notebooks(
        dataset_ids=req.dataset_ids,
        storage_root=Path("storage/datasets"),
        depth=req.depth,
        force=req.force,
        limit=req.limit,
    )


@router.get("/{dataset_id}")
async def dataset_notebook(dataset_id: str, depth: str = "deep", _user=Depends(require_user)):
    return build_dataset_notebook(dataset_id, storage_root=Path("storage/datasets"), depth=depth)
