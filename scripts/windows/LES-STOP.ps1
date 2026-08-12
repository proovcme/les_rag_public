#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$LesRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$StopScript = Join-Path $LesRoot "installers\windows\stop-light.ps1"

if (-not (Test-Path -LiteralPath $StopScript)) {
    throw "LES stop script not found: $StopScript"
}

Set-Location -LiteralPath $LesRoot
# stop-light uses the LES runtime state/PID ownership contract. Do not kill an
# arbitrary process merely because it happens to listen on a familiar port.
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $StopScript
if ($LASTEXITCODE -ne 0) {
    throw "LES stop failed with exit code $LASTEXITCODE"
}

Write-Host "LES-owned runtime processes stopped." -ForegroundColor Green

