"""Read-only navigation summary over electrical manifests.

This service is a model-facing reading aid. It must not turn extractor coverage
gaps into a code-side verdict that the electrical section is absent or unusable.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


_DASHES = str.maketrans({"–": "-", "—": "-", "−": "-", "‑": "-"})
MAX_ISSUE_EXAMPLES_PER_TYPE = 5


def build_electrical_evidence_summary(
    schematic_manifests: list[dict[str, Any]] | None = None,
    material_manifests: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a source-backed electrical evidence summary from extractor manifests."""
    schematic_manifests = schematic_manifests or []
    material_manifests = material_manifests or []
    load_rows = _load_rows(schematic_manifests)
    circuits = _candidate_circuits(schematic_manifests)
    material_rows = _material_rows(material_manifests)
    cable_materials = [row for row in material_rows if row.get("item_kind") == "cable"]
    summary = {
        "schema": "electrical_evidence_summary_v1",
        "input_files": _input_files(schematic_manifests, material_manifests),
        "model_reading_contract": _model_reading_contract(),
        "summary": {
            "load_rows": len(load_rows),
            "candidate_circuits": len(circuits),
            "material_rows": len(material_rows),
            "cable_material_rows": len(cable_materials),
            "so_rows": sum(1 for row in material_rows if row.get("doc_role") == "so"),
            "vor_rows": sum(1 for row in material_rows if row.get("doc_role") == "vor"),
        },
        "load_aggregates_by_panel": _load_aggregates_by_panel(load_rows),
        "cable_inventory": _cable_inventory(cable_materials),
        "equipment_inventory": _equipment_inventory(material_rows),
        "load_to_material_cable_matches": _load_to_material_cable_matches(load_rows, cable_materials),
        "so_to_vor_seeds": _so_to_vor_seeds(material_rows),
        "source_navigation": _source_navigation(schematic_manifests, material_manifests),
        "issue_counts": {},
        "issues": [],
    }
    all_issues = _issues(load_rows, circuits, cable_materials, summary["load_to_material_cable_matches"])
    summary["issue_counts"] = _issue_counts(all_issues)
    summary["issues"] = _issue_examples(all_issues)
    summary["summary"]["issue_count"] = len(all_issues)
    summary["summary"]["issue_examples"] = len(summary["issues"])
    summary["summary"]["so_to_vor_seed_rows"] = len(summary["so_to_vor_seeds"])
    return summary


def build_electrical_evidence_summary_from_files(paths: list[str | Path]) -> dict[str, Any]:
    """Load manifest JSON files and build an electrical summary."""
    import json

    schematics: list[dict[str, Any]] = []
    materials: list[dict[str, Any]] = []
    unknown: list[str] = []
    for item in paths:
        path = Path(item)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            unknown.append(path.as_posix())
            continue
        schema = payload.get("schema")
        if schema == "electrical_schematic_manifest_v1":
            schematics.append(payload)
        elif schema == "electrical_material_manifest_v1":
            materials.append(payload)
        else:
            unknown.append(path.as_posix())
    result = build_electrical_evidence_summary(schematics, materials)
    if unknown:
        result.setdefault("warnings", []).append({"unknown_manifest_files": unknown})
    return result


def _input_files(schematic_manifests: list[dict[str, Any]], material_manifests: list[dict[str, Any]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for payload in schematic_manifests + material_manifests:
        out.append({
            "schema": str(payload.get("schema") or ""),
            "file_name": str(payload.get("file_name") or ""),
            "source_path": str(payload.get("source_path") or ""),
        })
    return out


def _model_reading_contract() -> dict[str, Any]:
    return {
        "role": "navigation_context_for_model",
        "use_for": [
            "ориентировать модель в составе ЭС/ЭОМ источников",
            "показывать положительные факты: нагрузки, щиты, кабели, оборудование, СО/ВОР строки",
            "давать source_ref для инженерного разбора и дальнейшего добора листов",
        ],
        "do_not_use_for": [
            "кодовый отказ от разбора раздела ЭС",
            "утверждение, что раздел ЭС отсутствует, только из-за missing fields",
            "финальная проверка правильности кабеля, автомата, схемы или норм",
            "выбор сметных норм или готовая ВОР без решения модели",
        ],
        "gap_semantics": (
            "issue_counts and issues are extractor coverage gaps or reconciliation prompts. "
            "They are not design defects and not proof that a source file is absent."
        ),
        "answer_guidance": (
            "If electrical input files, load rows, material rows or cable inventory are present, "
            "continue the engineering read from those facts. State limits narrowly and ask/open "
            "target files only for missing layers."
        ),
    }


def _source_navigation(
    schematic_manifests: list[dict[str, Any]],
    material_manifests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for manifest in schematic_manifests:
        file_name = _clean(manifest.get("file_name") or "")
        summary = manifest.get("summary") or {}
        items.append(
            {
                "file_name": file_name,
                "source_path": manifest.get("source_path") or "",
                "schema": manifest.get("schema") or "",
                "discipline_hint": _discipline_hint(file_name),
                "role_hint": _schematic_role_hint(file_name, summary),
                "load_rows": int(summary.get("load_rows") or 0),
                "candidate_circuits": int(summary.get("candidate_circuits") or 0),
                "pages_read": int(manifest.get("pages_read") or 0),
            }
        )
    for manifest in material_manifests:
        file_name = _clean(manifest.get("file_name") or "")
        row_counts: Counter[str] = Counter()
        doc_roles: Counter[str] = Counter()
        for page in manifest.get("pages") or []:
            for row in page.get("material_rows") or []:
                row_counts[str(row.get("item_kind") or "material")] += 1
                doc_roles[str(row.get("doc_role") or "unknown")] += 1
        items.append(
            {
                "file_name": file_name,
                "source_path": manifest.get("source_path") or "",
                "schema": manifest.get("schema") or "",
                "discipline_hint": _discipline_hint(file_name),
                "role_hint": _material_role_hint(file_name, doc_roles),
                "material_rows_by_kind": dict(sorted(row_counts.items())),
                "doc_roles": dict(sorted(doc_roles.items())),
                "pages_read": int(manifest.get("pages_read") or 0),
            }
        )
    return items


def _load_rows(manifests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for manifest in manifests:
        file_name = _clean(manifest.get("file_name") or "")
        panel_hint = _panel_from_file_name(file_name)
        for page in manifest.get("pages") or []:
            for table in page.get("load_tables") or []:
                for row in table.get("rows") or []:
                    item = dict(row)
                    item["_source_file_name"] = file_name
                    if panel_hint and not item.get("panel"):
                        item["panel"] = panel_hint
                        item["panel_source"] = "file_name"
                    out.append(item)
    return out


def _candidate_circuits(manifests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for manifest in manifests:
        for page in manifest.get("pages") or []:
            out.extend(page.get("candidate_circuits") or [])
    return out


def _material_rows(manifests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for manifest in manifests:
        for page in manifest.get("pages") or []:
            out.extend(page.get("material_rows") or [])
    return out


def _load_aggregates_by_panel(load_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for row in load_rows:
        panel = _clean(row.get("panel") or "unknown")
        key = _norm_key(panel) or "unknown"
        bucket = buckets.setdefault(
            key,
            {
                "panel": panel,
                "rows": 0,
                "p_installed_kw": 0.0,
                "p_calc_kw": 0.0,
                "q_calc_kvar": 0.0,
                "s_calc_kva": 0.0,
                "i_calc_a": 0.0,
                "line_ids": [],
                "consumers": [],
                "source_refs": [],
            },
        )
        bucket["rows"] += 1
        for field in ("p_installed_kw", "p_calc_kw", "q_calc_kvar", "s_calc_kva", "i_calc_a"):
            bucket[field] = round(float(bucket[field]) + float(row.get(field) or 0.0), 6)
        _append_unique(bucket["line_ids"], _clean(row.get("line_id") or ""))
        _append_unique(bucket["consumers"], _clean(row.get("consumer") or ""))
        _append_unique(bucket["source_refs"], _clean(row.get("source_ref") or ""))
    return sorted(buckets.values(), key=lambda item: (-int(item["rows"]), item["panel"]))


def _cable_inventory(cable_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for row in cable_rows:
        mark = _clean(row.get("cable_mark") or row.get("name") or "")
        key = _norm_cable(mark)
        if not key:
            key = _norm_key(row.get("name") or "")
        bucket = buckets.setdefault(
            key,
            {
                "identity": mark,
                "rows": 0,
                "quantity_m": 0.0,
                "by_doc_role": defaultdict(float),
                "source_refs": [],
                "examples": [],
            },
        )
        bucket["rows"] += 1
        quantity_m = float(row.get("quantity_m") or 0.0)
        bucket["quantity_m"] = round(float(bucket["quantity_m"]) + quantity_m, 6)
        role = row.get("doc_role") or "unknown"
        bucket["by_doc_role"][role] += quantity_m
        _append_unique(bucket["source_refs"], _clean(row.get("source_ref") or ""))
        if len(bucket["examples"]) < 3:
            bucket["examples"].append(_row_excerpt(row))
    out = []
    for item in buckets.values():
        item["by_doc_role"] = {key: round(value, 6) for key, value in sorted(item["by_doc_role"].items())}
        out.append(item)
    return sorted(out, key=lambda item: (-float(item["quantity_m"]), item["identity"]))


def _equipment_inventory(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        kind = row.get("item_kind") or "material"
        bucket = buckets.setdefault(kind, {"item_kind": kind, "rows": 0, "quantity_by_unit": defaultdict(float), "examples": []})
        bucket["rows"] += 1
        unit = _clean(row.get("unit") or "")
        quantity = row.get("quantity")
        if unit and quantity is not None:
            bucket["quantity_by_unit"][unit] += float(quantity)
        if len(bucket["examples"]) < 5:
            bucket["examples"].append(_row_excerpt(row))
    out = []
    for item in buckets.values():
        item["quantity_by_unit"] = {key: round(value, 6) for key, value in sorted(item["quantity_by_unit"].items())}
        out.append(item)
    return sorted(out, key=lambda item: (-int(item["rows"]), item["item_kind"]))


def _load_to_material_cable_matches(load_rows: list[dict[str, Any]], cable_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    material_index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in cable_rows:
        key = _norm_cable(row.get("cable_mark") or row.get("name") or "")
        if key:
            material_index[key].append(row)
    out: list[dict[str, Any]] = []
    for row in load_rows:
        cable = _clean(row.get("cable") or "")
        key = _norm_cable(cable)
        matches = material_index.get(key, []) if key else []
        out.append(
            {
                "load_source_ref": row.get("source_ref") or "",
                "panel": row.get("panel") or "",
                "consumer": row.get("consumer") or "",
                "line_id": row.get("line_id") or "",
                "load_cable": cable,
                "matched": bool(matches),
                "material_source_refs": [item.get("source_ref") or "" for item in matches[:8]],
                "material_quantity_m": round(sum(float(item.get("quantity_m") or 0.0) for item in matches), 6),
            }
        )
    return out


def _so_to_vor_seeds(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seeds: list[dict[str, Any]] = []
    for row in rows:
        if row.get("doc_role") != "so" or row.get("item_kind") == "section":
            continue
        seed = {
            "schema": "electrical_so_to_vor_seed_v1",
            "source_ref": row.get("source_ref") or "",
            "item_kind": row.get("item_kind") or "material",
            "name": row.get("name") or "",
            "unit": row.get("unit") or "",
            "quantity": row.get("quantity"),
            "cable_mark": row.get("cable_mark") or "",
            "technical": _technical_fields(row),
            "model_instruction": "Draft the VOR work wording from this source row; code must not choose norms.",
        }
        seeds.append(seed)
    return seeds


def _issues(
    load_rows: list[dict[str, Any]],
    circuits: list[dict[str, Any]],
    cable_rows: list[dict[str, Any]],
    matches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    matched_by_ref = {item["load_source_ref"]: item for item in matches}
    for row in load_rows:
        ref = row.get("source_ref") or ""
        if not row.get("panel"):
            issues.append(_issue("load_row_missing_panel", "medium", "Load row has no panel field.", ref, row))
        if not row.get("cable"):
            issues.append(_issue("load_row_missing_cable", "medium", "Load row has no cable field.", ref, row))
        elif not matched_by_ref.get(ref, {}).get("matched"):
            issues.append(_issue("load_row_cable_not_found_in_materials", "low", "Load row cable has no matching material cable mark.", ref, row))
        if row.get("cable") and row.get("cable_length_m") is None:
            issues.append(_issue("load_row_missing_cable_length", "medium", "Load row has cable but no cable length.", ref, row))
        if not row.get("protection"):
            issues.append(_issue("load_row_missing_protection", "low", "Load row has no protection device field.", ref, row))
    for circuit in circuits:
        ref = circuit.get("source_ref") or ""
        if not circuit.get("cable"):
            issues.append(_issue("circuit_missing_cable", "medium", "Candidate circuit has no readable cable label.", ref, circuit))
        if circuit.get("cable") and circuit.get("cable_length_m") is None:
            issues.append(_issue("circuit_missing_cable_length", "medium", "Candidate circuit has cable but no readable length.", ref, circuit))
        if not circuit.get("protection"):
            issues.append(_issue("circuit_missing_protection", "low", "Candidate circuit has no readable protection device.", ref, circuit))
    for row in cable_rows:
        ref = row.get("source_ref") or ""
        if not row.get("cable_mark"):
            issues.append(_issue("material_cable_missing_mark", "low", "Cable material row has no parsed cable mark.", ref, row))
        if row.get("quantity_m") is None:
            issues.append(_issue("material_cable_missing_quantity_m", "medium", "Cable material row has no meter quantity.", ref, row))
    return issues


def _issue_counts(issues: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(str(issue.get("type") or "unknown") for issue in issues)
    return {key: counts[key] for key in sorted(counts)}


def _issue_examples(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: Counter[str] = Counter()
    examples: list[dict[str, Any]] = []
    for issue in issues:
        issue_type = str(issue.get("type") or "unknown")
        if seen[issue_type] >= MAX_ISSUE_EXAMPLES_PER_TYPE:
            continue
        item = dict(issue)
        item["semantics"] = "extractor_gap_example_not_design_verdict"
        examples.append(item)
        seen[issue_type] += 1
    return examples


def _issue(issue_type: str, severity: str, message: str, source_ref: str, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": issue_type,
        "severity": severity,
        "message": message,
        "source_ref": source_ref,
        "row": _row_excerpt(row),
    }


def _row_excerpt(row: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "source_ref",
        "position",
        "name",
        "panel",
        "consumer",
        "line_id",
        "cable",
        "cable_mark",
        "unit",
        "quantity",
        "quantity_m",
        "item_kind",
        "doc_role",
    )
    return {key: row.get(key) for key in keys if row.get(key) not in ("", None, [])}


def _technical_fields(row: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "type_mark",
        "product_code",
        "supplier",
        "ip_rating",
        "rated_current_a",
        "voltage_v",
        "voltages_v",
        "rated_power_w",
        "rated_power_kw",
        "rated_reactive_power_kvar",
        "dimensions_mm",
        "cable_cores",
        "cable_section_mm2",
    )
    return {key: row.get(key) for key in keys if row.get(key) not in ("", None, [])}


def _norm_cable(value: Any) -> str:
    text = _clean(value)
    text = re.sub(r"\b0[,.]\d+\b", "", text)
    return _norm_key(text)


def _panel_from_file_name(value: str) -> str:
    match = re.search(r"\b(ГРЩ\s*[-№]?\s*\d+[A-ZА-Я0-9-]*)\b", value, re.IGNORECASE)
    if not match:
        return ""
    return re.sub(r"\s+", "", match.group(1)).upper()


def _norm_key(value: Any) -> str:
    text = _clean(value).casefold().replace("ё", "е")
    text = text.replace("х", "x")
    return re.sub(r"[^0-9a-zа-я]+", "", text)


def _clean(value: Any) -> str:
    text = str(value or "").translate(_DASHES)
    return re.sub(r"\s+", " ", text).strip()


def _append_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def _discipline_hint(file_name: str) -> str:
    key = _norm_key(file_name)
    if "иосэс" in key or re.search(r"\b(?:ЭС|ES|ЭОМ|EOM)\b", file_name, re.IGNORECASE):
        return "electrical_power"
    if "иоссс" in key or re.search(r"\b(?:СС|SS|СКС|SCS)\b", file_name, re.IGNORECASE):
        return "low_current"
    return "unknown"


def _schematic_role_hint(file_name: str, summary: dict[str, Any]) -> str:
    key = _norm_key(file_name)
    if "таблицарасчетанагруз" in key or int(summary.get("load_rows") or 0) > 0:
        return "load_calculation"
    if "однолин" in key or "схема" in key or int(summary.get("candidate_circuits") or 0) > 0:
        return "single_line_or_scheme"
    return "electrical_manifest"


def _material_role_hint(file_name: str, doc_roles: Counter[str]) -> str:
    key = _norm_key(file_name)
    if "вор" in key or doc_roles.get("vor"):
        return "vor"
    if "со" in key or doc_roles.get("so"):
        return "specification"
    return "material_statement"
