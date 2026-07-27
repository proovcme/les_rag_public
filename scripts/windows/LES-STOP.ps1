#Requires -Version 5.1
# Stop LES API/UI and local Qdrant. ASCII-only for Windows PowerShell 5.1.
$ErrorActionPreference = "SilentlyContinue"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root

Write-Host "=== LES STOP ===" -ForegroundColor Cyan

$stopLight = Join-Path $Root "installers\windows\stop-light.ps1"
if (Test-Path -LiteralPath $stopLight) {
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $stopLight
}

function Stop-Port([int]$Port) {
  Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
    if ($_.OwningProcess -gt 0) {
      Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
      Write-Host "Stopped PID $($_.OwningProcess) on :$Port"
    }
  }
}

Stop-Port 8050
Stop-Port 8051
Stop-Port 6333
Stop-Port 18080

Get-Process -Name "qdrant" -ErrorAction SilentlyContinue | ForEach-Object {
  Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
  Write-Host "Stopped qdrant PID $($_.Id)"
}

Start-Sleep 1
foreach ($p in 8050, 8051, 6333) {
  $up = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
  if ($up) { Write-Host "STILL UP :$p" -ForegroundColor Yellow }
  else { Write-Host "DOWN :$p" -ForegroundColor Green }
}

Write-Host "Ollama left running (shared app)."
Write-Host "=== DONE ==="
pause
