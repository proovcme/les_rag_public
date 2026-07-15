param(
  [Parameter(Mandatory = $true)]
  [string]$RuntimeRoot,
  [Parameter(Mandatory = $true)]
  [string]$StateRoot,
  [Parameter(Mandatory = $true)]
  [string]$ExpectedVersion,
  [string]$Question = "ширина путей эвакуации",
  [int]$TopK = 3,
  [int]$BootstrapTimeoutSeconds = 240,
  [int]$RetrievalTimeoutSeconds = 180
)

# Live release smoke for an installed Windows runtime.  This intentionally
# launches bootstrap out-of-process and polls its machine-readable status:
# piping bootstrap stdout can keep the pipe open through long-lived proxy/UI
# descendants and turn a healthy launch into a false hang.
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
$RuntimeRoot = [System.IO.Path]::GetFullPath($RuntimeRoot)
$StateRoot = [System.IO.Path]::GetFullPath($StateRoot)
$LogDir = Join-Path $StateRoot "logs"
$StatusPath = Join-Path $LogDir "bootstrap-status.json"
$RuntimeStatePath = Join-Path $LogDir "windows-light-state.json"
$ReportPath = Join-Path $LogDir "release-smoke.json"
$Bootstrap = Join-Path $RuntimeRoot "installers\windows\app\bootstrap.ps1"
$StopScript = Join-Path $RuntimeRoot "installers\windows\stop-light.ps1"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Remove-Item $StatusPath, $RuntimeStatePath, $ReportPath -Force -ErrorAction SilentlyContinue

$env:LES_WINDOWS_STATE_ROOT = $StateRoot
$env:LES_TAURI_SHELL = "1"
$env:LES_TAURI_ACTION = "start"
$smokeCollection = "les_release_smoke_$([guid]::NewGuid().ToString('N'))"
$env:RAG_COLLECTION_NAME = $smokeCollection

$result = [ordered]@{
  schema = "les_windows_release_smoke_v1"
  ok = $false
  stage = "bootstrap"
  runtime_root = $RuntimeRoot
  state_root = $StateRoot
  qdrant_collection = $smokeCollection
}
$bootstrapProcess = $null
$runtimeState = $null
$smokeDatasetId = $null
$smokeSeedPath = $null
$smokeCollectionCreated = $false
$fgisSmokeStarted = $false

try {
  if (-not (Test-Path -LiteralPath $Bootstrap)) {
    throw "bootstrap not found: $Bootstrap"
  }

  $bootstrapProcess = Start-Process -FilePath "powershell.exe" `
    -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $Bootstrap) `
    -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $LogDir "release-smoke-bootstrap.out.log") `
    -RedirectStandardError (Join-Path $LogDir "release-smoke-bootstrap.err.log")

  $deadline = (Get-Date).AddSeconds($BootstrapTimeoutSeconds)
  $bootstrapStatus = $null
  do {
    Start-Sleep -Milliseconds 500
    if (Test-Path -LiteralPath $StatusPath) {
      try {
        $bootstrapStatus = Get-Content -LiteralPath $StatusPath -Raw | ConvertFrom-Json
      } catch { }
    }
    if ($bootstrapStatus -and $bootstrapStatus.state -in @("ready", "failed")) { break }
  } while ((Get-Date) -lt $deadline)

  if (-not $bootstrapStatus) { throw "bootstrap status was not created" }
  $result.bootstrap_state = $bootstrapStatus.state
  $result.bootstrap_phase = $bootstrapStatus.phase
  $result.bootstrap_code = $bootstrapStatus.code
  if ($bootstrapStatus.state -ne "ready") {
    throw "bootstrap failed: $($bootstrapStatus.code) $($bootstrapStatus.message)"
  }
  if (-not (Test-Path -LiteralPath $RuntimeStatePath)) {
    throw "windows-light-state.json was not created"
  }

  $runtimeState = Get-Content -LiteralPath $RuntimeStatePath -Raw | ConvertFrom-Json
  $proxyPort = [int]$runtimeState.proxy_port
  $uiPort = [int]$runtimeState.ui_port
  $result.proxy_port = $proxyPort
  $result.ui_port = $uiPort

  $result.stage = "smeta_baseline"
  $Python = Join-Path $StateRoot ".venv\Scripts\python.exe"
  if (-not (Test-Path -LiteralPath $Python)) {
    throw "release smoke Python was not created: $Python"
  }
  $smetaJson = @(& $Python (Join-Path $RuntimeRoot "tools\smeta_release_baseline.py") `
    verify-root --root $StateRoot) -join "`n"
  if ($LASTEXITCODE -ne 0) { throw "clean-install smeta baseline verification failed: $smetaJson" }
  $smetaBaseline = $smetaJson | ConvertFrom-Json
  $result.smeta_baseline = $smetaBaseline
  if (-not $smetaBaseline.ok -or [int]$smetaBaseline.norm_count -lt 40000 -or `
      [int]$smetaBaseline.fsem_rows -lt 1500) {
    throw "clean-install smeta baseline is incomplete"
  }
  $result.price_scope = [ordered]@{
    bundled = $false
    status = "requires_region_zone_period_selection"
  }

  $result.stage = "api"
  $proxy = Invoke-RestMethod -Uri "http://127.0.0.1:$proxyPort/api/health" -TimeoutSec 30
  $version = Invoke-RestMethod -Uri "http://127.0.0.1:$proxyPort/api/version" -TimeoutSec 30
  $ui = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$uiPort/healthz" -TimeoutSec 30
  $qdrant = Invoke-RestMethod -Uri "http://127.0.0.1:6333/collections" -TimeoutSec 30
  $result.proxy_status = $proxy.status
  $result.les_version = $version.les_version
  $result.app_version = $version.app_version
  $result.harness_version = $version.harness_version
  $result.git_commit = $version.git_commit
  $result.ui_status = [int]$ui.StatusCode
  $result.qdrant_collections = @($qdrant.result.collections).Count
  $smokeCollectionCreated = @(
    $qdrant.result.collections | Where-Object { $_.name -eq $smokeCollection }
  ).Count -eq 1
  if (-not $smokeCollectionCreated) {
    throw "isolated Qdrant collection was not created: $smokeCollection"
  }

  # Prove that the installed operator button is wired to a real resumable
  # process, not only to a static status response. Stop it after the first live
  # catalogue/download heartbeat; the release smoke must stay bounded.
  $result.stage = "fgis_start"
  $fgisStart = Invoke-RestMethod -Method Post `
    -Uri "http://127.0.0.1:$proxyPort/api/service-sources/fgis/update" -TimeoutSec 30
  if (-not $fgisStart.ok -or -not $fgisStart.started) {
    throw "FGIS operator update did not start: $($fgisStart.message)"
  }
  $fgisSmokeStarted = $true
  $fgisDeadline = (Get-Date).AddSeconds(120)
  $fgisStatus = $null
  do {
    Start-Sleep -Seconds 1
    $fgisStatus = Invoke-RestMethod `
      -Uri "http://127.0.0.1:$proxyPort/api/service-sources/fgis/update/status" -TimeoutSec 30
    if ($fgisStatus.running -and $fgisStatus.progress.stage -in @("baseline", "catalog", "price_books")) {
      break
    }
  } while ((Get-Date) -lt $fgisDeadline)
  if (-not $fgisStatus -or -not $fgisStatus.running) {
    throw "FGIS operator update did not produce a live process/status"
  }
  if (@($fgisStatus.layers).Count -lt 7) {
    throw "FGIS operator status does not expose the FSNB layer plan"
  }
  $result.fgis = [ordered]@{
    started = $true
    pid = $fgisStatus.pid
    stage = $fgisStatus.progress.stage
    stage_label = $fgisStatus.progress.stage_label
    layers = @($fgisStatus.layers).Count
    log_lines = @($fgisStatus.log_tail).Count
  }

  # A clean release state has no local dataset catalog. Looking only at the
  # shared Qdrant collections would test somebody else's data and can return an
  # empty result even when indexing is healthy. Seed one isolated dataset
  # through the installed API, wait for its own dense+sparse indexing, query it
  # explicitly, then remove it in finally.
  $result.stage = "rrf_seed"
  $seedMarker = "les release smoke эвакуационный проход контрольный маркер"
  $datasetName = "LES release smoke $([guid]::NewGuid().ToString('N'))"
  $encodedDatasetName = [System.Uri]::EscapeDataString($datasetName)
  $dataset = Invoke-RestMethod -Method Post `
    -Uri "http://127.0.0.1:$proxyPort/api/rag/datasets?name=$encodedDatasetName" `
    -TimeoutSec 30
  $smokeDatasetId = [string]$dataset.id
  if (-not $smokeDatasetId) { throw "release smoke dataset was not created" }
  $result.rrf_dataset_id = $smokeDatasetId

  $smokeSeedPath = Join-Path $StateRoot "release-smoke-rag.txt"
  [System.IO.File]::WriteAllText(
    $smokeSeedPath,
    "$seedMarker. Ширина путей эвакуации проверяется по нормативному источнику.",
    (New-Object System.Text.UTF8Encoding($false))
  )
  $uploadJson = & curl.exe --silent --show-error --fail `
    --form "file=@$smokeSeedPath;type=text/plain" `
    "http://127.0.0.1:$proxyPort/api/rag/upload/$smokeDatasetId"
  if ($LASTEXITCODE -ne 0) { throw "release smoke upload failed with curl exit code $LASTEXITCODE" }
  $upload = ($uploadJson -join "`n") | ConvertFrom-Json
  if (-not $upload.doc_id) { throw "release smoke upload did not return doc_id" }

  $indexDeadline = (Get-Date).AddSeconds($RetrievalTimeoutSeconds)
  $indexedDocument = $null
  do {
    Start-Sleep -Milliseconds 750
    $documents = Invoke-RestMethod `
      -Uri "http://127.0.0.1:$proxyPort/api/rag/documents?dataset_id=$smokeDatasetId&limit=10" `
      -TimeoutSec 30
    $indexedDocument = @($documents.documents) | Where-Object { $_.status -eq "INDEXED" } | Select-Object -First 1
    $failedDocument = @($documents.documents) | Where-Object { $_.status -eq "ERROR" } | Select-Object -First 1
    if ($failedDocument) {
      throw "release smoke indexing failed: $($failedDocument.last_error)"
    }
    if ($indexedDocument) { break }
  } while ((Get-Date) -lt $indexDeadline)
  if (-not $indexedDocument) { throw "release smoke dataset was not indexed before timeout" }
  $result.rrf_seed_chunks = [int]$indexedDocument.chunk_count

  $result.stage = "rrf"
  $body = @{
    question = $Question
    dataset_ids = @($smokeDatasetId)
    top_k = $TopK
  } | ConvertTo-Json -Compress
  # Windows PowerShell 5 may otherwise send a string body in the active ANSI
  # codepage.  Russian text then reaches FastAPI corrupted and BM25 is empty.
  $bodyBytes = [System.Text.Encoding]::UTF8.GetBytes($body)
  $rrf = Invoke-RestMethod -Method Post `
    -Uri "http://127.0.0.1:$proxyPort/api/rag/retrieve-debug" `
    -ContentType "application/json; charset=utf-8" `
    -Body $bodyBytes -TimeoutSec $RetrievalTimeoutSeconds
  $channels = @($rrf.retrieval_trace.retrieval_channels)
  $result.rrf_chunks = @($rrf.chunks).Count
  $result.rrf_channels = $channels
  $result.rrf_fusion = $rrf.retrieval_trace.fusion
  $result.rrf_mode = $rrf.retrieval_trace.mode
  $result.ok = (
    $bootstrapStatus.state -eq "ready" -and
    $version.les_version -eq $ExpectedVersion -and
    $smetaBaseline.ok -and
    [int]$smetaBaseline.norm_count -ge 40000 -and
    [int]$smetaBaseline.fsem_rows -ge 1500 -and
    [int]$ui.StatusCode -eq 200 -and
    $result.fgis.started -and
    [int]$result.fgis.layers -ge 7 -and
    @($rrf.chunks).Count -gt 0 -and
    $rrf.retrieval_trace.fusion -match "rrf" -and
    $channels -contains "dense" -and
    $channels -contains "qdrant_sparse"
  )
  $result.stage = "done"
} catch {
  $result.error = $_.Exception.Message
  $result.error_type = $_.Exception.GetType().FullName
} finally {
  if ($fgisSmokeStarted) {
    try {
      Get-CimInstance Win32_Process | Where-Object {
        $_.ExecutablePath -and
        $_.ExecutablePath.StartsWith($StateRoot, [System.StringComparison]::OrdinalIgnoreCase) -and
        $_.CommandLine -match "tools\.fgis_(update_supervisor|full_update)"
      } | ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
      }
    } catch { }
  }
  if ($smokeDatasetId -and $runtimeState) {
    try {
      Invoke-RestMethod -Method Delete `
        -Uri "http://127.0.0.1:$([int]$runtimeState.proxy_port)/api/rag/datasets/$smokeDatasetId" `
        -TimeoutSec 30 | Out-Null
    } catch {
      $result.cleanup_error = $_.Exception.Message
      $result.ok = $false
    }
  }
  if ($smokeCollectionCreated) {
    try {
      Invoke-RestMethod -Method Delete `
        -Uri "http://127.0.0.1:6333/collections/$smokeCollection" `
        -TimeoutSec 30 | Out-Null
    } catch {
      $result.collection_cleanup_error = $_.Exception.Message
      $result.ok = $false
    }
  }
  if ($smokeSeedPath) {
    Remove-Item -LiteralPath $smokeSeedPath -Force -ErrorAction SilentlyContinue
  }
  $json = $result | ConvertTo-Json -Depth 10
  $json | Set-Content -LiteralPath $ReportPath -Encoding UTF8
  Write-Output $json

  if ($runtimeState -and (Test-Path -LiteralPath $StopScript)) {
    try {
      & $StopScript -ProxyPort ([int]$runtimeState.proxy_port) -UiPort ([int]$runtimeState.ui_port) | Out-Null
    } catch { }
  }
  if ($bootstrapProcess -and -not $bootstrapProcess.HasExited) {
    Stop-Process -Id $bootstrapProcess.Id -Force -ErrorAction SilentlyContinue
  }
}

if (-not $result.ok) { exit 1 }
