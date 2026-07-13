param(
  [Parameter(Mandatory = $true)]
  [string]$Version,
  [Parameter(Mandatory = $true)]
  [int]$BuildNumber,
  [Parameter(Mandatory = $true)]
  [string]$BuildCommit,
  [string]$Branch = "main",
  [string]$RepoRoot = "C:\Users\Oleg\les_rag",
  [string]$InstallRoot = "",
  [string]$StateRoot = ""
)

$ErrorActionPreference = "Stop"
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

  Invoke-Checked "git" @("fetch", "origin", $Branch)
  & git show-ref --verify --quiet "refs/heads/$Branch"
  if ($LASTEXITCODE -eq 0) {
    Invoke-Checked "git" @("checkout", $Branch)
  } else {
    # A clean release host may still be checked out on the previous feature
    # branch. Create the canonical local branch from the fetched remote.
    Invoke-Checked "git" @("checkout", "-b", $Branch, "--track", "origin/$Branch")
  }
  Invoke-Checked "git" @("pull", "--ff-only", "origin", $Branch)
  $head = (& git rev-parse HEAD).Trim()
  if ($head -ne $BuildCommit) {
    throw "Legion HEAD $head does not match requested build commit $BuildCommit"
  }

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
