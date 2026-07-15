# ALGO: PDF ingestion for RAG

Status: current canon from `0.24.0.237`.

## Rule

PDF ingestion is tiered. A PDF document must not fail RAG indexing when a basic
text layer can be extracted.

```text
Tier 0: manifest / file card
Tier 1: fast page text baseline        required, local, bounded
Tier 2: structured markdown/layout     optional enrichment
Tier 3: tables/OCR/images              optional enrichment
```

The baseline is evidence enough for search/navigation, not for exact table
calculation. Exact tables remain separate table/CAD/PDF enrichment work.
This is a general PDF contract, not a smeta-specific path.

## Runtime behavior

`backend/converter.py` uses PyMuPDF page text as the default indexing baseline
for real PDF files. This path keeps page anchors in markdown:

```text
# PDF text projection: file.pdf
## Page 1
...
## Page 2
...
```

Heavy converters (`pymupdf4llm`, Docling, OCR/table extraction) are not allowed
to be the gate for searchable RAG. If an isolated converter times out, indexing
falls back to the fast page-text layer instead of marking the document `ERROR`.

`backend/qdrant_adapter.py` then indexes real PDF/P7M files as bounded page
nodes instead of sending the whole markdown projection into generic markdown
heading splitters. Page nodes carry `payload.type=pdf_page_text`,
`source_layer=pdf_fast_text`, `page`, `page_part` and route metadata. Defaults:

```text
RAG_PDF_PAGE_NODES_ENABLED=true
RAG_PDF_PAGE_NODE_MAX_CHARS=1800
RAG_PDF_PAGE_NODE_OVERLAP_CHARS=150
```

This prevents hundreds of tiny structural chunks per ordinary project PDF and
keeps page anchors stable for source-map/read tools. The bound is deliberately
below the old generic markdown split threshold so the sentence-transformers
embedder does not receive long page batches that can allocate multi-GB
attention buffers.

Embedding is also part of the PDF ingestion contract. The runtime default is
`RAG_EMBED_BATCH=16` and `RAG_EMBED_TIMEOUT_SEC=300`; a searchable PDF must not
be marked `ERROR` only because one local CPU embedding batch takes more than
60 seconds.

Compact drawing labels are valid searchable content. If the normal lexical
tokenizer finds no word of three or more characters, native sparse encoding
uses a narrow fallback for uppercase technical designations (`BB_63`, `PE`,
`N`, phase labels). The fallback is not added to ordinary prose. Thus one
short technical fragment cannot produce an empty sparse vector and reject the
whole PDF.

The local Ollama-compatible embedding client retries a rejected/transient
batch a bounded number of times and then bisects it, preserving successful
fragments and their order while isolating an actually bad fragment. A final
failure reports the server's real reason and a content hash, not a generic
HTTP help link or document text. Dataset jobs remain `QUEUED` while waiting for
the parse semaphore, then expose the current file and the human stage
(`чтение страниц`, `создание поискового индекса`, `сохранение индекса`). The
shared jobs API derives percentage and ETA from completed files.

`backend/document_router.py` must not classify an ordinary design/project PDF
as `SMETA`/`TABLE_SMETA` just because it contains weak words like `смета затрат`
or a substring such as `тер` inside another word. PDF estimate routing requires
explicit estimate signals in the filename/text; electrical project PDFs with
`ЭОМ` route as general document/electrical corpus material.

## Local parsers

Allowed local parsers:

```text
PyMuPDF / PyMuPDF4LLM:
  primary local baseline and light markdown/layout path

Docling:
  optional structured enrichment for reading order, tables, formulas, OCR

Marker / Unstructured:
  optional benchmark/enrichment candidates; not current default
```

Cloud parsers are not default LES runtime dependencies.

## Acceptance

For a project folder with dozens or hundreds of PDF files:

```text
accepted PDF -> INDEXED page-text chunks OR explicit no_text_layer/manual_required
heavy table/layout timeout -> warning/enrichment failure, not document ERROR
raw PDF remains the source file; page-text chunks carry file/page anchors
tables/layout can be rebuilt later without deleting the baseline
ordinary project PDF with weak estimate words -> DOCUMENT/NTD_* not TABLE_SMETA
text-layer PDF -> page-level nodes, not markdown chunk flood
```

## Project PDF source-map layers

`project_pdf_extract_v1` is the dataset-level enrichment layer above baseline
PDF ingestion. It is written as sidecar data under
`storage/datasets/{dataset_id}/_les_pdf_extract` and is model navigation, not a
final answer. The extractor must keep this boundary:

```text
code extracts normalized facts/tables/source_refs
model reads the map and retrieved fragments, then answers
```

Discipline readers are additive plugins. They must never block the whole
project source-map: a missing/empty/broken PDF or a failed discipline reader is
a file-level warning/status.

Large datasets are processed as resumable batches. After each PDF the
orchestrator atomically writes `file_extract.json` beside that file's manifests.
The checkpoint is reusable only when `doc_id`, file name/path, size, mtime,
algorithm version and requested page depth still match. `max_files` limits new
PDF work in one invocation; valid checkpoints are included without consuming
that budget. A partial summary therefore resumes instead of returning a cache
hit, and a lost dataset-level summary can be rebuilt from file checkpoints.
Coverage always reports the aggregate attempted/unattempted set.

Current and planned normalized layers:

```text
common/drawing:
  title blocks, sheet formats, ciphers, stages, sheet names/numbers,
  volume contents, project composition, PZ contents

electrical ES/EOM:
  load tables, switchboards, circuits, protection devices, cable marks,
  cable cross-sections, cable lengths where present, VOR/SO material rows

HVAC OV:
  ХВС / characteristics of air systems tables:
    system id, served zone/room, airflow, pressure, temperature, heat/cold
    load, equipment, filter/heater/fan fields, source_ref
  equipment and material tables where present

water VK:
  water balance tables:
    consumer/system, cold/hot/process/fire water, wastewater, flow rates,
    daily/hourly peaks, units, source_ref
  equipment/material tables where present

room explications on planning sheets:
  room number, room name, area, category/fire category/functional class when
  present, floor/building/zone, sheet/source_ref
```

Room explications are not discipline-specific. They appear on many graphic
planning sheets and are extracted by the shared `project_pdf_table_manifest_v1`
layer before discipline-specific plugins attempt interpretation.

## Semantic Table Candidates

The shared table layer also emits compact `project_pdf_table_type_candidate_v1`
records for every PDF table detected in the text/vector layer. This is a
navigation surface for the model, not a normalized engineering fact table.

Each candidate carries:

```yaml
source_ref: file.pdf#page=N#table=M
semantic_type: one of the project table classes
category: engineering | service | navigation | noise | unknown
sample: first compact header/body lines
confidence: classifier confidence
```

Current semantic classes cover:

```text
STRUCT/CALC, STRUCT/REINF, STRUCT/GEO, STRUCT/LOAD
ENV/ACOUSTIC, ENV/AIR, ENV/SOIL, ENV/WASTE
FIRE, FIRE/AUPT, FIRE/LOWCURRENT, FIRE/RISK
AUTOMATION, LOWCURRENT
ELEC, ELEC/LINE, ELEC/LIGHT
HVAC, HVAC/HEAT, VK, ROOM
QTY, SPEC, TEP, TEP/STAFF, ENERGY, GEO, LEGAL/GPU, CATALOG
SERVICE, NAV, NOISE, TEXT, UNKNOWN
```

Before classification, consecutive PDF table fragments with the same header
are joined into one logical candidate. A headerless continuation of the known
`Имя панели / Помещение` grid inherits that header and is classified as
`ELEC/CABLE_JOURNAL`; its primary locator is `#tables=N-M` and `source_refs`
retains every original table locator. `Раздел / Наименование / Исполнитель` is
navigation (`NAV`, project composition). `ОТМ. 0.000` is emitted separately as
`ANNOTATION` with row/cell coordinates, even when it is embedded in a title
block. New manifests use the source path rather than a basename-only locator so
same-named files in different folders remain distinguishable.

`SERVICE`, `NAV` and `NOISE` are deliberately separated from engineering table
types:

- `SERVICE`: title blocks, frames, stamp-like repeated layout tables;
- `NAV`: composition, contents and drawing/document registers, including
  repeated project-volume composition tables headed by `№ тома / Обозначение /
  Наименование раздела`;
- `NOISE`: column-number rows, torn grid fragments, graphical plan debris and
  short low-current schematic callouts without a real tabular header.
- `TEXT`: paragraph fragments that PyMuPDF exposed through the table detector,
  including one-row long text samples; useful for diagnostics, not model-facing
  navigation.

Classifier rules stay local to the detected table sample and nearby table
context. They may down-rank repeated service/catalog/unknown noise into
`NAV`, `NOISE`, `SPEC` or a discipline-specific candidate when the header
pattern is stable. One-row table samples are not dropped automatically: long
one-row contents/paragraphs are classified as `NAV`/`TEXT`/discipline candidates
when the sample is stable, while short one-row debris still returns no semantic
candidate. The classifier must not synthesize answer text or infer row-level
facts without normalized rows/source fragments.

The model may use candidates to decide where to look next, but row-level claims
still need normalized rows or retrieved source fragments with `source_ref`.

## Addressable table registry

`project_table_registry_service` converts completed per-file table manifests into
a bounded JSONL search registry. A search hit is only a navigation card. `table_id`
binds document SHA-256, page, bbox, full normalized header, algorithm and detector
versions. For an engineering claim, `read_project_table(table_id)` validates size,
mtime, SHA-256, manifest/source linkage, versions, geometry and header before opening
the original PDF. A changed source/detector or fragments that no longer merge return
`stale`, never evidence. Only the exact verified matrix/normalized rows are evidence.
`UNKNOWN`, service, navigation and paragraph-like detector fragments remain in
coverage diagnostics but are excluded from the compact model navigation so they
cannot displace recognized `SPEC`, `ELEC`, `HVAC` and other engineering tables.

The source-map refresh also rebuilds the table registry and the document/virtual-
volume registry. Therefore a successful Л.И.С.Т. pass is immediately usable by
`search_project_tables`, `read_project_table` and `assemble_project_volume`; an
operator does not need to call separate build endpoints. These typed registries
are intentionally not copied into Qdrant as pseudo-evidence. Baseline page text
stays in the common dense+sparse index, compact source navigation goes to dataset
memory, and exact table rows are opened from the original PDF after identity checks.

## Documentation metadata model

`project_document_registry_service` builds a read-only JSON projection; it does not
claim to be a transactional database and does not invent a second document taxonomy.
It combines existing MetaDB classification, filename classifier, SPDS designation,
drawing-manifest fields, page-level sheet records and the LIST volume register:

```text
Documentation
└── Project (explicit link; else cipher, object name or address)
    └── Stage
        └── Virtual volume (metadata selection, never a merged PDF)
            └── Section
                └── Document + page/sheet properties
```

Contracts, commercial offers, estimates and correspondence stay related entities
under Documentation instead of being forced into a project stage. Stage values are
canonical (`ПД`, `РД`, `ИД`, etc.); a dataset explicitly named as working/project/
as-built documentation may provide a fallback stage with `stage_source=dataset_name`.
Sheet number/count values that exceed the real PDF page count are discarded at the
document-card level; their page-local raw source remains available in the sheet
register. The entire registry and virtual-volume result are navigation, not evidence.
Issued PDFs anchor volumes by canonical cipher+discipline. Supporting files join by
exact identity, then unique discipline/stage; directory path is the final fallback.
Every volume exposes `association_basis` and confidence.

## L.I.S.T. reliability contract

Since `0.24.0.344`, file roles and disciplines are recognized only from
delimited filename/cipher codes and a whitelist of project disciplines. Short
substrings such as `ВОР`, `СО`, `ПЗ` and `ОВ` must not match ordinary words
(`договор`, `состав`, `ПЗУ`, `условия`). A project-composition row mentioning
ЭС does not make the current PDF an electrical document.

Dataset summaries distinguish attempted and successfully extracted files:

```text
status=ok       every PDF was extracted
status=partial  at least one PDF succeeded and at least one failed/missing
status=failed   PDFs were supplied but none succeeded
status=empty    no PDFs were supplied
```

`coverage.files_attempted` is the number processed;
`coverage.files_extracted/files_ok` is the successful count;
`files_unattempted/files_limit_truncated` expose a `max_files` cut instead of
silently calling it complete. Bounded
`warnings`, `source_refs` and `volume_register` arrays expose matching
`*_total` and `*_truncated` fields. Row/table refs are kept ahead of generic
page refs. `dataset_id` is one safe path component and cannot escape the
sidecar storage root.

Generic manual tables are not promoted from weak words alone: a cable table
requires explicit cable fields, and a VOR table requires work name, unit and
quantity together. This keeps `line/length` parameters and a lone `quantity`
column in software or equipment manuals out of project navigation.

## Anti-pattern

Do not fix project PDF failures by only increasing
`RAG_PARSE_FILE_TIMEOUT_SEC`. Timeout growth hides the root issue and still makes
large intakes non-scalable. The correct fix is baseline-first indexing with
bounded enrichment. Table detection on pages with excessive vector drawing
objects is skipped with an explicit warning
`table_detection_skipped_heavy_vector_page` so one heavy plan sheet cannot block
the whole dataset run.
