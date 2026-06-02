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

## Import API

```bash
curl -X POST http://127.0.0.1:8050/api/cad-bim/import \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $LES_ADMIN_KEY" \
  -d '{"source_path":"RAG_Content/CAD_BIM/JSON/model.json","source_type":"ifc"}'
```

The legacy `/api/speckle/import` endpoint remains for compatibility, but the
preferred path is `/api/cad-bim/import`.

## DWG Node Workflow

Python does not reliably parse proprietary DWG directly in the local LES stack.
Use AutoCAD as the converter, then let LES ingest DXF-derived JSON:

1. Open the DWG node in AutoCAD.
2. Run `DXFOUT` or `SAVEAS` and save the node as `.dxf`.
3. Put the DXF anywhere accessible to the Mac, for example:
   `RAG_Content/CAD_BIM/DWG/my_node.dxf`.
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
