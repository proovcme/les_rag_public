from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import pytest
from pathlib import Path

from backend.ingestion_ownership import file_ingestion_lock, ingestion_lock_path


def _run_holder(root: Path, dataset: str, file_key: str, marker: Path, hold: float) -> subprocess.Popen:
    """Take the lock in a separate process and record when the section runs."""
    program = textwrap.dedent(
        f"""
        import json, os, sys, time
        sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r})
        from backend.ingestion_ownership import file_ingestion_lock

        with file_ingestion_lock({dataset!r}, {file_key!r}, root={str(root)!r}, timeout_seconds=30.0):
            entered = time.monotonic()
            time.sleep({hold})
            left = time.monotonic()
        # Distinct files: concurrent Windows buffered append can lose a receipt.
        with open({str(marker)!r} + "." + str(os.getpid()), "w", encoding="utf-8") as stream:
            stream.write(json.dumps({{"entered": entered, "left": left}}) + "\\n")
        """
    )
    return subprocess.Popen([sys.executable, "-c", program])


def _intervals(marker: Path) -> list[tuple[float, float]]:
    rows = [json.loads(path.read_text(encoding="utf-8"))
            for path in marker.parent.glob(marker.name + ".*")]
    return sorted((row["entered"], row["left"]) for row in rows)


def test_same_file_replacements_cannot_overlap(tmp_path: Path) -> None:
    """Two parses of one file must not interleave their replace windows.

    Both would read the same old point ids and then delete each other's fresh
    evidence, leaving the document indexed but unsearchable.
    """
    marker = tmp_path / "windows.jsonl"
    first = _run_holder(tmp_path, "dataset", "spec.pdf", marker, 1.0)
    second = _run_holder(tmp_path, "dataset", "spec.pdf", marker, 1.0)
    assert first.wait(timeout=120) == 0
    assert second.wait(timeout=120) == 0

    windows = _intervals(marker)
    assert len(windows) == 2
    assert windows[0][1] <= windows[1][0], "replace windows overlapped"


def test_different_files_are_not_serialized(tmp_path: Path) -> None:
    """The lock is per file: unrelated documents keep indexing in parallel."""
    marker = tmp_path / "windows.jsonl"
    first = _run_holder(tmp_path, "dataset", "one.pdf", marker, 1.0)
    second = _run_holder(tmp_path, "dataset", "two.pdf", marker, 1.0)
    assert first.wait(timeout=120) == 0
    assert second.wait(timeout=120) == 0

    windows = _intervals(marker)
    assert len(windows) == 2
    assert windows[0][1] > windows[1][0], "unrelated files were serialized"


def test_lock_path_is_scoped_and_filesystem_safe(tmp_path: Path) -> None:
    path = ingestion_lock_path("dataset/id", "../../etc/passwd", root=tmp_path)

    assert path.parent == tmp_path / "ingestion-locks"
    assert path.suffix == ".lock"
    assert ".." not in path.name and "/" not in path.name and "\\" not in path.name
    assert path != ingestion_lock_path("dataset/id", "other.pdf", root=tmp_path)


def test_lock_is_released_when_the_section_raises(tmp_path: Path) -> None:
    try:
        with file_ingestion_lock("dataset", "spec.pdf", root=tmp_path, timeout_seconds=5.0):
            raise RuntimeError("indexing failed")
    except RuntimeError:
        pass

    with file_ingestion_lock("dataset", "spec.pdf", root=tmp_path, timeout_seconds=5.0):
        pass


def test_contended_lock_has_bounded_timeout(tmp_path):
    with file_ingestion_lock("dataset", "spec.pdf", root=tmp_path):
        with pytest.raises(TimeoutError):
            with file_ingestion_lock("dataset", "spec.pdf", root=tmp_path, timeout_seconds=0):
                pytest.fail("contender entered the owned window")
