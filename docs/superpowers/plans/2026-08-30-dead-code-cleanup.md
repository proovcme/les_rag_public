# Dead Code Cleanup 0.30.5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the first proven unreachable historical-code group without changing LES product behavior.

**Architecture:** Treat deletion as four reversible groups. Static reachability and source-contract tests prove the boundary before deletion; the generated runtime map, Windows staging smoke and canonical gates prove the final tree.

**Tech Stack:** Python 3.12+/AST, pytest, uv, FastAPI/NiceGUI, Tauri/Rust, git.

**Spec:** `docs/superpowers/specs/2026-08-30-code-truth-map-design.md`

## Global Constraints

- Do not modify `sovushka/pages/mail.py`, `proxy/legacy_app.py` or `proxy/smeta_core/**`.
- Do not change model, RAG, tool execution, navigation or user data.
- Do not deploy, publish or update the installed runtime.
- Use `apply_patch` for source/test/doc edits and `git rm` only for the exact reviewed paths.
- Run pytest with workspace-local `--basetemp=.test-tmp/<gate>`.

---

### Task 1: Lock the observable behavior baseline

**Files:**
- Modify: `tests/test_code_runtime_map.py`
- Modify: `tests/test_sovushka_uikit.py`
- Modify: `tests/test_static_assets.py`

**Interfaces:**
- Consumes: `build_inventory(root: Path) -> dict`.
- Produces: product route/import baseline and shell assertions that do not require dormant source files to remain.

- [x] **Step 1: Stop tests from preserving obsolete UI files**

In `test_sovushka_uikit.py`, remove `prorab.py`, `overview.py` and `rim.py`
source-style assertions while retaining shell/navigation behavior. In
`test_static_assets.py`, keep only the production-mounting contract; do not require
a dormant page definition to remain.

- [x] **Step 2: Record the real baseline**

Import `proxy.app`, record its route count and run the existing shell/RIM/runtime tests.
These are the behaviors deletion must preserve. Do not add a source-absence test: that
would be a change detector, not a product regression test.

- [x] **Step 3: Run the baseline gate**

Run:

```powershell
uv run python -m pytest --basetemp=.test-tmp/dead-code-baseline -q tests/test_sovushka_uikit.py tests/test_static_assets.py tests/test_sovushka_data_workspace.py tests/test_rim_api.py tests/test_runtime_router.py
```

Expected: PASS before deletion; the same behavior gate must pass afterwards.

### Task 2: Remove backend and package scaffolding

**Files:**
- Delete: `backend/auth_login_route.py`
- Delete: `backend/login.html`
- Delete: `backend/diagnostics.py`
- Delete: `backend/inference/sparse_embed.py`
- Delete: `proxy/clients/__init__.py`
- Delete: `proxy/repositories/__init__.py`
- Delete: `proxy/workers/__init__.py`
- Modify: `docs/CODE_MAP.md`
- Modify: `pyproject.toml`
- Modify: `tests/test_status_page.py`

**Interfaces:**
- Consumes: current login registration in `sovushka.auth`, diagnostics router and `bm25_sparse` production contract.
- Produces: no replacement API; removes only unreachable implementations.

- [x] **Step 1: Recheck consumers immediately before deletion**

Run exact `rg` searches for the six module names outside generated/archive files. Stop if a product consumer appears.

- [x] **Step 2: Delete only the seven listed files**

Use `git rm` with exact literal paths. Do not recursively delete any parent except the now-empty `proxy/clients`, `proxy/repositories` and `proxy/workers` directories represented by their tracked initializer files.

- [x] **Step 3: Correct narrow CODE_MAP claims**

Remove `auth_login_route.py`, dead diagnostics and BGE-M3 learned-sparse as active/current code references. Keep the live replacements explicit.

- [x] **Step 4: Run focused import checks**

```powershell
uv run python -m compileall -q backend proxy sovushka
uv run python -m pytest --basetemp=.test-tmp/dead-code-backend -q tests/test_runtime_router.py tests/test_rag_config.py tests/test_static_assets.py
```

Expected: PASS.

### Task 3: Remove unused visualizer helper and dormant pages

**Files:**
- Delete: `qdrant_visualizer/export_data.py`
- Delete: `sovushka/components/logterm.py`
- Delete: `sovushka/pages/overview.py`
- Delete: `sovushka/pages/prorab.py`
- Delete: `sovushka/pages/obyomy.py`
- Delete: `sovushka/pages/zadachi.py`
- Delete: `sovushka/pages/mermaid_page.py`
- Delete: `sovushka/pages/rim.py`
- Delete: `tests/test_mermaid_graph.py`
- Modify: `docs/CODE_MAP.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `docs/TEST_INVENTORY.md`

**Interfaces:**
- Consumes: production shell `sovushka_ng.py`, active Qdrant static visualizer, RIM API/services.
- Produces: unchanged production shell with fewer shipped source files.

- [x] **Step 1: Recheck source and string consumers**

Search every builder/module name across Python, PowerShell, JSON/TOML and canonical docs. Confirm only tests/docs or the file itself refer to each deleted page.

- [x] **Step 2: Delete the eight exact files**

Use `git rm` with the paths above. Do not remove `qdrant_visualizer/index.html`, `visualizer.js`, `pca.js`, styles or any RIM backend path.

- [x] **Step 3: Correct factual documentation only**

State that RIM works through universal-agent/API services and has no separate UI. Remove obsolete Overview/Prorab/field/tasks/Mermaid page claims. Preserve Mail UI as temporarily dormant and subject to redesign.

- [x] **Step 4: Run UI/RIM focused gates**

```powershell
uv run python -m pytest --basetemp=.test-tmp/dead-code-ui -q tests/test_sovushka_uikit.py tests/test_static_assets.py tests/test_sovushka_data_workspace.py tests/test_rim_api.py tests/test_rim_agent_turn.py
```

Expected: PASS with live RIM backend coverage intact.

### Task 4: Regenerate truth surfaces and version 0.30.5

**Files:**
- Modify: `tools/code_runtime_map.py`
- Modify: `docs/CODE_RUNTIME_MAP.md`
- Modify: `docs/generated/code_runtime_map.json`
- Modify: `config/version.json`
- Modify: `docs/RELEASE_LEDGER.md`
- Modify: version-synchronized Tauri/Python surfaces.

**Interfaces:**
- Consumes: final tracked Python tree and `config/windows_runtime_manifest.json`.
- Produces: synchronized `0.30.5 / build 645 / desktop 5.1.645` candidate.

- [x] **Step 1: Regenerate runtime map**

Run `uv run python tools/code_runtime_map.py`. Confirm removed paths disappear, protected paths remain and product entrypoint counts do not drop unexpectedly.

- [x] **Step 2: Move version contract**

Set `product_version=0.30.5`, `build_number=645`, `desktop_version=5.1.645`; run `uv run python tools/sync_version_contract.py` and `uv lock --offline`.

- [x] **Step 3: Record exact cleanup result**

Update RELEASE_LEDGER, MODULE_INDEX and TEST_INVENTORY with deleted paths, before/after counts, no behavior change, no deploy and explicit Mail/legacy/smeta exclusions.

- [x] **Step 4: Run focused GREEN**

```powershell
uv run python -m pytest --basetemp=.test-tmp/dead-code-final -q tests/test_code_runtime_map.py tests/test_documentation_contract.py tests/test_software_versions.py
uv run python tools/code_runtime_map.py --check
```

Expected: PASS.

### Task 5: Full verification and one cleanup commit

**Files:**
- Verify all changed/deleted files.

**Interfaces:**
- Consumes: completed Tasks 1–4.
- Produces: one reviewable 0.30.5 cleanup commit; no release artifact.

- [x] **Step 1: Run canonical gates**

```powershell
make verify
make test
make test-tauri
```

Expected: all PASS.

- [x] **Step 2: Stage Windows runtime and import product entrypoints**

Use the existing `build_tauri_app.stage_runtime(win32)` test/smoke path. Confirm updater helpers remain, removed files are absent and `proxy.app` imports from the staged tree.

- [x] **Step 3: Review diff and repository state**

Run `git diff --check`, `git status --short`, and confirm protected paths have no diff.

- [x] **Step 4: Commit**

```powershell
git add -A
git commit -m "refactor: remove proven unreachable runtime code"
```
