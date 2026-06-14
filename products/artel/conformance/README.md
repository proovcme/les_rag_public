# ARTEL conformance kit

Golden inputs and expected outputs that pin the behavior of the deterministic
generator core (FOP resolution, action-plan compiler, geometry archetypes).

АРТЕЛЬ ships as a standalone Windows package, so the core is **ported to C# inside
`Agnostis.Api`**. The Python implementation in the LES repo
(`tools/artel_family_action_plan.py`, `tools/artel_family_geometry.py`) is the
**reference oracle**; this kit is the contract the C# port must reproduce.

```text
inputs/
  fop_reference.txt      Revit shared-parameter file (GUID source)
  shkaf.spec.json        approved FamilySpecification (camelCase, as from Agnostis.Api)
  shkaf.geometry.json    family_geometry.v1 recipe (rect_cabinet + door)
  column.spec.json       round column spec
  column.geometry.json   cylinder_revolve recipe (circle profile)
  beam.spec.json         I-beam spec
  beam.geometry.json     bar_profile recipe (section extruded along length)
expected/
  shkaf_base.plan.json       compile(spec, fop)            -> family_action_plan.v1
  shkaf_geometry.plan.json   compile(spec, fop, geometry)  -> rect_cabinet + door
  column_geometry.plan.json  compile(spec, fop, geometry)  -> cylinder_revolve
  beam_geometry.plan.json    compile(spec, fop, geometry)  -> bar_profile
```

Covered archetypes: `rect_cabinet`, `cylinder_revolve` (circle profile),
`bar_profile`. Regenerate any case the same way (swap the `--spec`/`--geometry`).

## Regenerate (reference oracle)

```bash
uv run python tools/artel_family_action_plan.py \
  --spec products/artel/conformance/inputs/shkaf.spec.json \
  --fop  products/artel/conformance/inputs/fop_reference.txt \
  --out  products/artel/conformance/expected/shkaf_base.plan.json

uv run python tools/artel_family_action_plan.py \
  --spec     products/artel/conformance/inputs/shkaf.spec.json \
  --fop      products/artel/conformance/inputs/fop_reference.txt \
  --geometry products/artel/conformance/inputs/shkaf.geometry.json \
  --out      products/artel/conformance/expected/shkaf_geometry.plan.json
```

`tests/test_artel_conformance_fixtures.py` recompiles the inputs and asserts the
committed `expected/*.json` match, so the fixtures cannot silently drift from the
oracle. The C# port (on Legion) reads the same `inputs/` and must produce the same
`expected/` — schema-valid `family_action_plan.v1`, no LES, no model.
