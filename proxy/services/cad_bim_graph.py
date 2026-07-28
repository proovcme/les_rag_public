"""Lightweight CAD/BIM graph store and text projection helpers."""

from __future__ import annotations

import hashlib
import json
import os
import re
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
    "tables",
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
    tables = _payload_tables(payload)
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
        render_projection(import_id, source, resolved_profile, elements, relations, properties, source_kind=source_kind, tables=tables),
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


def cad_bim_import_inventory(
    *,
    db_path: Path = CAD_BIM_DB_PATH,
    meta_db_path: str | Path | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """Read-only CAD/BIM import inventory with projection index status.

    This is an operator diagnostic: graph DB stays the source for imports, while
    MetaDB documents tell whether generated markdown projections are actually
    indexed in `CAD_BIM_Index`.
    """

    init_graph_db(db_path)
    safe_limit = max(1, min(int(limit or 200), 1000))
    warnings: list[str] = []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        total_imports = conn.execute("SELECT COUNT(*) FROM cad_bim_imports").fetchone()[0]
        totals = {
            "imports": total_imports,
            "elements": conn.execute("SELECT COUNT(*) FROM cad_bim_elements").fetchone()[0],
            "relations": conn.execute("SELECT COUNT(*) FROM cad_bim_relations").fetchone()[0],
            "properties": conn.execute("SELECT COUNT(*) FROM cad_bim_properties").fetchone()[0],
        }
        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT
                  i.id, i.source, i.source_kind, i.profile, i.created_at,
                  i.element_count, i.relation_count, i.property_count, i.projection_path,
                  (SELECT COUNT(*) FROM cad_bim_elements e WHERE e.import_id = i.id) AS actual_element_count,
                  (SELECT COUNT(*) FROM cad_bim_relations r WHERE r.import_id = i.id) AS actual_relation_count,
                  (SELECT COUNT(*) FROM cad_bim_properties p WHERE p.import_id = i.id) AS actual_property_count
                FROM cad_bim_imports i
                ORDER BY i.created_at DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        ]

    resolved_meta_db_path = Path(meta_db_path) if meta_db_path is not None else _default_meta_db_path()
    projection_docs, doc_warnings = _load_cad_bim_projection_docs(resolved_meta_db_path)
    warnings.extend(doc_warnings)

    imports: list[dict[str, Any]] = []
    duplicate_buckets: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        element_count = int(row.get("element_count") or 0)
        relation_count = int(row.get("relation_count") or 0)
        property_count = int(row.get("property_count") or 0)
        source_basename = _cad_bim_source_basename(row.get("source", ""))
        source_fingerprint = _cad_bim_source_fingerprint(
            row.get("source", ""),
            profile=row.get("profile", ""),
            element_count=element_count,
            relation_count=relation_count,
            property_count=property_count,
        )
        indexed_documents = _projection_docs_for_import(
            projection_docs,
            import_id=str(row["id"]),
            projection_path=str(row.get("projection_path") or ""),
        )
        projection_index_status = _projection_index_status(indexed_documents)
        item = {
            **row,
            "source_basename": source_basename,
            "source_fingerprint": source_fingerprint,
            "quality_status": _cad_bim_import_quality(element_count, relation_count),
            "indexed_count": len(indexed_documents),
            "indexed_documents": indexed_documents,
            "projection_index_status": projection_index_status,
        }
        imports.append(item)
        duplicate_buckets.setdefault(source_fingerprint, []).append(item)

    duplicate_groups = [
        {
            "source_fingerprint": fingerprint,
            "count": len(items),
            "import_ids": [item["id"] for item in items],
            "sources": [item["source"] for item in items],
            "profile": items[0].get("profile", ""),
            "element_count": items[0].get("element_count", 0),
            "relation_count": items[0].get("relation_count", 0),
            "property_count": items[0].get("property_count", 0),
        }
        for fingerprint, items in duplicate_buckets.items()
        if len(items) > 1
    ]

    minimal_count = sum(1 for item in imports if item["quality_status"] in {"empty", "minimal", "suspicious"})
    duplicate_indexed_count = sum(1 for item in imports if item["projection_index_status"] == "duplicate_indexed")
    totals.update(
        {
            "imports_returned": len(imports),
            "projection_documents": len(projection_docs),
            "duplicate_groups": len(duplicate_groups),
            "weak_imports": minimal_count,
            "duplicate_indexed_imports": duplicate_indexed_count,
        }
    )
    return {
        "db_path": db_path.as_posix(),
        "meta_db_path": resolved_meta_db_path.as_posix(),
        "limit": safe_limit,
        "totals": totals,
        "imports": imports,
        "duplicate_groups": duplicate_groups,
        "warnings": warnings,
    }


def _default_meta_db_path() -> Path:
    try:
        from backend.rag_config import rag_meta_db_path

        return Path(rag_meta_db_path())
    except Exception:  # noqa: BLE001
        return Path(os.getenv("RAG_META_DB_PATH", "data/les_meta_qwen.db"))


def _load_cad_bim_projection_docs(meta_db_path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    if not meta_db_path.exists():
        return [], [f"meta_db_not_found:{meta_db_path.as_posix()}"]
    warnings: list[str] = []
    try:
        with sqlite3.connect(meta_db_path) as conn:
            conn.row_factory = sqlite3.Row
            if not _sqlite_table_exists(conn, "documents"):
                return [], ["meta_db_documents_table_missing"]
            doc_columns = _sqlite_columns(conn, "documents")
            datasets_exists = _sqlite_table_exists(conn, "datasets")
            select_id = "d.id AS id" if "id" in doc_columns else "'' AS id"
            select_status = "d.status AS status" if "status" in doc_columns else "'' AS status"
            select_chunk_count = "COALESCE(d.chunk_count, 0) AS chunk_count" if "chunk_count" in doc_columns else "0 AS chunk_count"
            select_dataset_id = "d.dataset_id AS dataset_id" if "dataset_id" in doc_columns else "'' AS dataset_id"
            join = ""
            conditions = ["d.file_name LIKE '%cad_bim_json_%'", "d.file_name LIKE '%cad_bim_speckle_%'"]
            if datasets_exists and "dataset_id" in doc_columns:
                join = "LEFT JOIN datasets ds ON ds.id = d.dataset_id"
                conditions.append("ds.name = 'CAD_BIM_Index'")
            if "dataset_id" in doc_columns:
                conditions.append("d.dataset_id = 'CAD_BIM_Index'")
            rows = conn.execute(
                f"""
                SELECT {select_id}, d.file_name, {select_status}, {select_chunk_count}, {select_dataset_id}
                FROM documents d
                {join}
                WHERE d.file_name IS NOT NULL AND ({' OR '.join(conditions)})
                ORDER BY d.file_name
                """
            ).fetchall()
    except Exception as error:  # noqa: BLE001
        return [], [f"meta_db_projection_lookup_failed:{error}"]
    docs = []
    for row in rows:
        docs.append(
            {
                "id": str(row["id"] or ""),
                "file_name": str(row["file_name"] or ""),
                "status": str(row["status"] or ""),
                "chunk_count": int(row["chunk_count"] or 0),
                "dataset_id": str(row["dataset_id"] or "") if "dataset_id" in row.keys() else "",
            }
        )
    return docs, warnings


def _sqlite_table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def _sqlite_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _projection_docs_for_import(
    projection_docs: list[dict[str, Any]],
    *,
    import_id: str,
    projection_path: str,
) -> list[dict[str, Any]]:
    projection_name = Path(projection_path).name if projection_path else ""
    matches = []
    for doc in projection_docs:
        file_name = str(doc.get("file_name") or "")
        file_base = Path(file_name).name
        if import_id and import_id in file_name:
            matches.append(doc)
        elif projection_name and (file_base == projection_name or file_name.endswith(projection_name)):
            matches.append(doc)
    return matches


def _projection_index_status(indexed_documents: list[dict[str, Any]]) -> str:
    if not indexed_documents:
        return "not_indexed"
    if len(indexed_documents) > 1:
        return "duplicate_indexed"
    status = str(indexed_documents[0].get("status") or "").strip().upper()
    if status and status != "INDEXED":
        return status.lower()
    return "indexed"


def _cad_bim_source_basename(source: str) -> str:
    return Path(str(source or "")).name


def _cad_bim_source_fingerprint(
    source: str,
    *,
    profile: str,
    element_count: int,
    relation_count: int,
    property_count: int,
) -> str:
    name = _cad_bim_source_basename(source)
    stem = name[:-len(".cad_bim_graph.json")] if name.endswith(".cad_bim_graph.json") else Path(name).stem
    stem = re.sub(r"_[0-9a-f]{10,16}$", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"^kotelnaya_(?:repair_)?\d+[\s_.-]+", "", stem, flags=re.IGNORECASE)
    compact = re.sub(r"[^0-9a-zа-я]+", "", stem.casefold().replace("ё", "е"))
    return "|".join(
        [
            str(profile or "generic").casefold(),
            compact or stem.casefold() or name.casefold(),
            str(int(element_count or 0)),
            str(int(relation_count or 0)),
            str(int(property_count or 0)),
        ]
    )


def _cad_bim_import_quality(element_count: int, relation_count: int) -> str:
    if element_count <= 0:
        return "empty"
    if element_count <= 2 or relation_count <= 0:
        return "minimal"
    if element_count <= 10:
        return "suspicious"
    return "ok"


def lookup_element_context(
    source_id: str,
    *,
    import_id: str | None = None,
    db_path: Path = CAD_BIM_DB_PATH,
    relation_limit: int = 24,
    property_limit: int = 80,
) -> dict[str, Any] | None:
    """Return RAG-ready CAD/BIM context for a stable element source id.

    `source_id` is the external object id from the source graph. For IFC this is
    the GlobalId, which is the value the OBC viewer can recover from selection.
    """

    normalized_source_id = str(source_id or "").strip()
    if not normalized_source_id:
        return None
    init_graph_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        params: list[Any] = [normalized_source_id]
        import_filter = ""
        if import_id:
            import_filter = " AND e.import_id = ?"
            params.append(import_id)
        element = conn.execute(
            f"""
            SELECT
              e.id, e.import_id, e.source_id, e.speckle_type, e.object_type, e.name,
              e.layer, e.category, e.family, e.level, e.material, e.attributes_json,
              e.source_path, i.source, i.source_kind, i.profile, i.created_at,
              i.projection_path
            FROM cad_bim_elements e
            JOIN cad_bim_imports i ON i.id = e.import_id
            WHERE e.source_id = ?{import_filter}
            ORDER BY i.created_at DESC
            LIMIT 1
            """,
            params,
        ).fetchone()
        if not element:
            return None
        properties = [
            dict(row)
            for row in conn.execute(
                """
                SELECT name, value, value_type, unit, property_set
                FROM cad_bim_properties
                WHERE element_id = ?
                ORDER BY property_set, name
                LIMIT ?
                """,
                (element["id"], property_limit),
            ).fetchall()
        ]
        relations = [
            dict(row)
            for row in conn.execute(
                """
                SELECT source_id, target_id, relation_type
                FROM cad_bim_relations
                WHERE import_id = ? AND (source_id = ? OR target_id = ?)
                ORDER BY relation_type, source_id, target_id
                LIMIT ?
                """,
                (element["import_id"], normalized_source_id, normalized_source_id, relation_limit),
            ).fetchall()
        ]

    attrs = _safe_json_dict(element["attributes_json"])
    item = dict(element)
    item["attributes"] = attrs
    item.pop("attributes_json", None)
    title = item.get("name") or item.get("object_type") or item.get("speckle_type") or item["source_id"]
    prompt = _rag_prompt_for_element(item, properties, relations)
    return {
        "found": True,
        "source_id": normalized_source_id,
        "element": item,
        "properties": properties,
        "relations": relations,
        "rag_prompt": prompt,
        "summary": {
            "title": title,
            "import_id": item["import_id"],
            "profile": item["profile"],
            "source": item["source"],
            "projection_path": item["projection_path"],
            "properties": len(properties),
            "relations": len(relations),
        },
    }


def _safe_json_dict(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text or "{}")
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _rag_prompt_for_element(
    element: dict[str, Any],
    properties: list[dict[str, str]],
    relations: list[dict[str, str]],
) -> str:
    title = element.get("name") or element.get("object_type") or element.get("speckle_type") or element.get("source_id")
    descriptors = [
        f"Source ID / GlobalId: {element.get('source_id')}",
        f"Profile: {element.get('profile')}",
        f"Type: {element.get('object_type') or element.get('speckle_type') or '-'}",
        f"Category: {element.get('category') or '-'}",
        f"Family: {element.get('family') or '-'}",
        f"Level: {element.get('level') or '-'}",
        f"Material: {element.get('material') or '-'}",
        f"Source: {element.get('source') or '-'}",
    ]
    prop_lines = []
    for prop in properties[:16]:
        unit = f" {prop['unit']}" if prop.get("unit") else ""
        group = f" ({prop['property_set']})" if prop.get("property_set") else ""
        prop_lines.append(f"- {prop['name']}{group}: {prop['value']}{unit}")
    relation_lines = [
        f"- {relation['source_id']} --{relation['relation_type']}--> {relation['target_id']}"
        for relation in relations[:12]
    ]
    return "\n".join(
        [
            f"Расскажи по BIM/CAD элементу `{title}`.",
            "Используй CAD/BIM индекс LES и связанные документы. Проверь назначение, параметры, связи, возможные замечания и что важно инженеру.",
            "",
            *descriptors,
            "",
            "Known properties:",
            *(prop_lines or ["- нет сохранённых свойств"]),
            "",
            "Known graph relations:",
            *(relation_lines or ["- нет связей"]),
        ]
    )


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


def _aggregate_projection_lines(
    elements: list[dict[str, str]],
    properties_by_source: dict[str, list[dict[str, str]]],
) -> list[str]:
    """W6.1 — сводные чанки «этаж × система × категория» поверх поэлементных.
    Отвечает на агрегатные вопросы («какие воздуховоды на 3 этаже», «сколько…»),
    на которые поэлементный ретрив слаб. 0 LLM: группировка + словарь системы."""
    if not elements:
        return []
    try:  # система — детерминированно (словарь категории), ленивый импорт против цикла
        from proxy.services.ontology_service import derive_system
    except Exception:
        def derive_system(category, object_type, family, system_prop=""):
            return category or "—"

    # системное свойство элемента (если есть) → точнее, чем словарь
    sys_prop_names = {"system", "система", "system name", "имя системы", "system type", "тип системы"}
    groups: dict[tuple[str, str, str], list[dict[str, str]]] = {}
    floor_counts: dict[str, int] = {}
    for el in elements:
        floor = (el.get("level") or "").strip() or "—"
        category = (el.get("category") or "").strip() or "—"
        sprop = ""
        for p in properties_by_source.get(el.get("source_id", ""), []):
            if (p.get("name") or "").strip().lower() in sys_prop_names and (p.get("value") or "").strip():
                sprop = p["value"].strip()
                break
        system = derive_system(el.get("category", ""), el.get("object_type", ""), el.get("family", ""), sprop)
        groups.setdefault((floor, system, category), []).append(el)
        floor_counts[floor] = floor_counts.get(floor, 0) + 1

    systems = {k[1] for k in groups}
    categories = {k[2] for k in groups}
    lines = [
        "## BIM summary (aggregate)",
        "",
        f"- Elements: {len(elements)} · Floors: {len(floor_counts)} · Systems: {len(systems)} · Categories: {len(categories)}",
        "- By floor: " + ", ".join(f"{f} ({n})" for f, n in sorted(floor_counts.items(), key=lambda kv: -kv[1])[:20]),
        "",
    ]
    for (floor, system, category), els in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        names = [e.get("name") or e.get("object_type") or e.get("source_id") for e in els]
        lines.append(f"## Aggregate {floor} / {system} / {category}")
        lines.append("")
        lines.append(f"- Floor/Этаж: {floor}")
        lines.append(f"- System/Система: {system}")
        lines.append(f"- Category/Категория: {category}")
        lines.append(f"- Count/Количество: {len(els)}")
        lines.append("- Elements/Элементы: " + ", ".join(str(n) for n in names[:40]) + (" …" if len(names) > 40 else ""))
        # общие свойства (одинаковое значение у всех элементов группы)
        common: dict[str, set] = {}
        for e in els:
            for p in properties_by_source.get(e.get("source_id", ""), []):
                common.setdefault(p["name"], set()).add(p.get("value", ""))
        shared = [(n, next(iter(v))) for n, v in common.items() if len(v) == 1 and next(iter(v))]
        if shared:
            lines.append("- Common properties/Общие свойства: " + ", ".join(f"{n}={v}" for n, v in shared[:8]))
        lines.append("")
    return lines


def render_projection(
    import_id: str,
    source: str,
    profile: str,
    elements: list[dict[str, str]],
    relations: list[dict[str, str]],
    properties: list[dict[str, str]] | None = None,
    source_kind: str = "json",
    tables: list[dict[str, Any]] | None = None,
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
    lines.extend(_drawn_table_projection_lines(tables or []))
    # W6.1 — агрегатные сводки (этаж×система×категория) перед поэлементными чанками
    lines.extend(_aggregate_projection_lines(elements, properties_by_source))
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


def _payload_tables(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("tables"), list):
        return [item for item in payload["tables"] if isinstance(item, dict)]
    return []


def _markdown_cell(value: Any) -> str:
    text = str(value or "").replace("\r", "\n").replace("\n", "<br>").strip()
    return text.replace("|", "\\|")


def _row_cells(row: dict[str, Any]) -> list[str]:
    cells = row.get("cells")
    if not isinstance(cells, list):
        return []
    out: list[str] = []
    for cell in cells:
        if isinstance(cell, dict):
            out.append(str(cell.get("text") or cell.get("value") or ""))
        else:
            out.append(str(cell or ""))
    return out


_POSITION_TOKEN_RE = re.compile(r"^\s*(\d{1,4})(?:[.)])?\s*$")
_LEADING_POSITION_RE = re.compile(r"^\s*(\d{1,4})(?:[.)])?\s+(.+?)\s*$", re.S)
_TRAILING_POSITION_RE = re.compile(r"^(.+?)\s+(\d{1,4})(?:[.)])?\s*$", re.S)
_UNIT_TOKEN_RE = re.compile(r"^(шт\.?|компл\.?|к-т|м|м2|м3|кг|т|л|пог\.?\s*м)\s*$", re.I)
_NUMBER_TOKEN_RE = re.compile(r"^\d+(?:[,.]\d+)?$")


def _normalize_table_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\r", "\n").strip())


def _split_position_cell(value: str) -> tuple[str | None, str]:
    text = _normalize_table_text(value)
    if not text:
        return None, ""
    match = _POSITION_TOKEN_RE.match(text)
    if match:
        return match.group(1), ""
    match = _LEADING_POSITION_RE.match(text)
    if match:
        return match.group(1), match.group(2).strip()
    match = _TRAILING_POSITION_RE.match(text)
    if match:
        return match.group(2), match.group(1).strip()
    return None, text


def _is_unit_text(value: str) -> bool:
    return bool(_UNIT_TOKEN_RE.match(_normalize_table_text(value)))


def _is_number_text(value: str) -> bool:
    return bool(_NUMBER_TOKEN_RE.match(_normalize_table_text(value)))


def _logical_spec_positions(rows: list[dict[str, Any]], *, limit: int = 80) -> list[str]:
    """Best-effort logical rows for CAD schedules drawn with primitive lines."""

    positions: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    def finish_current() -> None:
        nonlocal current
        if current is not None:
            positions.append(current)
            current = None

    for row in sorted(rows, key=_row_index):
        if _row_index(row) < 2:
            continue
        cells = _row_cells(row)
        nonempty = [(idx, _normalize_table_text(cell)) for idx, cell in enumerate(cells) if cell.strip()]
        if not nonempty:
            continue

        found: tuple[str, int, str] | None = None
        for idx, text in nonempty[:4]:
            pos, remainder = _split_position_cell(text)
            if pos:
                found = (pos, idx, remainder)
                break

        if found:
            finish_current()
            pos, pos_idx, remainder = found
            current = {
                "position": pos,
                "name_parts": [],
                "mark_parts": [],
                "manufacturer": "",
                "unit": "",
                "qty": "",
                "row": _row_index(row),
            }
            candidates: list[tuple[int, str]] = []
            if remainder:
                candidates.append((pos_idx, remainder))
            for idx, text in nonempty:
                if idx == pos_idx:
                    continue
                candidates.append((idx, text))

            unit_item = next(((idx, text) for idx, text in candidates if _is_unit_text(text)), None)
            unit_idx = unit_item[0] if unit_item else None
            if unit_item:
                current["unit"] = unit_item[1]
                qty_item = next(
                    ((idx, text) for idx, text in candidates if idx > unit_idx and _is_number_text(text)),
                    None,
                )
                if qty_item:
                    current["qty"] = qty_item[1]

            before_unit = [(idx, text) for idx, text in candidates if unit_idx is None or idx < unit_idx]
            if before_unit:
                current["name_parts"].append(before_unit[0][1])
            if len(before_unit) >= 2:
                current["mark_parts"].append(before_unit[1][1])
            if len(before_unit) >= 3:
                current["manufacturer"] = before_unit[-1][1]
            continue

        if current is None:
            continue

        for idx, text in nonempty:
            if _is_unit_text(text) or _is_number_text(text):
                continue
            if idx <= 2:
                current["name_parts"].append(text)
            elif idx <= 5 and len(current["mark_parts"]) < 3:
                current["mark_parts"].append(text)

    finish_current()

    lines: list[str] = []
    for item in positions[:limit]:
        name = " ".join(part for part in item["name_parts"] if part).strip()
        mark = " ".join(part for part in item["mark_parts"] if part).strip()
        bits = [f"position {item['position']} / позиция {item['position']}"]
        if name:
            bits.append(f"name: {name}")
        if mark:
            bits.append(f"mark: {mark}")
        if item.get("manufacturer"):
            bits.append(f"manufacturer: {item['manufacturer']}")
        if item.get("unit"):
            bits.append(f"unit: {item['unit']}")
        if item.get("qty"):
            bits.append(f"qty: {item['qty']}")
        bits.append(f"source_row: {item['row']}")
        lines.append(" | ".join(_markdown_cell(bit) for bit in bits))
    return lines


def _drawn_table_projection_lines(tables: list[dict[str, Any]]) -> list[str]:
    if not tables:
        return []
    lines = [
        "## CAD drawn tables",
        "",
        f"- Tables detected: {len(tables)}",
        "- Source: line/polyline grid plus TEXT/MTEXT assigned to cells",
        "",
    ]
    for index, table in enumerate(tables[:12], start=1):
        rows = [row for row in table.get("rows", []) if isinstance(row, dict)]
        nonempty_rows = [row for row in rows if any(_row_cells(row))]
        if not nonempty_rows:
            continue
        column_count = int(table.get("column_count") or 0)
        used_columns = [
            col
            for col in range(column_count)
            if any(col < len(_row_cells(row)) and _row_cells(row)[col].strip() for row in nonempty_rows)
        ][:24]
        if not used_columns:
            continue
        bbox = table.get("bbox") if isinstance(table.get("bbox"), dict) else {}
        bbox_text = ""
        if bbox:
            bbox_text = f" x={bbox.get('x0')}..{bbox.get('x1')}, y={bbox.get('y0')}..{bbox.get('y1')}"
        lines.extend(
            [
                f"## CAD drawn table {table.get('id') or index}",
                "",
                f"- Rows: {table.get('row_count') or len(rows)}",
                f"- Columns: {column_count}",
                f"- Non-empty cells: {table.get('nonempty_cell_count') or '-'}",
                f"- BBox:{bbox_text or ' -'}",
                "",
            ]
        )
        data_rows = [row for row in nonempty_rows if _row_index(row) >= 2]
        logical_positions = _logical_spec_positions(nonempty_rows)
        if logical_positions:
            lines.append(f"### CAD drawn table {table.get('id') or index} first positions / первые три позиции")
            lines.append("")
            for line in logical_positions[:12]:
                lines.append(f"- {line}")
            lines.append("")
            lines.append(f"### CAD drawn table {table.get('id') or index} logical positions / позиции спецификации")
            lines.append("")
            lines.append("- Logical spec positions / позиции спецификации:")
            for line in logical_positions[:40]:
                lines.append(f"  - {line}")
            lines.append("")
        if data_rows:
            lines.append("- First data rows / первые позиции:")
            for row in data_rows[:12]:
                compact = _compact_row_text(row)
                if compact:
                    lines.append(f"  - row {row.get('index', '')}: {_markdown_cell(compact)}")
            lines.append("")
            lines.append("- Data rows:")
            for row in data_rows[:80]:
                compact = _compact_row_text(row)
                if compact:
                    lines.append(f"  - row {row.get('index', '')}: {_markdown_cell(compact)}")
            lines.append("")
        lines.append("- Compact non-empty rows:")
        for row in nonempty_rows[:80]:
            compact = _compact_row_text(row)
            if compact:
                lines.append(f"  - row {row.get('index', '')}: {_markdown_cell(compact)}")
        lines.append("")
        header = ["row", *[f"C{col + 1}" for col in used_columns]]
        lines.append("| " + " | ".join(header) + " |")
        lines.append("| " + " | ".join(["---"] * len(header)) + " |")
        for row in nonempty_rows[:80]:
            cells = _row_cells(row)
            rendered = [str(row.get("index", ""))]
            rendered.extend(_markdown_cell(cells[col] if col < len(cells) else "") for col in used_columns)
            lines.append("| " + " | ".join(rendered) + " |")
        if len(nonempty_rows) > 80:
            lines.append(f"| ... | trimmed: {len(nonempty_rows) - 80} more non-empty rows | |")
        lines.append("")
    if len(tables) > 12:
        lines.append(f"- Trimmed tables in projection: {len(tables) - 12}")
        lines.append("")
    return lines


def _row_index(row: dict[str, Any]) -> int:
    try:
        return int(row.get("index", 0))
    except (TypeError, ValueError):
        return 0


def _compact_row_text(row: dict[str, Any]) -> str:
    compact = " | ".join(cell.strip() for cell in _row_cells(row) if cell.strip())
    if len(compact) > 1200:
        compact = compact[:1200].rstrip() + "..."
    return compact


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
