"""Deterministic parametric geometry compilation for ARTEL family generation
(LES3_PLAN W10.2, geometry layer).

The insight (operator, 2026-06-14): Revit API can build geometry from a
description, so geometry is *not* manual work. But a vision model must not invent
geometry directly — that is fragile. Instead the pipeline splits into three:

  read source (vision) -> classify into a parametric ARCHETYPE + bind dimensions
                       -> deterministically instantiate Revit geometry (this code)

This module owns the archetype library and turns a ``family_geometry.v1`` recipe
into ordered ``create_extrusion`` operations whose dimensions are bound to family
parameters, so the resulting family flexes. Execution of the operations is on the
Windows/Revit side (`ARTEL.Revit.FamilyFactory`, finished on Legion).

Archetypes cover the common parametric forms (boxes, panels, profiles, fittings).
A shape not in the library is reported as manual work and is a candidate to grow
the library via the learning loop.
"""

from __future__ import annotations

from typing import Any, Callable

GEOMETRY_SCHEMA_VERSION = "artel.family_geometry.v1"

# A door's thickness when not bound to a parameter (mm). Constant defaults keep
# the recipe terse: vision only has to identify the archetype + main dimensions.
_DEFAULT_DOOR_THICKNESS_MM = 18.0
_DEFAULT_PANEL_THICKNESS_MM = 18.0


def _param_ref(name: str) -> dict[str, Any]:
    return {"parameter": name}


def _const_ref(value: float, unit: str = "mm") -> dict[str, Any]:
    return {"constant": value, "unit": unit}


def _resolve_dim(
    archetype: str,
    dim: str,
    bindings: dict[str, str],
    declared: set[str],
    diagnostics: list[dict[str, Any]],
    *,
    required: bool = True,
) -> dict[str, Any] | None:
    """Resolve an archetype dimension to a parameter ref, validating bindings."""
    param = bindings.get(dim)
    if not param:
        if required:
            diagnostics.append({
                "severity": "error", "code": "ARF-PLAN-GEOM-002",
                "message": f"Archetype '{archetype}' requires dimension '{dim}'; not bound.",
                "target": archetype,
            })
        return None
    if param not in declared:
        diagnostics.append({
            "severity": "error", "code": "ARF-PLAN-GEOM-003",
            "message": f"Geometry binds dimension '{dim}' to undeclared parameter '{param}'.",
            "target": param,
        })
        return None
    return _param_ref(param)


def _compile_rect_cabinet(
    bindings: dict[str, str],
    features: list[dict[str, Any]],
    declared: set[str],
    diagnostics: list[dict[str, Any]],
    manual_work: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Rectangular body extruded up; optional front door."""
    width = _resolve_dim("rect_cabinet", "width", bindings, declared, diagnostics)
    depth = _resolve_dim("rect_cabinet", "depth", bindings, declared, diagnostics)
    height = _resolve_dim("rect_cabinet", "height", bindings, declared, diagnostics)
    if not (width and depth and height):
        return []

    ops: list[dict[str, Any]] = [{
        "op": "create_extrusion",
        "id": "body",
        "role": "body",
        "sketch_plane": "ref_level",
        "profile": {"shape": "rectangle", "width": width, "depth": depth},
        "extrusion": height,
    }]

    for feature in features:
        kind = str(feature.get("kind", "")).strip().lower()
        fb = dict(feature.get("bindings") or {})
        if kind == "door":
            door_w = _resolve_dim("door", "width", fb, declared, diagnostics, required=False) or width
            door_h = _resolve_dim("door", "height", fb, declared, diagnostics, required=False) or height
            thickness = (
                _resolve_dim("door", "thickness", fb, declared, diagnostics, required=False)
                or _const_ref(_DEFAULT_DOOR_THICKNESS_MM)
            )
            ops.append({
                "op": "create_extrusion",
                "id": "door",
                "role": "door",
                "sketch_plane": "front",
                "profile": {"shape": "rectangle", "width": door_w, "depth": door_h},
                "extrusion": thickness,
            })
        else:
            diagnostics.append({
                "severity": "warning", "code": "ARF-PLAN-GEOM-004",
                "message": f"Feature '{kind}' is not in the rect_cabinet archetype; flagged as manual work.",
                "target": "rect_cabinet",
            })
            manual_work.append({
                "kind": "geometry",
                "description": f"Доделать элемент '{kind}' вручную (нет в архетипе rect_cabinet).",
            })
    return ops


def _compile_panel(
    bindings: dict[str, str],
    features: list[dict[str, Any]],
    declared: set[str],
    diagnostics: list[dict[str, Any]],
    manual_work: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Flat panel/plate: front face extruded by thickness."""
    width = _resolve_dim("panel", "width", bindings, declared, diagnostics)
    height = _resolve_dim("panel", "height", bindings, declared, diagnostics)
    thickness = _resolve_dim("panel", "thickness", bindings, declared, diagnostics, required=False)
    if not (width and height):
        return []
    return [{
        "op": "create_extrusion",
        "id": "body",
        "role": "body",
        "sketch_plane": "front",
        "profile": {"shape": "rectangle", "width": width, "depth": height},
        "extrusion": thickness or _const_ref(_DEFAULT_PANEL_THICKNESS_MM),
    }]


def _compile_bar_profile(
    bindings: dict[str, str],
    features: list[dict[str, Any]],
    declared: set[str],
    diagnostics: list[dict[str, Any]],
    manual_work: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Linear bar/beam: a section (width×height) extruded along its length."""
    width = _resolve_dim("bar_profile", "width", bindings, declared, diagnostics)
    height = _resolve_dim("bar_profile", "height", bindings, declared, diagnostics)
    length = _resolve_dim("bar_profile", "length", bindings, declared, diagnostics)
    if not (width and height and length):
        return []
    manual_work.append({
        "kind": "geometry",
        "description": "Заменить габаритный прямоугольник сечения на реальный профиль (L/I/U), если требуется.",
    })
    return [{
        "op": "create_extrusion",
        "id": "body",
        "role": "body",
        "sketch_plane": "section",
        "profile": {"shape": "rectangle", "width": width, "depth": height},
        "extrusion": length,
    }]


def _compile_cylinder_revolve(
    bindings: dict[str, str],
    features: list[dict[str, Any]],
    declared: set[str],
    diagnostics: list[dict[str, Any]],
    manual_work: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Round body: a circle (diameter) extruded by height (a straight cylinder)."""
    diameter = _resolve_dim("cylinder_revolve", "diameter", bindings, declared, diagnostics)
    height = _resolve_dim("cylinder_revolve", "height", bindings, declared, diagnostics)
    if not (diameter and height):
        return []
    return [{
        "op": "create_extrusion",
        "id": "body",
        "role": "body",
        "sketch_plane": "ref_level",
        "profile": {"shape": "circle", "diameter": diameter},
        "extrusion": height,
    }]


# Archetype library: key -> {label, dimensions (required), compile}.
ArchetypeCompiler = Callable[
    [dict[str, str], list[dict[str, Any]], set[str], list[dict[str, Any]], list[dict[str, Any]]],
    list[dict[str, Any]],
]

ARCHETYPES: dict[str, dict[str, Any]] = {
    "rect_cabinet": {
        "label": "Прямоугольный корпус",
        "dimensions": ["width", "depth", "height"],
        "features": ["door"],
        "compile": _compile_rect_cabinet,
    },
    "panel": {
        "label": "Плита / панель",
        "dimensions": ["width", "height"],
        "features": [],
        "compile": _compile_panel,
    },
    "bar_profile": {
        "label": "Линейный профиль / балка",
        "dimensions": ["width", "height", "length"],
        "features": [],
        "compile": _compile_bar_profile,
    },
    "cylinder_revolve": {
        "label": "Цилиндр / тело вращения",
        "dimensions": ["diameter", "height"],
        "features": [],
        "compile": _compile_cylinder_revolve,
    },
}


def compile_geometry(
    recipe: dict[str, Any],
    declared_parameters: set[str],
    diagnostics: list[dict[str, Any]],
    manual_work: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compile a family_geometry.v1 recipe into geometry operations.

    Appends diagnostics/manual_work in place. Returns the ordered operations
    (empty on a blocking error). Deterministic and offline.
    """
    archetype = str(recipe.get("archetype", "")).strip()
    spec = ARCHETYPES.get(archetype)
    if spec is None:
        diagnostics.append({
            "severity": "error", "code": "ARF-PLAN-GEOM-001",
            "message": (
                f"Unknown geometry archetype '{archetype}'. "
                f"Known: {', '.join(sorted(ARCHETYPES))}."
            ),
            "target": archetype or None,
        })
        manual_work.append({
            "kind": "geometry",
            "description": f"Архетип '{archetype}' неизвестен — построить геометрию вручную.",
        })
        return []

    bindings = {str(k): str(v) for k, v in (recipe.get("bindings") or {}).items()}
    features = list(recipe.get("features") or [])
    compiler: ArchetypeCompiler = spec["compile"]
    return compiler(bindings, features, declared_parameters, diagnostics, manual_work)
