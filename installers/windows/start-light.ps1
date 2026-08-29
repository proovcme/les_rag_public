param(
  [int]$ProxyPort = 8050,
  [int]$UiPort = 8051,
  [int]$QdrantPort = 6333,
  [int]$LemonadeHostPort = 18080,
  [ValidateSet("", "mlx", "openrouter", "openai", "ollama", "lemonade", "freetoken", "openai-compatible")]
  [string]$Provider = "",
  [string]$Model = "",
  [switch]$NoUi,
  [ValidateSet("full", "backend", "ui")]
  [string]$Mode = "full",
  [string]$BackendUrl = ""
)

$ErrorActionPreference = "Stop"
# Runtime startup must never wait on Hugging Face. Tokenizer/model downloads are
# an explicit preparation action; the online chat/search contour uses Ollama.
$env:RAG_TOKENIZER_LOCAL_FILES_ONLY = "true"
$env:HF_HUB_OFFLINE = "1"
$ProxyPortExplicit = $PSBoundParameters.ContainsKey("ProxyPort")
$UiPortExplicit = $PSBoundParameters.ContainsKey("UiPort")
if ($NoUi) {
  if ($Mode -eq "ui") { throw "-NoUi cannot be combined with -Mode ui." }
  $Mode = "backend"
}
if ($Mode -eq "backend") { $NoUi = $true }
if ($Mode -eq "ui") {
  if (-not $BackendUrl) { throw "UI_BACKEND_URL_REQUIRED" }
  $backendUri = $null
  if (-not [Uri]::TryCreate($BackendUrl, [UriKind]::Absolute, [ref]$backendUri) -or
      $backendUri.Scheme -notin @("http", "https") -or
      -not $backendUri.Host -or $backendUri.UserInfo -or
      $backendUri.Query -or $backendUri.Fragment) {
    throw "UI_BACKEND_URL_INVALID"
  }
  $BackendUrl = $BackendUrl.TrimEnd("/")
}
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root
$env:LES_RUNTIME_HOME = $Root.Path
$env:LES_REPO_ROOT = $Root.Path
. (Join-Path $PSScriptRoot "runtime-process.ps1")

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
    "freetoken" { "FREETOKEN_MODEL" }
    default { "MLX_MODEL" }
  }
  $Model = Get-LesDotEnvValue $modelKey
  if (-not $Model -and $Provider -eq "ollama") { $Model = "qwen3.5:9b" }
}

function Get-LesFreePort([int]$StartPort, [int[]]$Reserved = @()) {
  for ($port = $StartPort; $port -lt ($StartPort + 100); $port++) {
    if (($Reserved -notcontains $port) -and (Test-LesPortFree -Port $port)) {
      return $port
    }
  }
  throw "No free TCP port found in range $StartPort-$($StartPort + 99)."
}

function Resolve-LesPython {
  $environment = if ($env:UV_PROJECT_ENVIRONMENT) {
    $env:UV_PROJECT_ENVIRONMENT
  } else {
    Join-Path $Root ".venv"
  }
  foreach ($name in @("pythonw.exe", "python.exe")) {
    $candidate = Join-Path $environment "Scripts\$name"
    if (Test-Path -LiteralPath $candidate) {
      return $candidate
    }
  }
  throw "LES Python environment is not ready: $environment"
}

function Normalize-LesProcessPathEnvironment {
  # Windows environment names are case-insensitive, but a parent process can
  # still pass both Path and PATH in its raw environment block. Windows
  # PowerShell 5.1 Start-Process then fails while building its environment
  # dictionary ("Key in dictionary: 'Path' ... 'PATH'"). Recreate the process
  # value under one canonical key before starting LES children.
  $processPath = [Environment]::GetEnvironmentVariable(
    "Path",
    [EnvironmentVariableTarget]::Process
  )
  [Environment]::SetEnvironmentVariable(
    "PATH",
    $null,
    [EnvironmentVariableTarget]::Process
  )
  [Environment]::SetEnvironmentVariable(
    "Path",
    $null,
    [EnvironmentVariableTarget]::Process
  )
  [Environment]::SetEnvironmentVariable(
    "Path",
    $processPath,
    [EnvironmentVariableTarget]::Process
  )
}

function Start-LesPythonProcess([string[]]$PythonArgs, [string]$StdOut, [string]$StdErr) {
  Normalize-LesProcessPathEnvironment
  Start-Process -FilePath $LesPython `
    -ArgumentList $PythonArgs `
    -WorkingDirectory $Root `
    -PassThru `
    -WindowStyle Hidden `
    -RedirectStandardOutput $StdOut `
    -RedirectStandardError $StdErr
}

$LesPython = Resolve-LesPython

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

if (($Mode -ne "ui") -and $ProxyPortExplicit) {
  Stop-LesPortProcess -Port $ProxyPort
} elseif (($Mode -ne "ui") -and (-not (Test-LesPortFree -Port $ProxyPort))) {
  try { Stop-LesPortProcess -Port $ProxyPort } catch {}
  if (-not (Test-LesPortFree -Port $ProxyPort)) {
    $ProxyPort = Get-LesFreePort -StartPort ($ProxyPort + 1)
  }
}

if ($Mode -ne "backend") {
  if ($UiPortExplicit) {
    Stop-LesPortProcess -Port $UiPort
  } elseif ((-not (Test-LesPortFree -Port $UiPort)) -or ($UiPort -eq $ProxyPort)) {
    try { Stop-LesPortProcess -Port $UiPort } catch {}
    if ((-not (Test-LesPortFree -Port $UiPort)) -or ($UiPort -eq $ProxyPort)) {
      $UiPort = Get-LesFreePort -StartPort ($UiPort + 1) -Reserved @($ProxyPort)
    }
  }
}

if (-not $env:QDRANT_URL) {
  $env:QDRANT_URL = "http://127.0.0.1:$QdrantPort"
}
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
$env:LES_RUNTIME_MODE = $Mode
$env:PROXY_URL = if ($Mode -eq "ui") { $BackendUrl } else { "http://127.0.0.1:$ProxyPort" }
$env:CORS_ALLOWED_ORIGINS = "http://127.0.0.1:$ProxyPort,http://127.0.0.1:$UiPort,http://localhost:$ProxyPort,http://localhost:$UiPort"
New-Item -ItemType Directory -Force -Path (Join-Path $Root "logs") | Out-Null

function Set-LesOllamaEmbeddings {
  $env:OLLAMA_BASE_URL = if ($env:OLLAMA_BASE_URL) { $env:OLLAMA_BASE_URL } else { "http://127.0.0.1:11434" }
  $env:MLX_URL = $env:OLLAMA_BASE_URL
  $env:EMBED_URL_PARSE = $env:OLLAMA_BASE_URL
  $env:EMBED_MODEL = if ($env:EMBED_MODEL) { $env:EMBED_MODEL } else { "bge-m3:latest" }
  $env:EMBEDDING_MODEL = if ($env:EMBEDDING_MODEL) { $env:EMBEDDING_MODEL } else { "bge-m3" }
  $env:EMBED_BACKEND = "ollama"
  $env:RAG_VECTOR_SIZE = "1024"
  if (-not $env:RERANKER_ENABLED) { $env:RERANKER_ENABLED = "false" }
  $env:RERANKER_BACKEND = "sentence_transformers"
  $env:RERANK_MODEL = if ($env:RERANK_MODEL) { $env:RERANK_MODEL } else { "BAAI/bge-reranker-v2-m3" }
}

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
    if ($Model) { $env:OLLAMA_MODEL = $Model }
    # Эмбеддер (EmbedClient → {MLX_URL}/v1/embeddings) на Windows идёт в ollama (bge-m3),
    # а не в несуществующий MLX-хост :18080. Иначе RAG-индексация/ретрив падают (#3/#4).
    # env.example содержит Mac/dev sidecar :8081. Windows production не поднимает этот процесс:
    # parse и query embeddings обязаны идти в один проверенный Ollama endpoint.
    # Ollama has no cross-encoder rerank endpoint. A native local
    # sentence-transformers cross-encoder keeps the 9B answer model out of
    # retrieval scoring.
    Set-LesOllamaEmbeddings
  }
  "freetoken" {
    $env:FREETOKEN_BASE_URL = if ($env:FREETOKEN_BASE_URL) { $env:FREETOKEN_BASE_URL } else { "http://127.0.0.1:1919/v1" }
    $env:FREETOKEN_CONTEXT_TOKENS = if ($env:FREETOKEN_CONTEXT_TOKENS) { $env:FREETOKEN_CONTEXT_TOKENS } else { "8253" }
    if (-not $env:FREETOKEN_PROMPT_MAX_CHARS) {
        $freeTokenContext = [int]$env:FREETOKEN_CONTEXT_TOKENS
        $freeTokenUsable = [Math]::Max(512, $freeTokenContext - 1200)
        $env:FREETOKEN_PROMPT_MAX_CHARS = [string]([Math]::Max(2000, $freeTokenUsable * 2))
    }
    if ($Model) { $env:FREETOKEN_MODEL = $Model }
    Set-LesOllamaEmbeddings
  }
  "lemonade" {
    $env:LEMONADE_BASE_URL = if ($env:LEMONADE_BASE_URL) { $env:LEMONADE_BASE_URL } else { "http://127.0.0.1:13305/api/v1" }
    $env:LEMONADE_API_KEY = if ($env:LEMONADE_API_KEY) { $env:LEMONADE_API_KEY } else { "lemonade" }
    $env:LEMONADE_HOST_PORT = "$LemonadeHostPort"
    if ($Model) { $env:LEMONADE_MODEL = $Model }
  }
}

$lemonadeHost = $null
if (($Mode -ne "ui") -and ($Provider -eq "lemonade")) {
  if ($PSBoundParameters.ContainsKey("LemonadeHostPort")) {
    Stop-LesPortProcess -Port $LemonadeHostPort
  } elseif (-not (Test-LesPortFree -Port $LemonadeHostPort)) {
    $LemonadeHostPort = Get-LesFreePort -StartPort ($LemonadeHostPort + 1) -Reserved @($ProxyPort, $UiPort)
    $env:LEMONADE_HOST_PORT = "$LemonadeHostPort"
    $env:MLX_URL = "http://127.0.0.1:$LemonadeHostPort"
  }
  $lemonadeHostArgs = @("lemonade_host.py")
  $lemonadeHostOut = Join-Path $Root "logs\windows-light-lemonade-host.out.log"
  $lemonadeHostErr = Join-Path $Root "logs\windows-light-lemonade-host.err.log"
  $lemonadeHost = Start-LesPythonProcess -PythonArgs $lemonadeHostArgs -StdOut $lemonadeHostOut -StdErr $lemonadeHostErr
  $lemonadeHealth = Wait-LesHttp "http://127.0.0.1:$LemonadeHostPort/api/health" 25
  if ($null -eq $lemonadeHealth) {
    Write-Warning "Lemonade adapter did not answer /api/health within startup timeout."
  }
}

$proxy = $null
$proxyErr = $null
if ($Mode -ne "ui") {
  $proxyArgs = @("-m", "uvicorn", "proxy_server:app", "--host", "127.0.0.1", "--port", "$ProxyPort")
  $proxyOut = Join-Path $Root "logs\windows-light-proxy.out.log"
  $proxyErr = Join-Path $Root "logs\windows-light-proxy.err.log"
  $proxy = Start-LesPythonProcess -PythonArgs $proxyArgs -StdOut $proxyOut -StdErr $proxyErr
}

$ui = $null
if ($Mode -ne "backend") {
  $env:SOVUSHKA_UI_PORT = "$UiPort"
  $uiArgs = @("sovushka_ng.py")
  $uiOut = Join-Path $Root "logs\windows-light-ui.out.log"
  $uiErr = Join-Path $Root "logs\windows-light-ui.err.log"
  $ui = Start-LesPythonProcess -PythonArgs $uiArgs -StdOut $uiOut -StdErr $uiErr
}

$health = $null
if ($proxy) {
  $health = Wait-LesHttp "http://127.0.0.1:$ProxyPort/api/health" 45
  if ($null -eq $health) {
    $health = @{ status = "error"; detail = "proxy did not answer /api/health within startup timeout" }
  }
} elseif ($ui) {
  $health = Wait-LesHttp "http://127.0.0.1:$UiPort/healthz" 30
}

$payload = [pscustomobject]@{
  status = "started"
  mode = $Mode
  provider = $Provider
  proxy_port = if ($proxy) { $ProxyPort } else { $null }
  ui_port = if ($ui) { $UiPort } else { $null }
  qdrant_url = $env:QDRANT_URL
  mlx_url = $env:MLX_URL
  lemonade_adapter_url = if ($lemonadeHost) { "http://127.0.0.1:$LemonadeHostPort" } else { $null }
  proxy_url = $env:PROXY_URL
  ui_url = if ($ui) { "http://127.0.0.1:$UiPort/les" } else { $null }
  ui_health_url = if ($ui) { "http://127.0.0.1:$UiPort/healthz" } else { $null }
  dynamic_ports = (($Mode -ne "ui") -and (-not $ProxyPortExplicit)) -or (($Mode -ne "backend") -and (-not $UiPortExplicit))
  lemonade_host_pid = if ($lemonadeHost) { $lemonadeHost.Id } else { $null }
  proxy_pid = if ($proxy) { $proxy.Id } else { $null }
  ui_pid = if ($ui) { $ui.Id } else { $null }
  lemonade_host_alive = if ($lemonadeHost) { -not $lemonadeHost.HasExited } else { $null }
  proxy_alive = if ($proxy) { -not $proxy.HasExited } else { $null }
  ui_alive = if ($ui) { -not $ui.HasExited } else { $null }
  lemonade_host_log = if ($lemonadeHost) { $lemonadeHostErr } else { $null }
  proxy_log = $proxyErr
  ui_log = if ($ui) { $uiErr } else { $null }
  health = $health
  state_root = if ($StateRoot) { $StateRoot } else { $Root.Path }
  process_contract = "direct_python_no_console_v1"
  python_executable = $LesPython
}

$statePath = Join-Path $Root "logs\windows-light-state.json"
$payload | ConvertTo-Json -Depth 8 | Set-Content -Path $statePath -Encoding utf8
$payload | ConvertTo-Json -Depth 8
