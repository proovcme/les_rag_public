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

- local Revit add-in on Legion: `ARTEL.Revit.FamilyFactory`;
- RevitCoreConsole where supported;
- APS Design Automation for Revit for cloud execution.

Mac/Linux can prepare specs, JSON, retrieval context and source manifests, but
cannot fully inspect or generate proprietary `.rfa`/`.rft` family documents
without a Revit-backed executor.

## ARTEL Revit Add-In

The current Windows/Revit executor is:

```text
products/artel/ARTEL.Revit.FamilyFactory/
```

It provides two manual commands inside Revit:

- `ARTEL Family Extract`: exports the active document/family metadata to JSON.
- `ARTEL Family Validate`: checks the active family document and writes a
  validation report JSON.

The validator currently checks:

- active document is a family document;
- category exists;
- family types exist;
- required shared/FOP parameters exist and are shared;
- Revit warnings are captured as validation warnings.
- family types can be flexed by switching `FamilyManager.CurrentType` and
  calling `Document.Regenerate()` inside a rollback transaction;
- optional scratch-project load test through `Document.LoadFamily`;
- manual project acceptance is still required for insert/tag/schedule checks.

Validator environment knobs:

```powershell
$env:ARTEL_REQUIRED_SHARED_PARAMETERS = "ADSK_Наименование,ADSK_КодИзделия"
$env:ARTEL_RUN_FLEX_TEST = "true"
$env:ARTEL_RUN_LOAD_TEST = "false"
$env:ARTEL_REQUIRE_PROJECT_CHECKS = "true"
```

Build and install on Legion/Revit 2025:

```powershell
cd products\artel
.\build-family-factory-revit.ps1 `
  -RevitInstallDir "C:\Program Files\Autodesk\Revit 2025"
```

Installed files:

```text
%APPDATA%\Autodesk\Revit\Addins\2025\ARTEL.FamilyFactory\
%APPDATA%\Autodesk\Revit\Addins\2025\ARTEL.Revit.FamilyFactory.addin
```

Local JSON output:

```text
%APPDATA%\ARTEL\family_factory\
```

Optional validation-report submit:

```powershell
$env:ARTEL_BASE_URL = "http://127.0.0.1:5057"
$env:ARTEL_TASK_ID = "task_0241"
$env:ARTEL_API_KEY = ""
```

When `ARTEL_TASK_ID` is set, `ARTEL Family Validate` posts the report to:

```http
POST /api/revit/tasks/{taskId}/validation-reports
```

## Data Rules

- Keep Autodesk SDK/CHM derived content local/private.
- Do not publish CHM-derived markdown in public repositories.
- Store accepted RFA metadata and validation reports as ARTEL runtime knowledge.
- Convert accepted validation reports to `LEARNING_CASE` and sync them back
  into LES.
- Prefer stable JSON outputs for diffs and catalog ingestion.
- Do not accept a generated family without open/load/flex/tag/schedule checks.

## Learning Case Export

ARTEL backend can project the latest validation report into a LES-ready learning
case:

```http
GET /api/tasks/{taskId}/learning-case
GET /api/validation-reports/{reportId}/learning-case
```

Seed that back into LES:

```bash
python3 tools/seed_artel_learning_cases.py \
  --case-url http://127.0.0.1:5057/api/tasks/task_0241/learning-case \
  --runtime-root /Users/ovc/Projects/LES_v2_reinstall_stress \
  --proxy-url http://127.0.0.1:8050 \
  --verify-search
```

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

If `RevitAPI.chm` has already been extracted into HTML, seed it directly. The
tool writes SDK docs as markdown shards by default, so a full Revit 2025 CHM
HTML tree becomes tens of runtime documents instead of tens of thousands of
tiny files:

```bash
python3 tools/seed_artel_revit_factory_sources.py \
  --runtime-root /Users/ovc/Projects/LES_v2_reinstall_stress \
  --proxy-url http://127.0.0.1:8050 \
  --seed-defaults \
  --sdk-html-dir local_private_archive/revit_api_sdk/revit-api-chms/html/2025 \
  --sdk-shard-pages auto \
  --verify-search
```

Current local source used for Revit 2025 SDK docs:

```text
local_private_archive/revit_api_sdk/revit-api-chms/html/2025
```

The upstream repository is `ADN-DevTech/revit-api-chms`, which stores Revit API
CHM files and extracted HTML snippets. Keep this clone and all CHM-derived
runtime projections private/local.

If the local Revit install has no `RevitAPI.chm`, seed selected SDK/API pages by
URL as private runtime knowledge:

```bash
python3 tools/seed_artel_revit_factory_sources.py \
  --runtime-root /Users/ovc/Projects/LES_v2_reinstall_stress \
  --proxy-url http://127.0.0.1:8050 \
  --sdk-url https://www.revitapidocs.com/2023/1cc4fe6c-0e9f-7439-0021-32d2e06f4c33.htm \
  --verify-search
```
