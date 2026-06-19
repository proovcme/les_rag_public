"""Offline tests for the Windows installer tooling."""

from __future__ import annotations

from tools import build_windows_installer


def test_stage_runtime_copies_clean_export_with_app_files(tmp_path):
    dest = tmp_path / "LES"
    count = build_windows_installer.stage_runtime(dest)
    assert count > 0

    # The Windows bootstrap shipped inside the runtime export.
    assert (dest / "installers" / "windows" / "app" / "bootstrap.ps1").is_file()
    assert (dest / "installers" / "windows" / "app" / "launcher.vbs").is_file()
    assert (dest / "installers" / "windows" / "app" / "LES.nsi").is_file()
    assert (dest / "tools" / "onboard_models.py").is_file()

    # No secrets / local data leak into the package.
    assert not (dest / ".env").exists()
    assert not (dest / "storage").exists()
    assert not (dest / "data").exists()


def test_stage_runtime_is_idempotent(tmp_path):
    dest = tmp_path / "LES"
    first = build_windows_installer.stage_runtime(dest)
    second = build_windows_installer.stage_runtime(dest)  # rebuild over existing
    assert first == second


def test_bootstrap_ps1_is_utf8_bom(tmp_path):
    # Windows PowerShell 5.1 / NSIS need a BOM to read Cyrillic correctly.
    ps1 = build_windows_installer.ROOT / "installers" / "windows" / "app" / "bootstrap.ps1"
    nsi = build_windows_installer.ROOT / "installers" / "windows" / "app" / "LES.nsi"
    assert ps1.read_bytes()[:3] == b"\xef\xbb\xbf"
    assert nsi.read_bytes()[:3] == b"\xef\xbb\xbf"
