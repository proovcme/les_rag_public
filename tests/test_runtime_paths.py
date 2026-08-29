from pathlib import Path

import pytest

from backend.runtime_paths import MutablePathError, mutable_path


def test_windows_state_root_owns_registered_mutable_path(tmp_path, monkeypatch):
    monkeypatch.setenv("LES_WINDOWS_STATE_ROOT", str(tmp_path / "state"))

    assert mutable_path("storage/artifacts/files") == (
        tmp_path / "state" / "storage" / "artifacts" / "files"
    )


def test_unknown_mutable_root_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("LES_WINDOWS_STATE_ROOT", str(tmp_path / "state"))

    with pytest.raises(MutablePathError, match="registered mutable root"):
        mutable_path("scratch/result.json")


def test_absolute_input_is_rejected(tmp_path):
    with pytest.raises(MutablePathError, match="relative"):
        mutable_path(Path(tmp_path) / "outside")


def test_repository_runtime_preserves_relative_path(monkeypatch):
    monkeypatch.delenv("LES_WINDOWS_STATE_ROOT", raising=False)

    assert mutable_path("logs/proxy.log") == Path("logs/proxy.log")
