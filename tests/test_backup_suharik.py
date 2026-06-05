"""
Unit tests for С.У.Х.А.Р.И.К. (tools/backup_suharik.py).
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
import tempfile
import sqlite3

from tools.backup_suharik import (
    run_sqlite_backup,
    rotate_sqlite_backups,
    rotate_qdrant_snapshots,
)


class TestBackupSuharik(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.backup_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("tools.backup_suharik.rag_meta_db_path")
    @patch("tools.backup_suharik.embed_profile_name")
    def test_sqlite_backup(self, mock_embed_profile, mock_db_path):
        # Create a mock source SQLite database
        source_db = self.backup_dir / "source.db"
        conn = sqlite3.connect(source_db)
        conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO test VALUES (1)")
        conn.commit()
        conn.close()

        mock_db_path.return_value = str(source_db)
        mock_embed_profile.return_value = "qwen"
        
        # Mock subdirectories under backup_dir
        (self.backup_dir / "storage" / "backups").mkdir(parents=True, exist_ok=True)

        with patch("tools.backup_suharik.project_root", self.backup_dir):
            ok, result = run_sqlite_backup()
            self.assertTrue(ok)
            self.assertTrue(Path(result).exists())
            self.assertIn("les_meta_qwen_", Path(result).name)

            # Verify data is copied
            conn_check = sqlite3.connect(result)
            row = conn_check.execute("SELECT * FROM test").fetchone()
            self.assertEqual(row[0], 1)
            conn_check.close()

    def test_sqlite_rotation(self):
        profile = "qwen"
        # Create 5 mock SQLite backup files
        for i in range(1, 6):
            backup_file = self.backup_dir / f"les_meta_{profile}_20260527_12000{i}.db"
            backup_file.touch()
            # Artificially set different modification times
            import os
            import time
            os.utime(backup_file, (time.time() + i, time.time() + i))

        rotate_sqlite_backups(self.backup_dir, profile)

        # Verify only the 3 newest remain
        remaining = sorted(
            self.backup_dir.glob(f"les_meta_{profile}_*.db"),
            key=lambda p: p.stat().st_mtime,
        )
        self.assertEqual(len(remaining), 3)
        self.assertEqual(remaining[0].name, "les_meta_qwen_20260527_120003.db")
        self.assertEqual(remaining[1].name, "les_meta_qwen_20260527_120004.db")
        self.assertEqual(remaining[2].name, "les_meta_qwen_20260527_120005.db")

    def test_qdrant_rotation(self):
        mock_client = MagicMock()
        mock_collection = "les_rag_qwen3_06b"
        
        # Mock snapshots returned from list_snapshots
        snap1 = MagicMock()
        snap1.name = "snap1"
        snap1.creation_time = "2026-05-27T06:00:00"

        snap2 = MagicMock()
        snap2.name = "snap2"
        snap2.creation_time = "2026-05-27T07:00:00"

        snap3 = MagicMock()
        snap3.name = "snap3"
        snap3.creation_time = "2026-05-27T08:00:00"

        snap4 = MagicMock()
        snap4.name = "snap4"
        snap4.creation_time = "2026-05-27T09:00:00"

        mock_client.list_snapshots.return_value = [snap1, snap2, snap3, snap4]

        rotate_qdrant_snapshots(mock_client, mock_collection)

        # Verify delete_snapshot was called on the oldest snapshot
        mock_client.delete_snapshot.assert_called_once_with(mock_collection, "snap1")


if __name__ == "__main__":
    unittest.main()
