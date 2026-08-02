#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$LesRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$StartScript = Join-Path $LesRoot "installers\windows\start-light.ps1"
$Model = if ($env:LES_OLLAMA_MODEL) { $env:LES_OLLAMA_MODEL } else { "qwen3.5:9b" }

if (-not (Test-Path -LiteralPath $StartScript)) {
    throw "LES start script not found: $StartScript"
}

Set-Location -LiteralPath $LesRoot
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $StartScript `
    -Provider ollama -Model $Model
if ($LASTEXITCODE -ne 0) {
    throw "LES start failed with exit code $LASTEXITCODE"
}

Write-Host "LES is ready: http://127.0.0.1:8051/les" -ForegroundColor Green

