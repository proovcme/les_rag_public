"""W11.3/W19 — API типовых форм документов: дескриптор + данные объекта → документ."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from proxy.security import require_user
from proxy.services import forms_service, list_office_agent_service, list_office_service

router = APIRouter(prefix="/api/forms", tags=["forms"])

_MEDIA = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


class FormGenerate(BaseModel):
    project_id: Optional[int] = None
    fmt: str = "docx"
    manual: Optional[dict[str, Any]] = None
    source: Optional[str] = None
    session_id: Optional[str] = None
    rows: Optional[list[list[str]]] = None
    assembled: Optional[dict[str, Any]] = None
    rim_form: Optional[dict[str, Any]] = None


class OfficeDraftCreate(BaseModel):
    form_id: str
    project_id: Optional[int] = None
    fmt: str = "docx"
    manual: Optional[dict[str, Any]] = None
    dataset_id: str = ""
    source_refs: Optional[list[dict[str, Any]]] = None
    document_id: Optional[str] = None
    office_ir: Optional[dict[str, Any]] = None
    review_confirmed: bool = False


class OfficeAgentDraft(BaseModel):
    form_id: str
    project_id: Optional[int] = None
    manual: Optional[dict[str, Any]] = None
    dataset_id: str = ""
    source_refs: Optional[list[dict[str, Any]]] = None
    instruction: str = ""


@router.get("")
async def forms_list(_user=Depends(require_user)):
    return {"forms": await asyncio.to_thread(forms_service.list_forms)}


@router.get("/artifacts")
async def office_artifacts(limit: int = 100, _user=Depends(require_user)):
    """Append-only журнал созданных в Студии документов Л.И.С.Т."""
    rows = await asyncio.to_thread(list_office_service.list_artifacts, limit=limit)
    return {"schema": "list.office_artifact_registry.v1", "artifacts": rows}


@router.post("/agent-draft")
async def office_agent_draft(req: OfficeAgentDraft, _user=Depends(require_user)):
    """Подготовить reviewable IR по выбранным файлам; офисный файл не создаётся."""
    try:
        return await list_office_agent_service.prepare_document_ir(
            req.form_id,
            project_id=req.project_id,
            manual=req.manual or {},
            dataset_id=req.dataset_id,
            source_refs=req.source_refs or [],
            instruction=req.instruction,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except list_office_agent_service.OfficeAgentUnavailable as exc:
        raise HTTPException(503, f"Л.Е.С. не подготовил валидный черновик: {exc}") from exc


@router.post("/artifacts")
async def office_artifact_create(req: OfficeDraftCreate, _user=Depends(require_user)):
    """Создать новую draft-ревизию, не изменяя файлы-основания."""
    try:
        return await asyncio.to_thread(
            list_office_service.create_draft,
            req.form_id,
            req.fmt,
            project_id=req.project_id,
            manual=req.manual or {},
            dataset_id=req.dataset_id,
            source_refs=req.source_refs or [],
            document_id=req.document_id,
            office_ir=req.office_ir,
            review_confirmed=req.review_confirmed,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/artifacts/{revision_id}/download")
async def office_artifact_download(revision_id: str, _user=Depends(require_user)):
    """Отдать ревизию только при совпадении её сохранённого SHA-256."""
    try:
        result = await asyncio.to_thread(list_office_service.artifact_file, revision_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "Ревизия не найдена или повреждена")
    target, manifest = result
    fmt = str(manifest.get("format") or target.suffix.lstrip("."))
    return FileResponse(
        target,
        media_type=_MEDIA.get(fmt, "application/octet-stream"),
        filename=str((manifest.get("artifact") or {}).get("filename") or target.name),
    )


@router.get("/{form_id}/fields")
async def forms_fields(form_id: str, project_id: Optional[int] = None, _user=Depends(require_user)):
    """Поля формы с разрешёнными из объекта значениями (0 LLM); needs_input — ручной ввод."""
    resolved = await asyncio.to_thread(forms_service.resolve_fields, form_id, project_id, None)
    if resolved is None:
        raise HTTPException(404, f"Форма {form_id!r} не найдена")
    return resolved


@router.post("/{form_id}/generate")
async def forms_generate(form_id: str, req: FormGenerate, _user=Depends(require_user)):
    """Сгенерировать документ. html — инлайн-превью; docx/xlsx — путь + /download."""
    fid = str(form_id or "").strip().casefold()
    source = str(req.source or "").strip().casefold()
    try:
        if fid in {"ks2", "ks3", "ks6a"} and source in {
            "last_lsr", "field_journal",
        }:
            from proxy.services import ks_forms_service

            result = await asyncio.to_thread(
                ks_forms_service.build_ks_document,
                fid,
                fmt=req.fmt,
                project_id=req.project_id,
                manual=req.manual or {},
                assembled=req.assembled,
                rim_form=req.rim_form,
                session_id=req.session_id or "",
                source=source,
            )
        else:
            result = await asyncio.to_thread(
                forms_service.generate,
                form_id,
                req.fmt,
                project_id=req.project_id,
                manual=req.manual or {},
                rows=req.rows,
            )
    except ValueError as e:
        raise HTTPException(400, str(e))
    if result.get("path"):
        result["download"] = f"/api/forms/{form_id}/download?path={Path(result['path']).name}"
    return result


@router.get("/{form_id}/download")
async def forms_download(form_id: str, path: str = Query(...), _user=Depends(require_user)):
    """Отдать ранее сгенерированный файл (по имени, в каталоге выдачи — path-guard)."""
    out_dir = forms_service._output_dir().resolve()
    target = (out_dir / Path(path).name).resolve()
    if out_dir not in target.parents or not target.is_file():
        raise HTTPException(404, "Файл не найден")
    fmt = target.suffix.lstrip(".")
    return FileResponse(target, media_type=_MEDIA.get(fmt, "application/octet-stream"), filename=target.name)
