# All Update Paths and Database Resilience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every supported LES update entrypoint preserve a consistent active database/index pair and prove database resilience across failures, restarts, configured path/alias changes, and application updates.

**Architecture:** Low-level builders remain staging-only. Every active smeta publication goes through one generation coordinator that owns the update lease, exact-SHA readiness, coordinated file/alias activation, rollback, and restart recovery. General RAG and application updates keep their existing sibling-generation and persistent-state boundaries, but enter one explicit regression matrix so a new bypass cannot ship unnoticed.

**Tech Stack:** Python 3.12, FastAPI startup services, Qdrant aliases, SQLite, NiceGUI, pytest, uv, Make.

**Spec:** `AGENTS.md`, `docs/ADR-13-smeta-session-workflow.md`, `docs/ALGO-gesn.md`, `docs/GUARDRAILS.md`, `docs/modules/sovushka-uikit.md`.

**Implementation status (2026-09-02):** completed in the 0.30.47 candidate;
the checklist below records the executed red/green sequence. Installed/live
acceptance remains separate and was not run against user state.

## Global Constraints

- Do not modify `proxy/smeta_core/**` or model/chat/workbook decision flow.
- Do not mutate the installed LES, active user databases, Qdrant aliases, or run a real reindex during offline development.
- Dataset and smeta alias names are configuration-owned; no hard-coded production alias.
- Readiness endpoints are read-only; repair runs only in coordinator/startup worker boundaries.
- No new dependencies.
- Every production behavior begins with a failing regression test.

---

### Task 1: Executable inventory of every update entrypoint

**Files:**
- Create: `tests/test_smeta_update_entrypoints.py`
- Modify: `Makefile`
- Modify: `docs/TEST_INVENTORY.md`

**Interfaces:**
- Consumes: `Makefile` targets, `config/windows_runtime_manifest.json`, Python `-m` callsites.
- Produces: a fail-closed static contract that rejects direct active-base builders and missing installed-runtime workers.

- [ ] **Step 1: Write failing tests** asserting that `smeta-base`, `smeta-base-source`, FGIS GUI/API and full FGIS update all reach `tools.smeta_generation_coordinator`, while low-level `tools.build_smeta_structured_base` is not an active publication command.
- [ ] **Step 2: Run** `uv run pytest -q tests/test_smeta_update_entrypoints.py --basetemp=.test-tmp/update-entrypoints-red` and verify failures name the direct Make target and absent runtime modules.
- [ ] **Step 3: Add the new test file to `INTEGRATION_TESTS`** so `make test` cannot omit this contract.
- [ ] **Step 4: Re-run the focused test after Tasks 2–3 and require PASS.**

### Task 2: Canonical staging-only builder and installed runtime closure

**Files:**
- Modify: `tools/smeta_generation_coordinator.py`
- Modify: `tools/build_smeta_structured_base.py`
- Modify: `Makefile`
- Modify: `config/windows_runtime_manifest.json`
- Test: `tests/test_smeta_update_entrypoints.py`
- Test: `tests/test_tauri_desktop.py`

**Interfaces:**
- Consumes: `publish_generation(source, active_base, active_base_manifest, active_integrity, active_rag_manifest, generations_root, alias, minimum_norms)`.
- Produces: `python -m tools.smeta_generation_coordinator --source PATH` as the only local active-base build command; low-level CLI refuses the configured active path.

- [ ] **Step 1: Add failing CLI tests** for arbitrary configured base path and alias, and for refusal by `build_smeta_structured_base.main()` when its output resolves to the active base.
- [ ] **Step 2: Run the tests RED.**
- [ ] **Step 3: Implement coordinator CLI** by resolving `active_base()` and passing its effective base/manifest/integrity/alias plus mutable generation root to `publish_generation`.
- [ ] **Step 4: Route Make `smeta-base` and `smeta-base-source` through the coordinator** while retaining service-card generation after successful activation.
- [ ] **Step 5: Add all transitive dynamic workers** (`smeta_generation_coordinator`, `rebuild_active_smeta_rag`, `build_smeta_norm_rag`, `smeta_rag_readiness`, `activate_smeta_rag_generation`, `activate_qdrant_generation`) to the Windows runtime manifest.
- [ ] **Step 6: Run focused entrypoint and Tauri runtime-manifest tests GREEN.**

### Task 3: Crash, concurrency, and rename recovery

**Files:**
- Create: `tools/smeta_generation_lease.py`
- Modify: `tools/smeta_generation_coordinator.py`
- Modify: `tools/rebuild_active_smeta_rag.py`
- Modify: `proxy/services/smeta_generation_reconciliation_service.py`
- Test: `tests/test_smeta_generation_coordinator.py`
- Test: `tests/test_smeta_generation_reconciliation_service.py`
- Test: `tests/test_rebuild_active_smeta_rag.py`

**Interfaces:**
- Produces: `generation_lease(root: Path, operation: str)` context manager using an atomic lock directory with PID ownership and stale-owner recovery.
- Produces: reconciliation that restores saved `les_smeta_base_manifest.json` and `les_smeta_base_integrity.json` for the exact active SQLite SHA before activating its exact RAG generation.

- [ ] **Step 1: Write failing tests** for two concurrent publishers, stale process lock, crash after SQLite replacement but before metadata/alias, Qdrant unavailable, physical alias blocker, arbitrary alias rename, and custom SQLite filename/path.
- [ ] **Step 2: Run each new case RED and record the expected invariant violation.**
- [ ] **Step 3: Implement the atomic lease** and use it in full publication and background rebuild.
- [ ] **Step 4: Extend startup reconciliation** to recover exact-SHA saved metadata files, then call the existing live Qdrant verification/alias activation; never trust a manifest without the actual alias.
- [ ] **Step 5: Ensure every failure leaves either the previous pair active or an explicit blocked/building warning with `restart_required=false`.**
- [ ] **Step 6: Run the three focused test files GREEN.**

### Task 4: Cross-system update and persistent-state regression matrix

**Files:**
- Create: `tests/test_update_resilience_matrix.py`
- Modify: `docs/TEST_INVENTORY.md`

**Interfaces:**
- Consumes: general RAG sibling supervisor, smeta coordinator, baseline repair, Windows soft/hard updater boundaries, configured runtime paths.
- Produces: one parameterized matrix documenting update type, mutable roots, precondition, failure injection, rollback/recovery result, and warning surface.

- [ ] **Step 1: Add matrix cases** for ordinary dataset add/change/reindex, general RAG generation activation failure, smeta FGIS/API/Make/baseline paths, Windows soft patch, Windows hard update, interrupted rollback, and clean install over existing state.
- [ ] **Step 2: Assert application updates never include persistent `data/`, `storage/`, MetaDB, Qdrant data, or user documents in application mutation roots.**
- [ ] **Step 3: Assert baseline repair changes smeta files only through a verified archive and startup reconciliation subsequently reports matching or rebuilding state.**
- [ ] **Step 4: Run focused matrix tests, `make test-rag-core`, `make test-updater`, and Windows updater/installer contract tests.**

### Task 5: Documentation, version, and final verification

**Files:**
- Modify: `docs/CODE_MAP.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `docs/ALGO-gesn.md`
- Modify: `docs/RELEASE_LEDGER.md`
- Modify: `config/version.json` and synchronized version surfaces

**Interfaces:**
- Produces: one current operator contract describing every update route and recovery state.

- [ ] **Step 1: Document the update graph and failure matrix** without claiming live acceptance.
- [ ] **Step 2: Bump candidate SemVer/build and run** `uv run python tools/sync_version_contract.py`.
- [ ] **Step 3: Regenerate** `docs/CODE_RUNTIME_MAP.md` and `docs/generated/code_runtime_map.json`.
- [ ] **Step 4: Run** `git diff --check`, `make architecture-gate`, `make verify`, `make test`, `make test-rag-core`, and `make test-updater`.
- [ ] **Step 5: Commit only this update-resilience package; preserve the six pre-existing chat changes separately.**
