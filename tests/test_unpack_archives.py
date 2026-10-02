"""Offline archive completion and input-integrity regressions."""
from __future__ import annotations

import hashlib
import json
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from tools import unpack_archives


MARKER = ".les-unpack-complete.json"


def _zip(path: Path, files: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as bundle:
        for name, content in files.items():
            bundle.writestr(name, content)
    return path


def _run(monkeypatch: pytest.MonkeyPatch, root: Path, *args: str) -> int:
    monkeypatch.setattr(sys, "argv", ["unpack_archives.py", str(root), *args])
    return unpack_archives.main()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_cli_failure_is_nonzero_and_other_archives_continue(tmp_path: Path) -> None:
    (tmp_path / "broken.zip").write_bytes(b"not a ZIP")
    _zip(tmp_path / "valid.zip", {"rows.csv": b"a,b\n1,2\n"})
    result = subprocess.run(
        [sys.executable, "-X", "utf8", str(Path(unpack_archives.__file__).resolve()), str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode != 0
    assert "broken.zip" in result.stdout
    assert (tmp_path / "valid__unpacked" / "rows.csv").read_bytes() == b"a,b\n1,2\n"
    assert (tmp_path / "valid__unpacked" / MARKER).is_file()
    assert not (tmp_path / "broken__unpacked" / MARKER).exists()


def test_partial_output_retries_and_preserves_existing_user_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = _zip(tmp_path / "partial.zip", {"first.txt": b"first", "nested/second.txt": b"second"})
    dest = tmp_path / "partial__unpacked"
    dest.mkdir()
    (dest / "first.txt").write_bytes(b"first")
    (dest / "my-notes.txt").write_bytes(b"user-owned")
    assert _run(monkeypatch, tmp_path) == 0
    assert (dest / "nested" / "second.txt").read_bytes() == b"second"
    assert (dest / "my-notes.txt").read_bytes() == b"user-owned"
    marker = json.loads((dest / MARKER).read_text(encoding="utf-8"))
    assert marker["source_sha256"] == _sha(archive)
    assert marker["source_name"] == archive.name
    assert {item["path"] for item in marker["files"]} == {"first.txt", "nested/second.txt"}


def test_completed_marker_checks_output_and_source_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = _zip(tmp_path / "revision.zip", {"a.txt": b"a", "b.txt": b"b"})
    assert _run(monkeypatch, tmp_path) == 0
    dest = tmp_path / "revision__unpacked"
    original_handler = unpack_archives._HANDLERS[".zip"]

    def unexpected_extract(*_args: object) -> int:
        raise AssertionError("completed output was unnecessarily re-extracted")

    monkeypatch.setitem(unpack_archives._HANDLERS, ".zip", unexpected_extract)
    assert _run(monkeypatch, tmp_path) == 0
    monkeypatch.setitem(unpack_archives._HANDLERS, ".zip", original_handler)
    (dest / "b.txt").unlink()
    assert _run(monkeypatch, tmp_path) == 0
    assert (dest / "b.txt").read_bytes() == b"b"
    previous_sha = _sha(archive)
    _zip(archive, {"a.txt": b"a", "b.txt": b"b", "c.txt": b"c"})
    assert _sha(archive) != previous_sha
    assert _run(monkeypatch, tmp_path) == 0
    assert (dest / "c.txt").read_bytes() == b"c"
    assert json.loads((dest / MARKER).read_text(encoding="utf-8"))["source_sha256"] == _sha(archive)


def test_conflicting_user_file_is_not_overwritten_or_marked_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _zip(tmp_path / "conflict.zip", {"a.txt": b"archive", "new.txt": b"new"})
    dest = tmp_path / "conflict__unpacked"
    dest.mkdir()
    (dest / "a.txt").write_bytes(b"user-owned")
    assert _run(monkeypatch, tmp_path) != 0
    assert (dest / "a.txt").read_bytes() == b"user-owned"
    assert not (dest / "new.txt").exists()
    assert not (dest / MARKER).exists()


def test_unknown_reserved_marker_is_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _zip(tmp_path / "marker.zip", {"a.txt": b"a"})
    dest = tmp_path / "marker__unpacked"
    dest.mkdir()
    (dest / MARKER).write_bytes(b"user-owned marker name")
    assert _run(monkeypatch, tmp_path) != 0
    assert (dest / MARKER).read_bytes() == b"user-owned marker name"
    assert not (dest / "a.txt").exists()


def test_changed_archive_conflict_preserves_output_and_previous_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = _zip(tmp_path / "changed.zip", {"a.txt": b"old"})
    assert _run(monkeypatch, tmp_path) == 0
    dest = tmp_path / "changed__unpacked"
    old_marker = (dest / MARKER).read_bytes()
    _zip(archive, {"a.txt": b"new"})
    assert _run(monkeypatch, tmp_path) != 0
    assert (dest / "a.txt").read_bytes() == b"old"
    assert (dest / MARKER).read_bytes() == old_marker


def test_removed_archive_file_blocks_new_completion_without_deleting_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    archive = _zip(tmp_path / "retired.zip", {"current.txt": b"current", "obsolete.txt": b"obsolete"})
    assert _run(monkeypatch, tmp_path) == 0
    dest = tmp_path / "retired__unpacked"
    old_marker = (dest / MARKER).read_bytes()
    (dest / "user-notes.txt").write_bytes(b"user-owned")
    _zip(archive, {"current.txt": b"current", "new.txt": b"new"})

    assert _run(monkeypatch, tmp_path) != 0
    assert "obsolete.txt" in capsys.readouterr().out
    assert (dest / "obsolete.txt").read_bytes() == b"obsolete"
    assert (dest / "user-notes.txt").read_bytes() == b"user-owned"
    assert not (dest / "new.txt").exists()
    assert (dest / MARKER).read_bytes() == old_marker


def test_retired_owned_file_already_absent_does_not_block_new_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = _zip(tmp_path / "absent.zip", {"current.txt": b"current", "obsolete.txt": b"obsolete"})
    assert _run(monkeypatch, tmp_path) == 0
    dest = tmp_path / "absent__unpacked"
    (dest / "obsolete.txt").unlink()
    _zip(archive, {"current.txt": b"current", "new.txt": b"new"})

    assert _run(monkeypatch, tmp_path) == 0
    assert (dest / "new.txt").read_bytes() == b"new"
    assert json.loads((dest / MARKER).read_text(encoding="utf-8"))["source_sha256"] == _sha(archive)


def test_resolved_scope_and_existing_junction_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path.resolve()
    with pytest.raises(ValueError):
        unpack_archives._checked_path(root, root.parent / "outside")
    blocked = root / "output"
    original = Path.is_junction
    monkeypatch.setattr(Path, "is_junction", lambda path: path == blocked or original(path))
    with pytest.raises(ValueError, match="output"):
        unpack_archives._checked_path(root, blocked / "nested.txt")


def test_source_changed_during_extraction_has_no_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = _zip(tmp_path / "moving.zip", {"a.txt": b"a"})
    original_handler = unpack_archives._HANDLERS[".zip"]

    def changing_source(path: Path, dest: Path) -> int:
        count = original_handler(path, dest)
        _zip(path, {"a.txt": b"changed"})
        return count

    monkeypatch.setitem(unpack_archives._HANDLERS, ".zip", changing_source)
    assert _run(monkeypatch, tmp_path) != 0
    assert not (tmp_path / "moving__unpacked").exists()
    assert archive.is_file()


def test_extraction_failure_can_be_retried_without_false_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _zip(tmp_path / "retry.zip", {"a.txt": b"a", "b.txt": b"b"})
    original_handler = unpack_archives._HANDLERS[".zip"]

    def fail_after_one_file(_path: Path, dest: Path) -> int:
        (dest / "a.txt").write_bytes(b"a")
        raise RuntimeError("simulated interrupted extraction")

    monkeypatch.setitem(unpack_archives._HANDLERS, ".zip", fail_after_one_file)
    assert _run(monkeypatch, tmp_path) != 0
    assert not (tmp_path / "retry__unpacked" / MARKER).exists()
    monkeypatch.setitem(unpack_archives._HANDLERS, ".zip", original_handler)
    assert _run(monkeypatch, tmp_path) == 0
    assert (tmp_path / "retry__unpacked" / "b.txt").read_bytes() == b"b"
    assert (tmp_path / "retry__unpacked" / MARKER).is_file()


@pytest.mark.parametrize("member", ["../escape.txt", "folder/../../escape.txt", "/absolute.txt", "C:\\escape.txt", "..\\escape.txt", "folder:stream.txt", MARKER])
def test_unsafe_member_is_rejected_before_any_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, member: str,
) -> None:
    _zip(tmp_path / "unsafe.zip", {"safe.txt": b"safe", member: b"unsafe"})
    assert _run(monkeypatch, tmp_path) != 0
    assert not (tmp_path / "unsafe__unpacked" / "safe.txt").exists()
    assert not (tmp_path / "unsafe__unpacked" / MARKER).exists()
    assert not (tmp_path / "escape.txt").exists()


def test_zip_symlink_is_rejected_before_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = zipfile.ZipInfo("link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(tmp_path / "link.zip", "w") as bundle:
        bundle.writestr(link, "../outside")
        bundle.writestr("safe.txt", "safe")
    assert _run(monkeypatch, tmp_path) != 0
    assert not (tmp_path / "link__unpacked" / "safe.txt").exists()


def test_missing_root_is_failure_and_dry_run_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _run(monkeypatch, tmp_path / "missing") != 0
    _zip(tmp_path / "dry.zip", {"a.txt": b"a"})
    assert _run(monkeypatch, tmp_path, "--dry-run") == 0
    assert not (tmp_path / "dry__unpacked").exists()


def test_unicode_and_spaces_in_archive_and_members(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = _zip(tmp_path / "архив с пробелом.zip", {"Раздел работ/объёмы.txt": "Объём 12,5".encode("utf-8")})
    assert _run(monkeypatch, tmp_path) == 0
    dest = tmp_path / f"{archive.stem}__unpacked"
    assert (dest / "Раздел работ" / "объёмы.txt").read_text(encoding="utf-8") == "Объём 12,5"
    assert json.loads((dest / MARKER).read_text(encoding="utf-8"))["source_name"] == archive.name
