"""Lightweight CAD/BIM graph store and text projection helpers."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CAD_BIM_ROOT = Path(os.getenv("CAD_BIM_CONTENT_ROOT", "RAG_Content/CAD_BIM"))
CAD_BIM_DB_PATH = Path(os.getenv("CAD_BIM_GRAPH_DB_PATH", "data/cad_bim_graph.db"))
MAX_TEXT_VALUE = 320
CHILD_KEYS = {
    "elements",
    "children",
    "objects",
    "members",
    "displayValue",
    "displayMesh",
    "instances",
    "definition",
}
SKIP_KEYS = {
    "bbox",
    "geometry",
    "vertices",
    "faces",
    "colors",
    "renderMaterial",
    "transform",
    "displayStyle",
}
PROPERTY_CONTAINER_KEYS = {"parameters", "properties", "propertySets", "property_sets", "info", "cells", "data"}


@dataclass(frozen=True)
class CadBimImportResult:
    import_id: str
    source: str
    profile: str
    elements: int
    relations: int
    properties: int
    projection_path: str
    db_path: str


def ensure_cad_bim_dirs(root: Path = CAD_BIM_ROOT) -> None:
    for child in ("JSON", "DWG", "RVT", "IFC", "Speckle", "exports", "renders", "notes"):
        (root / child).mkdir(parents=True, exist_ok=True)


def init_graph_db(db_path: Path = CAD_BIM_DB_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cad_bim_imports (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                source_kind TEXT NOT NULL,
                profile TEXT NOT NULL DEFAULT 'generic',
                created_at TEXT NOT NULL,
                element_count INTEGER NOT NULL DEFAULT 0,
                relation_count INTEGER NOT NULL DEFAULT 0,
                property_count INTEGER NOT NULL DEFAULT 0,
                projection_path TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cad_bim_elements (
                id TEXT PRIMARY KEY,
                import_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                speckle_type TEXT NOT NULL DEFAULT '',
                object_type TEXT NOT NULL DEFAULT '',
                name TEXT NOT NULL DEFAULT '',
                layer TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '',
                family TEXT NOT NULL DEFAULT '',
                level TEXT NOT NULL DEFAULT '',
                material TEXT NOT NULL DEFAULT '',
                attributes_json TEXT NOT NULL DEFAULT '{}',
                source_path TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE(import_id, source_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cad_bim_relations (
                id TEXT PRIMARY KEY,
                import_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cad_bim_properties (
                id TEXT PRIMARY KEY,
                import_id TEXT NOT NULL,
                element_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                name TEXT NOT NULL,
                value TEXT NOT NULL,
                value_type TEXT NOT NULL DEFAULT 'text',
                unit TEXT NOT NULL DEFAULT '',
                property_set TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        _ensure_column(conn, "cad_bim_imports", "profile", "TEXT NOT NULL DEFAULT 'generic'")
        _ensure_column(conn, "cad_bim_imports", "property_count", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "cad_bim_elements", "level", "TEXT NOT NULL DEFAULT ''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cad_bim_elements_import ON cad_bim_elements(import_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cad_bim_relations_import ON cad_bim_relations(import_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cad_bim_properties_import ON cad_bim_properties(import_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cad_bim_properties_element ON cad_bim_properties(element_id)")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, typedef: str) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {typedef}")


def latest_cad_bim_json_source(root: Path = CAD_BIM_ROOT) -> Path | None:
    source_dirs = [root / name for name in ("JSON", "Speckle", "IFC", "DWG", "RVT")]
    candidates = [
        p
        for source_dir in source_dirs
        if source_dir.exists()
        for p in source_dir.rglob("*")
        if p.suffix.lower() in {".json", ".jsonl"} and p.is_file()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def latest_speckle_source(root: Path = CAD_BIM_ROOT) -> Path | None:
    return latest_cad_bim_json_source(root)


def load_source_payload(source_path: Path) -> Any:
    suffix = source_path.suffix.lower()
    if suffix == ".jsonl":
        rows = []
        with source_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return rows
    if suffix == ".json":
        return json.loads(source_path.read_text(encoding="utf-8"))
    raise ValueError(f"unsupported CAD/BIM JSON source suffix: {suffix}")


def import_payload(
    payload: Any,
    *,
    source: str,
    source_kind: str = "speckle",
    profile: str | None = None,
    root: Path = CAD_BIM_ROOT,
    db_path: Path = CAD_BIM_DB_PATH,
    max_objects: int = 5000,
) -> CadBimImportResult:
    ensure_cad_bim_dirs(root)
    init_graph_db(db_path)
    import_id = uuid.uuid4().hex[:12]
    created_at = datetime.now(timezone.utc).isoformat()
    elements: list[dict[str, str]] = []
    relations: list[dict[str, str]] = []
    properties: list[dict[str, str]] = []
    resolved_profile = normalize_profile(profile or detect_profile(payload, source))
    _walk_payload(
        payload,
        import_id=import_id,
        profile=resolved_profile,
        elements=elements,
        relations=relations,
        properties=properties,
        max_objects=max_objects,
    )
    relations = _dedupe_relations(relations)
    projection_prefix = "cad_bim_speckle" if source_kind == "speckle" else "cad_bim_json"
    projection_path = root / "exports" / f"{projection_prefix}_{import_id}.md"
    projection_path.write_text(
        render_projection(import_id, source, resolved_profile, elements, relations, properties, source_kind=source_kind),
        encoding="utf-8",
    )

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO cad_bim_imports
            (id, source, source_kind, profile, created_at, element_count, relation_count, property_count, projection_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                import_id,
                source,
                source_kind,
                resolved_profile,
                created_at,
                len(elements),
                len(relations),
                len(properties),
                projection_path.as_posix(),
            ),
        )
        conn.executemany(
            """
            INSERT OR REPLACE INTO cad_bim_elements
            (id, import_id, source_id, speckle_type, object_type, name, layer, category, family, level, material,
             attributes_json, source_path, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    element["id"],
                    import_id,
                    element["source_id"],
                    element["speckle_type"],
                    element["object_type"],
                    element["name"],
                    element["layer"],
                    element["category"],
                    element["family"],
                    element["level"],
                    element["material"],
                    element["attributes_json"],
                    element["source_path"],
                    created_at,
                )
                for element in elements
            ],
        )
        conn.executemany(
            """
            INSERT INTO cad_bim_relations
            (id, import_id, source_id, target_id, relation_type, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    relation["id"],
                    import_id,
                    relation["source_id"],
                    relation["target_id"],
                    relation["relation_type"],
                    created_at,
                )
                for relation in relations
            ],
        )
        conn.executemany(
            """
            INSERT INTO cad_bim_properties
            (id, import_id, element_id, source_id, name, value, value_type, unit, property_set, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    prop["id"],
                    import_id,
                    prop["element_id"],
                    prop["source_id"],
                    prop["name"],
                    prop["value"],
                    prop["value_type"],
                    prop["unit"],
                    prop["property_set"],
                    created_at,
                )
                for prop in properties
            ],
        )

    return CadBimImportResult(
        import_id=import_id,
        source=source,
        profile=resolved_profile,
        elements=len(elements),
        relations=len(relations),
        properties=len(properties),
        projection_path=projection_path.as_posix(),
        db_path=db_path.as_posix(),
    )


def graph_summary(db_path: Path = CAD_BIM_DB_PATH) -> dict[str, Any]:
    init_graph_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        totals = {
            "imports": conn.execute("SELECT COUNT(*) FROM cad_bim_imports").fetchone()[0],
            "elements": conn.execute("SELECT COUNT(*) FROM cad_bim_elements").fetchone()[0],
            "relations": conn.execute("SELECT COUNT(*) FROM cad_bim_relations").fetchone()[0],
            "properties": conn.execute("SELECT COUNT(*) FROM cad_bim_properties").fetchone()[0],
        }
        imports = [
            dict(row)
            for row in conn.execute(
                """
                SELECT id, source, source_kind, profile, created_at, element_count, relation_count, property_count, projection_path
                FROM cad_bim_imports
                ORDER BY created_at DESC
                LIMIT 20
                """
            ).fetchall()
        ]
    return {"db_path": db_path.as_posix(), "totals": totals, "imports": imports}


def normalize_profile(profile: str | None) -> str:
    value = str(profile or "").strip().casefold().replace("-", "_")
    aliases = {
        "dwg": "autocad",
        "cad": "autocad",
        "autocad": "autocad",
        "civil3d": "autocad",
        "civil_3d": "autocad",
        "rvt": "revit",
        "revit": "revit",
        "ifc": "ifc",
        "excel": "excel",
        "xlsx": "excel",
        "powerbi": "excel",
        "power_bi": "excel",
    }
    return aliases.get(value, "generic")


def detect_profile(payload: Any, source: str = "") -> str:
    text = f"{source}\n{_profile_probe_text(payload)}".casefold()
    if any(token in text for token in ("revit", "revitobject", "built-elements.revit", "family", "category")):
        return "revit"
    if any(token in text for token in ("ifc", "ifcwall", "ifcbeam", "ifcspace", "ifcbuildingstorey", "property sets", "pset_")):
        return "ifc"
    if any(token in text for token in ("autocad", "civil3d", "layer", "block", "instance", "definition", ".dwg", ".dxf")):
        return "autocad"
    if any(token in text for token in ("excel", "xlsx", "worksheet", "sheet", "row", "column", "powerbi", "power bi")):
        return "excel"
    return "generic"


def render_projection(
    import_id: str,
    source: str,
    profile: str,
    elements: list[dict[str, str]],
    relations: list[dict[str, str]],
    properties: list[dict[str, str]] | None = None,
    source_kind: str = "json",
) -> str:
    relation_counts: dict[str, int] = {}
    for relation in relations:
        relation_counts[relation["source_id"]] = relation_counts.get(relation["source_id"], 0) + 1
        relation_counts[relation["target_id"]] = relation_counts.get(relation["target_id"], 0) + 1
    properties_by_source: dict[str, list[dict[str, str]]] = {}
    for prop in properties or []:
        properties_by_source.setdefault(prop["source_id"], []).append(prop)

    title_kind = "Speckle" if source_kind == "speckle" else "JSON"
    lines = [
        f"# CAD/BIM {title_kind} projection ({profile})",
        "",
        f"Import ID: {import_id}",
        f"Source: {source}",
        f"Source kind: {source_kind}",
        f"Profile: {profile}",
        "Domain: CAD_BIM",
        "Canonical format: cad_bim_graph.json",
        "Source formats: DWG, DXF, RVT, IFC, Excel/Power BI, Speckle",
        "",
    ]
    for element in elements:
        title = element["name"] or element["object_type"] or element["speckle_type"] or element["source_id"]
        lines.extend(_profile_projection_lines(profile, element, relation_counts.get(element["source_id"], 0)))
        props = properties_by_source.get(element["source_id"], [])
        if props:
            lines.append("- Properties:")
            for prop in props[:24]:
                unit = f" {prop['unit']}" if prop["unit"] else ""
                group = f" ({prop['property_set']})" if prop["property_set"] else ""
                lines.append(f"  - {prop['name']}{group}: {prop['value']}{unit}")
        attrs = json.loads(element["attributes_json"])
        if attrs:
            lines.append("- Attributes:")
            for key, value in sorted(attrs.items())[:24]:
                lines.append(f"  - {key}: {value}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _profile_projection_lines(profile: str, element: dict[str, str], relation_count: int) -> list[str]:
    title = element["name"] or element["object_type"] or element["speckle_type"] or element["source_id"]
    common = [
        f"## Element {title}",
        "",
        f"- Source ID: {element['source_id']}",
        f"- Speckle type: {element['speckle_type'] or '-'}",
        f"- Object type: {element['object_type'] or '-'}",
    ]
    if profile == "autocad":
        return [
            *common,
            f"- Layer: {element['layer'] or '-'}",
            f"- Block or instance: {element['family'] or element['category'] or '-'}",
            f"- Material: {element['material'] or '-'}",
            f"- Graph relations: {relation_count}",
        ]
    if profile == "revit":
        return [
            *common,
            f"- Category: {element['category'] or '-'}",
            f"- Family: {element['family'] or '-'}",
            f"- Level: {element['level'] or '-'}",
            f"- Material: {element['material'] or '-'}",
            f"- Graph relations: {relation_count}",
        ]
    if profile == "ifc":
        return [
            *common,
            f"- IFC class/entity: {element['object_type'] or element['speckle_type'] or '-'}",
            f"- Storey/level: {element['level'] or '-'}",
            f"- Material: {element['material'] or '-'}",
            f"- Property sets available: yes",
            f"- Graph relations: {relation_count}",
        ]
    if profile == "excel":
        return [
            *common,
            f"- Sheet/table: {element['category'] or element['layer'] or '-'}",
            f"- Row/key: {element['name'] or element['source_id']}",
            f"- Linked BIM object: {element['family'] or '-'}",
            f"- Graph relations: {relation_count}",
        ]
    return [
        *common,
        f"- Layer: {element['layer'] or '-'}",
        f"- Category: {element['category'] or '-'}",
        f"- Family: {element['family'] or '-'}",
        f"- Level: {element['level'] or '-'}",
        f"- Material: {element['material'] or '-'}",
        f"- Relations: {relation_count}",
    ]


def _walk_payload(
    value: Any,
    *,
    import_id: str,
    profile: str,
    elements: list[dict[str, str]],
    relations: list[dict[str, str]],
    properties: list[dict[str, str]],
    max_objects: int,
    parent_id: str | None = None,
    path: str = "$",
) -> None:
    if len(elements) >= max_objects:
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _walk_payload(
                item,
                import_id=import_id,
                profile=profile,
                elements=elements,
                relations=relations,
                properties=properties,
                max_objects=max_objects,
                parent_id=parent_id,
                path=f"{path}[{index}]",
            )
        return
    if not isinstance(value, dict):
        return

    source_id = _source_id(value, path)
    if _looks_like_element(value):
        element = _element_payload(value, import_id, source_id, path)
        elements.append(element)
        properties.extend(_properties_payload(value, import_id, element["id"], source_id))
        if parent_id:
            relations.append(
                {
                    "id": uuid.uuid4().hex,
                    "source_id": parent_id,
                    "target_id": source_id,
                    "relation_type": "contains",
                }
            )
        parent_id = source_id

    for key, child in value.items():
        if key in SKIP_KEYS:
            continue
        if key in PROPERTY_CONTAINER_KEYS:
            continue
        if key == "relations" and isinstance(child, list):
            relations.extend(_explicit_relations_payload(child))
            continue
        if key in CHILD_KEYS or isinstance(child, (list, dict)):
            _walk_payload(
                child,
                import_id=import_id,
                profile=profile,
                elements=elements,
                relations=relations,
                properties=properties,
                max_objects=max_objects,
                parent_id=parent_id,
                path=f"{path}.{key}",
            )


def _looks_like_element(value: dict[str, Any]) -> bool:
    return any(
        key in value
        for key in (
            "id",
            "speckle_type",
            "speckleType",
            "applicationId",
            "name",
            "category",
            "family",
            "layer",
            "parameters",
            "properties",
            "propertySets",
            "cells",
        )
    )


def _source_id(value: dict[str, Any], path: str) -> str:
    raw = value.get("id") or value.get("applicationId") or value.get("elementId")
    if raw:
        return str(raw)
    digest = hashlib.sha1(path.encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"path-{digest}"


def _element_payload(value: dict[str, Any], import_id: str, source_id: str, path: str) -> dict[str, str]:
    attrs = _compact_attrs(value)
    object_type = str(value.get("type") or value.get("object_type") or value.get("objectType") or "")
    speckle_type = str(value.get("speckle_type") or value.get("speckleType") or "")
    name = str(value.get("name") or value.get("Name") or value.get("mark") or value.get("type") or "")
    return {
        "id": f"{import_id}:{source_id}",
        "source_id": source_id,
        "speckle_type": speckle_type,
        "object_type": object_type,
        "name": name,
        "layer": str(value.get("layer") or value.get("Layer") or attrs.get("layer") or ""),
        "category": str(value.get("category") or attrs.get("category") or ""),
        "family": str(value.get("family") or attrs.get("family") or ""),
        "level": str(value.get("level") or value.get("Level") or value.get("storey") or attrs.get("level") or ""),
        "material": str(value.get("material") or attrs.get("material") or ""),
        "attributes_json": json.dumps(attrs, ensure_ascii=False, sort_keys=True),
        "source_path": path,
    }


def _properties_payload(value: dict[str, Any], import_id: str, element_id: str, source_id: str) -> list[dict[str, str]]:
    properties: list[dict[str, str]] = []
    for name, item in _iter_property_items(value):
        prop_value, value_type, unit = _property_value(item)
        if prop_value == "":
            continue
        properties.append(
            {
                "id": uuid.uuid4().hex,
                "import_id": import_id,
                "element_id": element_id,
                "source_id": source_id,
                "name": name,
                "value": prop_value,
                "value_type": value_type,
                "unit": unit,
                "property_set": _property_set_name(item),
            }
        )
    return properties


def _explicit_relations_payload(items: list[Any]) -> list[dict[str, str]]:
    relations: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        source_id = item.get("source_id") or item.get("sourceId") or item.get("from")
        target_id = item.get("target_id") or item.get("targetId") or item.get("to")
        if not source_id or not target_id:
            continue
        relations.append(
            {
                "id": str(item.get("id") or uuid.uuid4().hex),
                "source_id": str(source_id),
                "target_id": str(target_id),
                "relation_type": str(item.get("relation_type") or item.get("relationType") or item.get("type") or "related"),
            }
        )
    return relations


def _dedupe_relations(relations: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, str]] = []
    for relation in relations:
        key = (relation["source_id"], relation["target_id"], relation["relation_type"])
        if key in seen:
            continue
        seen.add(key)
        out.append(relation)
    return out


def _iter_property_items(value: dict[str, Any]) -> list[tuple[str, Any]]:
    items: list[tuple[str, Any]] = []
    for container_key in PROPERTY_CONTAINER_KEYS:
        container = value.get(container_key)
        if isinstance(container, dict):
            for key, item in container.items():
                if isinstance(item, dict) and any(isinstance(v, dict) for v in item.values()):
                    for child_key, child in item.items():
                        items.append((str(child_key), child))
                else:
                    items.append((str(key), item))
        elif isinstance(container, list):
            for index, item in enumerate(container):
                if isinstance(item, dict):
                    name = item.get("name") or item.get("Name") or item.get("key") or item.get("column") or f"{container_key}_{index}"
                    items.append((str(name), item))
    return items


def _property_value(item: Any) -> tuple[str, str, str]:
    unit = ""
    value = item
    if isinstance(item, dict):
        unit = str(item.get("unit") or item.get("units") or "")
        value = item.get("value", item.get("Value", item.get("displayValue", item.get("val", ""))))
    if value is None:
        return "", "null", unit
    if isinstance(value, bool):
        return ("true" if value else "false"), "bool", unit
    if isinstance(value, (int, float)):
        return str(value), "number", unit
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False)[:MAX_TEXT_VALUE]
        return text, "json", unit
    text = str(value).strip()
    if len(text) > MAX_TEXT_VALUE:
        text = text[:MAX_TEXT_VALUE] + "..."
    return text, "text", unit


def _property_set_name(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    return str(item.get("group") or item.get("parameterGroup") or item.get("propertySet") or item.get("set") or "")


def _profile_probe_text(payload: Any, limit: int = 12000) -> str:
    try:
        text = json.dumps(payload, ensure_ascii=False)
    except TypeError:
        text = str(payload)
    return text[:limit]


def _compact_attrs(value: dict[str, Any]) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for key, item in value.items():
        if key in CHILD_KEYS or key in SKIP_KEYS or key.startswith("@"):
            continue
        if isinstance(item, (dict, list)):
            continue
        text = str(item).strip()
        if not text:
            continue
        if len(text) > MAX_TEXT_VALUE:
            text = text[:MAX_TEXT_VALUE] + "..."
        attrs[str(key)] = text
    return attrs
