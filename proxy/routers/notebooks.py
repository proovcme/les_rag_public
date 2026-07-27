"""Notebook API: unified navigation/passport layer for datasets."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from proxy.security import require_admin, require_user
from proxy.services.dataset_memory_service import (
    build_typed_dataset_memory,
    get_typed_dataset_memory,
    run_dataset_reader_pass,
    schedule_dataset_reader_pass,
)
from proxy.services.notebook_service import build_dataset_notebook, warmup_dataset_notebooks

router = APIRouter(prefix="/api/notebooks", tags=["notebooks"])


class NotebookWarmupRequest(BaseModel):
    dataset_ids: list[str] = Field(default_factory=list)
    depth: str = "deep"
    force: bool = False
    limit: int = 0


class DatasetReaderRequest(BaseModel):
    force: bool = False
    background: bool = False


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


@router.get("/{dataset_id}/memory")
async def dataset_typed_memory(dataset_id: str, _user=Depends(require_user)):
    return get_typed_dataset_memory(dataset_id)


@router.post("/{dataset_id}/memory/refresh")
async def refresh_dataset_typed_memory(dataset_id: str, _admin=Depends(require_admin)):
    return build_typed_dataset_memory(dataset_id, force=True)


@router.post("/{dataset_id}/memory/read")
async def read_dataset_memory(dataset_id: str, req: DatasetReaderRequest | None = None, _admin=Depends(require_admin)):
    req = req or DatasetReaderRequest()
    if req.background:
        return schedule_dataset_reader_pass(
            dataset_id,
            reason="api_memory_read",
            force=req.force,
            require_enabled=False,
        )
    return await run_dataset_reader_pass(dataset_id, force=req.force)
