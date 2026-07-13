from __future__ import annotations

import json
from pathlib import Path

from tools import build_release_artifacts, build_tauri_app


ROOT = Path(__file__).resolve().parents[1]
TAURI = ROOT / "desktop" / "tauri"


def test_tauri_config_is_the_canonical_les_desktop_shell():
    config = json.loads((TAURI / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))

    assert config["identifier"] == "me.ovc.les"
    assert config["productName"] == "ЛЕС"
    assert config["build"]["frontendDist"] == "../web"
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
    assert '.get("install_url")' in source
    assert 'creation_flags(0x0800_0000)' in source
    assert '"restart" => run_action' in source
    assert '"stop" => run_action' in source
    assert "search_norm" not in source
    assert "submit_lsr_mapping" not in source


def test_tauri_bootstrap_does_not_install_or_launch_pywebview():
    mac = (ROOT / "installers/macos/app/bootstrap.sh").read_text(encoding="utf-8")
    windows = (ROOT / "installers/windows/app/bootstrap.ps1").read_text(encoding="utf-8-sig")

    assert "uv sync --extra mac-mlx (Tauri owns desktop shell)" in mac
    assert 'LES_TAURI_SHELL:-0' in mac
    assert "lesctl start --include-ui (Tauri shell)" in mac
    assert 'LES_TAURI_SHELL -eq "1"' in windows
    assert "uv sync (Tauri owns desktop shell)" in windows
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

    assert build_tauri_app.stage_runtime("win32") == 1
    assert not (resources / "bootstrap.sh").exists()
    assert not (resources / "runtime/installers/macos/app/bootstrap.sh").exists()
    assert (resources / "runtime/installers/windows/app/bootstrap.ps1").is_file()

    assert build_tauri_app.stage_runtime("darwin") == 1
    assert (resources / "bootstrap.sh").is_file()
    assert (resources / "runtime/installers/macos/app/bootstrap.sh").is_file()
    assert not (resources / "runtime/installers/windows/app/bootstrap.ps1").exists()


def test_release_stage_excludes_agent_and_runtime_temporary_files():
    assert build_release_artifacts.should_exclude(ROOT / ".codex_tmp" / "private-probe.json")
    assert build_release_artifacts.should_exclude(ROOT / "tmp" / "runtime-diagnostic.txt")


def test_legacy_macos_builder_delegates_to_tauri():
    source = (ROOT / "tools/build_macos_app.py").read_text(encoding="utf-8")
    assert "from tools.build_tauri_app import build" in source
    assert 'build(version, "app")' in source


def test_windows_builder_never_emits_old_shell_exe_on_non_windows():
    source = (ROOT / "tools/build_windows_installer.py").read_text(encoding="utf-8")
    assert 'build_tauri(version, "nsis")' in source
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
