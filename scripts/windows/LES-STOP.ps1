#Requires -Version 5.1
# Stop LES API/UI and local native Qdrant. ASCII-only for Windows PowerShell 5.1.
# Proxy/UI: ownership-aware stop-light only. Qdrant: stop local qdrant.exe by name.
$ErrorActionPreference = "Continue"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location -LiteralPath $Root

Write-Host "=== LES STOP ===" -ForegroundColor Cyan

$stopLight = Join-Path $Root "installers\windows\stop-light.ps1"
if (Test-Path -LiteralPath $stopLight) {
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $stopLight -ProxyPort 8050 -UiPort 8051
  if ($LASTEXITCODE -ne 0) {
    Write-Host "WARN: stop-light exit code $LASTEXITCODE" -ForegroundColor Yellow
  }
} else {
  Write-Host "WARN: stop-light.ps1 missing" -ForegroundColor Yellow
}

# Local native Qdrant started by LES-START (tools\bin\qdrant.exe). Do not touch Docker.
Get-Process -Name "qdrant" -ErrorAction SilentlyContinue | ForEach-Object {
  $path = $null
  try { $path = $_.Path } catch { }
  $owned = $false
  if ($path -and ($path -like "*\tools\bin\qdrant.exe")) { $owned = $true }
  if (-not $path) {
    # Path may be unavailable without elevation; still stop by name for desktop helper.
    $owned = $true
  }
  if ($owned) {
    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    Write-Host "Stopped qdrant PID $($_.Id)"
  }
}

function Test-PortOpen([int]$Port) {
  $client = $null
  try {
    $client = New-Object System.Net.Sockets.TcpClient
    $iar = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
    $ok = $iar.AsyncWaitHandle.WaitOne(300)
    if (-not $ok) { return $false }
    $client.EndConnect($iar) | Out-Null
    return $client.Connected
  } catch {
    return $false
  } finally {
    if ($client) { $client.Close() }
  }
}

Start-Sleep 1
foreach ($p in 8050, 8051, 6333) {
  if (Test-PortOpen $p) { Write-Host "STILL UP :$p" -ForegroundColor Yellow }
  else { Write-Host "DOWN :$p" -ForegroundColor Green }
}

Write-Host "Ollama left running (shared app)."
Write-Host "=== DONE ===" -ForegroundColor Green
if ($Host.Name -eq "ConsoleHost" -and [Environment]::UserInteractive) {
  try {
    if (-not [Console]::IsInputRedirected) { pause }
  } catch { }
}
