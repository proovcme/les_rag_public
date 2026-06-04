param(
  [string]$AutoCADInstallDir = "C:\Program Files\Autodesk\AutoCAD 2025",
  [string]$RevitInstallDir = "C:\Program Files\Autodesk\Revit 2025",
  [string]$AutoCADYear = "2025",
  [string]$RevitYear = "2025",
  [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"

$ExportersRoot = $PSScriptRoot
$Out = Join-Path $ExportersRoot "artifacts\cad-bim-exporters"
$Payload = Join-Path $Out "payload"

Remove-Item $Out -Recurse -Force -ErrorAction SilentlyContinue
New-Item $Payload -ItemType Directory -Force | Out-Null

dotnet build (Join-Path $ExportersRoot "autocad\LES.AutoCAD.JsonExport\LES.AutoCAD.JsonExport.csproj") `
  -c $Configuration `
  -p:AutoCADInstallDir="$AutoCADInstallDir"
if ($LASTEXITCODE -ne 0) { throw "AutoCAD exporter build failed with exit code $LASTEXITCODE" }

dotnet build (Join-Path $ExportersRoot "revit\LES.Revit.JsonExport\LES.Revit.JsonExport.csproj") `
  -c $Configuration `
  -p:RevitInstallDir="$RevitInstallDir"
if ($LASTEXITCODE -ne 0) { throw "Revit exporter build failed with exit code $LASTEXITCODE" }

Copy-Item (Join-Path $ExportersRoot "autocad\LES.AutoCAD.JsonExport\bin\$Configuration\net48\LES.AutoCAD.JsonExport.dll") $Payload -Force
Copy-Item (Join-Path $ExportersRoot "revit\LES.Revit.JsonExport\bin\$Configuration\net48\LES.Revit.JsonExport.dll") $Payload -Force

dotnet publish (Join-Path $ExportersRoot "installer\LES.CadBimExporterInstaller\LES.CadBimExporterInstaller.csproj") `
  -c $Configuration `
  -r win-x64 `
  --self-contained true `
  -p:PublishSingleFile=true `
  -p:ExporterPayloadDir="$Payload" `
  -o $Out
if ($LASTEXITCODE -ne 0) { throw "Installer publish failed with exit code $LASTEXITCODE" }

Copy-Item (Join-Path $Payload "LES.AutoCAD.JsonExport.dll") $Out -Force
Copy-Item (Join-Path $Payload "LES.Revit.JsonExport.dll") $Out -Force

$Readme = @"
LES CAD/BIM Exporters
=====================

Run:
  .\LES.CadBimExporterInstaller.exe --autocad-year $AutoCADYear --revit-year $RevitYear

The installer embeds the exporter DLL payload. DLL copies are also included
next to the installer for manual loading/debugging.

After install:
  AutoCAD ribbon tab: LES
  AutoCAD commands: LESJSONEXPORT, LESJSONPUSH, LESJSONCONFIG
  Revit ribbon tab: LES
  Revit buttons: Export JSON, Push to LES
"@
$Readme | Set-Content -Path (Join-Path $Out "README.txt") -Encoding UTF8

Write-Host "Built exporter installer package:"
Write-Host "  $Out"
