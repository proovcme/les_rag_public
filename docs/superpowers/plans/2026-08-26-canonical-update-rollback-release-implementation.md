# Canonical Update, Rollback and Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package the verified 0.29.0 architecture as a lightweight GitHub update when classification remains patch-safe, with an exact-manifest rollback that preserves user artifacts, checkpoints, traces, documents, indexes and settings.

**Architecture:** One GUI-visible `legacy | shadow | active` route factor controls ordinary chat. Shadow is the fail-closed default and leaves the preserved v0.28.2-compatible answer authoritative; active requires both an explicit operator action and a passing acceptance receipt bound to the exact commit, build, 9B preset and observed model identity. The existing immutable update channel classifies the exact committed change set, creates a commit-bound manifest and proves apply/skip/rollback against isolated state before publication.

**Tech Stack:** Python 3.12, existing update service and GitHub patch tools, FastAPI, NiceGUI, pytest, PowerShell acceptance, uv, Make.

**Spec:** `docs/superpowers/specs/2026-08-26-canonical-tool-context-memory-update-design.md`

## Global Constraints

- Execute after the foundation, ContextGovernor/memory, workbook and trust-fix plans are complete and green.
- Public release remains `0.29.0`; increment only `build_number`/`desktop_version` for implementation checkpoints.
- Lightweight update is allowed only when the classifier proves no dependency, installer, native runtime or destructive migration change.
- PR6 is excluded because bundled Qdrant requires a full installer and exact Windows storage acceptance.
- Rollback changes executable routing only; it must not delete or rewrite artifacts, checkpoints, traces, documents, indexes or settings.
- The requested/effective route factor is GUI-visible with value, source, downgrade reason and restart requirement.
- An absent route setting defaults to `shadow`; update/install never creates a receipt, changes a stored choice or promotes to `active`.
- `shadow` cannot alter user-visible output or persist canonical tool/artifact/checkpoint/profile/binding effects.
- Promotion requires a real same-workflow 9B non-regression report and explicit operator acceptance; 35B evidence is optional and cannot replace it.
- Publishing remains prohibited without the owner's explicit release instruction.
- Do not add dependencies or touch `proxy/smeta_core/**`.
- Every task updates its module documentation and `docs/MODULE_INDEX.md`, increments `build_number` once, runs `make version-sync`, and records the change in `docs/RELEASE_LEDGER.md` in the same commit.

---

### Task 1: Harden the preserved-data three-state route and promotion gate

**Files:**
- Create: `proxy/services/canonical_promotion_service.py`
- Create: `tests/test_canonical_promotion_service.py`
- Modify: `proxy/services/canonical_route_service.py`
- Modify: `tests/test_canonical_route_service.py`
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
- Consumes: configured `LES_CANONICAL_AGENT_ROUTE_MODE`, exact runtime identity, append-only accepted `PromotionReceipt` and runtime restart state.
- Produces: `accept_promotion_report()`, `load_exact_promotion_receipt()`, fail-closed `CanonicalRouteDecision` and one route decision before model invocation.

- [ ] **Step 1: Before UI edits, read required Sovushka instructions**

Read `skills/sovushka-ui/SKILL.md` and `docs/modules/sovushka-uikit.md`; reuse the runtime-factor component registry.

- [ ] **Step 2: Write failing route/rollback tests**

```python
def test_route_mode_is_explicit_and_redacted(monkeypatch):
    monkeypatch.setenv("LES_CANONICAL_AGENT_ROUTE_MODE", "legacy")
    decision = resolve_canonical_route(receipt=None)
    assert decision.effective is CanonicalRouteMode.LEGACY
    assert decision.source == "environment"


def test_active_without_exact_receipt_fails_closed_to_shadow(monkeypatch):
    monkeypatch.setenv("LES_CANONICAL_AGENT_ROUTE_MODE", "active")
    decision = resolve_canonical_route(receipt=receipt_for(build_number=590))
    assert decision.requested is CanonicalRouteMode.ACTIVE
    assert decision.effective is CanonicalRouteMode.SHADOW
    assert decision.reason == "promotion_receipt_mismatch"


def test_exact_passing_9b_receipt_allows_explicit_active(monkeypatch):
    monkeypatch.setenv("LES_CANONICAL_AGENT_ROUTE_MODE", "active")
    decision = resolve_canonical_route(receipt=exact_passing_9b_receipt())
    assert decision.effective is CanonicalRouteMode.ACTIVE


def test_accepting_report_never_changes_stored_route(meta_db, passing_report):
    set_route_mode(meta_db, "shadow")
    receipt = accept_promotion_report(meta_db, passing_report, operator_confirmed=True)
    assert receipt.acceptance_sha256 == passing_report.sha256
    assert get_route_mode(meta_db) == "shadow"


def test_update_without_stored_choice_resolves_shadow(meta_db):
    apply_additive_029_schema(meta_db)
    assert get_route_mode(meta_db) is None
    assert resolve_canonical_route(receipt=None).effective is CanonicalRouteMode.SHADOW


@pytest.mark.asyncio
async def test_compatibility_route_does_not_delete_canonical_state(state, chat_runtime):
    before = state.snapshot_tables("les_artifact_revisions", "les_workflow_checkpoints")
    await run_chat_with_route(chat_runtime, mode="legacy")
    assert state.snapshot_tables("les_artifact_revisions", "les_workflow_checkpoints") == before
```

- [ ] **Step 3: Run and confirm the boolean route/receipt assertions fail**

Run: `uv run python -m pytest -q --basetemp=.test-tmp/route-switch tests/test_canonical_promotion_service.py tests/test_canonical_route_service.py tests/test_chat_evidence_application_service.py`

- [ ] **Step 4: Implement the explicit route decision**

```python
@dataclass(frozen=True)
class CanonicalRouteDecision:
    requested: CanonicalRouteMode
    effective: CanonicalRouteMode
    source: str
    reason: str
    restart_required: bool


def resolve_canonical_route(*, receipt: PromotionReceipt | None) -> CanonicalRouteDecision:
    """Resolve one visible mode and fail closed when promotion proof is absent."""
```

`legacy` uses the preserved v0.28.2-compatible path. `shadow` keeps that answer
and runs the canonical Registry → Broker → Executor → ContextGovernor candidate
without persistent effects. `active` uses the canonical answer only when the
receipt has `passed=true` and exactly matches source commit, build number,
`qwen-9b-restrictive` preset, observed model identity and acceptance-report
SHA-256. Missing, failed or stale proof downgrades effective mode to `shadow`.
Include requested/effective/reason in redacted `/api/version` diagnostics and
the configuration page. Changing to active is a `Danger` action with explicit
confirmation; installing an update does not invoke it.

Store accepted reports in an additive append-only
`les_canonical_promotion_receipts` MetaDB table. `accept_promotion_report()`
requires `operator_confirmed=True`, recomputes the report SHA-256, verifies a
real non-fixture 9B result and inserts the immutable receipt; it never writes
the route setting. `load_exact_promotion_receipt()` returns a receipt only when
all runtime identity fields match. The settings route exposes acceptance and
mode-change as two separate authenticated operations.

- [ ] **Step 5: Run focused tests and architecture gate**

```text
uv run python -m pytest -q --basetemp=.test-tmp/route-switch tests/test_canonical_promotion_service.py tests/test_canonical_route_service.py tests/test_chat_evidence_application_service.py tests/test_runtime_config_registry_service.py tests/test_diag_platform.py
make architecture-gate
```

- [ ] **Step 6: Update version/docs and commit**

Commit: `feat(runtime): gate canonical route promotion`.

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

### Task 4: Prove 9B non-regression, then run the full pre-release gate

**Files:**
- Modify: `tools/live_workbook_acceptance.py`
- Modify: `tests/test_live_workbook_acceptance.py`
- Modify: `docs/CURRENT_ARCHITECTURE.md`
- Modify: `docs/TEST_INVENTORY.md`
- Modify: `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: all 0.29.0 implementation plans and a paired legacy/canonical 9B workbook report when available.
- Produces: a hash-bound promotion report/optional operator-accepted receipt and a release-candidate evidence record; no automatic activation or publication.

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

- [ ] **Step 4: Evaluate paired live 9B non-regression**

First run the report/receipt contract tests:

```text
uv run python -m pytest -q --basetemp=.test-tmp/route-acceptance tests/test_live_workbook_acceptance.py tests/test_canonical_promotion_service.py tests/test_canonical_route_service.py
```

Run the preserved and canonical candidates on the same representative source,
request, bound profile and observed local 9B identity. Canonical execution uses
an isolated state root, not production `active`. The report fails on any loss
of workflow completion, readable revision 1/revision 2 artifacts, immutable
history, provenance, blockers/MISSING integrity, cancellation/resume behavior,
or stability (including repeated row-closing loops). It records both outcomes,
elapsed times, exact commit/build/preset/model identity and its own SHA-256; it
must not claim semantic superiority from fixtures or structural tests.

If no user-owned representative document/model is available, record `PENDING`,
do not produce a receipt and do not call the release accepted. A passing report
still requires an explicit operator acceptance action to create the bound
`PromotionReceipt`; creation does not change the stored route mode. Run the same
workflow on configured 35B when available, but never use it instead of 9B.

The checked-in CLI exposes explicit `--compare-routes legacy,canonical-candidate`,
`--isolated-state-root`, `--attachment`, `--base-url`, `--profile-revision`,
`--model-preset qwen-9b-restrictive` and `--out` arguments. It rejects fixture
attachments, a production state root, unequal request/profile inputs and any
attempt to emit a receipt without a passing report plus explicit operator
confirmation.

- [ ] **Step 5: Record result without publishing**

The ledger states exact commands/counts, verified commit, manifest hash,
apply/skip/rollback receipts, paired live acceptance status/report hash,
promotion-receipt status and exclusions. Verify an update preserves explicit
`legacy`/`shadow`, treats no stored value as `shadow`, and downgrades stale
`active` proof to effective `shadow`. Publication remains blocked until an
explicit owner instruction; publication never changes the route mode.

- [ ] **Step 6: Commit the release-candidate record**

Commit: `docs(release): record 0.29.0 candidate evidence`.
