# Ordinary Smeta RAG Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the separate smeta product workflow with an ordinary RAG dataset and keep FreeToken's physical KV cache synchronized with LES settings.

**Architecture:** Retire only the visible RIM/smeta routes while preserving legacy data and protected core code. Publish typed SQLite norm cards through the unified named-vector RAG contract under a stable system dataset identity. Add a loopback-only FreeToken cache reconciler used by settings and generation preflight.

**Tech Stack:** Python 3.12, FastAPI, NiceGUI, httpx, Qdrant, SQLite, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-08-24-ordinary-smeta-rag-design.md`

## Global Constraints

- Do not modify `proxy/smeta_core/**` or delete saved RIM data.
- Do not add dependencies, copy legacy dense vectors or create an unnamed collection.
- Use standard `dense` + `bm25_sparse`, native RRF and explicit dataset scope.
- Preserve unrelated dirty-worktree changes; do not commit, push or publish.
- Use workspace-local pytest temporary directories on Windows.

---

### Task 1: Retire the separate smeta product surface

**Files:**
- Modify: `sovushka_ng.py`
- Modify: `sovushka/components/header.py`
- Modify: `sovushka/pages/chat.py`
- Test: `tests/test_sovushka_uikit.py`
- Test: `tests/test_sovushka_chat.py`

**Interfaces:**
- Consumes: existing ordinary chat and dataset selector.
- Produces: a shell with no `rim` tab and a chat with no `mode=smeta` control.

- [ ] Write tests asserting the rendered navigation/mode registry cannot select RIM or smeta.
- [ ] Run the focused tests and verify they fail on the existing visible controls.
- [ ] Remove RIM imports/panel registration, header entries, special chat chip/guidance and retry prompt.
- [ ] Run the focused tests and require green.

### Task 2: Reconcile FreeToken physical KV

**Files:**
- Create: `proxy/services/freetoken_cache_profile_service.py`
- Modify: `proxy/routers/settings.py`
- Modify: `proxy/routers/chat.py`
- Modify: `sovushka/components/header.py`
- Test: `tests/test_freetoken_provider.py`
- Test: `tests/test_proxy_routers.py`

**Interfaces:**
- Produces: `reconcile_freetoken_cache(base_url, desired_kv, client=None) -> dict[str, object]` and a public configured/effective status payload.

- [ ] Write tests for aligned, rebuildable and unreachable cache states.
- [ ] Verify failure because no reconciler/status exists.
- [ ] Implement loopback validation, status parsing, feasible MoE calculation and bounded rebuild.
- [ ] Invoke on settings save/read and once before FreeToken generation; display status using existing UI components.
- [ ] Run focused tests and require green.

### Task 3: Publish the norm base as an ordinary dataset

**Files:**
- Modify: `proxy/services/system_dataset_service.py`
- Create: `tools/publish_smeta_norm_dataset.py`
- Test: `tests/test_system_dataset_service.py`
- Test: `tests/test_publish_smeta_norm_dataset.py`

**Interfaces:**
- Produces: stable `SMETA_NORMS_Index` metadata and standard unified-collection point payloads derived from trusted typed norm rows.

- [ ] Write registry and point-contract tests with a small temporary SQLite base.
- [ ] Verify failure because the dataset and publisher do not exist.
- [ ] Implement deterministic cards, provenance, dense/sparse vectors, resumable upsert and lexical publication without touching the typed base.
- [ ] Run focused tests and require green.

### Task 4: Documentation, version and gates

**Files:**
- Modify: `docs/modules/sovushka-uikit.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `docs/CODE_MAP.md`
- Modify: `docs/TEST_INVENTORY.md`
- Modify: `docs/RELEASE_LEDGER.md`
- Modify: `config/version.json`

- [ ] Document the single ordinary-RAG workflow and configured/effective FreeToken state.
- [ ] Bump product to `0.27.77`, build `584`, desktop `5.1.584`.
- [ ] Run focused tests, `make verify`, `make test`, and the protected smeta benchmark because the release changes visible smeta behavior.
- [ ] Deploy only after all gates are green; run live FreeToken restart and ordinary norm-RAG smoke.

## Self-review

- Every acceptance item maps to one task.
- The plan contains no deletion of data or protected-core mutation.
- The three boundaries remain independently testable and use explicit interfaces.
