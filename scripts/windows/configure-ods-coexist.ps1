#Requires -Version 5.1
# Remap ODS host-published ports away from LES defaults so both stacks can run.
# LES keeps: Ollama :11434, Qdrant :6333/:6334
# ODS host:  llama-server :21134, Qdrant :26333/:26334
# Internal ODS Docker DNS (llama-server / qdrant) is unchanged.
# ASCII-only: Windows PowerShell 5.1 encoding is fragile with Cyrillic.
$ErrorActionPreference = "Stop"

$OdsHome = if ($env:ODS_HOME) { $env:ODS_HOME } else { Join-Path $env:USERPROFILE "ods" }
$EnvFile = Join-Path $OdsHome ".env"
$OdsCli = Join-Path $OdsHome "ods.ps1"

$Wanted = @{
  "OLLAMA_PORT"       = "21134"
  "QDRANT_PORT"       = "26333"
  "QDRANT_GRPC_PORT"  = "26334"
}

if (-not (Test-Path -LiteralPath $EnvFile)) {
  throw "ODS .env not found: $EnvFile (set ODS_HOME if install is elsewhere)"
}

Write-Host "=== LES + ODS port coexist ===" -ForegroundColor Cyan
Write-Host "ODS home: $OdsHome"
Write-Host "Patching host ports in .env (Docker-internal URLs stay the same)..."

$lines = Get-Content -LiteralPath $EnvFile -Encoding UTF8
$seen = @{}
$out = foreach ($line in $lines) {
  if ($line -match '^\s*#') { $line; continue }
  if ($line -match '^\s*$') { $line; continue }
  $parts = $line -split "=", 2
  if ($parts.Count -ne 2) { $line; continue }
  $key = $parts[0].Trim()
  if ($Wanted.ContainsKey($key)) {
    $seen[$key] = $true
    "{0}={1}" -f $key, $Wanted[$key]
  } else {
    $line
  }
}
foreach ($key in $Wanted.Keys) {
  if (-not $seen.ContainsKey($key)) {
    $out += ("{0}={1}" -f $key, $Wanted[$key])
  }
}

$marker = "# LES coexist: host ports remapped (Ollama/LES :11434, Qdrant/LES :6333)"
$joined = ($out -join "`n")
if ($joined -notmatch [regex]::Escape("LES coexist")) {
  $insert = @(
    "",
    $marker,
    "# ODS host LLM :21134, ODS host Qdrant :26333/:26334",
    "# Apply via: scripts\windows\configure-ods-coexist.ps1"
  ) -join "`n"
  # Place marker near Ports section when present.
  if ($joined -match "(?m)^#=== Ports ===") {
    $joined = [regex]::Replace($joined, "(?m)^#=== Ports ===", ("#=== Ports ===`n" + $insert), 1)
  } else {
    $joined = $joined + "`n" + $insert + "`n"
  }
}

$backup = Join-Path $OdsHome (".env.les-coexist.bak-{0:yyyyMMdd-HHmmss}" -f (Get-Date))
Copy-Item -LiteralPath $EnvFile -Destination $backup -Force
Set-Content -LiteralPath $EnvFile -Value $joined -Encoding UTF8 -NoNewline
Add-Content -LiteralPath $EnvFile -Value "`n" -Encoding UTF8
Write-Host "Backup: $backup"
Write-Host ("ODS host ports -> LLM :{0}  Qdrant :{1}/:{2}" -f $Wanted.OLLAMA_PORT, $Wanted.QDRANT_PORT, $Wanted.QDRANT_GRPC_PORT)

$recreate = $true
if ($args -contains "-NoRecreate") { $recreate = $false }

if ($recreate) {
  if (-not (Test-Path -LiteralPath $OdsCli)) {
    Write-Host "WARN: ods.ps1 not found; recreate manually:" -ForegroundColor Yellow
    Write-Host "  cd $OdsHome"
    Write-Host "  .\ods.ps1 up -d --force-recreate llama-server qdrant"
    Write-Host "  (or: .\ods.ps1 restart llama-server ; .\ods.ps1 restart qdrant)"
    exit 0
  }
  Write-Host "Recreating ODS llama-server + qdrant with new host binds..."
  Push-Location -LiteralPath $OdsHome
  try {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $OdsCli restart llama-server
    if ($LASTEXITCODE -ne 0) { throw "ods.ps1 restart llama-server failed: $LASTEXITCODE" }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $OdsCli restart qdrant
    if ($LASTEXITCODE -ne 0) { throw "ods.ps1 restart qdrant failed: $LASTEXITCODE" }
  } finally {
    Pop-Location
  }
}

Write-Host ""
Write-Host "Done. Expected map:" -ForegroundColor Green
Write-Host "  LES  Ollama     http://127.0.0.1:11434"
Write-Host "  LES  Qdrant     http://127.0.0.1:6333"
Write-Host ("  ODS  llama.cpp  http://127.0.0.1:{0}" -f $Wanted.OLLAMA_PORT)
Write-Host ("  ODS  Qdrant     http://127.0.0.1:{0}" -f $Wanted.QDRANT_PORT)
Write-Host "Note: both GPU models can still fight for VRAM; unload one when running heavy LES LSR."
