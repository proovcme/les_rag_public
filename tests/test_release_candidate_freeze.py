from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from pathlib import Path

import pytest

from tools import release_orchestrator as release


def _candidate(tmp_path):
    root = tmp_path / "candidate"
    public = root / "public"
    public.mkdir(parents=True)
    asset = public / "LES-Setup.exe"
    asset.write_bytes(b"exact-candidate")
    return root, {"assets": [asset], "acceptance_path": public}


def _lock_error(code):
    error = PermissionError("injected Windows sharing lock")
    error.winerror = code
    return error


def test_freeze_retries_only_bounded_windows_locks_and_verifies_bytes(monkeypatch, tmp_path):
    root, built = _candidate(tmp_path)
    replace = release.os.replace
    calls, sleeps = [], []
    def locked(source, target):
        calls.append((source, target))
        if len(calls) < 3:
            raise _lock_error(32 if len(calls) == 1 else 5)
        return replace(source, target)
    monkeypatch.setattr(release.os, "replace", locked)
    monkeypatch.setattr(release.time, "sleep", sleeps.append)

    frozen = release._freeze_candidate(work_root=tmp_path / "work", candidate_root=root, built=built)

    assert len(calls) == 3 and sleeps == [0.1, 0.2]
    assert frozen["assets"][0].read_bytes() == b"exact-candidate"


@pytest.mark.parametrize("code, expected_calls", [(5, 3), (32, 3), (33, 3), (3, 1)])
def test_freeze_keeps_final_failure_visible_and_source_intact(monkeypatch, tmp_path, code, expected_calls):
    root, built = _candidate(tmp_path)
    calls = []
    def locked(source, target):
        calls.append((source, target))
        raise _lock_error(code)
    monkeypatch.setattr(release.os, "replace", locked)
    monkeypatch.setattr(release.time, "sleep", lambda seconds: None)
    with pytest.raises(PermissionError) as failure:
        release._freeze_candidate(work_root=tmp_path / "work", candidate_root=root, built=built)
    assert failure.value.winerror == code
    assert len(calls) == expected_calls
    assert built["assets"][0].read_bytes() == b"exact-candidate"
    assert not calls[-1][1].exists()
    assert calls[-1][0].is_dir()


def test_existing_frozen_candidate_with_different_bytes_is_never_overwritten(monkeypatch, tmp_path):
    root, built = _candidate(tmp_path)
    values = dict(work_root=tmp_path / "work", candidate_root=root, built=built)
    frozen = release._freeze_candidate(**values)
    asset = frozen["assets"][0]
    asset.write_bytes(b"different-bytes")
    monkeypatch.setattr(release.os, "replace", lambda *a: pytest.fail("existing artifact must not be overwritten"))
    with pytest.raises(RuntimeError, match="asset bytes"):
        release._freeze_candidate(**values)
    assert asset.read_bytes() == b"different-bytes"
    assert built["assets"][0].read_bytes() == b"exact-candidate"


@pytest.mark.skipif(os.name != "nt", reason="actual Windows sharing semantics")
def test_freeze_recovers_after_real_windows_no_delete_share_handle_is_closed(monkeypatch, tmp_path):
    root, built = _candidate(tmp_path)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                  wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    copytree = release.shutil.copytree
    handle = None
    sleeps = []
    def copied_then_locked(source, target, *args, **kwargs):
        nonlocal handle
        result = copytree(source, target, *args, **kwargs)
        if Path(source) == root:
            handle = kernel.CreateFileW(str(Path(target) / "public/LES-Setup.exe"),
                                        0x80000000, 0x1 | 0x2, None, 3, 0x80, None)
            assert handle != ctypes.c_void_p(-1).value, ctypes.get_last_error()
        return result
    def unlock(seconds):
        nonlocal handle
        sleeps.append(seconds)
        assert kernel.CloseHandle(handle)
        handle = None
    monkeypatch.setattr(release.shutil, "copytree", copied_then_locked)
    monkeypatch.setattr(release.time, "sleep", unlock)
    try:
        frozen = release._freeze_candidate(work_root=tmp_path / "work", candidate_root=root, built=built)
        assert sleeps == [0.1]
        assert frozen["assets"][0].read_bytes() == b"exact-candidate"
    finally:
        if handle is not None:
            kernel.CloseHandle(handle)
