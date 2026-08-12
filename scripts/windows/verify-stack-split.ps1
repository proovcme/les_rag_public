#Requires -Version 5.1
# Verify LES (host Ollama/Qdrant) and ODS (Docker) stay on separate ports.
# ASCII-only for Windows PowerShell 5.1.
$ErrorActionPreference = "Continue"

function Test-HttpOk([string]$Url, [int]$TimeoutSec = 3) {
  try {
    $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec
    return ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500)
  } catch {
    return $false
  }
}

function Test-IsOllamaTags([string]$Url) {
  try {
    $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
    $json = $resp.Content | ConvertFrom-Json
    return ($null -ne $json.models)
  } catch {
    return $false
  }
}

Write-Host "=== LES / ODS stack split ===" -ForegroundColor Cyan
$checks = @()

$lesOllama = Test-IsOllamaTags "http://127.0.0.1:11434/api/tags"
$checks += [pscustomobject]@{ Name = "LES Ollama :11434 /api/tags"; Ok = $lesOllama; Expect = "host Ollama for LES" }

$odsLlama = Test-HttpOk "http://127.0.0.1:21134/health"
$checks += [pscustomobject]@{ Name = "ODS llama-server :21134 /health"; Ok = $odsLlama; Expect = "Docker llama.cpp" }

$wrong = Test-IsOllamaTags "http://127.0.0.1:21134/api/tags"
$checks += [pscustomobject]@{ Name = "ODS :21134 is NOT Ollama tags"; Ok = (-not $wrong); Expect = "llama-server OpenAI API" }

$lesQ = Test-HttpOk "http://127.0.0.1:6333/collections"
$checks += [pscustomobject]@{ Name = "LES Qdrant :6333 /collections"; Ok = $lesQ; Expect = "native LES Qdrant" }

$odsQAuth = $false
try {
  $null = Invoke-WebRequest -Uri "http://127.0.0.1:26333/collections" -UseBasicParsing -TimeoutSec 3
  $odsQAuth = $true
} catch {
  # ODS Qdrant usually requires API key -> 401 still proves the port is ODS.
  if ($_.Exception.Message -match "401|Unauthorized") { $odsQAuth = $true }
}
$checks += [pscustomobject]@{ Name = "ODS Qdrant :26333"; Ok = $odsQAuth; Expect = "Docker qdrant (often 401 without key)" }

$lesApi = Test-HttpOk "http://127.0.0.1:8050/api/version"
$checks += [pscustomobject]@{ Name = "LES API :8050"; Ok = $lesApi; Expect = "LES proxy" }

$odsWeb = Test-HttpOk "http://127.0.0.1:3000"
$checks += [pscustomobject]@{ Name = "ODS WebUI :3000"; Ok = $odsWeb; Expect = "Open WebUI" }

$dockerOllama = docker ps -a --format "{{.Names}}" 2>$null | Select-String -Pattern "^ods-ollama$"
$checks += [pscustomobject]@{ Name = "No ods-ollama container"; Ok = (-not [bool]$dockerOllama); Expect = "Ollama stays on host for LES" }

foreach ($c in $checks) {
  $mark = if ($c.Ok) { "[OK]" } else { "[!!]" }
  $color = if ($c.Ok) { "Green" } else { "Red" }
  Write-Host ("  {0} {1}  ({2})" -f $mark, $c.Name, $c.Expect) -ForegroundColor $color
}

Write-Host ""
Write-Host "Port map:" -ForegroundColor Cyan
Write-Host "  LES  Ollama      http://127.0.0.1:11434"
Write-Host "  LES  Qdrant      http://127.0.0.1:6333"
Write-Host "  LES  UI/API      http://127.0.0.1:8051/les  |  :8050"
Write-Host "  ODS  llama.cpp   http://127.0.0.1:21134"
Write-Host "  ODS  Qdrant      http://127.0.0.1:26333"
Write-Host "  ODS  WebUI       http://127.0.0.1:3000"
Write-Host "  ODS  AnythingLLM http://127.0.0.1:7800  (after: ods enable anythingllm)"

$failed = @($checks | Where-Object { -not $_.Ok }).Count
if ($failed -gt 0) {
  Write-Host ""
  Write-Host ("FAILED checks: {0}. Re-run configure-ods-coexist.ps1 if ports collided." -f $failed) -ForegroundColor Yellow
  exit 1
}
Write-Host ""
Write-Host "Stack split looks good." -ForegroundColor Green
exit 0
