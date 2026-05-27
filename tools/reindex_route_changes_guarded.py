#!/usr/bin/env python3
"""Guarded selective reindex for Folder Watcher route_changed documents.

This runner moves already indexed documents whose deterministic route now
points to another dataset. It is intentionally separate from watch/scan:
route moves must delete old Qdrant points and update SQLite/storage atomically
enough that a later parse does not leave duplicate corpus entries.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import time
import uuid
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import qdrant_client
from qdrant_client.http import models

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.rag_config import rag_collection_name, rag_meta_db_path
from backend.smart_index import build_smart_plan
from tools import reindex_datasets_guarded as guarded


@dataclass(frozen=True)
class RouteChangeDoc:
    current_doc_id: str
    current_dataset_id: str
    current_dataset_name: str
    target_dataset_name: str
    current_file_name: str
    target_file_name: str
    source_path: str
    file_size: int
    file_mtime: float
    chunk_count: int
    status: str
    route: dict[str, Any]


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def dataset_ids(conn: sqlite3.Connection) -> dict[str, str]:
    return {row["name"]: row["id"] for row in conn.execute("SELECT id, name FROM datasets")}


def ensure_dataset(conn: sqlite3.Connection, ids: dict[str, str], name: str) -> str:
    if name in ids:
        return ids[name]
    dataset_id = str(uuid.uuid4())
    ids[name] = dataset_id
    conn.execute(
        "INSERT INTO datasets (id, name, status, chunk_count) VALUES (?, ?, 'IDLE', 0)",
        (dataset_id, name),
    )
    return dataset_id


def load_docs_inventory(db_path: str) -> dict[str, dict[Any, dict[str, Any]]]:
    with connect(db_path) as conn:
        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT d.name AS dataset_name,
                       d.id AS dataset_id,
                       doc.id AS doc_id,
                       doc.file_name,
                       doc.status,
                       COALESCE(doc.file_mtime, 0) AS file_mtime,
                       COALESCE(doc.file_size, 0) AS file_size,
                       COALESCE(doc.chunk_count, 0) AS chunk_count,
                       COALESCE(doc.last_error, '') AS last_error
                FROM documents doc
                JOIN datasets d ON d.id=doc.dataset_id
                """
            ).fetchall()
        ]
    by_dataset_path = {(row["dataset_name"], row["file_name"]): row for row in rows}
    by_path: dict[str, dict[str, Any]] = {}
    by_basename: dict[str, dict[str, Any]] = {}
    basename_counts: Counter[str] = Counter()
    for row in rows:
        file_name = str(row.get("file_name") or "")
        if not file_name:
            continue
        by_path.setdefault(file_name, row)
        basename = Path(file_name).name
        basename_counts[basename] += 1
        by_basename.setdefault(basename, row)
    by_basename = {name: row for name, row in by_basename.items() if basename_counts[name] == 1}
    return {"by_dataset_path": by_dataset_path, "by_path": by_path, "by_basename": by_basename}


def route_changes(db_path: str, source_root: str, *, status_filter: str = "INDEXED") -> list[RouteChangeDoc]:
    root = Path(source_root)
    plan = build_smart_plan(root)
    known = load_docs_inventory(db_path)
    result: list[RouteChangeDoc] = []
    for target_dataset, items in plan["plan"].items():
        for item in items:
            relative_path = str(item["relative_path"])
            current = known["by_dataset_path"].get((target_dataset, relative_path))
            if current is None:
                current = known["by_path"].get(relative_path)
            if current is None:
                basename_current = known["by_basename"].get(Path(relative_path).name)
                if basename_current is not None and basename_current.get("dataset_name") == target_dataset:
                    current = basename_current
            if not current or current.get("dataset_name") == target_dataset:
                continue
            if status_filter and current.get("status") != status_filter:
                continue
            source_path = Path(str(item["path"]))
            stat = source_path.stat() if source_path.exists() else None
            route = item.get("route") or {}
            result.append(
                RouteChangeDoc(
                    current_doc_id=str(current.get("doc_id") or ""),
                    current_dataset_id=str(current.get("dataset_id") or ""),
                    current_dataset_name=str(current.get("dataset_name") or ""),
                    target_dataset_name=target_dataset,
                    current_file_name=str(current.get("file_name") or ""),
                    target_file_name=relative_path,
                    source_path=str(source_path),
                    file_size=int(item.get("size_bytes") or current.get("file_size") or 0),
                    file_mtime=float(stat.st_mtime if stat else current.get("file_mtime") or 0.0),
                    chunk_count=int(current.get("chunk_count") or 0),
                    status=str(current.get("status") or ""),
                    route=route,
                )
            )
    return sorted(
        result,
        key=lambda doc: (
            doc.current_dataset_name,
            doc.target_dataset_name,
            doc.file_size,
            doc.target_file_name,
        ),
    )


def plan_summary(docs: list[RouteChangeDoc]) -> dict[str, Any]:
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for doc in docs:
        key = (doc.current_dataset_name, doc.target_dataset_name)
        group = groups.setdefault(
            key,
            {
                "current_dataset_name": doc.current_dataset_name,
                "target_dataset_name": doc.target_dataset_name,
                "files": 0,
                "bytes": 0,
                "chunks": 0,
            },
        )
        group["files"] += 1
        group["bytes"] += doc.file_size
        group["chunks"] += doc.chunk_count
    return {
        "total": len(docs),
        "groups": sorted(groups.values(), key=lambda item: (-item["files"], item["current_dataset_name"], item["target_dataset_name"])),
    }


def _csv_filter(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


def filter_route_changes(
    docs: list[RouteChangeDoc],
    *,
    from_datasets: str = "",
    to_datasets: str = "",
    path_contains: str = "",
) -> list[RouteChangeDoc]:
    from_names = _csv_filter(from_datasets)
    to_names = _csv_filter(to_datasets)
    path_hint = path_contains.casefold().strip()
    result: list[RouteChangeDoc] = []
    for doc in docs:
        if from_names and doc.current_dataset_name not in from_names:
            continue
        if to_names and doc.target_dataset_name not in to_names:
            continue
        if path_hint and path_hint not in doc.target_file_name.casefold():
            continue
        result.append(doc)
    return result


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "completed": {}, "runs": [], "created_at": guarded.timestamp()}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"state is not a JSON object: {path}")
    data.setdefault("completed", {})
    data.setdefault("runs", [])
    return data


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = guarded.timestamp()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def update_dataset_rollups(conn: sqlite3.Connection, dataset_ids_to_update: set[str]) -> None:
    for dataset_id in dataset_ids_to_update:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status='PENDING' THEN 1 ELSE 0 END) AS pending,
                SUM(CASE WHEN status='ERROR' THEN 1 ELSE 0 END) AS errors,
                COALESCE(SUM(CASE WHEN status='INDEXED' THEN chunk_count ELSE 0 END), 0) AS chunks
            FROM documents
            WHERE dataset_id=?
            """,
            (dataset_id,),
        ).fetchone()
        pending = int(row["pending"] or 0)
        errors = int(row["errors"] or 0)
        total = int(row["total"] or 0)
        status = "IDLE" if pending else "ERROR" if errors else "COMPLETED" if total else "IDLE"
        conn.execute("UPDATE datasets SET status=?, chunk_count=? WHERE id=?", (status, int(row["chunks"] or 0), dataset_id))


def storage_candidates(storage_root: Path, doc: RouteChangeDoc) -> list[Path]:
    current = storage_root / doc.current_dataset_id / doc.current_file_name
    basename = storage_root / doc.current_dataset_id / Path(doc.current_file_name).name
    return [current, basename] if current != basename else [current]


def copy_storage(doc: RouteChangeDoc, target_dataset_id: str, storage_root: str) -> tuple[str, list[str]]:
    root = Path(storage_root)
    target = root / target_dataset_id / doc.target_file_name
    target.parent.mkdir(parents=True, exist_ok=True)
    source = Path(doc.source_path)
    removed: list[str] = []
    if source.exists():
        shutil.copy2(source, target)
    else:
        existing = next((path for path in storage_candidates(root, doc) if path.exists()), None)
        if existing is None:
            raise FileNotFoundError(f"source and storage file are missing: {doc.source_path}")
        shutil.copy2(existing, target)
    for old_path in storage_candidates(root, doc):
        if old_path.exists() and old_path.resolve() != target.resolve():
            old_path.unlink()
            removed.append(str(old_path))
    return str(target), removed


def move_doc_to_target(db_path: str, doc: RouteChangeDoc, *, storage_root: str) -> dict[str, Any]:
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        ids = dataset_ids(conn)
        target_dataset_id = ensure_dataset(conn, ids, doc.target_dataset_name)
        collision = conn.execute(
            "SELECT id FROM documents WHERE dataset_id=? AND file_name=? AND id<>?",
            (target_dataset_id, doc.target_file_name, doc.current_doc_id),
        ).fetchone()
        if collision:
            raise RuntimeError(
                f"target document already exists: {doc.target_dataset_name}/{doc.target_file_name}"
            )
        storage_path, removed = copy_storage(doc, target_dataset_id, storage_root)
        route = doc.route
        metadata = route.get("metadata") if isinstance(route.get("metadata"), dict) else {}
        domain = route.get("domain") or metadata.get("domain") or ""
        doc_type = route.get("doc_type") or metadata.get("doc_type") or ""
        content_type = route.get("content_type") or metadata.get("content_type") or ""
        complexity = route.get("complexity") or metadata.get("complexity") or ""
        pipeline = route.get("pipeline") or metadata.get("pipeline") or ""
        conn.execute(
            """
            UPDATE documents
            SET dataset_id=?, file_name=?, status='PENDING', chunk_count=0, last_error='',
                file_mtime=?, file_size=?, domain=?, route_dataset=?, doc_type=?,
                content_type=?, complexity=?, pipeline=?
            WHERE id=?
            """,
            (
                target_dataset_id,
                doc.target_file_name,
                doc.file_mtime,
                doc.file_size,
                domain,
                doc.target_dataset_name,
                doc_type,
                content_type,
                complexity,
                pipeline,
                doc.current_doc_id,
            ),
        )
        update_dataset_rollups(conn, {doc.current_dataset_id, target_dataset_id})
        conn.commit()
    return {
        "target_dataset_id": target_dataset_id,
        "storage_path": storage_path,
        "removed_storage": removed,
    }


def delete_old_points(qdrant_url: str, collection: str, doc: RouteChangeDoc) -> None:
    client = qdrant_client.QdrantClient(url=qdrant_url)
    client.delete(
        collection_name=collection,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(key="dataset_id", match=models.MatchValue(value=doc.current_dataset_id)),
                    models.FieldCondition(key="file_name", match=models.MatchValue(value=doc.current_file_name)),
                ]
            )
        ),
        wait=True,
    )


def target_doc(doc: RouteChangeDoc, target_dataset_id: str) -> guarded.TargetDoc:
    return guarded.TargetDoc(
        id=doc.current_doc_id,
        dataset_id=target_dataset_id,
        dataset_name=doc.target_dataset_name,
        file_name=doc.target_file_name,
        file_size=doc.file_size,
        chunk_count=doc.chunk_count,
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default=rag_meta_db_path())
    parser.add_argument("--auth-db-path", default="data/les_meta.db")
    parser.add_argument("--source-root", default="RAG_Content")
    parser.add_argument("--storage-root", default="storage/datasets")
    parser.add_argument("--proxy-url", default="http://127.0.0.1:8050")
    parser.add_argument("--mlx-url", default="http://127.0.0.1:8080")
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    parser.add_argument("--collection", default=rag_collection_name())
    parser.add_argument("--api-key", default="")
    parser.add_argument("--artifacts-dir", default="artifacts/reindex_runs")
    parser.add_argument("--state-file", default="")
    parser.add_argument("--stop-file", default="")
    parser.add_argument("--max-docs", type=int, default=0)
    parser.add_argument("--from-dataset", default="", help="Comma-separated current dataset names to include")
    parser.add_argument("--to-dataset", default="", help="Comma-separated target dataset names to include")
    parser.add_argument("--path-contains", default="", help="Only include route changes whose target path contains this text")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--min-free-gb", type=float, default=4.0)
    parser.add_argument("--max-swap-pct", type=float, default=85.0)
    parser.add_argument("--post-min-free-gb", type=float, default=3.0)
    parser.add_argument("--post-max-swap-pct", type=float, default=85.0)
    parser.add_argument("--memory-wait-sec", type=float, default=86400.0)
    parser.add_argument("--memory-poll-sec", type=float, default=30.0)
    parser.add_argument("--cooldown-sec", type=float, default=90.0)
    parser.add_argument("--health-timeout", type=float, default=20.0)
    parser.add_argument("--parse-timeout", type=float, default=3600.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    args.proxy_url = args.proxy_url.rstrip("/")
    args.mlx_url = args.mlx_url.rstrip("/")
    args.qdrant_url = args.qdrant_url.rstrip("/")
    run_dir = Path(args.artifacts_dir) / f"route_change_reindex_{guarded.run_stamp()}"
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "reindex_route_changes.jsonl"
    state_path = Path(args.state_file) if args.state_file else Path(args.artifacts_dir) / "reindex_state_route_changes.json"
    state = load_state(state_path)
    state.setdefault("runs", []).append({"run_dir": str(run_dir), "started_at": guarded.timestamp()})
    if not args.dry_run:
        save_state(state_path, state)

    admin_key = args.api_key
    if not admin_key and Path(args.auth_db_path).exists():
        admin_key = guarded.local_admin_key(args.auth_db_path)
    guarded.emit(log_path, "start", db_path=args.db_path, source_root=args.source_root, state_file=str(state_path), dry_run=args.dry_run)
    if not admin_key and not args.dry_run:
        guarded.emit(log_path, "error", detail="admin API key is required")
        return 2

    docs = filter_route_changes(
        route_changes(args.db_path, args.source_root),
        from_datasets=args.from_dataset,
        to_datasets=args.to_dataset,
        path_contains=args.path_contains,
    )
    completed = set(state.get("completed") or {})
    docs = [doc for doc in docs if doc.current_doc_id not in completed]
    if args.max_docs > 0:
        docs = docs[: args.max_docs]
    summary = plan_summary(docs)
    guarded.emit(log_path, "plan", **summary, completed_in_state=len(completed))
    if args.dry_run:
        guarded.emit(log_path, "dry_run", preview=[asdict(doc) for doc in docs[:20]], omitted=max(0, len(docs) - 20))
        return 0
    if not docs:
        guarded.emit(log_path, "done", detail="no route changes")
        return 0

    try:
        sqlite_backup = guarded.backup_sqlite(args.db_path, run_dir)
        guarded.emit(log_path, "sqlite_backup", path=str(sqlite_backup), bytes=sqlite_backup.stat().st_size)
        guarded.health_snapshot(args.proxy_url, args.health_timeout, admin_key)
        guarded.wait_for_memory(
            args.mlx_url,
            args.health_timeout,
            min_free_gb=args.min_free_gb,
            max_swap_pct=args.max_swap_pct,
            wait_sec=args.memory_wait_sec,
            poll_sec=args.memory_poll_sec,
            log_path=log_path,
            event="pre_memory_wait",
        )
        guarded.emit(log_path, "pre_unload", result=guarded.unload_all(args.mlx_url, args.health_timeout))

        for index, doc in enumerate(docs, 1):
            stop = guarded.stop_requested(args.stop_file)
            if stop:
                guarded.emit(log_path, "paused", index=index, remaining=len(docs) - index + 1, request=stop)
                return 0
            guarded.emit(log_path, "doc_start", index=index, total=len(docs), doc=asdict(doc))
            guarded.wait_for_memory(
                args.mlx_url,
                args.health_timeout,
                min_free_gb=args.min_free_gb,
                max_swap_pct=args.max_swap_pct,
                wait_sec=args.memory_wait_sec,
                poll_sec=args.memory_poll_sec,
                log_path=log_path,
                event="doc_memory_pre_wait",
                index=index,
            )
            delete_old_points(args.qdrant_url, args.collection, doc)
            move = move_doc_to_target(args.db_path, doc, storage_root=args.storage_root)
            guarded.emit(log_path, "doc_moved", index=index, move=move)
            parsed = guarded.parse_scheduler_once(
                args.proxy_url,
                target_doc(doc, move["target_dataset_id"]),
                args.parse_timeout,
                admin_key,
                dataset_names=[doc.target_dataset_name],
                min_free_gb=args.min_free_gb,
                max_swap_pct=args.max_swap_pct,
                post_min_free_gb=args.post_min_free_gb,
                post_max_swap_pct=args.post_max_swap_pct,
            )
            guarded.emit(log_path, "doc_parse", index=index, result=parsed)
            health = guarded.health_snapshot(args.proxy_url, args.health_timeout, admin_key)
            guarded.emit(log_path, "doc_health", index=index, rag=guarded.compact_rag(health.get("rag")))
            state.setdefault("completed", {})[doc.current_doc_id] = {
                "completed_at": guarded.timestamp(),
                "from": doc.current_dataset_name,
                "to": doc.target_dataset_name,
                "file_name": doc.target_file_name,
            }
            save_state(state_path, state)
            guarded.emit(log_path, "campaign_progress", completed=len(state["completed"]), remaining=max(0, len(docs) - index))
            guarded.emit(log_path, "doc_unload", index=index, result=guarded.unload_all(args.mlx_url, args.health_timeout))
            guarded.wait_for_memory(
                args.mlx_url,
                args.health_timeout,
                min_free_gb=args.post_min_free_gb,
                max_swap_pct=args.post_max_swap_pct,
                wait_sec=args.memory_wait_sec,
                poll_sec=args.memory_poll_sec,
                log_path=log_path,
                event="doc_memory_post_wait",
                index=index,
            )
            if index < len(docs) and args.cooldown_sec > 0:
                time.sleep(args.cooldown_sec)
        guarded.emit(log_path, "done", docs=len(docs), run_dir=str(run_dir))
        return 0
    except Exception as error:
        guarded.emit(log_path, "failed", error=str(error), run_dir=str(run_dir))
        return 1
    finally:
        try:
            guarded.emit(log_path, "final_unload", result=guarded.unload_all(args.mlx_url, args.health_timeout))
        except Exception as error:
            guarded.emit(log_path, "final_unload_failed", error=str(error))


if __name__ == "__main__":
    raise SystemExit(main())
