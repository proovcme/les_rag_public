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

try {
  if (-not (Test-Path -LiteralPath $Installer)) { throw "Installer not found: $Installer" }
  $pdfFiles = @(Get-ChildItem -LiteralPath $HeavyPdfRoot -Filter "*.pdf" -File -ErrorAction Stop)
  if ($pdfFiles.Count -ne 4) {
    throw "Heavy PDF polygon must contain exactly 4 PDF files, found $($pdfFiles.Count): $HeavyPdfRoot"
  }
  $result.pdf_files = @($pdfFiles | ForEach-Object { $_.Name })

  $result.stage = "stop_previous"
  try {
    $oldVersion = Invoke-RestMethod -Uri "http://127.0.0.1:8050/api/version" -TimeoutSec 10
    $result.previous_version = $oldVersion.les_version
  } catch { $result.previous_version = "unavailable" }
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
  if ($health.status -ne "ok" -or [int]$ui.StatusCode -ne 200) {
    throw "Production API/UI health is not ready"
  }
  $result.les_version = $version.les_version
  $result.git_commit = $version.git_commit
  $result.ui_status = [int]$ui.StatusCode

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
    if ($indexed.Count -eq 4) { break }
  } while ((Get-Date) -lt $indexDeadline)
  if ($indexed.Count -ne 4) {
    throw "Production heavy PDF polygon did not finish: indexed $($indexed.Count)/4"
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
  $result.stage = "done"
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
  $json = $result | ConvertTo-Json -Depth 10
  [System.IO.File]::WriteAllText($ReportPath, $json, (New-Object System.Text.UTF8Encoding($false)))
  Write-Output $json
}

if (-not $result.ok) { exit 1 }
