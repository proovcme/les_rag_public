param(
  [int]$ProxyPort = 8050,
  [int]$UiPort = 8051,
  [int]$LemonadeHostPort = 18080
)

# Stop the LES windows-light stack started by start-light.ps1 by terminating the
# processes listening on the proxy and UI ports. Qdrant (Docker, if used) is left
# running on purpose — it is cheap to keep and holds the vector store.
$ErrorActionPreference = "SilentlyContinue"
$ProxyPortExplicit = $PSBoundParameters.ContainsKey("ProxyPort")
$UiPortExplicit = $PSBoundParameters.ContainsKey("UiPort")
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

function Stop-LesPortProcess([int]$Port) {
  $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  foreach ($conn in $connections) {
    if ($conn.OwningProcess -gt 0) {
      Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
    }
  }
}

Stop-LesPortProcess -Port $ProxyPort
Stop-LesPortProcess -Port $UiPort
Stop-LesPortProcess -Port $LemonadeHostPort

Write-Host "LES windows-light stopped (proxy:$ProxyPort ui:$UiPort lemonade-adapter:$LemonadeHostPort)."
