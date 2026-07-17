# Persistent Windows state for the Tauri/NSIS runtime.
#
# Application code is replaceable. User data is not. The installed runtime keeps
# its historical relative paths through directory junctions, while the actual
# files live under %LOCALAPPDATA%\LES (or LES_WINDOWS_STATE_ROOT for smoke tests).

function Get-LesWindowsStateRoot {
  if ($env:LES_WINDOWS_STATE_ROOT) {
    return [System.IO.Path]::GetFullPath($env:LES_WINDOWS_STATE_ROOT)
  }
  if (-not $env:LOCALAPPDATA) {
    throw "LOCALAPPDATA is not defined and LES_WINDOWS_STATE_ROOT was not provided."
  }
  return [System.IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "LES"))
}

function Grant-LesWindowsStateAccess {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [switch]$Recurse
  )

  if (-not (Test-Path -LiteralPath $Path)) { return }
  $sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
  $targets = @((Get-Item -LiteralPath $Path -Force))
  if ($Recurse) {
    $targets += @(Get-ChildItem -LiteralPath $Path -Force -Recurse -ErrorAction Stop)
  }
  foreach ($item in $targets) {
    # Read and write only the discretionary ACL. Passing the full object from
    # Get-Acl to Set-Acl can make Windows PowerShell 5.1 attempt to persist the
    # audit ACL too, which requires SeSecurityPrivilege and breaks ordinary
    # interactive launches after an administrator provisioned the state.
    $acl = $item.GetAccessControl(
      [System.Security.AccessControl.AccessControlSections]::Access
    )
    $inheritance = if ($item.PSIsContainer) {
      [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor `
        [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
    } else {
      [System.Security.AccessControl.InheritanceFlags]::None
    }
    $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
      $sid,
      [System.Security.AccessControl.FileSystemRights]::Modify,
      $inheritance,
      [System.Security.AccessControl.PropagationFlags]::None,
      [System.Security.AccessControl.AccessControlType]::Allow
    )
    $acl.SetAccessRule($rule)
    $item.SetAccessControl($acl)
  }
}

function New-LesDirectoryJunction([string]$LinkPath, [string]$TargetPath) {
  $quotedLink = '"' + $LinkPath + '"'
  $quotedTarget = '"' + $TargetPath + '"'
  $output = & cmd.exe /d /c mklink /J $quotedLink $quotedTarget 2>&1
  if ($LASTEXITCODE -ne 0) {
    throw "Unable to create junction $LinkPath -> ${TargetPath}: $output"
  }
}

function Copy-LesLegacyDirectory([string]$BackupPath, [string]$TargetPath) {
  # The immutable backup is the lossless source of truth. Existing persistent
  # files win on name conflicts; the backup remains available for inspection.
  & robocopy.exe $BackupPath $TargetPath /E /COPY:DAT /DCOPY:DAT /R:1 /W:1 /XO /XC /XN /XJ /NFL /NDL /NJH /NJS | Out-Null
  if ($LASTEXITCODE -gt 7) {
    throw "Unable to merge legacy state $BackupPath into $TargetPath (robocopy=$LASTEXITCODE)."
  }
}

function Initialize-LesWindowsState {
  param(
    [Parameter(Mandatory = $true)][string]$RuntimeRoot,
    [string]$StateRoot = ""
  )

  $runtime = [System.IO.Path]::GetFullPath($RuntimeRoot)
  $state = if ($StateRoot) { [System.IO.Path]::GetFullPath($StateRoot) } else { Get-LesWindowsStateRoot }
  New-Item -ItemType Directory -Force -Path $state | Out-Null
  # An administrator may provision the package, while Tauri and uvicorn run
  # under the ordinary interactive token. State must remain writable by that
  # same user even when inherited installer ACLs are protected.
  Grant-LesWindowsStateAccess -Path $state

  $migrationRoot = Join-Path $state "migration"
  New-Item -ItemType Directory -Force -Path $migrationRoot | Out-Null
  $stamp = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssfffZ")
  $migrationRun = Join-Path $migrationRoot $stamp
  $migrated = New-Object System.Collections.Generic.List[string]

  # NSIS updates replace known files but can retain files that disappeared from
  # a newer package. Agent/runtime scratch belongs to replaceable application
  # code, never to persistent LES state. Refuse to traverse a reparse point.
  foreach ($temporaryName in @(".codex_tmp", "tmp")) {
    $temporaryPath = Join-Path $runtime $temporaryName
    if (-not (Test-Path -LiteralPath $temporaryPath)) { continue }
    $temporaryItem = Get-Item -LiteralPath $temporaryPath -Force
    if (($temporaryItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
      throw "Refusing to remove temporary reparse point from LES runtime: $temporaryPath"
    }
    Remove-Item -LiteralPath $temporaryPath -Recurse -Force
  }

  foreach ($name in @("data", "storage", "RAG_Content", "logs", "artifacts")) {
    $source = Join-Path $runtime $name
    $target = Join-Path $state $name
    New-Item -ItemType Directory -Force -Path $target | Out-Null

    if (Test-Path -LiteralPath $source) {
      $item = Get-Item -LiteralPath $source -Force
      if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        $actualTarget = @($item.Target) | Select-Object -First 1
        if (-not $actualTarget -or
            -not [string]::Equals(
              [System.IO.Path]::GetFullPath($actualTarget).TrimEnd('\'),
              [System.IO.Path]::GetFullPath($target).TrimEnd('\'),
              [System.StringComparison]::OrdinalIgnoreCase
            )) {
          throw "Existing reparse point $source does not target persistent LES state $target."
        }
        continue
      }
      New-Item -ItemType Directory -Force -Path $migrationRun | Out-Null
      $backup = Join-Path $migrationRun $name
      Move-Item -LiteralPath $source -Destination $backup
      Copy-LesLegacyDirectory -BackupPath $backup -TargetPath $target
      $migrated.Add($name)
    }

    if (-not (Test-Path -LiteralPath $source)) {
      New-LesDirectoryJunction -LinkPath $source -TargetPath $target
    }
  }

  $runtimeEnv = Join-Path $runtime ".env"
  $stateEnv = Join-Path $state ".env"
  if ((Test-Path -LiteralPath $runtimeEnv) -and -not (Test-Path -LiteralPath $stateEnv)) {
    New-Item -ItemType Directory -Force -Path $migrationRun | Out-Null
    $envBackup = Join-Path $migrationRun ".env"
    Move-Item -LiteralPath $runtimeEnv -Destination $envBackup
    Copy-Item -LiteralPath $envBackup -Destination $stateEnv
    $migrated.Add(".env")
  } elseif (Test-Path -LiteralPath $runtimeEnv) {
    New-Item -ItemType Directory -Force -Path $migrationRun | Out-Null
    Move-Item -LiteralPath $runtimeEnv -Destination (Join-Path $migrationRun ".env")
    $migrated.Add(".env_backup_only")
  }

  if (-not (Test-Path -LiteralPath $stateEnv)) {
    $example = Join-Path $runtime "env.example"
    if (-not (Test-Path -LiteralPath $example)) {
      throw "env.example is missing from runtime: $example"
    }
    Copy-Item -LiteralPath $example -Destination $stateEnv
  }

  $payload = [ordered]@{
    schema = "les_windows_state_v1"
    runtime_root = $runtime
    state_root = $state
    env_path = $stateEnv
    migrated = @($migrated)
    migration_backup = if ($migrated.Count -gt 0) { $migrationRun } else { $null }
  }
  $manifest = Join-Path $migrationRoot "last_state_init.json"
  $payload | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifest -Encoding utf8
  return [pscustomobject]$payload
}
