param(
  [Parameter(Mandatory = $true)][string]$Version,
  [Parameter(Mandatory = $true)][int]$BuildNumber,
  [Parameter(Mandatory = $true)][string]$BuildCommit,
  [string]$RepoRoot = "C:\Users\Oleg\les_rag",
  [string]$CacheRoot = ""
)

# Convert an already prepared immutable installer into the canonical hard-update
# job. All mutation, smoke and rollback belong to windows_update_engine.py.
$ErrorActionPreference = "Stop"
if (-not $CacheRoot) {
  $CacheRoot = Join-Path $env:LOCALAPPDATA "LES\update-cache\bundles\$BuildCommit"
}
$PreparedPath = Join-Path $CacheRoot "manifest.json"
if (-not (Test-Path -LiteralPath $PreparedPath)) {
  throw "Prepared update manifest is missing: $PreparedPath"
}
$Prepared = Get-Content -LiteralPath $PreparedPath -Raw | ConvertFrom-Json
if (
  $Prepared.schema -ne "les.windows.prepared-update.v1" -or
  $Prepared.status -ne "prepared" -or
  $Prepared.product_version -ne $Version -or
  [int]$Prepared.build_number -ne $BuildNumber -or
  $Prepared.commit -ne $BuildCommit
) {
  throw "Prepared update identity does not match requested release"
}
$Installer = [string]$Prepared.installer
if (-not (Test-Path -LiteralPath $Installer)) { throw "Prepared installer is missing" }
$Sha = (Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash.ToLowerInvariant()
if ($Sha -ne [string]$Prepared.sha256) { throw "Prepared installer checksum mismatch" }

$StateRoot = Join-Path $env:LOCALAPPDATA "LES"
$StatusPath = Join-Path $StateRoot "artifacts\updates\hard-update-status.json"
$JobPath = Join-Path $CacheRoot "hard-update-job.json"
[ordered]@{
  schema = "les.windows-hard-update.v1"
  update_id = "prepared-$Version-$BuildNumber"
  installer = $Installer
  installer_sha256 = $Sha
  install_root = (Join-Path $env:LOCALAPPDATA "Programs\LES")
  state_root = $StateRoot
  status_path = $StatusPath
  product_version = $Version
  build_number = $BuildNumber
  desktop_version = [string]$Prepared.desktop_version
  target_commit = $BuildCommit
  branch = "codex/sovushka-ui-kit"
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $JobPath -Encoding utf8

& (Join-Path $RepoRoot "tools\windows_production_deploy.ps1") -Job $JobPath
if ($LASTEXITCODE -ne 0) { throw "Hard update transaction failed" }
Get-Content -LiteralPath $StatusPath -Raw
