#Requires -Version 5.1
# Start LES for local smeta test: Ollama + Qdrant + start-light.
# Forces reranker onto CUDA (fixes NPU default instability).
# ASCII-only messages: Windows PowerShell 5.1 .ps1 encoding is fragile with Cyrillic.
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location -LiteralPath $Root

$QdrantExe = Join-Path $Root "tools\bin\qdrant.exe"
$QdrantCfg = Join-Path $Root "config\qdrant.local.yaml"
$CudaEnv = Join-Path $Root "config\local\windows-cuda.env"
$StopLight = Join-Path $Root "installers\windows\stop-light.ps1"
$StartLight = Join-Path $Root "installers\windows\start-light.ps1"
$LogDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Root "data\qdrant") | Out-Null
# Default until windows-cuda.env is imported below.
$Model = if ($env:LES_OLLAMA_MODEL) { $env:LES_OLLAMA_MODEL } else { "qwen2.5:14b-instruct-q4_K_M" }

function Test-PortOpen([int]$Port) {
  $client = $null
  try {
    $client = New-Object System.Net.Sockets.TcpClient
    $iar = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
    $ok = $iar.AsyncWaitHandle.WaitOne(400)
    if (-not $ok) { return $false }
    $client.EndConnect($iar) | Out-Null
    return $client.Connected
  } catch {
    return $false
  } finally {
    if ($client) { $client.Close() }
  }
}

function Test-OllamaApi {
  try {
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/tags" -UseBasicParsing -TimeoutSec 3
    if ($resp.StatusCode -ne 200) { return $false }
    $null = $resp.Content | ConvertFrom-Json
    return $true
  } catch {
    return $false
  }
}

function Test-LesQdrantApi {
  # LES native Qdrant has open /collections. Docker ODS often returns 401.
  try {
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:6333/collections" -UseBasicParsing -TimeoutSec 3
    return ($resp.StatusCode -eq 200)
  } catch {
    $msg = $_.Exception.Message
    if ($msg -match "401|Unauthorized") { return $false }
    return $false
  }
}

function Import-LesEnvFile([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path)) { return }
  Get-Content -LiteralPath $Path -Encoding UTF8 | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#")) { return }
    $parts = $line -split "=", 2
    if ($parts.Count -ne 2) { return }
    $key = $parts[0].Trim()
    $val = $parts[1].Trim().Trim('"').Trim("'")
    if ($key) { Set-Item -Path "Env:$key" -Value $val }
  }
}

Write-Host "=== LES START ===" -ForegroundColor Cyan
Write-Host "Root: $Root"
Write-Host "Model: $Model"

if (-not (Test-Path -LiteralPath $StartLight)) {
  throw "LES start script not found: $StartLight"
}
if (-not (Test-Path -LiteralPath $QdrantCfg)) {
  throw "Missing $QdrantCfg"
}

Import-LesEnvFile $CudaEnv
# Re-resolve after windows-cuda.env so LES_OLLAMA_MODEL / OLLAMA_MODEL stick.
$Model = if ($env:LES_OLLAMA_MODEL) {
  $env:LES_OLLAMA_MODEL
} elseif ($env:OLLAMA_MODEL) {
  $env:OLLAMA_MODEL
} else {
  "qwen2.5:14b-instruct-q4_K_M"
}
$env:LES_OLLAMA_MODEL = $Model
$env:OLLAMA_MODEL = $Model
if (-not $env:LES_SMETA_QWEN_MODEL) { $env:LES_SMETA_QWEN_MODEL = $Model }
$env:RERANK_DEVICE = "cuda"
$env:RERANKER_ENABLED = "true"
$env:RERANKER_BACKEND = "sentence_transformers"
if (-not $env:RERANK_MODEL) { $env:RERANK_MODEL = "BAAI/bge-reranker-v2-m3" }
Write-Host "Model (resolved): $Model"
Write-Host "RERANK_DEVICE=$($env:RERANK_DEVICE) RERANKER_BACKEND=$($env:RERANKER_BACKEND)"

try {
  $gpu = & nvidia-smi --query-gpu=name --format=csv,noheader 2>$null
  if ($gpu) {
    Write-Host ("GPU: " + (($gpu | Select-Object -First 1).ToString().Trim())) -ForegroundColor Green
  } else {
    Write-Host "WARN: nvidia-smi found no GPU; reranker may fall back" -ForegroundColor Yellow
  }
} catch {
  Write-Host "WARN: nvidia-smi unavailable" -ForegroundColor Yellow
}

# Restart LES-owned proxy/UI on canonical ports before bootstrap.
if (Test-Path -LiteralPath $StopLight) {
  Write-Host "Stopping previous LES-owned stack..."
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $StopLight -ProxyPort 8050 -UiPort 8051
  if ($LASTEXITCODE -ne 0) {
    throw "LES stop before start failed with exit code $LASTEXITCODE"
  }
}

# 1) Ollama
$ollamaCmd = Get-Command ollama -ErrorAction SilentlyContinue
$ollamaExe = $null
if ($ollamaCmd) {
  $ollamaExe = $ollamaCmd.Source
} else {
  $candidate = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
  if (Test-Path -LiteralPath $candidate) { $ollamaExe = $candidate }
}

if (-not (Test-PortOpen 11434)) {
  Write-Host "Starting Ollama..."
  $ollamaApp = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama app.exe"
  if (Test-Path -LiteralPath $ollamaApp) {
    Start-Process -FilePath $ollamaApp | Out-Null
  } elseif ($ollamaExe) {
    Start-Process -FilePath $ollamaExe -ArgumentList "serve" -WindowStyle Hidden | Out-Null
  } else {
    throw "Ollama not found. Install Ollama and models bge-m3 + $Model"
  }
  $deadline = (Get-Date).AddMinutes(2)
  while (-not (Test-PortOpen 11434)) {
    if ((Get-Date) -gt $deadline) { throw "Ollama did not start on :11434" }
    Start-Sleep 2
  }
} else {
  Write-Host "Port :11434 already open; checking Ollama API..."
}

if (-not (Test-OllamaApi)) {
  throw @"
Port :11434 is not a real Ollama /api/tags endpoint.
Another stack (often Docker ods-llama-server / llama.cpp) stole the port.
Preferred fix (keep both stacks): remap ODS host ports, then re-run LES START:
  powershell -File scripts\windows\configure-ods-coexist.ps1
That moves ODS llama -> :21134 and ODS Qdrant -> :26333 (LES keeps :11434/:6333).
Quick temporary fix: docker stop ods-llama-server
"@
}
Write-Host "Ollama API OK on :11434"

try {
  if ($ollamaExe) {
    $have = & $ollamaExe list 2>$null
    $haveText = ($have | Out-String)
    foreach ($m in @("bge-m3", $Model)) {
      $needle = ($m -split ":")[0]
      if ($haveText -notmatch [regex]::Escape($needle)) {
        Write-Host "Pulling model $m ..."
        & $ollamaExe pull $m
      }
    }
  }
} catch {
  Write-Host "WARN: could not verify Ollama models: $($_.Exception.Message)" -ForegroundColor Yellow
}

# 2) Qdrant (native tools\bin\qdrant.exe — Docker optional, not required here)
if (-not (Test-PortOpen 6333)) {
  if (-not (Test-Path -LiteralPath $QdrantExe)) { throw "Missing $QdrantExe" }
  Write-Host "Starting Qdrant..."
  $qOut = Join-Path $LogDir "qdrant.out.log"
  $qErr = Join-Path $LogDir "qdrant.err.log"
  Start-Process -FilePath $QdrantExe -ArgumentList @("--config-path", $QdrantCfg) `
    -WorkingDirectory $Root -RedirectStandardOutput $qOut -RedirectStandardError $qErr -WindowStyle Hidden | Out-Null
  $deadline = (Get-Date).AddMinutes(1)
  while (-not (Test-PortOpen 6333)) {
    if ((Get-Date) -gt $deadline) { throw "Qdrant did not start on :6333 (see logs\qdrant.*.log)" }
    Start-Sleep 1
  }
} else {
  Write-Host "Port :6333 already open; checking LES Qdrant API..."
}

if (-not (Test-LesQdrantApi)) {
  throw @"
Port :6333 is not an open LES Qdrant /collections endpoint.
Another stack (often Docker ods-qdrant with API key) stole the port.
Preferred fix (keep both stacks): remap ODS host ports, then re-run LES START:
  powershell -File scripts\windows\configure-ods-coexist.ps1
That moves ODS Qdrant -> :26333/:26334 (LES keeps :6333/:6334).
Quick temporary fix: docker stop ods-qdrant
"@
}
Write-Host "Qdrant API OK on :6333"

# 3) LES proxy/UI on fixed 8050/8051 (do not drift to free ports).
# Do NOT capture start-light stdout/stderr: pythonw children inherit redirected
# pipes and the parent then waits forever for EOF after a successful start.
Write-Host "Starting LES (start-light)..."
$startProc = Start-Process -FilePath "powershell.exe" `
  -ArgumentList @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $StartLight,
    "-Provider", "ollama",
    "-Model", $Model,
    "-ProxyPort", "8050",
    "-UiPort", "8051"
  ) `
  -WorkingDirectory $Root `
  -WindowStyle Hidden `
  -PassThru

$deadline = (Get-Date).AddMinutes(2)
$ready = $false
while ((Get-Date) -lt $deadline) {
  if ($startProc.HasExited -and $startProc.ExitCode -ne 0) {
    throw "start-light failed with exit code $($startProc.ExitCode)"
  }
  if ((Test-PortOpen 8050) -and (Test-PortOpen 8051) -and (Test-PortOpen 6333)) {
    try {
      $resp = Invoke-WebRequest -Uri "http://127.0.0.1:8050/api/version" -UseBasicParsing -TimeoutSec 3
      if ($resp.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
  }
  Start-Sleep 1
}
if (-not $ready) {
  throw "LES did not become ready on :8050/:8051/:6333 within timeout"
}

Write-Host ""
Write-Host "=== READY ===" -ForegroundColor Green
Write-Host "UI:      http://127.0.0.1:8051/les"
Write-Host "API:     http://127.0.0.1:8050"
Write-Host "Qdrant:  http://127.0.0.1:6333"
Write-Host "Ollama:  http://127.0.0.1:11434"
Write-Host "RERANK_DEVICE=cuda"
Write-Host ""
Write-Host "Smeta test: Smety -> attach VOR/PDF -> ask to build LSR"
Write-Host "Stop: desktop LES STOP.bat"
try {
  Start-Process "http://127.0.0.1:8051/les"
} catch {
  # ignore browser open failures
}
