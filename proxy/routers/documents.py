"""No-AI document explorer API.

These endpoints are for browsing and searching indexed datasets directly.
They do not call LLMs; they read LES metadata and the lexical SQLite index.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from proxy.security import require_admin, require_user
from proxy.services.document_explorer_service import explorer

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.get("/datasets")
async def document_datasets(
    q: str = "",
    limit: int = Query(default=200, ge=1, le=1000),
    _user=Depends(require_user),
):
    try:
        return {"datasets": explorer().list_datasets(q=q, limit=limit)}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/datasets/{dataset_id}/documents")
async def dataset_documents(
    dataset_id: str,
    q: str = "",
    status: str = "",
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    _user=Depends(require_user),
):
    try:
        return explorer().list_documents(dataset_id, q=q, status=status, limit=limit, offset=offset)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/datasets/{dataset_id}/quality")
async def dataset_index_quality(
    dataset_id: str,
    samples: int = Query(default=2, ge=1, le=4),
    _user=Depends(require_user),
):
    try:
        return explorer().dataset_index_quality(dataset_id, sample_chunks_per_file=samples)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/by-id/{doc_id}")
async def document_by_id(
    doc_id: str,
    _user=Depends(require_user),
):
    try:
        document = explorer().get_document(doc_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if document is None:
        raise HTTPException(status_code=404, detail="document not found")
    return {"document": document}


@router.post("/by-id/{doc_id}/open-native")
async def open_document_native(
    doc_id: str,
    _admin=Depends(require_admin),
):
    try:
        document = explorer().get_document(doc_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if document is None:
        raise HTTPException(status_code=404, detail="document not found")
    source_path_raw = str(document.get("source_path") or "").strip()
    if not source_path_raw:
        raise HTTPException(status_code=404, detail="document has no source_path")
    source_path = Path(source_path_raw).expanduser()
    if not source_path.exists() or not source_path.is_file():
        raise HTTPException(status_code=404, detail="source file not found")
    try:
        completed = subprocess.run(["open", str(source_path)], check=False, timeout=5)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"open failed: {type(exc).__name__}: {exc}") from exc
    return {
        "status": "opened" if completed.returncode == 0 else "open_failed",
        "doc_id": doc_id,
        "file_name": document.get("file_name") or "",
        "source_path": source_path.as_posix(),
        "returncode": completed.returncode,
    }


@router.get("/by-id/{doc_id}/chunks")
async def document_chunks_by_id(
    doc_id: str,
    q: str = "",
    limit: int = Query(default=80, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    max_chars: int = Query(default=4000, ge=200, le=12000),
    _user=Depends(require_user),
):
    try:
        result = explorer().document_chunks_by_id(
            doc_id,
            q=q,
            limit=limit,
            offset=offset,
            max_chars=max_chars,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="document not found")
    return result


@router.get("/datasets/{dataset_id}/chunks/{doc_name:path}")
async def document_chunks(
    dataset_id: str,
    doc_name: str,
    q: str = "",
    limit: int = Query(default=80, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    max_chars: int = Query(default=4000, ge=200, le=12000),
    _user=Depends(require_user),
):
    try:
        return explorer().document_chunks(
            dataset_id,
            doc_name,
            q=q,
            limit=limit,
            offset=offset,
            max_chars=max_chars,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/search")
async def document_search(
    q: str = Query(min_length=1, max_length=4000),
    dataset_id: list[str] | None = Query(default=None),
    doc_name: str = "",
    doc_id: str = "",
    limit: int = Query(default=50, ge=1, le=200),
    max_chars: int = Query(default=1200, ge=200, le=8000),
    _user=Depends(require_user),
):
    try:
        return explorer().search(
            q,
            dataset_ids=dataset_id or [],
            doc_name=doc_name,
            doc_id=doc_id,
            limit=limit,
            max_chars=max_chars,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
