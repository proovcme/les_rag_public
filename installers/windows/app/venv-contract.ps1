# Pure helpers for the persistent, offline LES Python environment contract.

function Get-LesSha256([string]$Path) {
  $stream = [System.IO.File]::OpenRead($Path)
  try {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
      return ([System.BitConverter]::ToString($sha.ComputeHash($stream))).Replace("-", "").ToLowerInvariant()
    } finally {
      $sha.Dispose()
    }
  } finally {
    $stream.Dispose()
  }
}

function Get-LesVenvContract {
  param(
    [Parameter(Mandatory = $true)][string]$Root,
    [Parameter(Mandatory = $true)]$State,
    [Parameter(Mandatory = $true)][string]$BundledPython,
    [Parameter(Mandatory = $true)][string]$Uv,
    [Parameter(Mandatory = $true)][string]$Extra,
    [string]$CacheRoot = $env:UV_CACHE_DIR
  )
  $rootPath = [System.IO.Path]::GetFullPath($Root).TrimEnd('\')
  $statePath = if ($State -is [string]) {
    [System.IO.Path]::GetFullPath([string]$State).TrimEnd('\')
  } elseif ($State.state_root) {
    [System.IO.Path]::GetFullPath([string]$State.state_root).TrimEnd('\')
  } else {
    throw "LES state root is missing"
  }
  $lockPath = Join-Path $rootPath "uv.lock"
  $projectPath = Join-Path $rootPath "pyproject.toml"
  if (-not (Test-Path -LiteralPath $lockPath) -or -not (Test-Path -LiteralPath $projectPath)) {
    throw "pyproject.toml and uv.lock must be shipped together"
  }
  $projectText = Get-Content -LiteralPath $projectPath -Raw
  $requiresMatch = [regex]::Match($projectText, '(?m)^requires-python\s*=\s*"([^"]+)"')
  if (-not $requiresMatch.Success) { throw "project requires-python is missing" }

  $pythonVersion = @(& $BundledPython --version 2>&1) -join " "
  if ($LASTEXITCODE -ne 0) { throw "bundled Python identity probe failed" }
  $uvVersion = @(& $Uv --version 2>&1) -join " "
  if ($LASTEXITCODE -ne 0) { throw "bundled uv identity probe failed" }
  $cacheMarker = if ($CacheRoot) { Join-Path $CacheRoot ".les-cache-ready" } else { "" }
  if (-not $cacheMarker -or -not (Test-Path -LiteralPath $cacheMarker)) {
    throw "offline cache readiness marker is missing"
  }

  return [ordered]@{
    schema = "les.windows-venv-contract.v1"
    lock_sha256 = Get-LesSha256 $lockPath
    requires_python = $requiresMatch.Groups[1].Value.Replace(" ", "")
    bundled_python_path = [System.IO.Path]::GetFullPath($BundledPython)
    bundled_python_sha256 = Get-LesSha256 $BundledPython
    bundled_python_version = ([string]$pythonVersion).Trim()
    uv_path = [System.IO.Path]::GetFullPath($Uv)
    uv_sha256 = Get-LesSha256 $Uv
    uv_version = ([string]$uvVersion).Trim()
    offline_cache_root = [System.IO.Path]::GetFullPath($CacheRoot).TrimEnd('\')
    offline_cache_identity = (Get-Content -LiteralPath $cacheMarker -Raw).Trim()
    selected_extra = $Extra
    platform = "windows-$($env:PROCESSOR_ARCHITECTURE)"
    runtime_root = $rootPath
    state_root = $statePath
  }
}

function Test-LesVenvContract {
  param(
    [Parameter(Mandatory = $true)]$Expected,
    [Parameter(Mandatory = $true)][string]$MarkerPath
  )
  if (-not (Test-Path -LiteralPath $MarkerPath)) { return $false }
  try {
    $actual = Get-Content -LiteralPath $MarkerPath -Raw | ConvertFrom-Json
    $expectedJson = $Expected | ConvertTo-Json -Depth 8 -Compress
    $actualJson = $actual | ConvertTo-Json -Depth 8 -Compress
    return $actualJson -ceq $expectedJson
  } catch {
    return $false
  }
}

function Test-LesVenvHealth {
  param([Parameter(Mandatory = $true)][string]$Python)
  if (-not (Test-Path -LiteralPath $Python)) { return $false }
  $previous = $ErrorActionPreference
  try {
    $ErrorActionPreference = "Continue"
    & $Python -c "import fastapi; import proxy.services.version_service" *> $null
    return ($LASTEXITCODE -eq 0)
  } catch {
    return $false
  } finally {
    $ErrorActionPreference = $previous
  }
}

function Write-LesVenvContractAtomically {
  param(
    [Parameter(Mandatory = $true)]$Contract,
    [Parameter(Mandatory = $true)][string]$MarkerPath
  )
  $parent = Split-Path -Parent $MarkerPath
  New-Item -ItemType Directory -Force -Path $parent | Out-Null
  $temporary = Join-Path $parent ("." + [System.IO.Path]::GetFileName($MarkerPath) + "." + [guid]::NewGuid().ToString("N") + ".tmp")
  try {
    [System.IO.File]::WriteAllText(
      $temporary,
      (($Contract | ConvertTo-Json -Depth 8) + "`n"),
      (New-Object System.Text.UTF8Encoding($false))
    )
    Move-Item -LiteralPath $temporary -Destination $MarkerPath -Force
  } finally {
    Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
  }
}
