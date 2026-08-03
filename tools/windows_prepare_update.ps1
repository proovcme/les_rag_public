param(
  [Parameter(Mandatory = $true)]
  [string]$Version,
  [Parameter(Mandatory = $true)]
  [int]$BuildNumber,
  [Parameter(Mandatory = $true)]
  [string]$BuildCommit,
  [string]$RepoRoot = "C:\Users\Oleg\les_rag",
  [Parameter(Mandatory = $true)]
  [string]$SmetaBaselineArchive,
  [string]$CacheRoot = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
if (-not $CacheRoot) {
  $CacheRoot = Join-Path $env:LOCALAPPDATA "LES\update-cache\bundles\$BuildCommit"
}
$CacheRoot = [System.IO.Path]::GetFullPath($CacheRoot)
$ManifestPath = Join-Path $CacheRoot "manifest.json"
$CachedInstaller = Join-Path $CacheRoot "LES-Setup.exe"
$GeneratedPaths = @(
  "desktop/tauri/package-lock.json",
  "desktop/tauri/src-tauri/Cargo.lock",
  "desktop/tauri/src-tauri/Cargo.toml",
  "desktop/tauri/src-tauri/gen/schemas/desktop-schema.json",
  "desktop/tauri/src-tauri/tauri.conf.json"
)
$WindowsSchema = Join-Path $RepoRoot "desktop\tauri\src-tauri\gen\schemas\windows-schema.json"

function Invoke-Checked([string]$Program, [string[]]$Arguments) {
  & $Program @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "$Program failed with exit code $LASTEXITCODE"
  }
}

function Restore-BuildTree {
  try { & git -C $RepoRoot restore -- $GeneratedPaths | Out-Null } catch { }
  Remove-Item -LiteralPath $WindowsSchema -Force -ErrorAction SilentlyContinue
}

function Read-PreparedUpdate {
  if (-not (Test-Path -LiteralPath $ManifestPath) -or
      -not (Test-Path -LiteralPath $CachedInstaller)) {
    return $null
  }
  try {
    $prepared = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
    $sha = (Get-FileHash -LiteralPath $CachedInstaller -Algorithm SHA256).Hash.ToLowerInvariant()
    if (
      $prepared.schema -eq "les.windows.prepared-update.v1" -and
      $prepared.status -eq "prepared" -and
      $prepared.product_version -eq $Version -and
      [int]$prepared.build_number -eq $BuildNumber -and
      $prepared.commit -eq $BuildCommit -and
      $prepared.sha256 -eq $sha
    ) {
      $prepared.cache_hit = $true
      return $prepared
    }
  } catch { }
  return $null
}

$cached = Read-PreparedUpdate
if ($cached) {
  $cached | ConvertTo-Json -Depth 12
  exit 0
}

try {
  Set-Location $RepoRoot
  $dirty = (& git status --porcelain) -join "`n"
  if ($dirty) { throw "Legion checkout is dirty before prepare:`n$dirty" }
  $head = (& git rev-parse HEAD).Trim()
  if ($head -ne $BuildCommit) {
    throw "Legion HEAD $head does not match requested commit $BuildCommit"
  }
  if (-not (Test-Path -LiteralPath $SmetaBaselineArchive)) {
    throw "Verified smeta baseline is missing: $SmetaBaselineArchive"
  }
  $env:LES_SMETA_BASELINE_ARCHIVE = $SmetaBaselineArchive

  Invoke-Checked "uv" @(
    "run", "python", "tools/build_windows_installer.py",
    "--version", $Version,
    "--build-number", [string]$BuildNumber
  )
  $Installer = Join-Path $RepoRoot "dist\LES-Setup.exe"
  if (-not (Test-Path -LiteralPath $Installer)) {
    throw "Installer was not built: $Installer"
  }

  # Keep the clean-install contour inside the checkout-owned temporary root.
  # A previous elevated/installer-owned LOCALAPPDATA contour can carry ACLs
  # that the next prepare cannot remove, even though it is not production.
  $SmokeRoot = Join-Path $RepoRoot ".codex_tmp\windows-release-smoke\$BuildCommit"
  $InstallRoot = Join-Path $SmokeRoot "app"
  $StateRoot = Join-Path $SmokeRoot "state"
  foreach ($path in @($InstallRoot, $StateRoot)) {
    if (Test-Path -LiteralPath $path) {
      Remove-Item -LiteralPath $path -Recurse -Force
    }
  }
  New-Item -ItemType Directory -Force -Path $InstallRoot, $StateRoot | Out-Null
  $env:LES_RELEASE_SMOKE = "1"
  $env:LES_WINDOWS_STATE_ROOT = $StateRoot
  $install = Start-Process -FilePath $Installer -ArgumentList @("/S", "/D=$InstallRoot") -Wait -PassThru
  if ($install.ExitCode -ne 0) { throw "NSIS clean install failed: $($install.ExitCode)" }
  $RuntimeRoot = @(
    (Join-Path $InstallRoot "runtime"),
    (Join-Path $InstallRoot "resources\runtime")
  ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
  if (-not $RuntimeRoot) { throw "Prepared runtime is missing under $InstallRoot" }

  Invoke-Checked "powershell.exe" @(
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
    (Join-Path $RepoRoot "tools\windows_release_smoke.ps1"),
    "-RuntimeRoot", $RuntimeRoot,
    "-StateRoot", $StateRoot,
    "-ExpectedVersion", $Version
  )
  $SmokeReport = Join-Path $StateRoot "logs\release-smoke.json"
  $smoke = Get-Content -LiteralPath $SmokeReport -Raw | ConvertFrom-Json
  if (-not $smoke.ok) { throw "Prepared Windows smoke is not green" }

  $sha = (Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash.ToLowerInvariant()
  New-Item -ItemType Directory -Force -Path $CacheRoot | Out-Null
  $temporaryInstaller = "$CachedInstaller.tmp"
  Copy-Item -LiteralPath $Installer -Destination $temporaryInstaller -Force
  Move-Item -LiteralPath $temporaryInstaller -Destination $CachedInstaller -Force
  $prepared = [ordered]@{
    schema = "les.windows.prepared-update.v1"
    status = "prepared"
    product_version = $Version
    build_number = $BuildNumber
    desktop_version = "5.1.$BuildNumber"
    commit = $BuildCommit
    installer = $CachedInstaller
    bytes = (Get-Item -LiteralPath $CachedInstaller).Length
    sha256 = $sha
    baseline_sha256 = (Get-FileHash -LiteralPath $SmetaBaselineArchive -Algorithm SHA256).Hash.ToLowerInvariant()
    smoke = $smoke
    prepared_at = [DateTime]::UtcNow.ToString("o")
    cache_hit = $false
  }
  $temporaryManifest = "$ManifestPath.tmp"
  [System.IO.File]::WriteAllText(
    $temporaryManifest,
    ($prepared | ConvertTo-Json -Depth 12),
    (New-Object System.Text.UTF8Encoding($false))
  )
  Move-Item -LiteralPath $temporaryManifest -Destination $ManifestPath -Force
  $prepared | ConvertTo-Json -Depth 12
} finally {
  Restore-BuildTree
  $remaining = (& git -C $RepoRoot status --porcelain) -join "`n"
  if ($remaining) {
    Write-Error "Legion checkout is not clean after prepare:`n$remaining"
  }
}
