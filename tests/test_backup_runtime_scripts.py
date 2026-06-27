from __future__ import annotations

import subprocess
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESTORE = ROOT / "tools" / "restore_runtime.sh"


def _write_archive(path: Path, *, corrupt: bool = False) -> None:
    path.mkdir()
    (path / "MANIFEST.txt").write_text("ts=20260627_120000\nchecksum=SHA256SUMS.txt\n", encoding="utf-8")
    db = path / "les_meta_qwen.db"
    db.write_text("ok\n", encoding="utf-8")
    checksum = subprocess.check_output(["shasum", "-a", "256", "les_meta_qwen.db"], cwd=path, text=True)
    (path / "SHA256SUMS.txt").write_text(checksum, encoding="utf-8")
    if corrupt:
        db.write_text("changed\n", encoding="utf-8")


def test_restore_runtime_dry_run_verifies_checksum(tmp_path):
    archive = tmp_path / "backup-ok"
    _write_archive(archive)

    result = subprocess.run(
        ["/bin/bash", str(RESTORE), str(archive), "--dry-run"],
        env={**os.environ, "LES_HOME": str(tmp_path / "les")},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "checksum: ok" in result.stdout
    assert "DRY-RUN" in result.stdout


def test_restore_runtime_stops_on_checksum_mismatch(tmp_path):
    archive = tmp_path / "backup-bad"
    _write_archive(archive, corrupt=True)

    result = subprocess.run(
        ["/bin/bash", str(RESTORE), str(archive), "--dry-run"],
        env={**os.environ, "LES_HOME": str(tmp_path / "les")},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "checksum mismatch" in result.stderr
