"""No-AI document explorer API.

These endpoints are for browsing and searching indexed datasets directly.
They do not call LLMs; they read LES metadata and the lexical SQLite index.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from proxy.security import require_user
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
