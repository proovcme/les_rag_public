param(
  [int]$ProxyPort = 8050,
  [int]$UiPort = 8051,
  [int]$LemonadeHostPort = 18080,
  [string]$RuntimeRoot = ""
)

# Stop only a confirmed LES windows-light stack. Foreign owners of 8050/8051 are
# reported, never killed (ALGO-windows-lifecycle foreign_port_owner).
$ErrorActionPreference = "Stop"
$ProxyPortExplicit = $PSBoundParameters.ContainsKey("ProxyPort")
$UiPortExplicit = $PSBoundParameters.ContainsKey("UiPort")
. (Join-Path $PSScriptRoot "runtime-process.ps1")

$StateRoot = if ($env:LES_WINDOWS_STATE_ROOT) {
  [System.IO.Path]::GetFullPath($env:LES_WINDOWS_STATE_ROOT)
} elseif ($env:LOCALAPPDATA) {
  Join-Path $env:LOCALAPPDATA "LES"
} else {
  ""
}
$StatePath = if ($StateRoot) { Join-Path $StateRoot "logs\windows-light-state.json" } else { "" }
if ($StatePath -and (Test-Path -LiteralPath $StatePath)) {
  try {
    $runtimeState = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
    if (-not $ProxyPortExplicit -and $runtimeState.proxy_port) { $ProxyPort = [int]$runtimeState.proxy_port }
    if (-not $UiPortExplicit -and $runtimeState.ui_port) { $UiPort = [int]$runtimeState.ui_port }
  } catch { }
}

if (-not $RuntimeRoot) {
  $RuntimeRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
}

$python = $null
if ($StateRoot) {
  # Lifecycle helpers must be awaited by PowerShell. pythonw.exe is correct
  # for the long-lived UI/proxy, but returns immediately when invoked here.
  foreach ($name in @("python.exe", "pythonw.exe")) {
    $candidate = Join-Path $StateRoot ".venv\Scripts\$name"
    if (Test-Path -LiteralPath $candidate) { $python = $candidate; break }
  }
}
$helper = Join-Path $RuntimeRoot "tools\windows_runtime.py"
if ($python -and (Test-Path -LiteralPath $helper) -and $StateRoot) {
  # PowerShell 5.1 can promote native stderr to NativeCommandError before the
  # real process exit code is inspected. Capture output under Continue, then
  # restore strict script handling and decide exclusively by LASTEXITCODE.
  $previousErrorActionPreference = $ErrorActionPreference
  try {
    $ErrorActionPreference = "Continue"
    $stopOut = @(& $python $helper stop --runtime $RuntimeRoot --state $StateRoot --proxy-port $ProxyPort --ui-port $UiPort 2>&1)
    $stopExitCode = $LASTEXITCODE
  } finally {
    $ErrorActionPreference = $previousErrorActionPreference
  }
  if ($stopExitCode -ne 0) {
    $detail = (($stopOut | ForEach-Object { "$_" }) -join " ").Trim()
    if ($detail -match 'foreign_port_owner') { throw $detail }
    throw "LES runtime stop failed: $detail"
  }
} else {
  Stop-LesConfirmedPortProcess -Port $ProxyPort -RuntimeRoot $RuntimeRoot
  Stop-LesConfirmedPortProcess -Port $UiPort -RuntimeRoot $RuntimeRoot
}

# Lemonade adapter is optional. Stop it only when it is clearly LES-owned; a
# foreign listener on 18080 must not block LES proxy/UI shutdown or startup.
try {
  Stop-LesConfirmedPortProcess -Port $LemonadeHostPort -RuntimeRoot $RuntimeRoot -AllowPatterns @('lemonade_host\.py')
} catch {
  if ("$_" -notmatch 'foreign_port_owner') { throw }
}

Write-Host "LES windows-light stopped (proxy:$ProxyPort ui:$UiPort lemonade-adapter:$LemonadeHostPort)."
