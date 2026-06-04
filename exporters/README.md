# LES CAD/BIM JSON Exporters

This folder contains Autodesk-side exporters that write LES canonical
`cad_bim_graph.json` payloads directly from source models.

## AutoCAD

- Project: `autocad/LES.AutoCAD.JsonExport`
- Ribbon tab: `LES`
- Commands: `LESJSONEXPORT`, `LESJSONPUSH`, `LESJSONCONFIG`
- Output: `<drawing>.cad_bim_graph.json`
- Default source profile for LES import: `autocad`

Build on a Windows workstation with AutoCAD installed:

```powershell
cd exporters\autocad\LES.AutoCAD.JsonExport
dotnet build -c Release -p:AutoCADInstallDir="C:\Program Files\Autodesk\AutoCAD 2025"
```

Install the bundle with the installer EXE or load the compiled DLL in AutoCAD
with `NETLOAD`. Use the `LES` ribbon tab, or run commands manually:

- `LESJSONEXPORT`: save JSON locally.
- `LESJSONPUSH`: export and POST to LES.
- `LESJSONCONFIG`: set upload URLs.

## Revit

- Project: `revit/LES.Revit.JsonExport`
- Ribbon tab: `LES`
- Buttons: `Export JSON`, `Push to LES`
- Output: `<project>.cad_bim_graph.json`
- Default source profile for LES import: `revit`

Build on a Windows workstation with Revit installed:

```powershell
cd exporters\revit\LES.Revit.JsonExport
dotnet build -c Release -p:RevitInstallDir="C:\Program Files\Autodesk\Revit 2025"
```

Copy the DLL to a stable plugin folder and install an `.addin` manifest based on
`LES.Revit.JsonExport.addin.template`. Replace `__INSTALL_DIR__` with the DLL
folder, then place the manifest in:

```text
%APPDATA%\Autodesk\Revit\Addins\2025\
```

The addin creates a Revit ribbon tab named `LES`.

## LES Import

After export, import the JSON with the existing LES endpoint:

```bash
curl -X POST http://127.0.0.1:8050/api/cad-bim/import \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $LES_ADMIN_KEY" \
  -d '{"source_path":"RAG_Content/CAD_BIM/JSON/model.cad_bim_graph.json","source_type":"autocad"}'
```

Use `source_type:"revit"` for Revit exports. DXF extraction remains a fallback
only; Speckle V3 is not part of the critical exporter path.

## Direct Upload

`LESJSONPUSH` and Revit `Push to LES` try these URLs by default:

```text
http://10.195.146.98:8050
https://les.ovc.me
```

The first URL is the Mac over ZeroTier; the second is the public tunnel. If both
uploads fail, the exporter saves a fallback JSON file under the user's Documents
folder. Optional settings live here:

```text
%APPDATA%\LES\cad_bim_exporter_settings.json
```

Public `https://les.ovc.me` uploads need an admin API key in that settings file;
trusted ZeroTier can work without a key when LES trusted-network auth accepts
the Legion subnet.

## Installer EXE

Build the DLL payload and a Windows installer EXE from a Windows workstation:

```powershell
cd exporters
.\build-exporters-windows.ps1 `
  -AutoCADInstallDir "C:\Program Files\Autodesk\AutoCAD 2025" `
  -RevitInstallDir "C:\Program Files\Autodesk\Revit 2025"
```

The output folder is:

```text
exporters\artifacts\cad-bim-exporters\
```

Ship these files together:

- `LES.CadBimExporterInstaller.exe`
- `LES.AutoCAD.JsonExport.dll`
- `LES.Revit.JsonExport.dll`

Then run:

```powershell
.\LES.CadBimExporterInstaller.exe --autocad-year 2025 --revit-year 2025
```
