param(
  [int]$ProxyPort = 8050,
  [int]$UiPort = 8051
)

# Stop the LES windows-light stack started by start-light.ps1 by terminating the
# processes listening on the proxy and UI ports. Qdrant (Docker, if used) is left
# running on purpose — it is cheap to keep and holds the vector store.
$ErrorActionPreference = "SilentlyContinue"

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

Write-Host "LES windows-light stopped (proxy:$ProxyPort ui:$UiPort)."
