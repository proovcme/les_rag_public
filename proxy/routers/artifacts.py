"""Authenticated metadata and verified downloads for immutable artifacts."""

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from backend.runtime_paths import mutable_path
from proxy.security import require_user
from proxy.services.artifact_revision_service import (
    ArtifactImmutableError,
    ArtifactNotFoundError,
    ArtifactRevisionStore,
)

router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])
artifact_revision_store = ArtifactRevisionStore(
    mutable_path("storage/artifacts/meta.db"),
    mutable_path("storage/artifacts/files"),
)


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": "ARTIFACT_NOT_FOUND", "message": str(exc)})


def content_disposition_attachment(filename: str) -> str:
    raw = str(filename or "workbook.xlsx").replace("\r", "").replace("\n", "").replace('"', "")
    ascii_name = raw.encode("ascii", "ignore").decode("ascii").strip("._") or "workbook.xlsx"
    if "." not in ascii_name:
        ascii_name = "workbook.xlsx"
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(raw)}'


@router.get("/{revision_id}/download")
async def artifact_download(revision_id: str, _user=Depends(require_user)):
    try:
        revision = artifact_revision_store.get_revision(revision_id)
        payload = artifact_revision_store.read_bytes(revision_id)
    except ArtifactNotFoundError as exc:
        raise _not_found(exc) from exc
    except ArtifactImmutableError as exc:
        raise HTTPException(status_code=409, detail={"code": "ARTIFACT_HASH_DRIFT", "message": str(exc)}) from exc
    return Response(
        payload,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": content_disposition_attachment(revision.filename)},
    )


@router.get("/{artifact_id}/revisions")
async def artifact_revisions(artifact_id: str, _user=Depends(require_user)):
    try:
        revisions = artifact_revision_store.list_revisions(artifact_id)
    except ArtifactNotFoundError as exc:
        raise _not_found(exc) from exc
    return {"schema": "les.artifact_revision_list.v1", "revisions": [item.to_dict() for item in revisions]}


@router.get("/{revision_id}")
async def artifact_metadata(revision_id: str, _user=Depends(require_user)):
    try:
        return artifact_revision_store.get_revision(revision_id).to_dict()
    except ArtifactNotFoundError as exc:
        raise _not_found(exc) from exc
