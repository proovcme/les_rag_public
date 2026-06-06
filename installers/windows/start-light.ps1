param(
  [int]$ProxyPort = 8050,
  [int]$UiPort = 8051,
  [int]$QdrantPort = 6333,
  [ValidateSet("mlx", "openrouter", "openai", "ollama", "lemonade", "openai-compatible")]
  [string]$Provider = "lemonade",
  [string]$Model = "",
  [switch]$StartQdrant,
  [switch]$NoUi
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root

function Stop-LesPortProcess([int]$Port) {
  $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  foreach ($conn in $connections) {
    if ($conn.OwningProcess -gt 0) {
      Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
    }
  }
}

if ($StartQdrant) {
  if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker is required when -StartQdrant is used."
  }
  docker rm -f les-light-qdrant 2>$null | Out-Null
  docker run -d --name les-light-qdrant -p "${QdrantPort}:6333" qdrant/qdrant:latest | Out-Null
}

Stop-LesPortProcess -Port $ProxyPort
if (-not $NoUi) {
  Stop-LesPortProcess -Port $UiPort
}

$env:QDRANT_URL = "http://127.0.0.1:$QdrantPort"
$env:MLX_URL = "http://127.0.0.1:18080"
$env:LES_LLM_PROVIDER = $Provider
$env:CHAT_VALIDATION_ENABLED = "false"
$env:RAG_OCR_ENABLED = "false"
$env:SPECKLE_ENABLED = "false"
$env:CORS_ALLOWED_ORIGINS = "http://127.0.0.1:$ProxyPort,http://127.0.0.1:$UiPort,http://localhost:$ProxyPort,http://localhost:$UiPort"
New-Item -ItemType Directory -Force -Path (Join-Path $Root "logs") | Out-Null

switch ($Provider) {
  "openrouter" {
    $env:OPENROUTER_BASE_URL = if ($env:OPENROUTER_BASE_URL) { $env:OPENROUTER_BASE_URL } else { "https://openrouter.ai/api/v1" }
    if ($Model) { $env:OPENROUTER_MODEL = $Model }
  }
  "openai" {
    $env:OPENAI_BASE_URL = if ($env:OPENAI_BASE_URL) { $env:OPENAI_BASE_URL } else { "https://api.openai.com/v1" }
    if ($Model) { $env:OPENAI_MODEL = $Model }
  }
  "openai-compatible" {
    $env:OPENAI_BASE_URL = if ($env:OPENAI_BASE_URL) { $env:OPENAI_BASE_URL } else { "http://127.0.0.1:8000/v1" }
    if ($Model) { $env:OPENAI_MODEL = $Model }
  }
  "ollama" {
    $env:OLLAMA_BASE_URL = if ($env:OLLAMA_BASE_URL) { $env:OLLAMA_BASE_URL } else { "http://127.0.0.1:11434" }
    if ($Model) { $env:OLLAMA_MODEL = $Model }
  }
  "lemonade" {
    $env:LEMONADE_BASE_URL = if ($env:LEMONADE_BASE_URL) { $env:LEMONADE_BASE_URL } else { "http://127.0.0.1:13305/api/v1" }
    $env:LEMONADE_API_KEY = if ($env:LEMONADE_API_KEY) { $env:LEMONADE_API_KEY } else { "lemonade" }
    if ($Model) { $env:LEMONADE_MODEL = $Model }
  }
}

$proxyArgs = @("run", "uvicorn", "proxy_server:app", "--host", "127.0.0.1", "--port", "$ProxyPort")
$proxyOut = Join-Path $Root "logs\windows-light-proxy.out.log"
$proxyErr = Join-Path $Root "logs\windows-light-proxy.err.log"
$proxy = Start-Process uv -ArgumentList $proxyArgs -WorkingDirectory $Root -PassThru -WindowStyle Hidden -RedirectStandardOutput $proxyOut -RedirectStandardError $proxyErr

$ui = $null
if (-not $NoUi) {
  $env:SOVUSHKA_UI_PORT = "$UiPort"
  $uiArgs = @("run", "python", "sovushka_ng.py")
  $uiOut = Join-Path $Root "logs\windows-light-ui.out.log"
  $uiErr = Join-Path $Root "logs\windows-light-ui.err.log"
  $ui = Start-Process uv -ArgumentList $uiArgs -WorkingDirectory $Root -PassThru -WindowStyle Hidden -RedirectStandardOutput $uiOut -RedirectStandardError $uiErr
}

Start-Sleep -Seconds 4

$health = $null
try {
  $health = Invoke-RestMethod "http://127.0.0.1:$ProxyPort/api/health"
} catch {
  $health = @{ status = "error"; detail = $_.Exception.Message }
}

[pscustomobject]@{
  status = "started"
  provider = $Provider
  proxy_port = $ProxyPort
  ui_port = if ($NoUi) { $null } else { $UiPort }
  qdrant_url = $env:QDRANT_URL
  proxy_pid = $proxy.Id
  ui_pid = if ($ui) { $ui.Id } else { $null }
  proxy_alive = -not $proxy.HasExited
  ui_alive = if ($ui) { -not $ui.HasExited } else { $null }
  proxy_log = $proxyErr
  ui_log = if ($ui) { $uiErr } else { $null }
  health = $health
} | ConvertTo-Json -Depth 8
