# CAD/BIM JSON Contract

LES treats JSON as the canonical interchange format for CAD/BIM ingestion. Raw
RVT, DWG, DXF and IFC files are source formats only; exporters should convert
them into JSON/JSONL before indexing.

## Inbox

Put extracted payloads under:

- `RAG_Content/CAD_BIM/JSON/` for canonical graph payloads.
- `RAG_Content/CAD_BIM/IFC/` for IFC-derived JSON next to raw IFC files.
- `RAG_Content/CAD_BIM/DWG/` for DWG/DXF-derived JSON next to raw CAD files.
- `RAG_Content/CAD_BIM/RVT/` for Revit-derived JSON next to raw RVT files.
- `RAG_Content/CAD_BIM/Speckle/` for legacy Speckle object graph exports.

The GUI `IMPORT JSON GRAPH` action imports the newest `.json` or `.jsonl` from
those folders when no explicit source path is supplied.

## Minimal Payload

```json
{
  "id": "model-001",
  "type": "Model",
  "name": "Project model",
  "elements": [
    {
      "id": "wall-001",
      "type": "IfcWall",
      "name": "Wall A",
      "category": "Walls",
      "family": "Basic Wall",
      "level": "Level 01",
      "layer": "A-WALL",
      "material": "Concrete",
      "properties": {
        "FireRating": {"value": "EI 60"},
        "Thickness": {"value": 200, "unit": "mm"}
      }
    }
  ],
  "relations": [
    {"source_id": "model-001", "target_id": "wall-001", "relation_type": "contains"}
  ]
}
```

## Element Fields

Recommended fields:

- `id`: stable source id, GUID, handle, element id or generated exporter id.
- `type` or `object_type`: IFC entity, Revit class, DWG entity or row type.
- `name`: human-readable label.
- `category`: Revit category, IFC grouping, table/sheet name.
- `family`: Revit family/type, DWG block name or linked object key.
- `level`: Revit level or IFC building storey.
- `layer`: DWG/DXF layer.
- `material`: primary material when known.
- `properties`, `parameters`, `propertySets`, `cells` or `data`: key/value
  properties.
- `elements`, `children`, `objects` or `members`: nested elements.

Large geometry arrays should stay out of the JSON graph by default. Store
renders, thumbnails or heavy meshes separately under `renders/` and keep only
references/properties in the graph.

For source highlighting and Speckle-like viewer QA, exporters may attach a
compact display mesh to an element. This geometry is for the viewer, not for RAG
projection text:

```json
{
  "id": "revit-unique-id",
  "type": "Duct",
  "category": "Воздуховоды",
  "properties": {"IfcGUID": "0d0tDHz$j7se2rce6G0lyf"},
  "geometry": {
    "type": "mesh",
    "units": "revit_internal_ft",
    "vertices": [0, 0, 0, 1, 0, 0, 0, 1, 0],
    "faces": [0, 1, 2],
    "material": {"name": "Galvanized", "color": "#f97316", "opacity": 0.86},
    "stats": {"triangles": 1, "vertices": 3, "source": "revit_geometry"},
    "truncated": false
  }
}
```

LES import skips heavy `geometry/vertices/faces` arrays when building SQLite and
markdown projections. The standalone WebGL viewer reads them directly from the
source JSON to render real meshes; old `bbox_min/bbox_max` remains the fallback
preview.

## Import API

```bash
curl -X POST http://127.0.0.1:8050/api/cad-bim/import \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $LES_ADMIN_KEY" \
  -d '{"source_path":"RAG_Content/CAD_BIM/JSON/model.json","source_type":"ifc"}'
```

The legacy `/api/speckle/import` endpoint remains for compatibility, but the
preferred path is `/api/cad-bim/import`.

## Viewer API

Lite Admin `VIZOR` (Visual IFC/JSON Object RAG) reads canonical payloads without importing them:

```bash
curl 'http://127.0.0.1:8050/api/cad-bim/source?source_path=RAG_Content/CAD_BIM/JSON/model.json&max_elements=5000'
```

When `source_path` is omitted, LES uses the newest JSON/JSONL source under the
CAD/BIM inboxes. The API returns the payload, total element count and a
`truncated` flag. The Lite Admin inline preview renders compact 2D previews
from `start/end`, `points_preview`, `center/radius`, `insert` and
`bbox_min/bbox_max`; if no drawable geometry exists, it falls back to a relation
graph view.

VIZOR can also ask LES for object-level RAG context by stable source id. For IFC
this id is the selected element `GlobalId`; for JSON it is the canonical element
`id` or exported `global_id`:

```bash
curl 'http://127.0.0.1:8050/api/cad-bim/element?source_id=0J$u4Qbqf7A9h1vBM9EA01'
```

The response includes the latest matching graph DB element, saved properties,
nearby relations and a ready `rag_prompt`. Mounted VIZOR uses the same route via
`/lite-api/cad-bim/element` after viewer selection.

The LES-mounted OBC/WebGL viewer is served from:

```text
http://127.0.0.1:8051/les/cad-bim-viewer
```

It uses `/lite-api/cad-bim/source` and `/lite-api/cad-bim/element` when mounted inside LES, supports
`source_path`, `source`, `highlight` and `focus` query parameters, and renders
CAD/BIM JSON back into an inspectable scene with models, structure, layers,
stats, clipping, basic distance measurements, selected element properties and
LES/RAG context cards.
For RVT JSON it reads lightweight per-element `geometry.mesh` arrays directly
from source JSON; LES import skips these heavy arrays when writing RAG
projections. This is a round-trip QA path for exporters: if
`DWG/RVT/IFC -> cad_bim_graph.json` can be drawn back into recognizable
geometry, the payload is suitable for object-level RAG indexing and source
highlighting.

An offline-ready install package is generated under:

```text
standalone/cad_bim_viewer/
```

That folder has no `npm` runtime dependency and no LES backend requirement. It
ships `assets/index.js`, `assets/index.css`, `fragments/worker.mjs`, browser
`web-ifc.wasm`, `web-ifc-mt.wasm`, `web-ifc-node.wasm`, any Vite
`assets/worker-*.mjs` files required by the bundled runtime, `serve.sh`,
`serve.ps1` and `models/demo.cad_bim_graph.json`.
Run `serve.ps1` on a bare Windows workstation or `serve.sh` on macOS/Linux, then
open `http://127.0.0.1:8095/`. Direct JSON paths like
`models/demo.cad_bim_graph.json` are loaded without `/lite-api`; IFC files can
be added through the `Добавить` file picker.

The 04.06.2026 DWG node sample `Узлы установки оросителей розеткой вниз`
round-tripped as `2534` elements, `2457` drawable objects and `2534` relations
after removing a UTF-8 BOM from the copied JSON source. Exporters and loaders
should prefer BOM-free UTF-8 JSON.

## AutoCAD Exporter Workflow

Use the AutoCAD .NET exporter in `exporters/autocad/LES.AutoCAD.JsonExport` as
the primary DWG path:

1. Build the plugin on a Windows workstation with AutoCAD installed.
2. Load `LES.AutoCAD.JsonExport.dll` with AutoCAD `NETLOAD`.
3. Run `LESJSONEXPORT`.
4. Save `<drawing>.cad_bim_graph.json` into `RAG_Content/CAD_BIM/JSON/`.
5. Run `IMPORT JSON GRAPH` in Lite Admin or call `/api/cad-bim/import` with
   `source_type:"autocad"`.

The exporter writes entity handles, layers, blocks/block attributes, text,
annotation metadata and compact geometry previews. It intentionally avoids heavy
meshes and full geometric reconstruction.

Installed AutoCAD bundles create a ribbon tab `LES` with buttons for local
export and direct push. `LESJSONPUSH` reads the shared destination config at
`%APPDATA%\LES\cad_bim_exporter_settings.json`: `les_urls` are treated as LES
base URLs, `custom_urls` can be exact POST endpoints or arbitrary import
addresses, and `local_output_dir` controls offline fallback saves.

## Revit Exporter Workflow

Use the Revit addin in `exporters/revit/LES.Revit.JsonExport` as the primary RVT
path:

1. Build the addin on a Windows workstation with Revit installed.
2. Install a manifest based on `LES.Revit.JsonExport.addin.template`.
3. Run `LES JSON Export` from Revit.
4. Save `<project>.cad_bim_graph.json` into `RAG_Content/CAD_BIM/JSON/`.
5. Run `IMPORT JSON GRAPH` in Lite Admin or call `/api/cad-bim/import` with
   `source_type:"revit"`.

The exporter writes stable Revit ids, categories, families/types, levels,
materials, bounding-box previews, parameter values and optional lightweight
display meshes under `geometry`. It does not post to LES unless the `Push to
LES` ribbon button is used. The Revit `Config` button creates/opens the same
shared destination config as AutoCAD.

## Navisworks Exporter Workflow

Use the Navisworks add-in in `exporters/navisworks/LES.Navisworks.JsonExport`
when coordination models (`.nwd`/`.nwf`) are the source of truth:

1. Build the plugin on a Windows workstation with Navisworks Manage installed.
2. Install through `LES.CadBimExporterInstaller.exe` or copy the DLL to:
   `%APPDATA%\Autodesk Navisworks Manage <year>\Plugins\LES.Navisworks.JsonExport\`.
3. Run the `LES JSON Export`, `LES JSON Push` or `LES JSON Config` Add-Ins
   plugin.
4. Import the resulting JSON with `source_type:"navisworks"`.

The initial Navisworks exporter is metadata-first: it traverses the model tree,
uses item instance GUIDs where available, writes property category values and
adds bounding-box preview geometry. Full mesh extraction is a later Windows
smoke-test item and should preserve the same `cad_bim_graph.json` shape.

## Universal Exporter Destinations

All Autodesk-side plugins share one config:

```json
{
  "les_urls": ["http://10.195.146.98:8050", "https://les.ovc.me"],
  "custom_urls": ["http://127.0.0.1:8050/api/cad-bim/import"],
  "local_output_dir": "%USERPROFILE%\\Documents\\LES CAD BIM",
  "api_key": "",
  "timeout_sec": 60
}
```

Destination rules:

- `les_urls`: base LES addresses; exporters POST to `<base>/api/cad-bim/import`.
- `custom_urls`: exact addresses stay exact; empty-path base URLs get
  `/api/cad-bim/import` appended.
- `local_output_dir`: fallback folder and intentional offline drop folder.
- `api_key`: sent as `X-API-Key` when public LES requires admin auth.

## DWG Node Workflow

Python does not reliably parse proprietary DWG directly in the local LES stack.
Use this DXF route only as a fallback when the AutoCAD `LESJSONEXPORT` plugin is
not available:

1. Open the DWG node in AutoCAD.
2. Run `DXFOUT` or `SAVEAS` and save the node as `.dxf`.
3. Put the DXF anywhere accessible to the Mac, for example:
   `RAG_Content/CAD_BIM/DWG/my_node.dxf`.

## Next IFC Work

IFC is the next CAD/BIM focus after AutoCAD/Revit JSON exporters and viewer
smoke. The target is the same canonical contract:

1. Extract IFC product ids, classes, names, storeys, materials, property sets and
   bounding boxes into `cad_bim_graph.json`.
2. Preserve `contains`, `spatial`, `system` and `connects` relations where the
   IFC graph exposes them.
3. Keep geometry previews lightweight enough for RAG and viewer source
   highlighting; full mesh conversion remains optional.
4. Extract and import:

```bash
uv run python tools/cad_bim_extract_dxf.py \
  RAG_Content/CAD_BIM/DWG/my_node.dxf \
  --import-to-les
```

The command writes:

- `RAG_Content/CAD_BIM/JSON/my_node.cad_bim_graph.json`
- `RAG_Content/CAD_BIM/exports/cad_bim_json_<id>.md`

Then use `SYNC CAD/BIM` in Lite Admin to register the projection in
`CAD_BIM_Index`.
