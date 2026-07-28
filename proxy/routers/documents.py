"""No-AI document explorer API.

These endpoints are for browsing and searching indexed datasets directly.
They do not call LLMs; they read LES metadata and the lexical SQLite index.
"""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from proxy.security import require_admin, require_user
from proxy.services.document_explorer_service import explorer
from proxy.services.pdf_contour_service import audit_pdf, render_page_preview

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


def _pdf_document_source(doc_id: str) -> tuple[dict, str]:
    try:
        document = explorer().get_document(doc_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if document is None:
        raise HTTPException(status_code=404, detail="document not found")
    source_path = _resolved_document_source(document)
    if source_path is None:
        raise HTTPException(status_code=404, detail="document has no source_path")
    return document, source_path.as_posix()


def _resolved_document_source(document: dict) -> Path | None:
    """Resolve an original without letting metadata escape dataset storage.

    External sources keep their recorded absolute path. Uploaded files do not
    store one, so fall back to the canonical read-only storage location.
    """
    recorded = str(document.get("source_path") or "").strip()
    if recorded:
        candidate = Path(recorded).expanduser()
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()

    dataset_id = str(document.get("dataset_id") or "").strip()
    file_name = str(document.get("file_name") or "").strip()
    if not dataset_id or Path(dataset_id).name != dataset_id or dataset_id in {".", ".."}:
        return None
    relative = Path(file_name)
    if not file_name or relative.is_absolute() or ".." in relative.parts:
        return None
    dataset_root = (Path("storage/datasets") / dataset_id).resolve()
    candidate = (dataset_root / relative).resolve()
    if not candidate.is_relative_to(dataset_root):
        return None
    return candidate if candidate.exists() and candidate.is_file() else None


@router.get("/by-id/{doc_id}/pdf-contour")
async def document_pdf_contour(
    doc_id: str,
    max_pages: int = Query(default=80, ge=1, le=200),
    _user=Depends(require_user),
):
    """Read-only per-page PDF routing passport with coordinates and quality."""
    document, source_path = _pdf_document_source(doc_id)
    try:
        return await asyncio.to_thread(
            audit_pdf,
            source_path,
            doc_id=doc_id,
            file_name=str(document.get("file_name") or ""),
            max_pages=max_pages,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/by-id/{doc_id}/pdf-contour/pages/{page_number}/preview")
async def document_pdf_contour_preview(
    doc_id: str,
    page_number: int,
    width: int = Query(default=1200, ge=320, le=1800),
    bbox: str = Query(default="", max_length=160),
    _user=Depends(require_user),
):
    """Render the page or an exact evidence bbox as PNG; source stays untouched."""
    _document, source_path = _pdf_document_source(doc_id)
    parsed_bbox = None
    if bbox.strip():
        try:
            values = tuple(float(value.strip()) for value in bbox.split(","))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="bbox must contain four numbers") from exc
        if len(values) != 4:
            raise HTTPException(status_code=400, detail="bbox must contain four numbers")
        parsed_bbox = values
    try:
        content = await asyncio.to_thread(
            render_page_preview,
            source_path,
            page_number=page_number,
            max_width=width,
            bbox=parsed_bbox,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type="image/png",
        headers={"Content-Disposition": f'inline; filename="page-{page_number}.png"'},
    )


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
    source_path = _resolved_document_source(document)
    if source_path is None:
        raise HTTPException(status_code=404, detail="document has no source_path")
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
