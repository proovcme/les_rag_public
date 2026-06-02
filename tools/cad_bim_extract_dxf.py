#!/usr/bin/env python3
"""Extract DXF entities into LES CAD/BIM JSON and optionally import them."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_ezdxf():
    try:
        import ezdxf  # type: ignore
    except ImportError as error:
        raise SystemExit("ezdxf is not installed. Run: uv sync") from error
    return ezdxf


def _point(value: Any) -> list[float]:
    try:
        return [round(float(value.x), 6), round(float(value.y), 6), round(float(value.z), 6)]
    except AttributeError:
        seq = list(value)
        while len(seq) < 3:
            seq.append(0.0)
        return [round(float(seq[0]), 6), round(float(seq[1]), 6), round(float(seq[2]), 6)]


def _entity_id(entity: Any, index: int) -> str:
    handle = getattr(entity.dxf, "handle", None)
    return str(handle or f"entity-{index}")


def _entity_name(entity: Any) -> str:
    dxftype = entity.dxftype()
    if dxftype == "INSERT":
        return str(getattr(entity.dxf, "name", "") or "Block reference")
    if dxftype in {"TEXT", "MTEXT"}:
        return _text_value(entity)[:80] or dxftype
    if dxftype in {"DIMENSION", "LEADER", "MLEADER"}:
        return "Dimension / annotation"
    return dxftype


def _text_value(entity: Any) -> str:
    if entity.dxftype() == "MTEXT":
        try:
            return str(entity.plain_text()).strip()
        except Exception:
            return str(getattr(entity, "text", "")).strip()
    return str(getattr(entity.dxf, "text", "")).strip()


def _common_properties(entity: Any) -> dict[str, Any]:
    dxf = entity.dxf
    props: dict[str, Any] = {
        "handle": str(getattr(dxf, "handle", "")),
        "layer": str(getattr(dxf, "layer", "")),
        "entity_type": entity.dxftype(),
    }
    for name in ("color", "linetype", "lineweight", "ltscale"):
        if hasattr(dxf, name):
            props[name] = getattr(dxf, name)
    return props


def _geometry_properties(entity: Any) -> dict[str, Any]:
    dxftype = entity.dxftype()
    dxf = entity.dxf
    props: dict[str, Any] = {}
    if dxftype == "LINE":
        props["start"] = _point(dxf.start)
        props["end"] = _point(dxf.end)
    elif dxftype in {"LWPOLYLINE", "POLYLINE"}:
        try:
            points = [_point(p) for p in entity.get_points()]
        except Exception:
            points = []
        props["points_count"] = len(points)
        props["points_preview"] = points[:32]
        props["closed"] = bool(getattr(entity, "closed", False))
    elif dxftype in {"CIRCLE", "ARC"}:
        props["center"] = _point(dxf.center)
        props["radius"] = float(dxf.radius)
        if dxftype == "ARC":
            props["start_angle"] = float(dxf.start_angle)
            props["end_angle"] = float(dxf.end_angle)
    elif dxftype in {"TEXT", "MTEXT"}:
        if hasattr(dxf, "insert"):
            props["insert"] = _point(dxf.insert)
        props["text"] = _text_value(entity)
        if hasattr(dxf, "height"):
            props["height"] = float(dxf.height)
    elif dxftype == "INSERT":
        props["block_name"] = str(getattr(dxf, "name", ""))
        props["insert"] = _point(dxf.insert)
        props["rotation"] = float(getattr(dxf, "rotation", 0.0) or 0.0)
        props["scale"] = [
            float(getattr(dxf, "xscale", 1.0) or 1.0),
            float(getattr(dxf, "yscale", 1.0) or 1.0),
            float(getattr(dxf, "zscale", 1.0) or 1.0),
        ]
        attrs = {}
        try:
            attrs = {str(a.dxf.tag): str(a.dxf.text) for a in entity.attribs}
        except Exception:
            attrs = {}
        if attrs:
            props["attributes"] = attrs
    elif dxftype == "DIMENSION":
        props["measurement"] = getattr(entity, "get_measurement", lambda: "")()
        if hasattr(dxf, "text"):
            props["text"] = str(dxf.text)
    return props


def _entity_to_element(entity: Any, index: int) -> dict[str, Any]:
    source_id = _entity_id(entity, index)
    dxftype = entity.dxftype()
    layer = str(getattr(entity.dxf, "layer", ""))
    props = {**_common_properties(entity), **_geometry_properties(entity)}
    return {
        "id": source_id,
        "type": dxftype,
        "name": _entity_name(entity),
        "layer": layer,
        "category": "Annotation" if dxftype in {"TEXT", "MTEXT", "DIMENSION", "LEADER", "MLEADER"} else "Geometry",
        "family": str(getattr(entity.dxf, "name", "")) if dxftype == "INSERT" else "",
        "properties": props,
    }


def extract_dxf(source: Path, *, max_entities: int = 20000) -> dict[str, Any]:
    if source.suffix.lower() == ".dwg":
        raise SystemExit("DWG must be saved/converted to DXF first. In AutoCAD use DXFOUT or Save As -> DXF.")
    if source.suffix.lower() != ".dxf":
        raise SystemExit(f"Expected .dxf, got: {source}")
    ezdxf = _load_ezdxf()
    doc = ezdxf.readfile(source)
    msp = doc.modelspace()
    elements = []
    relations = []
    model_id = f"dxf:{source.stem}"
    for index, entity in enumerate(msp):
        if index >= max_entities:
            break
        element = _entity_to_element(entity, index)
        elements.append(element)
        relations.append({"source_id": model_id, "target_id": element["id"], "relation_type": "contains"})
    layers = sorted({element.get("layer", "") for element in elements if element.get("layer")})
    return {
        "id": model_id,
        "type": "DXFModel",
        "name": source.stem,
        "source_format": "dxf",
        "source_path": source.as_posix(),
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "properties": {
            "entity_count": len(elements),
            "layers": layers,
            "dxf_version": str(doc.dxfversion),
        },
        "elements": elements,
        "relations": relations,
    }


def default_output(source: Path) -> Path:
    return _repo_root() / "RAG_Content" / "CAD_BIM" / "JSON" / f"{source.stem}.cad_bim_graph.json"


def post_import(proxy_url: str, output: Path, api_key: str = "") -> dict[str, Any]:
    url = proxy_url.rstrip("/") + "/api/cad-bim/import"
    payload = {"source_path": output.as_posix(), "source_type": "autocad"}
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"import failed HTTP {exc.code}: {body[:500]}") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="DXF file exported from DWG")
    parser.add_argument("--out", default="", help="Output JSON path")
    parser.add_argument("--max-entities", type=int, default=20000)
    parser.add_argument("--import-to-les", action="store_true", help="POST JSON to /api/cad-bim/import after extraction")
    parser.add_argument("--proxy-url", default="http://127.0.0.1:8050")
    parser.add_argument("--api-key", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = Path(args.source).expanduser().resolve()
    if not source.exists():
        raise SystemExit(f"source not found: {source}")
    output = Path(args.out).expanduser() if args.out else default_output(source)
    if not output.is_absolute():
        output = (_repo_root() / output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = extract_dxf(source, max_entities=args.max_entities)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "extracted", "source": source.as_posix(), "out": output.as_posix(), "elements": len(payload["elements"])}, ensure_ascii=False))
    if args.import_to_les:
        result = post_import(args.proxy_url, output, args.api_key)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
