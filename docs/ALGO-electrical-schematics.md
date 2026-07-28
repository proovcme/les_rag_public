# ALGO-electrical-schematics

Read-only reader for electrical single-line drawings, load-calculation tables and VOR/SO
material/equipment statements.

Status: 0.24.0.286 MVP. This is a navigation/evidence layer, not a final electrical-design
checker and not an LLM answer.

## Goal

Project electrical sheets are usually graphic single-line diagrams, while load calculations are
tables. LES must read both as related evidence:

- graphic one-line sheet -> labels, cable marks, cable lengths, protection devices, vector line
  primitives, candidate circuits;
- load calculation table -> normalized load rows with panel, consumer, line, installed/calculated
  power, current, cos phi, cable, cable length and protection;
- VOR/SO statement -> material/equipment rows with position, name, unit, quantity, category,
  cable mark/section and `quantity_m` where available;
- later layers can compare scheme rows, load tables, cable journals and specifications by
  source-backed fields.

## Contract

Service: `proxy/services/electrical_schematic_service.py`

Materials service: `proxy/services/electrical_materials_service.py`

Evidence summary service: `proxy/services/electrical_evidence_summary_service.py`

CLI: `tools/electrical_schematic.py`

Materials CLI: `tools/electrical_materials.py`

Evidence summary CLI: `tools/electrical_evidence_summary.py`

Dictionary: `config/domain/electrical_schema_terms.yaml`

Output schema:

```text
electrical_schematic_manifest_v1
  pages[]
    sheet_kind: electrical_single_line | electrical_load_table | unknown
    text_nodes[]: panel/protection/cable/line labels with bbox and source_ref
    line_segments[]: vector primitives from PDF drawings
    candidate_circuits[]: from/to/cable/cable_length_m/protection/load_kw/current_a
    load_tables[]: electrical_load_table_v1 rows

electrical_material_manifest_v1
  pages[]
    material_tables[]
      rows[]: position/name/unit/quantity/item_kind/section/type_mark/source_ref/doc_role
      cable rows: cable_mark/cable_cores/cable_section_mm2/quantity_m
      technical fields: work_action/ip_rating/rated_current_a/voltage_v/voltages_v/rated_power_w/
        rated_power_kw/rated_reactive_power_kvar/install_height_m/cable_diameter_mm/
        dimensions_mm/unit_mass_kg/total_mass_kg/product_code/supplier

electrical_evidence_summary_v1
  model_reading_contract: model-facing guardrails; summary is navigation, not a code verdict
  source_navigation[]: which ES/EOM files/layers are present and what role they play
  load_aggregates_by_panel[]: sums of Pуст/Pр/Qр/Sр/Iр plus line/consumer lists
  cable_inventory[]: cable identity, rows, quantity_m, by_doc_role, source refs
  equipment_inventory[]: item_kind counts and quantity_by_unit
  load_to_material_cable_matches[]: load row cable mark -> material cable rows
  so_to_vor_seeds[]: source-backed SO rows for model-facing draft VOR generation
  issue_counts: full counts of missing cable/protection/length/mark coverage gaps
  issues[]: capped examples of coverage gaps with source refs
```

Important fields:

- `cable_length_m` is first-class in both `candidate_circuits` and load-table rows.
- Load-table aliases are dictionary-driven. Example: `Руст` / `Pуст` maps to
  `p_installed_kw` = installed power, `Рр` / `Pр` maps to `p_calc_kw` = calculated power,
  and `L` / `длина кабеля` maps to `cable_length_m`.
- Every extracted value has a `source_ref` down to page/table/row when available.
- Missing graphic understanding is explicit: if vector lines exist but no readable circuit row can
  be assembled, the page gets `graphic_scheme_without_readable_circuit_rows`.
- VOR/SO rows are classified as `cable`, `panel`, `lighting`, `containment`, `busbar`,
  `protection`, `equipment`, `section`, `linear` or `material`. Classification is evidence
  tagging only; it is not a design decision.
- VOR/SO are different document roles. LES must be able to compare them and derive a draft VOR
  from SO/specification rows, but must not sum them as one quantity source.
- `issue_counts` / `issues` are extractor coverage gaps and reconciliation prompts. They are not
  design defects, not proof that the ES section is absent, and not a reason for code to refuse the
  engineering read when ES files/load rows/material rows are present.

## Current MVP

The reader uses PyMuPDF only:

1. `page.get_text("dict")` -> text blocks with coordinates.
2. Dictionary + regex extraction of common electrical labels:
   - panels/switchboards: `ВРУ`, `ГРЩ`, `ЩО`, `ЩР`, `РУ`, `КТП`, etc.;
   - protection/control: `QF`, `QS`, `FU`, `KM`, `ВА`, `АВ`;
   - cables: `ВВГнг-LS 5х16`, `АВВГ`, `ПвВГ`, `NYM`, etc.;
   - line ids: `Л1`, `L1`, `Гр.1`, `линия ...`, `фидер ...`.
3. `page.get_drawings()` -> horizontal/vertical/diagonal line segments.
4. `page.find_tables()` -> load-calculation tables, normalized by dictionary header aliases.
5. Candidate circuits are built only from same text-block co-occurrence and ranked by completeness.
6. `electrical_materials_service` reads VOR/SO `find_tables()` matrices, repairs PDF mojibake,
   maps columns by headers, tracks section rows and normalizes quantities.
7. Material rows get directly written technical facts when present: document role, work action,
   IP rating, rated current/voltage(s)/power, installation height, cable diameter, equipment
   dimensions, unit mass and total mass.
8. `electrical_evidence_summary_service` merges schematic/load/material manifests into panel
   aggregates, cable/equipment inventories, SO->VOR seeds, source navigation and capped gap
   examples. It does not decide norms, does not decide that a section is absent, and must not
   replace the model's engineering read.

## Extraction Map

Covered by `drawing_manifest_service` / `pd_rd_manifest_service`:

- volume composition: sheets, sections, explanatory note, VOR, SO, tables and attachments when
  they appear in title blocks, volume contents or composition registers;
- ciphers, stages, sheet numbers, sheet names, object/building hints and source-map navigation;
- explanatory note table of contents and "where to look" navigation.

Planned extraction from explanatory notes:

- project decisions: power inputs, GRSH/main switchboards, reliability categories, voltage,
  grounding/earthing, lightning protection, cable type families and design assumptions.

Covered by `electrical_schematic_service`:

- load tables: `Pуст`, `Pр`, `Qр`, `Sр`, `Iр`, `cosφ`, `Ки`, consumer and panel when present or
  inferable from load-table file name;
- schematic labels: switchboards, line/group labels, cable marks, protection labels and vector
  line primitives when readable from the PDF text/vector layer.

Covered by `electrical_materials_service`:

- VOR/SO cable rows: mark, cores, section, unit, quantity_m and source_ref;
- lighting, sockets/switches/equipment, panels, protection devices, busbars, trays/containment;
- technical attributes: IP, current, voltage(s), power, dimensions, install height, cable
  diameter, unit/total mass, type mark, product code and supplier.

Covered by `electrical_evidence_summary_service`:

- load aggregates by panel: total `Pуст/Pр/Sр/Iр`, row count, line list and consumer list;
- equipment inventory by kind and unit;
- source navigation: ES/EOM manifests and their role hints (`load_calculation`,
  `single_line_or_scheme`, `vor`, `specification`);
- coverage checks across load table / scheme / VOR-SO: counts and capped examples for missing
  cable, protection, length, cable mark and material match;
- SO rows converted into source-backed draft-VOR seeds for the model.

Still planned:

- deeper PZ project decision extraction;
- geometric association of labels to schematic line segments;
- richer apparatus parsing: QF/automats/nominals/RCD/differential devices when the text layer is
  structured enough;
- row-level reconciliation: load table <-> scheme <-> VOR/SO by panel, line, consumer and cable.

## Non-goals

- Do not infer hidden topology from line geometry alone.
- Do not claim final electrical correctness.
- Do not choose cable/protection adequacy.
- Do not mutate datasets or trigger reindex.
- Do not replace the model's explanation; this layer gives evidence to the model.
- Do not sum VOR and SO quantities as one total: VOR and SO are different document roles.

## Next Steps

1. Add geometric association: nearest label to line segment, busbar candidate, branch candidate.
2. Add cross-check:
   - scheme cable length vs load table length;
   - scheme line id vs load table line id;
   - scheme panel/consumer vs load table panel/consumer.
3. Add VOR <-> SO reconciliation: match rows by normalized equipment/cable identity, unit and
   quantity; report missing-in-VOR, missing-in-SO, quantity mismatch and attribute mismatch with
   both source refs.
4. Add SO -> draft VOR derivation: convert specification rows into model-facing VOR candidates
   using item kind, unit, quantity and technical attributes, without choosing norms in code.
5. Add cross-check between load rows and VOR/SO cable rows by consumer/line/panel terms.
6. Add Documents UI panel for `electrical_schematic_manifest_v1` and
   `electrical_material_manifest_v1` / `electrical_evidence_summary_v1`.
