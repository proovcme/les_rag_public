"""Offline tests for the Windows installer tooling."""

from __future__ import annotations

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


def test_bootstrap_ps1_is_utf8_bom(tmp_path):
    # Windows PowerShell 5.1 / NSIS need a BOM to read Cyrillic correctly.
    ps1 = build_windows_installer.ROOT / "installers" / "windows" / "app" / "bootstrap.ps1"
    nsi = build_windows_installer.ROOT / "installers" / "windows" / "app" / "LES.nsi"
    assert ps1.read_bytes()[:3] == b"\xef\xbb\xbf"
    assert nsi.read_bytes()[:3] == b"\xef\xbb\xbf"


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


def test_start_light_keeps_uv_server_processes_alive():
    ps1 = build_windows_installer.ROOT / "installers" / "windows" / "start-light.ps1"
    text = ps1.read_text(encoding="utf-8")

    assert "function Start-LesUvProcess" in text
    assert "function Get-LesFreePort" in text
    assert '$ProxyPortExplicit = $PSBoundParameters.ContainsKey("ProxyPort")' in text
    assert '$env:PROXY_URL = "http://127.0.0.1:$ProxyPort"' in text
    assert '[int]$LemonadeHostPort = 18080' in text
    assert '"run", "python", "lemonade_host.py"' in text
    assert "windows-light-lemonade-host.err.log" in text
    assert "lemonade_adapter_url" in text
    assert "lemonade_host_pid" in text
    assert "$payload = [pscustomobject]@{" in text
    assert "windows-light-state.json" in text
    assert "ui_health_url" in text
    assert 'Start-Process -FilePath "cmd.exe"' in text
    assert "Wait-LesHttp" in text
    assert "Start-Process uv -ArgumentList" not in text


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

    assert '$PSBoundParameters.ContainsKey("ProxyPort")' in text
    assert 'logs\\windows-light-state.json' in text
    assert "$runtimeState.proxy_port" in text
    assert "$runtimeState.ui_port" in text


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


def test_windows_production_defaults_to_ollama_and_reads_persisted_choice():
    ps1 = build_windows_installer.ROOT / "installers" / "windows" / "start-light.ps1"
    text = ps1.read_text(encoding="utf-8")

    assert '[string]$Provider = ""' in text
    assert '$Provider = Get-LesDotEnvValue "LES_LLM_PROVIDER"' in text
    assert 'if (-not $Provider) { $Provider = "ollama" }' in text
    assert 'if (-not $Model -and $Provider -eq "ollama") { $Model = "qwen3.5:9b" }' in text


def test_windows_bootstrap_preloads_complete_local_rag_model_set():
    bootstrap = build_windows_installer.ROOT / "installers" / "windows" / "app" / "bootstrap.ps1"
    text = bootstrap.read_text(encoding="utf-8-sig")

    assert "--provider ollama --ensure-platform windows" in text
    assert '"qwen3.5:9b"' in text
    assert '"bge-m3:latest"' in text
    assert "--extra windows-reranker" in text
    assert "tools\\onboard_reranker.py" in text
    assert '"BAAI/bge-reranker-v2-m3"' in (
        build_windows_installer.ROOT / "installers" / "windows" / "start-light.ps1"
    ).read_text(encoding="utf-8")
    assert "$Ollama show" in text
    assert "$Ollama pull" in text


def test_windows_bootstrap_installs_and_requires_uv_ollama_docker():
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
    assert 'Install-WingetRequirement "Ollama.Ollama"' in text
    assert 'Install-WingetRequirement "Docker.DockerDesktop"' in text
    assert "https://ollama.com/download/windows" in text
    assert "https://www.docker.com/products/docker-desktop/" in text
    assert '"docker_engine_unavailable"' in text
    assert '"qdrant_health_failed"' in text
    assert "RAG features limited" not in text


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
