#!/usr/bin/env python3
"""Extract IFC STEP records into LES CAD/BIM JSON and optionally import them."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT_TYPES = {"IFCPROJECT", "IFCSITE", "IFCBUILDING", "IFCBUILDINGSTOREY", "IFCSPACE"}
RELATION_TYPES = {
    "IFCRELAGGREGATES": "contains",
    "IFCRELCONTAINEDINSPATIALSTRUCTURE": "spatial",
    "IFCRELDEFINESBYTYPE": "type",
    "IFCRELASSOCIATESMATERIAL": "material",
}
SKIP_GLOBAL_TYPES = {
    "IFCPROPERTYSET",
    "IFCELEMENTQUANTITY",
    "IFCRELAGGREGATES",
    "IFCRELASSOCIATESMATERIAL",
    "IFCRELCONTAINEDINSPATIALSTRUCTURE",
    "IFCRELDEFINESBYPROPERTIES",
    "IFCRELDEFINESBYTYPE",
}


@dataclass(frozen=True)
class StepRecord:
    ref: str
    entity: str
    args: list[str]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _read_ifc_text(source: Path) -> tuple[str, str]:
    suffix = source.suffix.lower()
    if suffix == ".ifc":
        return source.read_text(encoding="utf-8", errors="replace"), source.name
    if suffix == ".ifczip":
        with zipfile.ZipFile(source) as archive:
            names = [name for name in archive.namelist() if name.lower().endswith(".ifc")]
            if not names:
                raise SystemExit(f"IFCZIP has no .ifc member: {source}")
            name = names[0]
            return archive.read(name).decode("utf-8", errors="replace"), f"{source.name}:{name}"
    raise SystemExit(f"Expected .ifc or .ifczip, got: {source}")


def _records(text: str) -> dict[str, StepRecord]:
    records: dict[str, StepRecord] = {}
    for match in re.finditer(r"#(\d+)\s*=\s*([A-Z0-9_]+)\s*\(", text):
        start = match.end() - 1
        end = _matching_paren(text, start)
        if end < 0:
            continue
        ref = f"#{match.group(1)}"
        entity = match.group(2).upper()
        records[ref] = StepRecord(ref=ref, entity=entity, args=_split_args(text[start + 1 : end]))
    return records


def _matching_paren(text: str, start: int) -> int:
    depth = 0
    in_string = False
    index = start
    while index < len(text):
        char = text[index]
        if in_string:
            if char == "'":
                if index + 1 < len(text) and text[index + 1] == "'":
                    index += 2
                    continue
                in_string = False
            index += 1
            continue
        if char == "'":
            in_string = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return -1


def _split_args(text: str) -> list[str]:
    args: list[str] = []
    start = 0
    depth = 0
    in_string = False
    index = 0
    while index < len(text):
        char = text[index]
        if in_string:
            if char == "'":
                if index + 1 < len(text) and text[index + 1] == "'":
                    index += 2
                    continue
                in_string = False
            index += 1
            continue
        if char == "'":
            in_string = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            args.append(text[start:index].strip())
            start = index + 1
        index += 1
    tail = text[start:].strip()
    if tail:
        args.append(tail)
    return args


def _string(token: str) -> str:
    token = token.strip()
    if token in {"$", "*"}:
        return ""
    if len(token) >= 2 and token[0] == "'" and token[-1] == "'":
        return token[1:-1].replace("''", "'")
    return ""


def _refs(token: str) -> list[str]:
    return re.findall(r"#\d+", token)


def _typed_value(token: str) -> tuple[Any, str, str]:
    token = token.strip()
    if token in {"$", "*"}:
        return "", "empty", ""
    match = re.match(r"([A-Z0-9_]+)\((.*)\)$", token)
    unit = ""
    value_type = "text"
    inner = token
    if match:
        value_type = match.group(1).removeprefix("IFC").casefold()
        inner = match.group(2).strip()
    if inner == ".T.":
        return True, value_type or "boolean", unit
    if inner == ".F.":
        return False, value_type or "boolean", unit
    text = _string(inner)
    if text:
        return text, value_type, unit
    try:
        if any(char in inner for char in ".E"):
            return float(inner), value_type or "number", unit
        return int(inner), value_type or "number", unit
    except ValueError:
        return inner, value_type, unit


def _is_product_record(record: StepRecord) -> bool:
    if not record.args or not _looks_like_guid(_string(record.args[0])):
        return False
    if record.entity in SKIP_GLOBAL_TYPES or record.entity.startswith("IFCREL"):
        return False
    if record.entity.endswith("TYPE") and record.entity not in ROOT_TYPES:
        return False
    if record.entity in ROOT_TYPES:
        return True
    return len(record.args) >= 7 and (record.args[5].startswith("#") or record.args[6].startswith("#"))


def _looks_like_guid(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9A-Za-z_$]{22}", value))


def _product_element(record: StepRecord, source_name: str) -> dict[str, Any]:
    guid = _string(record.args[0])
    name = _string(record.args[2]) if len(record.args) > 2 else ""
    description = _string(record.args[3]) if len(record.args) > 3 else ""
    object_type = _string(record.args[4]) if len(record.args) > 4 else ""
    tag = _string(record.args[7]) if len(record.args) > 7 else ""
    props: dict[str, Any] = {
        "global_id": guid,
        "ifc_ref": record.ref,
        "ifc_class": record.entity,
    }
    if description:
        props["Description"] = description
    if object_type:
        props["ObjectType"] = object_type
    if tag:
        props["Tag"] = tag
    return {
        "id": guid,
        "type": record.entity,
        "name": name or object_type or guid,
        "category": _category(record.entity),
        "family": object_type,
        "material": "",
        "properties": props,
        "source_path": source_name,
    }


def _category(entity: str) -> str:
    text = entity.removeprefix("IFC")
    if text.endswith("STANDARDCASE"):
        text = text.removesuffix("STANDARDCASE")
    return text.title().replace("_", " ")


def _property_sets(records: dict[str, StepRecord]) -> dict[str, dict[str, dict[str, Any]]]:
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for ref, record in records.items():
        if record.entity not in {"IFCPROPERTYSET", "IFCELEMENTQUANTITY"}:
            continue
        name = _string(record.args[2]) if len(record.args) > 2 else ref
        props: dict[str, dict[str, Any]] = {}
        for prop_ref in _refs(record.args[4] if len(record.args) > 4 else ""):
            prop = records.get(prop_ref)
            if not prop:
                continue
            if prop.entity == "IFCPROPERTYSINGLEVALUE":
                prop_name = _string(prop.args[0]) if prop.args else prop_ref
                value, value_type, unit = _typed_value(prop.args[2] if len(prop.args) > 2 else "")
                item = {"value": value, "value_type": value_type}
                if unit:
                    item["unit"] = unit
                props[prop_name] = item
            elif prop.entity.startswith("IFCQUANTITY"):
                prop_name = _string(prop.args[0]) if prop.args else prop_ref
                value, value_type, unit = _typed_value(prop.args[-1] if prop.args else "")
                props[prop_name] = {"value": value, "value_type": value_type, "unit": unit}
        out[ref] = {"name": name, "properties": props}
    return out


def _material_name(ref: str, records: dict[str, StepRecord]) -> str:
    record = records.get(ref)
    if not record:
        return ref
    if record.entity == "IFCMATERIAL":
        return _string(record.args[0]) if record.args else ref
    names = [_material_name(child, records) for child in _refs(",".join(record.args))]
    names = [name for name in names if name and not name.startswith("#")]
    return ", ".join(dict.fromkeys(names)) if names else record.entity


def _attach_properties_and_materials(
    elements_by_ref: dict[str, dict[str, Any]],
    records: dict[str, StepRecord],
) -> list[dict[str, str]]:
    relations: list[dict[str, str]] = []
    psets = _property_sets(records)
    for record in records.values():
        if record.entity == "IFCRELDEFINESBYPROPERTIES" and len(record.args) >= 6:
            pset = psets.get(record.args[5])
            if not pset:
                continue
            for target_ref in _refs(record.args[4]):
                element = elements_by_ref.get(target_ref)
                if not element:
                    continue
                element.setdefault("propertySets", {})[pset["name"]] = pset["properties"]
                relations.append({"source_id": element["id"], "target_id": pset["name"], "relation_type": "has_properties"})
        elif record.entity == "IFCRELASSOCIATESMATERIAL" and len(record.args) >= 6:
            material = _material_name(record.args[5], records)
            for target_ref in _refs(record.args[4]):
                element = elements_by_ref.get(target_ref)
                if not element:
                    continue
                element["material"] = material
                element.setdefault("properties", {})["Material"] = material
                relations.append({"source_id": element["id"], "target_id": material, "relation_type": "has_material"})
    return relations


def _explicit_relations(elements_by_ref: dict[str, dict[str, Any]], records: dict[str, StepRecord]) -> list[dict[str, str]]:
    relations: list[dict[str, str]] = []
    for record in records.values():
        relation_type = RELATION_TYPES.get(record.entity)
        if not relation_type:
            continue
        if record.entity == "IFCRELAGGREGATES" and len(record.args) >= 6:
            parent = elements_by_ref.get(record.args[4])
            for child_ref in _refs(record.args[5]):
                child = elements_by_ref.get(child_ref)
                if parent and child:
                    relations.append({"source_id": parent["id"], "target_id": child["id"], "relation_type": relation_type})
        elif record.entity == "IFCRELCONTAINEDINSPATIALSTRUCTURE" and len(record.args) >= 6:
            container = elements_by_ref.get(record.args[5])
            for child_ref in _refs(record.args[4]):
                child = elements_by_ref.get(child_ref)
                if container and child:
                    relations.append({"source_id": container["id"], "target_id": child["id"], "relation_type": relation_type})
        elif record.entity == "IFCRELDEFINESBYTYPE" and len(record.args) >= 6:
            type_ref = record.args[5]
            type_record = records.get(type_ref)
            type_name = _string(type_record.args[2]) if type_record and len(type_record.args) > 2 else type_ref
            for child_ref in _refs(record.args[4]):
                child = elements_by_ref.get(child_ref)
                if child:
                    child["family"] = type_name
                    child.setdefault("properties", {})["Type"] = type_name
                    relations.append({"source_id": child["id"], "target_id": type_name, "relation_type": relation_type})
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


def extract_ifc(source: Path, *, max_products: int = 50000) -> dict[str, Any]:
    text, source_name = _read_ifc_text(source)
    records = _records(text)
    schema = ""
    schema_match = re.search(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", text)
    if schema_match:
        schema = schema_match.group(1)
    elements_by_ref: dict[str, dict[str, Any]] = {}
    model_id = f"ifc:{source.stem}"
    for record in records.values():
        if len(elements_by_ref) >= max_products:
            break
        if _is_product_record(record):
            elements_by_ref[record.ref] = _product_element(record, source_name)
    relations = [{"source_id": model_id, "target_id": element["id"], "relation_type": "contains"} for element in elements_by_ref.values()]
    relations.extend(_explicit_relations(elements_by_ref, records))
    relations.extend(_attach_properties_and_materials(elements_by_ref, records))
    elements = list(elements_by_ref.values())
    return {
        "id": model_id,
        "type": "IFCModel",
        "name": source.stem,
        "source_format": "ifc",
        "source_path": source.as_posix(),
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "properties": {
            "schema": schema,
            "source_file": source_name,
            "product_count": len(elements),
            "step_record_count": len(records),
        },
        "elements": elements,
        "relations": _dedupe_relations(relations),
    }


def default_output(source: Path) -> Path:
    return _repo_root() / "RAG_Content" / "CAD_BIM" / "JSON" / f"{source.stem}.cad_bim_graph.json"


def post_import(proxy_url: str, output: Path, api_key: str = "") -> dict[str, Any]:
    url = proxy_url.rstrip("/") + "/api/cad-bim/import"
    payload = {"source_path": output.as_posix(), "source_type": "ifc"}
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="IFC or IFCZIP source file")
    parser.add_argument("--out", default="", help="Output JSON path")
    parser.add_argument("--max-products", type=int, default=50000)
    parser.add_argument("--import-to-les", action="store_true", help="POST JSON to /api/cad-bim/import after extraction")
    parser.add_argument("--proxy-url", default="http://127.0.0.1:8050")
    parser.add_argument("--api-key", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    source = Path(args.source).expanduser().resolve()
    if not source.exists():
        raise SystemExit(f"source not found: {source}")
    output = Path(args.out).expanduser() if args.out else default_output(source)
    if not output.is_absolute():
        output = (_repo_root() / output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = extract_ifc(source, max_products=args.max_products)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "extracted", "source": source.as_posix(), "out": output.as_posix(), "elements": len(payload["elements"]), "relations": len(payload["relations"])}, ensure_ascii=False))
    if args.import_to_les:
        result = post_import(args.proxy_url, output, args.api_key)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
