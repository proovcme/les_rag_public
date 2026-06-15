param(
    [Parameter(Mandatory = $true)]
    [string]$PlanPath,

    [Parameter(Mandatory = $true)]
    [string]$TemplatePath,

    [string]$SharedParamsFile = "",
    [string]$SaveRfa = "",
    [string]$RevitInstallDir = "C:\Program Files\Autodesk\Revit 2025",
    [bool]$ExitRevit = $true,
    [int]$TimeoutSec = 420,
    [switch]$SkipLockScreenCheck,
    [switch]$KeepExistingReports
)

$ErrorActionPreference = "Stop"

$revitExe = Join-Path $RevitInstallDir "Revit.exe"
if (-not (Test-Path $revitExe)) { throw "Revit.exe not found: $revitExe" }
if (-not (Test-Path $PlanPath)) { throw "PlanPath not found: $PlanPath" }
if (-not (Test-Path $TemplatePath)) { throw "TemplatePath not found: $TemplatePath" }

if (-not $SkipLockScreenCheck -and (Get-Process LogonUI -ErrorAction SilentlyContinue)) {
    throw "Windows desktop appears locked (LogonUI.exe). Unlock Legion before the ARTEL generate autorun."
}

$reportDir = Join-Path $env:APPDATA "ARTEL\family_factory"
New-Item -ItemType Directory -Path $reportDir -Force | Out-Null
if (-not $KeepExistingReports) {
    Remove-Item (Join-Path $reportDir "generate_autorun*.json") -Force -ErrorAction SilentlyContinue
}
$startedAt = Get-Date

$env:ARTEL_AUTORUN_GENERATE_PLAN = (Resolve-Path $PlanPath).Path
$env:ARTEL_AUTORUN_TEMPLATE = (Resolve-Path $TemplatePath).Path
$env:ARTEL_SHARED_PARAMS_FILE = if ($SharedParamsFile) { (Resolve-Path $SharedParamsFile).Path } else { "" }
$env:ARTEL_AUTORUN_SAVE_RFA = $SaveRfa
$env:ARTEL_AUTORUN_EXIT = if ($ExitRevit) { "true" } else { "false" }

$process = Start-Process -FilePath $revitExe -PassThru
$deadline = (Get-Date).AddSeconds($TimeoutSec)
$report = $null
$errorReport = $null

while ((Get-Date) -lt $deadline) {
    $report = Get-ChildItem $reportDir -Filter "generate_autorun_*.json" -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -ge $startedAt -and $_.Name -notlike "generate_autorun_error_*" } |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    $errorReport = Get-ChildItem $reportDir -Filter "generate_autorun_error_*.json" -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -ge $startedAt } |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($report -or $errorReport) { break }
    Start-Sleep -Seconds 5
}

$result = [ordered]@{
    status = if ($report) { "ok" } elseif ($errorReport) { "error" } else { "timeout" }
    planPath = $env:ARTEL_AUTORUN_GENERATE_PLAN
    template = $env:ARTEL_AUTORUN_TEMPLATE
    revitExe = $revitExe
    processId = $process.Id
    generateReport = if ($report) { $report.FullName } else { $null }
    autorunError = if ($errorReport) { $errorReport.FullName } else { $null }
    savedRfa = $env:ARTEL_AUTORUN_SAVE_RFA
    timeoutSec = $TimeoutSec
}
$result | ConvertTo-Json -Depth 4

if (-not $report) { exit 1 }
