param(
  [ValidateSet("windows-lite", "windows-docker", "server-remote-model")]
  [string]$Profile = "windows-lite",
  [switch]$InitEnv,
  [switch]$ForceEnv,
  [switch]$Sync,
  [switch]$Start
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root

function Require-Command([string]$Name) {
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
    throw "Missing required command: $Name"
  }
}

Require-Command python
Require-Command uv

New-Item -ItemType Directory -Force -Path data, storage, logs, RAG_Content, artifacts, artifacts\backups | Out-Null

if ($InitEnv -or $ForceEnv) {
  if ((Test-Path ".env") -and -not $ForceEnv) {
    Write-Host ".env exists"
  } else {
    Copy-Item "env.example" ".env" -Force
    Write-Host ".env created from env.example"
  }
}

if ($Sync) {
  & uv sync
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

& uv run lesctl doctor --profile $Profile
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($Profile -eq "windows-docker") {
  Require-Command docker
  if ($Start) {
    & docker compose -f installers\windows\docker-compose.yml --project-directory $Root up -d qdrant proxy ui
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  }
}

Write-Host "LES $Profile install step complete."

