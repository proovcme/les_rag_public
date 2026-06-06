param(
    [Parameter(Mandatory = $true)]
    [string]$FamilyPath,

    [string]$RevitInstallDir = "C:\Program Files\Autodesk\Revit 2025",
    [string]$ArtelBaseUrl = "",
    [string]$TaskId = "",
    [string]$ApiKey = "",
    [string]$RequiredSharedParameters = "ADSK_Наименование",
    [bool]$RunFlexTest = $true,
    [bool]$RunLoadTest = $false,
    [bool]$RequireProjectChecks = $true,
    [bool]$ExitRevit = $true,
    [int]$TimeoutSec = 420,
    [switch]$SkipLockScreenCheck,
    [switch]$KeepExistingReports
)

$ErrorActionPreference = "Stop"

function Set-BoolEnv([string]$Name, [bool]$Value) {
    if ($Value) {
        Set-Item -Path "Env:$Name" -Value "true"
    } else {
        Set-Item -Path "Env:$Name" -Value "false"
    }
}

$revitExe = Join-Path $RevitInstallDir "Revit.exe"
if (-not (Test-Path $revitExe)) {
    throw "Revit.exe not found: $revitExe"
}

if (-not $SkipLockScreenCheck -and (Get-Process LogonUI -ErrorAction SilentlyContinue)) {
    throw "Windows desktop appears locked: LogonUI.exe is running. Unlock Legion before ARTEL Revit autorun smoke."
}

$resolvedFamilyPath = (Resolve-Path $FamilyPath).Path
if (-not (Test-Path $resolvedFamilyPath)) {
    throw "FamilyPath not found: $FamilyPath"
}

$reportDir = Join-Path $env:APPDATA "ARTEL\family_factory"
if (-not $KeepExistingReports) {
    Remove-Item -Recurse -Force $reportDir -ErrorAction SilentlyContinue
}
New-Item -ItemType Directory -Path $reportDir -Force | Out-Null
$startedAt = Get-Date

Set-Item -Path Env:ARTEL_AUTORUN_VALIDATE_PATH -Value $resolvedFamilyPath
Set-BoolEnv -Name ARTEL_AUTORUN_EXIT -Value $ExitRevit
Set-Item -Path Env:ARTEL_BASE_URL -Value $ArtelBaseUrl
Set-Item -Path Env:ARTEL_TASK_ID -Value $TaskId
Set-Item -Path Env:ARTEL_API_KEY -Value $ApiKey
Set-Item -Path Env:ARTEL_REQUIRED_SHARED_PARAMETERS -Value $RequiredSharedParameters
Set-BoolEnv -Name ARTEL_RUN_FLEX_TEST -Value $RunFlexTest
Set-BoolEnv -Name ARTEL_RUN_LOAD_TEST -Value $RunLoadTest
Set-BoolEnv -Name ARTEL_REQUIRE_PROJECT_CHECKS -Value $RequireProjectChecks

$process = Start-Process -FilePath $revitExe -PassThru
$deadline = (Get-Date).AddSeconds($TimeoutSec)
$report = $null
$errorReport = $null

while ((Get-Date) -lt $deadline) {
    $report = Get-ChildItem $reportDir -Filter "validation_*.json" -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -ge $startedAt } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    $errorReport = Get-ChildItem $reportDir -Filter "autorun_error_*.json" -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -ge $startedAt } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1

    if ($report -or $errorReport) {
        break
    }

    Start-Sleep -Seconds 5
}

$result = [ordered]@{
    status = if ($report) { "ok" } elseif ($errorReport) { "error" } else { "timeout" }
    familyPath = $resolvedFamilyPath
    revitExe = $revitExe
    processId = $process.Id
    reportDir = $reportDir
    validationReport = if ($report) { $report.FullName } else { $null }
    autorunError = if ($errorReport) { $errorReport.FullName } else { $null }
    timeoutSec = $TimeoutSec
}

$result | ConvertTo-Json -Depth 4

if (-not $report) {
    exit 1
}
