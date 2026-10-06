"""A clean Windows payload must carry exact native reader/collector dependencies."""
from __future__ import annotations

import hashlib
from pathlib import Path

from tools import build_tauri_app


ROOT = Path(__file__).resolve().parents[1]


def test_clean_windows_stage_keeps_exact_rtf_helper_without_broad_tools(monkeypatch, tmp_path):
    parser = ROOT / "backend/rtf_parser.py"
    native_helper = ROOT / "tools/windows_rtf_extract.ps1"
    repository_only_tool = ROOT / "tools/build_tauri_app.py"
    resources = tmp_path / "resources"
    build_tauri_app.windows_runtime_manifest.cache_clear()
    monkeypatch.setattr(build_tauri_app, "RESOURCES", resources)
    monkeypatch.setattr(build_tauri_app, "iter_files", lambda: [parser, native_helper, repository_only_tool])
    # Test the real application allowlist and copy boundary; no executable,
    # dependency cache, installer, service, model or network operation is run.
    for name in ("stage_windows_uv", "stage_windows_python", "stage_windows_uv_cache", "stage_windows_deploy_stamp"):
        monkeypatch.setattr(build_tauri_app, name, lambda *_args, **_kwargs: 0)

    assert build_tauri_app.stage_runtime("win32") == 2
    staged = resources / "runtime"
    assert (staged / "backend/rtf_parser.py").is_file()
    installed_dependency = staged / "tools/windows_rtf_extract.ps1"
    assert installed_dependency.is_file()
    assert hashlib.sha256(installed_dependency.read_bytes()).digest() == hashlib.sha256(native_helper.read_bytes()).digest()
    assert not (staged / "tools/build_tauri_app.py").exists()
    files, prefixes = build_tauri_app.windows_runtime_manifest()
    assert "tools/windows_rtf_extract.ps1" in files
    assert "tools/" not in prefixes


def test_clean_windows_stage_keeps_exact_classic_outlook_sources_from_real_export(monkeypatch, tmp_path):
    required = [ROOT / "clients/outlook_mail_poller/setup_task.ps1", ROOT / "clients/outlook_mail_poller/LesMailPoller.cs"]
    repository_only_readme = ROOT / "clients/outlook_mail_poller/README.md"
    # The real Git-backed release iterator must admit these exact sources before
    # the Windows application allowlist gets its say. Do not merely invent a
    # fixture export that bypasses a tracked-file/exclusion defect.
    actual_export = set(build_tauri_app.iter_files())
    assert set(required).issubset(actual_export)
    assert repository_only_readme in actual_export
    resources = tmp_path / "resources"
    build_tauri_app.windows_runtime_manifest.cache_clear()
    monkeypatch.setattr(build_tauri_app, "RESOURCES", resources)
    monkeypatch.setattr(build_tauri_app, "iter_files", lambda: [*required, repository_only_readme])
    for name in ("stage_windows_uv", "stage_windows_python", "stage_windows_uv_cache", "stage_windows_deploy_stamp"):
        monkeypatch.setattr(build_tauri_app, name, lambda *_args, **_kwargs: 0)

    assert build_tauri_app.stage_runtime("win32") == 2
    for source in required:
        target = resources / "runtime" / source.relative_to(ROOT)
        assert target.is_file()
        assert hashlib.sha256(target.read_bytes()).digest() == hashlib.sha256(source.read_bytes()).digest()
    assert not (resources / "runtime" / repository_only_readme.relative_to(ROOT)).exists()
    files, prefixes = build_tauri_app.windows_runtime_manifest()
    assert {path.relative_to(ROOT).as_posix() for path in required}.issubset(files)
    assert "clients/" not in prefixes and "clients/outlook_mail_poller/" not in prefixes
