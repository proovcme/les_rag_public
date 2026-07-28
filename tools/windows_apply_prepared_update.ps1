param(
  [Parameter(Mandatory = $true)]
  [string]$Version,
  [Parameter(Mandatory = $true)]
  [int]$BuildNumber,
  [Parameter(Mandatory = $true)]
  [string]$BuildCommit,
  [string]$RepoRoot = "C:\Users\Oleg\les_rag",
  [string]$CacheRoot = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
if (-not $CacheRoot) {
  $CacheRoot = Join-Path $env:LOCALAPPDATA "LES\update-cache\bundles\$BuildCommit"
}
$ManifestPath = Join-Path $CacheRoot "manifest.json"
if (-not (Test-Path -LiteralPath $ManifestPath)) {
  throw "Prepared update manifest is missing: $ManifestPath"
}
$prepared = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
$Installer = [string]$prepared.installer
if (
  $prepared.schema -ne "les.windows.prepared-update.v1" -or
  $prepared.status -ne "prepared" -or
  $prepared.product_version -ne $Version -or
  [int]$prepared.build_number -ne $BuildNumber -or
  $prepared.commit -ne $BuildCommit
) {
  throw "Prepared update identity does not match requested release"
}
if (-not (Test-Path -LiteralPath $Installer)) {
  throw "Prepared installer is missing: $Installer"
}
$sha = (Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash.ToLowerInvariant()
if ($sha -ne [string]$prepared.sha256) {
  throw "Prepared installer checksum mismatch"
}

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  (Join-Path $RepoRoot "tools\windows_transactional_production_deploy.ps1") `
  -Installer $Installer -ExpectedVersion $Version
if ($LASTEXITCODE -ne 0) {
  throw "Prepared production apply failed with exit code $LASTEXITCODE"
}
$ProductionReport = Join-Path $env:LOCALAPPDATA "LES\logs\production-deploy.json"
$production = Get-Content -LiteralPath $ProductionReport -Raw | ConvertFrom-Json
if (-not $production.ok) { throw "Prepared production apply is not green" }

$RuntimeRoot = @(
  (Join-Path $env:LOCALAPPDATA "Programs\LES\resources\runtime"),
  (Join-Path $env:LOCALAPPDATA "Programs\LES\runtime")
) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $RuntimeRoot) { throw "Applied Windows runtime is missing" }
$stampCode = @"
from pathlib import Path
from proxy.services.version_service import write_deploy_stamp
write_deploy_stamp(
    dev_root=Path(r"$RepoRoot"),
    runtime_root=Path(r"$RuntimeRoot"),
    deployed_commit="$BuildCommit",
    deployed_branch="codex/audit-rag",
    notes=["prepared internal Windows update"],
)
"@
Push-Location $RepoRoot
try {
  & uv run python -c $stampCode
  if ($LASTEXITCODE -ne 0) { throw "Windows deploy stamp write failed" }
} finally {
  Pop-Location
}

[ordered]@{
  schema = "les.windows.applied-update.v1"
  status = "applied"
  product_version = $Version
  build_number = $BuildNumber
  commit = $BuildCommit
  sha256 = $sha
  cache_hit = $true
  rebuild = $false
  baseline_transfer = $false
  production = $production
} | ConvertTo-Json -Depth 12
