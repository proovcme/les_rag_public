# LES Ecosystem

LES is the local knowledge and runtime core. VIZOR and Agnostis can be shipped as separate products, but they should use LES contracts instead of embedding their own RAG/runtime layers.

## Products

| Product | Role | Owns | Uses LES For |
|---|---|---|---|
| LES | Local knowledge core | RAG, Qdrant/SQLite, local MLX runtime, auth, dataset routing, CAD/BIM JSON ingestion | N/A |
| VIZOR | BIM/CAD visual viewer | WebGL viewer UX, IFC/JSON scene, object selection, standalone delivery | Object context, CAD/BIM search, selected element RAG |
| Agnostis | Revit family workflow | tasks, source files, specifications, Revit add-in workflow, validation reports, catalog | Similar family/task search, validation memory, RFA/RAG knowledge |

## Boundary Rules

- LES owns retrieval, indexing, local models, CAD/BIM graph storage and runtime health.
- VIZOR must not implement its own RAG. It can call LES for selected element context and search.
- Agnostis must not implement a parallel RAG. It calls LES through the Agnostis backend.
- Revit add-ins should call Agnostis, not LES directly.
- Raw RVT/RFA/DWG/IFC should be transformed into structured JSON/JSONL before LES indexing.
- Large local corpora, runtime databases and private samples stay out of product repos.

## Shared LES Contracts

### Health

```http
GET /api/health
```

Used by products to verify that LES proxy and retrieval backend are available.

### Retrieval-Only Search

```http
POST /api/search
```

Use this for interactive product UI. It returns ranked chunks and metadata without LLM generation.

Example:

```json
{
  "query": "Найди похожие RFA кейсы для металлического шкафа",
  "dataset_filter": "AGNOSTIS",
  "top_k": 8,
  "include_trace": false
}
```

### Chat

```http
POST /api/chat
```

Use this only when a generated answer is required. Product UIs should prefer `/api/search` first, then summarize with OpenRouter or local LES generation as a separate step.

### CAD/BIM Import

```http
POST /api/cad-bim/import
```

Canonical path for object graphs from exporters, VIZOR, Speckle-derived payloads and future RFA metadata extractors.

## Agnostis Data LES Should Index

Do not index only RFA binaries. LES should receive structured learning cases:

```text
FamilyLearningCase =
  task
  source summaries
  approved specification
  shared parameter profile refs
  Revit action log
  validation report
  catalog card
  recipe/archetype
  acceptance outcome
```

Recommended datasets:

- `AGNOSTIS_Index` for general task/spec/catalog cases;
- `RFA_RECIPES_Index` for archetypes and recipes;
- `VALIDATION_MEMORY_Index` for common validation failures and fixes;
- `CAD_BIM_Index` for canonical object graphs and viewer context.

## VIZOR Data LES Should Index

VIZOR should keep the viewer standalone, but LES-side context should store:

- selected object metadata;
- IFC `GlobalId` / source ids;
- layer/category/family/level/material;
- relations;
- extracted properties;
- markdown projections for retrieval.

## Practical Build Order

1. Stabilize `/api/search` as the shared retrieval-only contract.
2. Update Agnostis backend to prefer `/api/search` for `rag-context`.
3. Add an Agnostis structured import contract for `FamilyLearningCase`.
4. Add dataset routing for Agnostis/RFA/validation memory.
5. Let VIZOR use `/api/search` for selected object context when generation is not needed.
6. Package each product separately while keeping LES as the integration spine.
