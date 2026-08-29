param(
  [string]$AutoCADInstallDir = "C:\Program Files\Autodesk\AutoCAD 2025",
  [string]$RevitInstallDir = "C:\Program Files\Autodesk\Revit 2025",
  [string]$NavisworksInstallDir = "C:\Program Files\Autodesk\Navisworks Manage 2025",
  [string]$AutoCADYear = "2025",
  [string]$RevitYear = "2025",
  [string]$NavisworksYear = "2025",
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

dotnet build (Join-Path $ExportersRoot "navisworks\LES.Navisworks.JsonExport\LES.Navisworks.JsonExport.csproj") `
  -c $Configuration `
  -p:NavisworksInstallDir="$NavisworksInstallDir"
if ($LASTEXITCODE -ne 0) { throw "Navisworks exporter build failed with exit code $LASTEXITCODE" }

Copy-Item (Join-Path $ExportersRoot "autocad\LES.AutoCAD.JsonExport\bin\$Configuration\net48\LES.AutoCAD.JsonExport.dll") $Payload -Force
Copy-Item (Join-Path $ExportersRoot "revit\LES.Revit.JsonExport\bin\$Configuration\net48\LES.Revit.JsonExport.dll") $Payload -Force
Copy-Item (Join-Path $ExportersRoot "navisworks\LES.Navisworks.JsonExport\bin\$Configuration\net48\LES.Navisworks.JsonExport.dll") $Payload -Force

dotnet publish (Join-Path $ExportersRoot "installer\LES.CadBimExporterInstaller\LES.CadBimExporterInstaller.csproj") `
  -c $Configuration `
  -r win-x64 `
  --self-contained true `
  -p:PublishSingleFile=true `
  -p:ExporterPayloadDir="$Payload" `
  -o $Out
if ($LASTEXITCODE -ne 0) { throw "Installer publish failed with exit code $LASTEXITCODE" }

$UniversalExe = Join-Path $Out "LES.CadBimPluginsSetup.exe"
Copy-Item (Join-Path $Out "LES.CadBimExporterInstaller.exe") $UniversalExe -Force

Copy-Item (Join-Path $Payload "LES.AutoCAD.JsonExport.dll") $Out -Force
Copy-Item (Join-Path $Payload "LES.Revit.JsonExport.dll") $Out -Force
Copy-Item (Join-Path $Payload "LES.Navisworks.JsonExport.dll") $Out -Force

$Readme = @"
LES CAD/BIM Exporters
=====================

Run:
  .\LES.CadBimPluginsSetup.exe --autocad-year $AutoCADYear --revit-year $RevitYear --navisworks-year $NavisworksYear

The setup EXE is self-contained and embeds all exporter DLL payloads. DLL copies
are also included next to the installer for manual loading/debugging.

Useful modes:
  .\LES.CadBimPluginsSetup.exe --only revit
  .\LES.CadBimPluginsSetup.exe --skip navisworks
  .\LES.CadBimPluginsSetup.exe --les-url http://127.0.0.1:8050 --local-output-dir "%USERPROFILE%\Documents\LES CAD BIM"

After install:
  AutoCAD ribbon tab: LES
  AutoCAD commands: LESJSONEXPORT, LESJSONPUSH, LESJSONCONFIG
  Revit ribbon tab: LES
  Revit buttons: Export JSON, Push to LES, Config
  Navisworks Add-Ins: LES JSON Export

Shared destinations config:
  %APPDATA%\LES\cad_bim_exporter_settings.json
"@
$Readme | Set-Content -Path (Join-Path $Out "README.txt") -Encoding UTF8

$ZipPath = Join-Path $ExportersRoot ("artifacts\LES_CAD_BIM_plugins_universal_{0}.zip" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
Compress-Archive `
  -Path $UniversalExe, (Join-Path $Out "README.txt") `
  -DestinationPath $ZipPath `
  -Force

Write-Host "Built exporter installer package:"
Write-Host "  $Out"
Write-Host "Universal setup:"
Write-Host "  $UniversalExe"
Write-Host "Zip:"
Write-Host "  $ZipPath"
