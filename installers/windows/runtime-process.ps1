# Shared Windows process primitives for LES installers, updater and runtime.
# Keep these functions compatible with Windows PowerShell 5.1.

function ConvertTo-LesNativeArgument([AllowEmptyString()][string]$Value) {
  if ($Value.Length -gt 0 -and $Value -notmatch '[\s"]') { return $Value }
  $builder = New-Object System.Text.StringBuilder
  [void]$builder.Append('"')
  $backslashes = 0
  foreach ($character in $Value.ToCharArray()) {
    if ($character -eq [char]'\') {
      $backslashes += 1
    } elseif ($character -eq [char]'"') {
      [void]$builder.Append([char]'\', (2 * $backslashes) + 1)
      [void]$builder.Append([char]'"')
      $backslashes = 0
    } else {
      if ($backslashes) { [void]$builder.Append([char]'\', $backslashes) }
      [void]$builder.Append($character)
      $backslashes = 0
    }
  }
  if ($backslashes) { [void]$builder.Append([char]'\', 2 * $backslashes) }
  [void]$builder.Append('"')
  return $builder.ToString()
}

function Invoke-LesBoundedProcess(
  [Parameter(Mandatory = $true)]
  [string]$File,
  [string[]]$Arguments = @(),
  [string]$WorkingDirectory = "",
  [int]$TimeoutSeconds = 600,
  [string]$StdOut = "",
  [string]$StdErr = ""
) {
  $startInfo = New-Object System.Diagnostics.ProcessStartInfo
  $startInfo.FileName = $File
  $startInfo.Arguments = (($Arguments | ForEach-Object {
    ConvertTo-LesNativeArgument ([string]$_)
  }) -join " ")
  $startInfo.WorkingDirectory = $WorkingDirectory
  $startInfo.UseShellExecute = $false
  $startInfo.CreateNoWindow = $true
  $startInfo.RedirectStandardOutput = [bool]$StdOut
  $startInfo.RedirectStandardError = [bool]$StdErr

  $process = New-Object System.Diagnostics.Process
  $process.StartInfo = $startInfo
  if (-not $process.Start()) { throw "Could not start $File" }
  $stdoutTask = if ($StdOut) { $process.StandardOutput.ReadToEndAsync() } else { $null }
  $stderrTask = if ($StdErr) { $process.StandardError.ReadToEndAsync() } else { $null }
  if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
    & (Join-Path $env:SystemRoot "System32\taskkill.exe") `
      /PID $process.Id /T /F *> $null
    throw "$File timed out after $TimeoutSeconds seconds"
  }
  $process.WaitForExit()
  if ($StdOut) {
    [System.IO.File]::WriteAllText(
      $StdOut, [string]$stdoutTask.Result, (New-Object System.Text.UTF8Encoding($false))
    )
  }
  if ($StdErr) {
    [System.IO.File]::WriteAllText(
      $StdErr, [string]$stderrTask.Result, (New-Object System.Text.UTF8Encoding($false))
    )
  }
  return [ordered]@{
    exit_code = [int]$process.ExitCode
    pid = [int]$process.Id
  }
}

function Get-LesListeningProcessIds([int]$Port) {
  $netstat = Join-Path $env:SystemRoot "System32\netstat.exe"
  $rows = @(& $netstat -ano -p tcp)
  if ($LASTEXITCODE -ne 0) { throw "netstat failed with exit code $LASTEXITCODE" }
  $processIds = New-Object System.Collections.Generic.List[int]
  foreach ($row in $rows) {
    $text = [string]$row
    if ($text -notmatch '^\s*TCP\s+\S+:(\d+)\s+\S+\s+LISTENING\s+(\d+)\s*$') { continue }
    if ([int]$Matches[1] -eq $Port) { $processIds.Add([int]$Matches[2]) }
  }
  return @($processIds | Sort-Object -Unique)
}

function Test-LesPortFree([int]$Port) {
  return @(Get-LesListeningProcessIds $Port).Count -eq 0
}

function Get-LesProcessCommandLine([int]$ProcessId) {
  try {
    $row = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction Stop
    return [string]$row.CommandLine
  } catch {
    return ""
  }
}

function Test-LesOwnedProcess(
  [int]$ProcessId,
  [string]$RuntimeRoot = "",
  [string[]]$AllowPatterns = @('proxy_server:app', 'sovushka_ng\.py', 'lemonade_host\.py')
) {
  if ($ProcessId -le 0) { return $false }
  $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
  if (-not $process) { return $false }
  $image = [string]$process.ProcessName
  if ($image -notin @('python', 'pythonw')) { return $false }
  $command = Get-LesProcessCommandLine $ProcessId
  if (-not $command) { return $false }
  $owned = $false
  foreach ($pattern in $AllowPatterns) {
    if ($command -match $pattern) { $owned = $true; break }
  }
  if (-not $owned) { return $false }
  # Optional install binding: prefer the persistent venv / runtime python, but do
  # not require the runtime path to appear in CommandLine (uvicorn often omits it).
  if ($RuntimeRoot) {
    $runtime = [System.IO.Path]::GetFullPath($RuntimeRoot).TrimEnd('\')
    $exe = ""
    try { $exe = [string]$process.Path } catch { $exe = "" }
    if (-not $exe) {
      try {
        $exe = [string](Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId").ExecutablePath
      } catch { $exe = "" }
    }
    # Windows often launches system python.exe with repo\.venv\Scripts\uvicorn.exe
    # (or -m uvicorn) while cwd/args still point at this RuntimeRoot. NiceGUI may
    # also re-exec as `python.exe sovushka_ng.py` without an absolute path — then
    # the parent under RuntimeRoot\.venv is the ownership proof.
    $commandUnderRuntime = $command.IndexOf($runtime, [StringComparison]::OrdinalIgnoreCase) -ge 0
    $underState = $false
    $underRuntime = $false
    if ($exe) {
      $exeFull = [System.IO.Path]::GetFullPath($exe)
      $statePython = Join-Path $env:LOCALAPPDATA "LES\.venv\Scripts"
      if ($env:LES_WINDOWS_STATE_ROOT) {
        $statePython = Join-Path ([System.IO.Path]::GetFullPath($env:LES_WINDOWS_STATE_ROOT)) ".venv\Scripts"
      }
      $underState = $exeFull.StartsWith(([System.IO.Path]::GetFullPath($statePython) + [IO.Path]::DirectorySeparatorChar), [StringComparison]::OrdinalIgnoreCase) -or
        $exeFull.Equals([System.IO.Path]::GetFullPath($statePython + "\python.exe"), [StringComparison]::OrdinalIgnoreCase) -or
        $exeFull.Equals([System.IO.Path]::GetFullPath($statePython + "\pythonw.exe"), [StringComparison]::OrdinalIgnoreCase)
      $underRuntime = $exeFull.StartsWith(($runtime + '\'), [StringComparison]::OrdinalIgnoreCase)
    }
    if ($underState -or $underRuntime -or $commandUnderRuntime) {
      return $true
    }
    $parentId = 0
    try {
      $parentId = [int](Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId").ParentProcessId
    } catch {
      $parentId = 0
    }
    if ($parentId -le 0) { return $false }
    $parentCmd = Get-LesProcessCommandLine $parentId
    $parentExe = ""
    try {
      $parentExe = [string](Get-CimInstance Win32_Process -Filter "ProcessId = $parentId").ExecutablePath
    } catch {
      $parentExe = ""
    }
    if ($parentExe) {
      $parentExeFull = [System.IO.Path]::GetFullPath($parentExe)
      if ($parentExeFull.StartsWith(($runtime + '\'), [StringComparison]::OrdinalIgnoreCase)) {
        return $true
      }
    }
    if ($parentCmd -and $parentCmd.IndexOf($runtime, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
      return $true
    }
    return $false
  }
  return $true
}

function Stop-LesConfirmedPortProcess(
  [int]$Port,
  [string]$RuntimeRoot = "",
  [string[]]$AllowPatterns = @('proxy_server:app', 'sovushka_ng\.py', 'lemonade_host\.py')
) {
  foreach ($processId in @(Get-LesListeningProcessIds $Port)) {
    if ($processId -le 0) { continue }
    if (Test-LesOwnedProcess -ProcessId $processId -RuntimeRoot $RuntimeRoot -AllowPatterns $AllowPatterns) {
      Stop-Process -Id $processId -Force -ErrorAction Stop
      continue
    }
    throw "foreign_port_owner: port=$Port pid=$processId"
  }
}

function Stop-LesPortProcess([int]$Port) {
  # Compatibility alias: never kill an unconfirmed owner.
  Stop-LesConfirmedPortProcess -Port $Port
}
