"""Deterministically compile an approved ARTEL family specification into a Revit
API action plan (LES3_PLAN W10.2).

ADR-11 (LLM-минимализм): the spec is already structured, so the mapping
"spec parameter -> add shared/family parameter", "spec type -> create type" and
"spec material -> assign material" is *code, not an LLM*. This module does that
mapping, resolves shared-parameter GUIDs against the FOP reference, validates the
result against ``schema/family_action_plan.schema.json``, and emits an explicit
list of manual geometry work that cannot be compiled from the spec.

The output (``family_action_plan.v1``) is the contract the ARTEL Revit add-in
(`ARTEL.Revit.FamilyFactory`) executes as a batch; execution + validation report
live on the Windows/Revit side.

Input spec shape mirrors the Agnostis.Api ``FamilySpecification`` record
(ASP.NET camelCase JSON); snake_case keys are also accepted.

CLI::

    uv run python tools/artel_family_action_plan.py \
        --spec spec.json --fop FOP2021.txt --out plan.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# Reuse the existing Revit shared-parameter file parser (groups + params w/ GUID).
try:  # pragma: no cover - import shim for both `python tools/...` and `from tools import`
    from tools import seed_artel_fop_profiles as fop_seed
    from tools import artel_family_geometry as geometry_lib
except ImportError:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from tools import seed_artel_fop_profiles as fop_seed
    from tools import artel_family_geometry as geometry_lib

SCHEMA_VERSION = "artel.family_action_plan.v1"
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "family_action_plan.schema.json"

_GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

# Spec data-type word -> Revit StorageType. Only StorageType is emitted here because
# it is a small, stable Revit enum; the add-in maps data_type -> ForgeTypeId/SpecTypeId.
_STORAGE_BY_DATATYPE: dict[str, str] = {
    "text": "String",
    "string": "String",
    "length": "Double",
    "number": "Double",
    "area": "Double",
    "volume": "Double",
    "angle": "Double",
    "slope": "Double",
    "currency": "Double",
    "integer": "Integer",
    "yesno": "Integer",
    "material": "ElementId",
}

# Categories that carry MEP connectors -> flagged as manual work.
_MEP_CATEGORY_HINTS = (
    "pipe", "duct", "cable", "conduit", "electrical", "mechanical", "plumbing",
    "труб", "воздуховод", "электр", "кабель", "механ",
)


def _get(mapping: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Return the first present key (camelCase/snake_case tolerant)."""
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return default


def build_fop_index(fop_text: str) -> dict[str, dict[str, str]]:
    """name -> {guid, datatype, group} from a Revit shared-parameter file."""
    parsed = fop_seed.parse_shared_parameters(fop_text)
    index: dict[str, dict[str, str]] = {}
    for row in parsed["params"]:
        name = (row.get("NAME") or "").strip()
        if not name:
            continue
        index[name] = {
            "guid": (row.get("GUID") or "").strip(),
            "datatype": (row.get("DATATYPE") or "").strip(),
            "group": (row.get("GROUP_NAME") or row.get("GROUP") or "").strip(),
        }
    return index


def _storage_type(data_type: str, diagnostics: list[dict[str, Any]], target: str) -> str:
    storage = _STORAGE_BY_DATATYPE.get((data_type or "").strip().lower())
    if storage is None:
        diagnostics.append({
            "severity": "warning",
            "code": "ARF-PLAN-DT-001",
            "message": f"Unknown data type '{data_type}'; defaulting storage type to String.",
            "target": target,
        })
        return "String"
    return storage


def _is_shared(parameter: dict[str, Any]) -> bool:
    source = str(_get(parameter, "source", default="")).lower()
    has_guid = bool(_get(parameter, "sharedParameterGuid", "shared_parameter_guid"))
    return "shared" in source or has_guid


def _safe_plan_id(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value.lower())
    cleaned = cleaned.strip("._-")
    return cleaned[:80] if len(cleaned) >= 3 else f"plan_{cleaned}".ljust(3, "0")


def compile_action_plan(
    spec: dict[str, Any],
    fop_index: dict[str, dict[str, str]] | None = None,
    geometry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile a FamilySpecification dict into a family_action_plan.v1 dict.

    ``geometry`` is an optional family_geometry.v1 recipe (else read from
    ``spec['geometry']``). When present, parametric geometry is compiled into the
    plan and the generic manual geometry work is replaced by a review step.

    Deterministic and offline: identical inputs yield byte-identical output
    (no clock, no LLM, no randomness).
    """
    fop_index = fop_index or {}
    diagnostics: list[dict[str, Any]] = []
    operations: list[dict[str, Any]] = []

    family_name = str(_get(spec, "familyName", "family_name", default="")).strip()
    category = str(_get(spec, "revitCategory", "revit_category", default="")).strip()
    task_id = _get(spec, "taskId", "task_id")
    spec_id = _get(spec, "id", "specId", "spec_id")

    if not family_name:
        diagnostics.append({
            "severity": "error", "code": "ARF-PLAN-NAME-001",
            "message": "Specification has no family name.", "target": None,
        })
    if not category:
        diagnostics.append({
            "severity": "error", "code": "ARF-PLAN-CAT-001",
            "message": "Specification has no Revit category.", "target": None,
        })

    parameters: list[dict[str, Any]] = list(_get(spec, "parameters", default=[]) or [])

    # Track declared parameters and which ones are formula-driven (cannot be set per type).
    declared: set[str] = set()
    formula_driven: set[str] = set()
    formula_ops: list[dict[str, Any]] = []

    # Pass 1: parameters (shared first in spec order, then formulas) ----------------
    for parameter in parameters:
        name = str(_get(parameter, "name", default="")).strip()
        if not name:
            diagnostics.append({
                "severity": "error", "code": "ARF-PLAN-PARAM-001",
                "message": "Parameter without a name in specification.", "target": None,
            })
            continue
        if name in declared:
            diagnostics.append({
                "severity": "error", "code": "ARF-PLAN-PARAM-002",
                "message": f"Duplicate parameter '{name}' in specification.", "target": name,
            })
            continue
        declared.add(name)

        data_type = str(_get(parameter, "dataType", "data_type", default="")).strip()
        group = str(_get(parameter, "group", default="")).strip()
        is_instance = bool(_get(parameter, "isInstance", "is_instance", default=False))
        is_required = bool(_get(parameter, "isRequired", "is_required", default=False))
        storage = _storage_type(data_type, diagnostics, name)
        formula = _get(parameter, "formula")

        if _is_shared(parameter):
            spec_guid = str(_get(parameter, "sharedParameterGuid", "shared_parameter_guid", default="")).strip()
            fop_entry = fop_index.get(name)
            guid = ""
            if fop_entry and fop_entry["guid"]:
                guid = fop_entry["guid"]
                if spec_guid and spec_guid.lower() != guid.lower():
                    diagnostics.append({
                        "severity": "error", "code": "ARF-PLAN-SP-002",
                        "message": (
                            f"Shared parameter '{name}' GUID disagrees with FOP reference "
                            f"(spec={spec_guid}, fop={guid})."
                        ),
                        "target": name,
                    })
            elif spec_guid:
                guid = spec_guid
                diagnostics.append({
                    "severity": "warning", "code": "ARF-PLAN-SP-003",
                    "message": f"Shared parameter '{name}' not in FOP reference; using spec GUID unverified.",
                    "target": name,
                })
            else:
                diagnostics.append({
                    "severity": "error", "code": "ARF-PLAN-SP-001",
                    "message": f"Shared parameter '{name}' has no GUID in spec or FOP reference.",
                    "target": name,
                })
                continue

            if not _GUID_RE.match(guid):
                diagnostics.append({
                    "severity": "error", "code": "ARF-PLAN-SP-004",
                    "message": f"Shared parameter '{name}' has a malformed GUID '{guid}'.",
                    "target": name,
                })
                continue

            operations.append({
                "op": "add_shared_parameter",
                "name": name,
                "guid": guid,
                "data_type": data_type,
                "storage_type": storage,
                "group": group,
                "is_instance": is_instance,
                "is_required": is_required,
            })
        else:
            operations.append({
                "op": "add_family_parameter",
                "name": name,
                "data_type": data_type,
                "storage_type": storage,
                "group": group,
                "is_instance": is_instance,
            })

        if formula:
            formula_driven.add(name)
            formula_ops.append({"op": "set_formula", "parameter": name, "formula": str(formula)})

    # Pass 2: formulas (after every parameter exists) ------------------------------
    operations.extend(formula_ops)

    # Pass 3: geometry (after parameters exist, so dimensions can bind to them) -----
    geometry_recipe = geometry if geometry is not None else _get(spec, "geometry")
    geometry_manual: list[dict[str, Any]] = []
    geometry_compiled = False
    if geometry_recipe:
        geometry_ops = geometry_lib.compile_geometry(
            geometry_recipe, declared, diagnostics, geometry_manual)
        geometry_compiled = bool(geometry_ops)
        operations.extend(geometry_ops)

    # Pass 4: types ----------------------------------------------------------------
    for family_type in _get(spec, "types", default=[]) or []:
        type_name = str(_get(family_type, "name", default="")).strip()
        if not type_name:
            diagnostics.append({
                "severity": "error", "code": "ARF-PLAN-TYPE-003",
                "message": "Family type without a name in specification.", "target": None,
            })
            continue
        raw_values = _get(family_type, "values", default={}) or {}
        values: list[dict[str, Any]] = []
        for param_name, value in raw_values.items():
            param_name = str(param_name).strip()
            if param_name not in declared:
                diagnostics.append({
                    "severity": "error", "code": "ARF-PLAN-TYPE-001",
                    "message": f"Type '{type_name}' sets undeclared parameter '{param_name}'.",
                    "target": type_name,
                })
                continue
            if param_name in formula_driven:
                diagnostics.append({
                    "severity": "warning", "code": "ARF-PLAN-TYPE-002",
                    "message": (
                        f"Type '{type_name}' sets formula-driven parameter '{param_name}'; "
                        "value skipped (Revit computes it from the formula)."
                    ),
                    "target": type_name,
                })
                continue
            values.append({"parameter": param_name, "value": value})
        operations.append({"op": "create_type", "name": type_name, "values": values})

    # Pass 5: materials ------------------------------------------------------------
    for material in _get(spec, "materials", default=[]) or []:
        material_name = str(_get(material, "name", default="")).strip()
        if not material_name:
            diagnostics.append({
                "severity": "error", "code": "ARF-PLAN-MAT-001",
                "message": "Material without a name in specification.", "target": None,
            })
            continue
        operations.append({
            "op": "assign_material",
            "name": material_name,
            "parameter": _get(material, "parameterName", "parameter_name"),
            "default_value": _get(material, "defaultValue", "default_value"),
        })

    manual_work = _manual_work(category, geometry_compiled) + geometry_manual

    has_error = any(d["severity"] == "error" for d in diagnostics)
    plan_id = _safe_plan_id(str(spec_id or task_id or family_name or "family_action_plan"))

    return {
        "schema_version": SCHEMA_VERSION,
        "plan_id": plan_id,
        "task_id": task_id,
        "spec_id": spec_id,
        "status": "error" if has_error else "ok",
        "compiled_at": None,
        "generator": {"mode": "deterministic", "llm_used": False, "tool": "artel_family_action_plan"},
        "family": {
            "name": family_name,
            "category": category,
            "template_file_id": _get(spec, "templateFileId", "template_file_id"),
            "shared_parameter_profile_id": _get(spec, "sharedParameterProfileId", "shared_parameter_profile_id"),
        },
        "operations": operations,
        "manual_work": manual_work,
        "diagnostics": diagnostics,
    }


def _manual_work(category: str, geometry_compiled: bool) -> list[dict[str, Any]]:
    """Manual work that the plan cannot compile.

    When a geometry recipe compiled, geometry is generated (not hand-built), so
    the only manual step is reviewing it against the source; otherwise the full
    skeleton/geometry/subcategory work stays manual.
    """
    if geometry_compiled:
        work = [
            {"kind": "geometry_review",
             "description": "Сверить сгенерированную геометрию с техничкой/чертежом; проверить флекс типоразмеров."},
            {"kind": "subcategories",
             "description": "Назначить подкатегории и графику элементов геометрии."},
        ]
    else:
        work = [
            {"kind": "reference_skeleton",
             "description": "Создать опорные плоскости и связать их с габаритными параметрами."},
            {"kind": "geometry",
             "description": "Построить твердотельную геометрию по опорным плоскостям; задать видимость по LOD."},
            {"kind": "subcategories",
             "description": "Назначить подкатегории и графику элементов геометрии."},
        ]
    lowered = category.lower()
    if any(hint in lowered for hint in _MEP_CATEGORY_HINTS):
        work.append({"kind": "connectors",
                     "description": f"Добавить MEP-коннекторы для категории '{category}'."})
    return work


def validate_plan(plan: dict[str, Any]) -> None:
    """Validate against family_action_plan.schema.json; raise on failure."""
    import jsonschema

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(plan, schema)


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compile an ARTEL family spec into a Revit action plan (W10.2).")
    parser.add_argument("--spec", required=True, type=Path, help="FamilySpecification JSON.")
    parser.add_argument("--fop", type=Path, help="Revit shared-parameter (.txt) FOP reference for GUID resolution.")
    parser.add_argument("--geometry", type=Path, help="family_geometry.v1 recipe JSON (else read from spec.geometry).")
    parser.add_argument("--out", type=Path, help="Write the plan JSON here (default: stdout).")
    parser.add_argument("--no-validate", action="store_true", help="Skip schema validation.")
    args = parser.parse_args(argv)

    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    fop_index = build_fop_index(fop_seed.read_text(args.fop)) if args.fop else {}
    geometry = json.loads(args.geometry.read_text(encoding="utf-8")) if args.geometry else None
    plan = compile_action_plan(spec, fop_index, geometry)
    if not args.no_validate:
        validate_plan(plan)

    rendered = json.dumps(plan, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(rendered + "\n", encoding="utf-8")
        print(f"Wrote {args.out} (status={plan['status']}, operations={len(plan['operations'])})")
    else:
        print(rendered)
    return 1 if plan["status"] == "error" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
