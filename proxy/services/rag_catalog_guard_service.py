"""Startup self-diagnostics and conservative catalog self-recovery."""

from __future__ import annotations

import asyncio
import sqlite3
import time
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

from proxy.services.lexical_index_service import LexicalIndex
from proxy.services.rag_catalog_recovery_service import (
    link_recovered_datasets,
    rebuild_lexical_catalog,
    recover_metadb_catalog,
    scan_qdrant_catalog,
)


_LOCK = asyncio.Lock()
_STATE: dict[str, Any] = {
    "schema": "les.rag.catalog-guard.v1",
    "status": "not_run",
    "error_code": "",
}


def catalog_guard_state() -> dict[str, Any]:
    return dict(_STATE)


def _set_state(payload: dict[str, Any]) -> dict[str, Any]:
    _STATE.clear()
    _STATE.update(payload)
    return dict(_STATE)


def infer_recovered_dataset_name(orphan: dict[str, Any]) -> str:
    """Use only preserved path identity; never infer professional semantics."""
    roots = []
    for file_name in orphan.get("sample_files") or []:
        normalized = str(file_name or "").replace("\\", "/").strip("/")
        if normalized:
            roots.append(PurePosixPath(normalized).parts[0])
    if roots and len(set(roots)) == 1 and roots[0].strip():
        return roots[0].strip()[:160]
    return f"Восстановленный датасет {str(orphan.get('dataset_id') or '')[:8]}"


def _backup_metadb(meta_db_path: Path) -> Path:
    root = (meta_db_path.parent.parent / "recovery" / "catalog-self-heal").resolve()
    root.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
    target = (root / f"{stamp}-{uuid.uuid4().hex[:8]}-{meta_db_path.name}").resolve()
    if root != target.parent:
        raise RuntimeError("catalog recovery backup path escaped its root")
    with sqlite3.connect(meta_db_path) as source, sqlite3.connect(target) as backup:
        source.backup(backup)
    if target.stat().st_size == 0:
        raise RuntimeError("catalog recovery MetaDB backup is empty")
    return target


async def run_catalog_guard(
    *,
    qdrant_url: str,
    collection: str,
    meta_db_path: str | Path,
    apply: bool = True,
) -> dict[str, Any]:
    """Audit catalog identity and self-heal only additive projections."""
    async with _LOCK:
        started = time.time()
        phase = "scan"
        db_path = Path(meta_db_path).resolve()
        try:
            inventory = await asyncio.to_thread(
                scan_qdrant_catalog,
                qdrant_url=qdrant_url,
                collection=collection,
                meta_db_path=db_path,
            )
            if not inventory.get("orphan_datasets"):
                return _set_state(
                    {
                        "schema": "les.rag.catalog-guard.v1",
                        "status": "ready",
                        "error_code": "",
                        "orphan_datasets": 0,
                        "orphan_points": 0,
                        "checked_at": time.time(),
                        "elapsed_seconds": round(time.time() - started, 3),
                    }
                )
            if not apply:
                return _set_state(
                    {
                        "schema": "les.rag.catalog-guard.v1",
                        "status": "degraded",
                        "error_code": "RAG_CATALOG_ORPHANS_DETECTED",
                        "orphan_datasets": inventory["orphan_datasets"],
                        "orphan_points": inventory["orphan_points"],
                        "orphan_files": inventory["orphan_files"],
                        "checked_at": time.time(),
                        "elapsed_seconds": round(time.time() - started, 3),
                    }
                )

            phase = "backup_metadb"
            backup = await asyncio.to_thread(_backup_metadb, db_path)
            names = {
                str(item["dataset_id"]): infer_recovered_dataset_name(item)
                for item in inventory.get("orphans") or []
            }
            phase = "recover_metadb"
            recovered = await asyncio.to_thread(
                recover_metadb_catalog,
                inventory=inventory,
                dataset_names=names,
                meta_db_path=db_path,
            )
            recovered_ids = list(names)
            phase = "recover_project_visibility"
            project_id = await asyncio.to_thread(
                link_recovered_datasets,
                meta_db_path=db_path,
                dataset_ids=recovered_ids,
            )
            phase = "rebuild_lexical"
            lexical = await asyncio.to_thread(
                rebuild_lexical_catalog,
                qdrant_url=qdrant_url,
                collection=collection,
                dataset_ids=recovered_ids,
                lexical_index=LexicalIndex(db_path=str(db_path)),
            )
            phase = "verify"
            verification = await asyncio.to_thread(
                scan_qdrant_catalog,
                qdrant_url=qdrant_url,
                collection=collection,
                meta_db_path=db_path,
            )
            if verification.get("orphan_datasets"):
                raise RuntimeError(
                    f"verification still sees {verification['orphan_datasets']} orphan dataset(s)"
                )
            return _set_state(
                {
                    "schema": "les.rag.catalog-guard.v1",
                    "status": "recovered",
                    "error_code": "",
                    "recovered": recovered,
                    "lexical": lexical,
                    "dataset_names": names,
                    "recovery_project_id": project_id,
                    "meta_db_backup": str(backup),
                    "checked_at": time.time(),
                    "elapsed_seconds": round(time.time() - started, 3),
                }
            )
        except Exception as exc:
            return _set_state(
                {
                    "schema": "les.rag.catalog-guard.v1",
                    "status": "blocked",
                    "error_code": "RAG_CATALOG_SELF_HEAL_FAILED",
                    "phase": phase,
                    "exception_type": type(exc).__name__,
                    "message": str(exc) or type(exc).__name__,
                    "checked_at": time.time(),
                    "elapsed_seconds": round(time.time() - started, 3),
                }
            )
