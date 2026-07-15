# LES Windows first-run / launch bootstrap.
#
# Invoked (hidden) by app\launcher.vbs from the Start Menu / Desktop shortcut.
# No terminal: progress is surfaced via tray balloons, failures via a dialog;
# full detail goes to %LOCALAPPDATA%\LES\logs\bootstrap.log.
#
# Windows has no Apple MLX → the engine is cloud / ollama / lemonade (configured
# in the Sovushka GUI). On first launch this installs uv if missing, runs
# `uv sync`, initializes .env/dirs, optionally starts Qdrant, then brings up the
# proxy + UI via start-light.ps1 and opens the browser.
$ErrorActionPreference = "Stop"

$AppDir   = Split-Path -Parent $MyInvocation.MyCommand.Definition          # ...\installers\windows\app
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
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$StateScript = Join-Path $Root "installers\windows\state.ps1"

function Log([string]$m) { "$([DateTime]::Now.ToString('yyyy-MM-dd HH:mm:ss'))  $m" | Out-File -FilePath $Log -Append -Encoding utf8 }

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

# Code is replaceable; state survives NSIS/Tauri updates. Junctions preserve the
# existing relative-path contracts used by Python without coupling data to an app version.
$State = Initialize-LesWindowsState -RuntimeRoot $Root -StateRoot $StateRoot
$env:LES_WINDOWS_STATE_ROOT = $State.state_root
$env:LES_ENV_PATH = $State.env_path
$env:UV_PROJECT_ENVIRONMENT = Join-Path $State.state_root ".venv"
Log "persistent state: $($State.state_root); migrated=$($State.migrated -join ',')"

# --- 1. Ensure uv -----------------------------------------------------------
function Resolve-Uv {
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

function Install-WingetRequirement(
  [string]$PackageId,
  [string]$DisplayName,
  [string]$InstallUrl
) {
  if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Fail "$DisplayName не установлен, а winget недоступен. Установите компонент и повторите запуск" `
      "winget_missing" $InstallUrl
  }
  Toast "Устанавливаю $DisplayName…"
  Write-Status -Phase "prerequisites" -State "running" -Message "Устанавливаю $DisplayName через winget"
  Log "winget install $PackageId"
  & winget install --id=$PackageId -e --source winget --accept-source-agreements --accept-package-agreements
  if ($LASTEXITCODE -ne 0) {
    Fail "winget не смог установить $DisplayName (код $LASTEXITCODE)" `
      "winget_install_failed" $InstallUrl
  }
  Refresh-ProcessPath
}

$Uv = Resolve-Uv
if (-not $Uv) {
  Toast "Устанавливаю uv (первый запуск)…"
  Log "installing uv"
  try {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
      & winget install --id=astral-sh.uv -e --accept-source-agreements --accept-package-agreements | Out-Null
    } else {
      powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex" | Out-Null
    }
  } catch { }
  $Uv = Resolve-Uv
  if (-not $Uv) {
    Fail "не удалось установить uv" "uv_install_failed" "https://docs.astral.sh/uv/getting-started/installation/"
  }
}
Log "uv: $Uv"

# --- 1b. Required Windows runtimes -----------------------------------------
# Production RAG on Windows is defined by Ollama + Docker/Qdrant.  Do not boot
# a misleading half-working UI when either runtime is absent.
$Ollama = Resolve-Executable "ollama" @(
  (Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"),
  (Join-Path $env:ProgramFiles "Ollama\ollama.exe")
)
if (-not $Ollama) {
  Install-WingetRequirement "Ollama.Ollama" "Ollama" "https://ollama.com/download/windows"
  $Ollama = Resolve-Executable "ollama" @(
    (Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"),
    (Join-Path $env:ProgramFiles "Ollama\ollama.exe")
  )
}
if (-not $Ollama) {
  Fail "Ollama установлена, но ollama.exe не найден. Завершите установку и повторите запуск" `
    "ollama_not_ready" "https://ollama.com/download/windows"
}
Add-ExecutableDirectory $Ollama
Log "ollama: $Ollama"

$Docker = Resolve-Executable "docker" @(
  (Join-Path $env:ProgramFiles "Docker\Docker\resources\bin\docker.exe")
)
if (-not $Docker) {
  Install-WingetRequirement "Docker.DockerDesktop" "Docker Desktop" "https://www.docker.com/products/docker-desktop/"
  $Docker = Resolve-Executable "docker" @(
    (Join-Path $env:ProgramFiles "Docker\Docker\resources\bin\docker.exe")
  )
}
if (-not $Docker) {
  Fail "Docker Desktop установлен, но docker.exe не найден. Завершите установку или перезагрузите Windows" `
    "docker_not_ready" "https://www.docker.com/products/docker-desktop/"
}
Add-ExecutableDirectory $Docker
Log "docker: $Docker"

# --- 2. Environment ---------------------------------------------------------
# --extra desktop pulls the native shell (pywebview + tray). No mac-mlx on Windows.
Toast "Готовлю окружение…"
Write-Status -Phase "python" -State "running" -Message "Синхронизирую Python-окружение через uv"
if ($env:LES_TAURI_SHELL -eq "1") {
  Log "uv sync (Tauri owns desktop shell)"
  & $Uv sync --extra windows-reranker
} else {
  Log "uv sync --extra desktop (legacy fallback)"
  & $Uv sync --extra desktop
}
if ($LASTEXITCODE -ne 0) { Fail "uv sync не удался" }

# A clean install must be able to resolve norms and calculate normative resource
# quantities without borrowing data from another workstation or scraping FGIS
# for hours. Regional split forms remain an explicit period/zone selection. The
# release baseline is immutable and checksum-verified; provisioning never
# overwrites partial or existing user state.
$SmetaBaseline = Join-Path $Root "installers\windows\baseline\LES-smeta-baseline.zip"
if (-not (Test-Path -LiteralPath $SmetaBaseline)) {
  Fail "в установочном пакете отсутствует проверенная сметная база" "smeta_baseline_missing"
}
Write-Status -Phase "smeta" -State "running" -Message "Проверяю базу ГЭСН и ФСЭМ"
$baselineResult = & $Uv run python tools\smeta_release_baseline.py provision `
  --archive $SmetaBaseline --state-root $StateRoot
if ($LASTEXITCODE -ne 0) {
  Fail "не удалось подготовить сметную базу: $($baselineResult -join ' ')" "smeta_baseline_failed"
}
Log "smeta baseline: $($baselineResult -join ' ')"

# Tauri owns the native window. Lifecycle actions stay in the same bootstrap,
# but must not launch the legacy pywebview shell.
if ($env:LES_TAURI_SHELL -eq "1") {
  if ($env:LES_TAURI_ACTION -eq "stop") {
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "installers\windows\stop-light.ps1")
    if ($LASTEXITCODE -ne 0) { Fail "не удалось остановить службы" }
    exit 0
  }
  if ($env:LES_TAURI_ACTION -eq "restart") {
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "installers\windows\stop-light.ps1")
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "installers\windows\start-light.ps1")
    if ($LASTEXITCODE -ne 0) { Fail "не удалось перезапустить службы" }
    exit 0
  }
}

# --- 3. .env + directories --------------------------------------------------
& $Uv run lesctl init --profile windows-lite 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "не удалось инициализировать Windows-профиль ЛЕС" "les_init_failed" }

# --- 3b. Provider onboarding (first run only) -------------------------------
# No MLX on Windows. Non-interactive default = local ollama so the first chat
# works without a cloud key; the operator switches provider/key/model in the
# Sovushka GUI «Настройки» afterwards. Existing Windows-compatible cloud,
# Ollama or Lemonade settings are preserved; a stale Mac-only MLX setting is
# replaced before model onboarding so Windows never downloads MLX weights.
& $Uv run python tools\onboard_provider.py --provider ollama --ensure-platform windows 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "не удалось настроить локальный провайдер Ollama" "provider_init_failed" }

# --- 4. Model weights (only if a local HF model is configured) --------------
# Cloud/ollama setups skip this; for a local provider it pre-pulls weights.
Toast "Проверяю модели…"
Write-Status -Phase "models" -State "running" -Message "Проверяю локальные модели"
& $Uv run python tools\onboard_models.py --skip-if-cloud
if ($LASTEXITCODE -ne 0) { Fail "загрузка моделей не удалась" }

# Ollama manages its own model store, so Hugging Face onboarding intentionally
# skips it. For the default Windows production profile ensure the answer,
# and embedding models are present before the first RAG turn.
$providerLine = Get-Content $env:LES_ENV_PATH -ErrorAction SilentlyContinue |
  Where-Object { $_ -match '^LES_LLM_PROVIDER=' } | Select-Object -Last 1
$configuredProvider = if ($providerLine) { ($providerLine -split '=', 2)[1].Trim() } else { "" }
if ($configuredProvider -eq "ollama") {
  $ollamaModels = @(
    "qwen3.5:9b",
    "bge-m3:latest"
  )
  foreach ($ollamaModel in $ollamaModels) {
    & $Ollama show $ollamaModel *> $null
    if ($LASTEXITCODE -ne 0) {
      Toast "Загружаю модель $ollamaModel…"
      Write-Status -Phase "models" -State "running" -Message "Загружаю Ollama-модель $ollamaModel"
      & $Ollama pull $ollamaModel
      if ($LASTEXITCODE -ne 0) {
        Fail "не удалось загрузить Ollama-модель $ollamaModel" "ollama_model_pull_failed" `
          "https://ollama.com/library"
      }
    }
  }
}

# The cross-encoder is a Hugging Face model, not an Ollama generation model.
Toast "Проверяю модель ранжирования…"
& $Uv run python tools\onboard_reranker.py
if ($LASTEXITCODE -ne 0) { Fail "загрузка модели ранжирования не удалась" }

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
  Fail "Docker Desktop установлен, но движок не запущен. Запустите Docker Desktop, завершите настройку WSL 2 и повторите запуск" `
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
  Fail "Qdrant не ответил после запуска контейнера" "qdrant_health_failed" `
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
    # Run the PowerShell script in-process. A native `powershell ... | Out-File`
    # pipeline can stay open after start-light exits because long-lived proxy/UI
    # descendants inherit its output handle, leaving bootstrap stuck at services/running.
    $serviceOutput = @(& (Join-Path $Root "installers\windows\start-light.ps1"))
    $serviceOutput | Out-File -FilePath $Log -Append -Encoding utf8
  } catch {
    Fail "не удалось поднять службы: $($_.Exception.Message)" "services_start_failed"
  }
} else {
  Log "les_shell (legacy fallback)"
  & $Uv run python -m tools.les_shell | Out-File -FilePath $Log -Append -Encoding utf8
  if ($LASTEXITCODE -ne 0) { Fail "не удалось запустить шелл" }
}

Log "===== bootstrap done ====="
Write-Status -Phase "ready" -State "ready" -Message "ЛЕС запущен"
exit 0
