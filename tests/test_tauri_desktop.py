from __future__ import annotations

import ast
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
    main = (TAURI / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")

    assert '#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]' in main
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
    assert "const CREATE_NO_WINDOW: u32 = 0x0800_0000" in source
    assert "fn windows_command(" in source
    assert "creation_flags(CREATE_NO_WINDOW)" in source
    assert "WindowsSingleInstanceGuard" in source
    assert r'Local\LES.Tauri.SingleInstance' in source
    assert "LIFECYCLE_IN_FLIGHT" in source
    assert "compare_exchange(false, true" in source
    assert "schedule_boot_and_navigate" in source
    assert 'Command::new("cmd.exe")' not in source
    assert 'Command::new("where.exe")' not in source
    assert source.count('.arg("list")') == 1
    assert '"restart" => run_action' in source
    assert '"stop" => run_action' in source
    assert '"setup" => show_setup' in source
    assert "setup_snapshot" in source
    assert "install_setup_component" not in source
    assert "start_from_setup" in source
    assert "retry_setup" in source
    assert "search_norm" not in source
    assert "submit_lsr_mapping" not in source

    wizard = (TAURI / "web" / "index.html").read_text(encoding="utf-8")
    script = (TAURI / "web" / "wizard.js").read_text(encoding="utf-8")
    assert "Настройка Л.Е.С." in wizard
    assert "Совместимые компоненты" in wizard
    assert "Движок ответа" in wizard
    assert "Ollama" in wizard
    assert "FreeToken" in wizard
    assert "Lemonade" in wizard
    assert "OpenAI-compatible" in wizard
    assert "Поиск по документам" in wizard
    assert "Локальный индекс" in wizard
    assert "qwen3.5:9b" not in wizard
    assert "Установить Ollama" not in wizard
    assert 'invoke("install_setup_component"' not in script
    assert 'invoke("start_from_setup")' in script
    assert "model-select" not in script
    assert "&& !preparing" in script
    assert 'preparing ? "Подготовка…"' in script
    assert "window.setInterval(refresh, 10000)" in script
    assert '"configured_provider"' in source
    assert '"freetoken"' in source
    assert '"lemonade"' in source
    assert '"openai-compatible"' in source
    assert '"recommended_model"' not in source
    assert "save_setup_model" not in source


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
    assert '$SelectedExtra = if ($env:LES_TAURI_SHELL -eq "1") { "windows-reranker" } else { "desktop" }' in windows
    assert '"--no-python-downloads", "--extra", $SelectedExtra' in windows
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


def test_windows_runtime_manifest_keeps_product_and_excludes_repository_only_files():
    included = [
        ROOT / "README.md",
        ROOT / "pyproject.toml",
        ROOT / "uv.lock",
        ROOT / "env.example",
        ROOT / "backend" / "qdrant_adapter.py",
        ROOT / "proxy" / "app.py",
        ROOT / "sovushka" / "pages" / "chat.py",
        ROOT / "sovushka_ng.py",
        ROOT / "qdrant_visualizer" / "index.html",
        ROOT / "config" / "version.json",
        ROOT / "schema" / "smeta_agent_trace.schema.json",
        ROOT / "skills" / "smeta" / "SKILL.md",
        ROOT / "installers" / "windows" / "app" / "bootstrap.ps1",
        ROOT / "tools" / "windows_runtime.py",
        ROOT / "tools" / "windows_update_engine.py",
        ROOT / "tools" / "windows_env_doctor.py",
        ROOT / "tools" / "vps_patch_apply.py",
        ROOT / "tools" / "smeta_release_baseline.py",
        ROOT / "tools" / "live_workbook_acceptance.py",
        ROOT / "tools" / "fgis_update_supervisor.py",
    ]
    excluded = [
        ROOT / "tests" / "test_chat_evidence_application_service.py",
        ROOT / "docs" / "CODE_MAP.md",
        ROOT / "legacy" / "backend" / "old.py",
        ROOT / "dev" / "README.md",
        ROOT / "golden" / "domain_fire_hvac_set.json",
        ROOT / "schema" / "artel_family_learning_case.schema.json",
        ROOT / "tools" / "build_tauri_app.py",
        ROOT / "tools" / "vps_patch.py",
        ROOT / "desktop" / "tauri" / "package.json",
        ROOT / "installers" / "macos" / "app" / "bootstrap.sh",
        ROOT / "clients" / "outlook_addin" / "manifest.xml",
        ROOT / "exporters" / "revit" / "LesExporter.cs",
        ROOT / "frontend" / "cad_bim_viewer" / "package.json",
        ROOT / "standalone" / "cad_bim_viewer" / "index.html",
    ]

    for path in included:
        assert build_tauri_app.windows_runtime_manifest_allows(path), path
    for path in excluded:
        assert not build_tauri_app.windows_runtime_manifest_allows(path), path


def test_windows_tauri_stage_applies_runtime_manifest(tmp_path, monkeypatch):
    resources = tmp_path / "resources"
    app_file = ROOT / "proxy" / "app.py"
    test_file = ROOT / "tests" / "test_tauri_desktop.py"
    monkeypatch.setattr(build_tauri_app, "RESOURCES", resources)
    monkeypatch.setattr(build_tauri_app, "iter_files", lambda: [app_file, test_file])
    monkeypatch.setattr(build_tauri_app, "stage_windows_uv", lambda _runtime, **_kwargs: 0)
    monkeypatch.setattr(build_tauri_app, "stage_windows_python", lambda _runtime, **_kwargs: 0)
    monkeypatch.setattr(build_tauri_app, "stage_windows_uv_cache", lambda _runtime, **_kwargs: 0)
    monkeypatch.setattr(build_tauri_app, "stage_windows_deploy_stamp", lambda _runtime: 0)

    assert build_tauri_app.stage_runtime("win32") == 1
    assert (resources / "runtime/proxy/app.py").is_file()
    assert not (resources / "runtime/tests/test_tauri_desktop.py").exists()


def test_windows_runtime_manifest_covers_python_tool_dependencies():
    runtime_files = [
        path
        for path in build_release_artifacts.iter_files()
        if build_tauri_app.windows_runtime_manifest_allows(path)
    ]
    assert len(runtime_files) < 600

    missing: set[str] = set()
    for source in runtime_files:
        if source.suffix != ".py":
            continue
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module == "tools":
                    modules.update(f"tools.{name.name}" for name in node.names)
                elif node.module.startswith("tools."):
                    modules.add(node.module)
            elif isinstance(node, ast.Import):
                modules.update(name.name for name in node.names if name.name.startswith("tools."))
        for module in modules:
            candidate = ROOT.joinpath(*module.split(".")).with_suffix(".py")
            if candidate.is_file() and not build_tauri_app.windows_runtime_manifest_allows(candidate):
                missing.add(candidate.relative_to(ROOT).as_posix())

    assert not missing, f"runtime tools missing from manifest: {sorted(missing)}"


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
    monkeypatch.setattr(build_tauri_app, "stage_windows_uv_cache", lambda _runtime, **_kwargs: 0)

    monkeypatch.setattr(build_tauri_app, "stage_windows_deploy_stamp", lambda _runtime: 1)

    assert build_tauri_app.stage_runtime("win32") == 2
    assert not (resources / "bootstrap.sh").exists()
    assert not (resources / "runtime/installers/macos/app/bootstrap.sh").exists()
    assert (resources / "runtime/installers/windows/app/bootstrap.ps1").is_file()

    assert build_tauri_app.stage_runtime("darwin") == 1
    assert (resources / "bootstrap.sh").is_file()
    assert (resources / "runtime/installers/macos/app/bootstrap.sh").is_file()
    assert not (resources / "runtime/installers/windows/app/bootstrap.ps1").exists()


def test_windows_runtime_stage_contains_exact_deploy_identity(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()

    assert build_tauri_app.stage_windows_deploy_stamp(runtime) == 1
    stamp = json.loads((runtime / ".les_deploy_stamp.json").read_text(encoding="utf-8"))

    assert len(stamp["deployed_commit"]) == 40
    assert stamp["product_version"]
    assert stamp["build_number"] > 0


def test_windows_start_and_release_smoke_are_offline_and_isolated():
    start = (ROOT / "installers/windows/start-light.ps1").read_text(encoding="utf-8-sig")
    hooks = (TAURI / "src-tauri/windows-installer-hooks.nsh").read_text(encoding="utf-8")
    prepare = (ROOT / "tools/windows_prepare_update.ps1").read_text(encoding="utf-8-sig")

    assert '$env:RAG_TOKENIZER_LOCAL_FILES_ONLY = "true"' in start
    assert '$env:HF_HUB_OFFLINE = "1"' in start
    assert 'ReadEnvStr $R7 "LES_RELEASE_SMOKE"' in hooks
    assert 'ReadEnvStr $R7 "LES_WINDOWS_STATE_ROOT"' in hooks
    assert "LES release smoke: рабочий desktop не останавливается" in hooks
    assert '$env:LES_RELEASE_SMOKE = "1"' not in prepare
    bootstrap = (ROOT / "installers/windows/app/bootstrap.ps1").read_text(encoding="utf-8-sig")
    assert 'release smoke: keep production ports and select dynamic ports' in bootstrap
    ui_source = (ROOT / "sovushka_ng.py").read_text(encoding="utf-8")
    ui_config = (ROOT / "sovushka/config.py").read_text(encoding="utf-8")
    assert "host=UI_HOST" in ui_source
    assert 'ThreadingHTTPServer((UI_HOST, QDRANT_VISUALIZER_PORT)' in ui_source
    assert 'SOVUSHKA_UI_HOST", "127.0.0.1"' in ui_config


def test_windows_tauri_stage_bundles_verified_smeta_baseline(tmp_path, monkeypatch):
    resources = tmp_path / "resources"
    archive = tmp_path / "LES-smeta-baseline.zip"
    archive.write_bytes(b"verified-baseline")
    monkeypatch.setattr(build_tauri_app, "RESOURCES", resources)
    monkeypatch.setattr(build_tauri_app, "iter_files", lambda: [ROOT / "pyproject.toml"])
    monkeypatch.setattr(smeta_release_baseline, "verify_archive", lambda path: {"ok": True})
    monkeypatch.setattr(build_tauri_app, "stage_windows_uv", lambda _runtime, **_kwargs: 0)
    monkeypatch.setattr(build_tauri_app, "stage_windows_python", lambda _runtime, **_kwargs: 0)
    monkeypatch.setattr(build_tauri_app, "stage_windows_uv_cache", lambda _runtime, **_kwargs: 0)

    assert build_tauri_app.stage_runtime("win32", smeta_baseline_archive=archive) == 3
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
    monkeypatch.setattr(build_tauri_app, "iter_files", lambda: [ROOT / "pyproject.toml"])
    monkeypatch.setattr(build_tauri_app, "stage_windows_python", lambda _runtime, **_kwargs: 0)
    monkeypatch.setattr(build_tauri_app, "stage_windows_uv_cache", lambda _runtime, **_kwargs: 0)

    assert build_tauri_app.stage_runtime("win32", windows_uv_archive=archive) == 3
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


def test_windows_tauri_stage_bundles_offline_uv_cache_with_lock_identity(tmp_path):
    archive = tmp_path / "windows-uv-cache.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("archive-v0/test-wheel.whl", b"wheel-bytes")
    lock = tmp_path / "uv.lock"
    lock.write_text("version = 1\n", encoding="utf-8")

    assert build_tauri_app.stage_windows_uv_cache(
        tmp_path / "runtime", archive_path=archive, lock_path=lock,
    ) == 1

    tools = tmp_path / "runtime/installers/windows/tools"
    contract = json.loads((tools / "uv-cache-contract.json").read_text(encoding="utf-8"))
    fingerprint = build_tauri_app.windows_dependency_fingerprint(lock, tools)
    assert contract == {
        "schema": "les.windows-uv-cache.v1",
        "fingerprint_schema": "les.windows-dependency-fingerprint.v2",
        "dependency_fingerprint": fingerprint,
        "archive_name": "windows-uv-cache.zip",
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
        "extra": "windows-reranker",
    }
    assert (tools / "windows-uv-cache.zip").read_bytes() == archive.read_bytes()


def test_windows_dependency_fingerprint_ignores_only_editable_project_version(tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "python-contract.json").write_text('{"version":"3.13.7"}', encoding="utf-8")
    (tools / "uv-contract.json").write_text('{"version":"0.8.14"}', encoding="utf-8")
    lock = tmp_path / "uv.lock"

    def write_lock(project_version: str, dependency_version: str) -> None:
        lock.write_text(
            'version = 1\n'
            '[[package]]\nname = "les-v2"\nversion = "' + project_version + '"\n'
            'source = { editable = "." }\ndependencies = [{ name = "fastapi" }]\n'
            '[[package]]\nname = "fastapi"\nversion = "' + dependency_version + '"\n'
            'source = { registry = "https://pypi.org/simple" }\n',
            encoding="utf-8",
        )

    write_lock("0.29.1", "0.116.0")
    first = build_tauri_app.windows_dependency_fingerprint(lock, tools)
    write_lock("0.29.2", "0.116.0")
    assert build_tauri_app.windows_dependency_fingerprint(lock, tools) == first
    write_lock("0.29.2", "0.117.0")
    assert build_tauri_app.windows_dependency_fingerprint(lock, tools) != first


def test_windows_uv_cache_build_primes_build_backend_then_verifies_offline_sync(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    tools = runtime / "installers/windows/tools"
    tools.mkdir(parents=True)
    (tools / "uv.exe").write_bytes(b"uv")
    (tools / "python-contract.json").write_text(
        json.dumps({"archive_name": "python.zip", "python_relative_path": "python.exe"}),
        encoding="utf-8",
    )
    with zipfile.ZipFile(tools / "python.zip", "w") as zf:
        zf.writestr("python.exe", b"python")
    seen = []

    def fake_run(command, **kwargs):
        seen.append(command)
        cache = Path(kwargs["env"]["UV_CACHE_DIR"])
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "wheel.whl").write_bytes(b"wheel")

    monkeypatch.setattr(build_tauri_app.subprocess, "run", fake_run)
    build_tauri_app._build_windows_uv_cache(runtime, tmp_path / "cache.zip")

    assert "--no-install-project" not in seen[0]
    assert "--offline" not in seen[0]
    assert "--offline" in seen[1]
    assert "--no-install-project" not in seen[1]


def test_windows_uv_cache_build_is_reused_for_same_lock(tmp_path, monkeypatch):
    lock = tmp_path / "uv.lock"
    lock.write_text("version = 1\n", encoding="utf-8")
    cache_dir = tmp_path / "release-cache"
    builds = []

    def fake_build(_runtime, archive):
        builds.append(archive)
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("archive-v0/test-wheel.whl", b"wheel-bytes")

    monkeypatch.setattr(build_tauri_app, "_build_windows_uv_cache", fake_build)
    for name in ("first", "second"):
        assert build_tauri_app.stage_windows_uv_cache(
            tmp_path / name,
            lock_path=lock,
            cache_dir=cache_dir,
        ) == 1

    assert len(builds) == 1
    assert len(list(cache_dir.glob("windows-uv-cache-*.zip"))) == 1


def test_windows_uv_cache_migrates_legacy_key_without_rebuild(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    tools = runtime / "installers/windows/tools"
    tools.mkdir(parents=True)
    lock = runtime / "uv.lock"
    lock.write_text("version = 1\n", encoding="utf-8")
    cache_dir = tmp_path / "release-cache"
    cache_dir.mkdir()
    legacy = cache_dir / (
        "windows-uv-cache-"
        + build_tauri_app._legacy_windows_uv_cache_fingerprint(lock, tools)
        + ".zip"
    )
    with zipfile.ZipFile(legacy, "w") as zf:
        zf.writestr("archive-v0/test-wheel.whl", b"wheel-bytes")
    monkeypatch.setattr(
        build_tauri_app,
        "_build_windows_uv_cache",
        lambda *_args: pytest.fail("compatible legacy cache must be migrated, not rebuilt"),
    )

    build_tauri_app.stage_windows_uv_cache(runtime, cache_dir=cache_dir)

    assert not legacy.exists()
    assert len(list(cache_dir.glob("windows-uv-cache-*.zip"))) == 1


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
