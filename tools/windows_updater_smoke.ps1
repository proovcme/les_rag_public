param(
  [Parameter(Mandatory = $true)]
  [string]$ExpectedVersion,
  [Parameter(Mandatory = $true)]
  [int]$ExpectedBuild,
  [Parameter(Mandatory = $true)]
  [string]$ExpectedCommit,
  [string]$StateRoot = "",
  [int]$TimeoutSeconds = 90
)

# Short installed-updater acceptance. No build, pytest, baseline, model or RAG query.
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
if (-not $StateRoot) {
  if (-not $env:LOCALAPPDATA) { throw "LOCALAPPDATA is not set" }
  $StateRoot = Join-Path $env:LOCALAPPDATA "LES"
}
$StateRoot = [System.IO.Path]::GetFullPath($StateRoot)
$UpdateStatusPath = Join-Path $StateRoot "artifacts\updates\vps-patch-status.json"
$RuntimeStatePath = Join-Path $StateRoot "logs\windows-light-state.json"
$ReportPath = Join-Path $StateRoot "artifacts\updates\updater-smoke.json"
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$last = "updater did not become ready"
$result = [ordered]@{
  schema = "les.windows-updater-smoke.v1"
  ok = $false
  expected_version = $ExpectedVersion
  expected_build = $ExpectedBuild
  expected_commit = $ExpectedCommit
  user_data_untouched = $true
  heavy_gates_run = $false
}

try {
  do {
    try {
      if (-not (Test-Path -LiteralPath $UpdateStatusPath)) {
        throw "updater status is missing"
      }
      $update = Get-Content -LiteralPath $UpdateStatusPath -Raw | ConvertFrom-Json
      if ($update.state -eq "failed") {
        throw "updater failed: $($update.stage) $($update.error)"
      }
      if ($update.state -ne "ready") {
        $last = "updater state=$($update.state), stage=$($update.stage)"
        Start-Sleep -Milliseconds 500
        continue
      }

      $version = Invoke-RestMethod -Uri "http://127.0.0.1:8050/api/version" -TimeoutSec 5
      $health = Invoke-RestMethod -Uri "http://127.0.0.1:8050/api/health" -TimeoutSec 5
      $ui = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8051/healthz" -TimeoutSec 5
      if ([string]$version.product_version -ne $ExpectedVersion) {
        throw "product version mismatch: $($version.product_version)"
      }
      if ([int]$version.build_number -ne $ExpectedBuild) {
        throw "build number mismatch: $($version.build_number)"
      }
      $actualCommit = [string]$version.deployed_commit
      if ($ExpectedCommit.Length -lt 8 -or $actualCommit.Length -lt 8 -or
          -not ($ExpectedCommit.StartsWith($actualCommit) -or $actualCommit.StartsWith($ExpectedCommit.Substring(0, 8)))) {
        throw "commit mismatch: $actualCommit"
      }
      if ($ui.StatusCode -ne 200) { throw "UI health failed" }
      if (-not $health.rag.index_contract.compatible) {
        throw "index contract is incompatible"
      }
      if (-not (Test-Path -LiteralPath $RuntimeStatePath)) {
        throw "windows-light-state.json is missing"
      }
      $runtime = Get-Content -LiteralPath $RuntimeStatePath -Raw | ConvertFrom-Json
      if ($runtime.process_contract -ne "direct_python_no_console_v1") {
        throw "runtime process contract is not console-clean"
      }
      $runtimePids = @($runtime.proxy_pid, $runtime.ui_pid, $runtime.lemonade_host_pid) |
        Where-Object { $_ -and [int]$_ -gt 0 }
      $runtimeNames = @()
      foreach ($runtimePid in $runtimePids) {
        $process = Get-CimInstance Win32_Process -Filter ("ProcessId=" + [int]$runtimePid) -ErrorAction SilentlyContinue
        if (-not $process) { throw "runtime process $runtimePid disappeared" }
        if ([string]$process.Name -notin @("python.exe", "pythonw.exe")) {
          throw "runtime process $runtimePid uses launcher $($process.Name)"
        }
        $runtimeNames += [string]$process.Name
      }
      $wrappers = @(Get-CimInstance Win32_Process | Where-Object {
        ([string]$_.Name -eq "cmd.exe") -and
        (([string]$_.CommandLine) -match "proxy_server:app|sovushka_ng\.py|lemonade_host\.py")
      })
      if ($wrappers.Count -ne 0) { throw "LES-owned cmd.exe wrappers: $($wrappers.Count)" }
      $desktops = @(Get-Process -Name "les-desktop" -ErrorAction SilentlyContinue)
      if ($desktops.Count -ne 1) { throw "expected one les-desktop process, got $($desktops.Count)" }

      $result.ok = $true
      $result.update_id = [string]$update.patch_id
      $result.version = [string]$version.product_version
      $result.build = [int]$version.build_number
      $result.commit = $actualCommit
      $result.process_hygiene = [ordered]@{
        contract = [string]$runtime.process_contract
        runtime_processes = $runtimeNames
        cmd_wrappers = 0
        desktop_count = 1
      }
      break
    } catch {
      $last = $_.Exception.Message
      Start-Sleep -Milliseconds 500
    }
  } while ((Get-Date) -lt $deadline)
  if (-not $result.ok) { throw "short updater smoke timed out: $last" }
} catch {
  $result.error = $_.Exception.Message
  throw
} finally {
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ReportPath) | Out-Null
  $result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $ReportPath -Encoding utf8
}

$result | ConvertTo-Json -Depth 8
