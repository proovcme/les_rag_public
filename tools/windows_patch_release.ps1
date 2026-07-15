param(
  [Parameter(Mandatory = $true)]
  [string]$Version,
  [Parameter(Mandatory = $true)]
  [int]$BuildNumber,
  [Parameter(Mandatory = $true)]
  [string]$BuildCommit,
  [string]$Branch = "main",
  [string]$RepoRoot = "C:\Users\Oleg\les_rag",
  [string]$SmetaBaselineArchive = "",
  [string]$InstallRoot = "",
  [string]$StateRoot = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
if (-not $InstallRoot) {
  $InstallRoot = Join-Path $env:LOCALAPPDATA "LES-release-smoke\app"
}
if (-not $StateRoot) {
  $StateRoot = Join-Path $env:LOCALAPPDATA "LES-release-smoke\state"
}
$AllowedRoot = [System.IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "LES-release-smoke"))
$InstallRoot = [System.IO.Path]::GetFullPath($InstallRoot)
$StateRoot = [System.IO.Path]::GetFullPath($StateRoot)
if (-not $InstallRoot.StartsWith($AllowedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
  throw "InstallRoot must stay under $AllowedRoot"
}
if (-not $StateRoot.StartsWith($AllowedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
  throw "StateRoot must stay under $AllowedRoot"
}

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

try {
  Set-Location $RepoRoot
  $dirty = (& git status --porcelain) -join "`n"
  if ($dirty) { throw "Legion checkout is dirty before build:`n$dirty" }

  Invoke-Checked "git" @("fetch", "origin", "${Branch}:refs/remotes/origin/${Branch}")
  & git show-ref --verify --quiet "refs/heads/$Branch"
  if ($LASTEXITCODE -eq 0) {
    Invoke-Checked "git" @("checkout", $Branch)
  } else {
    # A clean release host may still be checked out on the previous feature
    # branch. Create the canonical local branch from the fetched remote.
    Invoke-Checked "git" @("checkout", "-b", $Branch, "refs/remotes/origin/$Branch")
  }
  Invoke-Checked "git" @("pull", "--ff-only", "origin", $Branch)
  $head = (& git rev-parse HEAD).Trim()
  if ($head -ne $BuildCommit) {
    throw "Legion HEAD $head does not match requested build commit $BuildCommit"
  }
  if (-not $SmetaBaselineArchive) {
    $SmetaBaselineArchive = Join-Path $RepoRoot "dist\LES-smeta-baseline.zip"
  }
  if (-not (Test-Path -LiteralPath $SmetaBaselineArchive)) {
    throw "Verified smeta baseline archive was not provided: $SmetaBaselineArchive"
  }
  $env:LES_SMETA_BASELINE_ARCHIVE = $SmetaBaselineArchive

  Invoke-Checked "uv" @(
    "run", "python", "tools/build_windows_installer.py",
    "--version", $Version,
    "--build-number", [string]$BuildNumber
  )
  $Installer = Join-Path $RepoRoot "dist\LES-Setup.exe"
  if (-not (Test-Path -LiteralPath $Installer)) { throw "Installer was not built: $Installer" }

  foreach ($path in @($InstallRoot, $StateRoot)) {
    if (Test-Path -LiteralPath $path) {
      Remove-Item -LiteralPath $path -Recurse -Force
    }
  }
  New-Item -ItemType Directory -Force -Path $InstallRoot, $StateRoot | Out-Null
  $install = Start-Process -FilePath $Installer -ArgumentList @("/S", "/D=$InstallRoot") -Wait -PassThru
  if ($install.ExitCode -ne 0) { throw "NSIS install failed with exit code $($install.ExitCode)" }

  $RuntimeRoot = @(
    (Join-Path $InstallRoot "runtime"),
    (Join-Path $InstallRoot "resources\runtime")
  ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
  if (-not $RuntimeRoot) { throw "Installed runtime was not found under $InstallRoot" }

  $ForbiddenArtel = @(
    (Join-Path $RuntimeRoot "products\artel"),
    (Join-Path $RuntimeRoot "schema\artel_family_manifest.schema.json"),
    (Join-Path $RuntimeRoot "golden\artel_family_manifest_golden.json"),
    (Join-Path $RuntimeRoot "examples\artel")
  ) | Where-Object { Test-Path -LiteralPath $_ }
  $ForbiddenArtel += @(
    Get-ChildItem -LiteralPath (Join-Path $RuntimeRoot "tools") -Filter "*artel*.py" -ErrorAction SilentlyContinue
    Get-ChildItem -LiteralPath (Join-Path $RuntimeRoot "tests") -Filter "test_artel*.py" -ErrorAction SilentlyContinue
  ) | ForEach-Object { $_.FullName }
  if ($ForbiddenArtel.Count -gt 0) {
    throw "ARTEL must not be bundled in the LES release runtime: $($ForbiddenArtel -join ', ')"
  }

  Invoke-Checked "powershell.exe" @(
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
    (Join-Path $RepoRoot "tools\windows_release_smoke.ps1"),
    "-RuntimeRoot", $RuntimeRoot,
    "-StateRoot", $StateRoot,
    "-ExpectedVersion", $Version
  )

  $SmokeReport = Join-Path $StateRoot "logs\release-smoke.json"
  $smoke = Get-Content -LiteralPath $SmokeReport -Raw | ConvertFrom-Json
  if (-not $smoke.ok) { throw "Live Windows smoke did not pass" }

  # Only a clean isolated smoke may advance to the actual Legion production
  # state. The production gate installs in-place, starts the persistent runtime
  # and proves the four real heavy project PDFs through dense+sparse RRF.
  Invoke-Checked "powershell.exe" @(
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
    (Join-Path $RepoRoot "tools\windows_production_deploy.ps1"),
    "-Installer", $Installer,
    "-ExpectedVersion", $Version
  )
  $ProductionReport = Join-Path $env:LOCALAPPDATA "LES\logs\production-deploy.json"
  if (-not (Test-Path -LiteralPath $ProductionReport)) {
    throw "Production deploy report was not created: $ProductionReport"
  }
  $production = Get-Content -LiteralPath $ProductionReport -Raw | ConvertFrom-Json
  if (-not $production.ok) { throw "Production Legion deploy did not pass" }

  $sha = (Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash.ToLowerInvariant()
  $Checksum = Join-Path $RepoRoot "dist\LES-Setup.exe.sha256"
  [System.IO.File]::WriteAllText($Checksum, "$sha  LES-Setup.exe`n", [System.Text.Encoding]::ASCII)
  $summary = [ordered]@{
    schema = "les.windows.patch-release.v1"
    product_version = $Version
    build_number = $BuildNumber
    desktop_version = "5.1.$BuildNumber"
    build_commit = $BuildCommit
    installer = $Installer
    bytes = (Get-Item -LiteralPath $Installer).Length
    sha256 = $sha
    runtime_root = $RuntimeRoot
    state_root = $StateRoot
    smoke = $smoke
    production = $production
  }
  $SummaryPath = Join-Path $RepoRoot "dist\windows-patch-release.json"
  $summary | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $SummaryPath -Encoding UTF8
  $summary | ConvertTo-Json -Depth 12
} finally {
  Restore-BuildTree
  $remaining = (& git -C $RepoRoot status --porcelain) -join "`n"
  if ($remaining) {
    Write-Error "Legion checkout is not clean after build:`n$remaining"
  }
}
