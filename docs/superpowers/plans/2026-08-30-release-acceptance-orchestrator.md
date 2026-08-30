# Release Acceptance Orchestrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make public LES releases impossible until the exact candidate has installed, passed smoke, rolled back, and reinstalled successfully on Legion.

**Architecture:** Add a small persisted release state/receipt core and one orchestrator that delegates package construction and Windows mutation to the existing patch, NSIS, updater, and smoke implementations. Harden both publishers to require the accepted receipt and explicit target commit, then expose one `make release` operator entry point.

**Tech Stack:** Python 3.12 stdlib, existing PowerShell 5.1 scripts, Tauri/NSIS, pytest, uv, Make, GitHub CLI.

**Spec:** `docs/superpowers/specs/2026-08-30-release-acceptance-orchestrator-design.md`

## Global Constraints

- Legion is the mandatory release host until the owner explicitly changes it.
- Publication is the last transition; candidate installation, smoke, rollback, and reinstallation happen first.
- Candidate source and artifact bytes are immutable after preparation.
- Patch/full is selected by `tools/release_classification.py`; classifier safeguards are never weakened.
- Persistent `%LOCALAPPDATA%\LES` state is outside the application transaction.
- External Qdrant is never installed or mutated except for a uniquely named temporary acceptance dataset when it was already available.
- No new dependency is added.
- `proxy/smeta_core/**`, RAG/model decisions, user corpora, and updater product defaults are not changed.

---

### Task 1: Persisted Release Attempt and Receipt Contract

**Files:**
- Create: `tools/release_receipt.py`
- Create: `tests/test_release_receipt.py`
- Modify: `docs/TEST_INVENTORY.md`

**Interfaces:**
- Produces: `create_attempt(...) -> Path`, `load_attempt(path: Path) -> dict[str, Any]`, `transition(path: Path, *, expected: str, target: str, evidence: dict[str, Any]) -> dict[str, Any]`, `fail_attempt(path: Path, *, stage: str, error: str, recovery: dict[str, Any]) -> dict[str, Any]`, `verify_binding(attempt: dict[str, Any], *, commit: str, assets: Sequence[Path]) -> None`, and `write_public_receipt(attempt_path: Path, destination: Path) -> Path`.
- Consumes: filesystem paths and SHA-256 only; it never invokes Git, Windows, or GitHub.

- [ ] **Step 1: Write failing schema and transition tests**

```python
def test_release_attempt_rejects_skipped_transition(tmp_path):
    state = release_receipt.create_attempt(
        root=tmp_path,
        release_class="patch",
        product_version="0.30.8",
        build_number=648,
        target_commit="a" * 40,
        base_commits=["b" * 40],
        host="legion",
        assets=[],
    )
    with pytest.raises(RuntimeError, match="invalid release transition"):
        release_receipt.transition(
            state,
            expected="planned",
            target="legion_installed",
            evidence={},
        )


def test_one_byte_asset_drift_invalidates_attempt(tmp_path):
    asset = tmp_path / "les-patch.zip"
    asset.write_bytes(b"candidate")
    state = release_receipt.create_attempt(
        root=tmp_path / "work",
        release_class="patch",
        product_version="0.30.8",
        build_number=648,
        target_commit="a" * 40,
        base_commits=["b" * 40],
        host="legion",
        assets=[asset],
    )
    asset.write_bytes(b"Candidate")
    with pytest.raises(RuntimeError, match="artifact binding changed"):
        release_receipt.verify_binding(
            release_receipt.load_attempt(state),
            commit="a" * 40,
            assets=[asset],
        )
```

- [ ] **Step 2: Run the new tests and confirm they fail because `tools.release_receipt` does not exist**

Run: `uv run pytest tests/test_release_receipt.py -q --basetemp=.test-tmp/release-receipt-red`

Expected: collection error importing `tools.release_receipt`.

- [ ] **Step 3: Implement the minimal atomic state machine**

Implement schema `les.release-attempt.v1`, the exact ordered stages from the design, canonical artifact records `{name, path, bytes, sha256}`, a release ID derived with SHA-256 from canonical JSON, and atomic JSON replacement through a sibling temporary file plus `os.replace`. `transition` must require the current and immediately following stages. `fail_attempt` must preserve all completed evidence. `write_public_receipt` must reject every state except `accepted`, redact local absolute paths, emit schema `les.release-receipt.v1`, and include the receipt's own detached SHA in the caller's artifact manifest rather than recursively inside itself.

- [ ] **Step 4: Add failure, resume, sanitization, and deterministic-ID tests**

```python
def test_public_receipt_contains_no_local_paths_or_secret_values(tmp_path):
    receipt = release_receipt.write_public_receipt(accepted_attempt, tmp_path / "release-receipt.json")
    text = receipt.read_text(encoding="utf-8")
    assert "C:\\Users\\Oleg" not in text
    assert "TOKEN=" not in text
    assert json.loads(text)["accepted"] is True
```

Cover repeated transition rejection, exact resume acceptance, commit drift, missing asset, failed attempt publication rejection, and deterministic ordering.

- [ ] **Step 5: Run focused tests**

Run: `uv run pytest tests/test_release_receipt.py -q --basetemp=.test-tmp/release-receipt-green`

Expected: all tests pass.

- [ ] **Step 6: Update the test inventory and commit**

```bash
git add tools/release_receipt.py tests/test_release_receipt.py docs/TEST_INVENTORY.md
git commit -m "feat(release): add immutable acceptance receipt"
```

---

### Task 2: Controlled Rollback of a Successfully Installed Candidate

**Files:**
- Modify: `tools/vps_patch_apply.py`
- Modify: `tools/windows_update_engine.py`
- Modify: `tests/test_windows_application_update.py`
- Modify: `tests/test_vps_patch.py`

**Interfaces:**
- Produces: `rollback_accepted_patch(*, runtime: Path, state: Path, backup_root: Path, expected_target_commit: str) -> dict[str, Any]` in `vps_patch_apply.py`.
- Produces: `rollback_accepted_hard_update(*, install: Path, state: Path, recovery_root: Path, expected_target_commit: str) -> dict[str, Any]` in `windows_update_engine.py`.
- Consumes: recovery locations already created by successful soft/hard update results.

- [ ] **Step 1: Write failing successful-update rollback tests**

```python
def test_accepted_soft_patch_can_be_rolled_back_byte_exact(tmp_path, monkeypatch):
    runtime, state, backup, old_stamp = accepted_soft_fixture(tmp_path)
    result = vps_patch_apply.rollback_accepted_patch(
        runtime=runtime,
        state=state,
        backup_root=backup,
        expected_target_commit="b" * 40,
    )
    assert result["state"] == "rolled_back"
    assert (runtime / "proxy/service.py").read_bytes() == b"old\n"
    assert (runtime / ".les_deploy_stamp.json").read_bytes() == old_stamp


def test_hard_rollback_refuses_recovery_for_another_target(tmp_path):
    with pytest.raises(RuntimeError, match="target identity"):
        windows_update_engine.rollback_accepted_hard_update(
            install=install,
            state=state,
            recovery_root=recovery,
            expected_target_commit="c" * 40,
        )
```

- [ ] **Step 2: Run the two exact tests and verify missing-function failures**

Run: `uv run pytest tests/test_windows_application_update.py tests/test_vps_patch.py -q --basetemp=.test-tmp/accepted-rollback-red -k "accepted_soft_patch_can_be_rolled_back or hard_rollback_refuses"`

- [ ] **Step 3: Refactor existing failure rollback into reusable private primitives**

Extract soft file/stamp restoration without changing the existing exception path. Validate backup manifest, current target commit, every current target SHA, saved file SHA, runtime/state boundary, and backup location below `state/artifacts/patch-backups` before stopping anything. For hard rollback validate that the current install is the accepted target and the recovery tree has its exact previous deploy stamp before swapping directories. Both functions stop only confirmed LES processes, restart the restored runtime, perform exact identity/API/UI smoke, and return structured evidence.

- [ ] **Step 4: Test fail-before-stop behavior and idempotency**

Add tests proving foreign bytes, foreign recovery paths, missing previous stamp, and already rolled-back identity are rejected before mutation. A repeated call may return `already_rolled_back` only when the restored deploy identity exactly matches the recovery manifest.

- [ ] **Step 5: Run updater regression tests**

Run: `make test-updater`

Expected: the updater behavior gate passes, including all existing automatic rollback tests.

- [ ] **Step 6: Commit**

```bash
git add tools/vps_patch_apply.py tools/windows_update_engine.py tests/test_windows_application_update.py tests/test_vps_patch.py
git commit -m "feat(updater): prove controlled candidate rollback"
```

---

### Task 3: Legion Installed-Acceptance Runner

**Files:**
- Create: `tools/windows_release_acceptance.py`
- Create: `tests/test_windows_release_acceptance.py`
- Modify: `tools/windows_updater_smoke.ps1`
- Modify: `tools/windows_release_smoke.ps1`

**Interfaces:**
- Produces: `snapshot_installed(runtime: Path, state: Path) -> dict[str, Any]`, `accept_patch(*, package_dir: Path, runtime: Path, state: Path, expected: dict[str, Any]) -> dict[str, Any]`, `accept_full(*, installer: Path, install: Path, state: Path, expected: dict[str, Any]) -> dict[str, Any]`, and CLI subcommands `snapshot`, `patch`, and `full`.
- Consumes: Task 2 rollback functions and existing updater/install entry points.

- [ ] **Step 1: Write failing acceptance-sequence tests with stubbed mutations**

```python
def test_patch_acceptance_orders_install_smoke_rollback_reinstall(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(acceptance, "install_patch", lambda **kw: calls.append("install") or ready)
    monkeypatch.setattr(acceptance, "installed_smoke", lambda **kw: calls.append("smoke") or healthy)
    monkeypatch.setattr(acceptance, "rollback_patch", lambda **kw: calls.append("rollback") or restored)
    result = acceptance.accept_patch(
        package_dir=tmp_path / "candidate",
        runtime=tmp_path / "app",
        state=tmp_path / "state",
        expected=expected,
    )
    assert calls == ["install", "smoke", "rollback", "smoke", "install", "smoke"]
    assert result["accepted"] is True
```

Add cases where each smoke or rollback fails and assert no later stage runs.

- [ ] **Step 2: Run tests and confirm the runner is absent**

Run: `uv run pytest tests/test_windows_release_acceptance.py -q --basetemp=.test-tmp/windows-acceptance-red`

- [ ] **Step 3: Implement installed snapshot and capability-continuity checks**

Read exact version/build/deploy stamp, resolved application/state roots, core health, UI health, process contract, and availability booleans for configured answer, embedding, and Qdrant roles. Record only role labels and booleans. Reject a changed root or starting commit before install. Require every capability available in the starting snapshot to remain available after each candidate smoke.

- [ ] **Step 4: Implement patch and full acceptance sequences**

Patch installation must use `vps_patch.apply_local` with the prepared directory, never rebuild the package. Full installation must invoke the prepared installer/update job and `windows_update_engine`, never rebuild NSIS. Both sequences cold-restart once, call the Task 2 rollback, smoke the restored identity, reinstall the same bytes, and smoke the final candidate.

- [ ] **Step 5: Add bounded Qdrant/RRF acceptance to the existing smoke scripts**

When Qdrant was available in the starting snapshot, create a uniquely prefixed dataset, upload one UTF-8 marker document, wait for `INDEXED`, call the native-RRF readiness/retrieval endpoint, require the marker in retrieved evidence, and delete only that exact temporary dataset. If cleanup fails, acceptance fails with the dataset ID. If Qdrant was absent initially, record `N/A` without installing or starting it.

- [ ] **Step 6: Run focused and updater tests**

Run: `uv run pytest tests/test_windows_release_acceptance.py tests/test_windows_application_update.py tests/test_vps_patch.py -q --basetemp=.test-tmp/windows-acceptance-green`

Run: `make test-updater`

- [ ] **Step 7: Commit**

```bash
git add tools/windows_release_acceptance.py tools/windows_updater_smoke.ps1 tools/windows_release_smoke.ps1 tests/test_windows_release_acceptance.py
git commit -m "feat(release): accept installed candidates on Legion"
```

---

### Task 4: Unified Prepare and Accept Orchestrator

**Files:**
- Create: `tools/release_orchestrator.py`
- Create: `tests/test_release_orchestrator.py`
- Modify: `tools/patch_release.py`
- Modify: `tools/github_patch_release.py`

**Interfaces:**
- Produces: `prepare(args: Namespace) -> dict[str, Any]`, `accept(args: Namespace) -> dict[str, Any]`, `status(attempt_path: Path) -> dict[str, Any]`, and CLI commands from the design.
- Consumes: Tasks 1 and 3 plus existing classification/build functions.

- [ ] **Step 1: Write failing automatic-classification and exact-byte tests**

```python
def test_prepare_selects_patch_without_calling_installer(monkeypatch, tmp_path):
    monkeypatch.setattr(orchestrator, "classify_release", lambda *a, **k: patch_classification)
    monkeypatch.setattr(orchestrator, "build_patch_candidate", patch_builder)
    monkeypatch.setattr(orchestrator, "build_full_candidate", forbidden)
    result = orchestrator.prepare(prepared_args(tmp_path))
    assert result["release_class"] == "patch"


def test_accept_never_rebuilds_prepared_candidate(monkeypatch, prepared_attempt):
    monkeypatch.setattr(orchestrator, "build_patch_candidate", forbidden)
    result = orchestrator.accept(accept_args(prepared_attempt))
    assert result["stage"] == "accepted"
```

- [ ] **Step 2: Run tests and confirm import failure**

Run: `uv run pytest tests/test_release_orchestrator.py -q --basetemp=.test-tmp/release-orchestrator-red`

- [ ] **Step 3: Implement `prepare`**

Require clean/pushed exact branch and run, in order, version sync check,
runtime-map check, `make verify`, `make test`, `make test-updater`, and
`make public-check`. Record command exit status and duration without embedding
full logs in the receipt. For `patch`, call `build_github_patch_release`
without publishing. For `full`, split `patch_release.py` so the existing remote
preparation produces/fetches the installer without production apply or GitHub
publication. Create the Task 1 attempt only after assets exist and hashes are
known, transition it to `prepared`, and atomically update
`dist/release-work/latest.json` with `{release_id, state_path}` for subsequent
operator commands.

- [ ] **Step 4: Implement Legion transport and `accept`**

Copy the content-addressed candidate and a JSON job to the configured Legion checkout using argument-list `ssh`/`scp`, or execute locally when the resolved host is the current Legion machine. Invoke `windows_release_acceptance.py`, retrieve its result, validate target/source/artifact hashes, and advance each persisted state-machine stage. On any failure call `fail_attempt` with the acceptance runner's recovery evidence.

- [ ] **Step 5: Implement `status` and safe `run`**

`status` prints the persisted attempt without secrets. `run --publish` is syntactic orchestration of `prepare`, `accept`, and Task 5 `publish`; it does not bypass or collapse transitions. `--skip-gates` is allowed only for local unit development and makes the attempt permanently non-publishable.

- [ ] **Step 6: Run focused tests**

Run: `uv run pytest tests/test_release_orchestrator.py tests/test_patch_release.py tests/test_github_patch_release.py -q --basetemp=.test-tmp/release-orchestrator-green`

- [ ] **Step 7: Commit**

```bash
git add tools/release_orchestrator.py tools/patch_release.py tools/github_patch_release.py tests/test_release_orchestrator.py
git commit -m "feat(release): orchestrate prepare and Legion acceptance"
```

---

### Task 5: Acceptance-Gated Draft Publication and Postflight

**Files:**
- Modify: `tools/release_orchestrator.py`
- Modify: `tools/github_patch_release.py`
- Modify: `tools/patch_release.py`
- Modify: `tests/test_release_orchestrator.py`
- Modify: `tests/test_github_patch_release.py`
- Modify: `tests/test_patch_release.py`

**Interfaces:**
- Produces: `publish(args: Namespace) -> dict[str, Any]` and shared `verify_public_provenance(...) -> dict[str, Any]`.
- Consumes: accepted Task 1 attempt and its `release-receipt.json`.

- [ ] **Step 1: Write failing publish-blocker tests**

```python
@pytest.mark.parametrize("stage", ["prepared", "legion_smoke_passed", "rollback_passed"])
def test_publish_refuses_every_preaccepted_stage(stage, attempt_path):
    set_attempt_stage(attempt_path, stage)
    with pytest.raises(RuntimeError, match="installed acceptance required"):
        orchestrator.publish(publish_args(attempt_path))


def test_full_publisher_uses_explicit_accepted_target(monkeypatch, accepted_attempt):
    commands = capture_gh_commands(monkeypatch)
    orchestrator.publish(publish_args(accepted_attempt))
    create = next(c for c in commands if c[:3] == ["gh", "release", "create"])
    assert create[create.index("--target") + 1] == "a" * 40
```

- [ ] **Step 2: Run exact tests and verify failure against current permissive full publisher**

Run: `uv run pytest tests/test_release_orchestrator.py tests/test_patch_release.py tests/test_github_patch_release.py -q --basetemp=.test-tmp/release-publish-red -k "publish or publisher"`

- [ ] **Step 3: Require accepted receipt in both publishers**

Re-hash every accepted asset immediately before GitHub calls. Require local HEAD, pushed branch, and public `main` to equal the accepted target. Add `release-receipt.json` to both canonical release asset sets and bind its SHA/size in `les-update.json` or full `latest.json`. Direct calls to old publish functions must require the attempt path and fail without it.

- [ ] **Step 4: Use immutable draft workflow for both release classes**

Create with the argument pair `--draft --target accepted_target_commit`, where
`accepted_target_commit` is read from the verified receipt, upload without
clobber, download all assets to a fresh directory, compare complete name/hash
maps, then set `--draft=false`. Preserve a failed draft for resume; never
delete, replace, or move an immutable tag automatically.

- [ ] **Step 5: Implement independent postflight**

Query public main and tag refs, download the public feed and receipt, and require exact equality with accepted commit and hashes. Transition to `postflight_verified` only after success. A post-publication mismatch records a critical incident and exits nonzero.

- [ ] **Step 6: Run publisher and updater tests**

Run: `uv run pytest tests/test_release_orchestrator.py tests/test_github_patch_release.py tests/test_patch_release.py -q --basetemp=.test-tmp/release-publish-green`

Run: `make test-updater`

- [ ] **Step 7: Commit**

```bash
git add tools/release_orchestrator.py tools/github_patch_release.py tools/patch_release.py tests/test_release_orchestrator.py tests/test_github_patch_release.py tests/test_patch_release.py
git commit -m "feat(release): publish only accepted artifacts"
```

---

### Task 6: One Operator Command and Canonical Documentation

**Files:**
- Modify: `Makefile`
- Create: `docs/RELEASE_PROCEDURE.md`
- Modify: `SKILL.md`
- Modify: `docs/VERSIONING.md`
- Modify: `docs/INSTALL_RUNBOOK.md`
- Modify: `docs/GUARDRAILS.md`
- Modify: `docs/CODE_MAP.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `docs/TEST_INVENTORY.md`
- Modify: `docs/RELEASE_LEDGER.md`
- Modify: `tests/test_test_profiles.py`
- Modify: `tests/test_documentation_contract.py`

**Interfaces:**
- Produces: `make release RELEASE_ARGS='run --host legion --publish ...'` as the sole public operator entry point.
- Consumes: Task 4/5 CLI.

- [ ] **Step 1: Write failing command and documentation-contract tests**

```python
def test_make_release_has_one_orchestrator_entrypoint():
    command = _dry_make_with_variable("release", "RELEASE_ARGS", "status --release-id abc")
    assert "tools/release_orchestrator.py" in command
    assert "tools/patch_release.py" not in command
    assert "tools/github_patch_release.py" not in command


def test_current_docs_do_not_advertise_legacy_publish_commands():
    for path in CURRENT_RELEASE_DOCS:
        text = path.read_text(encoding="utf-8")
        assert "make patch-release PATCH_RELEASE_ARGS='--publish" not in text
```

- [ ] **Step 2: Run the focused contract tests and confirm failure**

Run: `uv run pytest tests/test_test_profiles.py tests/test_documentation_contract.py -q --basetemp=.test-tmp/release-docs-red`

- [ ] **Step 3: Add the canonical Make target**

```make
release:
	uv run python tools/release_orchestrator.py $(RELEASE_ARGS)
```

Keep old targets only as clearly labelled internal adapters and remove them from operator help.

- [ ] **Step 4: Write the short runbook and repair current docs**

`RELEASE_PROCEDURE.md` must show: bump/sync/commit/push; `prepare`; inspect status; `accept`; inspect receipt; `publish`; postflight; recovery. Replace obsolete `0.23` instructions in `GUARDRAILS.md`. Explain that the tagged ledger records intent while the public receipt records actual acceptance/publication.

- [ ] **Step 5: Regenerate maps if Python line counts changed and run documentation checks**

Run: `uv run python tools/code_runtime_map.py`

Run: `uv run python tools/documentation_contract.py`

- [ ] **Step 6: Run focused tests and commit**

Run: `uv run pytest tests/test_test_profiles.py tests/test_documentation_contract.py tests/test_code_runtime_map.py -q --basetemp=.test-tmp/release-docs-green`

```bash
git add Makefile SKILL.md docs tools/code_runtime_map.py tests/test_test_profiles.py tests/test_documentation_contract.py
git commit -m "docs(release): make installed acceptance canonical"
```

---

### Task 7: Full Verification and Non-public Legion Rehearsal

**Files:**
- Modify only if factual results require it: `docs/RELEASE_LEDGER.md`
- Produce ignored artifacts below `dist/release-work/`, with the content-derived
  release ID as the directory name, plus atomic pointer
  `dist/release-work/latest.json`.

**Interfaces:**
- Consumes: all prior tasks.
- Produces: one accepted, non-public Legion rehearsal receipt for exact `0.30.8` candidate bytes.

- [ ] **Step 1: Synchronize generated/version contracts and inspect the complete diff**

Run: `make version-sync`

Run: `uv run python tools/code_runtime_map.py`

Run: `git diff --check`

- [ ] **Step 2: Run focused release gates**

Run: `make test-updater`

Run: `uv run pytest tests/test_release_receipt.py tests/test_release_orchestrator.py tests/test_windows_release_acceptance.py tests/test_patch_release.py tests/test_github_patch_release.py -q --basetemp=.test-tmp/release-procedure`

- [ ] **Step 3: Run canonical gates**

Run: `make verify`

Run: `make test`

Run: `make public-check`

Expected: all commands exit zero without skipped or weakened release tests.

- [ ] **Step 4: Commit and push the exact candidate before acceptance**

```bash
git status --short
git push origin codex/les-0.30.0-bootstrap-updater
```

Require clean status and exact equality of local HEAD and the pushed branch.

- [ ] **Step 5: Prepare without publication**

Run: `make release RELEASE_ARGS='prepare --host legion --base 9cddee74b4818bf03d9f3e8b75ac920c85c19692 --full-feed .codex_tmp/full-feed-030-release/latest.json'`

The command atomically writes `dist/release-work/latest.json`. Verify its
release ID, classified release kind, target commit, and artifact hashes.

- [ ] **Step 6: Accept on Legion without publication**

Run in PowerShell:

```powershell
$lesReleaseId = (Get-Content -LiteralPath dist/release-work/latest.json -Raw | ConvertFrom-Json).release_id
make release RELEASE_ARGS="accept --host legion --release-id $lesReleaseId"
```

Expected receipt: exact `0.30.8/build 648` commit; install, cold restart, smoke, rollback, restored-version smoke, same-byte reinstall, final smoke; `accepted=true`. The command must stop and recover on any mismatch.

- [ ] **Step 7: Exercise the publication blocker without publishing**

Copy the accepted state to a temporary test location, alter one candidate byte, and invoke publish against the copy. Expected: nonzero exit with `artifact binding changed` before any `gh release create` call. Restore nothing because only the temporary copy was altered.

- [ ] **Step 8: Update the ledger with the factual non-public rehearsal result and commit**

Record release ID, target commit, Legion starting/final identities, acceptance result, receipt SHA, and `published: false`. Do not include machine paths or logs.

```bash
git add docs/RELEASE_LEDGER.md
git commit -m "docs(release): record Legion acceptance rehearsal"
```

- [ ] **Step 9: Request final code review before the first orchestrated publication**

Review must check state-machine safety, both rollback implementations, receipt sanitization, direct-publisher fail-closed behavior, and the exact Legion receipt. Resolve every Critical or Important finding and rerun affected gates.
