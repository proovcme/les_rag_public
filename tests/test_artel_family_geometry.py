"""W10.2 geometry layer — archetype-driven parametric geometry compilation.

Geometry is generated from a family_geometry.v1 recipe, not hand-built: the recipe
names a parametric archetype (rect_cabinet, panel) and binds its dimensions to
family parameters, and the compiler emits flexing create_extrusion operations.
"""

from __future__ import annotations

import copy

from tools import artel_family_action_plan as compiler
from tools import artel_family_geometry as geometry

from tests.test_artel_family_action_plan import FOP_TEXT, SHKAF_SPEC


def _fop_index():
    return compiler.build_fop_index(FOP_TEXT)


# Шкаф with an explicit depth parameter so geometry can bind width/depth/height.
def _shkaf_with_depth():
    spec = copy.deepcopy(SHKAF_SPEC)
    spec["parameters"].append(
        {"id": "param_010", "name": "Глубина", "source": "family_parameter",
         "dataType": "Length", "group": "Dimensions", "isInstance": False, "isRequired": True}
    )
    return spec


CABINET_RECIPE = {
    "schema_version": geometry.GEOMETRY_SCHEMA_VERSION,
    "archetype": "rect_cabinet",
    "bindings": {"width": "Ширина", "depth": "Глубина", "height": "Высота"},
}


def test_rect_cabinet_compiles_to_flexing_extrusion():
    plan = compiler.compile_action_plan(_shkaf_with_depth(), _fop_index(), CABINET_RECIPE)
    assert plan["status"] == "ok"

    body = next(op for op in plan["operations"] if op.get("op") == "create_extrusion")
    assert body["id"] == "body"
    assert body["profile"] == {
        "shape": "rectangle",
        "width": {"parameter": "Ширина"},
        "depth": {"parameter": "Глубина"},
    }
    assert body["extrusion"] == {"parameter": "Высота"}
    compiler.validate_plan(plan)


def test_geometry_replaces_manual_geometry_with_review():
    plan = compiler.compile_action_plan(_shkaf_with_depth(), _fop_index(), CABINET_RECIPE)
    kinds = {item["kind"] for item in plan["manual_work"]}
    assert "geometry_review" in kinds
    # The generic "build geometry by hand" / skeleton steps are gone.
    assert "geometry" not in kinds
    assert "reference_skeleton" not in kinds


def test_geometry_operations_come_after_parameters():
    plan = compiler.compile_action_plan(_shkaf_with_depth(), _fop_index(), CABINET_RECIPE)
    op_names = [op["op"] for op in plan["operations"]]
    first_extrusion = op_names.index("create_extrusion")
    last_param = max(
        op_names.index("add_shared_parameter"),
        len(op_names) - 1 - op_names[::-1].index("add_family_parameter"),
    )
    assert first_extrusion > last_param


def test_recipe_can_ride_on_the_spec():
    spec = _shkaf_with_depth()
    spec["geometry"] = CABINET_RECIPE
    plan = compiler.compile_action_plan(spec, _fop_index())  # no explicit geometry arg
    assert any(op.get("op") == "create_extrusion" for op in plan["operations"])


def test_door_feature_adds_second_extrusion():
    recipe = copy.deepcopy(CABINET_RECIPE)
    recipe["features"] = [{"kind": "door"}]
    plan = compiler.compile_action_plan(_shkaf_with_depth(), _fop_index(), recipe)
    extrusions = [op for op in plan["operations"] if op.get("op") == "create_extrusion"]
    assert [op["id"] for op in extrusions] == ["body", "door"]
    door = extrusions[1]
    # Door defaults its thickness to a constant when not bound.
    assert door["extrusion"] == {"constant": geometry._DEFAULT_DOOR_THICKNESS_MM, "unit": "mm"}
    assert door["profile"]["width"] == {"parameter": "Ширина"}


def test_unknown_archetype_is_blocking_error_and_falls_back_to_manual():
    recipe = {"schema_version": geometry.GEOMETRY_SCHEMA_VERSION,
              "archetype": "blob", "bindings": {}}
    plan = compiler.compile_action_plan(_shkaf_with_depth(), _fop_index(), recipe)
    assert plan["status"] == "error"
    assert any(d["code"] == "ARF-PLAN-GEOM-001" for d in plan["diagnostics"])
    assert any(item["kind"] == "geometry" for item in plan["manual_work"])


def test_missing_required_dimension_is_error():
    recipe = copy.deepcopy(CABINET_RECIPE)
    del recipe["bindings"]["height"]
    plan = compiler.compile_action_plan(_shkaf_with_depth(), _fop_index(), recipe)
    assert plan["status"] == "error"
    assert any(d["code"] == "ARF-PLAN-GEOM-002" for d in plan["diagnostics"])


def test_binding_to_undeclared_parameter_is_error():
    recipe = copy.deepcopy(CABINET_RECIPE)
    recipe["bindings"]["depth"] = "Глубина"  # not declared in the base шкаф spec
    plan = compiler.compile_action_plan(SHKAF_SPEC, _fop_index(), recipe)  # no Глубина param
    assert plan["status"] == "error"
    assert any(d["code"] == "ARF-PLAN-GEOM-003" for d in plan["diagnostics"])


def test_unknown_feature_warns_and_becomes_manual_work():
    recipe = copy.deepcopy(CABINET_RECIPE)
    recipe["features"] = [{"kind": "drawer"}]
    plan = compiler.compile_action_plan(_shkaf_with_depth(), _fop_index(), recipe)
    assert plan["status"] == "ok"  # warning, not blocking
    assert any(d["code"] == "ARF-PLAN-GEOM-004" for d in plan["diagnostics"])
    assert any("drawer" in item["description"] for item in plan["manual_work"])


def test_panel_archetype_single_extrusion():
    spec = copy.deepcopy(SHKAF_SPEC)
    spec["parameters"].append(
        {"id": "p_t", "name": "Толщина", "source": "family_parameter",
         "dataType": "Length", "group": "Dimensions", "isInstance": False, "isRequired": True}
    )
    recipe = {
        "schema_version": geometry.GEOMETRY_SCHEMA_VERSION,
        "archetype": "panel",
        "bindings": {"width": "Ширина", "height": "Высота", "thickness": "Толщина"},
    }
    plan = compiler.compile_action_plan(spec, _fop_index(), recipe)
    assert plan["status"] == "ok"
    extrusions = [op for op in plan["operations"] if op.get("op") == "create_extrusion"]
    assert len(extrusions) == 1
    assert extrusions[0]["extrusion"] == {"parameter": "Толщина"}
    compiler.validate_plan(plan)


def _spec_with_params(param_names):
    spec = copy.deepcopy(SHKAF_SPEC)
    spec["types"] = []
    spec["parameters"] = [SHKAF_SPEC["parameters"][0]] + [
        {"id": f"p_{n}", "name": n, "source": "family_parameter", "dataType": "Length",
         "group": "Dimensions", "isInstance": False, "isRequired": True}
        for n in param_names
    ]
    return spec


def test_bar_profile_extrudes_section_along_length():
    spec = _spec_with_params(["Ширина сечения", "Высота сечения", "Длина"])
    recipe = {"schema_version": geometry.GEOMETRY_SCHEMA_VERSION, "archetype": "bar_profile",
              "bindings": {"width": "Ширина сечения", "height": "Высота сечения", "length": "Длина"}}
    plan = compiler.compile_action_plan(spec, _fop_index(), recipe)
    assert plan["status"] == "ok"
    body = next(op for op in plan["operations"] if op.get("op") == "create_extrusion")
    assert body["profile"] == {
        "shape": "rectangle",
        "width": {"parameter": "Ширина сечения"},
        "depth": {"parameter": "Высота сечения"},
    }
    assert body["extrusion"] == {"parameter": "Длина"}
    compiler.validate_plan(plan)


def test_cylinder_revolve_circle_extrusion():
    spec = _spec_with_params(["Диаметр", "Высота"])
    recipe = {"schema_version": geometry.GEOMETRY_SCHEMA_VERSION, "archetype": "cylinder_revolve",
              "bindings": {"diameter": "Диаметр", "height": "Высота"}}
    plan = compiler.compile_action_plan(spec, _fop_index(), recipe)
    assert plan["status"] == "ok"
    body = next(op for op in plan["operations"] if op.get("op") == "create_extrusion")
    assert body["profile"] == {"shape": "circle", "diameter": {"parameter": "Диаметр"}}
    assert body["extrusion"] == {"parameter": "Высота"}
    compiler.validate_plan(plan)


def test_new_archetypes_are_in_the_library():
    assert {"rect_cabinet", "panel", "bar_profile", "cylinder_revolve"} <= set(geometry.ARCHETYPES)


def test_no_recipe_keeps_full_manual_geometry():
    # Backward-compat: without a recipe, geometry stays manual.
    plan = compiler.compile_action_plan(SHKAF_SPEC, _fop_index())
    kinds = {item["kind"] for item in plan["manual_work"]}
    assert "geometry" in kinds
    assert "reference_skeleton" in kinds
    assert "geometry_review" not in kinds
    assert not any(op.get("op") == "create_extrusion" for op in plan["operations"])
