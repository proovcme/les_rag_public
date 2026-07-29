param(
  [Parameter(Mandatory = $true)]
  [string]$Installer,
  [Parameter(Mandatory = $true)]
  [string]$ExpectedVersion,
  [string]$InstallRoot = "",
  [string]$StateRoot = "",
  [int]$BootstrapTimeoutSeconds = 600
)

# Production deployment gate for Legion. It runs only after the isolated
# clean-install release smoke. Persistent LES data and Qdrant are preserved;
# only LES API/UI processes are stopped for the in-place code update.
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
if (-not $InstallRoot) { $InstallRoot = Join-Path $env:LOCALAPPDATA "Programs\LES" }
if (-not $StateRoot) { $StateRoot = Join-Path $env:LOCALAPPDATA "LES" }
$InstallRoot = [System.IO.Path]::GetFullPath($InstallRoot)
$StateRoot = [System.IO.Path]::GetFullPath($StateRoot)
$LogDir = Join-Path $StateRoot "logs"
$ReportPath = Join-Path $LogDir "production-deploy.json"
$StatusPath = Join-Path $LogDir "bootstrap-status.json"
$RuntimeStatePath = Join-Path $LogDir "windows-light-state.json"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
. (Join-Path $PSScriptRoot "..\installers\windows\runtime-process.ps1")

$result = [ordered]@{
  schema = "les_windows_production_deploy_v1"
  ok = $false
  stage = "preflight"
  expected_version = $ExpectedVersion
  install_root = $InstallRoot
  state_root = $StateRoot
  warnings = @()
}
$proxyPort = 0
$oldHealth = $null
$mailTask = $null

function Set-LesEnvValue([string]$Path, [string]$Key, [string]$Value) {
  $lines = if (Test-Path -LiteralPath $Path) { @(Get-Content -LiteralPath $Path) } else { @() }
  $updated = New-Object System.Collections.Generic.List[string]
  $found = $false
  foreach ($line in $lines) {
    if ($line -match "^$([regex]::Escape($Key))=") {
      if (-not $found) { $updated.Add("$Key=$Value") }
      $found = $true
    } else {
      $updated.Add([string]$line)
    }
  }
  if (-not $found) { $updated.Add("$Key=$Value") }
  $tmp = "$Path.tmp"
  [System.IO.File]::WriteAllLines($tmp, $updated, (New-Object System.Text.UTF8Encoding($false)))
  Move-Item -LiteralPath $tmp -Destination $Path -Force
}

function Stop-LesRuntime {
  $existingStop = @(
    (Join-Path $InstallRoot "resources\runtime\installers\windows\stop-light.ps1"),
    (Join-Path $InstallRoot "runtime\installers\windows\stop-light.ps1")
  ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
  if ($existingStop) {
    try {
      $env:LES_WINDOWS_STATE_ROOT = $StateRoot
      & $existingStop | Out-Null
    } catch { }
  }
  try {
    Get-CimInstance Win32_Process | Where-Object {
      $_.ExecutablePath -and
      $_.ExecutablePath.StartsWith($InstallRoot, [System.StringComparison]::OrdinalIgnoreCase)
    } | ForEach-Object {
      Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
  } catch { }
  # A previous dev/reference launch can survive on fallback ports even when
  # the production state file only remembers the canonical pair. Stop only
  # listeners that are demonstrably LES-owned across the complete port set.
  foreach ($port in @(8050, 8051, 8052, 8053)) {
    foreach ($listenerPid in @(Get-LesListeningProcessIds $port)) {
      if ($listenerPid -gt 0) {
        $process = Get-CimInstance Win32_Process -Filter ("ProcessId=" + [int]$listenerPid) `
          -ErrorAction SilentlyContinue
        $executable = [string]$process.ExecutablePath
        $commandLine = [string]$process.CommandLine
        $isLes = (
          $executable.StartsWith($InstallRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
          $executable.StartsWith($StateRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
          $commandLine -match "proxy_server:app|sovushka_ng\.py"
        )
        if ($isLes) {
          Stop-Process -Id $listenerPid -Force -ErrorAction SilentlyContinue
        }
      }
    }
  }
}

function Start-PreparedUpdateRuntime(
  [string]$RuntimeRoot,
  [string]$StateRoot,
  [int]$TimeoutSeconds = 180
) {
  $uv = Join-Path $RuntimeRoot "installers\windows\tools\uv.exe"
  $python = Get-ChildItem -LiteralPath (Join-Path $StateRoot "embedded-python") `
    -Directory -ErrorAction SilentlyContinue |
    Sort-Object Name -Descending |
    ForEach-Object { Join-Path $_.FullName "python.exe" } |
    Where-Object { Test-Path -LiteralPath $_ } |
    Select-Object -First 1
  $startLight = Join-Path $RuntimeRoot "installers\windows\start-light.ps1"
  if (-not (Test-Path -LiteralPath $uv)) { throw "Prepared update uv is missing: $uv" }
  if (-not $python) { throw "Prepared update bundled Python is missing" }
  if (-not (Test-Path -LiteralPath $startLight)) {
    throw "Prepared update service launcher is missing: $startLight"
  }

  $env:LES_WINDOWS_STATE_ROOT = $StateRoot
  $env:LES_ENV_PATH = Join-Path $StateRoot ".env"
  $env:UV_PROJECT_ENVIRONMENT = Join-Path $StateRoot ".venv"
  Push-Location $RuntimeRoot
  try {
    $previousPreference = $ErrorActionPreference
    try {
      $ErrorActionPreference = "Continue"
      $syncOutput = @(& $uv sync --locked --python $python --no-python-downloads `
        --extra windows-reranker 2>&1)
      $syncExitCode = $LASTEXITCODE
    } finally {
      $ErrorActionPreference = $previousPreference
    }
    if ($syncExitCode -ne 0) {
      $detail = (($syncOutput | Select-Object -Last 8) -join " | ").Trim()
      throw "Prepared update uv sync failed ($syncExitCode): $detail"
    }
    $startOut = Join-Path $LogDir "production-fast-start.out.log"
    $startErr = Join-Path $LogDir "production-fast-start.err.log"
    $startProcess = Invoke-LesBoundedProcess -File "powershell.exe" -Arguments @(
      "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $startLight,
      "-ProxyPort", "8050", "-UiPort", "8051"
    ) -WorkingDirectory $RuntimeRoot -TimeoutSeconds 120 `
      -StdOut $startOut -StdErr $startErr
    if ($startProcess.exit_code -ne 0) {
      $detail = if (Test-Path -LiteralPath $startErr) {
        (Get-Content -LiteralPath $startErr -Tail 12) -join " | "
      } else {
        "no stderr"
      }
      throw "Prepared update service start failed ($($startProcess.exit_code)): $detail"
    }
  } finally {
    Pop-Location
  }

  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  do {
    Start-Sleep -Seconds 1
    try {
      $version = Invoke-RestMethod -Uri "http://127.0.0.1:8050/api/version" -TimeoutSec 10
      $ui = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8051/healthz" -TimeoutSec 10
      if ($version -and [int]$ui.StatusCode -eq 200) {
        return [ordered]@{
          proxy_port = 8050
          ui_port = 8051
          product_version = [string]$version.product_version
        }
      }
    } catch { }
  } while ((Get-Date) -lt $deadline)
  throw "Prepared update API/UI did not become healthy within $TimeoutSeconds seconds"
}

function Get-LesRuntimeProcessHygiene([string]$RuntimeStatePath) {
  if (-not (Test-Path -LiteralPath $RuntimeStatePath)) {
    throw "Windows runtime state is missing for process hygiene gate"
  }
  $state = Get-Content -LiteralPath $RuntimeStatePath -Raw | ConvertFrom-Json
  if ($state.process_contract -ne "direct_python_no_console_v1") {
    throw "Windows runtime does not use direct console-free Python processes"
  }
  $runtimePids = @($state.proxy_pid, $state.ui_pid, $state.lemonade_host_pid) |
    Where-Object { $_ -and [int]$_ -gt 0 }
  $names = @()
  foreach ($runtimePid in $runtimePids) {
    $process = Get-CimInstance Win32_Process -Filter ("ProcessId=" + [int]$runtimePid) `
      -ErrorAction SilentlyContinue
    if (-not $process) { throw "LES runtime process $runtimePid is not alive" }
    if ([string]$process.Name -notin @("python.exe", "pythonw.exe")) {
      throw "LES runtime process $runtimePid is an unexpected launcher: $($process.Name)"
    }
    $names += [string]$process.Name
  }
  $consoleWrappers = @(Get-CimInstance Win32_Process | Where-Object {
    ([string]$_.Name -eq "cmd.exe") -and (
      ([string]$_.CommandLine) -match "proxy_server:app|sovushka_ng\.py|lemonade_host\.py"
    )
  })
  if ($consoleWrappers.Count -ne 0) {
    throw "LES runtime left $($consoleWrappers.Count) cmd.exe wrapper process(es)"
  }
  return [ordered]@{
    contract = [string]$state.process_contract
    runtime_processes = $names
    cmd_wrappers = 0
  }
}

function Invoke-InteractiveOutlookProbe(
  [string]$Collector,
  [object]$CollectorTask,
  [int]$TimeoutSeconds = 60
) {
  # An SSH PowerShell process runs outside the logged-on desktop session and
  # cannot see Outlook's COM object even while OUTLOOK.EXE is open. Run the
  # non-mutating probe as a one-shot interactive task under the same principal
  # as the installed collector, then read its native exit code.
  $probeTaskName = "LES E.ZH.I.K. Outlook Release Probe"
  $userId = [string]$CollectorTask.Principal.UserId
  if (-not $userId) { throw "E.ZH.I.K. Scheduled Task has no interactive user" }
  $action = New-ScheduledTaskAction -Execute $Collector -Argument "--probe"
  $principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive
  try {
    Unregister-ScheduledTask -TaskName $probeTaskName -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $probeTaskName -Action $action -Principal $principal -Force | Out-Null
    $previousInfo = Get-ScheduledTaskInfo -TaskName $probeTaskName -ErrorAction Stop
    $previousRunTime = $previousInfo.LastRunTime
    Start-ScheduledTask -TaskName $probeTaskName
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $probeInfo = $null
    $probeRan = $false
    do {
      Start-Sleep -Milliseconds 250
      $probeTask = Get-ScheduledTask -TaskName $probeTaskName -ErrorAction Stop
      $probeInfo = Get-ScheduledTaskInfo -TaskName $probeTaskName -ErrorAction Stop
      $probeRan = $probeInfo.LastRunTime -gt $previousRunTime
      if ($probeTask.State -ne "Running" -and $probeRan) { break }
    } while ((Get-Date) -lt $deadline)
    if (-not $probeInfo -or -not $probeRan) {
      throw "classic Outlook interactive probe did not run within $TimeoutSeconds seconds"
    }
    return [int]$probeInfo.LastTaskResult
  } finally {
    Unregister-ScheduledTask -TaskName $probeTaskName -Confirm:$false -ErrorAction SilentlyContinue
  }
}

function Start-InteractiveLesDesktop(
  [string]$Desktop,
  [object]$CollectorTask,
  [int]$TimeoutSeconds = 180
) {
  if (-not (Test-Path -LiteralPath $Desktop)) {
    throw "Installed LES desktop was not found: $Desktop"
  }
  $taskName = "LES Release Desktop Start"
  $userId = [string]$CollectorTask.Principal.UserId
  if (-not $userId) { throw "LES desktop handoff has no interactive user" }
  $action = New-ScheduledTaskAction -Execute $Desktop `
    -WorkingDirectory (Split-Path -Parent $Desktop)
  $principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive
  try {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $taskName -Action $action -Principal $principal -Force | Out-Null
    Start-ScheduledTask -TaskName $taskName
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
      Start-Sleep -Seconds 1
      $desktopCount = @(Get-Process -Name "les-desktop" -ErrorAction SilentlyContinue | Where-Object {
        $_.SessionId -ne 0
      }).Count
      if ($desktopCount -gt 1) {
        throw "single-instance gate failed: found $desktopCount interactive LES desktops"
      }
      if ($desktopCount -eq 1) {
        try {
          $version = Invoke-RestMethod -Uri "http://127.0.0.1:8050/api/version" -TimeoutSec 10
          $ui = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8051/healthz" -TimeoutSec 10
          if ($version.les_version -eq $ExpectedVersion -and [int]$ui.StatusCode -eq 200) {
            return [ordered]@{
              product_version = [string]$version.les_version
              ui_status = [int]$ui.StatusCode
              desktop_processes = [int]$desktopCount
              launch_mode = "interactive_scheduled_task"
              services_reused = $true
              bootstrap_reentered = $false
              process_hygiene = Get-LesRuntimeProcessHygiene $RuntimeStatePath
            }
          }
        } catch { }
      }
    } while ((Get-Date) -lt $deadline)
    throw "installed LES desktop did not establish persistent API/UI within $TimeoutSeconds seconds"
  } finally {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
  }
}

try {
  if (-not (Test-Path -LiteralPath $Installer)) { throw "Installer not found: $Installer" }

  $result.stage = "stop_previous"
  try {
    $oldVersion = Invoke-RestMethod -Uri "http://127.0.0.1:8050/api/version" -TimeoutSec 10
    $result.previous_version = $oldVersion.les_version
  } catch { $result.previous_version = "unavailable" }
  try {
    $oldHealth = Invoke-RestMethod -Uri "http://127.0.0.1:8050/api/health" -TimeoutSec 30
    $result.previous_collection = $oldHealth.rag.qdrant.collection
    $result.previous_contract_compatible = [bool]$oldHealth.rag.index_contract.compatible
  } catch {
    $result.previous_contract_compatible = $false
  }
  Stop-LesRuntime

  $result.stage = "install"
  $install = Invoke-LesBoundedProcess -File $Installer `
    -Arguments @("/S", "/D=$InstallRoot") -WorkingDirectory (Split-Path -Parent $Installer) `
    -TimeoutSeconds 300
  if ($install.exit_code -ne 0) {
    throw "Production NSIS install failed with exit code $($install.exit_code)"
  }

  $RuntimeRoot = @(
    (Join-Path $InstallRoot "resources\runtime"),
    (Join-Path $InstallRoot "runtime")
  ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
  if (-not $RuntimeRoot) { throw "Installed production runtime was not found under $InstallRoot" }
  $result.runtime_root = $RuntimeRoot
  if (-not $result.previous_contract_compatible) {
    # Never adopt or rewrite an unknown legacy collection.  Activate a clean,
    # stable Windows generation; the old Qdrant collection remains untouched
    # for explicit audit/migration, and subsequent restarts use this value.
    $newCollection = "les_rag_windows_v2"
    Set-LesEnvValue (Join-Path $StateRoot ".env") "RAG_COLLECTION_NAME" $newCollection
    $result.collection_migration = [ordered]@{
      reason = "previous_index_contract_incompatible"
      previous = $result.previous_collection
      active = $newCollection
      old_collection_preserved = $true
    }
  }
  $result.stage = "fast_start"
  $runtimeState = Start-PreparedUpdateRuntime $RuntimeRoot $StateRoot
  $proxyPort = [int]$runtimeState.proxy_port
  $uiPort = [int]$runtimeState.ui_port
  $result.start_mode = "prepared_fast_update"
  $result.proxy_port = $proxyPort
  $result.ui_port = $uiPort

  $result.stage = "production_health"
  $health = Invoke-RestMethod -Uri "http://127.0.0.1:$proxyPort/api/health" -TimeoutSec 30
  $version = Invoke-RestMethod -Uri "http://127.0.0.1:$proxyPort/api/version" -TimeoutSec 30
  $ui = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$uiPort/healthz" -TimeoutSec 30
  if ($version.les_version -ne $ExpectedVersion) {
    throw "Production version mismatch: expected $ExpectedVersion, got $($version.les_version)"
  }
  if (-not $health -or [int]$ui.StatusCode -ne 200) {
    throw "Production API/UI health is not ready"
  }
  if (-not [bool]$health.rag.index_contract.compatible) {
    throw "Production index contract is not compatible after fast start"
  }
  $result.active_collection = $health.rag.qdrant.collection
  $result.les_version = $version.les_version
  $result.git_commit = $version.git_commit
  $result.ui_status = [int]$ui.StatusCode
  $result.process_hygiene = Get-LesRuntimeProcessHygiene $RuntimeStatePath

  $result.stage = "outlook_mail"
  $collector = Join-Path $StateRoot "bin\LesMailPoller.exe"
  if (-not (Test-Path -LiteralPath $collector)) {
    throw "E.ZH.I.K. Outlook collector was not installed: $collector"
  }
  $mailTask = Get-ScheduledTask -TaskName "LES E.ZH.I.K. Outlook Collector" -ErrorAction SilentlyContinue
  if (-not $mailTask) { throw "E.ZH.I.K. interactive Scheduled Task was not installed" }
  if ([string]$mailTask.Principal.LogonType -notin @("Interactive", "InteractiveToken")) {
    throw "E.ZH.I.K. Scheduled Task is not interactive"
  }
  $mailTriggers = @($mailTask.Triggers | Where-Object { $null -ne $_ })
  if ($mailTriggers.Count -ne 0) {
    throw "E.ZH.I.K. collector must be manual, found $($mailTriggers.Count) scheduled trigger(s)"
  }
  $outlookProbe = "ok"
  try {
    $outlookProbeResult = Invoke-InteractiveOutlookProbe $collector $mailTask
    if ($outlookProbeResult -ne 0) {
      throw "classic Outlook probe returned $outlookProbeResult"
    }
  } catch {
    # Outlook belongs to the optional mail contour and depends on an active
    # interactive desktop session. Its absence must not roll back a healthy
    # LES core/UI update. Keep the result visible for a dedicated mail check.
    $outlookProbe = "warning"
    $result.warnings += "Outlook probe skipped: $($_.Exception.Message)"
  }
  $mailApi = Invoke-RestMethod -Uri "http://127.0.0.1:$proxyPort/api/mail/accounts" -TimeoutSec 30
  $mailApiJson = $mailApi | ConvertTo-Json -Depth 8 -Compress
  if ($mailApiJson -match '"password"\s*:') {
    throw "mail account API exposed a password field"
  }
  $result.mail = [ordered]@{
    collector = $collector
    task_state = [string]$mailTask.State
    interactive = $true
    schedule = "manual"
    trigger_count = 0
    probe_mode = "interactive_scheduled_task"
    outlook_probe = $outlookProbe
    accounts = @($mailApi.accounts).Count
  }
  $result.rag = [ordered]@{
    index_contract_compatible = $true
    active_collection = [string]$health.rag.qdrant.collection
    retrieval_proof = "isolated_clean_install_smoke"
    user_corpus_mutated = $false
  }
  $result.ok = $true
} catch {
  $result.error = $_.Exception.Message
  $result.error_type = $_.Exception.GetType().FullName
} finally {
  if ($result.ok) {
    try {
      $result.stage = "desktop_handoff"
      $result.desktop_handoff = Start-InteractiveLesDesktop `
        (Join-Path $InstallRoot "les-desktop.exe") $mailTask
      $result.stage = "done"
    } catch {
      $result.error = $_.Exception.Message
      $result.error_type = $_.Exception.GetType().FullName
      $result.ok = $false
    }
  }
  $json = $result | ConvertTo-Json -Depth 10
  [System.IO.File]::WriteAllText($ReportPath, $json, (New-Object System.Text.UTF8Encoding($false)))
  Write-Output $json
}

if (-not $result.ok) { exit 1 }
