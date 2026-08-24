# FreeToken Smeta Layered Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove Big Qwen context management, tool transport and per-row checkpoint/resume with short falsifiable probes before any costly smeta run.

**Architecture:** Keep the complete checkpoint as the immutable audit record and project only the current authoritative working set into each FreeToken inference frame. Verify transport, context projection, checkpoint semantics and model behavior as separate layers; a failing layer stops the sequence. The protected professional smeta core and model-owned norm decisions are not changed.

**Tech Stack:** Python 3.12, pytest, FastAPI/httpx, FreeToken OpenAI-compatible API, Big Qwen, existing LES attachment checkpoint.

**Spec:** `docs/superpowers/specs/2026-08-22-freetoken-local-provider-design.md` (sections `Prompt budgeting` and `Layered smeta acceptance`), with runtime behavior defined by `docs/modules/smeta-core.md#freetoken-one-row-transport-v02772`.

## Global Constraints

- Do not modify `proxy/smeta_core/**`, norm selection, mappings, quantities or calculations.
- Do not add a mini-model, reranker, card phase, catalog route or code-owned professional correction.
- Do not reindex, delete or mutate Qdrant datasets for these tests.
- Do not start a 70-row or other full-document run from this plan.
- A failed gate stops execution; diagnose only that layer and rerun only its shortest reproducer.
- A live request has a 120-second operator timeout. Preserve its checkpoint on timeout or failure.
- Preserve unrelated dirty-worktree changes. Do not commit, push, publish or build an installer.
- Use workspace-local pytest temp directories on Windows.

---

### Task 1: Freeze the context-projection contract

**Files:**
- Modify: `proxy/services/smeta_chat_adapter_service.py`
- Test: `tests/test_smeta_chat_application_service.py`
- Document: `docs/modules/smeta-core.md`

**Interfaces:**
- Consumes: `smeta_norm_agent_working_memory_v1` emitted by the existing document workflow.
- Produces: `_freetoken_working_set_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]`.

- [x] **Step 1: Write a failing test with old audit turns, a latest tool exchange, current working memory and terminal instruction.**

  The assertion requires old audit call/results to be absent and the immutable system/source prefix plus current state to remain.

- [x] **Step 2: Run the single test and verify it fails because historical audit is still transported.**

  Run:

  ```powershell
  uv run pytest tests/test_smeta_chat_application_service.py::test_freetoken_transport_keeps_authoritative_working_set_not_audit_history -q --basetemp=.test-tmp/freetoken-context-red
  ```

- [x] **Step 3: Implement the minimal transport projection without changing the durable message/checkpoint history.**

- [x] **Step 4: Re-run the single test and require `1 passed`.**

  Expected duration: under 5 seconds.

### Task 2: Prove FreeToken capacity without RAG or smeta

**Files:**
- Create: `tools/freetoken_context_probe.py`
- Document: `docs/modules/smeta-core.md`
- Document: `docs/TEST_INVENTORY.md`

**Interfaces:**
- Consumes: FreeToken `/v1/messages/count_tokens` and `/v1/chat/completions`.
- Produces: one forced `report_probe` tool call plus counted prompt, completion usage and elapsed seconds.

- [x] **Step 1: Run the small forced-tool probe.**

  ```powershell
  uv run python tools/freetoken_context_probe.py --input-tokens 512 --max-tokens 1024
  ```

  Require: exit code 0, `ok true`, `tool_name report_probe`, elapsed under 30 seconds.

- [x] **Step 2: Run the physical-boundary probe.**

  ```powershell
  uv run python tools/freetoken_context_probe.py --input-tokens 6200 --max-tokens 1024
  ```

  Require: exit code 0 and FreeToken completion/tool-call with total input plus reserve below the reported 8253-page capacity. Expected duration: under 90 seconds.

- [ ] **Step 3: If either probe fails, stop.**

  Record the exact counted input, reserve, HTTP error and `/v1/stats`; do not invoke chat, RAG or an attachment workflow.

### Task 3: Prove per-row durability entirely offline

**Files:**
- Test: `tests/test_smeta_core.py`
- Test: `tests/test_smeta_chat_application_service.py`

**Interfaces:**
- Consumes: existing document workflow checkpoint callback and opaque attachment checkpoint path.
- Produces: proof that an accepted row is written before the next row and resume skips already completed work.

- [x] **Step 1: Run only the three checkpoint-contract cases.**

  ```powershell
  uv run pytest tests/test_smeta_core.py::test_submit_checkpoints_each_accepted_row_before_the_next tests/test_smeta_core.py::test_sequential_row_mapping_resumes_checkpoint_without_repeating_completed_rows tests/test_smeta_chat_application_service.py::test_local_freetoken_document_application_uses_single_row_batches -q --basetemp=.test-tmp/freetoken-row-checkpoint
  ```

  Require: `3 passed`. Expected duration: under 15 seconds and zero model/network calls.

  Evidence 2026-08-24: `3 passed in 1.82s`.

- [ ] **Step 2: If a case fails, stop and repair only the checkpoint/application boundary under test.**

  Do not substitute a live XLSX run for this proof.

### Task 4: Prove the complete focused FreeToken contract offline

**Files:**
- Test: `tests/test_freetoken_provider.py`
- Test: `tests/test_smeta_chat_application_service.py`

**Interfaces:**
- Consumes: the shared FreeToken provider profile and smeta chat adapter.
- Produces: one bounded regression result for locality, no-thinking options, output reserve, forced terminal mapping and working-set projection.

- [x] **Step 1: Run the focused files.**

  ```powershell
  uv run pytest tests/test_freetoken_provider.py tests/test_smeta_chat_application_service.py -q --basetemp=.test-tmp/freetoken-layered-focused
  ```

  Require: all collected cases pass. Expected duration: under 20 seconds.

  Evidence 2026-08-24: `41 passed in 3.62s`; four existing FastAPI
  `on_event` deprecation warnings, no contract failure.

- [x] **Step 2: Compare failures with Tasks 1-3 and stop on the first new contract mismatch.**

  Do not run `make test` to diagnose a focused failure.

### Task 5: Resume exactly one real row

**Current status:** blocked before any live request. The browser automation
session no longer has the original opaque attachment identity, and chat history
does not expose it. A re-upload would be a fresh run, not proof of resume, so it
is deliberately not substituted here.

**Files:**
- Runtime state only: existing chat attachment and its durable checkpoint.
- No source changes unless this gate exposes a reproducible defect already isolated by Tasks 1-4.

**Interfaces:**
- Consumes: the original opaque attachment identity, its exact source SHA and its existing checkpoint.
- Produces: one newly completed row, an updated checkpoint, tool trace and elapsed time.

- [ ] **Step 1: Verify read-only that the original attachment identity is still available to the active chat session.**

  Require exact identity/source match. If history exposes only a filename or a newly uploaded attachment has a different opaque ID, mark this gate `BLOCKED: original attachment identity unavailable` and stop.

- [ ] **Step 2: Resume with a one-row slice and a 120-second timeout.**

  Require the UI/runtime to report one current row only, preserve the existing completed count, and write the next checkpoint before any following row.

- [ ] **Step 3: Inspect the one-row evidence.**

  Require the model itself to call the typed search/read tools, return a terminal mapping, and leave its professional decision unchanged by code. Record elapsed time, prompt/completion tokens, tool names, selected norm and checkpoint completed count.

- [ ] **Step 4: Stop after that row even on success.**

  A successful one-row result permits Task 6; it does not permit a full fixture run.

### Task 6: Run one bounded five-row resume slice

**Files:**
- Runtime state only: the same verified attachment/checkpoint from Task 5.

**Interfaces:**
- Consumes: Task 5 checkpoint and the same immutable source identity.
- Produces: five sequential row outcomes and five durable checkpoint transitions.

- [ ] **Step 1: Obtain the owner's explicit go-ahead after showing Task 5 evidence.**

- [ ] **Step 2: Resume at one row per model task with stop after five additional rows.**

  Require each row to start with a fresh bounded working set, preserve prior audit in the checkpoint, and persist before the next row. Stop immediately on repeated search loops, context rejection, identity mismatch or missing checkpoint advancement.

- [ ] **Step 3: Report per-row latency and correctness separately.**

  Report median/p95 latency, tool sequence, mapping status and any blockers. Do not average away failed rows.

- [ ] **Step 4: End the plan.**

  The 70-row run remains a separate release-acceptance decision and is not an automatic next step.

## Self-review

- Spec coverage: prompt budgeting, tool transport, checkpoint integrity, one-row batching and explicit full-run prohibition each map to a task.
- Placeholder scan: no implementation placeholder or open-ended error-handling step remains.
- Interface consistency: every live gate uses the same original attachment identity and checkpoint; a re-upload cannot masquerade as resume.
