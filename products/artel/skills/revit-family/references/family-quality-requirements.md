# ARTEL Family Quality Requirements

Use this only when LES retrieval is unavailable. LES `ARTEL_Index` is the live
source of truth.

## Required Evidence

- Family category and Revit template are explicit.
- Purpose, discipline, project stage and target LOD are explicit.
- Host behavior, room behavior, tags and schedules are defined where relevant.
- Geometry is driven by reference planes/lines.
- Parameters are separated into type, instance, shared/FOP and internal family
  parameters.
- Required shared parameters are checked against FOP by exact name, GUID and
  datatype.
- Materials, subcategories, symbolic graphics and detail levels are intentional.
- Type catalog is used when type count is large.
- Family opens, loads, inserts, flexes, tags and schedules correctly.
- Technical description, validation report and acceptance notes exist.

## Reject Patterns

- Wrong template/category.
- Unconstrained geometry.
- Excessive geometry for project use.
- Heavy 3D geometry used as a plan symbol.
- Missing shared parameters required by task/FOP.
- Excessive formulas, arrays, voids or nested families without reason.
- No flex test.
- No schedule/tag validation.
- No technical description.
