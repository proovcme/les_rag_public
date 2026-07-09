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

## Anti-pattern

Do not fix project PDF failures by only increasing
`RAG_PARSE_FILE_TIMEOUT_SEC`. Timeout growth hides the root issue and still makes
large intakes non-scalable. The correct fix is baseline-first indexing with
bounded enrichment. Table detection on pages with excessive vector drawing
objects is skipped with an explicit warning
`table_detection_skipped_heavy_vector_page` so one heavy plan sheet cannot block
the whole dataset run.
