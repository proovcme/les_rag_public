#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$LesRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$StartScript = Join-Path $LesRoot "installers\windows\start-light.ps1"
$StopScript = Join-Path $LesRoot "installers\windows\stop-light.ps1"
$Model = if ($env:LES_OLLAMA_MODEL) { $env:LES_OLLAMA_MODEL } else { "qwen3.5:9b" }

if (-not (Test-Path -LiteralPath $StartScript)) {
    throw "LES start script not found: $StartScript"
}

Set-Location -LiteralPath $LesRoot

# Restart the repo-owned stack on the canonical ports. stop-light only kills
# confirmed LES Python owners; a true foreign 8050/8051 still fails closed.
if (Test-Path -LiteralPath $StopScript) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $StopScript
    if ($LASTEXITCODE -ne 0) {
        throw "LES stop before start failed with exit code $LASTEXITCODE"
    }
}

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $StartScript `
    -Provider ollama -Model $Model -ProxyPort 8050 -UiPort 8051
if ($LASTEXITCODE -ne 0) {
    throw "LES start failed with exit code $LASTEXITCODE"
}

Write-Host "LES is ready: http://127.0.0.1:8051/les" -ForegroundColor Green
