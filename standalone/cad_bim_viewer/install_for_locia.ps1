param(
  [string]$LociaRoot = "C:\Locia",
  [string]$InstallRoot = "C:\LociaTimViewer2",
  [int]$Port = 8095,
  [string]$PublicHost = "",
  [string]$Bind = "+"
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
  Write-Host ""
  Write-Host "== $Message =="
}

function Assert-Admin {
  $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
  $principal = [Security.Principal.WindowsPrincipal]::new($identity)
  if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this installer as Administrator."
  }
}

function Get-DefaultPublicHost {
  try {
    $ip = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
      Where-Object {
        $_.IPAddress -notlike "127.*" -and
        $_.IPAddress -notlike "169.254.*" -and
        $_.PrefixOrigin -ne "WellKnown"
      } |
      Sort-Object InterfaceMetric, PrefixLength |
      Select-Object -First 1 -ExpandProperty IPAddress
    if ($ip) {
      return $ip
    }
  } catch {
    # Fall back to computer name below.
  }

  return $env:COMPUTERNAME
}

function Copy-ViewerFiles([string]$SourceRoot, [string]$TargetRoot) {
  $sourceResolved = [System.IO.Path]::GetFullPath($SourceRoot).TrimEnd("\")
  $targetResolved = [System.IO.Path]::GetFullPath($TargetRoot).TrimEnd("\")
  if ($sourceResolved -ieq $targetResolved) {
    Write-Host "Source already equals install root: $TargetRoot"
    return
  }

  New-Item -ItemType Directory -Force -Path $TargetRoot | Out-Null
  $targetModels = Join-Path $TargetRoot "models"
  $modelsBackup = $null
  if (Test-Path -LiteralPath $targetModels) {
    $modelsBackup = Join-Path ([System.IO.Path]::GetTempPath()) ("locia-tim-viewer2-models-" + [Guid]::NewGuid().ToString("N"))
    Move-Item -LiteralPath $targetModels -Destination $modelsBackup -Force
  }

  try {
    & robocopy $SourceRoot $TargetRoot /MIR /NFL /NDL /NJH /NJS /NP | Out-Host
    if ($LASTEXITCODE -gt 7) {
      throw "robocopy failed with code $LASTEXITCODE"
    }

    if ($modelsBackup) {
      if (Test-Path -LiteralPath $targetModels) {
        Remove-Item -LiteralPath $targetModels -Recurse -Force
      }
      Move-Item -LiteralPath $modelsBackup -Destination $targetModels -Force
      Write-Host "Existing models folder preserved: $targetModels"
    }
  } catch {
    if ($modelsBackup -and -not (Test-Path -LiteralPath $targetModels)) {
      Move-Item -LiteralPath $modelsBackup -Destination $targetModels -Force
    }
    throw
  }
}

function Set-EnvValue([string]$EnvPath, [string]$Name, [string]$Value) {
  if (-not (Test-Path -LiteralPath $EnvPath)) {
    throw ".env not found: $EnvPath"
  }

  $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
  Copy-Item -LiteralPath $EnvPath -Destination "$EnvPath.tim-viewer2-$stamp.bak" -Force

  $lines = [System.Collections.Generic.List[string]]::new()
  $found = $false
  foreach ($line in [System.IO.File]::ReadAllLines($EnvPath)) {
    if ($line -match "^\s*$([Regex]::Escape($Name))=") {
      $lines.Add("$Name=$Value")
      $found = $true
    } else {
      $lines.Add($line)
    }
  }
  if (-not $found) {
    $lines.Add("$Name=$Value")
  }

  $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
  [System.IO.File]::WriteAllLines($EnvPath, $lines, $utf8NoBom)
}

Assert-Admin

$SourceRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$required = @(
  "index.html",
  "assets\index.js",
  "assets\index.css",
  "fragments\worker.mjs",
  "web-ifc\web-ifc.wasm",
  "web-ifc\web-ifc-mt.wasm",
  "web-ifc\web-ifc-node.wasm",
  "models\demo.cad_bim_graph.json",
  "serve.ps1"
)

Write-Step "Validate source"
foreach ($relative in $required) {
  $path = Join-Path $SourceRoot $relative
  if (-not (Test-Path -LiteralPath $path)) {
    throw "Required viewer file is missing: $relative"
  }
}

if ([string]::IsNullOrWhiteSpace($PublicHost)) {
  $PublicHost = Get-DefaultPublicHost
}
$ViewerUrl = "http://$PublicHost`:$Port"

Write-Step "Install isolated viewer files"
Copy-ViewerFiles $SourceRoot $InstallRoot

Write-Step "Configure firewall"
$ruleName = "Locia TIM Viewer 2.0 ($Port)"
$existingRule = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if (-not $existingRule) {
  New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port -Profile Any | Out-Null
  Write-Host "Firewall rule created: $ruleName"
} else {
  Write-Host "Firewall rule already exists: $ruleName"
}

Write-Step "Register startup task"
$taskName = "TimViewer2"
$taskPath = "\LociaERP\"
$serveScript = Join-Path $InstallRoot "serve.ps1"
$taskArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$serveScript`" -Port $Port -Bind `"$Bind`""

try {
  Stop-ScheduledTask -TaskPath $taskPath -TaskName $taskName -ErrorAction SilentlyContinue
} catch {
  # Ignore absent or already stopped task.
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $taskArgs
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskPath $taskPath -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskPath $taskPath -TaskName $taskName
Write-Host "Scheduled task registered and started: $taskPath$taskName"

Write-Step "Configure Locia link"
$envPath = Join-Path $LociaRoot ".env"
Set-EnvValue $envPath "TIM_VIEWER_2_URL" $ViewerUrl
Write-Host "TIM_VIEWER_2_URL=$ViewerUrl"

Write-Step "Restart Locia Apache"
$apache = Get-Service -Name "LociaApache" -ErrorAction SilentlyContinue
if ($apache) {
  Restart-Service -Name "LociaApache" -Force
  Write-Host "LociaApache restarted."
} else {
  Write-Host "LociaApache service was not found; restart Locia manually if needed."
}

Write-Step "Smoke check"
Start-Sleep -Seconds 2
try {
  $response = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec 10
  Write-Host "Local viewer HTTP: $($response.StatusCode)"
} catch {
  Write-Host "Warning: local viewer HTTP check failed: $($_.Exception.Message)"
}

Write-Host ""
Write-Host "Done."
Write-Host "Open from LAN: $ViewerUrl"
Write-Host "Locia menu item uses TIM_VIEWER_2_URL from $envPath"
