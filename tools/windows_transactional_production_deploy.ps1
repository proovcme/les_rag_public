param(
  [Parameter(Mandatory = $true)]
  [string]$Installer,
  [Parameter(Mandatory = $true)]
  [string]$ExpectedVersion,
  [string]$InstallRoot = "",
  [string]$StateRoot = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
if (-not $InstallRoot) { $InstallRoot = Join-Path $env:LOCALAPPDATA "Programs\LES" }
if (-not $StateRoot) { $StateRoot = Join-Path $env:LOCALAPPDATA "LES" }
$InstallRoot = [System.IO.Path]::GetFullPath($InstallRoot)
$StateRoot = [System.IO.Path]::GetFullPath($StateRoot)
$RecoveryRoot = Join-Path $StateRoot "recovery"
$BackupRoot = Join-Path $RecoveryRoot ("audit-rag-" + (Get-Date -Format "yyyyMMddTHHmmss"))
$ReportPath = Join-Path $StateRoot "logs\production-deploy.json"
New-Item -ItemType Directory -Force -Path $RecoveryRoot | Out-Null

if (-not (Test-Path -LiteralPath $InstallRoot)) { throw "Current LES install not found: $InstallRoot" }

$PreviousVersion = ""
$PreviousBuildNumber = 0
$PreviousCommit = ""
try {
  $previousApi = Invoke-RestMethod -Uri "http://127.0.0.1:8050/api/version" -TimeoutSec 5
  $PreviousVersion = [string]$previousApi.les_version
  $PreviousBuildNumber = [int]$previousApi.build_number
  $PreviousCommit = [string]$(if ($previousApi.deployed_commit) {
    $previousApi.deployed_commit
  } else {
    $previousApi.git_commit
  })
} catch {
  # The isolated clean-install smoke intentionally stops 8050/8051 before the
  # production transaction. The installed code contract remains authoritative
  # for selecting the rollback target while the old runtime is offline.
  $installedVersionPath = Join-Path $InstallRoot "runtime\config\version.json"
  if (-not (Test-Path -LiteralPath $installedVersionPath)) {
    throw "Previous LES API is offline and installed version contract is missing: $installedVersionPath"
  }
  $installedVersion = Get-Content -LiteralPath $installedVersionPath -Raw | ConvertFrom-Json
  $PreviousVersion = [string]$installedVersion.product_version
  $PreviousBuildNumber = [int]$installedVersion.build_number

  $installedStampPath = Join-Path $InstallRoot "runtime\.les_deploy_stamp.json"
  if (Test-Path -LiteralPath $installedStampPath) {
    $installedStamp = Get-Content -LiteralPath $installedStampPath -Raw | ConvertFrom-Json
    $PreviousCommit = [string]$installedStamp.deployed_commit
  }
}
if (-not $PreviousVersion -or $PreviousBuildNumber -le 0) {
  throw "Previous LES identity is unavailable; transactional deploy refused"
}
& robocopy.exe $InstallRoot $BackupRoot /E /COPY:DAT /DCOPY:DAT /XJ `
  /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) {
  throw "Application backup failed with robocopy exit code $LASTEXITCODE"
}

$ProductionScript = Join-Path $PSScriptRoot "windows_production_deploy.ps1"
$RollbackScript = Join-Path $PSScriptRoot "windows_production_rollback.ps1"
try {
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ProductionScript `
    -Installer $Installer -ExpectedVersion $ExpectedVersion `
    -InstallRoot $InstallRoot -StateRoot $StateRoot
  if ($LASTEXITCODE -ne 0) { throw "Production deploy failed with exit code $LASTEXITCODE" }

  $report = Get-Content -LiteralPath $ReportPath -Raw | ConvertFrom-Json
  if (-not $report.ok) { throw "Production deploy report is not green" }
  $report | Add-Member -NotePropertyName rollback -NotePropertyValue ([ordered]@{
    available = $true
    backup_root = $BackupRoot
    previous_version = $PreviousVersion
    previous_build_number = $PreviousBuildNumber
    previous_commit = $PreviousCommit
    data_untouched = $true
  }) -Force
  $report | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $ReportPath -Encoding UTF8
} catch {
  $deployError = $_.Exception.Message
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $RollbackScript `
    -BackupRoot $BackupRoot -ExpectedVersion $PreviousVersion `
    -InstallRoot $InstallRoot -StateRoot $StateRoot
  if ($LASTEXITCODE -ne 0) {
    throw "$deployError; automatic rollback also failed"
  }
  if (Test-Path -LiteralPath $ReportPath) {
    $failedReport = Get-Content -LiteralPath $ReportPath -Raw | ConvertFrom-Json
    $failedReport | Add-Member -NotePropertyName rollback -NotePropertyValue ([ordered]@{
      available = $true
      backup_root = $BackupRoot
      previous_version = $PreviousVersion
      previous_build_number = $PreviousBuildNumber
      previous_commit = $PreviousCommit
      data_untouched = $true
      auto_restored = $true
    }) -Force
    $failedReport | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $ReportPath -Encoding UTF8
  }
  throw "$deployError; previous application restored"
}
