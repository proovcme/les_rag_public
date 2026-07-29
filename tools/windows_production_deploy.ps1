param(
  [Parameter(Mandatory = $true)]
  [string]$Job
)

# Compatibility entrypoint only. The transaction belongs to the Python engine;
# PowerShell must never hold installer output, poll WMI/CIM, build, test or
# manage rollback state.
$ErrorActionPreference = "Stop"
$StateRoot = if ($env:LES_WINDOWS_STATE_ROOT) {
  [System.IO.Path]::GetFullPath($env:LES_WINDOWS_STATE_ROOT)
} elseif ($env:LOCALAPPDATA) {
  Join-Path $env:LOCALAPPDATA "LES"
} else {
  throw "LES Windows state root is unavailable"
}
$Python = Join-Path $StateRoot ".venv\Scripts\python.exe"
$Engine = Join-Path $PSScriptRoot "windows_update_engine.py"
if (-not (Test-Path -LiteralPath $Python)) { throw "LES Python environment is missing" }
if (-not (Test-Path -LiteralPath $Engine)) { throw "Windows update engine is missing" }
& $Python $Engine --job $Job
exit $LASTEXITCODE
