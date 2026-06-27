"""W10.2 — deterministic family spec -> Revit action plan compiler.

Golden case is the reference «Шкаф архивный металлический» (Agnostis.Api SeedData
spec_0241): it must compile *without an LLM* into a schema-valid action plan.
"""

from __future__ import annotations

import copy

from tools import artel_family_action_plan as compiler


# Revit shared-parameter (.txt) FOP reference used as the GUID source of truth.
FOP_TEXT = "\n".join(
    [
        "# Revit shared parameter file (ARTEL test fixture)",
        "*META\tVERSION\tMINVERSION",
        "META\t2\t1",
        "*GROUP\tID\tNAME",
        "GROUP\t1\t01 Идентификация",
        "*PARAM\tGUID\tNAME\tDATATYPE\tDATACATEGORY\tGROUP\tVISIBLE\tDESCRIPTION\tUSERMODIFIABLE",
        "PARAM\t4f5cb6a1-0000-0000-0000-000000000000\tADSK_Наименование\tTEXT\t\t1\t1\tНаименование\t1",
    ]
)


# Mirror of Agnostis.Api SeedData spec_0241 (ASP.NET camelCase JSON).
SHKAF_SPEC = {
    "id": "spec_0241",
    "taskId": "task_0241",
    "status": "approved",
    "familyName": "Шкаф архивный металлический",
    "revitCategory": "Furniture",
    "templateFileId": "file_template_001",
    "sharedParameterProfileId": "fop_2026",
    "parameters": [
        {"id": "param_001", "name": "ADSK_Наименование", "source": "shared_parameter",
         "sharedParameterGuid": "4f5cb6a1-0000-0000-0000-000000000000", "dataType": "Text",
         "group": "Identity Data", "isInstance": False, "isRequired": True},
        {"id": "param_002", "name": "Ширина", "source": "family_parameter", "dataType": "Length",
         "group": "Dimensions", "isInstance": False, "isRequired": True},
        {"id": "param_003", "name": "Высота", "source": "family_parameter", "dataType": "Length",
         "group": "Dimensions", "isInstance": False, "isRequired": True},
    ],
    "types": [
        {"id": "type_001", "name": "Шкаф 800x400x1800",
         "values": {"Ширина": 800, "Высота": 1800}},
    ],
    "materials": [
        {"id": "mat_001", "name": "Материал корпуса", "parameterName": "Материал корпуса",
         "defaultValue": "RAL 7035"},
    ],
}


def _fop_index():
    return compiler.build_fop_index(FOP_TEXT)


def test_shkaf_compiles_without_llm_and_validates():
    plan = compiler.compile_action_plan(SHKAF_SPEC, _fop_index())

    assert plan["status"] == "ok"
    assert plan["generator"] == {
        "mode": "deterministic", "llm_used": False, "tool": "artel_family_action_plan",
    }
    assert plan["family"]["name"] == "Шкаф архивный металлический"
    assert plan["family"]["category"] == "Furniture"
    assert not [d for d in plan["diagnostics"] if d["severity"] == "error"]

    # Schema-valid before it can be issued to Revit.
    compiler.validate_plan(plan)


def test_shkaf_operations_are_ordered_and_correct():
    plan = compiler.compile_action_plan(SHKAF_SPEC, _fop_index())
    ops = plan["operations"]

    # Parameters first, then the single type, then the material.
    assert [op["op"] for op in ops] == [
        "add_shared_parameter", "add_family_parameter", "add_family_parameter",
        "create_type", "assign_material",
    ]

    shared = ops[0]
    assert shared["name"] == "ADSK_Наименование"
    assert shared["guid"] == "4f5cb6a1-0000-0000-0000-000000000000"
    assert shared["storage_type"] == "String"
    assert shared["is_required"] is True

    assert ops[1]["name"] == "Ширина"
    assert ops[1]["storage_type"] == "Double"

    create_type = ops[3]
    assert create_type["name"] == "Шкаф 800x400x1800"
    assert create_type["values"] == [
        {"parameter": "Ширина", "value": 800},
        {"parameter": "Высота", "value": 1800},
    ]

    material = ops[4]
    assert material["name"] == "Материал корпуса"
    assert material["default_value"] == "RAL 7035"


def test_compilation_is_deterministic():
    fop = _fop_index()
    first = compiler.compile_action_plan(SHKAF_SPEC, fop)
    second = compiler.compile_action_plan(copy.deepcopy(SHKAF_SPEC), fop)
    assert first == second
    assert first["compiled_at"] is None  # no clock -> reproducible


def test_manual_geometry_work_is_flagged():
    plan = compiler.compile_action_plan(SHKAF_SPEC, _fop_index())
    kinds = {item["kind"] for item in plan["manual_work"]}
    assert {"reference_skeleton", "geometry", "subcategories"} <= kinds
    # Furniture is not MEP -> no connectors.
    assert "connectors" not in kinds


def test_mep_category_adds_connector_manual_work():
    spec = copy.deepcopy(SHKAF_SPEC)
    spec["revitCategory"] = "Pipe Fittings"
    plan = compiler.compile_action_plan(spec, _fop_index())
    assert any(item["kind"] == "connectors" for item in plan["manual_work"])


def test_missing_shared_parameter_guid_is_blocking_error():
    plan = compiler.compile_action_plan(SHKAF_SPEC, {})  # empty FOP, spec still has GUID
    # Spec carries the GUID, so this is an unverified warning, not an error.
    assert plan["status"] == "ok"
    assert any(d["code"] == "ARF-PLAN-SP-003" for d in plan["diagnostics"])

    spec = copy.deepcopy(SHKAF_SPEC)
    del spec["parameters"][0]["sharedParameterGuid"]
    plan = compiler.compile_action_plan(spec, {})  # no GUID anywhere
    assert plan["status"] == "error"
    assert any(d["code"] == "ARF-PLAN-SP-001" for d in plan["diagnostics"])


def test_guid_disagreement_is_blocking_error():
    spec = copy.deepcopy(SHKAF_SPEC)
    spec["parameters"][0]["sharedParameterGuid"] = "11111111-2222-3333-4444-555555555555"
    plan = compiler.compile_action_plan(spec, _fop_index())
    assert plan["status"] == "error"
    assert any(d["code"] == "ARF-PLAN-SP-002" for d in plan["diagnostics"])


def test_type_referencing_undeclared_parameter_is_error():
    spec = copy.deepcopy(SHKAF_SPEC)
    spec["types"][0]["values"]["Глубина"] = 400  # not declared as a parameter
    plan = compiler.compile_action_plan(spec, _fop_index())
    assert plan["status"] == "error"
    assert any(d["code"] == "ARF-PLAN-TYPE-001" for d in plan["diagnostics"])


def test_formula_driven_parameter_emits_set_formula_and_skips_type_value():
    spec = copy.deepcopy(SHKAF_SPEC)
    spec["parameters"].append(
        {"id": "param_004", "name": "Площадь", "source": "family_parameter",
         "dataType": "Area", "group": "Dimensions", "isInstance": False,
         "isRequired": False, "formula": "Ширина * Высота"}
    )
    spec["types"][0]["values"]["Площадь"] = 1.44  # must be skipped (formula-driven)
    plan = compiler.compile_action_plan(spec, _fop_index())

    ops = plan["operations"]
    assert any(op["op"] == "set_formula" and op["parameter"] == "Площадь" for op in ops)
    create_type = next(op for op in ops if op["op"] == "create_type")
    assert all(value["parameter"] != "Площадь" for value in create_type["values"])
    assert any(d["code"] == "ARF-PLAN-TYPE-002" for d in plan["diagnostics"])

    # set_formula comes after the parameter that owns it.
    op_names = [op["op"] for op in ops]
    assert op_names.index("set_formula") > op_names.index("add_family_parameter")


def test_unknown_data_type_warns_and_defaults_storage():
    spec = copy.deepcopy(SHKAF_SPEC)
    spec["parameters"][1]["dataType"] = "Wibble"
    plan = compiler.compile_action_plan(spec, _fop_index())
    assert plan["status"] == "ok"  # warning, not blocking
    assert any(d["code"] == "ARF-PLAN-DT-001" for d in plan["diagnostics"])
    width_op = next(op for op in plan["operations"] if op.get("name") == "Ширина")
    assert width_op["storage_type"] == "String"


def test_missing_category_is_error():
    spec = copy.deepcopy(SHKAF_SPEC)
    spec["revitCategory"] = ""
    plan = compiler.compile_action_plan(spec, _fop_index())
    assert plan["status"] == "error"
    assert any(d["code"] == "ARF-PLAN-CAT-001" for d in plan["diagnostics"])
