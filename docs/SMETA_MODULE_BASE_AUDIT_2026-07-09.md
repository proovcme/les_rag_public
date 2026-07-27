# Smeta module/base audit · 2026-07-09

Scope: dev checkout `/Users/ovc/Projects/LES_v2`. This is an audit only: no
runtime logic, databases, parquet files, or generated service notebooks were
changed.

## Verdict

The smeta stack is not clean enough for a golden БАП/СКС/Столп benchmark yet.
There are two separate classes of problems:

1. **Data/source hygiene:** the unified GESN base is the right direction, but it
   still contains incomplete rows and the pricebook layer has exact duplicate or
   wrongly named parquet files. The service RAG notebook also exposes these
   stale/scratch books.
2. **Model-first boundary:** code no longer hard-binds top candidates by default,
   but it still heavily shapes the candidate pool, ranking, workflow prompts and
   review prompts for BAP/SKS/finish cases. This is not pure arithmetic; it is
   code-side professional judgement embedded as routing and scoring.

For the next cleanup, treat the GESN/pricebook source layer as a product asset:
one canonical norm base, one visible book per actual region/period, no scratch
books in normal discovery, and no duplicate generated service docs.

## Closeout Status

Closed in `0.24.0.319`:

- Pricebook visible layer cleaned. Duplicate/scratch parquet files were moved out
  of `data/price_base` into `storage/cache/price_base_quarantine/20260709`.
- `config/domain/pricebook_manifest.json` is the canonical visibility/alias
  manifest for pricebooks.
- `SMETA_SERVICE` was regenerated from visible sources only and no longer shows
  `spb_refresh`, `spb_2kv2026`, `omskaya-oblast_2kv2026`, or
  `nizhegorodskaya-oblast_2kv2026`.
- Working pricebook discovery now reports `85` visible books, default
  `sankt-peterburg_2kv2026`.

Closed in `0.24.0.320`:

- Runtime-facing GESN/smeta base is now one structured SQLite database:
  `data/smeta_base/les_smeta_base.sqlite`.
- The raw/unified parquet remains a source/staging snapshot; `gesn_service`
  reads SQLite first for normal runtime calls.
- The `109130` rows with empty `norm_name`/`norm_unit` are `11849` whole
  `norm_key` groups with missing metadata, not mixed partial rows. They are not
  exposed to the machine base and are recorded in
  `data/smeta_base/les_smeta_base_manifest.json` as excluded source debt.
- Current structured base: `47037` norms and `664597` resource rows.

Closed in `0.24.0.321`:

- Update path is now explicit and reproducible:
  `ФГИС/raw → unified parquet → structured SQLite → SMETA_SERVICE cards`.
- `tools/gesn_update_from_fgis.py` runs that whole chain by default after a
  download/update, so SQLite and generated model-navigation cards do not lag
  behind source parquet.
- Operator shortcuts:
  - `make smeta-base`: checked unified parquet → SQLite → service cards.
  - `make smeta-base-source`: raw/cache → unified parquet → SQLite → service cards.
  - `make smeta-base-update`: FGIS download/update → full chain.

Still a separate refactor:

- Code/prompt heuristics that shape candidate ranking for БАП/СКС/finish remain
  outside this source-cleaning task. They should be handled as model-first
  retrieval refactor, not as late cleanup in the database task.

## Data Audit

### GESN unified base

Current source/staging files in `data/gesn_base`:

- `gesn2022_unified.parquet`
- `gesn2022_unified_audit.json`

Measured from `data/gesn_base/gesn2022_unified.parquet`:

- Rows: `773727`
- Unique `norm_key`: `58886`
- Base types:
  - `ГЭСН`: `460140` rows
  - `ГЭСНм`: `268165` rows
  - `ГЭСНр`: `26536` rows
  - `ГЭСНп`: `14257` rows
  - `ГЭСНмр`: `4629` rows
- `norm_name` empty: `109130`
- `norm_unit` empty: `109130`
- `per_unit <= 0`: `15974`
- Exact duplicate resource rows by `(norm_key, resource_code, resource_name, kind, per_unit)`: `0`
- `norm_key` with more than one `norm_name`: `0`
- `norm_key` with more than one `norm_unit`: `0`

Measured from `gesn2022_unified_audit.json`:

- `legacy_rows_remapped_by_typed_metadata`: `195278`
- `metadata_conflict_rows_dropped`: `32791`

Important positive check: typed keys are now separated. For example,
`ГЭСН:38-01-001-01` resolves to hydraulic/earthwork dam construction resources,
while `ГЭСНм:38-01-001-01` resolves to mounting sheet metal structures. They are
not the same norm and are not collapsed in the unified parquet.

Risk: `109130` rows with missing norm title/unit are too many for a golden
source. They may be resource-only leftovers or overlay artifacts, but until
classified, they are source debt. They are excluded from the runtime-facing
SQLite base instead of becoming model cards or lookup candidates.

### Structured machine base

Current files in `data/smeta_base`:

- `les_smeta_base.sqlite`
- `les_smeta_base_manifest.json`

Measured from `data/smeta_base/les_smeta_base_manifest.json`:

- Source rows: `773727`
- Source norm_key: `58886`
- Runtime norms: `47037`
- Runtime resources: `664597`
- Excluded norms missing name/unit: `11849`

SQLite tables:

- `norms`: typed identity, display code, base type, bare code, name, unit,
  work steps, source references, resource count/kinds.
- `resources`: norm_key FK, kind, resource code/name/unit, per-unit quantity,
  optional price, source references.

This is the normal machine-facing base. Parquet is kept for rebuild/audit and
bulk updates.

### Pricebooks

Current `data/price_base`: `89` parquet files.

Confirmed exact duplicate or misleading books:

- `data/price_base/omskaya-oblast_2kv2026.parquet` is byte-identical to
  `data/price_base/kostromskaya-oblast_2kv2026.parquet`; internal region is
  `Костромская область`.
- `data/price_base/nizhegorodskaya-oblast_2kv2026.parquet` is byte-identical to
  `data/price_base/gorod-sarov-nizhegorodskaya-oblast_2kv2026.parquet`;
  internal region is `город Саров (Нижегородская область)`.
- `data/price_base/spb_2kv2026.parquet` is byte-identical to
  `data/price_base/sankt-peterburg_2kv2026.parquet`; internal region is
  `Санкт-Петербург`.
- `data/price_base/spb_refresh.parquet` has only `2` rows and is a scratch
  refresh file for `город Санкт-Петербург`, `2 квартал 2025 г.`.

The code already hides scratch books in `fgis_price_service.available_pricebooks`
unless explicitly requested, but the files and generated service docs still
exist and can confuse humans, notebooks, and any source-map/RAG layer.

### Service RAG notebook

Current `RAG_Content/TABLE_SMETA/SMETA_SERVICE`:

- Total files: `97`
- `pricebook_*.md`: `47`
- `collection_*.md`: `49`

The overview currently exposes known bad/stale books:

- `nizhegorodskaya-oblast_2kv2026` shown as `город Саров (Нижегородская область)`
- `omskaya-oblast_2kv2026` shown as `Костромская область`
- `spb_refresh` shown as a normal card with `2` rows
- both `spb_2kv2026` and `sankt-peterburg_2kv2026` are present in parquet layer

Action: regenerate the service notebook only from the cleaned canonical source
inventory. Do not delete service notebook files blindly; they are system-facing
navigation artifacts. Remove/regenerate them through the service-source build
path.

## Module Boundary Audit

### P0: code still shapes norm choice

`proxy/services/estimate_harness_service.py` contains route and scoring logic
that is more than arithmetic:

- `WORK_FAMILY_COLLECTIONS` maps work families to allowed collections and
  special-cases `electric/backup_power` to allow `10`/`ГЭСНм10`.
- `_infer_finish_operation_route` rewrites generic finish lookup into
  `primer/putty/wallpaper/painting` based on source words.
- `_ROUTE_TERM_SETS` and `_ROUTE_FORBIDDEN_TITLE_ANCHORS` hard-code BAP, cable,
  pipe, box, low-current, and finish route terms.
- `_intent_route_candidate_rows` walks all norm rows, filters by allowed
  collections and forbidden title anchors, and sorts by `_route_row_priority`.
- `_route_row_priority` adds explicit bonuses/penalties: SKS -> `ГЭСНм10`,
  electric -> `08/ГЭСНм08`, BAP -> `10/ГЭСНм10`, cable with clamps over
  high-voltage/oil cable noise, indoor corrugated PVC over underground pipe,
  junction box over terminal box, etc.
- `_score_candidate` repeats many of the same domain bonuses and penalties.
- `check_applicability` rejects/ambiguous candidates by collection/family and
  title anchors before the model sees final candidate status.

This may be useful as a search heuristic, but it violates the stricter rule
“code does not decide professional meaning”. It can still hide or demote the
right norm and can overfit to recent БАП/СКС failures.

### P0: prompts contain case-specific repair logic

`proxy/routers/chat.py` now asks a model to choose lookup calls and norm codes,
which is better than code-only routing. But the prompts include detailed
case-specific rules:

- lookup selector prompt routes `ЭОМ/кабели/гофры/скобы/коробки/БАП` to
  `electric`, with explicit `element_type=box|pipe|cable|backup_power`;
- structured norm-choice prompt says how to prefer BAP small converters over
  large UPS, open wiring junction boxes over terminal boxes, ceiling candidates
  over wall candidates, finish analogs over empty rows, etc.

This is still professional judgement, just moved into prompt text. The durable
shape should be: general smetnik skill + neutral source map + model asks/read
cards, not a growing list of case patches.

### P1: old/live smeta layers need ownership cleanup

The repo still has multiple smeta entry points and historical layers:

- `proxy/services/estimate_harness_service.py`
- `proxy/services/smeta_norm_store.py`
- `proxy/services/smeta_artifact_service.py`
- `proxy/services/smeta_chat_service.py`
- `proxy/services/estimate_service.py`
- `proxy/routers/chat.py`
- `proxy/routers/estimates.py`

Some are current, some are import/legacy/support. The module index still lists
`smeta_chat_service` as part of the smeta flow, while the user-facing direct LSR
path is mainly in `chat.py` + `estimate_harness_service` +
`smeta_artifact_service`. This should be flattened into one current owner map:
what reads source docs, what calls model, what reads norms, what calculates,
what renders artifact, and what is legacy-only.

### P1: visible answer/artifact builder can obscure conflicts

`smeta_artifact_service.py` builds checked RIM forms from visible rows and can
replace the visible answer with trace-rendered LSR. That is acceptable only if
the artifact clearly exposes:

- source rows accepted vs missing;
- selected norm code provenance;
- rows priced vs `0.00`;
- KAC/pricebook gaps;
- removed/conflicting manual totals.

The function names show this is a display/calculation layer, not pure passive
formatting: `_select_lsr_source_tables`, `_select_pricebook_for_question`,
`build_checked_rim_form_from_visible_rows`, `_drop_conflicting_manual_totals`,
`compact_smeta_answer`, `_trace_lsr_visible_answer`.

## Cleanup Plan

1. **Freeze current audit.** Do not tune BAP/SKS again until the source layer is
   clean and the model/code boundary is explicit.
2. **Canonicalize pricebooks.**
   - Remove or quarantine byte-identical misleading parquet names:
     `omskaya-oblast_2kv2026`, `nizhegorodskaya-oblast_2kv2026`, one of
     `spb_2kv2026`/`sankt-peterburg_2kv2026`.
   - Keep `spb_refresh` only as cache/scratch, not a visible book.
   - Add a pricebook manifest with `stem`, `region`, `quarter`, `source_url`,
     `sha256`, `rows`, `visible`.
3. **Regenerate SMETA_SERVICE from manifest.**
   - Do not hand-delete required service files.
   - Rebuild `00_smeta_service_overview.md`, `pricebook_*.md`,
     `collection_*.md` from canonical source inventory.
4. **Classify GESN incomplete rows.**
   - Explain `109130` rows without `norm_name/norm_unit`: valid resource rows,
     bad overlay records, or legacy leftovers.
   - Add a base QA report with counts by `base_type`, `source_doc`, and
     `source_guid`.
   - Fail the update/build if a new source increases missing title/unit without
     an explicit audit reason.
5. **Split retrieval from professional judgement.**
   - Keep code retrieval neutral: lexical/FTS, typed identity, source cards,
     collection map, exact work composition.
   - Move professional selection guidance to smetnik skill, not route/scoring
     case patches.
   - Code may validate existence, units, arithmetic, price/KAC availability,
     duplicate source rows, and provenance.
6. **Simplify smeta entry points.**
   - Mark legacy modules as legacy or remove them after route verification.
   - Keep one live path for `сделай ЛСР`: source read -> model ВОР/norm choice
     -> code expand/price -> artifact.
7. **Only then rebuild golden tests.**
   - Golden should compare row coverage, selected norm provenance, priced rows,
     missing KAC/price rows, and total.
   - Unit tests that assert a case-specific candidate is first are not enough;
     they can pass while the live model returns a bad estimate.

## Evidence Commands

Commands run during the audit:

```bash
find data/price_base -maxdepth 1 -type f -name '*.parquet' | wc -l
find RAG_Content/TABLE_SMETA/SMETA_SERVICE -maxdepth 1 -type f | wc -l
find RAG_Content/TABLE_SMETA/SMETA_SERVICE -maxdepth 1 -type f -name 'pricebook_*.md' | wc -l
find RAG_Content/TABLE_SMETA/SMETA_SERVICE -maxdepth 1 -type f -name 'collection_*.md' | wc -l
uv run python - <<'PY'
# pandas audit of data/gesn_base/gesn2022_unified.parquet and
# data/gesn_base/gesn2022_unified_audit.json
PY
uv run python - <<'PY'
# pandas/hash audit of data/price_base/*.parquet
PY
rg -n "backup_power|ГЭСНм10|_route_row_priority|_intent_route_candidate_rows|_infer_finish_operation_route|unit_conflict|previous_candidates|max_calls" \
  proxy/services/estimate_harness_service.py proxy/services/smeta_norm_store.py proxy/routers/chat.py docs/CODE_MAP.md docs/MODULE_INDEX.md
rg -n "gesn2022|gesn2022_v2|spb_refresh|omsk|nizhegorod|Костром|Саров|ГЭСНм38|38-01-001-01" \
  RAG_Content/TABLE_SMETA/SMETA_SERVICE docs skills config proxy/services tests
```
