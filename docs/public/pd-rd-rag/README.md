# PD/RD RAG Source Map

`PD/RD RAG Source Map` is a document-structure layer for retrieval over project and working documentation.

The goal is simple: do not throw a 200-page construction PDF into a vector index as a bag of chunks. Project documentation already contains a machine-readable structure: volume contents, project composition, explanatory-note table of contents, sheet stamps, ciphers, sheet numbers, source file names and declared sheet counts. This layer extracts that structure first and gives the model a map before retrieval.

## What It Extracts

- Volume contents: designation, title, note, section, sheet number and sheet count.
- Project composition: volume number, designation and section/subsection title.
- Explanatory note TOC: section number, title and target sheet.
- Sheet passport: sheet format, stamp presence, cipher, stage, sheet number, sheet count, document kind and source file name.
- PDF text repair for common Cyrillic extraction failures.
- Source references for every extracted row.

## Why It Matters

Typical RAG over project PDFs fails because the model sees isolated fragments without knowing where it is in the documentation set. For construction documents this is avoidable: the document set already has formal navigation.

This source-map layer lets a RAG system answer questions through a structured path:

1. Identify the relevant discipline or volume.
2. Choose the document type, for example explanatory note or graphical sheet.
3. Use the declared table of contents and sheet register.
4. Retrieve exact pages/sections.
5. Let the model answer using sources.

## Current MVP

The current MVP is read-only and deterministic. It does not call an LLM and does not replace the model's answer. It only prepares navigation data.

Supported input:

- PDF volumes with text layer.
- Russian PD/RD style documentation.
- SPDS/ESKD-like title blocks and volume registers.

Current output schemas:

- `pd_rd_manifest_v1`
- `volume_contents_register_v1`
- `project_composition_register_v1`
- `pz_toc_v1`
- `pd_rd_sheet_summary_v1`

## CLI Shape

```bash
python tools/pd_rd_manifest.py path/to/volume.pdf --output pd_rd_manifest.json
```

The JSON output can be stored as a sidecar next to the indexed document and used by retrieval, UI navigation or agent tools.

## Roadmap

- Cross-check declared contents against actual sheet stamps.
- Build a document graph: project section -> volume -> document kind -> sheet/page.
- Add table extraction for calculation tables in explanatory notes.
- Add graphical-sheet reader for drawn tables, equipment schedules and electrical schemes.
- Expose the map in UI as a human-readable document navigator.
- Use the map to constrain retrieval before broad vector fallback.

## Non-Goals

- It is not an OCR engine.
- It is not a CAD/DWG parser.
- It does not make engineering conclusions by itself.
- It does not generate final answers without a model.

The model still reads, reasons and answers. The source map gives it rails.
