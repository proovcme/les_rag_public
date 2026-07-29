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

function Stop-LesPortProcess([int]$Port) {
  foreach ($processId in @(Get-LesListeningProcessIds $Port)) {
    if ($processId -gt 0) {
      Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
  }
}
