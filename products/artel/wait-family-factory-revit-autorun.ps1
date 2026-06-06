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
    [int]$RevitTimeoutSec = 420,
    [int]$WaitTimeoutSec = 1800,
    [int]$WaitPollSec = 10,
    [switch]$KeepExistingReports
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$autorunScript = Join-Path $scriptRoot "run-family-factory-revit-autorun.ps1"
if (-not (Test-Path $autorunScript)) {
    throw "ARTEL autorun script not found: $autorunScript"
}

$startedAt = Get-Date
$deadline = $startedAt.AddSeconds($WaitTimeoutSec)
$attempts = 0
$lastStatus = "unknown"

while ((Get-Date) -lt $deadline) {
    $attempts += 1
    if (Get-Process LogonUI -ErrorAction SilentlyContinue) {
        $lastStatus = "locked"
        Start-Sleep -Seconds $WaitPollSec
        continue
    }
    $lastStatus = "interactive"
    break
}

if ($lastStatus -ne "interactive") {
    [ordered]@{
        status = "locked_timeout"
        startedAt = $startedAt.ToString("o")
        attempts = $attempts
        waitTimeoutSec = $WaitTimeoutSec
        waitPollSec = $WaitPollSec
        familyPath = $FamilyPath
        message = "Windows desktop did not become interactive before timeout."
    } | ConvertTo-Json -Depth 4
    exit 2
}

$arguments = @{
    FamilyPath = $FamilyPath
    RevitInstallDir = $RevitInstallDir
    ArtelBaseUrl = $ArtelBaseUrl
    TaskId = $TaskId
    ApiKey = $ApiKey
    RequiredSharedParameters = $RequiredSharedParameters
    RunFlexTest = $RunFlexTest
    RunLoadTest = $RunLoadTest
    RequireProjectChecks = $RequireProjectChecks
    ExitRevit = $ExitRevit
    TimeoutSec = $RevitTimeoutSec
}
if ($KeepExistingReports) {
    $arguments["KeepExistingReports"] = $true
}

$raw = & $autorunScript @arguments
$exitCode = $LASTEXITCODE
$autorun = $null
try {
    $rawText = ($raw | Out-String).Trim()
    if ($rawText) {
        $autorun = $rawText | ConvertFrom-Json
    }
} catch {
    $autorun = $null
}

[ordered]@{
    status = if ($exitCode -eq 0) { "ok" } else { "autorun_failed" }
    startedAt = $startedAt.ToString("o")
    attempts = $attempts
    waitedSec = [Math]::Round(((Get-Date) - $startedAt).TotalSeconds, 1)
    familyPath = $FamilyPath
    autorun = $autorun
    autorunRaw = if ($autorun) { $null } else { $raw }
    exitCode = $exitCode
} | ConvertTo-Json -Depth 8

exit $exitCode
