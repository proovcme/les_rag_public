"""Е.Ж.И.К. mail ingest routes."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import subprocess
import sys
import uuid
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, Request, UploadFile
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
from backend.mail_profile import build_mail_vector_profile
from proxy.routers.datasets import (
    DEFAULT_PARSE_BATCH_LIMIT,
    active_parse_scheduler_job,
    assert_parse_admission,
    get_dataset_state,
)
from proxy.security import require_admin, require_internal, require_user
from proxy.services.runtime_dispatcher import RuntimeDispatcher
from proxy.services.mail_registry_service import (
    get_mail_registry,
    mail_dataset_name,
)
from proxy.services.mail_sync_service import settings_for_account, sync_imap_account


router = APIRouter(prefix="/api/mail", tags=["mail"])
logger = logging.getLogger(__name__)


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


class MailAccountCreateRequest(BaseModel):
    kind: str
    label: str = Field(min_length=1, max_length=160)
    provider: str = ""
    host: str = ""
    port: int = Field(default=993, ge=1, le=65535)
    login: str = ""
    password: str = ""
    ssl: bool = True
    folders: list[str] = Field(default_factory=lambda: ["*"])
    native_account_id: str = ""


class MailAccountUpdateRequest(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=160)
    enabled: bool | None = None
    host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    login: str | None = None
    password: str | None = None
    ssl: bool | None = None
    folders: list[str] | None = None


class MailAccountSyncRequest(BaseModel):
    mode: str = "incremental"
    max_messages: int = Field(default=200, ge=1, le=2000)
    parse: bool = True
    parse_limit: int = Field(default=DEFAULT_PARSE_BATCH_LIMIT, ge=1, le=25)
    parse_batches: int = Field(default=20, ge=1, le=40)


class MailLegacyMigrationRequest(BaseModel):
    source_folder: str = "MAIL"
    max_files: int = Field(default=5000, ge=1, le=50000)
    parse: bool = True
    parse_limit: int = Field(default=DEFAULT_PARSE_BATCH_LIMIT, ge=1, le=25)


OUTLOOK_COLLECTOR_TASK = "LES E.ZH.I.K. Outlook Collector"


async def _mail_dataset_id(state: Any) -> tuple[str, bool]:
    """Legacy shared dataset retained only for backward-compatible routes."""
    datasets = await state.backend.list_datasets()
    existing = next((dataset for dataset in datasets if dataset.name == MAIL_DATASET_NAME), None)
    if existing:
        return existing.id, False
    return await state.backend.create_dataset(MAIL_DATASET_NAME), True


def _mail_account_config(req: MailAccountCreateRequest) -> dict[str, Any]:
    provider = req.provider.strip().casefold()
    host = req.host.strip()
    port = req.port
    ssl = req.ssl
    if provider == "yandex":
        host, port, ssl = "imap.yandex.ru", 993, True
    return {
        "provider": provider,
        "host": host,
        "port": port,
        "login": req.login.strip(),
        "ssl": ssl,
        "folders": [folder.strip() for folder in req.folders if folder.strip()] or ["*"],
    }


async def _create_mail_account(req: MailAccountCreateRequest) -> dict[str, Any]:
    kind = req.kind.strip().casefold()
    if kind not in {"imap", "outlook_classic"}:
        raise HTTPException(status_code=400, detail=f"unsupported mail account kind: {kind}")
    if kind == "imap" and not (req.login.strip() and (req.host.strip() or req.provider == "yandex")):
        raise HTTPException(status_code=400, detail="IMAP account requires host/provider and login")
    account_id = str(uuid.uuid4())
    dataset_name = mail_dataset_name(req.label, account_id)
    state = get_dataset_state()
    dataset_id = await state.backend.create_dataset(dataset_name)
    try:
        return get_mail_registry().create_account(
            kind=kind,
            label=req.label,
            config=_mail_account_config(req) if kind == "imap" else {
                "exclude_special": ["junk", "trash", "drafts"]
            },
            secret=req.password if kind == "imap" else "",
            native_account_id=req.native_account_id,
            account_id=account_id,
            dataset_id=dataset_id,
            dataset_name=dataset_name,
        )
    except Exception as error:
        # Dataset deletion is intentionally not attempted: destructive cleanup
        # requires an explicit operator action and the orphan remains visible.
        raise HTTPException(status_code=422, detail=str(error)) from error


async def _ensure_outlook_store_account(store_id: str, label: str) -> dict[str, Any]:
    registry = get_mail_registry()
    existing = registry.find_outlook_account(store_id=store_id)
    if existing:
        return existing
    return await _create_mail_account(
        MailAccountCreateRequest(
            kind="outlook_classic",
            label=label or "Outlook",
            native_account_id=store_id,
        )
    )


def _require_loopback(request: Request) -> None:
    host = str(request.client.host if request.client else "")
    if host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(status_code=403, detail="mail collector endpoint is loopback-only")


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


_mail_parse_tasks: dict[str, asyncio.Task] = {}
_outlook_upload_queues: dict[str, asyncio.Queue[Path]] = {}
_outlook_upload_tasks: dict[str, asyncio.Task] = {}
_outlook_queued_manifests: set[Path] = set()


async def _parse_mailbox_until_idle(account_id: str, dataset_id: str) -> None:
    """Debounced parser for sidecar intake; one task per mailbox dataset."""
    try:
        await asyncio.sleep(2.0)
        state = get_dataset_state()
        registry = get_mail_registry()
        final_result: dict[str, Any] | None = None
        for _batch in range(40):
            started, blocked, result = await _maybe_parse_mail_dataset(
                state, dataset_id, parse=True, parse_limit=25
            )
            if blocked or not started:
                break
            final_result = result
            if (
                not result
                or int(result.get("remaining_pending") or 0) <= 0
                or int(result.get("errors") or 0) > 0
            ):
                break
        if final_result and int(final_result.get("remaining_pending") or 0) == 0 and int(final_result.get("errors") or 0) == 0:
            for message in registry.list_messages(
                account_id=account_id, index_status="registered", limit=1000
            ):
                registry.mark_indexed(message["id"], status="indexed")
    finally:
        _mail_parse_tasks.pop(dataset_id, None)


def _schedule_mailbox_parse(account_id: str, dataset_id: str) -> None:
    current = _mail_parse_tasks.get(dataset_id)
    if current is None or current.done():
        _mail_parse_tasks[dataset_id] = asyncio.create_task(
            _parse_mailbox_until_idle(account_id, dataset_id)
        )


def _mail_state_root() -> Path:
    return Path(os.getenv("LES_MAIL_STATE_ROOT", "storage/mail")).resolve()


def _write_outlook_spool_manifest(path: Path, payload: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def _register_spooled_outlook_message(
    registry: Any,
    payload: dict[str, str],
) -> tuple[dict[str, Any], bool]:
    return registry.register_message(
        account_id=payload["account_id"],
        raw_path=payload["raw_path"],
        relative_path=payload["relative_path"],
        source_kind="outlook_classic",
        native_id=payload["entry_id"],
        internet_message_id=payload["internet_message_id"],
        folder_native_id=payload["folder_id"],
        folder_path=payload["folder_path"],
        outlook_store_id=payload["store_id"],
        outlook_entry_id=payload["entry_id"],
        received_at=payload["received_at"],
    )


async def _drain_outlook_uploads(account_id: str, dataset_id: str) -> None:
    """Register durable spool files after the Outlook COM request has returned."""
    queue = _outlook_upload_queues[dataset_id]
    uploaded = False
    try:
        state = get_dataset_state()
        registry = get_mail_registry()
        while True:
            try:
                manifest_path = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            registered: dict[str, Any] | None = None
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                raw_path = Path(payload["raw_path"]).resolve()
                state_root = _mail_state_root()
                if state_root != raw_path and state_root not in raw_path.parents:
                    raise ValueError("Outlook spool points outside mail state root")
                registered, _created = await asyncio.to_thread(
                    _register_spooled_outlook_message,
                    registry,
                    payload,
                )
                registry.mark_indexed(registered["id"], status="queued")
                doc_id = await state.backend.upload_file(
                    dataset_id,
                    raw_path,
                    relative_path=payload["relative_path"],
                )
                registry.mark_indexed(registered["id"], rag_doc_id=doc_id, status="registered")
                manifest_path.unlink(missing_ok=True)
                uploaded = True
            except Exception:
                if registered is not None:
                    registry.mark_indexed(registered["id"], status="error")
                logger.exception(
                    "Outlook spool registration failed",
                    extra={"outlook_manifest": manifest_path.name, "dataset_id": dataset_id},
                )
            finally:
                _outlook_queued_manifests.discard(manifest_path)
                queue.task_done()
    finally:
        _outlook_upload_tasks.pop(dataset_id, None)
        if uploaded:
            _schedule_mailbox_parse(account_id, dataset_id)


def _queue_outlook_spool_manifest(
    *,
    account_id: str,
    dataset_id: str,
    manifest_path: Path,
) -> tuple[int, asyncio.Task]:
    queue = _outlook_upload_queues.setdefault(dataset_id, asyncio.Queue())
    manifest_path = manifest_path.resolve()
    if manifest_path not in _outlook_queued_manifests:
        _outlook_queued_manifests.add(manifest_path)
        queue.put_nowait(manifest_path)
    current = _outlook_upload_tasks.get(dataset_id)
    if current is None or current.done():
        current = asyncio.create_task(_drain_outlook_uploads(account_id, dataset_id))
        _outlook_upload_tasks[dataset_id] = current
    return queue.qsize(), current


def recover_outlook_spool() -> int:
    """Resume durable Outlook manifests left by a proxy restart."""
    queued = 0
    for manifest_path in _mail_state_root().glob("*/spool/*.json"):
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            _queue_outlook_spool_manifest(
                account_id=str(payload["account_id"]),
                dataset_id=str(payload["dataset_id"]),
                manifest_path=manifest_path,
            )
            queued += 1
        except Exception:
            logger.exception("Invalid Outlook spool manifest", extra={"manifest": manifest_path.name})
    return queued


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


@router.get("/accounts")
async def list_mail_accounts(_user=Depends(require_user)):
    registry = get_mail_registry()
    return {
        "component": "Е.Ж.И.К.",
        "accounts": registry.list_accounts(),
        "folders": registry.list_folders(),
    }


@router.post("/accounts")
async def create_mail_account(req: MailAccountCreateRequest, _admin=Depends(require_admin)):
    account = await _create_mail_account(req)
    return {"status": "created", "account": account}


@router.patch("/accounts/{account_id}")
async def update_mail_account(
    account_id: str,
    req: MailAccountUpdateRequest,
    _admin=Depends(require_admin),
):
    registry = get_mail_registry()
    try:
        current = registry.get_account(account_id, include_secret_state=False)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="mail account not found") from error
    config: dict[str, Any] = {}
    for key in ("host", "port", "login", "ssl", "folders"):
        value = getattr(req, key)
        if value is not None:
            config[key] = value
    try:
        account = registry.update_account(
            account_id,
            label=req.label,
            enabled=req.enabled,
            config=config or None,
            secret=req.password,
        )
    except Exception as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    assert account["dataset_id"] == current["dataset_id"]
    return {"status": "updated", "account": account}


@router.post("/accounts/{account_id}/test")
async def test_mail_account(account_id: str, _admin=Depends(require_admin)):
    registry = get_mail_registry()
    try:
        account = registry.get_account(account_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="mail account not found") from error
    if account["kind"] == "outlook_classic":
        return {"status": "ready", "kind": account["kind"], "dataset_id": account["dataset_id"]}
    try:
        settings = settings_for_account(account, registry.account_secret(account_id))
        from backend.mail_ingest import _open_imap_client

        client = await asyncio.to_thread(_open_imap_client, settings)
        try:
            await asyncio.to_thread(client.login, settings.login, settings.password)
            status, _rows = await asyncio.to_thread(client.list)
            if status != "OK":
                raise RuntimeError("IMAP LIST failed")
        finally:
            try:
                await asyncio.to_thread(client.logout)
            except Exception:
                pass
    except Exception as error:
        detail = _redact_imap_error(error, settings if "settings" in locals() else None)
        raise HTTPException(status_code=502, detail=f"IMAP test failed: {detail}") from error
    return {"status": "ready", "kind": "imap", "dataset_id": account["dataset_id"]}


@router.post("/accounts/{account_id}/sync")
async def sync_mail_account(
    account_id: str,
    req: MailAccountSyncRequest,
    _admin=Depends(require_admin),
):
    registry = get_mail_registry()
    try:
        account = registry.get_account(account_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="mail account not found") from error
    if account["kind"] != "imap":
        raise HTTPException(status_code=409, detail="Outlook is synchronized by the Windows sidecar")
    if req.mode not in {"full", "incremental"}:
        raise HTTPException(status_code=400, detail="mode must be full or incremental")
    settings = settings_for_account(account, registry.account_secret(account_id))
    try:
        fetched = await asyncio.to_thread(
            sync_imap_account,
            settings,
            registry,
            account_id=account_id,
            mode=req.mode,
            max_messages=req.max_messages,
        )
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=f"IMAP sync failed: {_redact_imap_error(error, settings)}",
        ) from error

    state = get_dataset_state()
    uploaded: list[dict[str, Any]] = []
    for registered in fetched:
        message = registry.get_message(registered.message_id)
        doc_id = await state.backend.upload_file(
            account["dataset_id"],
            registered.file.path,
            relative_path=registered.file.relative_path,
        )
        registry.mark_indexed(message["id"], rag_doc_id=doc_id, status="registered")
        uploaded.append({"doc_id": doc_id, **registered.payload()})

    parse_started = False
    parse_blocked = ""
    parse_results: list[dict[str, Any]] = []
    if req.parse:
        for _batch in range(req.parse_batches):
            started, blocked, result = await _maybe_parse_mail_dataset(
                state, account["dataset_id"], parse=True, parse_limit=req.parse_limit
            )
            parse_started = parse_started or started
            parse_blocked = blocked
            if result:
                parse_results.append(result)
            if (
                blocked
                or not result
                or int(result.get("remaining_pending") or 0) <= 0
                or int(result.get("errors") or 0) > 0
            ):
                break
    parse_result = parse_results[-1] if parse_results else None
    if (
        parse_started and parse_result
        and int(parse_result.get("remaining_pending") or 0) == 0
        and int(parse_result.get("errors") or 0) == 0
    ):
        for item in uploaded:
            registry.mark_indexed(item["registry_message_id"], rag_doc_id=item["doc_id"], status="indexed")
    return {
        "status": "registered" if uploaded else "no_new_mail",
        "account_id": account_id,
        "dataset_id": account["dataset_id"],
        "dataset_name": account["dataset_name"],
        "files": len(uploaded),
        "uploaded": uploaded,
        "parse_started": parse_started,
        "parse_blocked": parse_blocked,
        "parse_results": parse_results,
        "parse_result": parse_result,
    }


@router.post("/accounts/{account_id}/migrate-legacy")
async def migrate_legacy_mail_to_account(
    account_id: str,
    req: MailLegacyMigrationRequest,
    _admin=Depends(require_admin),
):
    """Additively copy an operator-selected legacy mail tree into one mailbox dataset."""
    registry = get_mail_registry()
    try:
        account = registry.get_account(account_id, include_secret_state=False)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="mail account not found") from error
    try:
        source_dir = resolve_mail_source_folder(req.source_folder)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    files = iter_mail_files(source_dir, max_files=req.max_files)
    state = get_dataset_state()
    registered_count = 0
    uploaded: list[dict[str, str]] = []
    for source_file in files:
        source_relative = source_file.relative_to(source_dir).as_posix()
        relative_path = f"legacy/{req.source_folder.strip('/')}/{source_relative}"
        message, created = registry.register_message(
            account_id=account_id,
            raw_path=source_file,
            relative_path=relative_path,
            source_kind=account["kind"],
            native_id=f"legacy:{source_relative}",
            folder_native_id="legacy",
            folder_path=req.source_folder,
        )
        doc_id = await state.backend.upload_file(
            account["dataset_id"], source_file, relative_path=relative_path
        )
        registry.mark_indexed(message["id"], rag_doc_id=doc_id, status="registered")
        registered_count += int(created)
        uploaded.append({"message_id": message["id"], "doc_id": doc_id, "relative_path": relative_path})
    parse_started, parse_blocked, parse_result = await _maybe_parse_mail_dataset(
        state,
        account["dataset_id"],
        parse=req.parse and bool(uploaded),
        parse_limit=req.parse_limit,
    )
    if req.parse and uploaded and (
        not parse_result or int(parse_result.get("remaining_pending") or 0) > 0
    ):
        _schedule_mailbox_parse(account_id, account["dataset_id"])
    return {
        "status": "registered",
        "account_id": account_id,
        "dataset_id": account["dataset_id"],
        "source_folder": req.source_folder,
        "files": len(uploaded),
        "new_messages": registered_count,
        "uploaded": uploaded,
        "legacy_source_retained": True,
        "parse_started": parse_started,
        "parse_blocked": parse_blocked,
        "parse_result": parse_result,
    }


@router.post("/collector/import", status_code=202)
async def import_outlook_message(
    request: Request,
    message: UploadFile = File(...),
    store_id: str = Form(...),
    entry_id: str = Form(...),
    store_label: str = Form(default="Outlook"),
    folder_id: str = Form(default=""),
    folder_path: str = Form(default=""),
    internet_message_id: str = Form(default=""),
    received_at: str = Form(default=""),
    _internal=Depends(require_internal),
):
    _require_loopback(request)
    suffix = Path(message.filename or "message.msg").suffix.casefold()
    if suffix not in {".msg", ".eml"}:
        raise HTTPException(status_code=400, detail="collector accepts only .msg or .eml")
    raw = await message.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty mail message")
    account = await _ensure_outlook_store_account(store_id, store_label)
    digest = hashlib.sha256(raw).hexdigest()
    root = _mail_state_root() / account["id"] / "raw"
    root.mkdir(parents=True, exist_ok=True)
    raw_path = root / f"{digest}{suffix}"
    created_snapshot = not raw_path.exists()
    if created_snapshot:
        temporary = raw_path.with_name(f".{raw_path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_bytes(raw)
        os.replace(temporary, raw_path)
    relative_path = f"outlook/{account['id']}/{digest}{suffix}"
    locator_digest = hashlib.sha256(f"{store_id}|{entry_id}|{folder_id}".encode("utf-8")).hexdigest()[:16]
    manifest_path = root.parent / "spool" / f"{digest}-{locator_digest}.json"
    _write_outlook_spool_manifest(
        manifest_path,
        {
            "account_id": account["id"],
            "dataset_id": account["dataset_id"],
            "store_id": store_id,
            "entry_id": entry_id,
            "folder_id": folder_id,
            "folder_path": folder_path,
            "internet_message_id": internet_message_id,
            "received_at": received_at,
            "raw_path": str(raw_path),
            "relative_path": relative_path,
        },
    )
    queue_depth, _task = _queue_outlook_spool_manifest(
        account_id=account["id"],
        dataset_id=account["dataset_id"],
        manifest_path=manifest_path,
    )
    return {
        "status": "accepted",
        "created": created_snapshot,
        "account_id": account["id"],
        "dataset_id": account["dataset_id"],
        "snapshot_id": digest,
        "index_status": "queued",
        "queue_depth": queue_depth,
    }


@router.post("/collector/run")
async def run_outlook_collector(
    request: Request,
    _admin=Depends(require_admin),
):
    _require_loopback(request)
    if not sys.platform.startswith("win"):
        raise HTTPException(status_code=501, detail="manual Outlook collection is available on Windows")
    result = subprocess.run(
        ["schtasks", "/run", "/tn", OUTLOOK_COLLECTOR_TASK],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        raise HTTPException(status_code=503, detail="could not start Outlook collector task")
    return {"status": "started", "mode": "manual", "hard_limit_seconds": 15}


@router.post("/messages/{message_id}/open")
async def open_mail_message(
    message_id: str,
    request: Request,
    _user=Depends(require_user),
):
    _require_loopback(request)
    try:
        message = get_mail_registry().get_message(message_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="mail message not found") from error
    if message["source_kind"] != "outlook_classic":
        raise HTTPException(status_code=409, detail="only Outlook messages can be opened in Outlook")
    if not sys.platform.startswith("win"):
        raise HTTPException(status_code=501, detail="opening Outlook originals is available on Windows")
    collector = Path(
        os.getenv(
            "LES_OUTLOOK_COLLECTOR_EXE",
            str(Path(os.getenv("LOCALAPPDATA", "")) / "LES" / "bin" / "LesMailPoller.exe"),
        )
    )
    if not collector.is_file():
        raise HTTPException(status_code=503, detail="Outlook collector is not installed")
    encode = lambda value: base64.urlsafe_b64encode(str(value).encode("utf-8")).decode("ascii")
    subprocess.Popen(
        [str(collector), "--open", encode(message["outlook_store_id"]), encode(message["outlook_entry_id"])],
        close_fds=True,
    )
    return {"status": "opening", "message_id": message_id}


@router.get("/messages/{message_id}")
async def get_registered_mail_message(message_id: str, _user=Depends(require_user)):
    registry = get_mail_registry()
    try:
        message = registry.get_message(message_id)
        account = registry.get_account(message["account_id"], include_secret_state=False)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="mail message not found") from error
    path = Path(message["raw_path"])
    if not path.is_file():
        raise HTTPException(status_code=410, detail="mail snapshot is missing")
    profile = await asyncio.to_thread(build_mail_vector_profile, path, source_dir=path.parent)
    return {
        "component": "Е.Ж.И.К.",
        "account": account,
        "message": message,
        "profile": profile.payload(),
        "body": profile.body,
        "attachments": [item.payload() for item in profile.attachments],
    }


@router.get("/status")
async def mail_status(_user=Depends(require_user)):
    state = get_dataset_state()
    datasets = await state.backend.list_datasets()
    dataset = next((item for item in datasets if item.name == MAIL_DATASET_NAME), None)
    imap_settings = imap_settings_from_env()
    autosync: dict[str, Any] = {}
    try:  # статус внутреннего IMAP-поллера (proxy.app.mail_autosync) — ленивый импорт без циклов
        import os as _os
        from proxy.app import mail_autosync as _autosync
        autosync = {**_autosync, "poll_sec": int(_os.getenv("MAIL_IMAP_POLL_SEC", "180") or "180")}
    except Exception:
        pass
    registry = get_mail_registry()
    spool_pending = sum(1 for _ in _mail_state_root().glob("*/spool/*.json"))
    return {
        "component": "Е.Ж.И.К.",
        "status": "ready" if dataset else "not_created",
        "dataset_name": MAIL_DATASET_NAME,
        "dataset": asdict(dataset) if dataset else None,
        "supported": [".eml", ".emlx", ".msg"],
        "imap": imap_settings.public_payload(),
        "autosync": autosync,
        "apple_mail": apple_mail_public_payload(),
        "accounts": registry.list_accounts(),
        "summary": {
            **registry.status_summary(),
            "spool_pending": spool_pending,
            "collector_running": any(not task.done() for task in _outlook_upload_tasks.values()),
        },
    }


@router.get("/messages")
async def list_mail_messages(
    account_id: str = Query(default="", max_length=80),
    folder: str = Query(default="", max_length=500),
    q: str = Query(default="", max_length=500),
    participant: str = Query(default="", max_length=300),
    thread_key: str = Query(default="", max_length=80),
    date_from: str = Query(default="", max_length=40),
    date_to: str = Query(default="", max_length=40),
    index_status: str = Query(default="", max_length=40),
    limit: int = Query(default=100, ge=1, le=1000),
    max_files: int = Query(default=2000, ge=1, le=10000),
    _user=Depends(require_user),
):
    account_id = account_id if isinstance(account_id, str) else ""
    folder = folder if isinstance(folder, str) else ""
    date_from = date_from if isinstance(date_from, str) else ""
    date_to = date_to if isinstance(date_to, str) else ""
    index_status = index_status if isinstance(index_status, str) else ""
    if account_id:
        try:
            account = get_mail_registry().get_account(account_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="mail account not found") from error
        messages = get_mail_registry().list_messages(
            account_id=account_id,
            folder=folder,
            q=q,
            participant=participant,
            date_from=date_from,
            date_to=date_to,
            index_status=index_status,
            limit=limit,
        )
        if thread_key:
            messages = [item for item in messages if item["thread_key"] == thread_key]
        return {
            "component": "Е.Ж.И.К.",
            "account_id": account_id,
            "dataset_name": account["dataset_name"],
            "dataset_id": account["dataset_id"],
            "total": len(messages),
            "limit": limit,
            "messages": messages,
        }
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
    account_id: str = Query(default="", max_length=80),
    q: str = Query(default="", max_length=500),
    participant: str = Query(default="", max_length=300),
    limit: int = Query(default=50, ge=1, le=500),
    max_files: int = Query(default=2000, ge=1, le=10000),
    _user=Depends(require_user),
):
    state = get_dataset_state()
    account_id = account_id if isinstance(account_id, str) else ""
    if account_id:
        try:
            account = get_mail_registry().get_account(account_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="mail account not found") from error
        datasets = await state.backend.list_datasets()
        dataset = next((item for item in datasets if item.id == account["dataset_id"]), None)
        if not dataset:
            raise HTTPException(status_code=404, detail="mailbox dataset not found")
        content_dir = getattr(state.backend, "content_dir", None)
        if content_dir is None:
            raise HTTPException(status_code=501, detail="mail view requires file-backed backend")
        dataset_root = Path(content_dir).resolve() / dataset.id
        messages = await asyncio.to_thread(read_mail_messages, dataset_root, max_files=max_files)
        messages = filter_mail_messages(messages, q=q, participant=participant)
        threads = group_mail_threads(messages)
        participants = sorted({person for message in messages for person in message.participants}, key=str.casefold)
        return {
            "component": "Е.Ж.И.К.",
            "account_id": account_id,
            "dataset_name": account["dataset_name"],
            "dataset_id": account["dataset_id"],
            "total_threads": len(threads),
            "total_messages": len(messages),
            "participants": participants,
            "limit": limit,
            "threads": [thread.summary_payload() for thread in threads[:limit]],
        }
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


@router.post("/push")
async def push_mail(payload: dict[str, Any] = Body(...), _user=Depends(require_user)):
    """Письмо из Outlook-плагина → классификация вложений → маршрут (КП→КАЦ, смета/док→RAG, скан→приёмка).

    Контракт: {subject, from, date, body, attachments:[{name, content_type, content_b64}]}.
    Принцип [[local-bases-untrusted-channel]]: плагин шлёт в ЛОКАЛЬНЫЙ ЛЕС, не в облако.
    """
    import hashlib

    from proxy.services import mail_push_service as mps

    subject = str(payload.get("subject") or "")
    sender = str(payload.get("from") or "")
    date = str(payload.get("date") or "")
    body = str(payload.get("body") or "")
    attachments = payload.get("attachments") or []
    if not isinstance(attachments, list):
        raise HTTPException(status_code=400, detail="attachments must be a list")

    msg_id = hashlib.sha1(f"{subject}|{sender}|{date}|{len(body)}|{len(attachments)}".encode()).hexdigest()[:12]
    push_dir = Path("storage/mail_push") / msg_id
    saved = mps.save_attachments(attachments, push_dir)

    state = get_dataset_state()
    dataset_id, created = await _mail_dataset_id(state)
    uploaded: list[dict[str, Any]] = []

    # тело письма → текстовый документ в RAG (mail-датасет)
    body_path = push_dir / f"{msg_id}.txt"
    body_path.write_text(mps.email_as_text(subject, sender, date, body), encoding="utf-8")
    try:
        body_doc = await state.backend.upload_file(
            dataset_id, body_path, relative_path=f"push/{msg_id}/{msg_id}.txt")
        uploaded.append({"doc_id": body_doc, "name": "(тело письма)"})
    except Exception as exc:  # noqa: BLE001 — регистрация best-effort, маршрут не должен падать
        uploaded.append({"name": "(тело письма)", "error": str(exc)})

    plan = mps.route_push(saved)

    # смета/документ-вложения → RAG; КП и сканы НЕ в общий RAG (КП→КАЦ, скан→приёмку)
    for s in plan["to_rag"]:
        try:
            doc_id = await state.backend.upload_file(
                dataset_id, Path(s["path"]), relative_path=f"push/{msg_id}/{Path(s['path']).name}")
            uploaded.append({"doc_id": doc_id, "name": s["name"]})
        except Exception as exc:  # noqa: BLE001
            uploaded.append({"name": s["name"], "error": str(exc)})

    return {
        "ok": True,
        "message_id": msg_id,
        "dataset_id": dataset_id,
        "dataset_created": created,
        "routed": plan["routed"],
        "kac": plan["kac"],
        "kp_count": plan["kp_count"],
        "uploaded": uploaded,
        "note": "КП → КАЦ; смета/док → RAG; скан → приёмка ИД (очередь pending)",
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
        if getattr(msg, "from_addr", ""):
            em["From"] = msg.from_addr
        to_addrs = getattr(msg, "to_addrs", None) or []
        cc_addrs = getattr(msg, "cc_addrs", None) or []
        if to_addrs:
            em["To"] = ", ".join(to_addrs)
        if cc_addrs:
            em["Cc"] = ", ".join(cc_addrs)
        if getattr(msg, "date", ""):
            em["Date"] = msg.date
        body = getattr(msg, "body_text", "") or getattr(msg, "body_html", "") or ""
        em.set_content(body)
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
        except RuntimeError as error:  # нет libpff/pypff
            raise HTTPException(status_code=501, detail=str(error)) from error
        except Exception as error:  # битый/нечитаемый PST
            raise HTTPException(status_code=422, detail=f"не удалось прочитать .pst: {error}") from error

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
