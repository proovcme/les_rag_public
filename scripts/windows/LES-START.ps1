#Requires -Version 5.1
# Start LES for local smeta test: Ollama + Qdrant + start-light.
# Forces reranker onto CUDA (fixes NPU default instability).
# ASCII-only messages: Windows PowerShell 5.1 .ps1 encoding is fragile with Cyrillic.
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root

$Model = if ($env:LES_OLLAMA_MODEL) { $env:LES_OLLAMA_MODEL } else { "qwen3.5:9b" }
$QdrantExe = Join-Path $Root "tools\bin\qdrant.exe"
$QdrantCfg = Join-Path $Root "config\qdrant.local.yaml"
$CudaEnv = Join-Path $Root "config\local\windows-cuda.env"
$LogDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Test-PortOpen([int]$Port) {
  try {
    $c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return [bool]$c
  } catch {
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

Import-LesEnvFile $CudaEnv
$env:RERANK_DEVICE = "cuda"
$env:RERANKER_ENABLED = "true"
$env:RERANKER_BACKEND = "sentence_transformers"
if (-not $env:RERANK_MODEL) { $env:RERANK_MODEL = "BAAI/bge-reranker-v2-m3" }
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
  Write-Host "Ollama already on :11434"
}

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

# 2) Qdrant
if (-not (Test-PortOpen 6333)) {
  if (-not (Test-Path -LiteralPath $QdrantExe)) { throw "Missing $QdrantExe" }
  if (-not (Test-Path -LiteralPath $QdrantCfg)) { throw "Missing $QdrantCfg" }
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
  Write-Host "Qdrant already on :6333"
}

# 3) LES
$startLight = Join-Path $Root "installers\windows\start-light.ps1"
Write-Host "Starting LES (start-light)..."
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $startLight -Provider ollama -Model $Model
if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
  throw "start-light failed with exit code $LASTEXITCODE"
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
