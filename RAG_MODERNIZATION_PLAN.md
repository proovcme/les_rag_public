# LES RAG Modernization Plan

Updated: 07.06.2026

This plan now tracks the 02.06.2026 local + external baseline. The authoritative corpus has expanded to `1212` files and is closed locally: `1212 indexed`, `0 pending`, `0 errors`, `143150` SQLite chunks, `143150` Qdrant points, and `points_match_sqlite_chunks=true`. The closeout included SQLite/Qdrant backup, stale Qdrant point removal, and a duplicate-basename pending-selection fix. External `les.ovc.me` is live through the P.A.U.K. reverse SSH tunnel; public smoke passes `12/12`.

07.06.2026 ARTEL/Revit update: LES is now seeded as a Revit/RFA retrieval base
for the family factory, not yet as a fully proven Revit execution expert.
`ARTEL_Index` contains family guides, FOP/shared-parameter profiles, Revit data
model notes, Revit API references, Revit API symbol maps, Revit API SDK/CHM
markdown shards and learning-case projections. The latest ARTEL readiness audit
returns `ready_except_revit_locked`: index health is clean, managed Legion
backend/tunnel smoke passes, but the strict real Revit learning-case gate is
expected to fail until a validation report from an unlocked Revit desktop is
ingested.

## Current Constraint

- The active bottleneck is embeddings, not Qdrant, conversion, or chunking: recent parse batches show about 99% of elapsed time in `embed_sec`.
- Core ML is now the local default for embedding (`compute_units=all`, ANE/GPU eligible). The live validator default is deterministic `rules`; Core ML MiniLM remains installed for measured compare/probe and should only become default after a golden-threshold decision.
- The small validator/reranker path is measured infrastructure, not a mandatory query preprocessor for every simple question.
- Hybrid retrieval is no longer missing: the current implementation is SQLite
  FTS5/BM25 + dense vector retrieval with RRF merge. The next question is
  coverage, freshness and quality versus Qdrant-native sparse vectors, not
  whether hybrid exists at all.
- FIRE/HVAC are now handled as measured domain routes, not one-off answer
  patches: `golden/domain_fire_hvac_set.json` checks route filters, top
  evidence and source hints, and currently passes `16/16`.
- Structured Rules/LangExtract is schema/code-ready, but active `data/les_meta_qwen.db` has `0` `structured_rules` rows until a targeted `NORMATIVE`/`SPEC` reindex populates it.
- Validator context windows already exist through `validation_context_windows`.
  The next step is to verify whether the selected windows are the right
  evidence, not to blindly expand the prompt.
- ARTEL's remaining hard constraint is not retrieval. It is the Revit GUI
  execution loop on Legion: `RevitCoreConsole.exe` is absent, OpenSSH/Scheduled
  Task runs hit the Windows lock screen, and a real `validation_*.json` must be
  produced from an interactive Revit 2025 session before the expert loop can be
  called complete.

## Phase 0: Freeze And Verify

1. Wait for `pending_files=0` and `error_files=0`.
2. Verify `sqlite_chunks == qdrant_points`.
3. Snapshot SQLite and Qdrant before Docker removal or retrieval experiments.
4. Run the golden retrieval set and record baseline top sources, scores,
   top-k hit, latency and memory. Start small: 30-50 questions with expected
   documents/clauses are enough to compare Qwen/BGE, query prefixes, K.O.T.,
   hybrid and later HyDE/contextual retrieval.

Status 2026-06-01: items 1-3 are complete for the local corpus. Current
baseline is `1211 indexed / 0 pending / 0 errors`, `142193` SQLite chunks =
`142193` Qdrant points. The backup/snapshot and stale-point repair log live in
`artifacts/consistency_20260601_130603/`. FIRE/HVAC golden currently passes
`16/16`; full pytest passes `357` tests.

## Phase 1: Fix Cheap Runtime Issues

1. Show `/api/chat` `409 indexing mode` clearly in UI instead of "no answer".
2. Replace chat `innerHTML` rendering with safe DOM/text rendering for answers and sources.
3. Return the effective inferred `dataset_filter` in `/api/chat` responses.
4. Audit validator context windows and fix source/window selection if the
   current cited retrieval windows are not the right evidence.
5. Put reranker calls under the same LLM semaphore/resource budget as generation.
6. Stabilize Е.Ж.И.К. mail parsing before expanding mailbox volume:
   - isolate PDF attachment extraction (`PyMuPDF`/`fitz`) in a subprocess with timeout so a native crash cannot kill proxy/parser;
   - keep graceful fallback to `pdf_needs_ocr_vlm` when text extraction fails;
   - add regression tests for corrupted PDF attachments, image-only PDFs, oversized attachments and OCR/VLM-disabled mode;
   - add a mail import job/progress model for long IMAP imports instead of keeping the HTTP request as the only progress surface;
   - keep sensitive settings and logs redacted, including IMAP passwords and mailbox addresses where possible.

Status 2026-05-26: PDF subprocess isolation and IMAP job/progress are
implemented. Remaining mail stabilization work is mostly quality and evidence:
image-only PDF/OCR/VLM cases, mail-specific golden set and thread-aware
retrieval validation.

Live IMAP run notes 2026-05-26:

- Real background run `743b1517-841` completed: 50 new IMAP messages fetched,
  registered and indexed through two parse batches. Mail storage now has 200
  `.eml` files. Follow-up Core ML embedding parse on 2026-05-27 indexed the
  remaining 25 pending documents: `MAIL_Index` now has 200 indexed documents,
  0 pending documents and 475 chunks; Qdrant points match SQLite chunks.
  The original 25 pending documents were expected because Lite Admin sends
  `parse_batches=ceil(max_messages/25)`, not an unbounded parse of the whole
  mailbox.
- Make IMAP checkpointing two-phase. A proxy restart after fetch but before
  registration can leave raw `.eml` files on disk while UID checkpoint already
  advanced; local import recovers this, but the normal path should checkpoint
  only after durable registration succeeds.
- Add parse-phase progress inside `mail_imap_import`. Fetch progress reports
  UID/count correctly; during `parse_dataset` the job message remains on the
  current parse batch until the whole batch returns.
- Move local mail import/index to the same job/progress model. The legacy sync
  `/api/mail/import-local?parse=true` path can tie up proxy under real mailbox
  volume and should become an operator-safe background task.

Out-of-order runtime hardening 2026-05-26: MLX Host now has a host-level
LLM policy lock around peer unload + generation, RAM early-warning guard,
busy-aware unload, configurable validator context limit, idle embedder TTL and
localhost bind by default.

## Phase 2: Attack The Embedding Bottleneck

1. Benchmark `RAG_EMBED_BATCH`: `8 -> 16 -> 24 -> 32` on a small controlled sample.
2. Keep concurrency conservative; prefer larger batches over parallel embedding requests.
3. Add chunk-text hash caching for future retries and partial reindexing.
4. Test normative chunk profiles: larger chunk size, lower overlap, no split inside numbered clauses where possible.
5. Keep every benchmark tied to memory, swap, files/hour, chunks/file, and retrieval golden-set quality.

Core ML embedding canaries 2026-05-26/27:

- UI polling was saturating proxy CPU through repeated folder-watch/runtime
  refreshes. Added a short proxy-side folder-watch cache and stopped the UI
  during embedding measurements.
- `coremltools` 9.0 is locked in the optional `coreml` dependency group, so
  Core ML probes run with `uv run --group coreml ...` and do not become a
  runtime dependency.
- `intfloat/multilingual-e5-small` converted successfully via a manual
  BERT-like static wrapper (`batch=1`, `seq_len=128`) to
  `artifacts/coreml/multilingual_e5_small_b1_s128_static.mlpackage`.
- E5 pending mail benchmark, no Qdrant writes: `25` pending `MAIL_Index`
  messages produced `25` mail-vector texts. SentenceTransformers CPU: about
  `106 texts/s`; Core ML `CPU_AND_NE`: about `352 texts/s`; cosine agreement
  with PyTorch mean `0.99995`.
- The default Qwen3-Embedding-0.6B Torch/Transformers graph hit unsupported
  CoreMLTools nodes (`new_ones`, `diff`). A manual decoder-only static wrapper
  with fixed RoPE, causal mask and shape constants now traces and converts for
  canary shape `batch=1`, `seq_len=64`:
  `artifacts/coreml/qwen3_embedding_06b_b1_s64_static.mlpackage`.
- Qwen canary checks: trace cosine vs SentenceTransformers `~1.0`; saved
  Core ML package prediction cosine vs static Torch `0.99994`.
- Qwen pending mail benchmark, no Qdrant writes, `25` pending messages,
  `seq_len=64`: SentenceTransformers MPS `batch=1` about `21.6 texts/s`,
  SentenceTransformers MPS `batch=8` about `13.4 texts/s`, Core ML
  `CPU_AND_NE` `batch=1` about `60 texts/s`; cosine agreement mean
  `0.99978`.
- Qwen normative chunk canary, no Qdrant writes, `32` long `NTD_%` chunks from
  `lexical_chunks`: `seq_len=256` and `seq_len=512` both keep cosine near
  `0.99975`, but both truncate `100%` of this worst-case sample
  (`tokens_p50=720`, `tokens_p95=825`, `tokens_max=882`).
- Random `NTD_%` sample of `1000` chunks: `seq_len=256` truncates about
  `98.6%`, `seq_len=512` about `90.1%`, `seq_len=768` about `4.0%`,
  `seq_len=1024` `0%` in the sample. This makes `s1024` or a smaller
  chunking profile the real production-switch threshold for the current
  corpus, not `s256/s512`.
- Historical Qwen `batch=1`, `seq_len=1024` canary converted successfully to
  `artifacts/coreml/qwen3_embedding_06b_b1_s1024_static.mlpackage` before disk
  cleanup removed the package. On the
  same long `NTD_%` sample: SentenceTransformers MPS `batch=1` about
  `1.65 texts/s`; Core ML `CPU_AND_NE` `batch=1` about `3.92 texts/s`;
  cosine agreement mean `0.99977`; truncation `0%`.
- Qwen `batch=8`, `seq_len=256` converts successfully, but did not improve
  this Core ML path: `23.2 texts/s` versus `31.0 texts/s` for `batch=1`
  on the same `s256` long-chunk canary. Keep Core ML batching as a measured
  knob, not an assumption.
- Artifact size note: Qwen3-Embedding-0.6B Core ML packages are about `1.1 GB`
  each; E5-small is about `224 MB`. Disk/RAM budget should be planned around
  the real package size, not the model nickname.
- Re-run commands:
  `uv run --group coreml python tools/coreml_embedding_probe.py convert-e5` and
  `uv run --group coreml python tools/coreml_embedding_probe.py convert-qwen`.
  For Qwen mail canary:
  `uv run --group coreml python tools/coreml_embedding_probe.py bench-mail --model-id Qwen/Qwen3-Embedding-0.6B --coreml-model artifacts/coreml/qwen3_embedding_06b_b1_s64_static.mlpackage --seq-len 64 --st-device mps --st-batch-size 1 --limit 25`.
  For a normative chunk canary, first recreate the selected Core ML package, then run:
  `uv run --group coreml python tools/coreml_embedding_probe.py bench-chunks --coreml-model artifacts/coreml/qwen3_embedding_06b_b1_s512_static.mlpackage --seq-len 512 --st-device mps --st-batch-size 1 --coreml-batch-size 1 --limit 32 --min-chars 900`.

Mixture-of-specialists direction:

- Keep the big Qwen generator loaded only by lease for final synthesis and
  hard multi-step normative answers.
- Move cheap always-on work to specialists where quality holds: Core ML
  embedder, deterministic K.O.T. routing, measured reranker, measured
  validator/NLI classifier.
- Do not replace the generator with specialists. Specialists should reduce how
  often the big model is called and improve evidence quality before it is
  called.
- Runtime step 2026-05-27: MLX Host now supports `EMBED_BACKEND=coreml` with
  `COREML_EMBED_MODEL`, `COREML_EMBED_SEQ_LEN`, `COREML_EMBED_BATCH_SIZE`,
  `COREML_EMBED_COMPUTE_UNITS`, local tokenizer loading, optional fallback to
  SentenceTransformers, and `COREML_EMBED_ISOLATE_PROCESS=true`. The current
  `.env` points to the kept `b1_s512` Qwen package and runs it as guarded
  Core ML default on `cpu_and_gpu`. Older canary packages were removed during
  disk cleanup; recreate them only for a focused benchmark. Core ML embedding
  cold path previously
  produced launchd-recovered `SIGSEGV` events on `CPU_AND_NE`; `cpu_only`
  later returned zero vectors for this package and then crashed. The runtime now
  moves Core ML predict into a persistent
  JSONL worker child so native crashes are contained, surfaced through
  `/api/health` worker counters, vector norms are checked before response, and
  bad/zero vectors can fall back without killing MLX Host. A short circuit
  prevents repeated slow Core ML retries after consecutive native/quality
  failures. The current production posture is Core ML first with fallback disabled,
  so a hidden model-cache download cannot mask failures.
- Validator runtime step 2026-05-27: MLX Host now has
  `VALIDATOR_BACKEND=mlx|coreml|rules`. `rules` is the current live default,
  `coreml` is the measured candidate, and `mlx` remains a comparison backend
  rather than an always-on fallback. Core ML is wired for a
  fixed-shape NLI/cross-encoder package that receives `(question, context,
  answer)` as premise/hypothesis and returns `VERIFIED / NO_DATA /
  HALLUCINATION`. The first converted candidate is
  `MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli` with 4D attention masks;
  keep it on `cpu_only` because `cpu_and_ne` crashed on long validation windows.
  Validator Core ML predict also runs behind `COREML_VALIDATOR_ISOLATE_PROCESS`
  so the same MLE5 reset SIGSEGV class is contained in a worker child instead
  of the MLX Host process.
  Conversion/probe scaffolding lives in
  `tools/coreml_validator_probe.py`; the measured quality gate is
  `coreml_validator_probe.py compare` over `golden/validator_probe_set.json`
  plus real `validation_context_windows`, producing backend accuracy/latency
  and Core ML confidence-threshold sweeps before widening the public default.
  Current MiniLM CPU measurement on the old 8-case synthetic-derived set was
  fast but not meaningful enough. The relabelled frozen real-window validator
  set now lives at `golden/validator_real_window_set.json`: 33 cases, balanced
  across `VERIFIED / NO_DATA / HALLUCINATION`, with contexts materialized from
  real `validation_context_windows`. On that set, single-pass Core ML reached
  `0.3333` accuracy, but the windowed Core ML policy (`context_mode=windows`,
  `pair_mode=answer`, entailment threshold `0.8`, contradiction threshold
  `0.6`, margin `0.05`) reached `0.5152` accuracy at `0.0433s` mean latency.
  MLX NLI reached comparable accuracy at higher latency; the older Qwen causal
  validator measurement was slower and is now a historical quality reference, not
  the runtime default. As of 01.06.2026 the live validator runtime is
  `VALIDATOR_BACKEND=rules` after local index consistency closeout; keep
  Core ML MiniLM available for focused compare/probe and only switch it after
  golden accuracy, latency and threshold gates are clean. Do not convert a large causal validator as
  the first Core ML validator path; use larger models only as offline quality
  
## Phase 2.5: Hybrid Structural-Semantic Ingestion & Extraction (NEW, 31.05.2026)

**Статус:** ✅ Структурно реализовано и верифицировано синтетическими тестами; corpus population pending targeted reindex.

Мы внедрили гибридный структурно-семантический конвейер, который совмещает классический векторный RAG с реляционной базой нормативных правил в SQLite для абсолютного заземления ответов и борьбы с галлюцинациями.

### 1. Microsoft MarkItDown как единый стандарт парсинга офисных файлов
* **Суть:** Внедрен в `backend/converter.py`. Парсит презентации PowerPoint (`.pptx`), документы Word (`.docx`, `.doc`), таблицы Excel (`.xlsx`, `.xls`) и `.xml` в чистую Markdown-разметку.
* **Надежность:** Реализован отказоустойчивый конвейер с graceful fallback: если библиотека не установлена или завершается с ошибкой, парсер на лету переключается на классические локальные библиотеки `mammoth` (для Word) и `pandas` (для таблиц), гарантируя 100% стабильность.

### 2. MLX-Native Visual OCR через GLM-OCR-4bit (Визуальный RAG)
* **Суть:** Внедрен в `backend/ocr_parser.py`. Автоматически обнаруживает пустые или отсканированные PDF-документы (без текстового слоя) или сканы по требованию роутера (`markdown_needs_ocr`) и пропускает их через локальную визуальную VLM-модель.
* **Стек:** `mlx-community/GLM-OCR-4bit` (на базе `mlx-vlm`), работающая локально на GPU/Metal Mac Mini.
* **Управление памятью на Apple Silicon:** Модель загружается лениво. После завершения OCR-парсинга пакета страниц принудительно запускается сборщик мусора Python и очищается кэш Metal GPU (`mlx.core.metal.clear_cache()`), освобождая Unified Memory для работы основного чат-сервера.
* **Рендеринг:** Преобразование PDF в PIL-изображения выполняется на лету с помощью `pypdfium2` (с разрешением `RAG_OCR_DPI=150`) без захламления диска временными файлами.

### 3. База реляционных правил Google LangExtract с точным заземлением
* **Суть:** Внедрен в `backend/rules_extractor.py` и `backend/qdrant_adapter.py`. Для документов типа `NORMATIVE` и `SPEC` (нормативные и проектные акты) текстовые чанки при индексации пропускаются через извлекатель правил.
* **Схема правил:** Строгая Pydantic-модель `EngineeringRule` (субъект, параметр, математический оператор, численное значение, единица измерения, дополнительные условия).
* **Grounding (Заземление):** Извлекаются точные символьные offsets (`char_start`/`char_end`) в тексте чанка, указывающие, из какого фрагмента текста получено каждое правило.
* **Хранение:** Правила записываются в SQLite таблицу `structured_rules` с реляционными индексами, связывая их с `chunk_id` и `file_key`. На 01.06.2026 активная таблица пуста (`0` rows), что ожидаемо до targeted reindex нормативных документов с включённым extractor.
* **Режимы работы:** Локальный режим (Qwen-Instruct) для полной приватности, либо высокоточный облачный режим (Gemini 1.5 Flash/Pro) при наличии ключа `GEMINI_API_KEY` в `.env`.

### 4. Верификационные скрипты в песочнице (`scratch/`)
* `scratch/test_markitdown.py`: изолированная проверка конвертации офисных файлов.
* `scratch/test_langextract_synthetic.py`: проверка правильности разбора нормативного требования на русском языке о ширине эвакуационных выходов.
* `scratch/test_mlx_ocr.py`: тест OCR на любой странице PDF с контролем RSS памяти до и после выгрузки модели.

---

## Phase 3: Retrieval Quality Before More LLM

Accepted order after mail stabilization:

1. Use the golden set as the measuring stick for every retrieval change.
   Status 2026-05-27: `golden/domain_fire_hvac_set.json` is the first domain
   acceptance gate for live engineering use. It covers 8 FIRE and 8 HVAC
   questions, checks `dataset_filter`, expected source presence in top-N, and
   expanded query evidence. Current result: `16/16`.
2. Capture confirmed chat outcomes before adding smarter routing: every
   successful `/api/chat` answer now stores route/retrieval/dataset trace in
   `chat_history`, user feedback is written through
   `/api/chat/history/{id}/feedback`, including the visible `Плохой ответ`
   (`bad_answer`) action. Feedback is durable in SQLite, mirrored to
   `logs/chat_feedback.jsonl`, and negative statuses emit `[CHAT_FEEDBACK]`
   warnings in `logs/proxy.log`; `/api/chat/learning` exposes
   confirmed/marked cases for routing and dataset-cleanup heuristics.
3. Verify validator context quality with real examples from
   `validation_context_windows`; fix source/window selection only if the audit
   shows bad evidence.
4. A/B test Qwen3 query-side instruction prefix without reindexing. Do not
   enable it by belief; enable only if golden metrics improve without damaging
   latency or memory.
5. Expand K.O.T. terminology before LLM query rewriting: engineering
   abbreviations, mixed Russian/Latin spelling, common typos and dataset
   routing. Status 2026-05-27: the first expansion is live for exact
   engineering abbreviations (`ОВ`, `ВК`, `ЭОМ`, `КЖ`, `АУПТ`, `СКС`, etc.),
   `MAIL`, and FIRE/HVAC anchors (`СП 7.13130`, `противодым`,
   `дымоудаление`, `СП 60`, `60.13330`, `воздухообмен`, `микроклимат`,
   `холодопроизводительность`). Mail-shaped chat questions now use a
   deterministic Е.Ж.И.К. path over stored `.eml/.msg` before vector retrieval
   or generation.
6. Audit the current FTS5/BM25 + RRF hybrid layer: confirm the lexical index is
   complete, fresh and actually contributing to normative references, clause
   numbers, tables and abbreviations. Only then decide whether Qdrant-native
   sparse vectors/FastEmbed are worth the migration.
7. Add a retrieval evaluator before generation only after the deterministic
   path is measured: if top results are weak, conflicting, or too broad,
   rewrite/expand the query and retrieve again.
   Status 2026-05-27: simple normative navigation questions (`где смотреть`,
   `какие нормы`, `каким нормативом`) can return a deterministic source list
   through `deterministic_source_lookup`, which avoids LLM/validator failures
   for source-discovery questions and still records history/trace.
8. Add conditional reranking only for uncertain retrieval, not for every
   request. Prefer a specialized Qwen3 reranker over prompt-reranking through
   the validator model.

Analysis candidates, not committed implementation scope yet:

- Hybrid search: current baseline is FTS5/BM25 + dense vectors + RRF. Measure
  whether it is sufficient, stale, or needs Qdrant-native sparse vectors.
- Query rewriting: test normalization for engineering abbreviations (`ОВ`, `ВК`, `ЭОМ`, `КЖ`), typos, mixed Latin/Russian spelling and conversational wording before retrieval.
- HyDE: test only for short semantic questions where user wording is far from standards language; keep cost and memory impact explicit.
- Contextual retrieval: test on a small high-value normative sample before any full reindex; compare document/section/table context in chunk text against the current baseline.
- Qwen3-Embedding-4B: test only as a separate quality-run profile on a small
  collection. On the 24 GB host it must not run alongside chat/validator/heavy
  indexing.
- Offline eval: define 50-100 candidate golden questions and decide which metrics are actually useful for LES before making it a required release gate.

## Phase 3.5: K.O.T. Terminology Filter

The current K.O.T. behavior is a draft backed by `config/kot_terms.yaml` and
router/service logic. The configuration exists, but the engineering vocabulary
is still thin: it needs normal coverage for `ОВ`, `ВК`, `ЭОМ`, `КЖ`, `АУПТ`,
`СКС`, synonyms and mixed spellings. After indexing, promote it into a
first-class configurable semantic terminology filter:

1. Move domain rules, trigger tokens, synonyms, and dataset mappings into YAML or SQLite-backed configuration.
2. Add a small admin UI for terminology domains, synonyms, route priority, and suggested filters.
3. Return K.O.T. trace data in `/api/chat`: route reason, inferred `dataset_filter`, matched domains, clarification reasons, and confidence.
4. Add golden-set tests for engineering wording, abbreviations, mixed Russian/Latin terms, and ambiguous broad-review prompts.
5. Keep the default path deterministic; use a small model only for ambiguous, multi-domain, or multi-hop queries after the rule-based pass.

## Phase 4: Hierarchical And Graph Layers

1. Add parent-document retrieval: retrieve small chunks, then include parent sections around cited chunks.
2. Build RAPTOR-lite summaries for documents/datasets where broad questions are common.
3. Build GraphRAG-lite only for high-value relations:
   - document -> clause
   - clause -> referenced SP/GOST
   - document -> topic/domain
   - project artifact -> normative requirement
4. Do not run full GraphRAG over the whole corpus until the lighter graph proves value on the golden set.

## Phase 4.5: Е.Ж.И.К. Mail Vector Profile

Mail is not just another document type. Retrieval must preserve communication
context, otherwise the system can find the right words but miss who committed
to what, who received it, and how the thread evolved.

Status 2026-05-26: first mail-vector layer is implemented in code. Email
conversion now builds `mail_profile=v1`; Qdrant receives separate
`mail_message` and `mail_attachment` nodes with `from/to/cc/bcc`,
`who_to_whom`, `thread_key`, `Message-ID`, importance, attachment IDs and
OCR/VLM status. Remaining work: SQLite side tables, thread-aware retrieval
expansion and mail golden cases.

1. Build mail-specific embedding text:
   `subject`, `from`, `to`, `cc`, normalized participants, direction
   "who-to-whom", `thread_key`, date, attachment names, importance markers and
   body snippet/full body.
2. Store mail metadata in Qdrant payload and SQLite side tables so retrieval can
   filter by person, domain, thread, date range and attachment presence.
3. Add thread-aware retrieval: retrieve matching messages, then expand to the
   whole thread or nearest parent/reply window before generation.
4. Treat image attachments as first-class evidence. Add OCR/VLM extraction for
   screenshots, scans, photos and image-only PDFs; store attachment text with
   `attachment_id` and link it back to the parent message.
5. Add mail golden set cases for "who promised what", "who received this",
   "latest reply in thread", "attachment contains evidence", and ambiguous
   person/name queries.

## Phase 5: Small Model Policy

Use the small model conditionally:

- validator after generation;
- reranker when retrieval confidence is low;
- query planner/rewrite only for broad, ambiguous, or multi-hop questions;
- never as a mandatory preprocessor for every simple routed query.

The default path should remain cheap:

```text
rule-based router -> retrieval -> answer -> validation
```

The adaptive path should be explicit:

```text
rule-based router -> retrieval -> retrieval evaluator
  -> conditional rewrite/rerank -> answer -> validation
```

## References To Revisit

- Qdrant hybrid search and RRF/fusion.
- Qdrant multivectors / ColBERT-style late interaction.
- Qwen3 Embedding and Qwen3 Reranker model cards.
- CRAG / corrective retrieval before generation.
- Adaptive-RAG query complexity routing.
- RAPTOR hierarchical retrieval.
- Microsoft GraphRAG, limited to GraphRAG-lite for this corpus.
