param(
  [Parameter(Mandatory = $true)]
  [string]$TargetCommit,
  [Parameter(Mandatory = $true)]
  [string]$Version,
  [Parameter(Mandatory = $true)]
  [int]$BuildNumber,
  [Parameter(Mandatory = $true)]
  [string]$BaselineArchive,
  [string]$Branch = "codex/sovushka-ui-kit",
  [string]$RepoRoot = "C:\Users\Oleg\les_rag",
  [string]$InstallRoot = "",
  [string]$StateRoot = "",
  [switch]$ReuseBuiltInstaller
)

# One-time bridge from updater v1 to v2. This intentionally does not run pytest,
# an isolated clean install, baseline rebuild, model inference or a RAG query.
# The existing transactional production deploy owns backup and rollback.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
if (-not $InstallRoot) { $InstallRoot = Join-Path $env:LOCALAPPDATA "Programs\LES" }
if (-not $StateRoot) { $StateRoot = Join-Path $env:LOCALAPPDATA "LES" }
$RepoRoot = [System.IO.Path]::GetFullPath($RepoRoot)
$InstallRoot = [System.IO.Path]::GetFullPath($InstallRoot)
$StateRoot = [System.IO.Path]::GetFullPath($StateRoot)
$LogRoot = Join-Path $StateRoot "logs\bootstrap-updater-v2"
$ReportPath = Join-Path $StateRoot "artifacts\updates\bootstrap-updater-v2.json"
$GeneratedPaths = @(
  "desktop/tauri/package-lock.json",
  "desktop/tauri/src-tauri/Cargo.lock",
  "desktop/tauri/src-tauri/Cargo.toml",
  "desktop/tauri/src-tauri/gen/schemas/desktop-schema.json",
  "desktop/tauri/src-tauri/tauri.conf.json"
)
$WindowsSchema = Join-Path $RepoRoot "desktop\tauri\src-tauri\gen\schemas\windows-schema.json"
New-Item -ItemType Directory -Force -Path $LogRoot, (Split-Path -Parent $ReportPath) | Out-Null
$started = Get-Date
$result = [ordered]@{
  schema = "les.windows-bootstrap-updater-v2.v1"
  ok = $false
  stage = "preflight"
  target_commit = $TargetCommit
  product_version = $Version
  build_number = $BuildNumber
  branch = $Branch
  baseline_transferred = $false
  heavy_tests_run = $false
  installer_published = $false
  user_data_untouched = $true
}

function Invoke-Native(
  [string]$File,
  [string[]]$Arguments,
  [string]$Name,
  [string]$WorkingDirectory,
  [int]$TimeoutSeconds = 1800
) {
  $stdout = Join-Path $LogRoot "$Name.out.log"
  $stderr = Join-Path $LogRoot "$Name.err.log"
  Remove-Item $stdout, $stderr -Force -ErrorAction SilentlyContinue
  function ConvertTo-NativeArgument([AllowEmptyString()][string]$Value) {
    if ($Value.Length -gt 0 -and $Value -notmatch '[\s"]') { return $Value }
    $builder = New-Object System.Text.StringBuilder
    [void]$builder.Append('"')
    $backslashes = 0
    foreach ($character in $Value.ToCharArray()) {
      if ($character -eq [char]'\') {
        $backslashes += 1
      } elseif ($character -eq [char]'"') {
        [void]$builder.Append([char]'\', (2 * $backslashes) + 1)
        [void]$builder.Append([char]'"')
        $backslashes = 0
      } else {
        if ($backslashes) { [void]$builder.Append([char]'\', $backslashes) }
        [void]$builder.Append($character)
        $backslashes = 0
      }
    }
    if ($backslashes) { [void]$builder.Append([char]'\', 2 * $backslashes) }
    [void]$builder.Append('"')
    return $builder.ToString()
  }
  $startInfo = New-Object System.Diagnostics.ProcessStartInfo
  $startInfo.FileName = $File
  $startInfo.Arguments = (($Arguments | ForEach-Object {
    ConvertTo-NativeArgument ([string]$_)
  }) -join " ")
  $startInfo.WorkingDirectory = $WorkingDirectory
  $startInfo.UseShellExecute = $false
  $startInfo.CreateNoWindow = $true
  $startInfo.RedirectStandardOutput = $true
  $startInfo.RedirectStandardError = $true
  $process = New-Object System.Diagnostics.Process
  $process.StartInfo = $startInfo
  if (-not $process.Start()) { throw "$Name could not be started" }
  $stdoutTask = $process.StandardOutput.ReadToEndAsync()
  $stderrTask = $process.StandardError.ReadToEndAsync()
  if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
    & (Join-Path $env:SystemRoot "System32\taskkill.exe") `
      /PID $process.Id /T /F *> $null
    throw "$Name timed out after $TimeoutSeconds seconds"
  }
  $process.WaitForExit()
  $standardOutput = [string]$stdoutTask.Result
  $standardError = [string]$stderrTask.Result
  [System.IO.File]::WriteAllText(
    $stdout, $standardOutput, (New-Object System.Text.UTF8Encoding($false))
  )
  [System.IO.File]::WriteAllText(
    $stderr, $standardError, (New-Object System.Text.UTF8Encoding($false))
  )
  $exitCode = [int]$process.ExitCode
  if ($exitCode -ne 0) {
    $tail = @()
    if (Test-Path -LiteralPath $stdout) { $tail += Get-Content -LiteralPath $stdout -Tail 12 }
    if (Test-Path -LiteralPath $stderr) { $tail += Get-Content -LiteralPath $stderr -Tail 12 }
    throw "$Name failed ($exitCode): $(($tail -join ' | ').Trim())"
  }
  return [ordered]@{
    exit_code = $exitCode
    stdout = $stdout
    stderr = $stderr
  }
}

function Restore-BuildTree {
  try { & git -C $RepoRoot restore -- $GeneratedPaths | Out-Null } catch { }
  Remove-Item -LiteralPath $WindowsSchema -Force -ErrorAction SilentlyContinue
}

function Get-RuntimeRoot {
  return @(
    (Join-Path $InstallRoot "resources\runtime"),
    (Join-Path $InstallRoot "runtime")
  ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}

function Write-DeployStamp([string]$RuntimeRoot) {
  $stamp = [ordered]@{
    product_version = $Version
    build_number = $BuildNumber
    desktop_version = "5.1.$BuildNumber"
    les_version = $Version
    app_version = $Version
    deployed_commit = $TargetCommit
    deployed_branch = $Branch
    deployed_at = [DateTime]::UtcNow.ToString("o")
    deployed_by = "legion-bootstrap-updater-v2"
    deploy_method = "transactional_bootstrap_installer"
    notes = @(
      "one-time updater v1 to v2 bootstrap",
      "no pytest, isolated RAG smoke, baseline rebuild or publication"
    )
  }
  $path = Join-Path $RuntimeRoot ".les_deploy_stamp.json"
  $temporary = "$path.tmp"
  [System.IO.File]::WriteAllText(
    $temporary,
    ($stamp | ConvertTo-Json -Depth 8),
    (New-Object System.Text.UTF8Encoding($false))
  )
  Move-Item -LiteralPath $temporary -Destination $path -Force
}

function Test-ShortRuntime([string]$RuntimeRoot) {
  $version = Invoke-RestMethod -Uri "http://127.0.0.1:8050/api/version" -TimeoutSec 15
  $health = Invoke-RestMethod -Uri "http://127.0.0.1:8050/api/health" -TimeoutSec 15
  $ui = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8051/healthz" -TimeoutSec 15
  if ([string]$version.product_version -ne $Version) {
    throw "short smoke product version mismatch: $($version.product_version)"
  }
  if ([int]$version.build_number -ne $BuildNumber) {
    throw "short smoke build mismatch: $($version.build_number)"
  }
  $actualCommit = [string]$version.deployed_commit
  if ($actualCommit.Length -lt 8 -or
      -not ($TargetCommit.StartsWith($actualCommit) -or $actualCommit.StartsWith($TargetCommit.Substring(0, 8)))) {
    throw "short smoke commit mismatch: $actualCommit"
  }
  if ([int]$ui.StatusCode -ne 200) { throw "short smoke UI is not ready" }
  if (-not [bool]$health.rag.index_contract.compatible) {
    throw "short smoke index contract is incompatible"
  }
  $runtimeStatePath = Join-Path $StateRoot "logs\windows-light-state.json"
  if (-not (Test-Path -LiteralPath $runtimeStatePath)) {
    throw "short smoke runtime process state is missing"
  }
  $runtimeState = Get-Content -LiteralPath $runtimeStatePath -Raw | ConvertFrom-Json
  if ($runtimeState.process_contract -ne "direct_python_no_console_v1") {
    throw "short smoke process contract is not console-clean"
  }
  $pids = @($runtimeState.proxy_pid, $runtimeState.ui_pid) |
    Where-Object { $_ -and [int]$_ -gt 0 }
  if ($pids.Count -ne 2) { throw "short smoke requires proxy and UI direct PID" }
  $names = @()
  foreach ($runtimePid in $pids) {
    $process = Get-CimInstance Win32_Process -Filter ("ProcessId=" + [int]$runtimePid) `
      -ErrorAction SilentlyContinue
    if (-not $process) { throw "short smoke runtime PID $runtimePid disappeared" }
    if ([string]$process.Name -notin @("python.exe", "pythonw.exe")) {
      throw "short smoke unexpected runtime launcher: $($process.Name)"
    }
    $names += [string]$process.Name
  }
  $wrappers = @(Get-CimInstance Win32_Process | Where-Object {
    ([string]$_.Name -eq "cmd.exe") -and
    (([string]$_.CommandLine) -match "proxy_server:app|sovushka_ng\.py|lemonade_host\.py")
  })
  if ($wrappers.Count -ne 0) { throw "short smoke found $($wrappers.Count) LES cmd.exe wrappers" }
  $desktops = @(Get-Process -Name "les-desktop" -ErrorAction SilentlyContinue |
    Where-Object { $_.SessionId -ne 0 })
  if ($desktops.Count -ne 1) {
    throw "short smoke expected one interactive desktop, got $($desktops.Count)"
  }
  $installedSchema = Select-String -LiteralPath `
    (Join-Path $RuntimeRoot "proxy\services\update_service.py") `
    -Pattern 'VPS_PATCH_SCHEMA = "les.vps-patch.v2"' -SimpleMatch
  if (-not $installedSchema) { throw "installed runtime does not contain updater v2" }
  return [ordered]@{
    product_version = [string]$version.product_version
    build_number = [int]$version.build_number
    deployed_commit = $actualCommit
    index_contract_compatible = $true
    runtime_processes = $names
    cmd_wrappers = 0
    desktop_count = 1
    updater_schema = "les.vps-patch.v2"
  }
}

try {
  if (-not (Test-Path -LiteralPath $RepoRoot)) { throw "Legion repo is missing: $RepoRoot" }
  if (-not (Test-Path -LiteralPath $InstallRoot)) { throw "LES install is missing: $InstallRoot" }
  if (-not (Test-Path -LiteralPath $BaselineArchive)) {
    throw "cached baseline is missing: $BaselineArchive"
  }
  if ($TargetCommit -notmatch '^[0-9a-f]{40}$') { throw "TargetCommit must be a full SHA" }
  if ($Branch -notmatch '^codex/[A-Za-z0-9._/-]+$') { throw "unsafe branch name" }
  $git = (Get-Command git).Source
  $uv = (Get-Command uv).Source
  $dirty = (& $git -C $RepoRoot status --porcelain) -join "`n"
  if ($dirty) { throw "Legion checkout is dirty before bootstrap: $dirty" }

  $result.stage = "checkout"
  Invoke-Native $git @(
    "-C", $RepoRoot, "fetch", "origin",
    "+${Branch}:refs/remotes/origin/${Branch}"
  ) "git-fetch" $RepoRoot | Out-Null
  $remote = (& $git -C $RepoRoot rev-parse "refs/remotes/origin/$Branch").Trim()
  if ($remote -ne $TargetCommit) {
    throw "origin/$Branch is $remote, expected exact $TargetCommit"
  }
  Invoke-Native $git @(
    "-C", $RepoRoot, "checkout", "-B", $Branch, "refs/remotes/origin/$Branch"
  ) "git-checkout" $RepoRoot | Out-Null
  $head = (& $git -C $RepoRoot rev-parse HEAD).Trim()
  if ($head -ne $TargetCommit) { throw "Legion HEAD mismatch after checkout: $head" }

  $contract = Get-Content -LiteralPath (Join-Path $RepoRoot "config\version.json") `
    -Raw | ConvertFrom-Json
  if ([string]$contract.product_version -ne $Version -or
      [int]$contract.build_number -ne $BuildNumber) {
    throw "target version contract does not match requested bootstrap"
  }

  $result.stage = "baseline_verify"
  Invoke-Native $uv @(
    "run", "python", "-m", "tools.smeta_release_baseline",
    "verify", "--archive", $BaselineArchive
  ) "baseline-verify" $RepoRoot | Out-Null
  $result.baseline_sha256 = (
    Get-FileHash -LiteralPath $BaselineArchive -Algorithm SHA256
  ).Hash.ToLowerInvariant()

  $installer = Join-Path $RepoRoot "dist\LES-Setup.exe"
  $result.stage = "installer_build"
  if ($ReuseBuiltInstaller) {
    if (-not (Test-Path -LiteralPath $installer)) {
      throw "requested prebuilt bootstrap installer is missing: $installer"
    }
    $expectedDesktopVersion = "5.1.$BuildNumber"
    $actualDesktopVersion = (Get-Item -LiteralPath $installer).VersionInfo.FileVersion
    if ([string]$actualDesktopVersion -ne $expectedDesktopVersion) {
      throw "prebuilt installer version is $actualDesktopVersion, expected $expectedDesktopVersion"
    }
    $result.installer_reused = $true
  } else {
    $env:LES_SMETA_BASELINE_ARCHIVE = $BaselineArchive
    Invoke-Native $uv @(
      "run", "python", "tools/build_windows_installer.py",
      "--version", $Version, "--build-number", [string]$BuildNumber
    ) "installer-build" $RepoRoot | Out-Null
    $result.installer_reused = $false
  }
  if (-not (Test-Path -LiteralPath $installer)) {
    throw "bootstrap installer was not built: $installer"
  }
  $result.installer = $installer
  $result.installer_bytes = (Get-Item -LiteralPath $installer).Length
  $result.installer_sha256 = (
    Get-FileHash -LiteralPath $installer -Algorithm SHA256
  ).Hash.ToLowerInvariant()

  $result.stage = "transactional_install"
  Invoke-Native "powershell.exe" @(
    "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
    (Join-Path $RepoRoot "tools\windows_transactional_production_deploy.ps1"),
    "-Installer", $installer,
    "-ExpectedVersion", $Version,
    "-InstallRoot", $InstallRoot,
    "-StateRoot", $StateRoot
  ) "transactional-install" $RepoRoot | Out-Null

  $runtimeRoot = Get-RuntimeRoot
  if (-not $runtimeRoot) { throw "installed runtime is missing after bootstrap" }
  Write-DeployStamp $runtimeRoot
  $result.stage = "short_smoke"
  $result.smoke = Test-ShortRuntime $runtimeRoot
  $result.runtime_root = [string]$runtimeRoot
  $result.ok = $true
  $result.stage = "done"
} catch {
  $result.error = $_.Exception.Message
  $result.error_type = $_.Exception.GetType().FullName
} finally {
  Restore-BuildTree
  $result.elapsed_seconds = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)
  $remaining = (& git -C $RepoRoot status --porcelain) -join "`n"
  $result.repo_clean_after = -not [bool]$remaining
  if ($remaining) {
    $result.repo_dirty_after = $remaining
    if ($result.ok) {
      $result.ok = $false
      $result.stage = "cleanup_failed"
      $result.error = "Legion checkout is dirty after bootstrap"
    }
  }
  [System.IO.File]::WriteAllText(
    $ReportPath,
    ($result | ConvertTo-Json -Depth 12),
    (New-Object System.Text.UTF8Encoding($false))
  )
  $result | ConvertTo-Json -Depth 12
}

if (-not $result.ok) { exit 1 }
