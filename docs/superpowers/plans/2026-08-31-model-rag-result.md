# Model → RAG → Result Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the bound LES model author and execute its own RAG queries, receive the untouched evidence, make the professional mapping, and hand that mapping to the existing deterministic XLSX renderer.

**Architecture:** Reuse the existing bound-model transport, canonical native-RRF `search_sources`, and canonical `build_lsr_workbook` contract. Remove the one-tool truncation and JSON-only selector protocol from the active model-owned turn; bind role datasets explicitly and skip code-authored initial retrieval for the estimator profile. No file under `proxy/smeta_core/**` changes.

**Tech Stack:** Python 3.12+, FastAPI application services, Ollama/OpenAI-compatible native tool calls, Qdrant native RRF, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-08-30-model-owned-evidence-first-rag-design.md`

## Global Constraints

- The model authors every semantic search query and every professional `decisions` item.
- Code may normalize tool-call JSON, freeze scope, execute retrieval, calculate, trace, and render XLSX; it may not choose or repair a norm.
- The number of calls returned by one model response is not restricted to five or one; the physical response size and visible wall-clock deadline remain the safety boundary.
- `proxy/smeta_core/**`, user data, Qdrant storage, installed runtime, updater, and installer remain unchanged.
- No new dependency and no dataset-specific query prose, boosts, expected answers, family inference, or auto-unbound behavior.

---

### Task 1: Preserve every active native tool call

**Files:**
- Modify: `proxy/services/canonical_route_service.py`
- Test: `tests/test_model_connection_chat_integration.py`

**Interfaces:**
- Consumes: `InferenceResponse.tool_calls` from `OpenAICompatibleTransport`.
- Produces: `BoundModelChatRunner.complete(..., mode=ACTIVE)` with the complete ordered tuple of calls and `pending_tool_calls=0`.

- [ ] **Step 1: Change the existing active-runner test to require both literal calls**

```python
assert [call["function"]["name"] for call in result.response.tool_calls] == [
    "read_source", "read_table"
]
assert result.pending_tool_calls == 0
```

- [ ] **Step 2: Run the test and verify RED**

Run: `uv run pytest -q --basetemp=.test-tmp/model-calls-red tests/test_model_connection_chat_integration.py::test_active_preserves_every_model_tool_call`

Expected: FAIL because the runner currently returns only `read_source` and reports one pending call.

- [ ] **Step 3: Preserve all calls only for ACTIVE transport execution**

Keep legacy/shadow compatibility bounded if required by their existing tests. Active execution returns the transport response unchanged.

- [ ] **Step 4: Run the focused model-connection tests**

Run: `uv run pytest -q --basetemp=.test-tmp/model-calls-green tests/test_model_connection_chat_integration.py tests/test_canonical_route_service.py`

Expected: PASS.

### Task 2: Bind the estimator role dataset as explicit frozen scope

**Files:**
- Modify: `proxy/routers/chat.py`
- Modify: `proxy/services/chat_evidence_application_service.py`
- Test: `tests/test_chat_evidence_application_service.py`
- Test: `tests/test_sovushka_chat.py`

**Interfaces:**
- Consumes: `profile_snapshot["rag_policy"]["system_datasets"] == ["smeta"]` and `module_dataset_ids("smeta")`.
- Produces: frozen dataset IDs with `scope_source="profile_system_datasets"`; estimator initial retrieval status `model_driven` without searching the literal command `Собери ЛСР`.

- [ ] **Step 1: Add a router/application test for explicit role scope**

The test starts without user dataset IDs, resolves the estimator profile, and asserts the smeta system dataset is supplied to the evidence application.

- [ ] **Step 2: Add a test that estimator startup makes zero retrieval calls**

The model receives the attachment and `search_sources` capability, but the injected retriever must not be called before the model authors a query.

- [ ] **Step 3: Run both tests and verify RED**

Run: `uv run pytest -q --basetemp=.test-tmp/role-scope-red tests/test_chat_evidence_application_service.py tests/test_sovushka_chat.py -k "estimator and (system_dataset or model_driven)"`

Expected: FAIL because committed 0.30 does not apply role datasets and pre-retrieves from the user command.

- [ ] **Step 4: Add the minimal scope binding and model-driven retrieval branch**

Do not infer scope from words. Only the selected profile's declared system dataset activates this branch.

- [ ] **Step 5: Run the focused tests until GREEN**

Run: `uv run pytest -q --basetemp=.test-tmp/role-scope-green tests/test_chat_evidence_application_service.py tests/test_sovushka_chat.py tests/test_system_dataset_service.py`

Expected: PASS.

### Task 3: Give the same model native search and workbook tools

**Files:**
- Modify: `proxy/services/chat_evidence_application_service.py`
- Modify: `proxy/services/chat_profile_service.py`
- Test: `tests/test_chat_evidence_application_service.py`
- Test: `tests/test_chat_profile_service.py`

**Interfaces:**
- Consumes: canonical tool contracts from the existing shortlist and active `InferenceResponse.tool_calls`.
- Produces: OpenAI/Ollama function schemas, exact model calls, executed RRF results, and the next call containing the accumulated evidence/tool exchange.

- [ ] **Step 1: Add a failing end-to-end application test**

The fake bound model first returns two `search_sources` calls, then one `build_lsr_workbook` call containing literal model decisions, then final text. Assert both model queries reach the injected canonical retriever unchanged, the workbook receives the exact decisions unchanged, and no retrieval call uses the literal user command.

- [ ] **Step 2: Run the new test and verify RED**

Run: `uv run pytest -q --basetemp=.test-tmp/native-loop-red tests/test_chat_evidence_application_service.py::test_estimator_model_queries_rag_then_builds_exact_decisions`

Expected: FAIL because selector requests currently contain no native `tools`, active calls are truncated, and the estimator profile/tool budget can hide capabilities.

- [ ] **Step 3: Project the existing contracts into native function schemas**

Use each contract's `name`, `summary`, and `input_schema`. Do not invent an alternative tool registry or parallel estimate tool names.

- [ ] **Step 4: Execute every valid call from the model response**

Freeze dataset and attachment IDs at the server boundary. Preserve model-authored query and `decisions`; add only missing server-owned scope fields. Continue until the same model returns text/no calls, a workbook completes, cancellation occurs, or the visible deadline expires.

- [ ] **Step 5: Keep attachment text in the evidence-priority packet**

The attachment is source evidence, not low-priority memory. Record inclusion/omission in the existing context trace.

- [ ] **Step 6: Run focused tests until GREEN**

Run: `uv run pytest -q --basetemp=.test-tmp/native-loop-green tests/test_chat_evidence_application_service.py tests/test_chat_profile_service.py tests/test_model_research_tool_service.py tests/test_workbook_tool_service.py`

Expected: PASS.

### Task 4: Document, version, verify, then run the real five-row acceptance

**Files:**
- Modify: `docs/ALGO-tool-harness.md`
- Modify: `docs/CODE_MAP.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `docs/TEST_INVENTORY.md`
- Modify: `docs/RELEASE_LEDGER.md`
- Modify: `config/version.json`
- Modify generated version surfaces using `tools/sync_version_contract.py`

**Interfaces:**
- Produces: truthful docs/version and a live trace showing attachment rows, exact Qwen queries, returned RRF cards, exact model decisions, and downloadable XLSX.

- [ ] **Step 1: Update module/code/test documentation and bump the patch build**

State explicitly that role scope is profile-bound, the model authors queries, and code performs no professional selection.

- [ ] **Step 2: Run focused and canonical gates**

Run: `make architecture-gate`, `make verify`, and `make test`.

Expected: all green; `git diff HEAD -- proxy/smeta_core` is empty.

- [ ] **Step 3: Run one real installed-style five-row Qwen 3.5 9B acceptance in isolated state**

Acceptance is not a pass score. Preserve the real answer, exact trace, and XLSX. It fails if the code authors any search query/norm, if any source row disappears, if the model does not receive the RAG cards, or if no artifact is produced.

- [ ] **Step 4: Stop before publication**

Report the evidence. Do not deploy, patch, tag, publish, or alter the installed Legion runtime without a separate owner instruction.
