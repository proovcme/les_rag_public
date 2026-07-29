param(
  [Parameter(Mandatory = $true)]
  [string]$Job
)

# Deprecated name kept for operator compatibility. Installer construction is a
# separate build step; installation is always the same Python hard-update job.
$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "windows_production_deploy.ps1") -Job $Job
exit $LASTEXITCODE
