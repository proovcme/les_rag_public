param(
  [Parameter(Mandatory = $true)]
  [string]$Job
)

# Historical entrypoint; retained as a thin alias so old shortcuts cannot enter
# the retired PowerShell transaction.
$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "windows_production_deploy.ps1") -Job $Job
exit $LASTEXITCODE
