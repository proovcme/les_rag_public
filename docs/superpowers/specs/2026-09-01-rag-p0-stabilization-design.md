# RAG P0 Stabilization Design

## Status

Approved direction from the 2026-09-01 live Windows acceptance and independent
code review. Implementation is based only on `codex/model-rag-result` at
`22314023`; the installed working baseline is `0.30.42 · 682`, exact runtime
commit `ab5146b2`.

## Goal

Make project RAG evidence traceable, continuous across dialogue turns, bounded
without losing useful candidates, and honestly observable, while preserving the
single invariant path: the model writes queries and conclusions; LES retrieves,
validates provenance, waits for resources and packages deterministic artifacts.

## Non-goals

- Do not change `proxy/smeta_core/**`, norm selection, pricing or calculation.
- Do not add JSON planning, confirmation, review, mapping or extra model turns.
- Do not rewrite, expand, classify by discipline or otherwise alter a query
  authored by the model.
- Do not choose professional conclusions, norms or analogues in code.
- Do not build RAPTOR or ColBERT generations, reindex data, restart installed
  services, publish a release or modify the installed runtime in this package.
- Do not implement selectable SearXNG/Crawl4AI web research in this package.
- Do not merge `origin/main`, `public/pr/18` or the artifact-first release branch
  until this P0 package is independently accepted.

## Product invariants

1. The visible answer remains the exact model-authored answer.
2. Search queries reach native dense+sparse RRF without code-authored semantic
   rewriting or hidden model calls.
3. A retrieval ranker may order evidence but may not make an engineering or
   estimating decision.
4. Every source marker resolves to an honest typed locator. LES never presents a
   synthetic norm card as a file or invents a page.
5. A selected dataset is not automatically a permanent web ban. An explicit,
   frozen request capability determines whether public-web tools exist.
6. Optional retrieval stages fail open to the proven native-RRF order and report
   the bypass reason without leaking raw exceptions to the user.

## 1. Typed provenance and source navigation

### Source locator

Every model-visible evidence item and every displayed source carries one typed
locator:

- `file_excerpt`: `source_ref`, canonical dataset-relative path, optional page,
  chunk/locator and excerpt;
- `norm_card`: dataset/base identity, exact card identity/code and optional
  card-section locator;
- `web_result`: canonical public URL, title, provider and retrieval timestamp;
- `unavailable`: stable reason explaining why no source can be opened.

Legacy `source_ref`, page and locator fields remain readable, but source-map
construction normalizes them into the typed locator instead of discarding them.
Synthetic norm cards use `norm_card`; an empty `doc_id` is not converted into a
fake file reference.

### UI behaviour

`[Источник N]` is an actionable source marker. Activating it:

1. scrolls/focuses the matching item in the source drawer;
2. shows the exact excerpt and bounded surrounding context used as evidence;
3. offers `Открыть оригинал` when the locator is openable;
4. offers `Показать в папке` and `Копировать путь` for local file excerpts;
5. opens the typed norm-card view for `norm_card` locators;
6. displays an honest unavailable reason rather than a dead link.

Paths are shown relative to the selected dataset root and collapse repeated
ingestion prefixes. The canonical underlying reference is preserved in trace.

### Counts

The answer footer shows three non-overlapping labels:

- `Найдено` — unique internal candidates after exact-duplicate collapse;
- `Показано модели` — evidence items serialized into the model context;
- `Процитировано` — distinct valid source markers used by the final answer.

## 2. Dialogue evidence continuity

Chat history for model-driven RAG is built from the actual
`model_evidence_chunks`, not the initial retrieval accumulator. Each completed
turn stores an immutable evidence manifest containing frozen scope, query,
model-visible evidence ids, typed locators and cited ids.

The next turn does not receive all prior evidence text automatically. It gets a
compact prior-evidence index for cited and model-used sources. When a follow-up
needs the excerpt, the existing read/search tools resolve the stored locator.
This preserves `IOS_ES` continuity without replaying 50–70 full sources or
silently importing stale evidence into an unrelated question.

Typed working memory may be compacted, but the immutable evidence manifest and
frozen dataset/capability scope are not cleared by the model-driven route.

## 3. Explicit source capability scope

The chat request captures a user-visible boolean `selected_sources_only`.

- `false`: the profile's permitted local and web capabilities remain available;
- `true`: public-web search/read tools are absent from the model tool registry for
  that request and all of its follow-ups until the user changes the setting.

Selecting a dataset alone does not set this flag. The GUI exposes the control
next to the dataset selector and displays its effective value in the answer
trace. Natural-language instructions remain useful to the model, but the
enforced capability boundary comes only from this explicit control, not keyword
classification.

## 4. Retrieval overfetch, diversity and profile-owned limits

The model-authored query is executed once. Candidate handling is separated into
three values owned by the effective chat profile and editable in GUI:

- `retrieval_candidate_k`: internal native-RRF pool, default `64`;
- `document_diversity_k`: maximum distinct excerpts from one canonical physical
  document after exact-duplicate collapse, default `2`;
- `model_evidence_k`: evidence returned to the model per query, default `6`.

The pipeline is:

```text
unchanged model query
  → native dense+sparse RRF candidate pool
  → collapse exact duplicate source/chunk identities
  → enforce per-document diversity without deleting distinct required pages
  → optional ready ColBERT / common reranker
  → model_evidence_k results
```

Exact document/code early-exit remains available. Internal candidates never
enter the model context unless they survive the final evidence limit. Existing
profiles receive the defaults through an idempotent effective migration; the
stored immutable profile revision is not rewritten.

The evidence grouping code consumes `model_evidence_k` from the effective
profile. No independent literal `6` remains in tool execution, grouping or
result slicing.

## 5. Safe errors and bounded model admission

Tool and SSE failures expose a stable public error code plus Russian operator
message. Raw exception class/message and stack context remain only in diagnostic
trace/logs and are not serialized into user-visible text or model evidence.

Model admission uses the supported semaphore acquisition API with a bounded
wait. It does not inspect private `Semaphore._value` and does not reject a
sequential request merely because a slot is transiently occupied. Timeout and
cancel have stable public outcomes and release no slot they did not acquire.
The final semaphore change requires a focused concurrent regression and a live
trace reproduction before claiming the observed false-busy symptom closed.

## 6. Honest readiness semantics

The GUI and API keep separate dimensions:

- `backend_available` — Qdrant/backend responds;
- `contract_complete` — active generation has compatible dense+sparse contract
  and fingerprint coverage;
- `optional_stages` — ColBERT and other optional stages with readiness/bypass;
- `query_quality` — per-request quality assessment such as ambiguity or weak
  coverage.

A derived user-facing overall state names the blocking dimension and never
equates backend availability with generation completeness. A correct exact hit
is not shown as failed solely because a quality heuristic returned degraded;
the request trace keeps the heuristic detail separately.

## 7. ColBERT and RAPTOR policy

RAPTOR default and effective product mode become `off`; no RAPTOR generation is
built by this package.

ColBERT remains optional and GUI-controlled. Retrieval calls it only when:

- effective mode is not `off`;
- status readiness is `ready`;
- the active generation contract reports complete ColBERT multivectors;
- the circuit breaker permits the call.

`not_built` or incomplete vectors produce a clean `not_ready` bypass and never
open the circuit breaker. The GUI shows mode, effective model, model source,
candidate/output counts, query/passage token limits, latency budget, circuit
policy, generation estimate, readiness and rebuild requirement. Unsupported
model selection is displayed read-only rather than hidden.

ColBERT generation and activation require a later explicit step and a standalone
shadow A/B over the twelve live construction retrieval scenarios. RAPTOR and
ColBERT are not combined in that acceptance. PLAID is out of scope.

## 8. Tests and live acceptance

Each behaviour is implemented test-first with a focused regression:

1. file, page, excerpt and norm-card locators survive source-map serialization;
2. source marker resolves to its drawer item and open actions match locator type;
3. counters report found/model-visible/cited independently;
4. history persists `model_evidence_chunks`, frozen scope and cited handles;
5. `selected_sources_only=true` removes web capabilities; `false` preserves
   profile-authorized web access even with a selected dataset;
6. overfetch feeds the internal pool while only the configured evidence limit is
   serialized;
7. exact duplicate chunks collapse while distinct pages from one document obey
   the diversity cap;
8. profile defaults migrate effectively and all three limits round-trip through
   API/GUI;
9. raw exception names/messages do not enter SSE, model evidence or visible UI;
10. bounded semaphore waiting handles sequential, queued, timeout and cancel;
11. readiness dimensions remain distinct and produce a truthful overall state;
12. ColBERT bypasses cleanly until a complete ready generation exists; RAPTOR
    defaults off.

Offline gates are focused tests, `make architecture-gate`, `make verify` and
`make test`. Installed acceptance uses the exact candidate without publication:

- three-turn dialogue on each of the two construction datasets;
- exact, broad and negative retrieval cases;
- source marker → excerpt → original/path navigation;
- selected-sources-only with web unavailable, followed by web-permitted mode;
- concurrent two-request admission probe;
- workbook non-regression using the protected smeta benchmark only if the
  changed integration surface reaches estimate behaviour.

No installed mutation, service restart or release occurs without a separate
explicit owner instruction.

## Rollback and compatibility

The package introduces no destructive data migration. New profile fields have
effective defaults and old records remain readable. New evidence manifests and
typed locators are additive; legacy histories render with unavailable/openable
status derived from their existing fields. Disabling the new capability flag or
optional ColBERT stage returns the request to native RRF without changing user
datasets.

