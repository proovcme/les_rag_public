param(
  [Parameter(Mandatory = $true)]
  [string]$BackupRoot,
  [Parameter(Mandatory = $true)]
  [string]$ExpectedVersion,
  [string]$InstallRoot = "",
  [string]$StateRoot = "",
  [int]$TimeoutSeconds = 300
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
if (-not $InstallRoot) { $InstallRoot = Join-Path $env:LOCALAPPDATA "Programs\LES" }
if (-not $StateRoot) { $StateRoot = Join-Path $env:LOCALAPPDATA "LES" }
$InstallRoot = [System.IO.Path]::GetFullPath($InstallRoot)
$StateRoot = [System.IO.Path]::GetFullPath($StateRoot)
$BackupRoot = [System.IO.Path]::GetFullPath($BackupRoot)
$AllowedBackupRoot = [System.IO.Path]::GetFullPath((Join-Path $StateRoot "recovery"))
if (-not $BackupRoot.StartsWith($AllowedBackupRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
  throw "Rollback backup must stay under $AllowedBackupRoot"
}
if (-not (Test-Path -LiteralPath $BackupRoot)) { throw "Rollback backup not found: $BackupRoot" }
. (Join-Path $PSScriptRoot "..\installers\windows\runtime-process.ps1")

function Stop-LesApplication {
  try {
    Get-CimInstance Win32_Process | Where-Object {
      $_.ExecutablePath -and
      $_.ExecutablePath.StartsWith($InstallRoot, [System.StringComparison]::OrdinalIgnoreCase)
    } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  } catch { }
  foreach ($port in @(8050, 8051, 8052, 8053)) {
    foreach ($listenerPid in @(Get-LesListeningProcessIds $port)) {
      if ($listenerPid -gt 0) {
        $process = Get-CimInstance Win32_Process -Filter ("ProcessId=" + [int]$listenerPid) `
          -ErrorAction SilentlyContinue
        $executable = [string]$process.ExecutablePath
        $commandLine = [string]$process.CommandLine
        $isLes = (
          $executable.StartsWith($InstallRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
          $executable.StartsWith($StateRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
          $commandLine -match "proxy_server:app|sovushka_ng\.py"
        )
        if ($isLes) {
          Stop-Process -Id $listenerPid -Force -ErrorAction SilentlyContinue
        }
      }
    }
  }
}

function Start-DesktopInteractive([string]$Desktop) {
  $collectorTask = Get-ScheduledTask -TaskName "LES E.ZH.I.K. Outlook Collector" -ErrorAction SilentlyContinue
  if (-not $collectorTask -or -not $collectorTask.Principal.UserId) {
    throw "Interactive LES user cannot be resolved for rollback"
  }
  $taskName = "LES Audit RAG Rollback Start"
  $action = New-ScheduledTaskAction -Execute $Desktop `
    -WorkingDirectory (Split-Path -Parent $Desktop)
  $principal = New-ScheduledTaskPrincipal -UserId ([string]$collectorTask.Principal.UserId) -LogonType Interactive
  try {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $taskName -Action $action -Principal $principal -Force | Out-Null
    Start-ScheduledTask -TaskName $taskName
  } finally {
    Start-Sleep -Seconds 2
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
  }
}

Stop-LesApplication
if (Test-Path -LiteralPath $InstallRoot) {
  Remove-Item -LiteralPath $InstallRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $InstallRoot) | Out-Null
Copy-Item -LiteralPath $BackupRoot -Destination $InstallRoot -Recurse -Force

$Desktop = Join-Path $InstallRoot "les-desktop.exe"
if (-not (Test-Path -LiteralPath $Desktop)) { throw "Restored desktop not found: $Desktop" }
Start-DesktopInteractive $Desktop

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$fallbackAt = (Get-Date).AddSeconds(60)
$fallbackStarted = $false
do {
  Start-Sleep -Seconds 2
  if (-not $fallbackStarted -and (Get-Date) -ge $fallbackAt) {
    Get-CimInstance Win32_Process | Where-Object {
      ([string]$_.CommandLine) -match "bootstrap\.ps1" -and
      ([string]$_.CommandLine).Contains($InstallRoot)
    } | ForEach-Object {
      Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
    $startLight = Join-Path $InstallRoot "runtime\installers\windows\start-light.ps1"
    $env:LES_WINDOWS_STATE_ROOT = $StateRoot
    Start-Process -FilePath "powershell.exe" -ArgumentList @(
      "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $startLight,
      "-ProxyPort", "8050", "-UiPort", "8051"
    ) -WindowStyle Hidden | Out-Null
    $fallbackStarted = $true
  }
  try {
    $version = Invoke-RestMethod -Uri "http://127.0.0.1:8050/api/version" -TimeoutSec 10
    $ui = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8051/healthz" -TimeoutSec 10
    if ($version.les_version -eq $ExpectedVersion -and [int]$ui.StatusCode -eq 200) {
      [ordered]@{
        ok = $true
        schema = "les.windows.application-rollback.v1"
        restored_version = [string]$version.les_version
        restored_commit = [string]$version.git_commit
        backup_root = $BackupRoot
        service_fallback_used = $fallbackStarted
      } | ConvertTo-Json -Compress
      exit 0
    }
  } catch { }
} while ((Get-Date) -lt $deadline)
throw "Restored LES did not become healthy as $ExpectedVersion"
