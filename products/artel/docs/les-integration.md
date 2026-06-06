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
  "query": "Найди похожие BIM/RFA/CAD_BIM кейсы...",
  "dataset_filter": "CAD_BIM",
  "top_k": 8,
  "include_trace": false
}
```

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

For АРТЕЛЬ, LES should index:

- accepted family metadata;
- family specifications;
- validation reports;
- catalog cards;
- RFA-derived JSON summaries;
- recipes and archetypes;
- CAD/BIM object graphs where relevant.

This gives АРТЕЛЬ retrieval over:

- similar families;
- similar tasks;
- known validation failures;
- FOP/parameter patterns;
- family recipes.

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
