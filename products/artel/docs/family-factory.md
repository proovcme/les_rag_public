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

## Action Plan Compiler (W10.2)

An approved `FamilySpecification` is compiled **deterministically, without an LLM**
(ADR-11) into a Revit build plan before any Revit work:

```bash
uv run python tools/artel_family_action_plan.py \
  --spec spec.json --fop FOP2021.txt --out plan.json
```

- Schema: `schema/family_action_plan.schema.json` (`family_action_plan.v1`).
- Compiler: `tools/artel_family_action_plan.py` (importable + CLI).
- Tests: `tests/test_artel_family_action_plan.py` (golden «Шкаф архивный
  металлический» = `Agnostis.Api` `spec_0241`).

The plan is an ordered batch of operations — `add_shared_parameter` (GUID resolved
against the FOP reference), `add_family_parameter`, `set_formula`, `create_extrusion`
(geometry), `create_type`, `assign_material` — plus `manual_work[]` and
`diagnostics[]` (`ARF-PLAN-*`). `status: "error"` means the plan must not be issued
to Revit.

### Parametric geometry (archetype layer)

Geometry is generated, not hand-built. The split is three layers, so a vision model
never invents geometry directly (fragile); it only classifies + binds:

```text
source (datasheet/drawing/image)
  -> vision: classify shape into an ARCHETYPE + bind dimensions   (family_geometry.v1, W10.1)
  -> deterministic: archetype -> create_extrusion ops bound to params  (tools/artel_family_geometry.py, W10.2)
  -> Revit add-in executes; geometry flexes with the parameters     (W10.3, Legion)
```

- Recipe schema: `schema/family_geometry.schema.json` (`family_geometry.v1` —
  `archetype`, `bindings` dimension→parameter, `features`, `source`/`confidence`).
- Archetype library: `tools/artel_family_geometry.py` (`rect_cabinet`, `panel`; door
  feature). A shape not in the library → `manual_work` + a candidate to grow the
  library via the learning loop.
- `create_extrusion` carries `profile`/`extrusion` dimensions as `{parameter: …}`
  refs, so the family flexes. When a recipe compiles, generic manual geometry work
  collapses to a single `geometry_review` step.
- CLI: `--geometry geom.json` (or put the recipe on `spec.geometry`).

Reliability rule for the vision step: photo → shape class (reliable),
datasheet table/text → dimensions (reliable), photo → exact dimensions (NOT
reliable → flag for the operator at the approve gate).

`family_action_plan.v1` is the contract between the compiler and the Windows side.
**Remaining (Legion/Revit session):** a C# `ArtelFamilyGenerateCommand` in
`ARTEL.Revit.FamilyFactory` that executes `operations[]` as a batch and writes a
validation report, and `Agnostis.Api` serving the compiled plan from
`/api/revit/tasks/{taskId}/package`.

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

## Autorun Smoke

For a repeatable Revit-side smoke from an unlocked Legion desktop session:

```powershell
cd products\artel
.\diagnose-family-factory-revit-session.ps1 -Screenshot
```

Proceed only when the diagnostic JSON returns `status: "interactive"`.

```powershell
cd products\artel
.\run-family-factory-revit-autorun.ps1 `
  -FamilyPath "C:\Program Files\Autodesk\Revit 2025\Samples\rac_basic_sample_family.rfa" `
  -TaskId "" `
  -ArtelBaseUrl "" `
  -TimeoutSec 420
```

The script sets `ARTEL_AUTORUN_VALIDATE_PATH`, starts Revit, waits for
`%APPDATA%\ARTEL\family_factory\validation_*.json`, and exits non-zero if only
`autorun_error_*.json` or no report appears. It also refuses to start if
`LogonUI.exe` is running, because that means Windows is on the lock screen.
Remote OpenSSH/Scheduled Task launches on locked Legion did not reach normal
Revit journal/report creation on 2026-06-06; unlock the Windows desktop before
the proof smoke.

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

Seed a Revit add-in validation JSON into ARTEL backend and LES:

```bash
python3 tools/ingest_artel_validation_report.py \
  --report 'local_private_archive/artel_validation_reports/validation_*.json' \
  --artel-url http://127.0.0.1:5057 \
  --task-id task_0241 \
  --runtime-root /Users/ovc/Projects/LES_v2_reinstall_stress \
  --proxy-url http://127.0.0.1:8050 \
  --verify-search
```

The ingest tool posts the report, fetches the report-specific learning case,
writes the LES projection and runs `ARTEL_Index` sync.

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
