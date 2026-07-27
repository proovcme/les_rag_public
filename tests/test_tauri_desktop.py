from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from tools import build_release_artifacts, build_tauri_app
from tools import smeta_release_baseline


ROOT = Path(__file__).resolve().parents[1]
TAURI = ROOT / "desktop" / "tauri"


def test_tauri_config_is_the_canonical_les_desktop_shell():
    config = json.loads((TAURI / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))

    assert config["identifier"] == "me.ovc.les"
    assert config["productName"] == "ЛЕС"
    assert config["build"]["frontendDist"] == "../web"
    assert config["app"]["withGlobalTauri"] is True
    assert config["app"]["windows"][0]["url"] == "index.html"
    assert config["bundle"]["windows"]["nsis"]["installMode"] == "currentUser"
    assert config["bundle"]["windows"]["nsis"]["installerHooks"] == "windows-installer-hooks.nsh"
    assert config["bundle"]["resources"] == {"resources/": "."}

    hooks = (TAURI / "src-tauri" / "windows-installer-hooks.nsh").read_text(encoding="utf-8")
    assert '$LOCALAPPDATA\\Programs\\LES' in hooks
    assert '${FileExists} "$INSTDIR\\${MAINBINARYNAME}.exe"' in hooks


def test_tauri_rust_shell_owns_only_lifecycle_and_navigation():
    source = (TAURI / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")

    assert 'const UI_URL: &str = "http://127.0.0.1:8051/les"' in source
    assert 'windows-light-state.json' in source
    assert 'std::env::var_os("LOCALAPPDATA")' in source
    assert 'join("LES")' in source
    assert 'payload.get("ui_url")' in source
    assert 'response.contains("\\\"service\\\":\\\"sovushka\\\"")' in source
    assert 'env("LES_TAURI_SHELL", "1")' in source
    assert 'env("LES_TAURI_ACTION", action)' in source
    assert 'bootstrap-status.json' in source
    assert "trim_start_matches('\\u{feff}')" in source
    assert 'tauri-bootstrap.err.log' in source
    assert 'strip_prefix(r"\\\\?\\")' in source
    assert "powershell_file_arg(" in source
    assert 'std::fs::remove_file(path)' in source
    assert '.get("install_url")' in source
    assert 'creation_flags(0x0800_0000)' in source
    assert '"restart" => run_action' in source
    assert '"stop" => run_action' in source
    assert '"setup" => show_setup' in source
    assert "setup_snapshot" in source
    assert "install_setup_component" in source
    assert "start_from_setup" in source
    assert "retry_setup" in source
    assert "search_norm" not in source
    assert "submit_lsr_mapping" not in source

    wizard = (TAURI / "web" / "index.html").read_text(encoding="utf-8")
    script = (TAURI / "web" / "wizard.js").read_text(encoding="utf-8")
    assert "Настройка Л.Е.С." in wizard
    assert "Рекомендации после запуска" in wizard
    assert "ollama pull qwen3.5:9b" in wizard
    assert "ollama pull bge-m3" in wizard
    assert 'invoke("install_setup_component"' in script
    assert 'invoke("start_from_setup"' in script


def test_tauri_bootstrap_does_not_install_or_launch_pywebview():
    mac = (ROOT / "installers/macos/app/bootstrap.sh").read_text(encoding="utf-8")
    windows = (ROOT / "installers/windows/app/bootstrap.ps1").read_text(encoding="utf-8-sig")

    assert "uv sync --extra mac-mlx (Tauri owns desktop shell)" in mac
    assert 'LES_TAURI_SHELL:-0' in mac
    assert "lesctl start --include-ui (Tauri shell)" in mac
    assert 'LES_TAURI_SHELL -eq "1"' in windows
    assert '$BootstrapPath.StartsWith("\\\\?\\")' in windows
    assert "uv sync with bundled Python (Tauri owns desktop shell)" in windows
    assert '"--no-python-downloads"' in windows
    assert '@("--extra", "windows-reranker")' in windows
    assert "start-light (Tauri shell)" in windows


def test_tauri_runtime_stage_excludes_recursive_shell_and_local_ui_state(tmp_path, monkeypatch):
    repo_file = ROOT / "README.md"
    tauri_file = TAURI / "package.json"
    nicegui_file = ROOT / ".nicegui" / "secret-state.json"
    monkeypatch.setattr(build_tauri_app, "RESOURCES", tmp_path / "resources")
    monkeypatch.setattr(build_tauri_app, "iter_files", lambda: [repo_file, tauri_file])

    assert build_tauri_app.stage_runtime("linux") == 1
    assert (tmp_path / "resources/runtime/README.md").is_file()
    assert not (tmp_path / "resources/runtime/desktop/tauri/package.json").exists()
    assert build_release_artifacts.should_exclude(nicegui_file)


def test_tauri_runtime_stage_is_platform_specific(tmp_path, monkeypatch):
    mac_bootstrap = ROOT / "installers/macos/app/bootstrap.sh"
    windows_bootstrap = ROOT / "installers/windows/app/bootstrap.ps1"
    resources = tmp_path / "resources"
    monkeypatch.setattr(build_tauri_app, "RESOURCES", resources)
    monkeypatch.setattr(
        build_tauri_app,
        "iter_files",
        lambda: [mac_bootstrap, windows_bootstrap],
    )
    monkeypatch.setattr(build_tauri_app, "stage_windows_uv", lambda _runtime, **_kwargs: 0)
    monkeypatch.setattr(build_tauri_app, "stage_windows_python", lambda _runtime, **_kwargs: 0)

    assert build_tauri_app.stage_runtime("win32") == 1
    assert not (resources / "bootstrap.sh").exists()
    assert not (resources / "runtime/installers/macos/app/bootstrap.sh").exists()
    assert (resources / "runtime/installers/windows/app/bootstrap.ps1").is_file()

    assert build_tauri_app.stage_runtime("darwin") == 1
    assert (resources / "bootstrap.sh").is_file()
    assert (resources / "runtime/installers/macos/app/bootstrap.sh").is_file()
    assert not (resources / "runtime/installers/windows/app/bootstrap.ps1").exists()


def test_windows_tauri_stage_bundles_verified_smeta_baseline(tmp_path, monkeypatch):
    resources = tmp_path / "resources"
    archive = tmp_path / "LES-smeta-baseline.zip"
    archive.write_bytes(b"verified-baseline")
    monkeypatch.setattr(build_tauri_app, "RESOURCES", resources)
    monkeypatch.setattr(build_tauri_app, "iter_files", lambda: [ROOT / "README.md"])
    monkeypatch.setattr(smeta_release_baseline, "verify_archive", lambda path: {"ok": True})
    monkeypatch.setattr(build_tauri_app, "stage_windows_uv", lambda _runtime, **_kwargs: 0)
    monkeypatch.setattr(build_tauri_app, "stage_windows_python", lambda _runtime, **_kwargs: 0)

    assert build_tauri_app.stage_runtime("win32", smeta_baseline_archive=archive) == 2
    assert (
        resources / "runtime/installers/windows/baseline/LES-smeta-baseline.zip"
    ).read_bytes() == b"verified-baseline"


def test_windows_tauri_stage_bundles_verified_uv(tmp_path, monkeypatch):
    archive = tmp_path / "uv.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("uv.exe", b"verified-uv")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    contract = tmp_path / "windows_uv.json"
    contract.write_text(json.dumps({
        "schema": "les.windows-uv.v1",
        "version": "test",
        "archive_url": "https://example.test/uv.zip",
        "archive_sha256": digest,
        "binary_sha256": hashlib.sha256(b"verified-uv").hexdigest(),
        "binary_name": "uv.exe",
    }), encoding="utf-8")
    resources = tmp_path / "resources"
    monkeypatch.setattr(build_tauri_app, "RESOURCES", resources)
    monkeypatch.setattr(build_tauri_app, "WINDOWS_UV_CONTRACT_PATH", contract)
    monkeypatch.setattr(build_tauri_app, "iter_files", lambda: [ROOT / "README.md"])
    monkeypatch.setattr(build_tauri_app, "stage_windows_python", lambda _runtime, **_kwargs: 0)

    assert build_tauri_app.stage_runtime("win32", windows_uv_archive=archive) == 2
    assert (resources / "runtime/installers/windows/tools/uv.exe").read_bytes() == b"verified-uv"


def test_windows_tauri_stage_rejects_tampered_uv_binary(tmp_path, monkeypatch):
    archive = tmp_path / "uv.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("uv.exe", b"tampered-uv")
    contract = tmp_path / "windows_uv.json"
    contract.write_text(json.dumps({
        "schema": "les.windows-uv.v1",
        "version": "test",
        "archive_url": "https://example.test/uv.zip",
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "binary_sha256": hashlib.sha256(b"expected-uv").hexdigest(),
        "binary_name": "uv.exe",
    }), encoding="utf-8")
    monkeypatch.setattr(build_tauri_app, "WINDOWS_UV_CONTRACT_PATH", contract)

    with pytest.raises(RuntimeError, match="uv.exe SHA-256 mismatch"):
        build_tauri_app.stage_windows_uv(tmp_path / "runtime", archive_path=archive)


def test_windows_tauri_stage_bundles_verified_python(tmp_path, monkeypatch):
    archive = tmp_path / "python.zip"
    archive.write_bytes(b"verified-python-archive")
    contract = tmp_path / "windows_python.json"
    contract.write_text(json.dumps({
        "schema": "les.windows-python.v2",
        "version": "test",
        "archive_url": "https://example.test/python.zip",
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "archive_name": "python-embed.zip",
        "python_relative_path": "python.exe",
    }), encoding="utf-8")
    monkeypatch.setattr(build_tauri_app, "WINDOWS_PYTHON_CONTRACT_PATH", contract)

    assert build_tauri_app.stage_windows_python(tmp_path / "runtime", archive_path=archive) == 1
    assert (tmp_path / "runtime/installers/windows/tools/python-embed.zip").read_bytes() == archive.read_bytes()


def test_windows_tauri_stage_rejects_tampered_python_archive(tmp_path, monkeypatch):
    archive = tmp_path / "python.zip"
    archive.write_bytes(b"tampered-python-archive")
    contract = tmp_path / "windows_python.json"
    contract.write_text(json.dumps({
        "schema": "les.windows-python.v2",
        "version": "test",
        "archive_url": "https://example.test/python.zip",
        "archive_sha256": hashlib.sha256(b"expected-python-archive").hexdigest(),
        "archive_name": "python-embed.zip",
        "python_relative_path": "python.exe",
    }), encoding="utf-8")
    monkeypatch.setattr(build_tauri_app, "WINDOWS_PYTHON_CONTRACT_PATH", contract)

    with pytest.raises(RuntimeError, match="Python archive SHA-256 mismatch"):
        build_tauri_app.stage_windows_python(tmp_path / "runtime", archive_path=archive)


def test_release_stage_excludes_agent_and_runtime_temporary_files():
    assert build_release_artifacts.should_exclude(ROOT / ".codex_tmp" / "private-probe.json")
    assert build_release_artifacts.should_exclude(ROOT / "tmp" / "runtime-diagnostic.txt")


def test_legacy_macos_builder_delegates_to_tauri():
    source = (ROOT / "tools/build_macos_app.py").read_text(encoding="utf-8")
    assert "from tools.build_tauri_app import build" in source
    assert 'build(version, "app")' in source


def test_windows_builder_never_emits_old_shell_exe_on_non_windows():
    source = (ROOT / "tools/build_windows_installer.py").read_text(encoding="utf-8")
    assert 'build_tauri(version, "nsis", build_number=build_number)' in source
    assert "LES-windows-tauri-source" in source
    assert "makensis" not in source


def test_tauri_builder_resolves_windows_npm_cmd(monkeypatch):
    seen: list[str] = []

    def fake_which(name: str):
        seen.append(name)
        return r"C:\Program Files\nodejs\npm.cmd" if name == "npm.cmd" else None

    monkeypatch.setattr(build_tauri_app.shutil, "which", fake_which)

    assert build_tauri_app.npm_executable("win32").endswith("npm.cmd")
    assert seen == ["npm.cmd"]


def test_tauri_builder_maps_four_part_les_version_to_desktop_semver():
    assert build_tauri_app.desktop_semver("0.24.0.401") == "5.1.401"
    assert build_tauri_app.desktop_semver("5.1.401") == "5.1.401"


def test_tauri_builder_separates_product_version_from_monotonic_build():
    assert build_tauri_app.desktop_semver("0.24.1", 407) == "5.1.407"
    contract = build_tauri_app.release_contract()
    assert contract["desktop_version"] == build_tauri_app.desktop_semver(
        str(contract["product_version"]), int(contract["build_number"])
    )
