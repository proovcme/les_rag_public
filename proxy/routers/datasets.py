"""RAG dataset routes for LES Proxy."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, File, UploadFile

from backend.interface import DatasetInfo
from proxy.config import max_upload_bytes, rag_upload_suffixes
from proxy.security import require_admin, require_user
from proxy.storage.file_storage import save_upload_tmp, safe_upload_name, validate_source_folder

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rag", tags=["rag"])
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


@dataclass
class DatasetRouterState:
    rag_backend: Any
    job_service: Any
    job_tracker: dict
    log_history: Any
    parse_semaphore: asyncio.Semaphore
    sync_parse_semaphore: asyncio.Semaphore

    @property
    def backend(self):
        return self.rag_backend() if callable(self.rag_backend) else self.rag_backend


_state: DatasetRouterState | None = None


def set_dataset_state(state: DatasetRouterState) -> None:
    global _state
    _state = state


def get_dataset_state() -> DatasetRouterState:
    if _state is None:
        raise RuntimeError("dataset router state is not configured")
    return _state


@router.delete("/datasets/{dataset_id}")
async def delete_dataset(dataset_id: str, _admin=Depends(require_admin)):
    errors = []

    try:
        qdrant_url = os.getenv("QDRANT_URL", "http://qdrant:6333")
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"{qdrant_url}/collections/les_rag/points/delete",
                json={"filter": {"must": [{"key": "dataset_id", "match": {"value": dataset_id}}]}},
            )
    except Exception as e:
        errors.append(f"Qdrant: {e}")

    try:
        with sqlite3.connect("./data/les_meta.db") as conn:
            conn.execute("BEGIN")
            conn.execute("DELETE FROM documents WHERE dataset_id=?", (dataset_id,))
            conn.execute("DELETE FROM datasets WHERE id=?", (dataset_id,))
            conn.execute("COMMIT")
    except Exception as e:
        errors.append(f"SQLite: {e}")

    ds_dir = Path(f"./storage/datasets/{dataset_id}")
    if ds_dir.exists():
        await asyncio.to_thread(shutil.rmtree, ds_dir)

    logger.info("[DELETE] Dataset %s removed", dataset_id)
    return {"status": "deleted", "dataset_id": dataset_id, "errors": errors}


@router.delete("/datasets")
async def delete_all_datasets(_admin=Depends(require_admin)):
    errors = []

    try:
        qdrant_url = os.getenv("QDRANT_URL", "http://qdrant:6333")
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.delete(f"{qdrant_url}/collections/les_rag")
    except Exception as e:
        errors.append(f"Qdrant delete: {e}")

    try:
        with sqlite3.connect("./data/les_meta.db") as conn:
            conn.execute("BEGIN")
            conn.execute("DELETE FROM documents")
            conn.execute("DELETE FROM datasets")
            conn.execute("COMMIT")
    except Exception as e:
        errors.append(f"SQLite: {e}")

    ds_root = Path("./storage/datasets")
    if ds_root.exists():
        for path in ds_root.iterdir():
            if path.is_dir():
                await asyncio.to_thread(shutil.rmtree, path)

    logger.info("[DELETE] All datasets reset")
    return {"status": "reset", "errors": errors}


@router.get("/datasets")
async def list_datasets(_user=Depends(require_user)):
    return await get_dataset_state().backend.list_datasets()


@router.post("/datasets")
async def create_dataset(name: str, _admin=Depends(require_admin)):
    state = get_dataset_state()
    return {"id": await state.backend.create_dataset(name), "name": name}


@router.get("/sources")
async def list_sources(_user=Depends(require_user)):
    state = get_dataset_state()
    base_dir = Path("./RAG_Content")
    sources = []
    if base_dir.exists():
        ds_list = await state.backend.list_datasets()
        for folder in sorted(base_dir.iterdir()):
            if folder.is_dir() and not UUID_RE.match(folder.name):
                src_files = [path for path in folder.rglob("*") if path.is_file()]
                if not src_files:
                    continue
                ds_name = f"{folder.name}_Index"
                ds = next((dataset for dataset in ds_list if dataset.name == ds_name), None)
                sources.append(
                    {
                        "folder": folder.name,
                        "source_files": len(src_files),
                        "dataset_id": ds.id if ds else None,
                        "dataset_status": ds.status if ds else "NOT_CREATED",
                        "indexed_files": ds.doc_count if ds else 0,
                        "chunk_count": ds.chunk_count if ds else 0,
                    }
                )
    return sources


@router.post("/sync/{folder}")
async def sync_folder(folder: str, _admin=Depends(require_admin)):
    state = get_dataset_state()
    src_dir = validate_source_folder(folder)
    ds_list = await state.backend.list_datasets()
    ds_name = f"{folder}_Index"
    ds = next((dataset for dataset in ds_list if dataset.name == ds_name), None)
    if not ds:
        ds_id = await state.backend.create_dataset(ds_name)
        ds = DatasetInfo(id=ds_id, name=ds_name, status="IDLE", doc_count=0, chunk_count=0)

    now_ts = datetime.now()
    stale = [
        key
        for key, value in state.job_tracker.items()
        if value.get("started_at")
        and (now_ts - datetime.fromisoformat(value["started_at"])).total_seconds() > 86400
    ]
    for key in stale:
        del state.job_tracker[key]

    job = state.job_service.create(
        "rag_sync",
        source=folder,
        dataset_id=ds.id,
        dataset_name=ds_name,
        status="running",
        message="Сканирование...",
    )
    job_id = job["id"]
    state.job_tracker[job_id] = {
        "dataset_id": ds.id,
        "dataset_name": ds_name,
        "status": "SCANNING",
        "total": 0,
        "processed": 0,
        "started_at": job["started_at"],
        "message": "Сканирование...",
    }

    dest_dir = Path(f"./storage/datasets/{ds.id}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    new_count, skip_count, changed_count = 0, 0, 0
    files = [path for path in src_dir.rglob("*") if path.is_file()]
    state.job_tracker[job_id]["total"] = len(files)
    state.job_service.update(job_id, total=len(files), status="running")

    for index, source_file in enumerate(files):
        rel_path = source_file.relative_to(src_dir)
        dest = dest_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)

        stat = source_file.stat()
        is_new = not dest.exists()
        is_changed = False
        if not is_new:
            dest_stat = dest.stat()
            if stat.st_size != dest_stat.st_size or abs(stat.st_mtime - dest_stat.st_mtime) > 1.0:
                is_changed = True
        if is_new or is_changed:
            await state.backend.upload_file(ds.id, source_file, relative_path=rel_path.as_posix())
            if is_new:
                new_count += 1
            else:
                changed_count += 1
        else:
            skip_count += 1
        state.job_tracker[job_id]["processed"] = index + 1
        state.job_tracker[job_id]["message"] = (
            f"{'Новый' if is_new else 'Обновлён' if is_changed else 'Пропущен'}: {source_file.name}"
        )
        state.job_service.update(job_id, processed=index + 1, message=state.job_tracker[job_id]["message"])
        if (index + 1) % 20 == 0 or is_new or is_changed:
            state.log_history.append(
                f"[JOB {job_id}] {source_file.name} ({index + 1}/{len(files)}): "
                f"{'NEW' if is_new else 'CHANGED' if is_changed else 'SKIP'}"
            )
        await asyncio.sleep(0.1)

    force_reindex = (new_count + changed_count) == 0 and (ds.chunk_count or 0) == 0 and skip_count > 0

    if force_reindex:
        state.job_tracker[job_id]["status"] = "PARSING"
        state.job_tracker[job_id]["message"] = f"Индекс пуст — принудительная переиндексация {skip_count} файлов"
        state.job_service.update(job_id, status="running", message=state.job_tracker[job_id]["message"])
        logger.info("[JOB %s] Force reindex: 0 chunks in Qdrant, %s files on disk", job_id, skip_count)
    else:
        has_changes = (new_count + changed_count) > 0
        state.job_tracker[job_id]["status"] = "PARSING" if has_changes else "COMPLETED"
        state.job_tracker[job_id]["message"] = (
            f"Векторизация bge-m3: {new_count} новых, {changed_count} изм."
            if has_changes
            else f"Нет изменений (пропущено {skip_count})"
        )
        state.job_service.update(
            job_id,
            status="running" if has_changes else "completed",
            message=state.job_tracker[job_id]["message"],
            result={"new_files": new_count, "changed_files": changed_count, "skipped_files": skip_count},
        )

    if (new_count + changed_count) > 0 or force_reindex:
        async def _run():
            try:
                async with state.sync_parse_semaphore:
                    os.nice(10)
                    result = await state.backend.parse_dataset(ds.id)
                chunks = result.get("chunks", 0) if isinstance(result, dict) else 0
                elapsed = result.get("elapsed_sec", 0) if isinstance(result, dict) else 0
                state.job_tracker[job_id]["status"] = "COMPLETED"
                state.job_tracker[job_id]["finished_at"] = datetime.now().isoformat()
                state.job_tracker[job_id]["message"] = (
                    f"Готово: +{new_count} новых, ~{changed_count} обновлённых, "
                    f"пропущено {skip_count} | {chunks} чанков | {elapsed:.0f}с"
                )
                state.job_service.update(
                    job_id,
                    status="completed",
                    message=state.job_tracker[job_id]["message"],
                    result={
                        "new_files": new_count,
                        "changed_files": changed_count,
                        "skipped_files": skip_count,
                        "chunks": chunks,
                        "elapsed_sec": elapsed,
                    },
                )
                logger.info("[JOB %s] COMPLETED: %s chunks, %.0fs", job_id, chunks, elapsed)
            except Exception as e:
                state.job_tracker[job_id]["status"] = "FAILED"
                state.job_tracker[job_id]["finished_at"] = datetime.now().isoformat()
                state.job_tracker[job_id]["message"] = f"Ошибка: {str(e)}"
                state.job_service.update(job_id, status="failed", errors=1, message=state.job_tracker[job_id]["message"])
                logger.error("[JOB %s] FAILED: %s", job_id, e, exc_info=True)

        asyncio.create_task(_run())

    return {
        "status": "sync_started",
        "job_id": job_id,
        "dataset_id": ds.id,
        "new_files": new_count,
        "changed_files": changed_count,
        "skipped_files": skip_count,
    }


@router.post("/upload/{dataset_id}")
async def upload_file(dataset_id: str, file: UploadFile = File(...), _admin=Depends(require_admin)):
    state = get_dataset_state()
    original_name = safe_upload_name(file.filename or "upload.bin", rag_upload_suffixes())
    temp_path = await save_upload_tmp(
        file,
        allowed_suffixes=rag_upload_suffixes(),
        max_bytes=max_upload_bytes(),
    )
    doc_id = await state.backend.upload_file(dataset_id, temp_path, relative_path=original_name)

    async def _parse():
        try:
            async with state.parse_semaphore:
                await state.backend.parse_dataset(dataset_id)
        finally:
            temp_path.unlink(missing_ok=True)

    asyncio.create_task(_parse())
    return {"doc_id": doc_id, "status": "queued"}
