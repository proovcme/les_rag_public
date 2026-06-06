param(
    [string]$RevitInstallDir = "C:\Program Files\Autodesk\Revit 2025",
    [switch]$Screenshot,
    [string]$OutputDir = "$env:LOCALAPPDATA\Temp\artel-revit-diagnose"
)

$ErrorActionPreference = "Stop"

function Get-SessionRows {
    $raw = quser 2>$null
    if (-not $raw) {
        return @()
    }

    $rows = @()
    foreach ($line in $raw | Select-Object -Skip 1) {
        $clean = ($line -replace "^\s*>", "").Trim()
        if (-not $clean) {
            continue
        }
        $parts = $clean -split "\s+"
        if ($parts.Length -lt 4) {
            continue
        }
        $rows += [ordered]@{
            user = $parts[0]
            sessionName = $parts[1]
            id = $parts[2]
            state = $parts[3]
            raw = $clean
        }
    }
    return $rows
}

$revitExe = Join-Path $RevitInstallDir "Revit.exe"
$addinPath = Join-Path $env:APPDATA "Autodesk\Revit\Addins\2025\ARTEL.Revit.FamilyFactory.addin"
$reportDir = Join-Path $env:APPDATA "ARTEL\family_factory"
$journalRoot = Join-Path $env:LOCALAPPDATA "Autodesk\Revit\Autodesk Revit 2025\Journals"

$screenshotPath = $null
if ($Screenshot) {
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
    $screenshotPath = Join-Path $OutputDir ("desktop_{0:yyyyMMdd_HHmmss}.png" -f (Get-Date))

    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $bounds = [System.Windows.Forms.SystemInformation]::VirtualScreen
    $bitmap = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.CopyFromScreen($bounds.Left, $bounds.Top, 0, 0, $bitmap.Size)
    $bitmap.Save($screenshotPath, [System.Drawing.Imaging.ImageFormat]::Png)
    $graphics.Dispose()
    $bitmap.Dispose()
}

$reports = @()
if (Test-Path $reportDir) {
    $reports = Get-ChildItem $reportDir -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 10 Name, FullName, Length, LastWriteTime
}

$journals = @()
if (Test-Path $journalRoot) {
    $journals = Get-ChildItem $journalRoot -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 10 FullName, Length, LastWriteTime
}

[ordered]@{
    status = if (Get-Process LogonUI -ErrorAction SilentlyContinue) { "locked" } else { "interactive" }
    checkedAt = (Get-Date).ToString("o")
    user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    sessions = Get-SessionRows
    lockScreen = [bool](Get-Process LogonUI -ErrorAction SilentlyContinue)
    revitExe = [ordered]@{
        path = $revitExe
        exists = Test-Path $revitExe
    }
    artelAddin = [ordered]@{
        path = $addinPath
        exists = Test-Path $addinPath
    }
    reportDir = [ordered]@{
        path = $reportDir
        exists = Test-Path $reportDir
        latest = $reports
    }
    revitProcesses = Get-Process Revit -ErrorAction SilentlyContinue |
        Select-Object Id, MainWindowTitle, Responding, StartTime
    journals = $journals
    screenshot = $screenshotPath
} | ConvertTo-Json -Depth 6
