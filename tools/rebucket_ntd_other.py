#!/usr/bin/env python3
"""Move pending NTD_OTHER documents into deterministic route datasets.

The tool is deliberately conservative: by default it only prints a plan.
Use --apply to move pending, not-yet-indexed documents between dataset folders
and update the SQLite metabase. Already indexed documents are left untouched so
existing Qdrant points remain consistent.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import uuid
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.document_router import route_document
from backend.rag_config import rag_meta_db_path


OLD_DATASET = "NTD_OTHER_Index"


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def dataset_ids(conn: sqlite3.Connection) -> dict[str, str]:
    return {row["name"]: row["id"] for row in conn.execute("SELECT id, name FROM datasets")}


def ensure_dataset(conn: sqlite3.Connection, ids: dict[str, str], name: str, apply: bool) -> str:
    if name in ids:
        return ids[name]
    dataset_id = str(uuid.uuid4())
    ids[name] = dataset_id
    if apply:
        conn.execute(
            "INSERT INTO datasets (id, name, status, chunk_count) VALUES (?, ?, 'IDLE', 0)",
            (dataset_id, name),
        )
    return dataset_id


def update_dataset_chunk_count(conn: sqlite3.Connection, dataset_id: str) -> None:
    row = conn.execute(
        "SELECT COALESCE(SUM(chunk_count),0) AS chunks FROM documents "
        "WHERE dataset_id=? AND status='INDEXED'",
        (dataset_id,),
    ).fetchone()
    conn.execute(
        "UPDATE datasets SET chunk_count=? WHERE id=?",
        (int(row["chunks"] if row else 0), dataset_id),
    )


def update_dataset_status(conn: sqlite3.Connection, dataset_id: str) -> None:
    row = conn.execute(
        "SELECT "
        "SUM(CASE WHEN status='PENDING' THEN 1 ELSE 0 END) AS pending, "
        "SUM(CASE WHEN status='ERROR' THEN 1 ELSE 0 END) AS errors, "
        "COUNT(*) AS total "
        "FROM documents WHERE dataset_id=?",
        (dataset_id,),
    ).fetchone()
    pending = int(row["pending"] or 0)
    errors = int(row["errors"] or 0)
    total = int(row["total"] or 0)
    status = "IDLE"
    if pending:
        status = "IDLE"
    elif errors:
        status = "ERROR"
    elif total:
        status = "COMPLETED"
    conn.execute("UPDATE datasets SET status=? WHERE id=?", (status, dataset_id))


def source_path_for(file_name: str, source_root: Path, fallback: Path) -> Path:
    source = source_root / file_name
    return source if source.exists() else fallback


def move_storage_file(old_path: Path, new_path: Path) -> None:
    if not old_path.exists():
        return
    new_path.parent.mkdir(parents=True, exist_ok=True)
    if new_path.exists():
        old_path.unlink()
        return
    shutil.move(str(old_path), str(new_path))


def rebucket(args: argparse.Namespace) -> int:
    load_dotenv(".env", override=False)
    db_path = args.db_path or rag_meta_db_path()
    source_root = Path(args.source_root)
    storage_root = Path(args.storage_root)

    with connect(db_path) as conn:
        ids = dataset_ids(conn)
        old_id = ids.get(OLD_DATASET)
        if not old_id:
            print(f"{OLD_DATASET}: dataset not found")
            return 0

        rows = conn.execute(
            """
            SELECT id, dataset_id, file_name, status, chunk_count
            FROM documents
            WHERE dataset_id=?
              AND status='PENDING'
            ORDER BY file_name
            """,
            (old_id,),
        ).fetchall()

        moves = []
        skipped = Counter()
        for row in rows:
            file_name = row["file_name"]
            old_storage = storage_root / old_id / file_name
            route_source = source_path_for(file_name, source_root, old_storage)
            if not route_source.exists():
                skipped["missing_source"] += 1
                continue
            route = route_document(route_source)
            if route.dataset_name == OLD_DATASET:
                skipped["still_other"] += 1
                continue
            target_id = ensure_dataset(conn, ids, route.dataset_name, args.apply)
            moves.append((row, route, target_id, old_storage, storage_root / target_id / file_name))

        summary = Counter(route.dataset_name for _, route, *_ in moves)
        print(f"db={db_path}")
        print(f"candidates={len(rows)} moves={len(moves)} skipped={dict(skipped)}")
        for dataset_name, count in sorted(summary.items()):
            print(f"{dataset_name}: {count}")

        if not args.apply:
            print("dry-run only; rerun with --apply to update SQLite/storage")
            return 0

        touched = {old_id}
        for row, route, target_id, old_storage, new_storage in moves:
            existing = conn.execute(
                "SELECT id FROM documents WHERE dataset_id=? AND file_name=?",
                (target_id, row["file_name"]),
            ).fetchone()
            move_storage_file(old_storage, new_storage)
            if existing:
                conn.execute(
                    """
                    UPDATE documents
                    SET status='PENDING', chunk_count=0, last_error='',
                        domain=?, route_dataset=?, doc_type=?, content_type=?,
                        complexity=?, pipeline=?
                    WHERE id=?
                    """,
                    (
                        route.domain,
                        route.dataset_name,
                        route.doc_type,
                        route.content_type,
                        route.complexity,
                        route.pipeline,
                        existing["id"],
                    ),
                )
                conn.execute("DELETE FROM documents WHERE id=?", (row["id"],))
            else:
                conn.execute(
                    """
                    UPDATE documents
                    SET dataset_id=?, status='PENDING', chunk_count=0, last_error='',
                        domain=?, route_dataset=?, doc_type=?, content_type=?,
                        complexity=?, pipeline=?
                    WHERE id=?
                    """,
                    (
                        target_id,
                        route.domain,
                        route.dataset_name,
                        route.doc_type,
                        route.content_type,
                        route.complexity,
                        route.pipeline,
                        row["id"],
                    ),
                )
            touched.add(target_id)

        for dataset_id in touched:
            update_dataset_chunk_count(conn, dataset_id)
            update_dataset_status(conn, dataset_id)
        conn.commit()
        print(f"applied moves={len(moves)}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--db-path", default="")
    parser.add_argument("--source-root", default="RAG_Content")
    parser.add_argument("--storage-root", default="storage/datasets")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(rebucket(parse_args()))
