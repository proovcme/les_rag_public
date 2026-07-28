# Build/install the classic-Outlook E.ZH.I.K. sidecar and interactive task.
param(
  [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA "LES\bin"),
  [string]$StateRoot = (Join-Path $env:LOCALAPPDATA "LES\mail"),
  [switch]$Probe,
  [switch]$Remove
)
$ErrorActionPreference = "Stop"
$task = "LES E.ZH.I.K. Outlook Collector"

if ($Remove) {
  schtasks /delete /tn $task /f 2>$null
  exit 0
}

$sourceRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
$source = Join-Path $sourceRoot "LesMailPoller.cs"
$compiler = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path -LiteralPath $compiler)) {
  $compiler = "C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe"
}
if (-not (Test-Path -LiteralPath $compiler)) { throw ".NET Framework csc.exe not found" }

New-Item -ItemType Directory -Force -Path $InstallRoot, $StateRoot | Out-Null
$target = Join-Path $InstallRoot "LesMailPoller.exe"
& $compiler /nologo /target:winexe /out:"$target" /r:System.dll /r:System.Core.dll /r:Microsoft.CSharp.dll $source
if ($LASTEXITCODE -ne 0) { throw "LesMailPoller compile failed ($LASTEXITCODE)" }

"http://127.0.0.1:8050/api/mail/collector/import" |
  Set-Content -LiteralPath (Join-Path $StateRoot "collector_url.txt") -Encoding ASCII

$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute $target
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive
$settings = New-ScheduledTaskSettingsSet `
  -ExecutionTimeLimit (New-TimeSpan -Seconds 20) `
  -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $task -Action $action -Principal $principal -Settings $settings -Force |
  Out-Null

if ($Probe) {
  & $target --probe
  if ($LASTEXITCODE -ne 0) { throw "Outlook probe failed ($LASTEXITCODE)" }
}

[ordered]@{
  task = $task
  executable = $target
  schedule = "manual"
  interactive_user = $identity
  state_root = $StateRoot
} | ConvertTo-Json -Compress
