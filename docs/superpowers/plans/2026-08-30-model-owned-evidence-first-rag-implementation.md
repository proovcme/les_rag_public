# Model-owned Evidence-first RAG — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan.

**Goal:** In LES 0.30, give the effective chat model the full observable RAG packet first, let that model decide whether to search/read further, and stop code from answering, rejecting, retrying, or silently narrowing evidence on the model's behalf.

**Architecture:** An explicit scope has three states: `none`, selected datasets, or `all`. Grounded requests use the canonical named-collection native dense+sparse RRF for both initial retrieval and model-requested `search_sources`; exact readers remain tools. Every model invocation is governed by the real backend context capacity, packs evidence before memory, and records the exact evidence/source-map payload it received. Ungrounded requests skip document retrieval and document tools. The model's final text is transported unchanged; code only records mechanical provenance and execution state.

**Tech Stack:** Python 3.12, FastAPI, NiceGUI, Qdrant native RRF, Pydantic, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-08-30-model-owned-evidence-first-rag-design.md`

## Global Constraints

- Work only in the isolated 0.30 worktree based on deployed commit `9cddee74b4818bf03d9f3e8b75ac920c85c19692`.
- Do not touch `proxy/smeta_core/**`, user data, Qdrant storage, the installed runtime, updater, installer, or deployment services.
- Do not add dependencies, dataset-specific boosts, expected answer words, professional rules, validators, or a second semantic judge.
- Use Red → Green → Refactor for every behavior change and preserve the exact failing-test output in the working log.
- Commit after every completed task. Do not ship or deploy without a separate explicit owner instruction.

---

## Task 1: Derive model capacity once and pack evidence before memory

**Files:**

- Modify: `proxy/services/model_execution_preset_service.py`
- Modify: `proxy/services/context_governor_service.py`
- Test: `tests/test_model_execution_preset_service.py`
- Test: `tests/test_context_governor_service.py`
- Test: `tests/test_model_preset_workflow_parity.py`

- [ ] Add failing preset tests proving that a requested 32,768-token context stays 32,768 when the backend reports no smaller limit, that an observed 16,384 limit narrows it to 16,384, and that observed 32,768 is used when no request override exists.
- [ ] Run `uv run pytest tests/test_model_execution_preset_service.py tests/test_model_preset_workflow_parity.py -q --basetemp=.test-tmp/model-preset-red` and confirm failure is the current factory 6,000-token ceiling.
- [ ] Change preset resolution so factory capacity is fallback only when neither requested nor observed capacity exists; when both exist use the smaller total context. Keep 9B tool-call/round defaults but do not subtract generation or safety reserves here.
- [ ] Add a failing governor test with a tight budget where evidence fits and working memory is omitted, proving reserves are subtracted exactly once and evidence is ordered before memory.
- [ ] Run `uv run pytest tests/test_context_governor_service.py -q --basetemp=.test-tmp/context-governor-red` and confirm the current priority order causes the failure.
- [ ] Change the packing order to `profile → tool shortlist → request → evidence → source map → tool exchange → checkpoint → working memory → dialogue`; retain explicit omission reasons and physical token enforcement.
- [ ] Run the three focused files until green, then `git diff --check`.
- [ ] Commit: `git commit -am "fix(rag): use real context capacity and prioritize evidence"`.

## Task 2: Make document scope explicit and remove cache/code answers from grounded chat

**Files:**

- Modify: `proxy/services/scope_service.py`
- Modify: `proxy/routers/chat.py`
- Modify: `proxy/services/chat_evidence_application_service.py`
- Modify: `sovushka/pages/chat.py`
- Test: `tests/test_scope_model_v21.py`
- Test: `tests/test_chat_evidence_application_service.py`
- Test: `tests/test_sovushka_chat.py`

- [ ] Add failing scope tests: absent scope resolves to `none`; explicit `all` remains `all`; selected IDs remain frozen; `none` never becomes inferred/all-corpus routing.
- [ ] Run `uv run pytest tests/test_scope_model_v21.py tests/test_sovushka_chat.py -q --basetemp=.test-tmp/scope-red` and verify failures describe the current default-all UI/API behavior.
- [ ] Add `none` to the scope contract. Initialize Совушка with `none`/`Без источников`; provide separate explicit actions for no sources and all sources; always send the chosen scope in the chat payload.
- [ ] In the router, skip `resolve_dataset_ids`, document retrieval, typed document memory, and document tools for `none`; do not infer scope from question words. Preserve explicit selected/all behavior and attachment binding.
- [ ] Add failing application tests proving selected/all requests never read or write semantic answer cache and empty retrieval still invokes the model with an empty evidence packet.
- [ ] Run `uv run pytest tests/test_chat_evidence_application_service.py -q --basetemp=.test-tmp/grounded-flow-red` and verify failures hit cache/`NO_DATA` branches.
- [ ] Disable semantic answer cache for every grounded request and remove deterministic empty-retrieval final answers. Keep cache implementation available only for non-grounded compatibility, outside the grounded path.
- [ ] Run all three focused files until green, then `git diff --check`.
- [ ] Commit: `git commit -am "fix(rag): require explicit grounding scope"`.

## Task 3: Use canonical native RRF for model-requested search

**Files:**

- Create: `proxy/services/model_research_tool_service.py`
- Create: `tests/test_model_research_tool_service.py`
- Modify: `proxy/services/chat_evidence_application_service.py`

- [ ] Write failing tests for a small `ModelResearchToolService`: `search_sources` calls the injected canonical retriever with the model's query and frozen selected dataset IDs; it ignores model attempts to widen scope; non-search exact readers delegate unchanged to `ToolHarnessService`.
- [ ] Run `uv run pytest tests/test_model_research_tool_service.py -q --basetemp=.test-tmp/research-tool-red` and confirm import/API failure.
- [ ] Implement the service with a narrow result contract containing the ordinary tool payload, retrieved chunks, and retrieval trace. Bind `search_sources` to `retrieve_chat_chunks(..., return_trace=True)`; do not call `DocumentExplorer` for model research.
- [ ] Wire the service into the application runtime while keeping exact `read_source`, PDF, Excel, image, mail, and calculation tools on the existing harness.
- [ ] Add a regression test proving the tool result and returned chunks retain Qdrant/RRF provenance fields without semantic post-processing.
- [ ] Run the new test file and the application test file until green, then `git diff --check`.
- [ ] Commit: `git add proxy/services/model_research_tool_service.py tests/test_model_research_tool_service.py proxy/services/chat_evidence_application_service.py && git commit -m "fix(rag): share native RRF with model research"`.

## Task 4: Give every model call its evidence and expose the exact packet

**Files:**

- Modify: `proxy/services/chat_evidence_application_service.py`
- Modify: `proxy/services/context_governor_service.py`
- Test: `tests/test_chat_evidence_application_service.py`
- Test: `tests/test_context_governor_service.py`

- [ ] Add a failing application test proving the first tool-decision model request already contains the exact initial `EVIDENCE` and `SOURCE_MAP`, not only memory/checkpoint.
- [ ] Add a failing multi-turn test where the model asks `search_sources`, the returned native-RRF chunks are merged, and the next model call plus final-answer call both receive the expanded packet.
- [ ] Add a failing test proving identical successive model-requested calls are executed rather than stopped by code-level semantic deduplication; termination occurs when the model returns an empty call list or a physical deadline/cancellation fires.
- [ ] Build the initial evidence packet before the first model/tool decision, rebuild after each research result, and pass evidence/source map through the governor for every model invocation. Remove exact-call dedupe and total three-call/three-round semantic caps; retain schema validation, per-response batch bounds, cancellation, and a visible wall-clock deadline.
- [ ] Add failing trace tests requiring each model-call record to contain ordered evidence/source-map objects with `object_id`, exact text/value, SHA-256, included/omitted state, omission reason, and continuation cursor when truncated.
- [ ] Extend `context_packet_trace` to serialize those exact non-secret packet objects. Never serialize system credentials, hidden profile text, or private memory into the evidence trace.
- [ ] Run `uv run pytest tests/test_chat_evidence_application_service.py tests/test_context_governor_service.py -q --basetemp=.test-tmp/evidence-loop` until green, then `git diff --check`.
- [ ] Commit: `git commit -am "feat(rag): make model research evidence-first and observable"`.

## Task 5: Preserve the model's final answer unchanged

**Files:**

- Modify: `proxy/services/chat_evidence_application_service.py`
- Test: `tests/test_chat_evidence_application_service.py`

- [ ] Add failing tests proving ordinary chat never invokes TOSKA/answer validators, never retries because of a semantic verdict, and returns the model's final text byte-for-byte even when a citation label cannot be mechanically resolved.
- [ ] Run the focused tests and confirm the current validation/status mutation paths cause the failures.
- [ ] Remove semantic validation/retry/status mutation from the ordinary chat execution path. Keep mechanical citation/source matching only as trace metadata; it may not edit answer text, select a professional conclusion, or suppress the response.
- [ ] Preserve physical backend failure, cancellation, timeout, and context-overflow reporting as execution errors, not semantic verdicts.
- [ ] Run `uv run pytest tests/test_chat_evidence_application_service.py -q --basetemp=.test-tmp/model-answer` until green, then `git diff --check`.
- [ ] Commit: `git commit -am "fix(chat): preserve model-owned final answers"`.

## Task 6: Add the dataset-story acceptance probe

**Files:**

- Create: `tools/rag_dataset_story_acceptance.py`
- Create: `tests/test_rag_dataset_story_acceptance.py`

- [ ] Add failing tests for a CLI that requires an explicit dataset ID, sends the exact question `Расскажи про датасет.`, contains no expected answer terms, and writes the answer plus exact per-model-call evidence trace to a report.
- [ ] Add a failing readiness test: incompatible/non-RRF collection produces `N/A: corpus not ready`, not a fabricated pass/fail answer-quality score.
- [ ] Implement the API-only probe with UTF-8 output and argument lists. It must not inspect user data directly, reindex, modify runtime state, or grade the engineering meaning of the answer.
- [ ] Run `uv run pytest tests/test_rag_dataset_story_acceptance.py -q --basetemp=.test-tmp/dataset-story` until green, then run `uv run python tools/rag_dataset_story_acceptance.py --help`.
- [ ] Commit: `git add tools/rag_dataset_story_acceptance.py tests/test_rag_dataset_story_acceptance.py && git commit -m "test(rag): add open dataset-story acceptance"`.

## Task 7: Make documentation and version 0.30.1 truthful

**Files:**

- Modify: `docs/ALGO-context-memory.md`
- Modify: `docs/ALGO-tool-harness.md`
- Modify: `docs/ALGO-rag-best-practices.md`
- Modify: `docs/CODE_MAP.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `docs/TEST_INVENTORY.md`
- Modify: `config/version.json`
- Modify: generated version-contract files from `tools/sync_version_contract.py`
- Modify: `docs/RELEASE_LEDGER.md`

- [ ] Update the algorithm docs with the exact `none/selected/all` contract, evidence-first packet order, same-RRF research loop, model-owned stopping, exact trace, and non-judging code boundary.
- [ ] Update CODE_MAP/MODULE_INDEX/TEST_INVENTORY with every new entry point and test. Remove claims that memory precedes evidence, that lexical search is the model research path, or that validators decide ordinary chat answers.
- [ ] Set `product_version` to `0.30.1`, increment `build_number` from 634 to 635, run `uv run python tools/sync_version_contract.py`, and add a release-ledger row describing source state only (not deployed).
- [ ] Run `rg -n "TODO|TBD|PLACEHOLDER|default_all" docs/superpowers/specs/2026-08-30-model-owned-evidence-first-rag-design.md docs/superpowers/plans/2026-08-30-model-owned-evidence-first-rag-implementation.md docs/ALGO-context-memory.md docs/ALGO-tool-harness.md docs/ALGO-rag-best-practices.md` and resolve any plan/doc placeholders or stale default-all claims.
- [ ] Run `git diff --check`.
- [ ] Commit: `git add config docs && git commit -m "docs: define model-owned evidence-first RAG in 0.30.1"`.

## Task 8: Verify without deployment or corpus mutation

**Files:** none expected

- [ ] Run all focused tests changed in Tasks 1–6 with workspace-local basetemp.
- [ ] Run `make verify` (or the exact Makefile commands with `--basetemp=.test-tmp/verify` if `make` is unavailable).
- [ ] Run `make test` (or the exact Makefile commands with `--basetemp=.test-tmp/test`).
- [ ] Run `git diff 9cddee74b4818bf03d9f3e8b75ac920c85c19692 -- proxy/smeta_core` and confirm empty output.
- [ ] Run `git status --short`, `git log --oneline 9cddee74b4818bf03d9f3e8b75ac920c85c19692..HEAD`, and review every changed file against the design spec.
- [ ] Do not run the live dataset-story probe until the owner chooses the acceptance dataset and the readiness endpoint reports canonical RRF ready. Do not deploy.
