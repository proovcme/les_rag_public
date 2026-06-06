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

The backend/RAG path is ready. The remaining Revit-side test needs GUI/manual
or add-in automation because `RevitCoreConsole.exe` is not present:

1. Open Revit 2025 on Legion.
2. Start from `Metric Casework.rft` or `Metric Electrical Equipment.rft`.
3. Open one standard cabinet family from the Base Cabinets folder.
4. Verify required shared/catalog parameters against the ARTEL task:
   `ADSK_Наименование`, `ADSK_КодИзделия`, `ADSK_Марка`, `ADSK_Примечание`.
5. Export a small public-safe validation summary into a future
   `FamilyLearningCase`.
