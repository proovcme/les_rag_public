"""Offline tests for the Windows installer tooling."""

from __future__ import annotations

import subprocess

from tools import build_release_artifacts
from tools import build_windows_installer


def test_stage_runtime_copies_clean_export_with_app_files(tmp_path):
    dest = tmp_path / "LES"
    count = build_windows_installer.stage_runtime(dest)
    assert count > 0

    # The Windows bootstrap shipped inside the runtime export.
    assert (dest / "installers" / "windows" / "app" / "bootstrap.ps1").is_file()
    assert (dest / "installers" / "windows" / "state.ps1").is_file()
    assert (dest / "installers" / "windows" / "app" / "launcher.vbs").is_file()
    assert (dest / "installers" / "windows" / "app" / "LES.nsi").is_file()
    assert (dest / "lemonade_host.py").is_file()
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


def test_release_inventory_uses_only_git_tracked_files(tmp_path, monkeypatch):
    tracked = tmp_path / "tracked.txt"
    untracked = tmp_path / "operator-notes.txt"
    tracked.write_text("public source", encoding="utf-8")
    untracked.write_text("local state", encoding="utf-8")

    monkeypatch.setattr(build_release_artifacts, "ROOT", tmp_path)
    monkeypatch.setattr(
        build_release_artifacts.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout=b"tracked.txt\0",
        ),
    )

    assert build_release_artifacts.iter_files() == [tracked]


def test_bootstrap_ps1_is_utf8_bom(tmp_path):
    # Windows PowerShell 5.1 / NSIS need a BOM to read Cyrillic correctly.
    ps1 = build_windows_installer.ROOT / "installers" / "windows" / "app" / "bootstrap.ps1"
    nsi = build_windows_installer.ROOT / "installers" / "windows" / "app" / "LES.nsi"
    assert ps1.read_bytes()[:3] == b"\xef\xbb\xbf"
    assert nsi.read_bytes()[:3] == b"\xef\xbb\xbf"


def test_windows_bootstrap_reports_the_installed_runtime_root():
    bootstrap = (
        build_windows_installer.ROOT
        / "installers"
        / "windows"
        / "app"
        / "bootstrap.ps1"
    ).read_text(encoding="utf-8-sig")

    assert "$env:LES_RUNTIME_HOME = $Root" in bootstrap
    assert "$env:LES_REPO_ROOT = $Root" in bootstrap


def test_windows_release_smoke_reports_cleanup_failures_before_success():
    smoke = (
        build_windows_installer.ROOT / "tools" / "windows_release_smoke.ps1"
    ).read_text(encoding="utf-8-sig")

    stop_call = smoke.index("& $StopScript")
    cleanup_error = smoke.index("$result.runtime_cleanup_error", stop_call)
    report_write = smoke.index("Set-Content -LiteralPath $ReportPath", cleanup_error)
    assert stop_call < cleanup_error < report_write


def test_windows_stop_helper_prefers_waitable_python():
    stop = (
        build_windows_installer.ROOT
        / "installers"
        / "windows"
        / "stop-light.ps1"
    ).read_text(encoding="utf-8-sig")

    assert 'foreach ($name in @("python.exe", "pythonw.exe"))' in stop


def test_windows_desktop_installer_stops_les_and_offers_data_wipe():
    """AnythingLLM-style Setup/Uninstall: stop app, optional full data wipe."""
    hooks = (
        build_windows_installer.ROOT
        / "desktop"
        / "tauri"
        / "src-tauri"
        / "windows-installer-hooks.nsh"
    ).read_text(encoding="utf-8")
    nsi = (
        build_windows_installer.ROOT / "installers" / "windows" / "app" / "LES.nsi"
    ).read_text(encoding="utf-8")
    helper = (
        build_windows_installer.ROOT
        / "installers"
        / "windows"
        / "app"
        / "les-setup-helpers.ps1"
    ).read_text(encoding="utf-8")
    desktop_doc = (
        build_windows_installer.ROOT / "docs" / "WINDOWS_DESKTOP.md"
    ).read_text(encoding="utf-8")
    tauri = (
        build_windows_installer.ROOT
        / "desktop"
        / "tauri"
        / "src-tauri"
        / "tauri.conf.json"
    ).read_text(encoding="utf-8")

    for text in (hooks, nsi):
        assert "exit /b 0" in text
        assert "ClearErrors" in text
        assert "les-setup-helpers.ps1" in text
        assert "LesWipeUserData" in text
        assert "setup-deps-missing.txt" in text
    assert "NSIS_HOOK_PREINSTALL" in hooks
    assert "NSIS_HOOK_PREUNINSTALL" in hooks
    assert "NSIS_HOOK_POSTUNINSTALL" in hooks
    assert r"$LOCALAPPDATA\Programs\LES" in hooks
    assert "exit 0" in helper
    assert "winget install" in helper
    assert "downloadBootstrapper" in tauri
    assert "ошибка 1" in desktop_doc
    assert "LES-Setup.exe" in desktop_doc
    assert "Параметры" in desktop_doc
    assert "Обновление поверх" in desktop_doc


def test_windows_release_smoke_executes_installed_runtime_and_real_rrf():
    smoke = build_windows_installer.ROOT / "tools" / "windows_release_smoke.ps1"
    raw = smoke.read_bytes()
    text = raw.decode("utf-8-sig")

    # Windows PowerShell 5 needs the BOM for the Russian smoke question.
    assert raw[:3] == b"\xef\xbb\xbf"
    assert 'Start-Process -FilePath "powershell.exe"' in text
    assert 'bootstrapStatus.state -in @("ready", "failed")' in text
    assert 'windows-light-state.json' in text
    assert '/api/version' in text
    assert '$env:RAG_COLLECTION_NAME = $smokeCollection' in text
    assert 'isolated Qdrant collection was not created' in text
    assert '[string]$ExpectedVersion' in text
    assert '$version.les_version -eq $ExpectedVersion' in text
    assert '/healthz' in text
    assert '/api/rag/datasets?name=' in text
    assert '/api/rag/upload/$smokeDatasetId' in text
    assert 'status -eq "INDEXED"' in text
    assert 'dataset_ids = @($smokeDatasetId)' in text
    assert '/api/rag/retrieve-debug' in text
    assert '[System.Text.Encoding]::UTF8.GetBytes($body)' in text
    assert '$channels -contains "dense"' in text
    assert '$channels -contains "qdrant_sparse"' in text
    assert '[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)' in text
    assert 'retrieval_trace.fusion -match "rrf"' in text
    assert 'Invoke-RestMethod -Method Delete' in text
    assert 'collections/$smokeCollection' in text
    assert 'verify-root --root $StateRoot' in text
    assert '[int]$smetaBaseline.norm_count -lt 40000' in text
    assert '[int]$smetaBaseline.fsem_rows -lt 1500' in text
    assert 'status = "requires_region_zone_period_selection"' in text
    assert 'process_contract -ne "direct_python_no_console_v1"' in text
    assert 'runtimeProcess.Name -notin @("python.exe", "pythonw.exe")' in text
    assert "cmd.exe wrapper process(es)" in text
    assert "bootstrap PowerShell stayed alive after terminal ready" in text


def test_start_light_uses_direct_console_free_python_processes():
    ps1 = build_windows_installer.ROOT / "installers" / "windows" / "start-light.ps1"
    text = ps1.read_text(encoding="utf-8")

    assert "function Resolve-LesPython" in text
    assert "function Start-LesPythonProcess" in text
    assert "function Normalize-LesProcessPathEnvironment" in text
    assert "Normalize-LesProcessPathEnvironment" in text
    assert '[Environment]::SetEnvironmentVariable(' in text
    assert '"PATH"' in text
    assert '@("pythonw.exe", "python.exe")' in text
    assert "Start-Process -FilePath $LesPython" in text
    assert '"-m", "uvicorn", "proxy_server:app"' in text
    assert 'process_contract = "direct_python_no_console_v1"' in text
    assert "function Get-LesFreePort" in text
    assert '$ProxyPortExplicit = $PSBoundParameters.ContainsKey("ProxyPort")' in text
    assert '$env:PROXY_URL = "http://127.0.0.1:$ProxyPort"' in text
    assert '[int]$LemonadeHostPort = 18080' in text
    assert '@("lemonade_host.py")' in text
    assert "windows-light-lemonade-host.err.log" in text
    assert "lemonade_adapter_url" in text
    assert "lemonade_host_pid" in text
    assert "$payload = [pscustomobject]@{" in text
    assert "windows-light-state.json" in text
    assert "ui_health_url" in text
    assert "Wait-LesHttp" in text
    assert 'Start-Process -FilePath "cmd.exe"' not in text
    assert "function Start-LesUvProcess" not in text


def test_windows_bootstrap_reports_ready_only_after_api_health():
    bootstrap = (
        build_windows_installer.ROOT / "installers" / "windows" / "app" / "bootstrap.ps1"
    ).read_text(encoding="utf-8-sig")

    assert "function Wait-LesApiReady" in bootstrap
    assert 'Wait-LesApiReady "http://127.0.0.1:$proxyPort/api/health" 180' in bootstrap
    assert 'if ($health) { return $health }' in bootstrap
    assert '$health.status -eq "ok"' not in bootstrap
    assert '"services_api_not_ready"' in bootstrap


def test_windows_bootstrap_captures_uv_progress_without_treating_stderr_as_failure():
    bootstrap = (
        build_windows_installer.ROOT / "installers" / "windows" / "app" / "bootstrap.ps1"
    ).read_text(encoding="utf-8-sig")

    assert '$previousErrorActionPreference = $ErrorActionPreference' in bootstrap
    assert '$ErrorActionPreference = "Continue"' in bootstrap
    assert '$uvSyncOutput = @(& $Uv @UvSyncArgs 2>&1)' in bootstrap
    assert '$uvSyncExitCode = $LASTEXITCODE' in bootstrap
    assert '$ErrorActionPreference = $previousErrorActionPreference' in bootstrap


def test_qdrant_payload_indexes_do_not_block_api_startup():
    adapter = (
        build_windows_installer.ROOT / "backend" / "qdrant_adapter.py"
    ).read_text(encoding="utf-8")

    payload_index_call = adapter.split("await self.aclient.create_payload_index(", 1)[1].split(")", 1)[0]
    assert "wait=False" in payload_index_call


def test_windows_tauri_uses_update_safe_persistent_state():
    root = build_windows_installer.ROOT
    state = (root / "installers" / "windows" / "state.ps1").read_text(encoding="utf-8")
    bootstrap = (root / "installers" / "windows" / "app" / "bootstrap.ps1").read_text(encoding="utf-8-sig")
    start = (root / "installers" / "windows" / "start-light.ps1").read_text(encoding="utf-8")

    for name in ("data", "storage", "RAG_Content", "logs", "artifacts"):
        assert f'"{name}"' in state
    assert 'Join-Path $env:LOCALAPPDATA "LES"' in state
    assert "Move-Item -LiteralPath $source -Destination $backup" in state
    assert "New-LesDirectoryJunction" in state
    assert "New-Item -ItemType Junction" in state
    assert "cmd.exe /d /c mklink" not in state
    assert 'schema = "les_windows_state_v1"' in state
    assert "$env:LES_ENV_PATH = $State.env_path" in bootstrap
    assert "$env:UV_PROJECT_ENVIRONMENT" in bootstrap
    assert 'Get-Content $env:LES_ENV_PATH' in bootstrap
    assert 'state_root = if ($StateRoot)' in start
    assert '@(".codex_tmp", "tmp")' in state
    assert "Refusing to remove temporary reparse point" in state
    assert "function Grant-LesWindowsStateAccess" in state
    assert "WindowsIdentity]::GetCurrent().User" in state
    assert "FileSystemRights]::Modify" in state
    assert "AccessControlSections]::Access" in state
    assert "$item.GetAccessControl(" in state
    assert "$item.SetAccessControl($acl)" in state
    assert "Set-Acl -LiteralPath" not in state
    assert '".les-write-probe-{0}-{1}.tmp"' in state
    assert "[System.IO.File]::WriteAllText($probe" in state
    assert "WindowsBuiltInRole]::Administrator" in state
    assert "LES state is not writable by the interactive user" in state
    assert 'Grant-LesWindowsStateAccess -Path $state' in state
    assert 'Grant-LesWindowsStateAccess -Path (Join-Path $StateRoot "data\\smeta_base") -Recurse' in bootstrap


def test_windows_qdrant_new_install_uses_named_volume():
    root = build_windows_installer.ROOT
    bootstrap = (root / "installers" / "windows" / "app" / "bootstrap.ps1").read_text(encoding="utf-8-sig")
    start = (root / "installers" / "windows" / "start-light.ps1").read_text(encoding="utf-8")

    assert "& $Docker volume create les-qdrant-data" in bootstrap
    assert 'les-qdrant-data:/qdrant/storage' in bootstrap
    assert "docker volume create les-qdrant-data" in start
    assert 'les-qdrant-data:/qdrant/storage' in start


def test_windows_stop_uses_persisted_dynamic_ports():
    text = (
        build_windows_installer.ROOT / "installers" / "windows" / "stop-light.ps1"
    ).read_text(encoding="utf-8")
    runtime = (
        build_windows_installer.ROOT / "installers" / "windows" / "runtime-process.ps1"
    ).read_text(encoding="utf-8")

    assert '$PSBoundParameters.ContainsKey("ProxyPort")' in text
    assert 'logs\\windows-light-state.json' in text
    assert "$runtimeState.proxy_port" in text
    assert "$runtimeState.ui_port" in text
    assert "windows_runtime.py" in text
    assert "foreign_port_owner" in text
    assert "function Stop-LesConfirmedPortProcess" in runtime
    assert "Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue" not in runtime
    # System python + repo\.venv\uvicorn / NiceGUI re-exec must still count as LES-owned.
    assert "commandUnderRuntime" in runtime
    assert "IndexOf($runtime" in runtime
    assert "ParentProcessId" in runtime


def test_start_light_keeps_provider_model_and_ollama_embedding_contract_aligned():
    ps1 = build_windows_installer.ROOT / "installers" / "windows" / "start-light.ps1"
    text = ps1.read_text(encoding="utf-8")

    # The selected model must be both the provider-specific model and the
    # provider-neutral status/fallback model.  Otherwise Windows executes one
    # model while /api/status reports a stale Mac MLX model.
    assert '$env:LLM_MODEL = $Model' in text
    assert 'if ($Model) { $env:OLLAMA_MODEL = $Model }' in text

    # A direct start-light launch (including Tauri) must have the same embedding
    # contract as `lesctl init --profile windows-lite`: Ollama bge-m3, 1024 dims.
    assert '$env:MLX_URL = $env:OLLAMA_BASE_URL' in text
    assert '$env:EMBED_URL_PARSE = $env:OLLAMA_BASE_URL' in text
    assert '"bge-m3:latest"' in text
    assert '$env:EMBED_BACKEND = "ollama"' in text
    assert '$env:RAG_VECTOR_SIZE = "1024"' in text
    assert '$env:RERANKER_ENABLED = "true"' in text
    assert '$env:RERANKER_BACKEND = "sentence_transformers"' in text
    assert '$env:RERANK_MODEL' in text
    assert "config\\local\\secrets.env" in text


def test_windows_production_defaults_to_ollama_and_reads_persisted_choice():
    ps1 = build_windows_installer.ROOT / "installers" / "windows" / "start-light.ps1"
    text = ps1.read_text(encoding="utf-8")

    assert '[string]$Provider = ""' in text
    assert '$Provider = Get-LesDotEnvValue "LES_LLM_PROVIDER"' in text
    assert 'if (-not $Provider) { $Provider = "ollama" }' in text
    assert 'if (-not $Model -and $Provider -eq "ollama") { $Model = "qwen3.5:9b" }' in text


def test_windows_bootstrap_requires_user_selected_models_without_pulling_them():
    bootstrap = build_windows_installer.ROOT / "installers" / "windows" / "app" / "bootstrap.ps1"
    text = bootstrap.read_text(encoding="utf-8-sig")

    assert "--provider ollama --ensure-platform windows" in text
    assert "Рекомендуем qwen3.5:9b" in text
    assert '$Ollama show "bge-m3:latest"' in text
    assert "--extra windows-reranker" in text
    assert "tools\\onboard_reranker.py" in text
    assert '"BAAI/bge-reranker-v2-m3"' in (
        build_windows_installer.ROOT / "installers" / "windows" / "start-light.ps1"
    ).read_text(encoding="utf-8")
    assert "$Ollama show $configuredModel" in text
    assert "$Ollama pull" not in text
    assert 'Require-Setup "Модель $configuredModel не установлена.' in text


def test_windows_bootstrap_bundles_core_and_defers_external_components_to_wizard():
    bootstrap = build_windows_installer.ROOT / "installers" / "windows" / "app" / "bootstrap.ps1"
    text = bootstrap.read_text(encoding="utf-8-sig")

    assert "astral-sh.uv" in text
    assert "function Install-Uv" in text
    assert "function Resolve-BundledPython" in text
    assert "Expand-Archive -LiteralPath $archive -DestinationPath $temporaryRoot -Force" in text
    assert "bundled Python archive SHA-256 mismatch" in text
    assert "installer_name" not in text
    assert "Start-Process -FilePath $installer" not in text
    assert "bundled_python_unavailable" in text
    assert "--no-python-downloads" in text
    assert "python-contract.json" in text
    assert "trying official installer" in text
    assert "uv_install_failed_after_fallback" in text
    assert "tools\\uv.exe" in text
    assert "Get-FileHash -LiteralPath $bundled -Algorithm SHA256" in text
    assert "https://docs.astral.sh/uv/getting-started/installation/" in text
    assert "function Require-Setup" in text
    assert '"ollama_missing"' in text
    assert '"docker_missing"' in text
    assert "https://ollama.com/download/windows" in text
    assert "https://www.docker.com/products/docker-desktop/" in text
    assert '"docker_engine_unavailable"' in text
    assert '"qdrant_health_failed"' in text
    assert 'Write-Status -Phase "setup" -State "setup_required"' in text


def test_windows_bootstrap_repairs_and_reports_uv_sync():
    bootstrap = build_windows_installer.ROOT / "installers" / "windows" / "app" / "bootstrap.ps1"
    text = bootstrap.read_text(encoding="utf-8-sig")

    assert '$env:UV_SYSTEM_CERTS' in text
    assert '$env:UV_HTTP_RETRIES' in text
    assert '$VenvWasUsable' in text
    assert 'removing incomplete or broken Python environment' in text
    assert '@("sync", "--locked", "--python", $BundledPython, "--no-python-downloads")' in text
    assert '$uvSyncOutput = @(& $Uv @UvSyncArgs 2>&1)' in text
    assert 'Log "uv: $safeLine"' in text
    assert '"uv_sync_failed"' in text
    assert 'concepts/authentication/certificates' in text


def test_windows_bootstrap_writes_machine_readable_status_for_tauri():
    bootstrap = build_windows_installer.ROOT / "installers" / "windows" / "app" / "bootstrap.ps1"
    text = bootstrap.read_text(encoding="utf-8-sig")

    assert 'bootstrap-status.json' in text
    assert text.index('New-Item -ItemType Directory -Force -Path $LogDir') < text.index('. $StateScript')
    assert text.index('Log "===== bootstrap start') < text.index('. $StateScript')
    assert 'windows_state_helper_missing' in text
    assert 'windows_state_helper_failed' in text
    assert '$serviceOutput = @(& (Join-Path $Root "installers\\windows\\start-light.ps1"))' in text
    assert '& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "installers\\windows\\start-light.ps1") | Out-File' not in text
    assert 'services_start_failed' in text
    assert 'schema = "les_windows_bootstrap_status_v1"' in text
    assert 'install_url = $InstallUrl' in text
    assert 'New-Object System.Text.UTF8Encoding($false)' in text
    assert 'Write-Status -Phase "ready" -State "ready"' in text
    assert 'if ($env:LES_TAURI_SHELL -ne "1")' in text
    assert 'LES-smeta-baseline.zip' in text
    assert 'tools\\smeta_release_baseline.py repair' in text
    stop_stale = '$stopStaleOutput = @(& $stopScript)'
    stop = '$stopOutput = @(& $stopScript -ProxyPort 8050 -UiPort 8051)'
    start = '$serviceOutput = @(& (Join-Path $Root "installers\\windows\\start-light.ps1"))'
    assert stop_stale in text
    assert stop in text
    assert text.index(stop_stale) < text.index(stop)
    assert text.index(stop) < text.index(start)
    assert 'Warn "сметная база недоступна:' in text
    assert '"bootstrap_degraded"' in text
    assert 'Fail "в установочном пакете отсутствует проверенная сметная база"' not in text
    assert 'Fail "не удалось подготовить сметную базу:' not in text


def test_desktop_les_start_bootstraps_native_qdrant_and_fixed_ports():
    root = build_windows_installer.ROOT
    start = (root / "scripts" / "windows" / "LES-START.ps1").read_text(encoding="utf-8")
    stop = (root / "scripts" / "windows" / "LES-STOP.ps1").read_text(encoding="utf-8")
    bat = (root / "scripts" / "windows" / "LES-START.bat").read_text(encoding="utf-8")
    qdrant_cfg = (root / "config" / "qdrant.local.yaml").read_text(encoding="utf-8")
    cuda_env = (root / "config" / "local" / "windows-cuda.env").read_text(encoding="utf-8")

    assert "tools\\bin\\qdrant.exe" in start
    assert "config\\qdrant.local.yaml" in start
    assert "config\\local\\windows-cuda.env" in start
    assert "config\\local\\secrets.env" in start
    gitignore = (root / ".gitignore").read_text(encoding="utf-8")
    assert "config/local/secrets.env" in gitignore
    assert "LES_ETM_PASSWORD=" not in cuda_env
    assert '"-ProxyPort", "8050"' in start
    assert '"-UiPort", "8051"' in start
    assert "/api/version" in start
    assert "stop-light.ps1" in start
    assert "Do NOT capture start-light stdout/stderr" in start
    assert "2>&1" not in start
    assert "RERANK_DEVICE" in start
    assert "cuda_available" in start
    assert '-WindowStyle Hidden' in start or "-WindowStyle Hidden" in start
    assert "stop-light.ps1" in stop
    assert 'Get-Process -Name "qdrant"' in stop
    assert "Stop-Port 8050" not in stop  # ownership-aware; no blind port kill
    assert "LES-START.ps1" in bat
    assert "storage_path: ./data/qdrant" in qdrant_cfg
    assert "http_port: 6333" in qdrant_cfg
    assert "RERANK_DEVICE=cuda" in cuda_env
    assert "LES_SMETA_DOCUMENT_TEMPERATURE=0.0" in cuda_env
    assert "LES_SMETA_DOCUMENT_TOP_P=1.0" in cuda_env
