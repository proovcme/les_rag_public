param(
  [int]$ProxyPort = 8050,
  [int]$UiPort = 8051,
  [int]$QdrantPort = 6333,
  [int]$LemonadeHostPort = 18080,
  [ValidateSet("", "mlx", "openrouter", "openai", "ollama", "lemonade", "openai-compatible")]
  [string]$Provider = "",
  [string]$Model = "",
  [switch]$StartQdrant,
  [switch]$NoUi
)

$ErrorActionPreference = "Stop"
$ProxyPortExplicit = $PSBoundParameters.ContainsKey("ProxyPort")
$UiPortExplicit = $PSBoundParameters.ContainsKey("UiPort")
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root

$StateRoot = if ($env:LES_WINDOWS_STATE_ROOT) { [System.IO.Path]::GetFullPath($env:LES_WINDOWS_STATE_ROOT) } else { "" }
if ($StateRoot) {
  $env:LES_ENV_PATH = if ($env:LES_ENV_PATH) { $env:LES_ENV_PATH } else { Join-Path $StateRoot ".env" }
  $env:UV_PROJECT_ENVIRONMENT = if ($env:UV_PROJECT_ENVIRONMENT) { $env:UV_PROJECT_ENVIRONMENT } else { Join-Path $StateRoot ".venv" }
}

function Get-LesDotEnvValue([string]$Key) {
  $envPath = if ($env:LES_ENV_PATH) { $env:LES_ENV_PATH } else { Join-Path $Root ".env" }
  if (-not (Test-Path $envPath)) { return "" }
  $line = Get-Content $envPath | Where-Object { $_ -match "^$([regex]::Escape($Key))=" } | Select-Object -Last 1
  if (-not $line) { return "" }
  return ($line -split "=", 2)[1].Trim().Trim('"').Trim("'")
}

if (-not $Provider) {
  $Provider = Get-LesDotEnvValue "LES_LLM_PROVIDER"
  if (-not $Provider) { $Provider = "ollama" }
}
if (-not $Model) {
  $modelKey = switch ($Provider) {
    "ollama" { "OLLAMA_MODEL" }
    "openrouter" { "OPENROUTER_MODEL" }
    "openai" { "OPENAI_MODEL" }
    "openai-compatible" { "OPENAI_MODEL" }
    "lemonade" { "LEMONADE_MODEL" }
    default { "MLX_MODEL" }
  }
  $Model = Get-LesDotEnvValue $modelKey
  if (-not $Model -and $Provider -eq "ollama") { $Model = "qwen3.5:9b" }
}

function Test-LesPortFree([int]$Port) {
  $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  return $null -eq $connection
}

function Get-LesFreePort([int]$StartPort, [int[]]$Reserved = @()) {
  for ($port = $StartPort; $port -lt ($StartPort + 100); $port++) {
    if (($Reserved -notcontains $port) -and (Test-LesPortFree -Port $port)) {
      return $port
    }
  }
  throw "No free TCP port found in range $StartPort-$($StartPort + 99)."
}

function Stop-LesPortProcess([int]$Port) {
  $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  foreach ($conn in $connections) {
    if ($conn.OwningProcess -gt 0) {
      Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
    }
  }
}

function Start-LesUvProcess([string[]]$UvArgs, [string]$StdOut, [string]$StdErr) {
  # Start the command through cmd.exe so Windows keeps the real uv child alive.
  # Direct Start-Process uv can exit after the launcher/build step on some uv installs.
  $quoted = @("uv")
  foreach ($arg in $UvArgs) {
    if ($arg -match '[\s"&|<>^]') {
      $quoted += '"' + ($arg -replace '"', '\"') + '"'
    } else {
      $quoted += $arg
    }
  }
  $cmdLine = $quoted -join " "
  Start-Process -FilePath "cmd.exe" `
    -ArgumentList @("/d", "/s", "/c", $cmdLine) `
    -WorkingDirectory $Root `
    -PassThru `
    -WindowStyle Hidden `
    -RedirectStandardOutput $StdOut `
    -RedirectStandardError $StdErr
}

function Wait-LesHttp([string]$Url, [int]$Seconds = 30) {
  $deadline = (Get-Date).AddSeconds($Seconds)
  do {
    try {
      return Invoke-RestMethod $Url
    } catch {
      Start-Sleep -Milliseconds 750
    }
  } while ((Get-Date) -lt $deadline)
  return $null
}

if ($ProxyPortExplicit) {
  Stop-LesPortProcess -Port $ProxyPort
} elseif (-not (Test-LesPortFree -Port $ProxyPort)) {
  $ProxyPort = Get-LesFreePort -StartPort ($ProxyPort + 1)
}

if (-not $NoUi) {
  if ($UiPortExplicit) {
    Stop-LesPortProcess -Port $UiPort
  } elseif ((-not (Test-LesPortFree -Port $UiPort)) -or ($UiPort -eq $ProxyPort)) {
    $UiPort = Get-LesFreePort -StartPort ($UiPort + 1) -Reserved @($ProxyPort)
  }
}

if ($StartQdrant) {
  if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker is required when -StartQdrant is used."
  }
  $existingQdrant = docker ps -a --filter "name=les-light-qdrant" --quiet
  $runningQdrant = docker ps --filter "name=les-light-qdrant" --quiet
  if ($runningQdrant) {
    Write-Host "les-light-qdrant is already running."
  } elseif ($existingQdrant) {
    docker start les-light-qdrant | Out-Null
  } else {
    $qdrantImage = if ($env:LES_QDRANT_IMAGE) { $env:LES_QDRANT_IMAGE } else { "qdrant/qdrant:v1.17.1" }
    docker volume create les-qdrant-data | Out-Null
    docker run -d --name les-light-qdrant -p "${QdrantPort}:6333" -v "les-qdrant-data:/qdrant/storage" $qdrantImage | Out-Null
  }
}

$env:QDRANT_URL = "http://127.0.0.1:$QdrantPort"
$env:MLX_URL = "http://127.0.0.1:$LemonadeHostPort"
$env:LES_LLM_PROVIDER = $Provider
if ($Model) {
  # LLM_MODEL is the provider-neutral runtime/status contract.  Provider-specific
  # variables below still drive the actual request, but they must not disagree
  # with the model shown by /api/status or used by a shared fallback path.
  $env:LLM_MODEL = $Model
}
$env:CHAT_VALIDATION_ENABLED = "false"
$env:RAG_OCR_ENABLED = "false"
$env:SPECKLE_ENABLED = "false"
$env:PROXY_URL = "http://127.0.0.1:$ProxyPort"
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
    # Эмбеддер (EmbedClient → {MLX_URL}/v1/embeddings) на Windows идёт в ollama (bge-m3),
    # а не в несуществующий MLX-хост :18080. Иначе RAG-индексация/ретрив падают (#3/#4).
    $env:MLX_URL = $env:OLLAMA_BASE_URL
    $env:EMBED_MODEL = if ($env:EMBED_MODEL) { $env:EMBED_MODEL } else { "bge-m3:latest" }
    $env:EMBEDDING_MODEL = if ($env:EMBEDDING_MODEL) { $env:EMBEDDING_MODEL } else { "bge-m3" }
    $env:EMBED_BACKEND = "ollama"
    $env:RAG_VECTOR_SIZE = "1024"
    # Ollama has no cross-encoder rerank endpoint. A native local
    # sentence-transformers cross-encoder keeps the 9B answer model out of
    # retrieval scoring.
    $env:RERANKER_ENABLED = "true"
    $env:RERANKER_BACKEND = "sentence_transformers"
    $env:RERANK_MODEL = if ($env:RERANK_MODEL) { $env:RERANK_MODEL } else { "BAAI/bge-reranker-v2-m3" }
  }
  "lemonade" {
    $env:LEMONADE_BASE_URL = if ($env:LEMONADE_BASE_URL) { $env:LEMONADE_BASE_URL } else { "http://127.0.0.1:13305/api/v1" }
    $env:LEMONADE_API_KEY = if ($env:LEMONADE_API_KEY) { $env:LEMONADE_API_KEY } else { "lemonade" }
    $env:LEMONADE_HOST_PORT = "$LemonadeHostPort"
    if ($Model) { $env:LEMONADE_MODEL = $Model }
  }
}

$lemonadeHost = $null
if ($Provider -eq "lemonade") {
  if ($PSBoundParameters.ContainsKey("LemonadeHostPort")) {
    Stop-LesPortProcess -Port $LemonadeHostPort
  } elseif (-not (Test-LesPortFree -Port $LemonadeHostPort)) {
    $LemonadeHostPort = Get-LesFreePort -StartPort ($LemonadeHostPort + 1) -Reserved @($ProxyPort, $UiPort)
    $env:LEMONADE_HOST_PORT = "$LemonadeHostPort"
    $env:MLX_URL = "http://127.0.0.1:$LemonadeHostPort"
  }
  $lemonadeHostArgs = @("run", "python", "lemonade_host.py")
  $lemonadeHostOut = Join-Path $Root "logs\windows-light-lemonade-host.out.log"
  $lemonadeHostErr = Join-Path $Root "logs\windows-light-lemonade-host.err.log"
  $lemonadeHost = Start-LesUvProcess -UvArgs $lemonadeHostArgs -StdOut $lemonadeHostOut -StdErr $lemonadeHostErr
  $lemonadeHealth = Wait-LesHttp "http://127.0.0.1:$LemonadeHostPort/api/health" 25
  if ($null -eq $lemonadeHealth) {
    Write-Warning "Lemonade adapter did not answer /api/health within startup timeout."
  }
}

$proxyArgs = @("run", "uvicorn", "proxy_server:app", "--host", "127.0.0.1", "--port", "$ProxyPort")
$proxyOut = Join-Path $Root "logs\windows-light-proxy.out.log"
$proxyErr = Join-Path $Root "logs\windows-light-proxy.err.log"
$proxy = Start-LesUvProcess -UvArgs $proxyArgs -StdOut $proxyOut -StdErr $proxyErr

$ui = $null
if (-not $NoUi) {
  $env:SOVUSHKA_UI_PORT = "$UiPort"
  $uiArgs = @("run", "python", "sovushka_ng.py")
  $uiOut = Join-Path $Root "logs\windows-light-ui.out.log"
  $uiErr = Join-Path $Root "logs\windows-light-ui.err.log"
  $ui = Start-LesUvProcess -UvArgs $uiArgs -StdOut $uiOut -StdErr $uiErr
}

$health = Wait-LesHttp "http://127.0.0.1:$ProxyPort/api/health" 45
if ($null -eq $health) {
  $health = @{ status = "error"; detail = "proxy did not answer /api/health within startup timeout" }
}

$payload = [pscustomobject]@{
  status = "started"
  provider = $Provider
  proxy_port = $ProxyPort
  ui_port = if ($NoUi) { $null } else { $UiPort }
  qdrant_url = $env:QDRANT_URL
  mlx_url = $env:MLX_URL
  lemonade_adapter_url = if ($Provider -eq "lemonade") { "http://127.0.0.1:$LemonadeHostPort" } else { $null }
  proxy_url = "http://127.0.0.1:$ProxyPort"
  ui_url = if ($NoUi) { $null } else { "http://127.0.0.1:$UiPort/les" }
  ui_health_url = if ($NoUi) { $null } else { "http://127.0.0.1:$UiPort/healthz" }
  dynamic_ports = (-not $ProxyPortExplicit) -or ((-not $NoUi) -and (-not $UiPortExplicit))
  lemonade_host_pid = if ($lemonadeHost) { $lemonadeHost.Id } else { $null }
  proxy_pid = $proxy.Id
  ui_pid = if ($ui) { $ui.Id } else { $null }
  lemonade_host_alive = if ($lemonadeHost) { -not $lemonadeHost.HasExited } else { $null }
  proxy_alive = -not $proxy.HasExited
  ui_alive = if ($ui) { -not $ui.HasExited } else { $null }
  lemonade_host_log = if ($lemonadeHost) { $lemonadeHostErr } else { $null }
  proxy_log = $proxyErr
  ui_log = if ($ui) { $uiErr } else { $null }
  health = $health
  state_root = if ($StateRoot) { $StateRoot } else { $Root.Path }
}

$statePath = Join-Path $Root "logs\windows-light-state.json"
$payload | ConvertTo-Json -Depth 8 | Set-Content -Path $statePath -Encoding utf8
$payload | ConvertTo-Json -Depth 8
