#!/usr/bin/env python3
"""
С.У.Х.А.Р.И.К. (Система Управления Холодными Архивами и Резервными Источниками Комплекса)
Standalone Backup Utility for SQLite and Qdrant.
"""

from __future__ import annotations

import os
import sys
import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from qdrant_client import QdrantClient

# Add project root to python path to support running from anywhere
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from backend.rag_config import (
    rag_meta_db_path,
    rag_collection_name,
    embed_profile_name,
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("suharik")


def run_sqlite_backup() -> tuple[bool, str]:
    """
    Performs a non-blocking WAL-friendly atomic backup of the SQLite metadata database.
    Retains only the 3 latest backups.
    """
    try:
        db_path_str = rag_meta_db_path()
        db_path = Path(db_path_str).resolve()
        if not db_path.exists():
            return False, f"Source SQLite database not found at {db_path_str}"

        profile = embed_profile_name()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = project_root / "storage" / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)

        backup_file = backup_dir / f"les_meta_{profile}_{timestamp}.db"

        logger.info(f"Starting SQLite backup of {db_path.name}...")
        
        # Connect to source and target to perform non-blocking backup
        src_conn = sqlite3.connect(db_path)
        dst_conn = sqlite3.connect(backup_file)
        try:
            with dst_conn:
                src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
            src_conn.close()

        logger.info(f"SQLite backup successfully created: {backup_file.name}")

        # Rotate SQLite backups (keep 3 latest)
        rotate_sqlite_backups(backup_dir, profile)

        return True, str(backup_file)
    except Exception as e:
        logger.error(f"SQLite backup failed: {e}")
        return False, str(e)


def rotate_sqlite_backups(backup_dir: Path, profile: str) -> None:
    """Retains only the 3 latest SQLite backup files for the current profile."""
    try:
        pattern = f"les_meta_{profile}_*.db"
        backups = sorted(
            backup_dir.glob(pattern),
            key=lambda p: p.stat().st_mtime,
        )
        if len(backups) > 3:
            to_delete = backups[:-3]
            for path in to_delete:
                try:
                    path.unlink()
                    logger.info(f"Pruned old SQLite backup file: {path.name}")
                except Exception as e:
                    logger.warning(f"Failed to delete old SQLite backup {path.name}: {e}")
    except Exception as e:
        logger.warning(f"Error during SQLite backup rotation: {e}")


def run_qdrant_backup() -> tuple[bool, str]:
    """
    Triggers Qdrant snapshot generation for the current active collection.
    Uses custom HTTP client timeouts to prevent ReadTimeouts during large snapshot writes.
    Retains only the 3 latest snapshots.
    """
    try:
        collection_name = rag_collection_name()
        qdrant_url = os.getenv("QDRANT_URL", "http://127.0.0.1:6333")
        
        logger.info(f"Connecting to Qdrant at {qdrant_url}...")
        # Instantiating QdrantClient with a generous 10-minute timeout for large collections
        client = QdrantClient(url=qdrant_url, timeout=600.0)
        
        if not client.collection_exists(collection_name):
            return False, f"Qdrant collection '{collection_name}' does not exist"

        logger.info(f"Triggering Qdrant snapshot for collection '{collection_name}' (this might take a while)...")
        snapshot = client.create_snapshot(collection_name=collection_name, wait=True)
        if not snapshot:
            return False, "Qdrant server returned empty snapshot response"

        logger.info(f"Qdrant snapshot successfully created: {snapshot.name} ({snapshot.size} bytes)")

        # Rotate Qdrant snapshots (keep 3 latest)
        rotate_qdrant_snapshots(client, collection_name)

        return True, snapshot.name
    except Exception as e:
        logger.error(f"Qdrant snapshot failed: {e}")
        return False, str(e)


def rotate_qdrant_snapshots(client: QdrantClient, collection_name: str) -> None:
    """Retains only the 3 latest Qdrant snapshots for the collection."""
    try:
        snapshots = client.list_snapshots(collection_name)
        # Sort snapshots by creation_time, oldest first
        snapshots_sorted = sorted(
            snapshots,
            key=lambda s: s.creation_time or "",
        )
        if len(snapshots_sorted) > 3:
            to_delete = snapshots_sorted[:-3]
            for snap in to_delete:
                try:
                    client.delete_snapshot(collection_name, snap.name)
                    logger.info(f"Pruned old Qdrant snapshot: {snap.name}")
                except Exception as e:
                    logger.warning(f"Failed to delete old Qdrant snapshot {snap.name}: {e}")
    except Exception as e:
        logger.warning(f"Error during Qdrant snapshot rotation: {e}")


def main() -> int:
    logger.info("=" * 60)
    logger.info("С.У.Х.А.Р.И.К. // ЗАПУСК СИНХРОННОГО БЭКАПА СИСТЕМЫ")
    logger.info("=" * 60)
    
    sqlite_ok, sqlite_res = run_sqlite_backup()
    qdrant_ok, qdrant_res = run_qdrant_backup()

    logger.info("=" * 60)
    logger.info("ИТОГИ РЕЗЕРВНОГО КОПИРОВАНИЯ:")
    logger.info(f"- SQLite WAL Метабаза: {'[OK] ' + Path(sqlite_res).name if sqlite_ok else '[FAIL] ' + sqlite_res}")
    logger.info(f"- Qdrant Снапшот:      {'[OK] ' + qdrant_res if qdrant_ok else '[FAIL] ' + qdrant_res}")
    logger.info("=" * 60)

    if sqlite_ok and qdrant_ok:
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
