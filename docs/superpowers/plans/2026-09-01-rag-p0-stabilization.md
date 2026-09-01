# RAG P0 Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make model-driven project RAG traceable, bounded, continuous across dialogue turns and truthfully observable without altering model-authored queries, conclusions, or visible answers.

**Architecture:** Keep the existing single model-driven route and insert only deterministic evidence plumbing around it: effective profile limits feed native-RRF overfetch and diversity, actual model-visible chunks become an immutable evidence manifest, and typed locators drive source navigation. Capability scope, model admission, public errors, readiness, and optional rerank readiness are enforced at existing boundaries; no extra model call or domain decision is introduced.

**Tech Stack:** Python 3.12, FastAPI/Pydantic, NiceGUI, Qdrant native dense+sparse RRF, SQLite chat history, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-09-01-rag-p0-stabilization-design.md`

## Global Constraints

- Work only in `C:\Users\Oleg\les_rag\.worktrees\model-rag-result` on `codex/model-rag-result`.
- Preserve the exact model-authored query list and visible answer; do not add a planner, JSON protocol, confirmation, mapping loop, or extra model turn.
- Do not modify `proxy/smeta_core/**`, norm selection, pricing, formulas, workbook behavior, or estimate product defaults.
- Do not build RAPTOR/ColBERT generations, reindex data, restart or modify installed services, publish a release, merge `origin/main`, or integrate unrelated branches.
- RAPTOR effective default is `off`; ColBERT is optional and may run only against a complete ready generation.
- Existing immutable profile revisions and legacy history records remain readable; effective migrations are additive and idempotent.
- All new runtime behavior is visible/configurable in Sovushka; secrets and mail are out of scope.
- Every production behavior starts with a focused failing regression, then the smallest implementation that makes it pass.

---

### Task 1: Effective Retrieval Policy and GUI Round Trip

**Files:**
- Modify: `proxy/services/chat_profile_service.py`
- Modify: `sovushka/pages/profiles.py`
- Test: `tests/test_chat_profile_service.py`
- Test: `tests/test_sovushka_profiles.py`

**Interfaces:**
- Produces: `effective_retrieval_policy(snapshot: Mapping[str, Any]) -> dict[str, int]` with `retrieval_candidate_k`, `document_diversity_k`, and `model_evidence_k`.
- Produces: `effective_profile_snapshot()` carrying those three validated values in `rag_policy` without changing the stored profile revision.
- Consumes: existing arbitrary `rag_policy` profile API payload.

- [ ] **Step 1: Write failing effective-migration tests**

```python
def test_effective_profile_adds_retrieval_limits_without_mutating_revision():
    stored = {"mode": "search", "rag_policy": {"grounded": True}}
    effective = effective_profile_snapshot(stored)
    assert effective["rag_policy"] == {
        "grounded": True,
        "retrieval_candidate_k": 64,
        "document_diversity_k": 2,
        "model_evidence_k": 6,
    }
    assert stored == {"mode": "search", "rag_policy": {"grounded": True}}

def test_effective_retrieval_policy_clamps_invalid_values():
    policy = effective_retrieval_policy({"rag_policy": {
        "retrieval_candidate_k": 2,
        "document_diversity_k": 0,
        "model_evidence_k": 12,
    }})
    assert policy == {
        "retrieval_candidate_k": 12,
        "document_diversity_k": 1,
        "model_evidence_k": 12,
    }
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `uv run pytest tests/test_chat_profile_service.py -q --basetemp=.test-tmp/rag-p0-profile`

Expected: FAIL because the helper/defaults do not exist.

- [ ] **Step 3: Implement pure effective policy normalization**

```python
DEFAULT_RETRIEVAL_POLICY = {
    "retrieval_candidate_k": 64,
    "document_diversity_k": 2,
    "model_evidence_k": 6,
}

def effective_retrieval_policy(snapshot):
    raw = dict((snapshot or {}).get("rag_policy") or {})
    evidence_k = _bounded_int(raw.get("model_evidence_k"), default=6, low=1, high=64)
    return {
        "retrieval_candidate_k": max(
            evidence_k,
            _bounded_int(raw.get("retrieval_candidate_k"), default=64, low=1, high=512),
        ),
        "document_diversity_k": _bounded_int(
            raw.get("document_diversity_k"), default=2, low=1, high=32
        ),
        "model_evidence_k": evidence_k,
    }
```

- [ ] **Step 4: Add three numeric profile controls using the existing rag-policy editor**

Add NiceGUI numeric controls labelled `Кандидаты RRF`, `Фрагментов на документ`, and `Evidence модели` which update the three exact `rag_policy` keys and display their effective values.

- [ ] **Step 5: Run profile and GUI tests and confirm GREEN**

Run: `uv run pytest tests/test_chat_profile_service.py tests/test_sovushka_profiles.py -q --basetemp=.test-tmp/rag-p0-profile`

- [ ] **Step 6: Commit the independently usable policy change**

```text
feat(rag): make evidence limits profile-owned
```

### Task 2: Native-RRF Overfetch, Exact Deduplication, and Diversity

**Files:**
- Create: `proxy/services/retrieval_candidate_service.py`
- Modify: `proxy/services/retrieval_service.py`
- Modify: `proxy/services/model_research_tool_service.py`
- Test: `tests/test_retrieval_candidate_service.py`
- Test: `tests/test_retrieval_service.py`
- Test: `tests/test_model_research_tool_service.py`

**Interfaces:**
- Produces: `candidate_identity(chunk) -> tuple[str, str]`, `physical_document_identity(chunk) -> str`, and `select_diverse_candidates(chunks, *, per_document_k: int, limit: int) -> list[Any]`.
- Changes: `retrieve_chat_chunks(..., result_limit=None, candidate_limit=None, document_diversity_k=None)` so backend `top_k` uses the internal candidate pool while the returned list uses the evidence limit.
- Changes: `ModelResearchToolService(..., retrieval_candidate_k=64, document_diversity_k=2, model_evidence_k=6)` and removes every independent literal six from execution/slicing.

- [ ] **Step 1: Write failing pure selection tests**

```python
def test_exact_duplicates_collapse_but_distinct_pages_survive():
    chunks = [chunk("a.pdf", "c1", 1), chunk("a.pdf", "c1", 1), chunk("a.pdf", "c2", 2)]
    assert [(x.meta["chunk_id"], x.meta["page"]) for x in select_diverse_candidates(
        chunks, per_document_k=2, limit=6
    )] == [("c1", 1), ("c2", 2)]

def test_per_document_cap_preserves_rank_order_across_documents():
    chunks = [chunk("a.pdf", "a1", 1), chunk("a.pdf", "a2", 2), chunk("b.pdf", "b1", 1)]
    assert [x.meta["chunk_id"] for x in select_diverse_candidates(
        chunks, per_document_k=1, limit=6
    )] == ["a1", "b1"]
```

- [ ] **Step 2: Run candidate tests and confirm RED**

Run: `uv run pytest tests/test_retrieval_candidate_service.py -q --basetemp=.test-tmp/rag-p0-candidates`

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement stable identity, deduplication, and diversity helpers**

Use canonical `source_ref`/path plus page/chunk identity. Treat norm-card code as a card identity. Do not collapse distinct pages merely because basenames match.

- [ ] **Step 4: Write failing retrieval-boundary tests**

```python
async def test_result_limit_does_not_shrink_native_rrf_pool():
    result = await retrieve_chat_chunks(
        question="q", dataset_ids=["ds"], rag_backend=backend,
        result_limit=6, candidate_limit=64, document_diversity_k=2,
        return_trace=True, **deps,
    )
    assert backend.calls[0]["top_k"] == 64
    assert len(result.chunks) <= 6
    assert result.trace.candidate_count == 64
```

- [ ] **Step 5: Implement overfetch and post-rerank final selection**

The unchanged query reaches native RRF once with `candidate_limit`; exact dedup and diversity run deterministically; optional rerank only reorders; final slicing uses `result_limit`. Record `found_count`, `model_visible_count`, and diversity settings in trace.

- [ ] **Step 6: Write and pass configurable tool-service tests**

Replace assertions that hard-code six with constructor-provided limits, including dedicated norm-card RRF. Assert `retrieval_candidate_k=64` reaches retrieval while only `model_evidence_k` chunks enter the result.

- [ ] **Step 7: Run all focused retrieval tests and confirm GREEN**

Run: `uv run pytest tests/test_retrieval_candidate_service.py tests/test_retrieval_service.py tests/test_model_research_tool_service.py -q --basetemp=.test-tmp/rag-p0-retrieval`

- [ ] **Step 8: Commit the independently testable retrieval pipeline**

```text
fix(rag): overfetch before evidence diversity
```

### Task 3: Typed Provenance and Honest Evidence Counts

**Files:**
- Create: `proxy/services/source_locator_service.py`
- Modify: `proxy/services/evidence_packet_service.py`
- Modify: `proxy/services/chat_evidence_application_service.py`
- Test: `tests/test_source_locator_service.py`
- Test: `tests/test_chat_evidence_application_service.py`

**Interfaces:**
- Produces: `source_locator(chunk: Any) -> dict[str, Any]` with kinds `file_excerpt`, `norm_card`, `web_result`, or `unavailable`.
- Produces: `source_map_item(chunk, *, index: int) -> dict[str, Any]` retaining legacy fields and adding `locator`.
- Changes: `_model_rag_source_map()` delegates to this service and reports the actual `Qx.Hy` evidence references.

- [ ] **Step 1: Write failing typed-locator tests**

```python
def test_file_locator_preserves_source_ref_page_chunk_and_excerpt():
    item = source_map_item(file_chunk(), index=1)
    assert item["locator"] == {
        "kind": "file_excerpt", "source_ref": "ds/spec.pdf#p7",
        "relative_path": "spec.pdf", "page": 7, "chunk_id": "c-7",
        "excerpt": "used text",
    }

def test_norm_card_without_doc_id_is_not_presented_as_file():
    item = source_map_item(norm_chunk(), index=1)
    assert item["locator"]["kind"] == "norm_card"
    assert item["locator"]["card_code"] == "ГЭСН01-01-001-01"
```

- [ ] **Step 2: Run locator tests and confirm RED**

Run: `uv run pytest tests/test_source_locator_service.py -q --basetemp=.test-tmp/rag-p0-locator`

- [ ] **Step 3: Implement normalization without invented coordinates**

Preserve canonical references in trace, collapse repeated ingestion prefixes only in `relative_path`, and emit `unavailable.reason` when no honest locator exists.

- [ ] **Step 4: Write failing model-RAG serialization regression**

Assert `Q1.H1`, `source_ref`, page, exact excerpt, typed locator, `found_count`, `model_visible_count`, and `cited_count` survive `_model_rag_source_map()` and the response trace.

- [ ] **Step 5: Wire source maps and independent counters**

`found_count` comes from post-dedup candidates, `model_visible_count` from `model_evidence_chunks`, and `cited_count` from distinct valid markers in the unchanged final answer.

- [ ] **Step 6: Run focused provenance tests and confirm GREEN**

Run: `uv run pytest tests/test_source_locator_service.py tests/test_chat_evidence_application_service.py -q --basetemp=.test-tmp/rag-p0-provenance`

- [ ] **Step 7: Commit typed provenance**

```text
fix(rag): preserve typed evidence locators
```

### Task 4: Actionable Source Markers and Drawer Navigation

**Files:**
- Modify: `sovushka/answer_render.py`
- Modify: `sovushka/pages/chat.py`
- Test: `tests/test_answer_render_v16.py`
- Test: `tests/test_sovushka_chat.py`

**Interfaces:**
- Consumes: typed `locator` from Task 3.
- Produces: `citation_drawer_item()` actions `open_original`, `show_in_folder`, `copy_path`, or `open_norm_card` according to locator kind.
- Produces: a marker-to-source index map so `[Источник N]` focuses the exact drawer item.

- [ ] **Step 1: Write failing renderer tests for every locator kind**

Assert file excerpts expose quote/context and local actions, norm cards expose only card navigation, web results expose canonical URL, and unavailable locators expose a reason with no dead link.

- [ ] **Step 2: Run renderer tests and confirm RED**

Run: `uv run pytest tests/test_answer_render_v16.py -q --basetemp=.test-tmp/rag-p0-render`

- [ ] **Step 3: Implement locator-driven drawer payloads and three counts**

Keep legacy fallback behavior, but make typed locator authoritative. Render `Найдено`, `Показано модели`, and `Процитировано` from separate response fields.

- [ ] **Step 4: Write failing chat-page marker navigation test**

Assert activating marker 3 opens/focuses drawer item 3 and invokes only the action available for its locator type.

- [ ] **Step 5: Wire marker activation and local actions using existing component registry**

No new design system component. Reuse the registered drawer/buttons and existing document endpoints.

- [ ] **Step 6: Run UI tests and confirm GREEN**

Run: `uv run pytest tests/test_answer_render_v16.py tests/test_sovushka_chat.py -q --basetemp=.test-tmp/rag-p0-ui`

- [ ] **Step 7: Commit source navigation**

```text
feat(ui): make source markers actionable
```

### Task 5: Immutable Evidence Manifest and Dialogue Continuity

**Files:**
- Create: `proxy/services/chat_evidence_manifest_service.py`
- Modify: `proxy/services/chat_evidence_application_service.py`
- Modify: `proxy/routers/chat.py`
- Test: `tests/test_chat_evidence_manifest_service.py`
- Test: `tests/test_chat_evidence_application_service.py`
- Test: `tests/test_chat_history_router.py`

**Interfaces:**
- Produces: `build_evidence_manifest(*, query, scope, chunks, answer) -> dict[str, Any]` schema `les.chat-evidence-manifest.v1`.
- Produces: `compact_prior_evidence_index(manifests, *, max_items=24) -> tuple[dict[str, Any], ...]` containing ids/labels/locators, never full prior evidence bodies.
- Changes: history trace stores the manifest built from final `model_evidence_chunks`, frozen dataset scope, and cited handles.

- [ ] **Step 1: Write failing manifest tests**

Assert immutability-by-copy, exact `Qx.Hy` handles, typed locators, cited subset, and compact output without full excerpts.

- [ ] **Step 2: Run manifest tests and confirm RED**

Run: `uv run pytest tests/test_chat_evidence_manifest_service.py -q --basetemp=.test-tmp/rag-p0-manifest`

- [ ] **Step 3: Implement manifest builder and compact index**

Do not infer relevance or import evidence from unrelated turns. Preserve only actual model-visible and cited identities.

- [ ] **Step 4: Write failing history regression using different initial and model-visible chunks**

Assert saved `sources`, `source_dataset_ids`, and evidence manifest come from `model_evidence_chunks`, not initial `chunks`; assert the next turn receives compact locator handles while full old evidence text is absent.

- [ ] **Step 5: Wire final evidence state through response/history/session context**

Replace the model-driven `working_memory=()` loss only with the compact prior-evidence index. Do not add a model call or replay full evidence.

- [ ] **Step 6: Run history and application tests and confirm GREEN**

Run: `uv run pytest tests/test_chat_evidence_manifest_service.py tests/test_chat_evidence_application_service.py tests/test_chat_history_router.py -q --basetemp=.test-tmp/rag-p0-history`

- [ ] **Step 7: Commit dialogue continuity**

```text
fix(chat): persist model-visible evidence manifest
```

### Task 6: Explicit Selected-Sources-Only Capability

**Files:**
- Modify: `proxy/routers/chat.py`
- Modify: `proxy/services/chat_evidence_application_service.py`
- Modify: `sovushka/pages/chat.py`
- Test: `tests/test_chat_stream_w51.py`
- Test: `tests/test_chat_evidence_application_service.py`
- Test: `tests/test_sovushka_chat.py`

**Interfaces:**
- Adds: `ChatRequest.selected_sources_only: bool = False`.
- Adds: frozen request/session scope field `selected_sources_only` shown in trace.
- Changes: tool registry construction removes public web search/read tools only when this field is true.

- [ ] **Step 1: Write failing request and capability tests**

```python
def test_dataset_selection_alone_preserves_profile_web_tools(): ...
def test_selected_sources_only_removes_web_tools_from_registry(): ...
def test_follow_up_keeps_frozen_selected_sources_only_until_user_changes_it(): ...
```

- [ ] **Step 2: Run capability tests and confirm RED**

Run: `uv run pytest tests/test_chat_stream_w51.py tests/test_chat_evidence_application_service.py -q --basetemp=.test-tmp/rag-p0-scope`

- [ ] **Step 3: Implement request/session propagation and executable capability filtering**

Use explicit tool ids/capability metadata, never query keyword classification. A selected dataset with `false` still permits profile-authorized web tools.

- [ ] **Step 4: Add GUI checkbox beside source scope and effective trace label**

Label: `Только выбранные источники`. Default false; preserve state per dialogue; include it in chat payload and answer trace.

- [ ] **Step 5: Run API/UI scope tests and confirm GREEN**

Run: `uv run pytest tests/test_chat_stream_w51.py tests/test_chat_evidence_application_service.py tests/test_sovushka_chat.py -q --basetemp=.test-tmp/rag-p0-scope`

- [ ] **Step 6: Commit enforced capability scope**

```text
feat(chat): enforce explicit source-only capability
```

### Task 7: Bounded Admission and Safe Public Errors

**Files:**
- Create: `proxy/services/public_error_service.py`
- Modify: `proxy/services/runtime_admission.py`
- Modify: `proxy/services/chat_evidence_application_service.py`
- Modify: `proxy/routers/chat.py`
- Modify: `sovushka/pages/chat.py`
- Test: `tests/test_runtime_admission.py`
- Test: `tests/test_chat_stream_w51.py`
- Test: `tests/test_sovushka_chat.py`

**Interfaces:**
- Produces: `acquire_generation_slot(semaphore, *, timeout_sec: float)` async context manager with stable `MODEL_QUEUE_TIMEOUT` and cancellation-safe ownership.
- Produces: `public_error(code: str, *, operator_message: str) -> dict[str, str]`; diagnostic details are logged/traced separately.
- Removes: all reads of private semaphore `_value` in chat admission/generation.

- [ ] **Step 1: Write failing concurrency tests**

Cover immediate acquisition, a second request queued then admitted after release, timeout without false release, and cancellation without capacity inflation.

- [ ] **Step 2: Run admission tests and confirm RED**

Run: `uv run pytest tests/test_runtime_admission.py -q --basetemp=.test-tmp/rag-p0-admission`

- [ ] **Step 3: Implement bounded async acquisition and remove preflight slot rejection**

Use `asyncio.timeout()`/`wait_for(semaphore.acquire())`, track `acquired` locally, and release only when true. Keep memory/indexing admission independent from transient slot availability.

- [ ] **Step 4: Write failing public-error boundary tests**

Raise controlled `ValueError("secret diagnostic")` and assert SSE/UI/model-visible result contains a stable code and Russian message but not `ValueError`, `secret diagnostic`, stack text, or `TOOL_HANDLER_ERROR` internals.

- [ ] **Step 5: Implement one public envelope and diagnostic trace separation**

The log/trace keeps exception class and correlation id; HTTP/SSE/model evidence gets only the public envelope.

- [ ] **Step 6: Run admission/error tests and confirm GREEN**

Run: `uv run pytest tests/test_runtime_admission.py tests/test_chat_stream_w51.py tests/test_sovushka_chat.py -q --basetemp=.test-tmp/rag-p0-errors`

- [ ] **Step 7: Commit runtime reliability boundary**

```text
fix(chat): queue model admission and sanitize errors
```

### Task 8: Honest Readiness and Optional Rerank Guards

**Files:**
- Modify: `proxy/services/rag_advanced_policy_service.py`
- Modify: `proxy/services/retrieval_service.py`
- Modify: `proxy/services/rag_readiness_service.py`
- Modify: `proxy/services/rag_pipeline_status_service.py`
- Modify: `sovushka/pages/diag.py`
- Test: `tests/test_rag_advanced_policy_service.py`
- Test: `tests/test_retrieval_service.py`
- Test: `tests/test_rag_readiness_service.py`
- Test: `tests/test_rag_pipeline_status_service.py`

**Interfaces:**
- Changes: `DEFAULT_POLICY["raptor"]["mode"] == "off"` and effective migration of old absent values to off.
- Produces: ColBERT readiness predicate requiring policy mode, status `ready`, complete active-generation multivectors, and closed circuit.
- Produces: user status dimensions `backend_available`, `contract_complete`, `optional_stages`, `query_quality`, plus derived `overall` and `blocking_dimension`.

- [ ] **Step 1: Write failing policy/readiness regressions**

Assert RAPTOR defaults off; a `not_built` ColBERT status bypasses as `not_ready` without calling backend or opening circuit; incomplete vectors behave identically; exact-hit quality detail does not turn backend/contract red.

- [ ] **Step 2: Run focused readiness tests and confirm RED**

Run: `uv run pytest tests/test_rag_advanced_policy_service.py tests/test_retrieval_service.py tests/test_rag_readiness_service.py tests/test_rag_pipeline_status_service.py -q --basetemp=.test-tmp/rag-p0-ready`

- [ ] **Step 3: Implement RAPTOR effective-off migration and ColBERT readiness guard**

Read existing status/generation contract before rerank. `not_ready` bypass is not a failure and never calls `_COLBERT_BREAKER.failure()`.

- [ ] **Step 4: Implement dimensional user-facing readiness**

Keep backend health and generation contract as separate facts; expose optional-stage bypass reasons and per-query quality without conflating them.

- [ ] **Step 5: Expose complete ColBERT effective configuration in diagnostics GUI**

Show mode, model/source, candidate/output counts, query/passage token limits, latency, breaker, generation estimate/readiness, and rebuild requirement. Unsupported model remains visible read-only.

- [ ] **Step 6: Run readiness/retrieval tests and confirm GREEN**

Run the command from Step 2 and expect all tests to pass.

- [ ] **Step 7: Commit readiness and rerank safety**

```text
fix(rag): gate optional rerank on ready generation
```

### Task 9: Documentation, Version, and Complete Verification

**Files:**
- Modify: `docs/modules/` relevant RAG/chat/UI module docs identified via `docs/MODULE_INDEX.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `docs/TEST_INVENTORY.md`
- Modify: `config/version.json`
- Modify: `docs/RELEASE_LEDGER.md`
- Test: all focused suites above and project gates

**Interfaces:**
- Produces: documented behavior matching code, product version `0.30.43`, build `683`, and a release-ledger entry that explicitly says candidate is not installed or published.

- [ ] **Step 1: Verify protected paths and inspect final diff**

Run: `git diff --name-only f5e001fe...HEAD`

Expected: no `proxy/smeta_core/**`, data, secrets, installed runtime, build artifacts, or unrelated release files.

- [ ] **Step 2: Update canonical module docs and test inventory**

Document typed locators, three counts, evidence manifest, explicit source-only capability, profile-owned retrieval limits, admission queue, readiness dimensions, RAPTOR off, and ColBERT readiness guard. Mark no live-installed acceptance yet.

- [ ] **Step 3: Bump version and ledger in the same final change**

Set `product_version` to `0.30.43` and `build_number` to `683`; ledger names the exact candidate commit after commit creation is finalized by amendment if required.

- [ ] **Step 4: Run focused regression bundle**

Run all test files touched in Tasks 1–8 with workspace-local `--basetemp=.test-tmp/rag-p0-focused`.

- [ ] **Step 5: Run architecture and canonical gates**

Run: `make architecture-gate`

Run: `make verify`

Run: `make test`

If `make` is unavailable, execute the exact commands shown by the corresponding Makefile targets with workspace-local basetemp; do not substitute repository-wide legacy tests.

- [ ] **Step 6: Run a dev-only live acceptance without touching installed LES**

Use only an isolated dev proxy/runtime already configured for this worktree. Exercise three-turn dialogues on two available construction datasets, exact/broad/negative retrieval, source navigation, source-only versus web-permitted capabilities, and two-request admission. Record N/A rather than mutating services when an isolated runtime is unavailable.

- [ ] **Step 7: Run protected estimate non-regression only if estimate integration was reached**

Run the exact benchmark command from `AGENTS.md`; do not change the benchmark, fixture, or protected code to obtain green.

- [ ] **Step 8: Commit documentation/version and report the candidate, not a release**

```text
chore(release): record RAG P0 candidate 0.30.43
```

## Self-Review

- Spec coverage: Tasks 1–9 cover typed provenance/navigation/counts, evidence continuity, explicit scope, overfetch/diversity/profile limits, safe errors/admission, readiness, ColBERT/RAPTOR, GUI visibility, compatibility, tests, docs, version, and non-mutating acceptance.
- Non-goals remain excluded: no model decision logic, query rewriting, extra model turn, `proxy/smeta_core/**`, web-provider implementation, generation build, reindex, installed restart, release, or branch merge.
- Type consistency: retrieval policy keys and defaults are identical in Tasks 1–3; typed locator kinds are identical in Tasks 3–5; `selected_sources_only` is identical in request/session/UI; readiness dimensions are identical in code/API/GUI.
- Placeholder scan: no `TBD`, deferred implementation placeholder, or source-text-only regression is present.
