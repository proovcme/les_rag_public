param(
  [string]$RepoRoot = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding

if (-not $RepoRoot) {
  $RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
}
$Contract = Get-Content -LiteralPath (Join-Path $RepoRoot "config\version.json") -Raw |
  ConvertFrom-Json
$Commit = (& git -C $RepoRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $Commit -notmatch "^[0-9a-f]{40}$") {
  throw "Windows release requires an exact Git commit"
}
$Branch = (& git -C $RepoRoot rev-parse --abbrev-ref HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or -not $Branch -or $Branch -eq "HEAD") {
  throw "Windows release requires a named branch"
}
$UseLocalCheckout = $Branch.StartsWith("codex/", [System.StringComparison]::OrdinalIgnoreCase)

& (Join-Path $PSScriptRoot "windows_patch_release.ps1") `
  -Version $Contract.product_version `
  -BuildNumber $Contract.build_number `
  -BuildCommit $Commit `
  -Branch $Branch `
  -RepoRoot $RepoRoot `
  -UseLocalCheckout:$UseLocalCheckout
exit $LASTEXITCODE
