# Canonical Update, Rollback and Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package the verified 0.29.0 architecture as a lightweight GitHub update when classification remains patch-safe, with an exact-manifest rollback that preserves user artifacts, checkpoints, traces, documents, indexes and settings.

**Architecture:** One GUI-visible route factor controls whether ordinary chat uses the canonical registry/governor pipeline or the preserved v0.28.2-compatible path. The existing immutable update channel classifies the exact committed change set, creates a commit-bound manifest and proves apply/skip/rollback against isolated state before publication.

**Tech Stack:** Python 3.12, existing update service and GitHub patch tools, FastAPI, NiceGUI, pytest, PowerShell acceptance, uv, Make.

**Spec:** `docs/superpowers/specs/2026-08-26-canonical-tool-context-memory-update-design.md`

## Global Constraints

- Execute after the foundation, ContextGovernor/memory, workbook and trust-fix plans are complete and green.
- Public release remains `0.29.0`; increment only `build_number`/`desktop_version` for implementation checkpoints.
- Lightweight update is allowed only when the classifier proves no dependency, installer, native runtime or destructive migration change.
- PR6 is excluded because bundled Qdrant requires a full installer and exact Windows storage acceptance.
- Rollback changes executable routing only; it must not delete or rewrite artifacts, checkpoints, traces, documents, indexes or settings.
- The active/effective route factor is GUI-visible with value, source and restart requirement.
- Publishing remains prohibited without the owner's explicit release instruction.
- Do not add dependencies or touch `proxy/smeta_core/**`.
- Every task updates its module documentation and `docs/MODULE_INDEX.md`, increments `build_number` once, runs `make version-sync`, and records the change in `docs/RELEASE_LEDGER.md` in the same commit.

---

### Task 1: Add the preserved-data canonical-route switch

**Files:**
- Create: `proxy/services/canonical_route_service.py`
- Create: `tests/test_canonical_route_service.py`
- Modify: `proxy/services/chat_evidence_application_service.py`
- Modify: `proxy/services/version_service.py`
- Modify: `proxy/services/runtime_config_registry_service.py`
- Modify: `proxy/routers/settings.py`
- Modify: `sovushka/pages/diag.py`
- Modify: `tests/test_chat_evidence_application_service.py`
- Modify: `tests/test_runtime_config_registry_service.py`
- Modify: `tests/test_diag_platform.py`
- Modify: `docs/CURRENT_ARCHITECTURE.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `config/version.json`
- Modify: `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: configured `LES_CANONICAL_AGENT_ROUTE_ENABLED` and runtime restart state.
- Produces: `CanonicalRouteDecision` and a single route branch before model invocation.

- [ ] **Step 1: Before UI edits, read required Sovushka instructions**

Read `skills/sovushka-ui/SKILL.md` and `docs/modules/sovushka-uikit.md`; reuse the runtime-factor component registry.

- [ ] **Step 2: Write failing route/rollback tests**

```python
def test_route_switch_is_explicit_and_redacted(monkeypatch):
    monkeypatch.setenv("LES_CANONICAL_AGENT_ROUTE_ENABLED", "0")
    decision = resolve_canonical_route()
    assert decision.enabled is False
    assert decision.source == "environment"


@pytest.mark.asyncio
async def test_compatibility_route_does_not_delete_canonical_state(state, chat_runtime):
    before = state.snapshot_tables("les_artifact_revisions", "les_workflow_checkpoints")
    await run_chat_with_route(chat_runtime, enabled=False)
    assert state.snapshot_tables("les_artifact_revisions", "les_workflow_checkpoints") == before
```

- [ ] **Step 3: Run and confirm the route service is absent**

Run: `uv run python -m pytest -q --basetemp=.test-tmp/route-switch tests/test_canonical_route_service.py tests/test_chat_evidence_application_service.py`

- [ ] **Step 4: Implement the explicit route decision**

```python
@dataclass(frozen=True)
class CanonicalRouteDecision:
    enabled: bool
    requested: str
    effective: str
    source: str
    restart_required: bool


def resolve_canonical_route() -> CanonicalRouteDecision:
    """Resolve one visible runtime factor; never infer from model or query text."""
```

The enabled route uses Registry → Broker → Executor → ContextGovernor. The disabled route uses the preserved v0.28.2-compatible chat path but reads no canonical state destructively. Include the decision in redacted `/api/version` diagnostics and the configuration page.

- [ ] **Step 5: Run focused tests and architecture gate**

```text
uv run python -m pytest -q --basetemp=.test-tmp/route-switch tests/test_canonical_route_service.py tests/test_chat_evidence_application_service.py tests/test_runtime_config_registry_service.py tests/test_diag_platform.py
make architecture-gate
```

- [ ] **Step 6: Update version/docs and commit**

Commit: `feat(runtime): add preserved-data canonical route rollback`.

### Task 2: Bind the lightweight manifest to the verified commit and classification

**Files:**
- Modify: `proxy/services/update_service.py`
- Modify: `tools/github_patch_release.py`
- Modify: `tools/patch_release.py`
- Modify: `tests/test_release_classification.py`
- Modify: `tests/test_github_patch_release.py`
- Modify: `tests/test_patch_release.py`
- Modify: `docs/INSTALL_RUNBOOK.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `config/version.json`
- Modify: `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: clean committed tree, base commit `e8ccad2b`, verified head commit and classifier report.
- Produces: immutable manifest with exact file hashes, apply/skip/rollback metadata and channel classification.

- [ ] **Step 1: Write failing manifest/classifier tests**

```python
def test_manifest_is_bound_to_verified_head(classified_tree):
    manifest = build_manifest(classified_tree, verified_commit="abc123")
    assert manifest["source_commit"] == "abc123"
    assert manifest["classification"]["channel"] == "lightweight_github_update"
    assert all(item["sha256"] for item in manifest["files"])


@pytest.mark.parametrize("change", ["uv.lock", "installers/windows/qdrant.exe", "desktop/tauri/src-tauri/Cargo.toml"])
def test_native_dependency_or_installer_changes_block_lightweight_channel(change, classifier):
    assert classifier.classify({change}).channel != "lightweight_github_update"
```

- [ ] **Step 2: Run and confirm missing 0.29 classifier assertions**

Run: `uv run python -m pytest -q --basetemp=.test-tmp/update-manifest tests/test_release_classification.py tests/test_github_patch_release.py tests/test_patch_release.py`

- [ ] **Step 3: Require exact classification and commit identity**

The build command fails when the worktree is dirty, HEAD differs from the verified commit, a manifest file hash differs, or classification includes dependency/installer/native runtime/destructive migration. The manifest includes base/head commits, product/build versions, exact file list/hashes, persistent-state exclusions and rollback preimage hashes.

- [ ] **Step 4: Prove protected/user state is excluded**

Add assertions that `.env`, `data/`, `storage/`, `RAG_Content/`, logs, secrets, artifacts, checkpoints and traces cannot enter the patch payload. Persistent schema additions may be additive only and rollback must leave them intact.

- [ ] **Step 5: Run focused tests and commit**

```text
uv run python -m pytest -q --basetemp=.test-tmp/update-manifest tests/test_release_classification.py tests/test_github_patch_release.py tests/test_patch_release.py tests/test_update_service.py
make architecture-gate
```

Commit: `fix(update): bind canonical patch to verified classification` after version/docs update.

### Task 3: Prove apply, idempotent skip and rollback in isolated Windows state

**Files:**
- Modify: `tests/test_windows_application_update.py`
- Modify: `tests/test_windows_update_shell.py`
- Modify: `tools/windows_prepare_update.ps1`
- Modify: `tools/windows_patch_release.ps1`
- Modify: `docs/INSTALL_RUNBOOK.md`
- Modify: `docs/TEST_INVENTORY.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `config/version.json`
- Modify: `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: exact manifest, isolated install root and isolated persistent state root.
- Produces: apply/skip/rollback receipts preserving state hashes.

- [ ] **Step 1: Write failing isolated lifecycle tests**

```python
def test_apply_skip_rollback_preserves_persistent_state(update_fixture):
    before = update_fixture.hash_persistent_state()
    applied = update_fixture.apply()
    skipped = update_fixture.apply()
    rolled_back = update_fixture.rollback()
    assert applied.status == "applied"
    assert skipped.status == "already_applied"
    assert rolled_back.status == "rolled_back"
    assert update_fixture.hash_persistent_state() == before
```

- [ ] **Step 2: Run and confirm the full state-preservation assertion is absent/failing**

Run: `uv run python -m pytest -q --basetemp=.test-tmp/update-lifecycle tests/test_windows_application_update.py tests/test_windows_update_shell.py`

- [ ] **Step 3: Extend receipts and rollback checks**

Use UTF-8 JSON argument files and PowerShell argument lists. Before mutation, resolve and dry-run the exact isolated `%LOCALAPPDATA%\Programs\LES`-shaped root. Receipts include manifest hash, before/after executable hashes, state-root hash inventory and terminal status. Rollback restores exact executable preimages without removing additive persistent tables or generated artifacts.

- [ ] **Step 4: Run update lifecycle and updater gates**

```text
uv run python -m pytest -q --basetemp=.test-tmp/update-lifecycle tests/test_windows_application_update.py tests/test_windows_update_shell.py tests/test_update_service.py tests/test_manual_update_ui.py
make test-updater
make architecture-gate
```

- [ ] **Step 5: Update version/docs and commit**

Commit: `test(update): prove canonical apply skip and rollback`.

### Task 4: Run the full pre-release gate and leave publication pending

**Files:**
- Modify: `docs/CURRENT_ARCHITECTURE.md`
- Modify: `docs/TEST_INVENTORY.md`
- Modify: `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: all 0.29.0 implementation plans and live workbook report when available.
- Produces: a release-candidate evidence record; no publication.

- [ ] **Step 1: Confirm exact tree boundaries**

```text
git status --short
git diff e8ccad2b...HEAD --name-status
git diff e8ccad2b...HEAD -- proxy/smeta_core uv.lock installers/windows
```

Expected: clean tree; no protected smeta-core changes; no dependency/native/installer changes. If any appear, stop and reclassify as a full installer release.

- [ ] **Step 2: Run complete offline gates**

```text
make architecture-gate
make verify
make test
make test-updater
make public-check
git diff --check
```

- [ ] **Step 3: Run patch preparation and isolated lifecycle**

Run the checked-in patch preparation command with the exact verified HEAD, then apply → idempotent skip → rollback in the isolated test roots described in `docs/INSTALL_RUNBOOK.md`. Record manifest/receipt hashes.

- [ ] **Step 4: Evaluate live model acceptance**

Require a real 9B ordinary-chat workbook report from `tools/live_workbook_acceptance.py`. If no user-owned representative document/model is available, record `PENDING` and do not call the release accepted. Run the same semantic workflow on configured 35B when available.

- [ ] **Step 5: Record result without publishing**

The ledger states exact commands/counts, verified commit, manifest hash, apply/skip/rollback receipts, live acceptance status and exclusions. Publication remains blocked until an explicit owner instruction.

- [ ] **Step 6: Commit the release-candidate record**

Commit: `docs(release): record 0.29.0 candidate evidence`.
