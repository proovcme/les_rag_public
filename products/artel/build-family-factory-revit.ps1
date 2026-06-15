param(
    [string]$RevitInstallDir = "C:\Program Files\Autodesk\Revit 2025",
    [string]$Configuration = "Release",
    [string]$InstallDir = "$env:APPDATA\Autodesk\Revit\Addins\2025\ARTEL.FamilyFactory"
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$project = Join-Path $root "ARTEL.Revit.FamilyFactory\ARTEL.Revit.FamilyFactory.csproj"
$template = Join-Path $root "ARTEL.Revit.FamilyFactory\ARTEL.Revit.FamilyFactory.addin.template"

if (-not (Test-Path $project)) {
    throw "Project not found: $project"
}
if (-not (Test-Path (Join-Path $RevitInstallDir "RevitAPI.dll"))) {
    throw "RevitAPI.dll not found under $RevitInstallDir"
}

dotnet build $project `
    --configuration $Configuration `
    -p:RevitInstallDir="$RevitInstallDir"

if ($LASTEXITCODE -ne 0) {
    throw "dotnet build failed with exit code $LASTEXITCODE"
}

$outputDir = Join-Path $root "ARTEL.Revit.FamilyFactory\bin\$Configuration\net8.0-windows"
New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
Copy-Item (Join-Path $outputDir "ARTEL.Revit.FamilyFactory.dll") $InstallDir -Force

$addinPath = Join-Path (Split-Path -Parent $InstallDir) "ARTEL.Revit.FamilyFactory.addin"
$addin = Get-Content $template -Raw
$addin = $addin.Replace("__INSTALL_DIR__", $InstallDir)
Set-Content -Path $addinPath -Value $addin -Encoding UTF8

[pscustomobject]@{
    status = "ok"
    project = $project
    revitInstallDir = $RevitInstallDir
    installDir = $InstallDir
    addin = $addinPath
} | ConvertTo-Json -Depth 4
