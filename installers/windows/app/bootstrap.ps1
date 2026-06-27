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
$LogDir   = Join-Path $env:LOCALAPPDATA "LES\logs"
$Log      = Join-Path $LogDir "bootstrap.log"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Log([string]$m) { "$([DateTime]::Now.ToString('yyyy-MM-dd HH:mm:ss'))  $m" | Out-File -FilePath $Log -Append -Encoding utf8 }

function Toast([string]$m) {
  try {
    Add-Type -AssemblyName System.Windows.Forms
    $n = New-Object System.Windows.Forms.NotifyIcon
    $n.Icon = [System.Drawing.SystemIcons]::Information
    $n.Visible = $true
    $n.ShowBalloonTip(4000, "ЛЕС · Совушка", $m, [System.Windows.Forms.ToolTipIcon]::Info)
  } catch { }
}

function Fail([string]$m) {
  Log "FAIL: $m"
  try {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show("ЛЕС не смог запуститься: $m`n`nЛог:`n$Log", "ЛЕС — ошибка",
      [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error) | Out-Null
  } catch { }
  exit 1
}

Log "===== bootstrap start (Root=$Root) ====="
Set-Location $Root

# --- 1. Ensure uv -----------------------------------------------------------
function Resolve-Uv {
  $cmd = Get-Command uv -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  foreach ($p in @("$env:USERPROFILE\.local\bin\uv.exe", "$env:USERPROFILE\.cargo\bin\uv.exe")) {
    if (Test-Path $p) { return $p }
  }
  return $null
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
  if (-not $Uv) { Fail "не удалось установить uv" }
}
Log "uv: $Uv"

# --- 2. Environment ---------------------------------------------------------
# --extra desktop pulls the native shell (pywebview + tray). No mac-mlx on Windows.
Toast "Готовлю окружение…"
Log "uv sync --extra desktop"
& $Uv sync --extra desktop
if ($LASTEXITCODE -ne 0) { Fail "uv sync не удался" }

# --- 3. .env + directories --------------------------------------------------
& $Uv run lesctl init --profile windows-lite 2>$null | Out-Null

# --- 3b. Provider onboarding (first run only) -------------------------------
# No MLX on Windows. Non-interactive default = local ollama so the first chat
# works without a cloud key; the operator switches provider/key/model in the
# Sovushka GUI «Настройки» afterwards. Skips if a provider is already set.
& $Uv run python tools\onboard_provider.py --skip-if-configured --provider ollama 2>$null | Out-Null

# --- 4. Model weights (only if a local HF model is configured) --------------
# Cloud/ollama setups skip this; for a local provider it pre-pulls weights.
Toast "Проверяю модели…"
& $Uv run python tools\onboard_models.py --skip-if-cloud
if ($LASTEXITCODE -ne 0) { Fail "загрузка моделей не удалась" }

# --- 5. Qdrant (best effort) ------------------------------------------------
$qdrantUp = $false
try { $null = Invoke-RestMethod "http://127.0.0.1:6333/collections" -TimeoutSec 2; $qdrantUp = $true } catch { }
if (-not $qdrantUp -and (Get-Command docker -ErrorAction SilentlyContinue)) {
  Log "starting qdrant via docker"
  docker rm -f les-qdrant 2>$null | Out-Null
  docker run -d --name les-qdrant -p "6333:6333" qdrant/qdrant:latest | Out-Null
} elseif (-not $qdrantUp) {
  Log "qdrant not running and docker absent — RAG features limited until Qdrant is available"
}

# --- 6. Launch the desktop shell --------------------------------------------
# The shell (tools/les_shell.py) owns lifecycle: on Windows it starts the stack
# via start-light.ps1, shows the native window + tray, and degrades to a browser
# tab if the GUI deps are missing.
Toast "Запускаю Совушку…"
Log "les_shell"
& $Uv run python -m tools.les_shell | Out-File -FilePath $Log -Append -Encoding utf8
if ($LASTEXITCODE -ne 0) { Fail "не удалось запустить шелл" }

Log "===== bootstrap done ====="
exit 0
