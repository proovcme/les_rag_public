#!/usr/bin/env python3
"""Extract DXF entities into LES CAD/BIM JSON and optionally import them."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
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


def _is_dxf_group_code(line: str) -> bool:
    try:
        int(line.strip())
        return True
    except ValueError:
        return False


def _repair_ascii_dxf_group_codes(source: Path) -> tuple[Path, int]:
    lines = source.read_text(encoding="utf-8", errors="surrogateescape").splitlines()
    repaired: list[str] = []
    expect_code = True
    repairs = 0
    for line in lines:
        if expect_code:
            if _is_dxf_group_code(line):
                repaired.append(line)
                expect_code = False
            elif repaired:
                repaired[-1] = repaired[-1] + r"\P" + line
                repairs += 1
        else:
            repaired.append(line)
            expect_code = True
    nonblank = [line.strip().upper() for line in repaired if line.strip()]
    if not nonblank or nonblank[-1] != "EOF":
        if not expect_code:
            repaired.append("")
        repaired.extend(["0", "EOF"])
        repairs += 1
    handle = tempfile.NamedTemporaryFile("w", suffix=".dxf", prefix="les-dxf-repaired-", delete=False, encoding="utf-8", errors="surrogateescape")
    with handle:
        handle.write("\n".join(repaired))
        handle.write("\n")
    return Path(handle.name), repairs


def _json_safe(value: Any) -> Any:
    if isinstance(value, str):
        return value.encode("utf-8", errors="replace").decode("utf-8")
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(_json_safe(key)): _json_safe(item) for key, item in value.items()}
    return value


def _read_dxf_document(source: Path) -> tuple[Any, dict[str, Any]]:
    ezdxf = _load_ezdxf()
    try:
        return ezdxf.readfile(source), {"dxf_read_mode": "strict"}
    except Exception as strict_error:
        repaired_path, repairs = _repair_ascii_dxf_group_codes(source)
        try:
            doc = ezdxf.readfile(repaired_path)
            return doc, {
                "dxf_read_mode": "repaired_group_codes",
                "dxf_repaired_invalid_group_codes": repairs,
                "dxf_strict_error": f"{type(strict_error).__name__}: {str(strict_error)[:300]}",
            }
        finally:
            try:
                repaired_path.unlink()
            except OSError:
                pass


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


def _axis_tolerance(values: list[float]) -> float:
    if not values:
        return 0.05
    span = max(values) - min(values)
    return max(0.05, min(80.0, span * 0.001))


def _cluster_coords(values: list[float], tolerance: float) -> list[float]:
    if not values:
        return []
    clusters: list[list[float]] = []
    for value in sorted(values):
        if not clusters or abs(value - (sum(clusters[-1]) / len(clusters[-1]))) > tolerance:
            clusters.append([value])
        else:
            clusters[-1].append(value)
    return [round(sum(cluster) / len(cluster), 6) for cluster in clusters]


def _segment_bbox(segment: dict[str, Any]) -> tuple[float, float, float, float]:
    x1, y1 = segment["start"]
    x2, y2 = segment["end"]
    return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)


def _bboxes_touch(a: tuple[float, float, float, float], b: tuple[float, float, float, float], tolerance: float) -> bool:
    return not (
        a[2] + tolerance < b[0]
        or b[2] + tolerance < a[0]
        or a[3] + tolerance < b[1]
        or b[3] + tolerance < a[1]
    )


def _find(parent: list[int], item: int) -> int:
    while parent[item] != item:
        parent[item] = parent[parent[item]]
        item = parent[item]
    return item


def _union(parent: list[int], left: int, right: int) -> None:
    root_left = _find(parent, left)
    root_right = _find(parent, right)
    if root_left != root_right:
        parent[root_right] = root_left


def _element_text_records(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for element in elements:
        if str(element.get("type") or "").upper() not in {"TEXT", "MTEXT"}:
            continue
        props = element.get("properties") if isinstance(element.get("properties"), dict) else {}
        insert = props.get("insert")
        text = str(props.get("text") or element.get("name") or "").strip()
        if not text or not isinstance(insert, list) or len(insert) < 2:
            continue
        records.append(
            {
                "id": str(element.get("id") or ""),
                "text": text,
                "x": float(insert[0]),
                "y": float(insert[1]),
            }
        )
    return records


def _element_axis_segments(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    all_coords: list[float] = []
    raw_segments: list[dict[str, Any]] = []
    for element in elements:
        props = element.get("properties") if isinstance(element.get("properties"), dict) else {}
        etype = str(element.get("type") or "").upper()
        if etype == "LINE":
            start = props.get("start")
            end = props.get("end")
            if isinstance(start, list) and isinstance(end, list) and len(start) >= 2 and len(end) >= 2:
                raw_segments.append({"element_id": str(element.get("id") or ""), "start": [float(start[0]), float(start[1])], "end": [float(end[0]), float(end[1])]})
                all_coords.extend([float(start[0]), float(end[0]), float(start[1]), float(end[1])])
        elif etype in {"LWPOLYLINE", "POLYLINE"}:
            points = props.get("points_preview")
            if not isinstance(points, list) or len(points) < 2:
                continue
            pairs = list(zip(points, points[1:]))
            if props.get("closed") and points[0] != points[-1]:
                pairs.append((points[-1], points[0]))
            for start, end in pairs:
                if not (isinstance(start, list) and isinstance(end, list) and len(start) >= 2 and len(end) >= 2):
                    continue
                raw_segments.append({"element_id": str(element.get("id") or ""), "start": [float(start[0]), float(start[1])], "end": [float(end[0]), float(end[1])]})
                all_coords.extend([float(start[0]), float(end[0]), float(start[1]), float(end[1])])
    tolerance = _axis_tolerance(all_coords)
    for segment in raw_segments:
        x1, y1 = segment["start"]
        x2, y2 = segment["end"]
        if abs(y1 - y2) <= tolerance and abs(x1 - x2) > tolerance * 4:
            segment["orientation"] = "h"
            segment["start"] = [min(x1, x2), (y1 + y2) / 2]
            segment["end"] = [max(x1, x2), (y1 + y2) / 2]
            segments.append(segment)
        elif abs(x1 - x2) <= tolerance and abs(y1 - y2) > tolerance * 4:
            segment["orientation"] = "v"
            segment["start"] = [(x1 + x2) / 2, min(y1, y2)]
            segment["end"] = [(x1 + x2) / 2, max(y1, y2)]
            segments.append(segment)
    return segments


def _component_indexes(segments: list[dict[str, Any]], tolerance: float) -> list[list[int]]:
    if not segments:
        return []
    parent = list(range(len(segments)))
    bboxes = [_segment_bbox(segment) for segment in segments]
    for left in range(len(segments)):
        for right in range(left + 1, len(segments)):
            if _bboxes_touch(bboxes[left], bboxes[right], tolerance):
                _union(parent, left, right)
    groups: dict[int, list[int]] = {}
    for index in range(len(segments)):
        groups.setdefault(_find(parent, index), []).append(index)
    return list(groups.values())


def _text_in_bbox(text: dict[str, Any], bbox: tuple[float, float, float, float], tolerance: float) -> bool:
    x0, y0, x1, y1 = bbox
    return x0 - tolerance <= text["x"] <= x1 + tolerance and y0 - tolerance <= text["y"] <= y1 + tolerance


def _cell_index(value: float, edges: list[float], *, descending: bool, tolerance: float) -> int | None:
    if descending:
        for index in range(len(edges) - 1):
            top = edges[index]
            bottom = edges[index + 1]
            if bottom - tolerance <= value <= top + tolerance:
                return index
        return None
    for index in range(len(edges) - 1):
        left = edges[index]
        right = edges[index + 1]
        if left - tolerance <= value <= right + tolerance:
            return index
    return None


def _build_drawn_table(
    table_index: int,
    component: list[int],
    segments: list[dict[str, Any]],
    texts: list[dict[str, Any]],
    tolerance: float,
) -> dict[str, Any] | None:
    component_segments = [segments[index] for index in component]
    horizontal = [segment for segment in component_segments if segment.get("orientation") == "h"]
    vertical = [segment for segment in component_segments if segment.get("orientation") == "v"]
    if len(horizontal) < 2 or len(vertical) < 2:
        return None
    bboxes = [_segment_bbox(segment) for segment in component_segments]
    x0 = min(bbox[0] for bbox in bboxes)
    y0 = min(bbox[1] for bbox in bboxes)
    x1 = max(bbox[2] for bbox in bboxes)
    y1 = max(bbox[3] for bbox in bboxes)
    bbox = (x0, y0, x1, y1)
    table_texts = [text for text in texts if _text_in_bbox(text, bbox, tolerance)]
    if len(table_texts) < 2:
        return None
    x_edges = _cluster_coords([segment["start"][0] for segment in vertical] + [segment["end"][0] for segment in vertical], tolerance)
    y_edges_ascending = _cluster_coords([segment["start"][1] for segment in horizontal] + [segment["end"][1] for segment in horizontal], tolerance)
    y_edges = list(reversed(y_edges_ascending))
    if len(x_edges) < 3 or len(y_edges) < 3:
        return None
    row_count = len(y_edges) - 1
    column_count = len(x_edges) - 1
    cells: list[list[list[str]]] = [[[] for _ in range(column_count)] for _ in range(row_count)]
    source_text_ids: list[str] = []
    for text in sorted(table_texts, key=lambda item: (-item["y"], item["x"])):
        row_index = _cell_index(text["y"], y_edges, descending=True, tolerance=tolerance)
        column_index = _cell_index(text["x"], x_edges, descending=False, tolerance=tolerance)
        if row_index is None or column_index is None:
            continue
        cells[row_index][column_index].append(text["text"])
        source_text_ids.append(text["id"])
    rows = []
    nonempty_cells = 0
    for row_index, row_cells in enumerate(cells):
        rendered_cells = ["\n".join(items).strip() for items in row_cells]
        if any(rendered_cells):
            nonempty_cells += sum(1 for cell in rendered_cells if cell)
        rows.append(
            {
                "index": row_index,
                "y_top": round(y_edges[row_index], 6),
                "y_bottom": round(y_edges[row_index + 1], 6),
                "cells": rendered_cells,
                "row_text": " | ".join(cell for cell in rendered_cells if cell),
            }
        )
    if nonempty_cells < 2:
        return None
    return {
        "id": f"drawn_table_{table_index}",
        "source": "drawn_primitives",
        "bbox": {"x0": round(x0, 6), "y0": round(y0, 6), "x1": round(x1, 6), "y1": round(y1, 6)},
        "row_count": row_count,
        "column_count": column_count,
        "text_count": len(table_texts),
        "nonempty_cell_count": nonempty_cells,
        "source_element_ids": sorted({str(segment.get("element_id") or "") for segment in component_segments if segment.get("element_id")}),
        "source_text_ids": source_text_ids,
        "confidence": {
            "horizontal_segments": len(horizontal),
            "vertical_segments": len(vertical),
            "grid_lines_x": len(x_edges),
            "grid_lines_y": len(y_edges),
        },
        "rows": rows,
    }


def _detect_drawn_tables(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    texts = _element_text_records(elements)
    segments = _element_axis_segments(elements)
    if not texts or len(segments) < 4:
        return []
    coords = [coord for segment in segments for point in (segment["start"], segment["end"]) for coord in point]
    tolerance = _axis_tolerance(coords)
    components = _component_indexes(segments, tolerance)
    tables: list[dict[str, Any]] = []
    for component in sorted(components, key=len, reverse=True):
        table = _build_drawn_table(len(tables) + 1, component, segments, texts, tolerance)
        if table is None:
            continue
        tables.append(table)
    return tables


def _convert_dwg_to_dxf(source: Path, *, output: Path, version: str = "r2013") -> dict[str, Any]:
    converter = shutil.which(os.getenv("LIBREDWG_DWG2DXF", "dwg2dxf"))
    if not converter:
        raise SystemExit("DWG conversion requires LibreDWG dwg2dxf. Install libredwg or set LIBREDWG_DWG2DXF.")
    output.parent.mkdir(parents=True, exist_ok=True)
    timeout = int(os.getenv("RAG_DWG2DXF_TIMEOUT_SEC", "120"))
    cmd = [converter, "-y", "--as", version, "-o", output.as_posix(), source.as_posix()]
    result = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout, check=False)
    if result.returncode != 0 or not output.exists() or output.stat().st_size == 0:
        stderr = (result.stderr or result.stdout or "").strip()[-2000:]
        raise SystemExit(f"dwg2dxf failed for {source}: {stderr}")
    warnings = "\n".join(part.strip() for part in (result.stderr, result.stdout) if part and part.strip())
    return {
        "tool": "dwg2dxf",
        "tool_path": converter,
        "target_version": version,
        "output": output.as_posix(),
        "warnings": warnings[-4000:],
    }


def _extract_dxf_file(
    dxf_source: Path,
    *,
    original_source: Path,
    source_format: str,
    max_entities: int,
    conversion: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if dxf_source.suffix.lower() != ".dxf":
        raise SystemExit(f"Expected .dxf, got: {dxf_source}")
    doc, read_info = _read_dxf_document(dxf_source)
    msp = doc.modelspace()
    elements = []
    relations = []
    model_id = f"{source_format}:{original_source.stem}"
    for index, entity in enumerate(msp):
        if index >= max_entities:
            break
        element = _entity_to_element(entity, index)
        elements.append(element)
        relations.append({"source_id": model_id, "target_id": element["id"], "relation_type": "contains"})
    layers = sorted({element.get("layer", "") for element in elements if element.get("layer")})
    tables = _detect_drawn_tables(elements)
    return {
        "id": model_id,
        "type": "DXFModel",
        "name": original_source.stem,
        "source_format": source_format,
        "source_path": original_source.as_posix(),
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "properties": {
            "entity_count": len(elements),
            "layers": layers,
            "dxf_version": str(doc.dxfversion),
            "drawn_tables_detected": len(tables),
            **read_info,
            **({"conversion": conversion} if conversion else {}),
        },
        "elements": elements,
        "relations": relations,
        "tables": tables,
    }


def extract_dxf(source: Path, *, max_entities: int = 20000, converted_dxf_dir: Path | None = None) -> dict[str, Any]:
    suffix = source.suffix.lower()
    if suffix == ".dxf":
        return _extract_dxf_file(source, original_source=source, source_format="dxf", max_entities=max_entities)
    if suffix == ".dwg":
        if converted_dxf_dir is not None:
            dxf_source = converted_dxf_dir / f"{source.stem}.dxf"
            conversion = _convert_dwg_to_dxf(source, output=dxf_source)
            return _extract_dxf_file(
                dxf_source,
                original_source=source,
                source_format="dwg",
                max_entities=max_entities,
                conversion=conversion,
            )
        with tempfile.TemporaryDirectory(prefix="les-dwg2dxf-") as tmp_dir:
            dxf_source = Path(tmp_dir) / f"{source.stem}.dxf"
            conversion = _convert_dwg_to_dxf(source, output=dxf_source)
            return _extract_dxf_file(
                dxf_source,
                original_source=source,
                source_format="dwg",
                max_entities=max_entities,
                conversion=conversion,
            )
    raise SystemExit(f"Expected .dxf or .dwg, got: {source}")


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
    parser.add_argument("source", help="DXF file or DWG file convertible with LibreDWG dwg2dxf")
    parser.add_argument("--out", default="", help="Output JSON path")
    parser.add_argument("--converted-dxf-dir", default="", help="Optional directory for keeping DWG->DXF artifacts")
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
    converted_dxf_dir = Path(args.converted_dxf_dir).expanduser().resolve() if args.converted_dxf_dir else None
    payload = _json_safe(extract_dxf(source, max_entities=args.max_entities, converted_dxf_dir=converted_dxf_dir))
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "extracted", "source": source.as_posix(), "out": output.as_posix(), "elements": len(payload["elements"])}, ensure_ascii=False))
    if args.import_to_les:
        result = post_import(args.proxy_url, output, args.api_key)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
