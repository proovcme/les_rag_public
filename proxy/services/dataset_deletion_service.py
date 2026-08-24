"""Fail-closed, recoverable deletion of RAG datasets.

Cross-store deletion cannot be made truly atomic across Qdrant, SQLite and the
filesystem.  This coordinator therefore creates recovery evidence first,
verifies every remote mutation, and only then commits the catalog deletion.
If Qdrant or lexical cleanup fails, MetaDB and project links remain intact.
"""

from __future__ import annotations

import asyncio
import shutil
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

import httpx


class DatasetDeletionError(RuntimeError):
    """A destructive phase was not proven complete; catalog data was preserved."""


_DELETE_LOCK = asyncio.Lock()


def _recovery_root(meta_db_path: Path) -> Path:
    default = meta_db_path.parent.parent / "recovery" / "dataset-deletions"
    root = default.resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _new_recovery_dir(meta_db_path: Path, label: str) -> Path:
    root = _recovery_root(meta_db_path)
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
    target = (root / f"{stamp}-{label}-{uuid.uuid4().hex[:8]}").resolve()
    if root != target.parent:
        raise DatasetDeletionError("recovery path escaped the configured recovery root")
    target.mkdir(parents=False, exist_ok=False)
    return target


def _backup_sqlite(source: Path, target: Path) -> None:
    if not source.is_file():
        raise DatasetDeletionError(f"MetaDB is missing: {source}")
    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
    if not target.is_file() or target.stat().st_size == 0:
        raise DatasetDeletionError("MetaDB recovery backup is empty")


def _dataset_exists(meta_db_path: Path, dataset_id: str) -> bool:
    with sqlite3.connect(meta_db_path) as conn:
        row = conn.execute("SELECT 1 FROM datasets WHERE id=?", (dataset_id,)).fetchone()
    return bool(row)


def _delete_catalog_rows(meta_db_path: Path, dataset_ids: list[str]) -> None:
    marks = ",".join("?" for _ in dataset_ids)
    with sqlite3.connect(meta_db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        if "structured_rules" in tables:
            for dataset_id in dataset_ids:
                conn.execute(
                    "DELETE FROM structured_rules WHERE document_id=? OR file_key IN "
                    "(SELECT file_name FROM documents WHERE dataset_id=?)",
                    (dataset_id, dataset_id),
                )
        if "les_project_links" in tables:
            conn.execute(
                f"DELETE FROM les_project_links WHERE kind='dataset' AND ref IN ({marks})",
                dataset_ids,
            )
        conn.execute(f"DELETE FROM documents WHERE dataset_id IN ({marks})", dataset_ids)
        conn.execute(f"DELETE FROM datasets WHERE id IN ({marks})", dataset_ids)
        conn.commit()


def _quarantine_storage(storage_dirs: list[Path], recovery_dir: Path) -> list[str]:
    moved: list[str] = []
    quarantine = recovery_dir / "storage"
    for source in storage_dirs:
        if not source.exists():
            continue
        quarantine.mkdir(parents=True, exist_ok=True)
        target = quarantine / source.name
        if target.exists():
            raise DatasetDeletionError(f"recovery storage target already exists: {target}")
        shutil.move(str(source), str(target))
        moved.append(str(target))
    return moved


def _dataset_filter(dataset_ids: list[str]) -> dict[str, Any]:
    if len(dataset_ids) == 1:
        match: dict[str, Any] = {"value": dataset_ids[0]}
    else:
        match = {"any": dataset_ids}
    return {"must": [{"key": "dataset_id", "match": match}]}


async def _qdrant_count(
    client: httpx.AsyncClient,
    *,
    qdrant_url: str,
    collection: str,
    dataset_ids: list[str],
) -> int:
    response = await client.post(
        f"{qdrant_url}/collections/{collection}/points/count",
        json={"filter": _dataset_filter(dataset_ids), "exact": True},
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") != "ok":
        raise DatasetDeletionError("Qdrant count did not return status=ok")
    return int((payload.get("result") or {}).get("count") or 0)


async def _qdrant_snapshot(
    client: httpx.AsyncClient,
    *,
    qdrant_url: str,
    collection: str,
) -> dict[str, Any]:
    response = await client.post(f"{qdrant_url}/collections/{collection}/snapshots")
    response.raise_for_status()
    payload = response.json()
    result = payload.get("result") or {}
    if payload.get("status") != "ok" or not result.get("name"):
        raise DatasetDeletionError("Qdrant snapshot was not confirmed")
    return dict(result)


async def delete_datasets_safely(
    *,
    dataset_ids: list[str],
    qdrant_url: str,
    collection: str,
    meta_db_path: str | Path,
    storage_root: str | Path,
    lexical_index: Any,
) -> dict[str, Any]:
    """Delete selected datasets only after recoverable, verified preparation."""
    unique_ids = list(dict.fromkeys(str(value).strip() for value in dataset_ids if str(value).strip()))
    if not unique_ids:
        raise KeyError("no datasets selected")
    db_path = Path(meta_db_path).resolve()
    missing = [dataset_id for dataset_id in unique_ids if not _dataset_exists(db_path, dataset_id)]
    if missing:
        raise KeyError(f"datasets not found: {', '.join(missing)}")

    async with _DELETE_LOCK:
        recovery_dir = _new_recovery_dir(db_path, "datasets")
        db_backup = recovery_dir / db_path.name
        _backup_sqlite(db_path, db_backup)

        qdrant_base = qdrant_url.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                snapshot = await _qdrant_snapshot(
                    client,
                    qdrant_url=qdrant_base,
                    collection=collection,
                )
                points_before = await _qdrant_count(
                    client,
                    qdrant_url=qdrant_base,
                    collection=collection,
                    dataset_ids=unique_ids,
                )
                response = await client.post(
                    f"{qdrant_base}/collections/{collection}/points/delete",
                    params={"wait": "true"},
                    json={"filter": _dataset_filter(unique_ids)},
                )
                response.raise_for_status()
                payload = response.json()
                if payload.get("status") != "ok":
                    raise DatasetDeletionError("Qdrant delete did not return status=ok")
                points_after = await _qdrant_count(
                    client,
                    qdrant_url=qdrant_base,
                    collection=collection,
                    dataset_ids=unique_ids,
                )
        except Exception as exc:
            if isinstance(exc, DatasetDeletionError):
                raise
            raise DatasetDeletionError(f"Qdrant deletion was not proven: {exc}") from exc

        if points_after != 0:
            raise DatasetDeletionError(
                f"Qdrant still contains {points_after} selected points; MetaDB was preserved"
            )

        try:
            lexical_deleted = 0
            for dataset_id in unique_ids:
                lexical_deleted += int(
                    lexical_index.delete_dataset(collection, dataset_id=dataset_id) or 0
                )
        except Exception as exc:
            raise DatasetDeletionError(
                f"lexical deletion failed after the recoverable Qdrant snapshot; MetaDB was preserved: {exc}"
            ) from exc

        _delete_catalog_rows(db_path, unique_ids)
        storage_base = Path(storage_root).resolve()
        storage_dirs = [(storage_base / dataset_id).resolve() for dataset_id in unique_ids]
        for path in storage_dirs:
            if storage_base not in path.parents:
                raise DatasetDeletionError(f"unsafe dataset storage path: {path}")
        quarantined = _quarantine_storage(storage_dirs, recovery_dir)

        return {
            "status": "deleted",
            "dataset_ids": unique_ids,
            "points_before": points_before,
            "points_after": points_after,
            "lexical_deleted": lexical_deleted,
            "recovery": {
                "directory": str(recovery_dir),
                "meta_db": str(db_backup),
                "qdrant_snapshot": snapshot,
                "storage": quarantined,
            },
        }
