# Legion Revit Smoke

Date: 2026-06-06.

Goal: verify that the Windows/Revit test host can support the next ARTEL hand
test loop with standard Revit family/template content and LES retrieval.

## Host

- SSH alias: `legion`
- Hostname: `DESKTOP-G0EBFRO`
- LES URL from Legion: `http://10.195.146.98:8050`
- ARTEL backend test URL on Legion: `http://127.0.0.1:5057`

## Installed Runtime

- .NET SDK: `10.0.201`
- ASP.NET Core runtimes include `8.0.23`
- Revit executables found:
  - `C:\Program Files\Autodesk\Revit 2024\Revit.exe`
  - `C:\Program Files\Autodesk\Revit 2025\Revit.exe`
- `RevitCoreConsole.exe` was not found under Revit 2024/2025 install folders.
- `RevitAPI.chm` was not found under common Autodesk/Revit folders or
  `C:\Users\Oleg`.

The Revit API CHM gap is covered by the local/private clone:

```text
local_private_archive/revit_api_sdk/revit-api-chms
```

The source repository is `ADN-DevTech/revit-api-chms`; it contains Revit API
CHM files and extracted HTML snippets. LES indexes the Revit 2025 HTML tree as
`REVIT_API_SDK_DOC` markdown shards, not as public repository content.

## Standard Content Inventory

RVT 2024:

- `.rfa`: `9882`
- `.rft`: `548`
- `.rte`: `171`

RVT 2025:

- `.rfa`: `9884`
- `.rft`: `1328`
- `.rte`: `171`

Useful RVT 2025 templates for ARTEL cabinet/equipment testing:

- `C:\ProgramData\Autodesk\RVT 2025\Family Templates\English\Metric Casework.rft`
- `C:\ProgramData\Autodesk\RVT 2025\Family Templates\English\Metric Electrical Equipment.rft`
- `C:\ProgramData\Autodesk\RVT 2025\Family Templates\English\Metric Generic Model.rft`
- `C:\ProgramData\Autodesk\RVT 2025\Family Templates\English\Metric Furniture.rft`

Useful RVT 2025 sample family folder:

```text
C:\ProgramData\Autodesk\RVT 2025\Libraries\English\US\Casework\Base Cabinets
```

Example families found there:

- `M_Base Cabinet-2 Bin.rfa`
- `M_Base Cabinet-4 Drawers.rfa`
- `M_Base Cabinet-Double Door & 2 Drawer.rfa`
- `M_Base Cabinet-Single Door.rfa`
- `M_Vanity Cabinet-Double Door & 4 Drawer.rfa`

## FOP / Shared Parameters Found

Real Revit shared-parameter/FOP files found on Legion:

```text
C:\Users\Oleg\Downloads\fop (2)\ФОП\ФОП2019.txt
C:\Users\Oleg\Downloads\fop (2)\ФОП\ФОП2021.txt
```

Both files have the standard Revit shared parameter structure:

```text
# This is a Revit shared parameter file.
*META
*GROUP
*PARAM
```

The preferred LES ingestion path is not raw `.txt` upload, but a normalized
ARTEL markdown projection:

```bash
python3 tools/seed_artel_fop_profiles.py \
  --fop /path/to/FOP2021.txt \
  --runtime-root /Users/ovc/Projects/LES_v2_reinstall_stress \
  --proxy-url http://127.0.0.1:8050 \
  --verify-search
```

The tool writes projections to `RAG_Content/ARTEL/fop_profiles/`, syncs only
`ARTEL_Index`, and verifies retrieval for FOP/shared parameter queries.

## ARTEL Backend Smoke

Copied current ARTEL mirror payload to:

```text
%TEMP%\artel-legion-smoke
```

Build command:

```powershell
dotnet build "$env:TEMP\artel-legion-smoke\backend\Agnostis.Api\Agnostis.Api.csproj" --configuration Release
```

Result:

- build succeeded;
- warnings: `0`;
- errors: `0`.

Run command:

```powershell
$env:LES_BASE_URL = "http://10.195.146.98:8050"
$env:LES_TIMEOUT_SECONDS = "30"
dotnet "$env:TEMP\artel-legion-smoke\backend\Agnostis.Api\bin\Release\net8.0\Agnostis.Api.dll" --urls http://127.0.0.1:5057
```

Passed endpoints:

- `GET /health` -> `status=ok`
- `GET /api/integrations/les/status` -> LES `httpStatus=200`
- `POST /api/tasks/task_0241/rag-context` with `datasetFilter=ARTEL` -> `status=ok`, LES `httpStatus=200`

Compact RAG result:

```json
{
  "Status": "ok",
  "HttpStatus": 200,
  "DatasetFilter": "ARTEL",
  "Count": 2,
  "FirstDoc": "family_learning_cases/demo_metal_cabinet_001.md",
  "FirstDomain": "ARTEL",
  "FirstDocType": "LEARNING_CASE",
  "Quality": "good"
}
```

## ARTEL FamilyFactory Add-In Build

Source:

```text
products/artel/ARTEL.Revit.FamilyFactory
```

Build/install command:

```powershell
cd products\artel
.\build-family-factory-revit.ps1 `
  -RevitInstallDir "C:\Program Files\Autodesk\Revit 2025"
```

Result:

- build succeeded on Legion;
- latest verification: 2026-06-06 after adding flex/load validation checks;
- warnings: `2` (`MSB3277` System.Drawing 4.0/8.0 reference conflict from
  Revit 2025/.NET assemblies);
- errors: `0`;
- installed to
  `C:\Users\Oleg\AppData\Roaming\Autodesk\Revit\Addins\2025\ARTEL.FamilyFactory`;
- `.addin` manifest written to
  `C:\Users\Oleg\AppData\Roaming\Autodesk\Revit\Addins\2025\ARTEL.Revit.FamilyFactory.addin`.

Commands exposed in Revit:

- `ARTEL Family Extract`;
- `ARTEL Family Validate`.

Validator behavior now includes:

- family document/category/type checks;
- required shared/FOP parameters from `ARTEL_REQUIRED_SHARED_PARAMETERS`;
- Revit warnings copied into validation issues;
- rollback flex test over all family types by default;
- optional scratch metric project load test when `ARTEL_RUN_LOAD_TEST=true`;
- manual project acceptance warning for insert/tag/schedule checks.

Expected output folder:

```text
C:\Users\Oleg\AppData\Roaming\ARTEL\family_factory
```

Optional submit environment:

```powershell
$env:ARTEL_BASE_URL = "http://127.0.0.1:5057"
$env:ARTEL_TASK_ID = "task_0241"
$env:ARTEL_API_KEY = ""
$env:ARTEL_REQUIRED_SHARED_PARAMETERS = "ADSK_Наименование,ADSK_КодИзделия"
$env:ARTEL_RUN_FLEX_TEST = "true"
$env:ARTEL_RUN_LOAD_TEST = "false"
$env:ARTEL_REQUIRE_PROJECT_CHECKS = "true"
```

Current limitation: Revit GUI execution has not yet been manually clicked in
this smoke. The code/build/install path is ready; actual open/flex/load
execution and insert/tag/schedule acceptance still need a hands-on Revit pass.

## Issue Found

Initial ARTEL `rag-context` from Legion returned:

```json
{
  "status": "upstream_error",
  "httpStatus": 401,
  "response": {
    "detail": "Authentication required"
  }
}
```

Cause: the active clean/stress LES runtime had:

```text
TRUSTED_NETWORKS=127.0.0.0/8,::1/128
```

Legion connects from `10.195.146.20`, so LES did not treat it as a trusted
ZeroTier client.

Runtime fix applied to the active stress install:

```text
TRUSTED_NETWORKS=127.0.0.0/8,::1/128,10.195.146.0/24
```

After proxy restart, trust diagnostics from Legion returned:

```json
{
  "trusted": true,
  "role": "admin",
  "holder": "trusted-network",
  "source": "10.195.146.20"
}
```

## Remaining Manual Revit Test

The backend/RAG path is ready. The remaining Revit-side test needs an
interactive Revit desktop session because `RevitCoreConsole.exe` is not
present and OpenSSH/Scheduled Task launch on 2026-06-06 hit the Windows lock
screen before normal journal/report creation.

1. Open Revit 2025 on Legion.
2. Start from `Metric Casework.rft` or `Metric Electrical Equipment.rft`.
3. Open one standard cabinet family from the Base Cabinets folder.
4. Verify required shared/catalog parameters against the ARTEL task:
   `ADSK_Наименование`, `ADSK_КодИзделия`, `ADSK_Марка`, `ADSK_Примечание`.
5. Run `External Tools -> ARTEL Family Validate`.
6. Copy the latest `%APPDATA%\ARTEL\family_factory\validation_*.json` from
   Legion into `local_private_archive/artel_validation_reports/`.
7. Ingest the report into ARTEL backend and LES:

```bash
python3 tools/ingest_artel_validation_report.py \
  --report 'local_private_archive/artel_validation_reports/validation_*.json' \
  --artel-url http://127.0.0.1:5057 \
  --task-id task_0241 \
  --runtime-root /Users/ovc/Projects/LES_v2_reinstall_stress \
  --proxy-url http://127.0.0.1:8050 \
  --verify-search
```

This should create a report-specific `FamilyLearningCase` projection under
`RAG_Content/ARTEL/family_learning_cases/` and make it searchable in
`ARTEL_Index`.

## Autorun Attempt 2026-06-06

Added `ARTEL_AUTORUN_VALIDATE_PATH` support to
`ARTEL.Revit.FamilyFactory` and installed it on Legion. The add-in build passed
with the existing two `System.Drawing` warnings and zero errors. The installed
manifest now includes both command entries and
`ARTEL.Revit.FamilyFactory.ArtelFamilyFactoryApplication`.

The intended unlocked-desktop smoke command is:

```powershell
cd products\artel
.\diagnose-family-factory-revit-session.ps1 -Screenshot
```

Run autorun only when the diagnostic status is `interactive`:

```powershell
cd products\artel
.\run-family-factory-revit-autorun.ps1 `
  -FamilyPath "C:\Program Files\Autodesk\Revit 2025\Samples\rac_basic_sample_family.rfa" `
  -TaskId "" `
  -ArtelBaseUrl "" `
  -TimeoutSec 420
```

Observed remote limits:

- direct OpenSSH `Start-Process Revit.exe` exited without a report;
- interactive `schtasks /IT` started Revit processes in console session 1, but
- desktop screenshot showed the Windows lock screen with `LogonUI.exe` running;
- locked-desktop launches produced zero-byte journals and no
  `%APPDATA%\ARTEL\family_factory` output;
- the test processes were stopped after diagnosis.

Next proof step: run the autorun command from the visible Legion desktop, or
open Revit and click `External Tools -> ARTEL Family Validate`, then ingest the
resulting `validation_*.json` with `tools/ingest_artel_validation_report.py`.

The macOS-side orchestrator for that proof is:

```bash
python3 tools/run_artel_legion_revit_validation.py \
  --artel-url http://127.0.0.1:5057 \
  --task-id task_0241 \
  --runtime-root /Users/ovc/Projects/LES_v2_reinstall_stress \
  --proxy-url http://127.0.0.1:8050 \
  --verify-search
```

On 2026-06-06 this command was smoke-tested against the locked Legion desktop.
It returned `status: "locked"`, confirmed Revit 2025 and the ARTEL add-in
exist, and stopped before starting Revit. The implementation uses
PowerShell `-EncodedCommand` and tolerant stdout decoding because Windows SSH
can otherwise break quoted paths and localized `quser` output.

## Backend Archive Bulk Smoke 2026-06-06

The Revit desktop was still locked, so no real `validation_*.json` could be
created from Revit. The backend archive side of the loop was verified with the
synthetic persistence report already stored on Legion:

- foreground backend command:
  `dotnet .\Agnostis.Api.dll` from
  `%TEMP%\artel-backend-persist\backend\Agnostis.Api\bin\Release\net8.0`;
- environment:
  `ARTEL_DATA_DIR=%TEMP%\artel-backend-persist\runtime-data`,
  `ASPNETCORE_URLS=http://127.0.0.1:5070`;
- SSH tunnel:
  `127.0.0.1:15070 -> legion:127.0.0.1:5070`;
- `GET /health` returned `ok`;
- `GET /api/validation-reports?taskId=task_0241` returned the archived report
  `report_1dd96d4690ac4eee9c78b8605cfaac89`;
- `GET /api/validation-reports/{reportId}/learning-case` returned
  `case_id = validation_report_1dd96d4690ac4eee9c78b8605cfaac89`;
- local `tools/seed_artel_backend_reports.py --no-sync --limit 1` wrote a
  markdown projection to a temporary runtime under
  `RAG_Content/ARTEL/family_learning_cases/`.

This proves the archived-report-to-learning-case bridge. It does not replace
the remaining real Revit proof because the source report was synthetic.
