# LES Integration

## Decision

АРТЕЛЬ should use LES as the retrieval and local knowledge layer.

АРТЕЛЬ remains responsible for:

- tasks;
- family specifications;
- catalog;
- Revit add-in workflow;
- OpenRouter orchestration;
- validation reports and acceptance.

LES remains responsible for:

- local RAG;
- Qdrant/SQLite retrieval;
- CAD/BIM JSON ingestion;
- object-level CAD/BIM context;
- local model runtime;
- dataset routing and validation.

## Why

Building another RAG layer inside АРТЕЛЬ would duplicate LES.

The correct architecture is:

```text
АРТЕЛЬ product workflow + LES retrieval/runtime
```

## LES runtime baseline

Checked on 2026-06-06:

- `GET http://127.0.0.1:8050/api/health` -> `status=ok`
- `GET http://127.0.0.1:8080/api/health` -> `status=ok`
- indexed files: `1212`
- chunks: `143150`
- Qdrant points: `143150`
- `points_match_sqlite_chunks=true`
- active CAD/BIM dataset: `CAD_BIM_Index`

## Current endpoints used by АРТЕЛЬ

### LES status

```http
GET /api/integrations/les/status
```

АРТЕЛЬ backend calls:

```http
GET {LES_BASE_URL}/api/health
```

### Task RAG context

```http
POST /api/tasks/{taskId}/rag-context
```

АРТЕЛЬ backend calls:

```http
POST {LES_BASE_URL}/api/search
```

Important: this MVP endpoint uses LES retrieval-only search, not LES chat.
It returns ranked chunks/sources/elements without local LLM generation.
Use LES `/api/chat` only as a separate optional summarization step.

Default LES payload:

```json
{
  "query": "Найди похожие ARTEL/RFA кейсы...",
  "dataset_filter": "ARTEL",
  "top_k": 8,
  "include_trace": false
}
```

For CAD/BIM object context АРТЕЛЬ can explicitly request `dataset_filter="CAD_BIM"`,
but the default task/family context is `ARTEL`.

## CAD/BIM ingestion path

LES treats JSON as the canonical CAD/BIM exchange format.

Preferred inbox:

```text
RAG_Content/CAD_BIM/JSON/
```

Preferred import endpoint:

```http
POST {LES_BASE_URL}/api/cad-bim/import
```

Important: raw RVT/RFA/DWG/IFC should be exported to canonical JSON/JSONL before indexing.

## Relevance to RFA generation

Factory architecture note: [family-factory.md](family-factory.md).

For АРТЕЛЬ, LES should index:

- accepted family metadata;
- family specifications;
- validation reports;
- catalog cards;
- RFA-derived JSON summaries;
- recipes and archetypes;
- CAD/BIM object graphs where relevant.

Public-safe seed:

```bash
uv run python tools/seed_artel_learning_cases.py --verify-search
```

This creates `RAG_Content/ARTEL/family_learning_cases/demo_metal_cabinet_001.md`,
syncs only `ARTEL_Index`, and verifies non-empty `/api/search` for
`dataset_filter="ARTEL"`.

This gives АРТЕЛЬ retrieval over:

- similar families;
- similar tasks;
- known validation failures;
- FOP/parameter patterns;
- family recipes.

Family guide seed:

```bash
python3 tools/seed_artel_family_guides.py \
  --guide-pdf /path/to/revit_family_creation_guide_autodesk_2017.pdf \
  --runtime-root /Users/ovc/Projects/LES_v2_reinstall_stress \
  --proxy-url http://127.0.0.1:8050 \
  --verify-search
```

The tool copies the PDF to `RAG_Content/ARTEL/family_guides/`, writes a
structured ARTEL quality requirements projection, syncs only `ARTEL_Index`, and
verifies retrieval. LES routes those files as `FAMILY_GUIDE`. This keeps
Autodesk/Revit family methodology separate from `FOP_PROFILE` shared-parameter
files and `LEARNING_CASE` accepted family cases.
If the official Autodesk attachment rejects non-browser downloads, use a
browser-downloaded local PDF or a curated markdown projection with the source
URL, outline, rules, checklist and retrieval hints.

Revit API reference seed:

```bash
python3 tools/seed_artel_revit_api_reference.py \
  --runtime-root /Users/ovc/Projects/LES_v2_reinstall_stress \
  --proxy-url http://127.0.0.1:8050 \
  --verify-search
```

The tool writes `RAG_Content/ARTEL/revit_api/revit_api_family_automation_reference.md`,
syncs only `ARTEL_Index`, and verifies retrieval. LES routes it as
`REVIT_API_REFERENCE`. Use it when АРТЕЛЬ needs API-level context for Revit
add-ins, family/template JSON extraction, `FamilyManager`, `FilteredElementCollector`,
transactions, shared parameters, connectors, loading/reloading families, or
Windows/Legion implementation planning.

Family factory sources seed:

```bash
python3 tools/seed_artel_revit_factory_sources.py \
  --runtime-root /Users/ovc/Projects/LES_v2_reinstall_stress \
  --proxy-url http://127.0.0.1:8050 \
  --seed-defaults \
  --verify-search
```

The tool writes:

- `RAG_Content/ARTEL/revit_model_guides/` as `REVIT_MODEL_GUIDE`;
- `RAG_Content/ARTEL/revit_api_symbol_map/` as `REVIT_API_SYMBOL_MAP`;
- `RAG_Content/ARTEL/revit_api_sdk_docs/` as `REVIT_API_SDK_DOC` when given
  extracted SDK HTML or `RevitAPI.chm`.

Default public inputs are the Rhino.Inside Revit data-model guide and
RevitAPIDocGen 2023 symbol map. Autodesk SDK/CHM content should stay local or
private: use it as LES runtime data, not as public repository content.

Legion/Revit SDK flow:

```bash
python3 tools/seed_artel_revit_factory_sources.py \
  --runtime-root /Users/ovc/Projects/LES_v2_reinstall_stress \
  --proxy-url http://127.0.0.1:8050 \
  --chm /path/to/RevitAPI.chm \
  --verify-search
```

If the workstation has no CHM extractor, extract the CHM to HTML first and use
`--sdk-html-dir /path/to/extracted/RevitAPI`.

Operational skill:

```text
products/artel/skills/revit-family/SKILL.md
```

The skill instructs agents to retrieve `FAMILY_GUIDE`, `REVIT_MODEL_GUIDE`,
`REVIT_API_REFERENCE`, `REVIT_API_SYMBOL_MAP`, `REVIT_API_SDK_DOC`,
`FOP_PROFILE`, and `LEARNING_CASE` evidence from LES before producing a family
specification, API implementation plan, validation checklist, catalog card, or
acceptance decision.

## Configuration

Backend config:

```json
{
  "Les": {
    "BaseUrl": "http://127.0.0.1:8050",
    "ApiKey": "",
    "TimeoutSeconds": 120
  }
}
```

Environment variables:

```text
LES_BASE_URL=http://127.0.0.1:8050
LES_API_KEY=
LES_TIMEOUT_SECONDS=120
```

For testing from Windows Legion over ZeroTier:

```text
LES_BASE_URL=http://10.195.146.98:8050
```

`LES_TIMEOUT_SECONDS` is clamped by АРТЕЛЬ to the `1..600` seconds range.
The default remains `120`, but `/api/search` should be much faster than chat generation.

## Current LES-side contract

The current `rag-context` endpoint uses the LES retrieval-only contract:

```http
POST {LES_BASE_URL}/api/search
```

Expected behavior:

- input: task question, dataset filter, max chunks, optional metadata filters;
- output: ranked chunks/sources/elements without model generation;
- latency target: under 2 seconds on warm runtime;
- separate optional step: summarize retrieved context with OpenRouter or local LES model.

## Integration rule

Revit add-in should not call LES directly in MVP.

Flow:

```text
Revit add-in -> АРТЕЛЬ backend -> LES
```

This keeps auth, logging, task context and product decisions centralized in АРТЕЛЬ.
