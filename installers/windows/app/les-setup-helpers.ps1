# LES Setup/Uninstall helper. Always exit 0 — NSIS must never see "error 1"
# from stop/deps probes. Missing pieces are reported in plain Russian.
$ErrorActionPreference = "Continue"
$Action = if ($args.Count -ge 1) { [string]$args[0] } else { "stop" }
$InstallRoot = if ($env:LES_SETUP_INSTALL_ROOT) {
  [System.IO.Path]::GetFullPath($env:LES_SETUP_INSTALL_ROOT)
} elseif ($args.Count -ge 2 -and $args[1]) {
  [System.IO.Path]::GetFullPath([string]$args[1])
} else {
  Join-Path $env:LOCALAPPDATA "Programs\LES"
}
$StateRoot = if ($env:LES_WINDOWS_STATE_ROOT) {
  [System.IO.Path]::GetFullPath($env:LES_WINDOWS_STATE_ROOT)
} else {
  Join-Path $env:LOCALAPPDATA "LES"
}

function Write-LesSetupLine([string]$Message) {
  Write-Output $Message
}

function Stop-LesBestEffort {
  Write-LesSetupLine "Останавливаю ЛЕС (все экземпляры, не только текущий INSTDIR)..."
  # 1) Every desktop shell — zombies from removed/purge/old shortcuts included.
  try {
    Get-CimInstance Win32_Process -Filter "Name = 'les-desktop.exe'" -ErrorAction SilentlyContinue |
      ForEach-Object {
        Write-LesSetupLine "stop desktop pid=$($_.ProcessId) path=$($_.ExecutablePath)"
        Stop-Process -Id ([int]$_.ProcessId) -Force -ErrorAction SilentlyContinue
      }
  } catch { }
  try { & taskkill.exe /IM les-desktop.exe /F 2>$null | Out-Null } catch { }

  # 2) Installed stop helper when present (refuses foreign port owners).
  foreach ($root in @($InstallRoot, (Join-Path $env:LOCALAPPDATA "Programs\LES"))) {
    foreach ($scriptName in @(
      "resources\runtime\installers\windows\stop-light.ps1",
      "runtime\installers\windows\stop-light.ps1",
      "installers\windows\stop-light.ps1"
    )) {
      $stopScript = Join-Path $root $scriptName
      if (-not (Test-Path -LiteralPath $stopScript)) { continue }
      try {
        $env:LES_WINDOWS_STATE_ROOT = $StateRoot
        & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $stopScript `
          -ProxyPort 8050 -UiPort 8051 2>$null | Out-Null
      } catch { }
      break
    }
  }

  # 3) LES python by command line + by listening on 8050/8051.
  try {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
      Where-Object {
        $_.Name -in @("python.exe", "pythonw.exe") -and
        $_.CommandLine -and
        $_.CommandLine -match 'proxy_server:app|sovushka_ng\.py|lemonade_host\.py'
      } |
      ForEach-Object {
        Stop-Process -Id ([int]$_.ProcessId) -Force -ErrorAction SilentlyContinue
      }
  } catch { }
  try {
    $listeners = @()
    foreach ($row in @(netstat.exe -ano -p tcp 2>$null)) {
      if ($row -notmatch '^\s*TCP\s+\S+:(8050|8051)\s+\S+\s+LISTENING\s+(\d+)\s*$') { continue }
      $listeners += [int]$Matches[2]
    }
    foreach ($pid in ($listeners | Sort-Object -Unique)) {
      $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $pid" -ErrorAction SilentlyContinue
      if (-not $proc) { continue }
      $name = [string]$proc.Name
      $cmd = [string]$proc.CommandLine
      if ($name -notin @("python.exe", "pythonw.exe")) { continue }
      if ($cmd -notmatch 'proxy_server:app|sovushka_ng\.py') { continue }
      Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
    }
  } catch { }
  Start-Sleep -Milliseconds 800
  Write-LesSetupLine "Остановка завершена (лучшее усилие)."
}

function Clear-LesZombieTrees {
  Write-LesSetupLine "Убираю выселенные деревья LES-removed/LES-purge..."
  $local = $env:LOCALAPPDATA
  foreach ($pattern in @("LES-removed-*", "LES-purge-*")) {
    Get-ChildItem -LiteralPath $local -Filter $pattern -ErrorAction SilentlyContinue | ForEach-Object {
      $path = $_.FullName
      Write-LesSetupLine "purge $path"
      # Rename first so a relaunch cannot find the old path, then delete.
      $gone = Join-Path $local ("LES-deleting-{0}" -f [guid]::NewGuid().ToString("N"))
      try {
        Move-Item -LiteralPath $path -Destination $gone -Force -ErrorAction Stop
        Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", "rmdir", "/s", "/q", "`"$gone`"") -WindowStyle Hidden
      } catch {
        try {
          Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", "rmdir", "/s", "/q", "`"$path`"") -WindowStyle Hidden
        } catch { }
      }
    }
  }
}

function Repair-LesShortcuts {
  Write-LesSetupLine "Проверяю ярлыки ЛЕС..."
  $canon = Join-Path $env:LOCALAPPDATA "Programs\LES\les-desktop.exe"
  $wsh = New-Object -ComObject WScript.Shell
  $candidates = @()
  $candidates += @(Get-ChildItem (Join-Path $env:USERPROFILE "Desktop\*.lnk") -ErrorAction SilentlyContinue)
  $candidates += @(Get-ChildItem (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\LES\*.lnk") -ErrorAction SilentlyContinue)
  foreach ($link in $candidates) {
    try {
      $shortcut = $wsh.CreateShortcut($link.FullName)
      $blob = ("{0} {1}" -f $shortcut.TargetPath, $shortcut.Arguments)
      if ($blob -notmatch 'LES|Совуш|les-desktop|Programs\\LES') { continue }
      if ($blob -match 'LES-removed-|LES-purge-|LES-deleting-') {
        Remove-Item -LiteralPath $link.FullName -Force -ErrorAction SilentlyContinue
        Write-LesSetupLine "удалён зомби-ярлык $($link.Name)"
        continue
      }
      if ((Test-Path -LiteralPath $canon) -and $shortcut.TargetPath -ne $canon) {
        if ($shortcut.TargetPath -match 'wscript|les-desktop|Programs\\LES|LOCALAPPDATA') {
          $shortcut.TargetPath = $canon
          $shortcut.Arguments = ""
          $shortcut.WorkingDirectory = Split-Path $canon
          $shortcut.Save()
          Write-LesSetupLine "ярлык переписан на $canon"
        }
      }
    } catch { }
  }
}

function Invoke-LesPreflightInstall {
  Stop-LesBestEffort
  Clear-LesZombieTrees
  Repair-LesShortcuts
  Write-LesSetupLine "preflight-install готов."
}

function Test-LesCommand([string]$Name) {
  return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Ensure-LesWebView2 {
  $marker = Join-Path ${env:ProgramFiles(x86)} "Microsoft\EdgeWebView\Application"
  $markerAlt = Join-Path $env:ProgramFiles "Microsoft\EdgeWebView\Application"
  if ((Test-Path -LiteralPath $marker) -or (Test-Path -LiteralPath $markerAlt)) {
    Write-LesSetupLine "WebView2: установлен"
    return $true
  }
  Write-LesSetupLine "WebView2: не найден — пробую установить через winget..."
  if (Test-LesCommand "winget") {
    try {
      & winget install --id Microsoft.EdgeWebView2Runtime -e --accept-package-agreements --accept-source-agreements --silent 2>&1 | Out-Null
    } catch { }
  }
  if ((Test-Path -LiteralPath $marker) -or (Test-Path -LiteralPath $markerAlt)) {
    Write-LesSetupLine "WebView2: установлен"
    return $true
  }
  Write-LesSetupLine "НУЖНО: установите Microsoft Edge WebView2 Runtime — https://developer.microsoft.com/microsoft-edge/webview2/"
  return $false
}

function Get-LesDependencyReport {
  $missing = New-Object System.Collections.Generic.List[string]
  $ok = New-Object System.Collections.Generic.List[string]

  if (Ensure-LesWebView2) { $ok.Add("WebView2") } else { $missing.Add("WebView2 Runtime — https://developer.microsoft.com/microsoft-edge/webview2/") }

  $ollama = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"),
    (Join-Path $env:ProgramFiles "Ollama\ollama.exe")
  ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
  if ($ollama -or (Test-LesCommand "ollama")) {
    $ok.Add("Ollama")
  } else {
    $ollamaNeed = "Ollama — https://ollama.com/download/windows"
    $missing.Add($ollamaNeed)
    if (Test-LesCommand "winget") {
      Write-LesSetupLine "Ollama: пробую установить через winget..."
      try {
        & winget install --id Ollama.Ollama -e --accept-package-agreements --accept-source-agreements --silent 2>&1 | Out-Null
      } catch { }
      if (Test-LesCommand "ollama" -or (Test-Path -LiteralPath (Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"))) {
        [void]$missing.Remove($ollamaNeed)
        $ok.Add("Ollama")
        Write-LesSetupLine "Ollama: установлен"
      }
    }
  }

  $docker = Get-Command "docker.exe" -ErrorAction SilentlyContinue
  if (-not $docker) {
    $candidate = Join-Path $env:ProgramFiles "Docker\Docker\resources\bin\docker.exe"
    if (Test-Path -LiteralPath $candidate) { $docker = $true }
  }
  if ($docker) {
    $ok.Add("Docker")
  } else {
    $missing.Add("Docker Desktop — https://www.docker.com/products/docker-desktop/")
  }

  return [pscustomobject]@{
    ok = @($ok)
    missing = @($missing)
  }
}

function Remove-LesStateBestEffort {
  param([switch]$IncludeQdrant)
  Write-LesSetupLine "Удаляю данные $StateRoot ..."
  if (Test-Path -LiteralPath $StateRoot) {
    try {
      Remove-Item -LiteralPath $StateRoot -Recurse -Force -ErrorAction Stop
      Write-LesSetupLine "Данные удалены."
    } catch {
      Write-LesSetupLine "НЕ УДАЛОСЬ удалить данные: $($_.Exception.Message)"
      Write-LesSetupLine "Закройте ЛЕС и удалите папку вручную: $StateRoot"
    }
  }
  if ($IncludeQdrant -and (Test-LesCommand "docker")) {
    try { & docker.exe rm -f les-light-qdrant 2>$null | Out-Null } catch { }
    try { & docker.exe volume rm les-qdrant-data 2>$null | Out-Null } catch { }
  }
}

try {
  switch ($Action.ToLowerInvariant()) {
    "stop" { Stop-LesBestEffort }
    "preflight-install" { Invoke-LesPreflightInstall }
    "deps" {
      $report = Get-LesDependencyReport
      $flagDir = Join-Path $StateRoot "logs"
      New-Item -ItemType Directory -Force -Path $flagDir | Out-Null
      $flag = Join-Path $flagDir "setup-deps-missing.txt"
      if ($report.missing.Count -eq 0) {
        Remove-Item -LiteralPath $flag -Force -ErrorAction SilentlyContinue
        Write-LesSetupLine "Зависимости в порядке: $($report.ok -join ', ')"
      } else {
        $body = @(
          "Установка программы ЛЕС завершена успешно.",
          "Чтобы ЛЕС мог работать, установите ещё:",
          ($report.missing | ForEach-Object { " - $_" }),
          "",
          "Затем откройте ЛЕС — мастер настройки проверит остальное."
        ) -join [Environment]::NewLine
        Set-Content -LiteralPath $flag -Value $body -Encoding UTF8
        Write-LesSetupLine $body
      }
    }
    "wipe-state" { Remove-LesStateBestEffort -IncludeQdrant }
    default { Write-LesSetupLine "Неизвестное действие helper: $Action" }
  }
} catch {
  Write-LesSetupLine "Предупреждение helper: $($_.Exception.Message)"
}
exit 0
