# LES Ecosystem

LES is the local knowledge and runtime core. АТЛАС and АРТЕЛЬ can be shipped as separate products, but they should use LES contracts instead of embedding their own RAG/runtime layers.

## Products

| Product | Role | Owns | Uses LES For |
|---|---|---|---|
| LES | Local knowledge core | RAG, Qdrant/SQLite, local MLX runtime, auth, dataset routing, CAD/BIM JSON ingestion | N/A |
| АТЛАС | BIM/CAD visual viewer | WebGL viewer UX, IFC/JSON scene, object selection, standalone delivery | Object context, CAD/BIM search, selected element RAG |
| АРТЕЛЬ | Revit family workflow | tasks, source files, specifications, Revit add-in workflow, validation reports, catalog | Similar family/task search, validation memory, RFA/RAG knowledge |

## Boundary Rules

- LES owns retrieval, indexing, local models, CAD/BIM graph storage and runtime health.
- АТЛАС must not implement its own RAG. It can call LES for selected element context and search.
- АРТЕЛЬ must not implement a parallel RAG. It calls LES through the АРТЕЛЬ backend.
- Revit add-ins should call АРТЕЛЬ, not LES directly.
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
  "dataset_filter": "ARTEL",
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

Canonical path for object graphs from exporters, АТЛАС, Speckle-derived payloads and future RFA metadata extractors.

## АРТЕЛЬ Data LES Should Index

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

- `ARTEL_Index` for general task/spec/catalog cases;
- `RFA_RECIPES_Index` for archetypes and recipes;
- `VALIDATION_MEMORY_Index` for common validation failures and fixes;
- `CAD_BIM_Index` for canonical object graphs and viewer context.

Fresh installs can seed the public-safe demo case without private RFA data:

```bash
uv run python tools/seed_artel_learning_cases.py --verify-search
```

The tool writes a markdown projection under `RAG_Content/ARTEL/family_learning_cases/`,
calls only `/api/rag/sync/ARTEL`, and verifies that `/api/search` with
`dataset_filter="ARTEL"` returns a non-empty result.

## АТЛАС Data LES Should Index

АТЛАС should keep the viewer standalone, but LES-side context should store:

- selected object metadata;
- IFC `GlobalId` / source ids;
- layer/category/family/level/material;
- relations;
- extracted properties;
- markdown projections for retrieval.

## Practical Build Order

1. Stabilize `/api/search` as the shared retrieval-only contract.
2. Keep АРТЕЛЬ backend on `/api/search` for `rag-context`.
3. Keep the АРТЕЛЬ structured import contract for `FamilyLearningCase` public-safe.
4. Add richer dataset routing for RFA recipes and validation memory when those corpora exist.
5. Keep АТЛАС on `/api/search` for selected object context when generation is not needed.
6. Package each product separately while keeping LES as the integration spine.
7. Add public-safe seed data so a fresh LES install can return non-empty ARTEL context.

## Repository Layout

LES is now the umbrella repository for the boxed ecosystem. External product
repositories can stay as public/demo mirrors, but the private LES repo owns the
release source of truth:

- repository root: LES runtime, API, installers and packaging;
- `products/atlas`: АТЛАС product notes and release surface;
- `frontend/cad_bim_viewer`: АТЛАС source viewer;
- `standalone/cad_bim_viewer`: АТЛАС offline-ready runtime folder;
- `products/artel`: curated АРТЕЛЬ source snapshot, backend/OpenAPI/docs and legacy Revit add-in source.

Generated build output, local corpora, private IFC/RFA samples, runtime indexes,
logs and nested repository metadata stay out of git.
