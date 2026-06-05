# LES CAD/BIM JSON Exporters

This folder contains Autodesk-side exporters that write LES canonical
`cad_bim_graph.json` payloads directly from source models. The exporters share
one destination config, so the same plugin can save locally, push to local LES,
push to public LES or POST to a custom address.

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
- `LESJSONPUSH`: export and POST to configured destinations.
- `LESJSONCONFIG`: set LES URLs, custom POST URLs and local fallback folder.

## Revit

- Project: `revit/LES.Revit.JsonExport`
- Ribbon tab: `LES`
- Buttons: `Export JSON`, `Push to LES`, `Config`
- Output: `<project>.cad_bim_graph.json`
- Default source profile for LES import: `revit`
- Geometry: lightweight per-element `geometry.mesh` display meshes for WebGL
  viewer QA; LES import skips the heavy arrays when writing RAG projections.

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

The addin creates a Revit ribbon tab named `LES`. `Config` creates/opens the
shared destination JSON file.

## Navisworks

- Project: `navisworks/LES.Navisworks.JsonExport`
- Add-Ins plugins: `LES JSON Export`, `LES JSON Push`, `LES JSON Config`
- Output: `<model>.cad_bim_graph.json`
- Default source profile for LES import: `navisworks`

Build on a Windows workstation with Navisworks Manage installed:

```powershell
cd exporters\navisworks\LES.Navisworks.JsonExport
dotnet build -c Release -p:NavisworksInstallDir="C:\Program Files\Autodesk\Navisworks Manage 2025"
```

The first Navisworks exporter is metadata-first: it traverses the model tree,
copies item properties, stable instance GUIDs where available and bounding-box
preview geometry. Full triangulated geometry extraction is intentionally left
for a Windows/Navisworks smoke pass.

## LES Import

After export, import the JSON with the existing LES endpoint:

```bash
curl -X POST http://127.0.0.1:8050/api/cad-bim/import \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $LES_ADMIN_KEY" \
  -d '{"source_path":"RAG_Content/CAD_BIM/JSON/model.cad_bim_graph.json","source_type":"autocad"}'
```

Use `source_type:"revit"` or `source_type:"navisworks"` for those exporters.
DXF extraction remains a fallback only; Speckle V3 is not part of the critical
exporter path.

## Offline Viewer QA

For a workstation with little or no network access, ship the ready folder:

```text
standalone/cad_bim_viewer/
```

It contains the WebGL viewer bundle, OBC fragments worker, browser
`web-ifc.wasm`, Windows PowerShell server, macOS/Linux server script and a demo
model. No `npm install` or LES backend is required to open exporter JSON:

```powershell
cd standalone\cad_bim_viewer
powershell -ExecutionPolicy Bypass -File .\serve.ps1 -Port 8095
```

Then open `http://127.0.0.1:8095/` and use `Добавить` to load the exported
`*.cad_bim_graph.json` or IFC file. To smoke-test the install without project
data, enter `models/demo.cad_bim_graph.json` and press `Загрузить`.

## Direct Upload

`LESJSONPUSH`, Revit `Push to LES` and Navisworks `push` try these LES base URLs
by default:

```text
http://10.195.146.98:8050
https://les.ovc.me
```

The first URL is the Mac over ZeroTier; the second is the public tunnel. Custom
addresses can be exact POST endpoints or base URLs; base URLs receive
`/api/cad-bim/import` automatically. If uploads fail, the exporter saves a
fallback JSON file under `local_output_dir` or the user's Documents folder.
Optional settings live here:

```text
%APPDATA%\LES\cad_bim_exporter_settings.json
```

Public `https://les.ovc.me` uploads need an admin API key in that settings file;
trusted ZeroTier can work without a key when LES trusted-network auth accepts
the Legion subnet.

Example:

```json
{
  "les_urls": ["http://10.195.146.98:8050", "https://les.ovc.me"],
  "custom_urls": ["http://127.0.0.1:8050/api/cad-bim/import"],
  "local_output_dir": "%USERPROFILE%\\Documents\\LES CAD BIM",
  "api_key": "",
  "timeout_sec": 60
}
```

## Installer EXE

Build the DLL payload and a Windows installer EXE from a Windows workstation:

```powershell
cd exporters
.\build-exporters-windows.ps1 `
  -AutoCADInstallDir "C:\Program Files\Autodesk\AutoCAD 2025" `
  -RevitInstallDir "C:\Program Files\Autodesk\Revit 2025" `
  -NavisworksInstallDir "C:\Program Files\Autodesk\Navisworks Manage 2025"
```

The output folder is:

```text
exporters\artifacts\cad-bim-exporters\
```

Ship these files together:

- `LES.CadBimExporterInstaller.exe`
- `LES.AutoCAD.JsonExport.dll`
- `LES.Revit.JsonExport.dll`
- `LES.Navisworks.JsonExport.dll`

Then run:

```powershell
.\LES.CadBimExporterInstaller.exe --autocad-year 2025 --revit-year 2025 --navisworks-year 2025
```
