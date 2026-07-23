# SESSION HANDOFF 2026-07-06 — PD/RD RAG, ГОСТ 21.101-2026, source-map

Статус: сессию закрыли, дальше работать по ветке `feat/les3-p1`.

Текущий dev HEAD на момент хендоффа:

```text
62b5f494 docs: add ГОСТ 21.101-2026 PD/RD profile
85562dfc docs: localize PD/RD RAG public README
c5934fc0 feat: add PD/RD RAG source map
fc575e3d Show dataset topic map in UI
eac2d508 Add topic-guided retrieval pass
d2d0ff6f Add dataset topic source guide
```

Remote state:

- `origin/feat/les3-p1` pushed through `62b5f494`.
- `public/feat/les3-p1` pushed through `62b5f494`.

Live runtime state:

- Runtime root: `/Users/ovc/LES`.
- Dev root: `/Users/ovc/Projects/LES_v2`.
- `/api/version.les_version`: `0.24.0.276`.
- Deployed commit stamp: `fc575e3d`.
- Dev version in branch: `0.24.0.279`.
- Runtime code was **not** deployed after PD/RD/GOST commits.
- Live RAG source was updated separately: `ГОСТ Р 21.101-2026` is indexed in `NTD_SPDS_Index`.
- `/api/version.runtime_alignment`: `divergent`; reported changed files include `proxy/routers/runtime.py`, `proxy/services/document_explorer_service.py`, `proxy/services/version_service.py`, `sovushka/styles.py`.

## What Was Closed

### 1. Dataset navigation layer

Earlier commits in this branch added notebook-style dataset navigation:

- `dataset_topic_map_v1`;
- `dataset_section_map_v1`;
- topic-guided retrieval pass;
- UI visibility for dataset topic map.

This remains the direction: model chooses topic/file/section first, then retrieval targets the selected sources.

### 2. Drawing manifest MVP

Commit lineage around `0.24.0.277` added `drawing_manifest_service` and `tools/drawing_manifest.py`.

Capability:

- detects PDF sheet size/format;
- extracts expected bottom-right title-block zone;
- collects positioned text blocks;
- extracts candidates for object/address/volume/cipher/stage/sheet numbers;
- groups sheets by normalized cipher;
- treats `ИОС.ЭС.ПЗ` as document/discipline signal, not just text.

Important limitation: this is not schematic understanding yet. It reads stable SPDS/ESKD document structure and title-block text, not electrical line topology.

### 3. PD/RD manifest MVP

Commit `c5934fc0 feat: add PD/RD RAG source map`.

Files added:

- `proxy/services/pd_rd_manifest_service.py`
- `tools/pd_rd_manifest.py`
- `tests/test_pd_rd_manifest_service.py`
- `docs/PD_RD_RAG_MINI_PRODUCT.md`
- `docs/public/pd-rd-rag/README.md`

Capability:

- `pd_rd_manifest_v1`;
- `volume_contents_register_v1`;
- `project_composition_register_v1`;
- `pz_toc_v1`;
- compact `pd_rd_sheet_summary_v1`;
- PDF mojibake repair for glyph-layer text;
- no LLM, no final answer stubs, no graph interpretation.

Spot-check on PD IC / `395.01-B481.120100.2.4-ИОС.ЭС.pdf`:

- `volume_contents_register.row_count=92`, pages `5-8`;
- `declared_total_sheets=242`;
- `project_composition_register.row_count=49`, pages `9-12`;
- `pz_toc.row_count=32`, page `13`.

Known rough edge: appendix tail still has noisy multiline rows. Next parser layer should merge continuation lines and cross-check register rows against actual sheet stamps.

### 4. Public README localized

Commit `85562dfc docs: localize PD/RD RAG public README`.

Public branch now has Russian-first README for the mini-product.

### 5. ГОСТ Р 21.101-2026 indexed and documented

Commit `62b5f494 docs: add ГОСТ 21.101-2026 PD/RD profile`.

Added:

- `docs/PD_RD_REGULATORY_BASE.md`
- release entry `0.24.0.279`;
- `MODULE_INDEX` links from normcontrol and PD/RD manifest to the normative base;
- `PD_RD_RAG_MINI_PRODUCT` notes that live `NTD_SPDS_Index` now contains the 2026 standard.

Live RAG source details:

- Dataset: `NTD_SPDS_Index`
- `dataset_id`: `10ccce5f-99c5-4231-b1ff-0a2115371859`
- File: `ГОСТ Р 21.101-2026 СПДС Основные требования к проектной и рабочей документации.pdf`
- `doc_id`: `7177fcf6-631e-4e21-bf07-2a3f5ea77b0b`
- Status: `INDEXED`
- Chunks: `127`
- Domain/doc_type: `NTD_SPDS` / `NORMATIVE`

Old source remains:

- `ГОСТ Р 21.101-2020. Национальный стандарт Российской Федерации.docx`
- Status: historical/outdated source for comparison only.
- New checks should target 2026.

Indexing command path used:

- Upload to `NTD_SPDS_Index`.
- Direct `parse-batch` initially failed with `429` memory guard:
  `ram_free_gb=4.9`, `swap_pct=80.5`, required `ram_free_gb>=7.0`.
- Used official `parse-scheduler` with dataset priority `["NTD_SPDS_Index"]`, one batch, light guard:

```json
{
  "batch_limit": 1,
  "max_batches": 1,
  "dataset_priority_order": ["NTD_SPDS_Index"],
  "min_free_gb": 4.0,
  "max_swap_pct": 85.0,
  "post_batch_min_free_gb": 3.5,
  "post_batch_max_swap_pct": 90.0
}
```

Result:

- `files_parsed=1`;
- `errors=0`;
- `chunks=127`;
- `embedded_chunks=127`;
- embedder unloaded after batch.

Post-batch memory was still critical:

- `ram_free_gb≈5.3`;
- `swap_pct≈82`.

Do not start mass-parse until memory pressure is handled.

## Verified Retrieval

Search over live `NTD_SPDS_Index` works.

1. Query: `ГОСТ Р 21.101-2026 основные надписи форма 3 форма 5 форма 6 графа 1 графа 7 листов`

Result:

- top hit: page 18;
- includes basic inscription placement, forms 3/5/6 and title-block rules;
- `quality_status=good`.

2. Query: `ГОСТ Р 21.101-2026 состав проектной документации номер тома обозначение наименование приложение С форма 13`

Result:

- top hit: page 34;
- includes `Состав проектной документации`, `Содержание тома`, form 13 and volume/list rules;
- `quality_status=good`.

## What LES Can Read Now

From PD/RD documents:

- project composition register;
- volume contents register;
- PZ table of contents;
- sheet/title-block text if present in PDF text layer;
- stage, sheet number, total sheet count, format;
- cipher and its domain hints;
- source file names from title blocks;
- relations between content register rows and physical sheets.

From ГОСТ Р 21.101-2026:

- expected PD/RD composition and packaging;
- section ciphers;
- text/graphic document designation rules;
- title-block forms and fields;
- title-block placement;
- volume content and project composition rules;
- RD main-set structure;
- attached/reference document registers;
- change tables and change journals;
- electronic package concepts: GUID, `info.xml`, УЛ/ЭП.

From ПП N 87:

- expected logical content of PD sections;
- section 5 ИОС subsections;
- expected contents of ИОС.ЭС text and graphic parts.

## Product Direction

The architecture is now:

```text
PDF / project folder
  -> source-map parser
  -> project/volume/sheet/cipher/stamp/register graph
  -> model sees the map
  -> model selects topic/file/section/sheet
  -> targeted retrieval
  -> model answers with sources
```

This is the core principle:

- code extracts structure and provenance;
- model decides what matters and answers;
- no code-side domain answer stubs;
- missing/conflict are explicit, not hidden behind a generic answer.

## Next Session Start Here

Do not start with “add more prompt”.

Recommended next steps:

1. Make `ГОСТ Р 21.101-2026` an explicit normcontrol source.
   - Update `doc_review_retrieval_service` / `normcontrol_service` to target the 2026 document or rulepack first.
   - Keep 2020 out of current checks unless user asks for comparison/history.

2. Add `normative_profile_v1` for PD/RD.
   - PP N 87 expected sections.
   - ГОСТ Р 21.101-2026 expected ciphers/forms/registers.
   - Actual project composition from `pd_rd_manifest`.
   - Output: expected/actual/missing/extra/not_applicable.

3. Add `stamp_field_profile_v1`.
   - Detect form 3/5/6.
   - Extract fields: designation, object, building, sheet, sheets, stage, org, format, scale, signatures, dates, changes.
   - Compare against content/project registers.

4. Add `rd_manifest_v1`.
   - Main working drawing set.
   - Main-set mark.
   - General data.
   - Drawing/register/specification lists.
   - Attached/reference documents.
   - Local estimates/VOR if present.

5. Improve `volume_contents_register`.
   - Merge continuation lines.
   - Handle multiline appendix names.
   - Cross-check row sheet counts against actual detected sheet stamps.

6. UI/tools.
   - Show PD/RD source-map in Documents tab.
   - Tool calls: `read_pd_rd_map`, `find_sheet`, `find_volume_section`, `read_pz_section`, `read_gost_21_101_clause`.

7. Then only after this:
   - deeper graphic-part reading;
   - drawn tables;
   - line/symbol/topology extraction from schemes.

## Checks Already Run

Before `c5934fc0`:

- `uv run pytest tests/test_pd_rd_manifest_service.py tests/test_drawing_manifest_service.py -q` -> `12 passed`
- `make verify` -> ok, `2561 tests collected`

For `62b5f494`:

- `git diff --check -- docs/PD_RD_REGULATORY_BASE.md docs/PD_RD_RAG_MINI_PRODUCT.md docs/MODULE_INDEX.md docs/RELEASE_LEDGER.md proxy/services/version_service.py` -> ok
- `uv run python` import of `version_service` -> `LES_VERSION=0.24.0.279`
- live `/api/documents` check -> ГОСТ 21.101-2026 `INDEXED`, `127` chunks
- live `/api/search` checks -> `quality_status=good`

## Important Risks

- Worktree is dirty with many unrelated edits from broader tool/CAD/smeta work. Do not revert them casually.
- Runtime code is not deployed past `0.24.0.276`; dev branch is `0.24.0.279`.
- Live RAG source was updated, but code using it explicitly for normcontrol is not implemented yet.
- Memory pressure was high during indexing; do not start bulk parsing without checking `/api/runtime/dispatcher/status`.
- The current drawing/PD-RD parsers read document structure, not engineering semantics of schemes.

## Quick Commands

Check live version:

```bash
curl -fsS http://127.0.0.1:8050/api/version | python3 -m json.tool
```

Check ГОСТ 21.101-2026 in live RAG:

```bash
curl -fsS 'http://127.0.0.1:8050/api/documents/datasets/10ccce5f-99c5-4231-b1ff-0a2115371859/documents?q=21.101-2026&limit=5' | python3 -m json.tool
```

Search title-block rules:

```bash
curl -fsS -X POST 'http://127.0.0.1:8050/api/search' \
  -H 'content-type: application/json' \
  -d '{"query":"ГОСТ Р 21.101-2026 основные надписи форма 3 форма 5 форма 6","dataset_ids":["10ccce5f-99c5-4231-b1ff-0a2115371859"],"top_k":5,"max_chars":1200,"include_trace":true}' \
  | python3 -m json.tool
```

Search volume/project composition rules:

```bash
curl -fsS -X POST 'http://127.0.0.1:8050/api/search' \
  -H 'content-type: application/json' \
  -d '{"query":"ГОСТ Р 21.101-2026 состав проектной документации номер тома форма 13 содержание тома","dataset_ids":["10ccce5f-99c5-4231-b1ff-0a2115371859"],"top_k":5,"max_chars":1200,"include_trace":true}' \
  | python3 -m json.tool
```
