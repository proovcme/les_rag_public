---
name: artel-revit-family
description: Use when creating, reviewing, validating, documenting, or cataloging Autodesk Revit RFA families for ARTEL, including family specifications, FOP/shared-parameter checks, template/category selection, quality gates, validation reports, and LES RAG retrieval over ARTEL_Index.
---

# ARTEL Revit Family Skill

## Source Of Truth

Work from LES `ARTEL_Index` first. Retrieve current evidence before writing a
specification, validation checklist, or acceptance note:

```bash
curl -fsS -X POST http://127.0.0.1:8050/api/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"ARTEL Revit family requirements FOP shared parameters validation", "dataset_filter":"ARTEL", "top_k":8, "include_trace":true}'
```

Expected ARTEL source classes:

- `FAMILY_GUIDE`: Revit family methodology and ARTEL quality requirements.
- `REVIT_MODEL_GUIDE`: Revit data-model concepts: Element, Parameter,
  Category, Family, Type, Document, Subcategory and stable ids.
- `REVIT_API_REFERENCE`: Revit API implementation basis for add-ins,
  family/template extraction, `FamilyManager`, collectors, transactions,
  shared parameters and connectors.
- `REVIT_API_SYMBOL_MAP`: exact API symbols, namespaces, member kinds and
  documentation ids/links.
- `REVIT_API_SDK_DOC`: detailed local SDK/CHM pages converted to markdown.
- `FOP_PROFILE`: exact ADSK/shared parameter names, GUIDs, types and flags.
- `LEARNING_CASE`: accepted family examples, known failures and fixes.

If LES is unavailable, read [family-quality-requirements.md](references/family-quality-requirements.md) as the offline baseline and say that retrieval was not checked.

## Workflow

1. Determine family category, Revit template, discipline, project stage, LOD,
   host/room behavior and expected schedules/tags.
2. Retrieve `FAMILY_GUIDE` chunks for creation and quality rules.
3. Retrieve `REVIT_MODEL_GUIDE` chunks when normalizing user requests into
   Revit concepts, catalog JSON fields or validation criteria.
4. Retrieve `REVIT_API_REFERENCE` chunks when writing add-in code, extractor
   logic, validation automation, or Revit API implementation plans.
5. Retrieve `REVIT_API_SYMBOL_MAP` and `REVIT_API_SDK_DOC` chunks for exact API
   symbols, member names, namespaces and detailed SDK behavior.
6. Retrieve `FOP_PROFILE` chunks for required ADSK/shared parameters.
7. Produce a family specification:
   - category/template;
   - geometry and reference skeleton;
   - type/instance parameters;
   - shared/FOP parameters;
   - materials/subcategories;
   - detail levels and symbolic graphics;
   - type catalog decision;
   - validation checklist;
   - catalog metadata.
8. Validate or review the RFA against the quality gates.
9. For Revit-side checks, use `ARTEL.Revit.FamilyFactory` on the Windows/Revit
   host to extract metadata and produce validation reports.
10. Save accepted and curated rejected outcomes as `LEARNING_CASE` so LES
    improves future work.

## Quality Gates

- Correct template and category.
- Explicit purpose, LOD, discipline and project stage.
- Reference planes/lines form the skeleton; geometry is constrained to it.
- Type parameters and instance parameters are separated.
- Shared parameters are checked against FOP.
- Detail levels, symbolic graphics, materials and subcategories are intentional.
- Type catalog is used for large type sets.
- Family opens, loads, inserts, flexes, tags and schedules correctly.
- File size, nested families, arrays, voids and formulas are reasonable.
- Technical description and validation report are attached before acceptance.

## Do Not Accept

- Wrong or unclear category/template.
- Loose geometry not driven by a reference skeleton.
- Heavy high-detail geometry for ordinary project use.
- Missing required ADSK/shared parameters.
- Embedded large type lists where a type catalog is expected.
- Unexplained nested families, formulas, voids or arrays.
- No flex test, no schedule/tag test, or no technical description.

## Commands

Seed Autodesk family guide plus ARTEL requirements:

```bash
python3 tools/seed_artel_family_guides.py \
  --guide-pdf /path/to/revit_family_creation_guide_autodesk_2017.pdf \
  --runtime-root /Users/ovc/Projects/LES_v2_reinstall_stress \
  --proxy-url http://127.0.0.1:8050 \
  --verify-search
```

Seed FOP/shared parameters:

```bash
python3 tools/seed_artel_fop_profiles.py \
  --fop /path/to/FOP2021.txt \
  --runtime-root /Users/ovc/Projects/LES_v2_reinstall_stress \
  --proxy-url http://127.0.0.1:8050 \
  --verify-search
```

Seed Revit API reference:

```bash
python3 tools/seed_artel_revit_api_reference.py \
  --runtime-root /Users/ovc/Projects/LES_v2_reinstall_stress \
  --proxy-url http://127.0.0.1:8050 \
  --verify-search
```

Seed family factory sources:

```bash
python3 tools/seed_artel_revit_factory_sources.py \
  --runtime-root /Users/ovc/Projects/LES_v2_reinstall_stress \
  --proxy-url http://127.0.0.1:8050 \
  --seed-defaults \
  --verify-search
```

Seed local Revit SDK/CHM docs:

```bash
python3 tools/seed_artel_revit_factory_sources.py \
  --runtime-root /Users/ovc/Projects/LES_v2_reinstall_stress \
  --proxy-url http://127.0.0.1:8050 \
  --chm /path/to/RevitAPI.chm \
  --verify-search
```

Seed extracted Revit API CHM HTML as markdown shards. This is the preferred
path for the local/private `ADN-DevTech/revit-api-chms` clone:

```bash
python3 tools/seed_artel_revit_factory_sources.py \
  --runtime-root /Users/ovc/Projects/LES_v2_reinstall_stress \
  --proxy-url http://127.0.0.1:8050 \
  --seed-defaults \
  --sdk-html-dir local_private_archive/revit_api_sdk/revit-api-chms/html/2025 \
  --sdk-shard-pages auto \
  --verify-search
```

Do not index full CHM HTML as one markdown file per page unless explicitly
debugging `--max-sdk-pages`; Revit 2025 has 28k+ HTML pages and should be
sharded before LES sync.

Seed selected SDK/API pages when no local CHM is available:

```bash
python3 tools/seed_artel_revit_factory_sources.py \
  --runtime-root /Users/ovc/Projects/LES_v2_reinstall_stress \
  --proxy-url http://127.0.0.1:8050 \
  --sdk-url https://www.revitapidocs.com/2023/1cc4fe6c-0e9f-7439-0021-32d2e06f4c33.htm \
  --verify-search
```

Build/install the Revit add-in on Legion/Revit 2025:

```powershell
cd products\artel
.\build-family-factory-revit.ps1 `
  -RevitInstallDir "C:\Program Files\Autodesk\Revit 2025"
```

Useful validation environment:

```powershell
$env:ARTEL_REQUIRED_SHARED_PARAMETERS = "ADSK_Наименование"
$env:ARTEL_RUN_FLEX_TEST = "true"
$env:ARTEL_RUN_LOAD_TEST = "false"
$env:ARTEL_REQUIRE_PROJECT_CHECKS = "true"
```

Autorun Revit validation from an unlocked Legion desktop:

```powershell
cd products\artel
.\diagnose-family-factory-revit-session.ps1 -Screenshot
```

```powershell
cd products\artel
.\run-family-factory-revit-autorun.ps1 `
  -FamilyPath "C:\Program Files\Autodesk\Revit 2025\Samples\rac_basic_sample_family.rfa" `
  -TaskId "" `
  -ArtelBaseUrl "" `
  -TimeoutSec 420
```

If this exits with a `LogonUI.exe`/lock-screen error, unlock the Legion Windows
desktop first; Revit API autorun does not produce validation reports from the
lock screen.

Run the full Legion autorun/copy/ingest path from macOS. This first diagnoses
the Legion desktop and exits with `status: "locked"` if Revit cannot be
started interactively. If ingest or add-in submit is enabled, it also checks
ARTEL backend `/health` before starting Revit and exits with
`status: "artel_backend_unavailable"` when the backend is down:

```bash
python3 tools/run_artel_legion_revit_validation.py \
  --use-legion-artel-backend \
  --artel-url http://127.0.0.1:5057 \
  --task-id task_0241 \
  --runtime-root /Users/ovc/Projects/LES_v2_reinstall_stress \
  --proxy-url http://127.0.0.1:8050 \
  --verify-search
```

Use `--no-ingest` for a diagnostic-only Legion check.
Use `--backend-only-smoke --use-legion-artel-backend` to verify the managed
Legion backend/tunnel without touching Revit.

Run the complete readiness audit:

```bash
python3 tools/smoke_artel_expert_loop.py \
  --backend-only-smoke \
  --check-legion
```

Before the Legion desktop is unlocked, the expected healthy status is
`ready_except_revit_locked`.

Ingest a Revit add-in validation report into ARTEL backend and LES:

```bash
python3 tools/ingest_artel_validation_report.py \
  --report 'local_private_archive/artel_validation_reports/validation_*.json' \
  --artel-url http://127.0.0.1:5057 \
  --task-id task_0241 \
  --runtime-root /Users/ovc/Projects/LES_v2_reinstall_stress \
  --proxy-url http://127.0.0.1:8050 \
  --verify-search
```

Seed all archived ARTEL backend reports into LES:

```bash
python3 tools/seed_artel_backend_reports.py \
  --artel-url http://127.0.0.1:5057 \
  --task-id task_0241 \
  --runtime-root /Users/ovc/Projects/LES_v2_reinstall_stress \
  --proxy-url http://127.0.0.1:8050 \
  --verify-search
```
