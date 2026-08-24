"""Recover a missing MetaDB/FTS catalog from preserved Qdrant payloads.

This is an operator recovery path, not an alternative ingestion pipeline.  It
never invents source paths, never rewrites vectors, and requires explicit names
before applying orphan dataset rows.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from qdrant_client import QdrantClient

from proxy.services.lexical_index_service import LexicalIndex


def _catalog_dataset_ids(meta_db_path: str | Path) -> set[str]:
    with sqlite3.connect(meta_db_path) as conn:
        rows = conn.execute("SELECT id FROM datasets").fetchall()
    return {str(row[0]) for row in rows}


def scan_qdrant_catalog(
    *,
    qdrant_url: str,
    collection: str,
    meta_db_path: str | Path,
    page_size: int = 10_000,
) -> dict[str, Any]:
    """Return bounded summaries plus file-level rows for orphan datasets."""
    known = _catalog_dataset_ids(meta_db_path)
    client = QdrantClient(url=qdrant_url, timeout=60.0, check_compatibility=False)
    offset = None
    datasets: dict[str, dict[str, Any]] = {}
    try:
        while True:
            points, offset = client.scroll(
                collection_name=collection,
                limit=page_size,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for point in points:
                payload = dict(point.payload or {})
                dataset_id = str(payload.get("dataset_id") or "").strip()
                file_name = str(payload.get("file_name") or "").strip()
                if not dataset_id or not file_name or dataset_id in known:
                    continue
                entry = datasets.setdefault(
                    dataset_id,
                    {
                        "dataset_id": dataset_id,
                        "points": 0,
                        "files": {},
                        "fingerprints": Counter(),
                        "node_roles": Counter(),
                    },
                )
                entry["points"] += 1
                entry["fingerprints"][str(payload.get("embedding_fingerprint") or "")] += 1
                entry["node_roles"][str(payload.get("node_role") or "")] += 1
                file_row = entry["files"].setdefault(
                    file_name,
                    {
                        "file_name": file_name,
                        "chunk_count": 0,
                        "doc_type": str(payload.get("doc_type") or ""),
                        "content_type": str(payload.get("content_type") or ""),
                        "domain": str(payload.get("domain") or ""),
                        "route_dataset": str(payload.get("route_dataset") or ""),
                        "complexity": str(payload.get("complexity") or ""),
                        "pipeline": str(payload.get("pipeline") or ""),
                    },
                )
                file_row["chunk_count"] += 1
            if offset is None:
                break
    finally:
        client.close()

    orphan_rows = []
    for dataset_id, entry in sorted(datasets.items()):
        files = list(entry["files"].values())
        orphan_rows.append(
            {
                "dataset_id": dataset_id,
                "points": int(entry["points"]),
                "file_count": len(files),
                "files": files,
                "fingerprints": dict(entry["fingerprints"]),
                "node_roles": dict(entry["node_roles"]),
                "sample_files": [row["file_name"] for row in files[:5]],
            }
        )
    return {
        "schema": "les.rag.catalog-recovery.v1",
        "collection": collection,
        "known_dataset_ids": sorted(known),
        "orphans": orphan_rows,
        "orphan_datasets": len(orphan_rows),
        "orphan_points": sum(row["points"] for row in orphan_rows),
        "orphan_files": sum(row["file_count"] for row in orphan_rows),
    }


def recover_metadb_catalog(
    *,
    inventory: dict[str, Any],
    dataset_names: dict[str, str],
    meta_db_path: str | Path,
) -> dict[str, Any]:
    """Insert only explicit orphan dataset identities and their document rows."""
    orphans = list(inventory.get("orphans") or [])
    orphan_ids = {str(item.get("dataset_id") or "") for item in orphans}
    missing_names = sorted(dataset_id for dataset_id in orphan_ids if not dataset_names.get(dataset_id, "").strip())
    if missing_names:
        raise ValueError(f"explicit dataset names are required for: {', '.join(missing_names)}")

    recovered_datasets = 0
    recovered_documents = 0
    with sqlite3.connect(meta_db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        for item in orphans:
            dataset_id = str(item["dataset_id"])
            existing = conn.execute("SELECT 1 FROM datasets WHERE id=?", (dataset_id,)).fetchone()
            if existing:
                continue
            conn.execute(
                "INSERT INTO datasets "
                "(id, name, status, chunk_count, sensitivity, group_name, dataset_scope, module_id) "
                "VALUES (?, ?, 'IDLE', ?, 'P0', '', 'user', '')",
                (dataset_id, dataset_names[dataset_id].strip(), int(item.get("points") or 0)),
            )
            recovered_datasets += 1
            for file_row in item.get("files") or []:
                file_name = str(file_row.get("file_name") or "")
                if not file_name:
                    continue
                doc_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"les-recovered:{dataset_id}:{file_name}"))
                conn.execute(
                    "INSERT OR IGNORE INTO documents "
                    "(id, dataset_id, file_name, status, file_mtime, file_size, chunk_count, "
                    "domain, route_dataset, doc_type, content_type, complexity, pipeline, "
                    "last_error, stage, source_path) "
                    "VALUES (?, ?, ?, 'INDEXED', 0, 0, ?, ?, ?, ?, ?, ?, ?, '', '', '')",
                    (
                        doc_id,
                        dataset_id,
                        file_name,
                        int(file_row.get("chunk_count") or 0),
                        str(file_row.get("domain") or ""),
                        str(file_row.get("route_dataset") or ""),
                        str(file_row.get("doc_type") or ""),
                        str(file_row.get("content_type") or ""),
                        str(file_row.get("complexity") or ""),
                        str(file_row.get("pipeline") or ""),
                    ),
                )
                recovered_documents += 1
        conn.commit()
    return {
        "recovered_datasets": recovered_datasets,
        "recovered_documents": recovered_documents,
    }


def link_recovered_datasets(
    *,
    meta_db_path: str | Path,
    dataset_ids: Iterable[str],
    project_name: str = "Аварийно восстановленные данные",
) -> int:
    """Keep recovered datasets visible through project mode without guessing identity."""
    selected = list(dict.fromkeys(str(value).strip() for value in dataset_ids if str(value).strip()))
    if not selected:
        return 0
    now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    with sqlite3.connect(meta_db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS les_projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                code TEXT NOT NULL DEFAULT '',
                address TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS les_project_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                ref TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(project_id, kind, ref)
            );
            """
        )
        row = conn.execute(
            "SELECT id FROM les_projects WHERE name=? ORDER BY id LIMIT 1",
            (project_name,),
        ).fetchone()
        project_id = int(row[0]) if row else int(
            conn.execute(
                "INSERT INTO les_projects(name, status, created_at) VALUES (?, 'active', ?)",
                (project_name, now),
            ).lastrowid
        )
        for dataset_id in selected:
            conn.execute(
                "INSERT OR IGNORE INTO les_project_links(project_id, kind, ref, created_at) "
                "VALUES (?, 'dataset', ?, ?)",
                (project_id, dataset_id, now),
            )
    return project_id


def rebuild_lexical_catalog(
    *,
    qdrant_url: str,
    collection: str,
    dataset_ids: Iterable[str],
    lexical_index: LexicalIndex,
    page_size: int = 2_000,
) -> dict[str, int]:
    """Rehydrate the exact FTS projection from preserved Qdrant text payloads."""
    selected = [str(value) for value in dataset_ids if str(value)]
    if not selected:
        return {"indexed": 0, "points": 0}
    client = QdrantClient(url=qdrant_url, timeout=60.0, check_compatibility=False)
    offset = None
    indexed = 0
    points_seen = 0
    try:
        while True:
            points, offset = client.scroll(
                collection_name=collection,
                scroll_filter={
                    "must": [{"key": "dataset_id", "match": {"any": selected}}]
                },
                limit=page_size,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            rows = []
            for point in points:
                payload = dict(point.payload or {})
                points_seen += 1
                rows.append(
                    {
                        **payload,
                        "point_id": str(point.id),
                        "doc_name": str(payload.get("file_name") or ""),
                    }
                )
            indexed += lexical_index.upsert_chunks(collection, rows)
            if offset is None:
                break
    finally:
        client.close()
    lexical_index.mark_collection(
        collection,
        point_count=points_seen,
        indexed_count=indexed,
    )
    return {"indexed": indexed, "points": points_seen}
