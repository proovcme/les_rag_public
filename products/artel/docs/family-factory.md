# ARTEL Family Factory

Goal: turn ARTEL from a family-spec assistant into a testable Revit family
factory.

## Knowledge Inputs

LES `ARTEL_Index` is the source-of-truth retrieval layer.

Required source classes:

- `FAMILY_GUIDE`: family creation and quality methodology.
- `REVIT_MODEL_GUIDE`: Revit data model concepts and vocabulary.
- `REVIT_API_REFERENCE`: implementation patterns for add-ins and extractors.
- `REVIT_API_SYMBOL_MAP`: exact API symbols, namespaces and documentation ids.
- `REVIT_API_SDK_DOC`: detailed SDK/CHM documentation pages when available.
- `FOP_PROFILE`: exact shared parameters, GUIDs, datatypes and flags.
- `LEARNING_CASE`: accepted family examples and validation outcomes.

## Factory Loop

```text
user task
  -> LES retrieval over ARTEL_Index
  -> family specification
  -> Revit add-in / RevitCoreConsole / APS Design Automation execution
  -> RFA + type catalog + validation report
  -> catalog card
  -> accepted LEARNING_CASE back into LES
```

## Generation Contract

Every generated family task must produce:

- category and template;
- family name and type naming scheme;
- LOD/detail behavior;
- reference skeleton plan;
- type and instance parameter table;
- FOP/shared-parameter requirements;
- geometry/subcategory/material plan;
- connector requirements where applicable;
- validation checklist;
- catalog metadata.

## Revit-Side Work

Native Revit API work stays on Windows/Revit infrastructure:

- local Revit add-in on Legion;
- RevitCoreConsole where supported;
- APS Design Automation for Revit for cloud execution.

Mac/Linux can prepare specs, JSON, retrieval context and source manifests, but
cannot fully inspect or generate proprietary `.rfa`/`.rft` family documents
without a Revit-backed executor.

## Data Rules

- Keep Autodesk SDK/CHM derived content local/private.
- Do not publish CHM-derived markdown in public repositories.
- Store accepted RFA metadata and validation reports as ARTEL runtime knowledge.
- Prefer stable JSON outputs for diffs and catalog ingestion.
- Do not accept a generated family without open/load/flex/tag/schedule checks.

## Seed Commands

```bash
python3 tools/seed_artel_revit_factory_sources.py \
  --runtime-root /Users/ovc/Projects/LES_v2_reinstall_stress \
  --proxy-url http://127.0.0.1:8050 \
  --seed-defaults \
  --verify-search
```

```bash
python3 tools/seed_artel_revit_factory_sources.py \
  --runtime-root /Users/ovc/Projects/LES_v2_reinstall_stress \
  --proxy-url http://127.0.0.1:8050 \
  --chm /path/to/RevitAPI.chm \
  --verify-search
```
