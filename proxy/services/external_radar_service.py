"""External source radar for operator-facing intake.

No reindex, no OCR, no LLM: this service only joins configured external roots,
the file-map database and MetaDB documents registered with source_path.
"""

from __future__ import annotations

import time
import sqlite3
from pathlib import Path
from typing import Any

from backend.rag_config import rag_meta_db_path
from proxy.config import external_allow_any, external_browse_default, external_source_roots, rag_upload_suffixes
from proxy.services.file_map_service import FILE_MAP_DB, map_stats, suggest_index_candidates


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return bool(row)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    except sqlite3.OperationalError:
        return set()


def _safe_resolve(path: str | Path) -> Path | None:
    try:
        return Path(path).expanduser().resolve(strict=False)
    except (OSError, RuntimeError):
        return None


def _is_inside(path: Path, root: Path) -> bool:
    try:
        return path == root or root in path.parents
    except RuntimeError:
        return False


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return ""


def _shallow_dir_stats(path: Path, *, max_entries: int = 2000) -> dict[str, Any]:
    suffixes = rag_upload_suffixes()
    stats = {
        "exists": path.exists(),
        "is_dir": path.is_dir(),
        "files_shallow": 0,
        "dirs_shallow": 0,
        "supported_shallow": 0,
        "truncated": False,
    }
    if not stats["is_dir"]:
        return stats
    try:
        for idx, child in enumerate(path.iterdir()):
            if idx >= max_entries:
                stats["truncated"] = True
                break
            if child.name.startswith("."):
                continue
            try:
                if child.is_dir():
                    stats["dirs_shallow"] += 1
                elif child.is_file():
                    stats["files_shallow"] += 1
                    if child.suffix.lower() in suffixes:
                        stats["supported_shallow"] += 1
            except OSError:
                continue
    except OSError as err:
        stats["error"] = str(err)
    return stats


def _external_documents() -> list[dict[str, Any]]:
    db_path = rag_meta_db_path()
    if not Path(db_path).exists():
        return []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        if not _table_exists(conn, "documents") or "source_path" not in _columns(conn, "documents"):
            return []
        has_datasets = _table_exists(conn, "datasets")
        dataset_name_expr = "COALESCE(ds.name, d.dataset_id)" if has_datasets else "d.dataset_id"
        join = "LEFT JOIN datasets ds ON ds.id = d.dataset_id" if has_datasets else ""
        rows = conn.execute(
            f"""
            SELECT d.dataset_id,
                   {dataset_name_expr} AS dataset_name,
                   d.file_name,
                   d.status,
                   COALESCE(d.chunk_count, 0) AS chunk_count,
                   d.source_path
            FROM documents d
            {join}
            WHERE COALESCE(d.source_path, '') != ''
            ORDER BY d.source_path
            """
        ).fetchall()
    return [dict(row) for row in rows]


def _root_key_for(path: Path, roots: list[Path]) -> str:
    matches = [root for root in roots if _is_inside(path, root)]
    if not matches:
        return ""
    return str(max(matches, key=lambda root: len(str(root))))


def _add_root(roots: dict[str, dict[str, Any]], path: str | Path, *, source: str) -> None:
    resolved = _safe_resolve(path)
    if not resolved:
        return
    key = str(resolved)
    entry = roots.setdefault(
        key,
        {
            "path": key,
            "name": resolved.name or key,
            "sources": [],
            "mapped_files": 0,
            "mapped_bytes": 0,
            "indexed_files": 0,
            "indexed_datasets": [],
            "last_scan_at": 0,
            "last_scan_sec": 0,
        },
    )
    if source not in entry["sources"]:
        entry["sources"].append(source)


def build_external_radar(*, candidate_limit: int = 15, file_map_db: Path = FILE_MAP_DB) -> dict[str, Any]:
    """Return a compact external-source radar summary for Samovar/UI."""
    allow_any = external_allow_any()
    configured = external_source_roots()
    roots: dict[str, dict[str, Any]] = {}
    for root in configured:
        _add_root(roots, root, source="configured")
    if allow_any:
        _add_root(roots, external_browse_default(), source="browse_default")

    try:
        stats = map_stats(db_path=file_map_db)
    except Exception as err:  # noqa: BLE001
        stats = {"roots": [], "by_ext": [], "files_with_cipher": 0, "error": str(err)}
    for row in stats.get("roots", []) or []:
        _add_root(roots, row.get("path", ""), source="filemap")
        entry = roots.get(str(_safe_resolve(row.get("path", "")) or ""))
        if entry:
            entry["mapped_files"] = int(row.get("file_count") or 0)
            entry["mapped_bytes"] = int(row.get("total_bytes") or 0)
            entry["last_scan_at"] = float(row.get("last_scan_at") or 0)
            entry["last_scan_sec"] = float(row.get("last_scan_sec") or 0)

    docs = _external_documents()
    known_roots = [_safe_resolve(path) for path in roots]
    known_roots = [root for root in known_roots if root]
    indexed_by_root: dict[str, dict[str, Any]] = {}
    for doc in docs:
        source = _safe_resolve(doc.get("source_path", ""))
        if not source:
            continue
        root_key = _root_key_for(source, known_roots)
        if not root_key:
            parent = source.parent
            _add_root(roots, parent, source="indexed_parent")
            root_key = str(parent)
            known_roots.append(parent)
        agg = indexed_by_root.setdefault(root_key, {"files": 0, "datasets": {}, "chunks": 0})
        agg["files"] += 1
        agg["chunks"] += int(doc.get("chunk_count") or 0)
        ds_id = str(doc.get("dataset_id") or "")
        if ds_id:
            agg["datasets"][ds_id] = str(doc.get("dataset_name") or ds_id)

    for key, agg in indexed_by_root.items():
        entry = roots.get(key)
        if not entry:
            continue
        entry["indexed_files"] = agg["files"]
        entry["indexed_chunks"] = agg["chunks"]
        entry["indexed_datasets"] = [
            {"id": ds_id, "name": name} for ds_id, name in sorted(agg["datasets"].items(), key=lambda item: item[1])
        ]

    enriched_roots: list[dict[str, Any]] = []
    for key, entry in roots.items():
        path = Path(key)
        shallow = _shallow_dir_stats(path)
        status = "ok" if shallow["is_dir"] else ("missing" if not shallow["exists"] else "not_dir")
        if entry["indexed_files"] and not entry["mapped_files"]:
            status = "indexed_unmapped"
        if entry["mapped_files"] and not entry["indexed_files"]:
            status = "mapped_not_indexed"
        enriched_roots.append(
            {
                **entry,
                **shallow,
                "status": status,
                "mapped_gb": round(int(entry.get("mapped_bytes") or 0) / 2**30, 3),
            }
        )
    enriched_roots.sort(
        key=lambda row: (
            0 if row["indexed_files"] else 1,
            0 if row["mapped_files"] else 1,
            row["path"].lower(),
        )
    )

    try:
        raw_candidates = suggest_index_candidates(limit=candidate_limit, db_path=file_map_db)
    except Exception:  # noqa: BLE001
        raw_candidates = []
    indexed_paths = [
        _safe_resolve(doc.get("source_path", "")) for doc in docs
    ]
    indexed_paths = [path for path in indexed_paths if path]
    candidates: list[dict[str, Any]] = []
    for cand in raw_candidates:
        root = _safe_resolve(cand.get("root", ""))
        if not root:
            continue
        folder = str(cand.get("folder") or "").strip("/")
        abs_path = root / folder if folder else root
        indexed_files = sum(1 for path in indexed_paths if _is_inside(path, abs_path))
        candidates.append(
            {
                **cand,
                "abs_path": str(abs_path),
                "indexed_files": indexed_files,
                "radar_status": "indexed" if indexed_files else "candidate",
            }
        )

    return {
        "status": "ok",
        "generated_at": time.time(),
        "allow_any": allow_any,
        "configured_roots": [str(root) for root in configured],
        "roots": enriched_roots,
        "external_documents": len(docs),
        "external_datasets": len({str(doc.get("dataset_id") or "") for doc in docs if doc.get("dataset_id")}),
        "filemap": {
            "roots": len(stats.get("roots", []) or []),
            "files_with_cipher": int(stats.get("files_with_cipher") or 0),
            "by_ext": stats.get("by_ext", []) or [],
            "error": stats.get("error", ""),
        },
        "candidates": candidates,
        "note": "Радар читает только env, MetaDB и file_map.db; он не индексирует и не читает содержимое файлов.",
    }
