param(
  [Parameter(Mandatory = $true)]
  [string]$Installer,
  [Parameter(Mandatory = $true)]
  [string]$ExpectedVersion,
  [string]$InstallRoot = "",
  [string]$StateRoot = "",
  [string]$HeavyPdfRoot = "C:\Users\Oleg\Downloads\NS\oleg",
  [int]$BootstrapTimeoutSeconds = 600,
  [int]$IndexTimeoutSeconds = 1800,
  [int]$RetrievalTimeoutSeconds = 300
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

$result = [ordered]@{
  schema = "les_windows_production_deploy_v1"
  ok = $false
  stage = "preflight"
  expected_version = $ExpectedVersion
  install_root = $InstallRoot
  state_root = $StateRoot
  heavy_pdf_root = $HeavyPdfRoot
}
$smokeDatasetId = $null
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
  foreach ($port in @(8050, 8051)) {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
      if ($_.OwningProcess -gt 0) { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    }
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
  $startedAt = Get-Date
  try {
    Unregister-ScheduledTask -TaskName $probeTaskName -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $probeTaskName -Action $action -Principal $principal -Force | Out-Null
    Start-ScheduledTask -TaskName $probeTaskName
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $probeInfo = $null
    do {
      Start-Sleep -Milliseconds 250
      $probeTask = Get-ScheduledTask -TaskName $probeTaskName -ErrorAction Stop
      $probeInfo = Get-ScheduledTaskInfo -TaskName $probeTaskName -ErrorAction Stop
      if ($probeTask.State -ne "Running" -and $probeInfo.LastRunTime -ge $startedAt) { break }
    } while ((Get-Date) -lt $deadline)
    if (-not $probeInfo -or $probeInfo.LastRunTime -lt $startedAt) {
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
  $arguments = '/c start "" "' + $Desktop + '"'
  $action = New-ScheduledTaskAction -Execute $env:ComSpec -Argument $arguments `
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
      if ($desktopCount -gt 0) {
        try {
          $version = Invoke-RestMethod -Uri "http://127.0.0.1:8050/api/version" -TimeoutSec 10
          $ui = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8051/healthz" -TimeoutSec 10
          if ($version.les_version -eq $ExpectedVersion -and [int]$ui.StatusCode -eq 200) {
            return [ordered]@{
              product_version = [string]$version.les_version
              ui_status = [int]$ui.StatusCode
              desktop_processes = [int]$desktopCount
              launch_mode = "interactive_scheduled_task"
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
  $pdfFiles = @(Get-ChildItem -LiteralPath $HeavyPdfRoot -Filter "*.pdf" -File -ErrorAction Stop)
  if ($pdfFiles.Count -lt 4) {
    throw "Heavy PDF polygon must contain at least 4 PDF files, found $($pdfFiles.Count): $HeavyPdfRoot"
  }
  $expectedPdfCount = $pdfFiles.Count
  $result.expected_pdf_count = $expectedPdfCount
  $result.pdf_files = @($pdfFiles | ForEach-Object { $_.Name })

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
  $install = Start-Process -FilePath $Installer -ArgumentList @("/S", "/D=$InstallRoot") -Wait -PassThru
  if ($install.ExitCode -ne 0) { throw "Production NSIS install failed with exit code $($install.ExitCode)" }

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
  $Bootstrap = Join-Path $RuntimeRoot "installers\windows\app\bootstrap.ps1"
  if (-not (Test-Path -LiteralPath $Bootstrap)) { throw "Production bootstrap not found: $Bootstrap" }

  $result.stage = "bootstrap"
  Remove-Item -LiteralPath $StatusPath -Force -ErrorAction SilentlyContinue
  $env:LES_WINDOWS_STATE_ROOT = $StateRoot
  $env:LES_TAURI_SHELL = "1"
  $env:LES_TAURI_ACTION = "start"
  Start-Process -FilePath "powershell.exe" `
    -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $Bootstrap) `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $LogDir "production-deploy-bootstrap.out.log") `
    -RedirectStandardError (Join-Path $LogDir "production-deploy-bootstrap.err.log") | Out-Null

  $deadline = (Get-Date).AddSeconds($BootstrapTimeoutSeconds)
  $bootstrapStatus = $null
  do {
    Start-Sleep -Milliseconds 500
    if (Test-Path -LiteralPath $StatusPath) {
      try { $bootstrapStatus = Get-Content -LiteralPath $StatusPath -Raw | ConvertFrom-Json } catch { }
    }
    if ($bootstrapStatus -and $bootstrapStatus.state -in @("ready", "failed")) { break }
  } while ((Get-Date) -lt $deadline)
  if (-not $bootstrapStatus) { throw "Production bootstrap status was not created" }
  if ($bootstrapStatus.state -ne "ready") {
    throw "Production bootstrap failed: $($bootstrapStatus.code) $($bootstrapStatus.message)"
  }
  if (-not (Test-Path -LiteralPath $RuntimeStatePath)) {
    throw "Production windows-light-state.json was not created"
  }
  $runtimeState = Get-Content -LiteralPath $RuntimeStatePath -Raw | ConvertFrom-Json
  $proxyPort = [int]$runtimeState.proxy_port
  $uiPort = [int]$runtimeState.ui_port
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
    throw "Production index contract is not compatible after bootstrap"
  }
  $result.active_collection = $health.rag.qdrant.collection
  $result.les_version = $version.les_version
  $result.git_commit = $version.git_commit
  $result.ui_status = [int]$ui.StatusCode

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
  $outlookProbeResult = Invoke-InteractiveOutlookProbe $collector $mailTask
  if ($outlookProbeResult -ne 0) {
    throw "classic Outlook probe failed; Outlook must be running in the release user session"
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
    probe_mode = "interactive_scheduled_task"
    outlook_probe = "ok"
    accounts = @($mailApi.accounts).Count
  }

  $result.stage = "heavy_pdf_dataset"
  $datasetName = "LES production PDF smoke $([guid]::NewGuid().ToString('N'))"
  $encodedDatasetName = [System.Uri]::EscapeDataString($datasetName)
  $dataset = Invoke-RestMethod -Method Post `
    -Uri "http://127.0.0.1:$proxyPort/api/rag/datasets?name=$encodedDatasetName" -TimeoutSec 30
  $smokeDatasetId = [string]$dataset.id
  if (-not $smokeDatasetId) { throw "Production smoke dataset was not created" }
  foreach ($pdf in $pdfFiles) {
    $uploadJson = & curl.exe --silent --show-error --fail `
      --form "file=@$($pdf.FullName);type=application/pdf" `
      "http://127.0.0.1:$proxyPort/api/rag/upload/$smokeDatasetId"
    if ($LASTEXITCODE -ne 0) { throw "Production PDF upload failed: $($pdf.Name)" }
    $upload = ($uploadJson -join "`n") | ConvertFrom-Json
    if (-not $upload.doc_id) { throw "Production PDF upload returned no doc_id: $($pdf.Name)" }
  }

  $indexDeadline = (Get-Date).AddSeconds($IndexTimeoutSeconds)
  $indexed = @()
  do {
    Start-Sleep -Seconds 2
    $documents = Invoke-RestMethod `
      -Uri "http://127.0.0.1:$proxyPort/api/rag/documents?dataset_id=$smokeDatasetId&limit=20" `
      -TimeoutSec 30
    $rows = @($documents.documents)
    $failed = @($rows | Where-Object { $_.status -eq "ERROR" })
    if ($failed.Count -gt 0) {
      throw "Production heavy PDF indexing failed: $($failed[0].file_name): $($failed[0].last_error)"
    }
    $indexed = @($rows | Where-Object { $_.status -eq "INDEXED" })
    if ($indexed.Count -eq $expectedPdfCount) { break }
  } while ((Get-Date) -lt $indexDeadline)
  if ($indexed.Count -ne $expectedPdfCount) {
    throw "Production heavy PDF polygon did not finish: indexed $($indexed.Count)/$expectedPdfCount"
  }
  $result.indexed_files = $indexed.Count
  $result.indexed_chunks = [int](($indexed | Measure-Object -Property chunk_count -Sum).Sum)

  $result.stage = "heavy_pdf_rrf"
  $body = @{
    question = "комплектная система бесперебойного питания таблица нагрузок"
    dataset_ids = @($smokeDatasetId)
    top_k = 5
  } | ConvertTo-Json -Compress
  $bodyBytes = [System.Text.Encoding]::UTF8.GetBytes($body)
  $rrf = Invoke-RestMethod -Method Post `
    -Uri "http://127.0.0.1:$proxyPort/api/rag/retrieve-debug" `
    -ContentType "application/json; charset=utf-8" -Body $bodyBytes `
    -TimeoutSec $RetrievalTimeoutSeconds
  $channels = @($rrf.retrieval_trace.retrieval_channels)
  if (@($rrf.chunks).Count -eq 0 -or $rrf.retrieval_trace.fusion -notmatch "rrf" -or `
      $channels -notcontains "dense" -or $channels -notcontains "qdrant_sparse") {
    throw "Production heavy PDF retrieval did not prove dense+sparse RRF"
  }
  $result.rrf_chunks = @($rrf.chunks).Count
  $result.rrf_channels = $channels
  $result.rrf_fusion = $rrf.retrieval_trace.fusion
  $result.ok = $true
} catch {
  $result.error = $_.Exception.Message
  $result.error_type = $_.Exception.GetType().FullName
} finally {
  if ($smokeDatasetId -and $proxyPort -gt 0) {
    try {
      Invoke-RestMethod -Method Delete `
        -Uri "http://127.0.0.1:$proxyPort/api/rag/datasets/$smokeDatasetId" `
        -TimeoutSec 60 | Out-Null
      $result.smoke_dataset_removed = $true
    } catch {
      $result.cleanup_error = $_.Exception.Message
      $result.ok = $false
    }
  }
  if ($result.ok) {
    try {
      $result.stage = "desktop_handoff"
      Stop-LesRuntime
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
