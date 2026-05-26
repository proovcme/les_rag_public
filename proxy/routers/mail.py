"""Е.Ж.И.К. mail ingest routes."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.mail_ingest import (
    MAIL_DATASET_NAME,
    iter_mail_files,
    resolve_mail_source_folder,
    summarize_mail_files,
)
from proxy.routers.datasets import (
    DEFAULT_PARSE_BATCH_LIMIT,
    active_parse_scheduler_job,
    assert_parse_admission,
    get_dataset_state,
)
from proxy.security import require_admin, require_user
from proxy.services.runtime_dispatcher import RuntimeDispatcher


router = APIRouter(prefix="/api/mail", tags=["mail"])


class MailLocalImportRequest(BaseModel):
    source_folder: str = "MAIL"
    max_files: int = Field(default=500, ge=1, le=5000)
    parse: bool = False
    parse_limit: int = Field(default=DEFAULT_PARSE_BATCH_LIMIT, ge=1, le=25)


async def _mail_dataset_id(state: Any) -> tuple[str, bool]:
    datasets = await state.backend.list_datasets()
    existing = next((dataset for dataset in datasets if dataset.name == MAIL_DATASET_NAME), None)
    if existing:
        return existing.id, False
    return await state.backend.create_dataset(MAIL_DATASET_NAME), True


@router.get("/status")
async def mail_status(_user=Depends(require_user)):
    state = get_dataset_state()
    datasets = await state.backend.list_datasets()
    dataset = next((item for item in datasets if item.name == MAIL_DATASET_NAME), None)
    return {
        "component": "Е.Ж.И.К.",
        "status": "ready" if dataset else "not_created",
        "dataset_name": MAIL_DATASET_NAME,
        "dataset": asdict(dataset) if dataset else None,
        "supported": [".eml", ".msg"],
        "imap": {"enabled": False, "status": "planned"},
    }


@router.post("/import-local")
async def import_local_mail(req: MailLocalImportRequest, _admin=Depends(require_admin)):
    state = get_dataset_state()
    try:
        source_dir = resolve_mail_source_folder(req.source_folder)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    files = iter_mail_files(source_dir, max_files=req.max_files)
    if not files:
        raise HTTPException(status_code=400, detail=f"no .eml/.msg files found in {source_dir}")

    dataset_id, created = await _mail_dataset_id(state)
    summaries = summarize_mail_files(source_dir, max_files=req.max_files)
    uploaded: list[dict[str, Any]] = []
    for source_file in files:
        rel_path = source_file.relative_to(source_dir).as_posix()
        doc_id = await state.backend.upload_file(
            dataset_id,
            source_file,
            relative_path=f"{req.source_folder.strip('/')}/{rel_path}",
        )
        uploaded.append({"doc_id": doc_id, "relative_path": rel_path})

    parse_started = False
    parse_blocked = ""
    parse_result: dict[str, Any] | None = None
    if req.parse:
        active = active_parse_scheduler_job(state)
        current_mode = state.current_mode or {}
        if current_mode.get("mode") == "indexing":
            parse_blocked = "indexing mode active"
        elif RuntimeDispatcher(current_mode=current_mode).reindex_status_payload().get("running"):
            parse_blocked = "guarded reindex active"
        elif active:
            job_id, job = active
            parse_blocked = f"parse scheduler active: {job_id} {job.get('status', '')}"
        else:
            async with state.sync_parse_semaphore:
                await assert_parse_admission(state)
                parse_result = await state.backend.parse_dataset(dataset_id, limit=req.parse_limit)
            parse_started = True

    return {
        "status": "registered",
        "component": "Е.Ж.И.К.",
        "source_folder": req.source_folder,
        "source_dir": source_dir.as_posix(),
        "dataset_id": dataset_id,
        "dataset_name": MAIL_DATASET_NAME,
        "dataset_created": created,
        "files": len(files),
        "uploaded": uploaded,
        "summaries": [summary.payload() for summary in summaries],
        "parse_started": parse_started,
        "parse_blocked": parse_blocked,
        "parse_result": parse_result,
    }
