"""Е.Ж.И.К. mail ingest routes."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.mail_ingest import (
    MAIL_DATASET_NAME,
    apple_mail_public_payload,
    fetch_imap_eml_files,
    imap_settings_from_env,
    import_apple_mail_eml_files,
    iter_mail_files,
    resolve_mail_source_folder,
    summarize_mail_files,
)
from backend.mail_threads import filter_mail_messages, group_mail_threads, read_mail_messages
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


class MailImapImportRequest(BaseModel):
    max_messages: int = Field(default=25, ge=1, le=200)
    parse: bool = False
    parse_limit: int = Field(default=DEFAULT_PARSE_BATCH_LIMIT, ge=1, le=25)
    parse_batches: int = Field(default=1, ge=1, le=20)
    background: bool = False
    # Параметры подключения из GUI (перекрывают env для этого вызова; пусто → берётся env).
    # Пароль НЕ персистится — живёт только в этом запросе по локальному/доверенному каналу.
    host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    login: str | None = None
    password: str | None = None
    ssl: bool | None = None
    folders: list[str] | None = None


class MailArchiveImportRequest(BaseModel):
    path: str
    max_messages: int = Field(default=2000, ge=1, le=50000)
    parse: bool = False
    parse_limit: int = Field(default=DEFAULT_PARSE_BATCH_LIMIT, ge=1, le=25)


class MailAppleImportRequest(BaseModel):
    mail_root: str = ""
    max_messages: int = Field(default=25, ge=1, le=200)
    parse: bool = False
    parse_limit: int = Field(default=DEFAULT_PARSE_BATCH_LIMIT, ge=1, le=25)


async def _mail_dataset_id(state: Any) -> tuple[str, bool]:
    datasets = await state.backend.list_datasets()
    existing = next((dataset for dataset in datasets if dataset.name == MAIL_DATASET_NAME), None)
    if existing:
        return existing.id, False
    return await state.backend.create_dataset(MAIL_DATASET_NAME), True


async def _mail_dataset_and_root(state: Any) -> tuple[Any, Path]:
    datasets = await state.backend.list_datasets()
    dataset = next((item for item in datasets if item.name == MAIL_DATASET_NAME), None)
    if not dataset:
        raise HTTPException(status_code=404, detail=f"{MAIL_DATASET_NAME} dataset is not created")

    content_dir = getattr(state.backend, "content_dir", None)
    if content_dir is None:
        raise HTTPException(status_code=501, detail="mail conversation view requires file-backed backend")
    content_root = Path(content_dir).resolve()
    dataset_root = (content_root / dataset.id).resolve()
    if content_root != dataset_root and content_root not in dataset_root.parents:
        raise HTTPException(status_code=500, detail="unsafe mail dataset storage path")
    if not dataset_root.exists():
        raise HTTPException(status_code=404, detail=f"mail dataset storage not found: {dataset_root}")
    return dataset, dataset_root


async def _load_mail_messages(
    state: Any,
    *,
    max_files: int,
    q: str = "",
    participant: str = "",
    thread_key: str = "",
) -> tuple[Any, list[Any]]:
    dataset, dataset_root = await _mail_dataset_and_root(state)
    messages = await asyncio.to_thread(read_mail_messages, dataset_root, max_files=max_files)
    messages = filter_mail_messages(messages, q=q, participant=participant, thread_key=thread_key)
    return dataset, messages


async def _maybe_parse_mail_dataset(state: Any, dataset_id: str, *, parse: bool, parse_limit: int) -> tuple[bool, str, dict[str, Any] | None]:
    if not parse:
        return False, "", None
    active = active_parse_scheduler_job(state)
    current_mode = state.current_mode or {}
    if current_mode.get("mode") == "indexing":
        return False, "indexing mode active", None
    if RuntimeDispatcher(current_mode=current_mode).reindex_status_payload().get("running"):
        return False, "guarded reindex active", None
    if active:
        job_id, job = active
        return False, f"parse scheduler active: {job_id} {job.get('status', '')}", None
    async with state.sync_parse_semaphore:
        await assert_parse_admission(state)
        parse_result = await state.backend.parse_dataset(dataset_id, limit=parse_limit)
    return True, "", parse_result


async def _upload_fetched_mail(state: Any, fetched: list[Any]) -> tuple[str, bool, list[dict[str, Any]]]:
    dataset_id, created = await _mail_dataset_id(state)
    uploaded: list[dict[str, Any]] = []
    for item in fetched:
        doc_id = await state.backend.upload_file(
            dataset_id,
            item.path,
            relative_path=item.relative_path,
        )
        uploaded.append({"doc_id": doc_id, **item.payload()})
    return dataset_id, created, uploaded


async def _run_imap_import_job(state: Any, job_id: str, req: MailImapImportRequest, settings: Any) -> None:
    def update_job(**updates: Any) -> None:
        try:
            state.job_service.update(job_id, **updates)
        except Exception:
            pass

    def progress(payload: dict[str, Any]) -> None:
        fetched_count = int(payload.get("fetched") or 0)
        folder = str(payload.get("folder") or "")
        uid = payload.get("uid")
        update_job(
            status="running",
            processed=fetched_count,
            total=req.max_messages,
            message=f"Fetching {folder} UID {uid}" if uid else "Fetching IMAP mail",
            result={"stage": "fetching", **payload},
        )

    try:
        update_job(status="running", total=req.max_messages, processed=0, message="Fetching IMAP mail")
        fetched = await asyncio.to_thread(
            fetch_imap_eml_files,
            settings,
            max_messages=req.max_messages,
            progress_callback=progress,
        )
        if not fetched:
            update_job(
                status="completed",
                processed=0,
                total=req.max_messages,
                message="No new IMAP mail",
                result={
                    "status": "no_new_mail",
                    "dataset_name": MAIL_DATASET_NAME,
                    "files": 0,
                    "uploaded": [],
                    "parse_started": False,
                    "parse_blocked": "",
                    "parse_result": None,
                },
            )
            return

        update_job(
            status="running",
            processed=len(fetched),
            total=req.max_messages,
            message=f"Registering {len(fetched)} IMAP messages",
            result={"stage": "registering", "files": len(fetched)},
        )
        dataset_id, created, uploaded = await _upload_fetched_mail(state, fetched)

        parse_started = False
        parse_blocked = ""
        parse_results: list[dict[str, Any]] = []
        if req.parse:
            for batch_index in range(max(1, req.parse_batches)):
                update_job(
                    status="running",
                    processed=len(fetched),
                    total=req.max_messages,
                    message=f"Parsing mail batch {batch_index + 1}/{req.parse_batches}",
                    dataset_id=dataset_id,
                    dataset_name=MAIL_DATASET_NAME,
                    result={"stage": "parsing", "batch": batch_index + 1, "files": len(fetched)},
                )
                started, blocked, parse_result = await _maybe_parse_mail_dataset(
                    state,
                    dataset_id,
                    parse=True,
                    parse_limit=req.parse_limit,
                )
                parse_started = parse_started or started
                parse_blocked = blocked
                if parse_result:
                    parse_results.append(parse_result)
                    if int(parse_result.get("remaining_pending") or 0) <= 0:
                        break
                if blocked:
                    break

        result = {
            "status": "registered",
            "dataset_id": dataset_id,
            "dataset_name": MAIL_DATASET_NAME,
            "dataset_created": created,
            "files": len(fetched),
            "uploaded": uploaded,
            "parse_started": parse_started,
            "parse_blocked": parse_blocked,
            "parse_results": parse_results,
            "parse_result": parse_results[-1] if parse_results else None,
        }
        update_job(
            status="completed",
            processed=len(fetched),
            total=req.max_messages,
            message=f"Imported {len(fetched)} IMAP messages",
            dataset_id=dataset_id,
            dataset_name=MAIL_DATASET_NAME,
            result=result,
        )
    except Exception as error:
        detail = _redact_imap_error(error, settings)
        update_job(
            status="failed",
            message=f"IMAP import failed: {detail}",
            result={"status": "failed", "error": detail, "dataset_name": MAIL_DATASET_NAME},
        )


def _redact_imap_error(error: Exception, settings: Any) -> str:
    detail = str(error)
    for secret in (getattr(settings, "password", ""),):
        if secret:
            detail = detail.replace(str(secret), "[redacted]")
    return detail


@router.get("/status")
async def mail_status(_user=Depends(require_user)):
    state = get_dataset_state()
    datasets = await state.backend.list_datasets()
    dataset = next((item for item in datasets if item.name == MAIL_DATASET_NAME), None)
    imap_settings = imap_settings_from_env()
    return {
        "component": "Е.Ж.И.К.",
        "status": "ready" if dataset else "not_created",
        "dataset_name": MAIL_DATASET_NAME,
        "dataset": asdict(dataset) if dataset else None,
        "supported": [".eml", ".emlx", ".msg"],
        "imap": imap_settings.public_payload(),
        "apple_mail": apple_mail_public_payload(),
    }


@router.get("/messages")
async def list_mail_messages(
    q: str = Query(default="", max_length=500),
    participant: str = Query(default="", max_length=300),
    thread_key: str = Query(default="", max_length=80),
    limit: int = Query(default=100, ge=1, le=1000),
    max_files: int = Query(default=2000, ge=1, le=10000),
    _user=Depends(require_user),
):
    state = get_dataset_state()
    dataset, messages = await _load_mail_messages(
        state,
        max_files=max_files,
        q=q,
        participant=participant,
        thread_key=thread_key,
    )
    selected = messages[:limit]
    return {
        "component": "Е.Ж.И.К.",
        "dataset_name": MAIL_DATASET_NAME,
        "dataset_id": dataset.id,
        "total": len(messages),
        "limit": limit,
        "messages": [message.payload() for message in selected],
    }


@router.get("/threads")
async def list_mail_threads(
    q: str = Query(default="", max_length=500),
    participant: str = Query(default="", max_length=300),
    limit: int = Query(default=50, ge=1, le=500),
    max_files: int = Query(default=2000, ge=1, le=10000),
    _user=Depends(require_user),
):
    state = get_dataset_state()
    dataset, messages = await _load_mail_messages(state, max_files=max_files, q=q, participant=participant)
    threads = group_mail_threads(messages)
    selected = threads[:limit]
    participants = sorted({person for message in messages for person in message.participants}, key=str.casefold)
    return {
        "component": "Е.Ж.И.К.",
        "dataset_name": MAIL_DATASET_NAME,
        "dataset_id": dataset.id,
        "total_threads": len(threads),
        "total_messages": len(messages),
        "participants": participants,
        "limit": limit,
        "threads": [thread.summary_payload() for thread in selected],
    }


@router.get("/threads/{thread_key}")
async def get_mail_thread(
    thread_key: str,
    max_files: int = Query(default=2000, ge=1, le=10000),
    _user=Depends(require_user),
):
    state = get_dataset_state()
    dataset, messages = await _load_mail_messages(state, max_files=max_files, thread_key=thread_key)
    threads = group_mail_threads(messages)
    if not threads:
        raise HTTPException(status_code=404, detail=f"mail thread not found: {thread_key}")
    thread = threads[0]
    return {
        "component": "Е.Ж.И.К.",
        "dataset_name": MAIL_DATASET_NAME,
        "dataset_id": dataset.id,
        **thread.payload(),
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

    parse_started, parse_blocked, parse_result = await _maybe_parse_mail_dataset(
        state,
        dataset_id,
        parse=req.parse,
        parse_limit=req.parse_limit,
    )

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


def _validate_archive_path(path: str) -> Path:
    """Путь к .olm/.pst внутри одобренных корней (LES_EXTERNAL_SOURCE_ROOTS)."""
    from proxy.config import external_source_roots

    raw = (path or "").strip()
    if not raw:
        raise HTTPException(400, "path обязателен")
    try:
        p = Path(raw).expanduser().resolve(strict=True)
    except FileNotFoundError as error:
        raise HTTPException(404, f"файл не найден: {raw}") from error
    except (OSError, RuntimeError) as error:
        raise HTTPException(400, f"некорректный путь: {raw}") from error
    if not p.is_file():
        raise HTTPException(400, "path должен быть файлом архива (.olm/.pst)")
    if p.suffix.lower() not in (".olm", ".pst"):
        raise HTTPException(400, "поддерживаются только .olm (Outlook для Mac) и .pst (Outlook Windows)")
    roots = external_source_roots()
    if roots and not any(p == r or r in p.parents for r in roots):
        raise HTTPException(403, f"архив вне одобренных корней LES_EXTERNAL_SOURCE_ROOTS: {p}")
    return p


def _extract_pst_to_eml(archive: Path, out_dir: Path, max_messages: int) -> list[Path]:
    try:
        import pypff  # noqa: F401
    except ImportError as error:
        raise RuntimeError(
            "PST требует libpff+pypff (не установлены). Установка (нужно одобрение): "
            "brew install libpff && uv add pypff. Либо экспортируй ящик в .olm/.eml."
        ) from error
    from email.message import EmailMessage

    from backend.pst_reader import PSTReader

    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for idx, msg in enumerate(PSTReader(str(archive)).iter_messages(), 1):
        if idx > max_messages:
            break
        em = EmailMessage()
        em["Subject"] = getattr(msg, "subject", "") or "(без темы)"
        if getattr(msg, "sender", ""):
            em["From"] = msg.sender
        if getattr(msg, "recipients", ""):
            em["To"] = msg.recipients
        if getattr(msg, "date", ""):
            em["Date"] = msg.date
        em.set_content(getattr(msg, "body", "") or "")
        eml = out_dir / f"pst_{idx:05d}.eml"
        eml.write_bytes(em.as_bytes())
        written.append(eml)
    return written


@router.post("/import-archive")
async def import_mail_archive(req: MailArchiveImportRequest, _admin=Depends(require_admin)):
    """Импорт почтового архива Outlook: .olm (Mac, stdlib) или .pst (Windows, нужен libpff).

    Извлекает письма → .eml → индексация в MAIL_Index (P0). Путь — внутри LES_EXTERNAL_SOURCE_ROOTS.
    """
    state = get_dataset_state()
    archive = _validate_archive_path(req.path)
    out_dir = Path("RAG_Content/MAIL") / archive.suffix.lstrip(".").upper() / archive.stem

    if archive.suffix.lower() == ".olm":
        from backend.olm_reader import extract_olm_to_eml
        eml_paths = await asyncio.to_thread(extract_olm_to_eml, archive, out_dir)
    else:
        try:
            eml_paths = await asyncio.to_thread(_extract_pst_to_eml, archive, out_dir, req.max_messages)
        except RuntimeError as error:
            raise HTTPException(status_code=501, detail=str(error)) from error

    eml_paths = eml_paths[: req.max_messages]
    if not eml_paths:
        raise HTTPException(422, f"в архиве {archive.name} не найдено писем")

    dataset_id, created = await _mail_dataset_id(state)
    uploaded: list[dict[str, Any]] = []
    for eml in eml_paths:
        doc_id = await state.backend.upload_file(dataset_id, eml, relative_path=f"{archive.stem}/{eml.name}")
        uploaded.append({"doc_id": doc_id, "relative_path": eml.name})

    parse_started, parse_blocked, parse_result = await _maybe_parse_mail_dataset(
        state, dataset_id, parse=req.parse, parse_limit=req.parse_limit,
    )
    return {
        "status": "registered", "component": "Е.Ж.И.К.",
        "archive": archive.name, "format": archive.suffix.lstrip("."),
        "dataset_id": dataset_id, "dataset_name": MAIL_DATASET_NAME, "dataset_created": created,
        "messages": len(eml_paths), "parse_started": parse_started,
        "parse_blocked": parse_blocked, "parse_result": parse_result,
    }


@router.post("/import-imap")
async def import_imap_mail(req: MailImapImportRequest, _admin=Depends(require_admin)):
    state = get_dataset_state()
    settings = imap_settings_from_env()
    # GUI-параметры перекрывают env для этого вызова (host/login/password/port/ssl/folders).
    overrides: dict[str, Any] = {}
    if req.host:
        overrides["host"] = req.host.strip()
    if req.login:
        overrides["login"] = req.login.strip()
    if req.password:
        overrides["password"] = req.password
    if req.port:
        overrides["port"] = int(req.port)
    if req.ssl is not None:
        overrides["ssl"] = bool(req.ssl)
    if req.folders:
        cleaned = [f.strip() for f in req.folders if f and f.strip()]
        if cleaned:
            overrides["folders"] = cleaned
    if overrides:
        settings = replace(settings, **overrides)
    if not settings.configured:
        raise HTTPException(
            status_code=400,
            detail="Нужны host, login и password (в полях подключения или MAIL_IMAP_* в .env)",
        )
    if req.background:
        job = state.job_service.create(
            "mail_imap_import",
            source="imap",
            dataset_name=MAIL_DATASET_NAME,
            total=req.max_messages,
            status="running",
            message="IMAP import queued",
        )
        job_id = str(job.get("id") or "")
        asyncio.create_task(_run_imap_import_job(state, job_id, req, settings))
        return {
            "status": "job_started",
            "component": "Е.Ж.И.К.",
            "job_id": job_id,
            "dataset_name": MAIL_DATASET_NAME,
            "max_messages": req.max_messages,
            "parse": req.parse,
            "parse_limit": req.parse_limit,
            "parse_batches": req.parse_batches,
        }
    try:
        fetched = await asyncio.to_thread(
            fetch_imap_eml_files,
            settings,
            max_messages=req.max_messages,
        )
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"imap import failed: {error}") from error

    if not fetched:
        return {
            "status": "no_new_mail",
            "component": "Е.Ж.И.К.",
            "dataset_name": MAIL_DATASET_NAME,
            "imap": settings.public_payload(),
            "files": 0,
            "uploaded": [],
            "parse_started": False,
            "parse_blocked": "",
            "parse_result": None,
        }

    dataset_id, created, uploaded = await _upload_fetched_mail(state, fetched)

    parse_started, parse_blocked, parse_result = await _maybe_parse_mail_dataset(
        state,
        dataset_id,
        parse=req.parse,
        parse_limit=req.parse_limit,
    )
    return {
        "status": "registered",
        "component": "Е.Ж.И.К.",
        "dataset_id": dataset_id,
        "dataset_name": MAIL_DATASET_NAME,
        "dataset_created": created,
        "imap": settings.public_payload(),
        "files": len(fetched),
        "uploaded": uploaded,
        "parse_started": parse_started,
        "parse_blocked": parse_blocked,
        "parse_result": parse_result,
    }


@router.post("/import-apple-mail")
async def import_apple_mail(req: MailAppleImportRequest, _admin=Depends(require_admin)):
    state = get_dataset_state()
    root = Path(req.mail_root).expanduser() if req.mail_root.strip() else None
    try:
        imported = await asyncio.to_thread(
            import_apple_mail_eml_files,
            mail_root=root,
            max_messages=req.max_messages,
        )
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"Apple Mail import failed: {error}") from error

    if not imported:
        return {
            "status": "no_local_mail",
            "component": "Е.Ж.И.К.",
            "dataset_name": MAIL_DATASET_NAME,
            "apple_mail": apple_mail_public_payload(),
            "files": 0,
            "uploaded": [],
            "parse_started": False,
            "parse_blocked": "",
            "parse_result": None,
        }

    dataset_id, created = await _mail_dataset_id(state)
    uploaded: list[dict[str, Any]] = []
    for item in imported:
        doc_id = await state.backend.upload_file(
            dataset_id,
            item.path,
            relative_path=item.relative_path,
        )
        uploaded.append({"doc_id": doc_id, **item.payload()})

    parse_started, parse_blocked, parse_result = await _maybe_parse_mail_dataset(
        state,
        dataset_id,
        parse=req.parse,
        parse_limit=req.parse_limit,
    )
    return {
        "status": "registered",
        "component": "Е.Ж.И.К.",
        "dataset_id": dataset_id,
        "dataset_name": MAIL_DATASET_NAME,
        "dataset_created": created,
        "apple_mail": apple_mail_public_payload(),
        "files": len(imported),
        "uploaded": uploaded,
        "parse_started": parse_started,
        "parse_blocked": parse_blocked,
        "parse_result": parse_result,
    }
