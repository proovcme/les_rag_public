"""Сканер папок — карта файлопомойки (W15.1, LES3_PLAN).

«ЛЕС поверх готового файлового архива»: дешёвая карта ВСЕГО дерева без чтения
содержимого и без LLM (ADR-11). Имя/тип/размер/mtime + шифры НТД и комплектов
из имён файлов. Инкрементальный re-scan по mtime. Из карты — выборочная
индексация (W15.2).
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

FILE_MAP_DB = Path(os.getenv("LES_FILE_MAP_DB", "data/file_map.db"))

# Каталоги, которые не сканируем (системный шум и тяжёлые кэши).
DEFAULT_EXCLUDE_DIRS = {
    ".git", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    ".cache", "Library", ".Trash", "$RECYCLE.BIN", "System Volume Information",
    "_originals", ".DS_Store",
}

# Шифры в именах: НТД (СП/ГОСТ/СНиП) и проектные комплекты (АБВ-РД-ОВ1-...).
NTD_CIPHER_RE = re.compile(r"\b(СП|ГОСТ\s*Р?|СНиП)\s*[\d.]+(?:[-.]\d+)*", re.IGNORECASE)
PROJECT_CIPHER_RE = re.compile(r"\b[А-ЯA-Z0-9]{2,8}-(?:РД|ПД|АР|КР|ОВ|ВК|ЭОМ|СС|ПЗ)[А-ЯA-Z0-9.-]*", re.IGNORECASE)


def extract_cipher(name: str) -> str:
    match = NTD_CIPHER_RE.search(name) or PROJECT_CIPHER_RE.search(name)
    return match.group(0).strip() if match else ""


def _connect(db_path: Path = FILE_MAP_DB) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS scan_roots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL UNIQUE,
            last_scan_at REAL DEFAULT 0,
            last_scan_sec REAL DEFAULT 0,
            file_count INTEGER DEFAULT 0,
            total_bytes INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS file_map (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            root_id INTEGER NOT NULL,
            rel_path TEXT NOT NULL,
            name TEXT NOT NULL,
            ext TEXT NOT NULL DEFAULT '',
            size INTEGER NOT NULL DEFAULT 0,
            mtime REAL NOT NULL DEFAULT 0,
            cipher TEXT NOT NULL DEFAULT '',
            seen_at REAL NOT NULL DEFAULT 0,
            UNIQUE(root_id, rel_path)
        );
        CREATE INDEX IF NOT EXISTS idx_fm_name ON file_map(name);
        CREATE INDEX IF NOT EXISTS idx_fm_ext ON file_map(ext);
        CREATE INDEX IF NOT EXISTS idx_fm_cipher ON file_map(cipher);
        """
    )
    return conn


def scan_root(
    root: Path,
    db_path: Path = FILE_MAP_DB,
    exclude_dirs: set[str] | None = None,
    max_files: int = 500_000,
) -> dict[str, Any]:
    """Полный/инкрементальный обход дерева. Только метаданные, контент не читаем."""
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"не каталог: {root}")
    excludes = DEFAULT_EXCLUDE_DIRS | (exclude_dirs or set())
    started = time.time()
    seen_marker = started

    with _connect(db_path) as conn:
        cur = conn.execute("INSERT OR IGNORE INTO scan_roots(path) VALUES (?)", (str(root),))
        root_id = conn.execute("SELECT id FROM scan_roots WHERE path=?", (str(root),)).fetchone()["id"]

        known = {
            row["rel_path"]: (row["mtime"], row["size"])
            for row in conn.execute("SELECT rel_path, mtime, size FROM file_map WHERE root_id=?", (root_id,))
        }

        count = 0
        total_bytes = 0
        added = updated = unchanged = 0
        batch: list[tuple] = []
        touch: list[str] = []

        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in excludes and not d.startswith(".")]
            for fname in filenames:
                if fname.startswith("."):
                    continue
                fpath = Path(dirpath) / fname
                try:
                    st = fpath.stat()
                except OSError:
                    continue
                rel = fpath.relative_to(root).as_posix()
                count += 1
                total_bytes += st.st_size
                prev = known.get(rel)
                if prev and abs(prev[0] - st.st_mtime) < 1 and prev[1] == st.st_size:
                    unchanged += 1
                    touch.append(rel)
                else:
                    if prev:
                        updated += 1
                    else:
                        added += 1
                    batch.append((
                        root_id, rel, fname, fpath.suffix.lower().lstrip("."),
                        st.st_size, st.st_mtime, extract_cipher(fname), seen_marker,
                    ))
                if count >= max_files:
                    logger.warning("[FILEMAP] %s: достигнут лимит %s файлов", root, max_files)
                    break
            if count >= max_files:
                break

        conn.executemany(
            "INSERT INTO file_map(root_id, rel_path, name, ext, size, mtime, cipher, seen_at) "
            "VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(root_id, rel_path) DO UPDATE SET "
            "size=excluded.size, mtime=excluded.mtime, cipher=excluded.cipher, seen_at=excluded.seen_at",
            batch,
        )
        for start in range(0, len(touch), 800):
            chunk = touch[start:start + 800]
            conn.execute(
                f"UPDATE file_map SET seen_at=? WHERE root_id=? AND rel_path IN ({','.join('?' * len(chunk))})",
                (seen_marker, root_id, *chunk),
            )
        removed = conn.execute(
            "DELETE FROM file_map WHERE root_id=? AND seen_at < ?", (root_id, seen_marker)
        ).rowcount
        elapsed = time.time() - started
        conn.execute(
            "UPDATE scan_roots SET last_scan_at=?, last_scan_sec=?, file_count=?, total_bytes=? WHERE id=?",
            (started, elapsed, count, total_bytes, root_id),
        )
        conn.commit()

    result = {
        "root": str(root), "files": count, "total_gb": round(total_bytes / 2**30, 2),
        "added": added, "updated": updated, "unchanged": unchanged, "removed": removed,
        "elapsed_sec": round(elapsed, 1),
    }
    logger.info("[FILEMAP] %s", result)
    return result


def search_map(
    q: str = "",
    ext: str = "",
    cipher: str = "",
    limit: int = 100,
    db_path: Path = FILE_MAP_DB,
) -> list[dict[str, Any]]:
    where, params = ["1=1"], []
    if q:
        where.append("(name LIKE ? OR rel_path LIKE ? OR cipher LIKE ?)")
        like = f"%{q}%"
        params += [like, like, like]
    if ext:
        where.append("ext=?")
        params.append(ext.lower().lstrip("."))
    if cipher:
        where.append("cipher LIKE ?")
        params.append(f"%{cipher}%")
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT r.path AS root, f.rel_path, f.name, f.ext, f.size, f.mtime, f.cipher
            FROM file_map f JOIN scan_roots r ON r.id = f.root_id
            WHERE {' AND '.join(where)}
            ORDER BY f.mtime DESC LIMIT ?
            """,
            (*params, min(limit, 500)),
        ).fetchall()
    return [dict(row) for row in rows]


def map_stats(db_path: Path = FILE_MAP_DB) -> dict[str, Any]:
    with _connect(db_path) as conn:
        roots = [dict(row) for row in conn.execute("SELECT * FROM scan_roots ORDER BY path")]
        by_ext = [
            dict(row)
            for row in conn.execute(
                "SELECT ext, COUNT(*) AS files, SUM(size) AS bytes FROM file_map "
                "GROUP BY ext ORDER BY files DESC LIMIT 25"
            )
        ]
        ciphered = conn.execute("SELECT COUNT(*) AS n FROM file_map WHERE cipher != ''").fetchone()["n"]
    return {"roots": roots, "by_ext": by_ext, "files_with_cipher": ciphered}
