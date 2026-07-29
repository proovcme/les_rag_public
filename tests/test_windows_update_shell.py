from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools import windows_update_shell


def test_shell_builder_attests_exact_commit_and_builds_no_installer_or_baseline(
    tmp_path, monkeypatch
):
    base = tmp_path / "installed" / "les-desktop.exe"
    base.parent.mkdir()
    base.write_bytes(b"old shell")
    built = tmp_path / "target" / "release" / "les-desktop.exe"
    built.parent.mkdir(parents=True)
    built.write_bytes(b"new shell")
    commands: list[list[str]] = []

    monkeypatch.setattr(windows_update_shell.sys, "platform", "win32")
    monkeypatch.setattr(
        windows_update_shell,
        "require_clean_pushed_branch",
        lambda: ("codex/sovushka-ui-kit", "a" * 40),
    )
    monkeypatch.setattr(
        windows_update_shell,
        "version_contract",
        lambda: {
            "schema": "les.version.v1",
            "product_version": "0.25.18",
            "build_number": 491,
            "desktop_version": "5.1.491",
        },
    )
    monkeypatch.setattr(windows_update_shell, "BUILT_EXE", built)
    monkeypatch.setattr(windows_update_shell.shutil, "which", lambda _name: "cargo.exe")
    monkeypatch.setattr(
        windows_update_shell.subprocess,
        "run",
        lambda command, **_kwargs: commands.append([str(item) for item in command]),
    )

    result = windows_update_shell.build_shell(base_exe=base, output=tmp_path / "out")
    manifest = json.loads(
        Path(result["manifest"]).read_text(encoding="utf-8")
    )

    assert manifest["target_commit"] == "a" * 40
    assert manifest["product_version"] == "0.25.18"
    assert manifest["build_number"] == 491
    assert manifest["binary_sha256"] == hashlib.sha256(b"new shell").hexdigest()
    assert manifest["base_binary_sha256"] == hashlib.sha256(b"old shell").hexdigest()
    assert manifest["installer_built"] is False
    assert manifest["baseline_built"] is False
    assert any(command[1:3] == ["build", "--release"] for command in commands)
    flattened = " ".join(" ".join(command) for command in commands).lower()
    assert "tauri build" not in flattened
    assert "nsis" not in flattened
    assert "baseline" not in flattened


def test_shell_builder_rejects_non_windows_before_any_build(tmp_path, monkeypatch):
    base = tmp_path / "les-desktop.exe"
    base.write_bytes(b"old")
    monkeypatch.setattr(windows_update_shell.sys, "platform", "darwin")

    with pytest.raises(RuntimeError, match="only be built on Windows"):
        windows_update_shell.build_shell(base_exe=base, output=tmp_path / "out")
