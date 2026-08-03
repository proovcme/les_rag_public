# LES Windows first-run / launch bootstrap.
#
# Invoked (hidden) by app\launcher.vbs from the Start Menu / Desktop shortcut.
# No terminal: progress is surfaced via tray balloons, failures via a dialog;
# full detail goes to %LOCALAPPDATA%\LES\logs\bootstrap.log.
#
# Windows has no Apple MLX → the engine is cloud / ollama / lemonade (configured
# in the Sovushka GUI). On first launch this installs bundled Python/uv, runs
# `uv sync`, initializes .env/dirs, optionally starts Qdrant, then brings up the
# proxy + UI via start-light.ps1 and opens the browser.
$ErrorActionPreference = "Stop"

$BootstrapPath = $MyInvocation.MyCommand.Definition
if ($BootstrapPath.StartsWith("\\?\")) {
  $BootstrapPath = $BootstrapPath.Substring(4)
}
$AppDir   = Split-Path -Parent $BootstrapPath                              # ...\installers\windows\app
$Root     = (Resolve-Path (Join-Path $AppDir "..\..\..")).Path             # install root (runtime export)
$UiUrl    = "http://127.0.0.1:8051/les"
$StateRoot = if ($env:LES_WINDOWS_STATE_ROOT) {
  [System.IO.Path]::GetFullPath($env:LES_WINDOWS_STATE_ROOT)
} elseif ($env:LOCALAPPDATA) {
  [System.IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "LES"))
} else {
  [System.IO.Path]::GetFullPath((Join-Path $env:TEMP "LES"))
}
$LogDir   = Join-Path $StateRoot "logs"
$Log      = Join-Path $LogDir "bootstrap.log"
$Status   = Join-Path $LogDir "bootstrap-status.json"
$script:BootstrapWarnings = @()
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$StateScript = Join-Path $Root "installers\windows\state.ps1"

function Log([string]$m) { "$([DateTime]::Now.ToString('yyyy-MM-dd HH:mm:ss'))  $m" | Out-File -FilePath $Log -Append -Encoding utf8 }

function Warn([string]$m) {
  $script:BootstrapWarnings += $m
  Log "WARN: $m"
}

function Write-Status(
  [string]$Phase,
  [string]$State,
  [string]$Message,
  [string]$Code = "",
  [string]$InstallUrl = ""
) {
  $payload = [ordered]@{
    schema = "les_windows_bootstrap_status_v1"
    phase = $Phase
    state = $State
    message = $Message
    code = $Code
    install_url = $InstallUrl
    log_path = $Log
    updated_at = [DateTime]::Now.ToString("o")
  }
  $tmp = "$Status.tmp"
  [System.IO.File]::WriteAllText(
    $tmp,
    ($payload | ConvertTo-Json -Depth 3),
    (New-Object System.Text.UTF8Encoding($false))
  )
  Move-Item -LiteralPath $tmp -Destination $Status -Force
}

function Toast([string]$m) {
  try {
    Add-Type -AssemblyName System.Windows.Forms
    $n = New-Object System.Windows.Forms.NotifyIcon
    $n.Icon = [System.Drawing.SystemIcons]::Information
    $n.Visible = $true
    $n.ShowBalloonTip(4000, "ЛЕС · Совушка", $m, [System.Windows.Forms.ToolTipIcon]::Info)
  } catch { }
}

function Wait-LesApiReady([string]$Url, [int]$TimeoutSeconds = 180) {
  $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
  do {
    try {
      $health = Invoke-RestMethod -Uri $Url -TimeoutSec 5
      # Clean state intentionally reports `degraded` until its first document
      # is indexed.  HTTP 2xx itself proves that FastAPI finished startup; the
      # release smoke validates the deeper RAG contract immediately after.
      if ($health) { return $health }
    } catch { }
    Start-Sleep -Seconds 1
  } while ([DateTime]::UtcNow -lt $deadline)
  return $null
}

function Fail([string]$m, [string]$Code = "bootstrap_failed", [string]$InstallUrl = "") {
  Log "FAIL: $m"
  Write-Status -Phase "failed" -State "failed" -Message $m -Code $Code -InstallUrl $InstallUrl
  if ($env:LES_TAURI_SHELL -ne "1") {
    try {
      Add-Type -AssemblyName System.Windows.Forms
      [System.Windows.Forms.MessageBox]::Show("ЛЕС не смог запуститься: $m`n`nЛог:`n$Log", "ЛЕС — ошибка",
        [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error) | Out-Null
    } catch { }
  }
  exit 1
}

function Require-Setup([string]$m, [string]$Code = "setup_required", [string]$InstallUrl = "") {
  Log "SETUP: $m"
  Write-Status -Phase "setup" -State "setup_required" -Message $m -Code $Code -InstallUrl $InstallUrl
  exit 0
}

trap {
  Fail "необработанная ошибка: $($_.Exception.Message)" "bootstrap_unhandled"
}

Log "===== bootstrap start (Root=$Root) ====="
Write-Status -Phase "bootstrap" -State "running" -Message "Проверяю окружение Windows"
if (-not (Test-Path -LiteralPath $StateScript)) {
  Fail "не найден модуль состояния Windows: $StateScript" "windows_state_helper_missing"
}
try {
  . $StateScript
  $StateRoot = Get-LesWindowsStateRoot
} catch {
  Fail "не удалось загрузить модуль состояния Windows: $($_.Exception.Message)" "windows_state_helper_failed"
}
Set-Location $Root
$env:LES_RUNTIME_HOME = $Root
$env:LES_REPO_ROOT = $Root

# Code is replaceable; state survives NSIS/Tauri updates. Junctions preserve the
# existing relative-path contracts used by Python without coupling data to an app version.
$State = Initialize-LesWindowsState -RuntimeRoot $Root -StateRoot $StateRoot
$env:LES_WINDOWS_STATE_ROOT = $State.state_root
$env:LES_ENV_PATH = $State.env_path
$env:UV_PROJECT_ENVIRONMENT = Join-Path $State.state_root ".venv"
Log "persistent state: $($State.state_root); migrated=$($State.migrated -join ',')"

# --- 1. Ensure bundled Python + uv ------------------------------------------
function Resolve-BundledPython {
  $contractPath = Join-Path $Root "installers\windows\tools\python-contract.json"
  if (-not (Test-Path -LiteralPath $contractPath)) {
    throw "bundled Python contract is missing: $contractPath"
  }
  $contract = Get-Content -LiteralPath $contractPath -Raw | ConvertFrom-Json
  $archive = Join-Path $Root ("installers\windows\tools\" + $contract.archive_name)
  if (-not (Test-Path -LiteralPath $archive)) {
    throw "bundled Python archive is missing: $archive"
  }
  $actual = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
  if (-not $contract.archive_sha256 -or $actual -ne $contract.archive_sha256.ToLowerInvariant()) {
    throw "bundled Python archive SHA-256 mismatch"
  }

  $pythonRoot = Join-Path $State.state_root ("embedded-python\" + $contract.version)
  $python = Join-Path $pythonRoot $contract.python_relative_path
  if (-not (Test-Path -LiteralPath $python)) {
    $temporaryRoot = "$pythonRoot.installing"
    Remove-Item -LiteralPath $temporaryRoot -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $temporaryRoot | Out-Null
    Toast "Распаковываю встроенный Python $($contract.version)…"
    Write-Status -Phase "python" -State "running" -Message "Распаковываю встроенный Python $($contract.version)"
    Expand-Archive -LiteralPath $archive -DestinationPath $temporaryRoot -Force
    $temporaryPython = Join-Path $temporaryRoot $contract.python_relative_path
    if (-not (Test-Path -LiteralPath $temporaryPython)) {
      throw "bundled Python archive did not create $temporaryPython"
    }
    if (Test-Path -LiteralPath $pythonRoot) {
      Remove-Item -LiteralPath $pythonRoot -Recurse -Force
    }
    Move-Item -LiteralPath $temporaryRoot -Destination $pythonRoot
  }
  $actualVersion = (& $python -c "import sys; print('.'.join(map(str, sys.version_info[:3])))").Trim()
  if ($LASTEXITCODE -ne 0 -or $actualVersion -ne [string]$contract.version) {
    throw "bundled Python version mismatch: expected $($contract.version), got $actualVersion"
  }
  return $python
}

try {
  $BundledPython = Resolve-BundledPython
  Log "bundled Python: $BundledPython"
} catch {
  Fail "не удалось подготовить встроенный Python: $($_.Exception.Message)" "bundled_python_unavailable"
}

function Resolve-Uv {
  $bundled = Join-Path $Root "installers\windows\tools\uv.exe"
  $contractPath = Join-Path $Root "installers\windows\tools\uv-contract.json"
  if ((Test-Path -LiteralPath $bundled) -and (Test-Path -LiteralPath $contractPath)) {
    try {
      $contract = Get-Content -LiteralPath $contractPath -Raw | ConvertFrom-Json
      $actual = (Get-FileHash -LiteralPath $bundled -Algorithm SHA256).Hash.ToLowerInvariant()
      if ($contract.binary_sha256 -and $actual -eq $contract.binary_sha256.ToLowerInvariant()) {
        return $bundled
      }
      Log "WARN: bundled uv.exe SHA-256 mismatch; refusing embedded binary"
    } catch {
      Log "WARN: bundled uv.exe contract unreadable: $($_.Exception.Message)"
    }
  }
  $cmd = Get-Command uv -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  foreach ($p in @("$env:USERPROFILE\.local\bin\uv.exe", "$env:USERPROFILE\.cargo\bin\uv.exe")) {
    if (Test-Path $p) { return $p }
  }
  return $null
}

function Refresh-ProcessPath {
  $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
  $user = [Environment]::GetEnvironmentVariable("Path", "User")
  $env:Path = "$machine;$user"
}

function Resolve-Executable([string]$Name, [string[]]$Candidates = @()) {
  $cmd = Get-Command $Name -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  foreach ($candidate in $Candidates) {
    if ($candidate -and (Test-Path -LiteralPath $candidate)) { return $candidate }
  }
  return $null
}

function Add-ExecutableDirectory([string]$Executable) {
  if (-not $Executable) { return }
  $directory = Split-Path -Parent $Executable
  if ($directory -and (($env:Path -split ';') -notcontains $directory)) {
    $env:Path = "$directory;$env:Path"
  }
}

function Install-Uv {
  $winget = Get-Command winget -ErrorAction SilentlyContinue
  if ($winget) {
    Log "installing uv via winget"
    try {
      & winget install --id=astral-sh.uv -e --accept-source-agreements --accept-package-agreements | Out-Null
      if ($LASTEXITCODE -eq 0) {
        Refresh-ProcessPath
      } else {
        Log "WARN: winget uv install failed with exit code $LASTEXITCODE; trying official installer"
      }
    } catch {
      Log "WARN: winget uv install exception: $($_.Exception.Message); trying official installer"
    }
    $installed = Resolve-Uv
    if ($installed) { return $installed }
  } else {
    Log "winget unavailable; trying official uv installer"
  }

  Log "installing uv via official installer fallback"
  try {
    & powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex" | Out-Null
    if ($LASTEXITCODE -ne 0) {
      Log "WARN: official uv installer failed with exit code $LASTEXITCODE"
    }
  } catch {
    Log "WARN: official uv installer exception: $($_.Exception.Message)"
  }
  Refresh-ProcessPath
  return Resolve-Uv
}

$Uv = Resolve-Uv
if (-not $Uv) {
  Toast "Устанавливаю uv (первый запуск)…"
  Log "installing uv"
  $Uv = Install-Uv
  if (-not $Uv) {
    Fail "не удалось установить uv через winget и официальный fallback; проверьте bootstrap.log" `
      "uv_install_failed_after_fallback" "https://docs.astral.sh/uv/getting-started/installation/"
  }
}
Log "uv: $Uv"

# --- 1b. Detect Windows runtimes --------------------------------------------
# The Tauri setup wizard owns installation choices. Missing external programs
# are a normal first-run state, not a bootstrap failure.
$Ollama = Resolve-Executable "ollama" @(
  (Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"),
  (Join-Path $env:ProgramFiles "Ollama\ollama.exe")
)
if ($Ollama) {
  Add-ExecutableDirectory $Ollama
  Log "ollama: $Ollama"
} else {
  Log "setup: Ollama not installed"
}

$Docker = Resolve-Executable "docker" @(
  (Join-Path $env:ProgramFiles "Docker\Docker\resources\bin\docker.exe")
)
if ($Docker) {
  Add-ExecutableDirectory $Docker
  Log "docker: $Docker"
} else {
  Log "setup: Docker Desktop not installed"
}

# --- 2. Environment ---------------------------------------------------------
# --extra desktop pulls the native shell (pywebview + tray). No mac-mlx on Windows.
Toast "Готовлю окружение…"
Write-Status -Phase "python" -State "running" -Message "Синхронизирую Python-окружение через uv"
$env:UV_SYSTEM_CERTS = if ($env:UV_SYSTEM_CERTS) { $env:UV_SYSTEM_CERTS } else { "true" }
$env:UV_HTTP_CONNECT_TIMEOUT = if ($env:UV_HTTP_CONNECT_TIMEOUT) { $env:UV_HTTP_CONNECT_TIMEOUT } else { "30" }
$env:UV_HTTP_TIMEOUT = if ($env:UV_HTTP_TIMEOUT) { $env:UV_HTTP_TIMEOUT } else { "120" }
$env:UV_HTTP_RETRIES = if ($env:UV_HTTP_RETRIES) { $env:UV_HTTP_RETRIES } else { "5" }

$VenvPath = $env:UV_PROJECT_ENVIRONMENT
$VenvWasUsable = $false
$VenvPython = Join-Path $VenvPath "Scripts\python.exe"
if (Test-Path -LiteralPath $VenvPython) {
  $venvProbe = @(& $VenvPython -c "import sys; print(sys.executable)" 2>&1)
  $VenvWasUsable = $LASTEXITCODE -eq 0
}
if ((Test-Path -LiteralPath $VenvPath) -and -not $VenvWasUsable) {
  Log "removing incomplete or broken Python environment: $VenvPath"
  Remove-Item -LiteralPath $VenvPath -Recurse -Force
}

$UvSyncArgs = @("sync", "--locked", "--python", $BundledPython, "--no-python-downloads")
if ($env:LES_TAURI_SHELL -eq "1") {
  Log "uv sync with bundled Python (Tauri owns desktop shell)" # command fragment: --extra windows-reranker
  $UvSyncArgs += @("--extra", "windows-reranker")
} else {
  Log "uv sync with bundled Python --extra desktop (legacy fallback)"
  $UvSyncArgs += @("--extra", "desktop")
}
# uv writes normal progress (including the selected interpreter) to stderr.
# Windows PowerShell 5.1 turns native stderr into a terminating error while the
# bootstrap-wide ErrorActionPreference is Stop, so capture it under Continue
# and decide solely from the native exit code below.
$previousErrorActionPreference = $ErrorActionPreference
try {
  $ErrorActionPreference = "Continue"
  $uvSyncOutput = @(& $Uv @UvSyncArgs 2>&1)
  $uvSyncExitCode = $LASTEXITCODE
} finally {
  $ErrorActionPreference = $previousErrorActionPreference
}
foreach ($line in $uvSyncOutput) {
  $safeLine = [regex]::Replace([string]$line, '(?i)(https?://)[^/\s:@]+:[^@\s/]+@', '$1***@')
  if ($safeLine) { Log "uv: $safeLine" }
}
if ($uvSyncExitCode -ne 0) {
  if (-not $VenvWasUsable -and (Test-Path -LiteralPath $VenvPath)) {
    Remove-Item -LiteralPath $VenvPath -Recurse -Force -ErrorAction SilentlyContinue
  }
  $uvDetail = (($uvSyncOutput | Where-Object { $_ } | Select-Object -Last 6) -join " | ").Trim()
  $uvDetail = [regex]::Replace($uvDetail, '(?i)(https?://)[^/\s:@]+:[^@\s/]+@', '$1***@')
  if ($uvDetail.Length -gt 900) { $uvDetail = $uvDetail.Substring(0, 900) }
  if (-not $uvDetail) { $uvDetail = "uv не вернул диагностический текст" }
  Fail "uv sync не удался (код $uvSyncExitCode): $uvDetail" "uv_sync_failed" `
    "https://docs.astral.sh/uv/concepts/authentication/certificates/"
}

# A clean install must be able to resolve norms and calculate normative resource
# quantities without borrowing data from another workstation or scraping FGIS
# for hours. Regional split forms remain an explicit period/zone selection. The
# release baseline is immutable and checksum-verified; provisioning never
# overwrites partial or existing user state.
$SmetaBaseline = Join-Path $Root "installers\windows\baseline\LES-smeta-baseline.zip"
if (-not (Test-Path -LiteralPath $SmetaBaseline)) {
  Warn "сметная база недоступна: в пакете нет verified baseline; сметный модуль ограничен"
} else {
  Write-Status -Phase "smeta" -State "running" -Message "Проверяю базу ГЭСН и ФСЭМ"
  # Updates must recover a partial/corrupt local baseline as well as provision a
  # clean machine. `repair` verifies healthy state without touching it and moves
  # only a broken set into storage/recovery before restoring the signed archive.
  $baselineResult = & $Uv run python tools\smeta_release_baseline.py repair `
    --archive $SmetaBaseline --state-root $StateRoot
  if ($LASTEXITCODE -ne 0) {
    Warn "сметная база недоступна: $($baselineResult -join ' '); остальные модули запускаются"
  } else {
    Grant-LesWindowsStateAccess -Path (Join-Path $StateRoot "data\smeta_base") -Recurse
    Grant-LesWindowsStateAccess -Path (Join-Path $StateRoot "data\gesn_base") -Recurse
    Log "smeta baseline: $($baselineResult -join ' ')"
  }
}

# Tauri owns the native window. Lifecycle actions stay in the same bootstrap,
# but must not launch the legacy pywebview shell.
if ($env:LES_TAURI_SHELL -eq "1") {
  if ($env:LES_TAURI_ACTION -eq "stop") {
    & (Join-Path $Root "installers\windows\stop-light.ps1")
    if ($LASTEXITCODE -ne 0) { Fail "не удалось остановить службы" }
    exit 0
  }
  if ($env:LES_TAURI_ACTION -eq "restart") {
    & (Join-Path $Root "installers\windows\stop-light.ps1")
    & (Join-Path $Root "installers\windows\start-light.ps1")
    if ($LASTEXITCODE -ne 0) { Fail "не удалось перезапустить службы" }
    exit 0
  }
}

# --- 3. .env + directories --------------------------------------------------
& $Uv run lesctl init --profile windows-lite 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "не удалось инициализировать Windows-профиль ЛЕС" "les_init_failed" }

# --- 3a. Classic Outlook read-only collector -------------------------------
# The task runs only in the interactive user session because Outlook COM is
# intentionally never exposed as a service account. Each Outlook store creates
# its own LES dataset on first successful intake.
$OutlookCollectorSetup = Join-Path $Root "clients\outlook_mail_poller\setup_task.ps1"
try {
  $classicOutlook = [Type]::GetTypeFromProgID("Outlook.Application")
  if ($env:LES_RELEASE_SMOKE -eq "1") {
    Log "release smoke: skip registration of the user-wide Outlook collector task"
  } elseif ($classicOutlook -and (Test-Path -LiteralPath $OutlookCollectorSetup)) {
    Write-Status -Phase "mail" -State "running" -Message "Устанавливаю сборщик классического Outlook"
    $mailInstallRoot = Join-Path $StateRoot "bin"
    $mailStateRoot = Join-Path $StateRoot "mail"
    $mailSetupOutput = @(& $OutlookCollectorSetup `
      -InstallRoot $mailInstallRoot -StateRoot $mailStateRoot)
    if ($LASTEXITCODE -ne 0) { throw "collector setup returned $LASTEXITCODE" }
    $env:LES_OUTLOOK_COLLECTOR_EXE = Join-Path $mailInstallRoot "LesMailPoller.exe"
    Log "Outlook collector: $($mailSetupOutput -join ' ')"
  } else {
    Log "classic Outlook not detected; collector task not installed"
  }
} catch {
  Warn "сборщик Outlook не установлен: $($_.Exception.Message)"
}

# --- 3b. Provider onboarding (first run only) -------------------------------
# No MLX on Windows. Non-interactive default = local ollama so the first chat
# works without a cloud key; the operator switches provider/key/model in the
# Sovushka GUI «Настройки» afterwards. Existing Windows-compatible cloud,
# Ollama or Lemonade settings are preserved; a stale Mac-only MLX setting is
# replaced before model onboarding so Windows never downloads MLX weights.
& $Uv run python tools\onboard_provider.py --provider ollama --ensure-platform windows 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "не удалось настроить локальный провайдер Ollama" "provider_init_failed" }

$providerLine = Get-Content $env:LES_ENV_PATH -ErrorAction SilentlyContinue |
  Where-Object { $_ -match '^LES_LLM_PROVIDER=' } | Select-Object -Last 1
$configuredProvider = if ($providerLine) { ($providerLine -split '=', 2)[1].Trim() } else { "" }

if (($configuredProvider -eq "ollama") -and (-not $Ollama)) {
  Require-Setup "Установите Ollama. Модель вы выберете и загрузите самостоятельно" `
    "ollama_missing" "https://ollama.com/download/windows"
}
if (-not $Docker) {
  Require-Setup "Установите Docker Desktop для локального хранилища документов" `
    "docker_missing" "https://www.docker.com/products/docker-desktop/"
}

# --- 4. Model weights (only if a local HF model is configured) --------------
# Cloud/ollama setups skip this; for a local provider it pre-pulls weights.
Toast "Проверяю модели…"
Write-Status -Phase "models" -State "running" -Message "Проверяю локальные модели"
& $Uv run python tools\onboard_models.py --skip-if-cloud
if ($LASTEXITCODE -ne 0) { Fail "загрузка моделей не удалась" }

# Ollama manages its own model store. The user may choose any installed answer
# model; LES recommends qwen3.5:9b but never pulls it behind the user's back.
# bge-m3 is the separate, fixed embedding contract for document search.
if ($configuredProvider -eq "ollama") {
  $modelLine = Get-Content $env:LES_ENV_PATH -ErrorAction SilentlyContinue |
    Where-Object { $_ -match '^OLLAMA_MODEL=' } | Select-Object -Last 1
  $configuredModel = if ($modelLine) { ($modelLine -split '=', 2)[1].Trim() } else { "" }
  if (-not $configuredModel) {
    Require-Setup "Выберите установленную модель Ollama. Рекомендуем qwen3.5:9b" `
      "answer_model_not_selected" "https://ollama.com/library"
  }
  & $Ollama show $configuredModel *> $null
  if ($LASTEXITCODE -ne 0) {
    Require-Setup "Модель $configuredModel не установлена. Загрузите любую подходящую модель и выберите её в мастере" `
      "answer_model_missing" "https://ollama.com/library"
  }
  & $Ollama show "bge-m3:latest" *> $null
  if ($LASTEXITCODE -ne 0) {
    Require-Setup "Для поиска по документам нужна embedding-модель bge-m3:latest. Загрузите её через Ollama" `
      "embedding_model_missing" "https://ollama.com/library/bge-m3"
  }
}

# The cross-encoder is a Hugging Face model, not an Ollama generation model.
Toast "Проверяю модель ранжирования…"
& $Uv run python tools\onboard_reranker.py
if ($LASTEXITCODE -ne 0) { Warn "модель ранжирования пока недоступна; ЛЕС запустится без rerank до повторной настройки" }

# --- 5. Docker + Qdrant (required) -----------------------------------------
function Test-DockerEngine {
  & $Docker info *> $null
  return ($LASTEXITCODE -eq 0)
}

if (-not (Test-DockerEngine)) {
  $DockerDesktop = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
  if (Test-Path -LiteralPath $DockerDesktop) {
    Toast "Запускаю Docker Desktop…"
    Write-Status -Phase "docker" -State "running" -Message "Запускаю Docker Desktop"
    Start-Process -FilePath $DockerDesktop | Out-Null
    $deadline = [DateTime]::UtcNow.AddMinutes(3)
    do {
      Start-Sleep -Seconds 3
      if (Test-DockerEngine) { break }
    } while ([DateTime]::UtcNow -lt $deadline)
  }
}
if (-not (Test-DockerEngine)) {
  Require-Setup "Запустите Docker Desktop и завершите первоначальную настройку WSL 2" `
    "docker_engine_unavailable" "https://docs.docker.com/desktop/setup/install/windows-install/"
}

Write-Status -Phase "qdrant" -State "running" -Message "Проверяю Qdrant"
$qdrantUp = $false
try { $null = Invoke-RestMethod "http://127.0.0.1:6333/collections" -TimeoutSec 2; $qdrantUp = $true } catch { }
if (-not $qdrantUp) {
  Log "starting qdrant via docker"
  & $Docker volume create les-qdrant-data | Out-Null
  if ($LASTEXITCODE -ne 0) { Fail "не удалось создать хранилище Qdrant" "qdrant_volume_failed" }
  $existingQdrant = & $Docker ps -a --filter "name=^/les-light-qdrant$" --quiet
  if ($existingQdrant) {
    & $Docker start les-light-qdrant | Out-Null
  } else {
    $qdrantImage = if ($env:LES_QDRANT_IMAGE) { $env:LES_QDRANT_IMAGE } else { "qdrant/qdrant:v1.17.1" }
    & $Docker run -d --name les-light-qdrant -p "6333:6333" -v "les-qdrant-data:/qdrant/storage" $qdrantImage | Out-Null
  }
  if ($LASTEXITCODE -ne 0) { Fail "не удалось запустить контейнер Qdrant" "qdrant_start_failed" }
  $qdrantDeadline = [DateTime]::UtcNow.AddMinutes(2)
  do {
    Start-Sleep -Seconds 2
    try {
      $null = Invoke-RestMethod "http://127.0.0.1:6333/collections" -TimeoutSec 2
      $qdrantUp = $true
      break
    } catch { }
  } while ([DateTime]::UtcNow -lt $qdrantDeadline)
}
if (-not $qdrantUp) {
  Require-Setup "Qdrant не запустился. Проверьте Docker Desktop и повторите проверку" "qdrant_health_failed" `
    "https://docs.docker.com/desktop/setup/install/windows-install/"
}

# --- 6. Launch the desktop shell --------------------------------------------
# The shell (tools/les_shell.py) owns lifecycle: on Windows it starts the stack
# via start-light.ps1, shows the native window + tray, and degrades to a browser
# tab if the GUI deps are missing.
Toast "Запускаю Совушку…"
Write-Status -Phase "services" -State "running" -Message "Запускаю службы ЛЕС"
if ($env:LES_TAURI_SHELL -eq "1") {
  Log "start-light (Tauri shell)"
  try {
    # An in-place update can leave the previous build listening on 8050/8051.
    # Stop only the LES proxy/UI ports (Qdrant and independent FGIS jobs survive)
    # so the installed build replaces the old one instead of hiding on 8052/8053.
    $stopScript = Join-Path $Root "installers\windows\stop-light.ps1"
    # First clear any fallback ports remembered by an older side-by-side start,
    # then always clear the canonical production ports. The second call passes
    # explicit values so stop-light cannot substitute stale state-file ports.
    if ($env:LES_RELEASE_SMOKE -eq "1") {
      Log "release smoke: keep production ports and select dynamic ports"
    } else {
      $stopStaleOutput = @(& $stopScript)
      $stopStaleOutput | Out-File -FilePath $Log -Append -Encoding utf8
      $stopOutput = @(& $stopScript -ProxyPort 8050 -UiPort 8051)
      $stopOutput | Out-File -FilePath $Log -Append -Encoding utf8
    }
    # Run the PowerShell script in-process. A native `powershell ... | Out-File`
    # pipeline can stay open after start-light exits because long-lived proxy/UI
    # descendants inherit its output handle, leaving bootstrap stuck at services/running.
    $serviceOutput = @(& (Join-Path $Root "installers\windows\start-light.ps1"))
    $serviceOutput | Out-File -FilePath $Log -Append -Encoding utf8
    # start-light starts long-lived child processes and has its own short
    # diagnostic timeout.  Bootstrap must not publish terminal `ready` until
    # the installed API itself answers; a clean Qdrant collection can still be
    # finishing asynchronous payload-index creation at that point.
    $runtimeStatePath = Join-Path $StateRoot "logs\windows-light-state.json"
    if (-not (Test-Path -LiteralPath $runtimeStatePath)) {
      Fail "службы запущены без файла состояния" "services_state_missing"
    }
    $runtimeState = Get-Content -LiteralPath $runtimeStatePath -Raw | ConvertFrom-Json
    $proxyPort = [int]$runtimeState.proxy_port
    $apiHealth = Wait-LesApiReady "http://127.0.0.1:$proxyPort/api/health" 180
    if (-not $apiHealth) {
      Fail "API ЛЕС не ответил после запуска служб" "services_api_not_ready"
    }
  } catch {
    Fail "не удалось поднять службы: $($_.Exception.Message)" "services_start_failed"
  }
} else {
  Log "les_shell (legacy fallback)"
  & $Uv run python -m tools.les_shell | Out-File -FilePath $Log -Append -Encoding utf8
  if ($LASTEXITCODE -ne 0) { Fail "не удалось запустить шелл" }
}

Log "===== bootstrap done ====="
if ($script:BootstrapWarnings.Count -gt 0) {
  Write-Status -Phase "ready" -State "ready" `
    -Message ("ЛЕС запущен с ограничениями: " + ($script:BootstrapWarnings -join "; ")) `
    -Code "bootstrap_degraded"
} else {
  Write-Status -Phase "ready" -State "ready" -Message "ЛЕС запущен"
}
exit 0
