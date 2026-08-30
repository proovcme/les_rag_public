# Transactional Delete Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow one lightweight GitHub patch to update an installed LES `0.30.0` directly to the current release while transactionally deleting proven obsolete runtime files and restoring them on failure.

**Architecture:** Keep the outer manifest at backward-compatible `les.vps-patch.v2`. A delete entry carries `operation: "delete"` plus a zero-byte compatibility payload, so the `0.30.0` feed/archive validator accepts it. The same cumulative patch must replace `tools/vps_patch_apply.py`; the already-shipped target-helper staging mechanism launches that new detached helper, which interprets deletion, backs up the installed file, removes it, and restores it on rollback.

**Tech Stack:** Python 3.12, zipfile/JSON/SHA-256, FastAPI service validation, detached Windows updater, pytest, uv, GitHub Release assets.

**Spec:** `docs/superpowers/specs/2026-08-30-boundary-first-architecture-design.md`

## Global Constraints

- Public compatibility base: `9cddee74b4818bf03d9f3e8b75ac920c85c19692` (`0.30.0 / build 634`).
- Keep schema `les.vps-patch.v2`; installed `0.30.0` rejects another schema before staging the target helper.
- Any patch with a delete entry must also replace `tools/vps_patch_apply.py`.
- Deletion is allowed only below `backend/`, `proxy/`, `sovushka/`, `qdrant_visualizer/`, `config/prompts/`, `skills/`, or `docs/`. App-shell and exact lifecycle/bootstrap files cannot be deleted.
- Unknown installed bytes fail before runtime stop or mutation.
- User state, datasets, SQLite, Qdrant, memory, settings and secrets never enter the transaction.
- Do not modify `proxy/smeta_core/**`; do not add dependencies.
- No installer/Tauri rebuild, deployment, installed-runtime mutation or publication.
- Repository DoD requires code, tests, docs, version and ledger together. Tasks 1–4 remain uncommitted; Task 5 creates one atomic commit.

## File Map

- `tools/vps_patch.py`: build backward-compatible replace/delete entries and enforce self-bridge.
- `tools/vps_patch_apply.py`: validate, apply and roll back deletion.
- `proxy/services/update_service.py`: calculate operation-aware availability/compatibility.
- `tools/github_patch_release.py`: prove delete/apply/skipped-version/rollback in the isolated release gate.
- `tests/test_{vps_patch,windows_application_update,github_patch_release,release_classification}.py`: regression coverage.
- `docs/{VPS_PATCH_CHANNEL,MODULE_INDEX,CODE_MAP,SOFTWARE_VERSIONS,RELEASE_LEDGER}.md` and synchronized version surfaces: product truth.

---

### Task 1: Build a v2-compatible self-bridging delete package

**Files:**
- Modify: `tools/vps_patch.py`
- Modify: `tests/test_vps_patch.py`
- Modify: `tests/test_release_classification.py`

**Interfaces:**
- Consumes: `accepted_file_hashes(base_commit, target_commit, path, installed_runtime=None) -> tuple[list[str], bool]`.
- Produces: optional manifest field `operation`, defaulting to `replace`.
- Produces: delete entry with zero-byte payload, its SHA-256, historical accepted hashes, and `accepted_missing=True`.

- [ ] **Step 1: Add a failing builder test**

Create a temporary Git repo with `proxy/old_agent.py`, `tools/vps_patch_apply.py`, and a valid `config/version.json`. Commit the base; delete the old module and modify the helper in the target. Build both paths and assert:

```python
with zipfile.ZipFile(built["archive"]) as bundle:
    manifest = json.loads(bundle.read("manifest.json"))
    deleted = next(
        entry for entry in manifest["files"]
        if entry["path"] == "proxy/old_agent.py"
    )
    assert manifest["schema"] == "les.vps-patch.v2"
    assert deleted["operation"] == "delete"
    assert deleted["bytes"] == 0
    assert deleted["sha256"] == hashlib.sha256(b"").hexdigest()
    assert bundle.read("payload/proxy/old_agent.py") == b""
    assert "payload/tools/vps_patch_apply.py" in bundle.namelist()
```

- [ ] **Step 2: Add fail-closed and classification tests**

Assert omission of the helper fails:

```python
with pytest.raises(
    ValueError,
    match="delete patch must replace tools/vps_patch_apply.py",
):
    vps_patch.build_patch(
        base=base,
        target=target,
        files=["proxy/old_agent.py"],
        output=tmp_path / "unsafe",
        origin="https://example.invalid",
    )
```

In `tests/test_release_classification.py`, delete an allowed committed `proxy/delete_me.py` and assert:

```python
result = classify_release(base, target, root=repo)
assert result.kind == "patch"
assert result.runtime_files == ("proxy/delete_me.py",)
```

- [ ] **Step 3: Run tests and confirm the intended failure**

```powershell
uv run pytest tests/test_vps_patch.py tests/test_release_classification.py --basetemp=.test-tmp/delete-builder -q
```

Expected: the builder reports that fast patches do not support deletion.

- [ ] **Step 4: Implement entry construction**

Add:

```python
PATCH_OPERATION_REPLACE = "replace"
PATCH_OPERATION_DELETE = "delete"
DELETE_BRIDGE_HELPER = "tools/vps_patch_apply.py"
DELETE_MARKER = b""
```

In `build_patch()`, replacements get `operation: "replace"`. When `after is None` and `before is not None`, create:

```python
payload[path] = DELETE_MARKER
entries.append(
    {
        "operation": PATCH_OPERATION_DELETE,
        "scope": "runtime",
        "path": path,
        "base_sha256": sha256_bytes(windows_runtime_bytes(before)),
        "accepted_sha256": accepted_hashes,
        "accepted_missing": True,
        "sha256": sha256_bytes(DELETE_MARKER),
        "bytes": 0,
    }
)
```

After assembling entries, require:

```python
if any(entry["operation"] == PATCH_OPERATION_DELETE for entry in entries):
    helper = next(
        (entry for entry in entries if entry["path"] == DELETE_BRIDGE_HELPER),
        None,
    )
    if helper is None or helper["operation"] != PATCH_OPERATION_REPLACE:
        raise ValueError(
            "delete patch must replace tools/vps_patch_apply.py"
        )
```

Do not introduce schema v3 and do not omit the marker ZIP member.

- [ ] **Step 5: Run builder tests**

```powershell
uv run pytest tests/test_vps_patch.py tests/test_release_classification.py --basetemp=.test-tmp/delete-builder -q
```

Expected: all tests pass and old replace-only archives remain valid v2 packages.

---

### Task 2: Make discovery understand delete target state

**Files:**
- Modify: `proxy/services/update_service.py`
- Modify: `tests/test_vps_patch.py`

**Interfaces:**
- Consumes: optional `operation`; absence means `replace`.
- Produces: `patch_entry_operation(entry: dict[str, Any]) -> str`.
- Produces: delete target matches when the path is absent; unknown existing bytes are incompatible.

- [ ] **Step 1: Add feed tests for known, absent and unknown targets**

Construct a v2 feed with a replacement helper entry and a deletion entry. Assert:

```python
known = update_service.validate_github_update_feed(feed)
assert known["available"] is True
assert known["compatible"] is True

old.unlink()
absent = update_service.validate_github_update_feed(feed)
assert absent["available"] is False
assert absent["compatible"] is True

old.write_bytes(b"local user edit\n")
unknown = update_service.validate_github_update_feed(feed)
assert unknown["available"] is True
assert unknown["compatible"] is False
```

Also assert deletion of `scope=app`, `config/version.json`, and `tools/windows_update_engine.py` is rejected.

- [ ] **Step 2: Run the new tests and confirm failure**

```powershell
uv run pytest tests/test_vps_patch.py -k "delete_target or delete_scope" --basetemp=.test-tmp/delete-feed -q
```

Expected: the current validator treats marker SHA as target file state.

- [ ] **Step 3: Implement operation-aware validation**

Add:

```python
VPS_PATCH_DELETE_ALLOWED_ROOTS = (
    "backend/",
    "proxy/",
    "sovushka/",
    "config/prompts/",
    "skills/",
    "docs/",
)

def patch_entry_operation(entry: dict[str, Any]) -> str:
    operation = str(entry.get("operation") or "replace")
    if operation not in {"replace", "delete"}:
        raise UpdateError(
            "Обновление содержит неизвестную файловую операцию"
        )
    return operation
```

Inside `_validate_patch_feed()`:

- validate operation and least-privilege delete scope;
- require a `replace` entry for `tools/vps_patch_apply.py` if any entry deletes;
- continue validating marker SHA/size for compatibility with `0.30.0`;
- compute target state with:

```python
target_matches_entry = (
    current is None if operation == "delete" else current == target_hash
)
```

Compatibility remains exact historical SHA or accepted absence.

- [ ] **Step 4: Preserve old-client archive staging**

Do not remove marker paths from expected ZIP names. Preserve `_stage_vps_patch_launcher()`: public `0.30.0` extracts the target helper before it stops LES.

- [ ] **Step 5: Run feed and launcher tests**

```powershell
uv run pytest tests/test_vps_patch.py tests/test_update_service.py --basetemp=.test-tmp/delete-feed -q
```

Expected: all URL, cumulative-hash, feed and target-helper tests pass.

---

### Task 3: Apply and roll back deletion transactionally

**Files:**
- Modify: `tools/vps_patch_apply.py`
- Modify: `tests/test_windows_application_update.py`

**Interfaces:**
- Consumes: optional `operation`, default `replace`.
- Produces: `_unlink_with_retry(path: Path, *, timeout: float = 15.0) -> None`.
- Produces: exact backup under `files/runtime/<path>` and restoration on rollback.
- Produces: ready-status counters `replaced_files` and `deleted_files`.

- [ ] **Step 1: Extend the fixture with deletion**

Add `delete_file: bool = False` to `_prepared_job()`. For true, create `runtime/proxy/old_agent.py`, make the helper entry `operation: "replace"`, add:

```python
{
    "operation": "delete",
    "path": "proxy/old_agent.py",
    "base_sha256": _sha(b"obsolete runtime\n"),
    "accepted_sha256": [_sha(b"obsolete runtime\n")],
    "accepted_missing": True,
    "sha256": _sha(b""),
    "bytes": 0,
}
```

and write `payload/proxy/old_agent.py` as `b""`.

- [ ] **Step 2: Add success, idempotency and pre-stop rejection tests**

Success must prove target absence, backup bytes and `deleted_files == 1`. Idempotency removes the target before apply and still succeeds. Unknown bytes must return `1`, leave `stopped == []`, preserve the local edit, and report stage `rejected`.

- [ ] **Step 3: Add forced-smoke rollback**

Reuse the existing failed-smoke health mock and assert:

```python
assert vps_patch_apply.apply_job(job) == 1
assert (
    runtime / "proxy" / "old_agent.py"
).read_bytes() == b"obsolete runtime\n"
assert (
    runtime / ".les_deploy_stamp.json"
).read_bytes() == previous_stamp
assert (
    state / "data" / "user-owned.db"
).read_bytes() == b"never replace me"
```

- [ ] **Step 4: Add transient lock coverage**

Make the first exact unlink raise `PermissionError` and the second succeed. Assert `_unlink_with_retry(path, timeout=1)` removes only the requested file.

- [ ] **Step 5: Run new behavior tests and confirm failure**

```powershell
uv run pytest tests/test_windows_application_update.py -k "delete or unknown_delete" --basetemp=.test-tmp/delete-apply -q
```

Expected: current helper compiles/replaces every payload and does not delete.

- [ ] **Step 6: Implement validation, mutation and rollback**

In `tools/vps_patch_apply.py`:

1. Parse operation with legacy default `replace`.
2. Restrict delete to the seven directory roots and forbid app deletion.
3. Require a replacement helper in every delete manifest.
4. Continue hashing the marker, but skip `py_compile` for delete.
5. Add bounded `_unlink_with_retry()`.
6. Back up existing targets before runtime stop.
7. For deletion, record `changed` before unlink and do not create the parent.
8. Keep rollback generic: an existing saved target is restored with `_atomic_copy`; an originally absent target remains absent.
9. Preserve `changed_files` and add explicit counters.

Mutation core:

```python
if operation == "delete":
    changed.append((target, existed, backup_rel))
    if existed:
        _unlink_with_retry(target)
    deleted_files += 1
else:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".les-update.tmp")
    shutil.copy2(stage / backup_rel, temporary)
    _replace_with_retry(temporary, target)
    changed.append((target, existed, backup_rel))
    replaced_files += 1
```

- [ ] **Step 7: Run the complete Windows updater behavior file**

```powershell
uv run pytest tests/test_windows_application_update.py --basetemp=.test-tmp/delete-apply -q
```

Expected: all soft/hard update, baseline, retry, process and rollback tests pass.

---

### Task 4: Make GitHub release evidence cover deletion

**Files:**
- Modify: `tools/github_patch_release.py`
- Modify: `tests/test_github_patch_release.py`

**Interfaces:**
- Consumes: marker payload for both operations.
- Produces: evidence keys `deleted_files_absent_after_apply` and `deleted_files_restored_on_rollback`.
- Preserves: existing apply, rollback, new-file and skipped-version evidence.

- [ ] **Step 1: Add a release fixture with replacement, addition and deletion**

Commit `proxy/obsolete.py` in the base; delete it in target and modify `tools/vps_patch_apply.py`. Assert the ZIP retains the zero-byte marker and v2 schema.

- [ ] **Step 2: Require deletion evidence**

```python
assert published["evidence"][
    "deleted_files_absent_after_apply"
] is True
assert published["evidence"][
    "deleted_files_restored_on_rollback"
] is True
```

- [ ] **Step 3: Run the release tests and confirm failure**

```powershell
uv run pytest tests/test_github_patch_release.py --basetemp=.test-tmp/delete-release -q
```

Expected: the current isolated gate leaves marker bytes instead of target absence.

- [ ] **Step 4: Implement operation-aware in-memory apply**

Continue validating marker size/SHA. For replace, assign payload to `current[path]`; for delete, remove `path`. Compute target state by operation, track base files deleted by target, restore `original` exactly, publish the two booleans and include them in required evidence.

```python
def target_state_matches(
    entry: dict[str, Any],
    current: dict[str, bytes],
) -> bool:
    path = str(entry["path"])
    if str(entry.get("operation") or "replace") == "delete":
        return path not in current
    return vps_patch.sha256_bytes(current[path]) == entry["sha256"]
```

- [ ] **Step 5: Run release and package tests together**

```powershell
uv run pytest tests/test_github_patch_release.py tests/test_vps_patch.py --basetemp=.test-tmp/delete-release -q
```

Expected: all tests pass and the five immutable GitHub asset names remain unchanged.

---

### Task 5: Synchronize truth, run gates, and commit atomically

**Files:**
- Modify: `docs/VPS_PATCH_CHANNEL.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `docs/CODE_MAP.md`
- Modify: `config/version.json`
- Modify by sync: `pyproject.toml`, `uv.lock`, Tauri version surfaces, `docs/SOFTWARE_VERSIONS.md`
- Modify: `docs/RELEASE_LEDGER.md`
- Commit all Task 1–5 files.

**Interfaces:**
- Produces: `0.30.6 / build 646 / desktop 5.1.646` dev candidate.
- Does not produce: release publication, deployment, installer or native binary.

- [ ] **Step 1: Document the exact contract**

In `docs/VPS_PATCH_CHANNEL.md`, record:

- missing `operation` means replace;
- deletion carries an empty compatibility payload because `0.30.0` validates one payload per entry;
- every deletion package includes and stages target `tools/vps_patch_apply.py`;
- unknown bytes reject before stop;
- already absent is idempotent target state;
- rollback restores exact saved bytes;
- app shell, lifecycle/bootstrap, state and data cannot be deleted.

Update the `ops/vps-patch` row in `docs/MODULE_INDEX.md` and updater flow in `docs/CODE_MAP.md` with the same entrypoints.

- [ ] **Step 2: Synchronize version 0.30.6**

Set `config/version.json` to:

```json
{
  "schema": "les.version.v1",
  "product_version": "0.30.6",
  "build_number": 646,
  "desktop_version": "5.1.646",
  "harness_schema_version": "0.24"
}
```

Run:

```powershell
make version-sync
```

Windows fallback:

```powershell
uv run python tools/sync_version_contract.py
```

Add a top ledger entry: unpublished/undeployed dev candidate; updater contract only; user state, RAG, models, UI behavior and `proxy/smeta_core/**` unchanged.

- [ ] **Step 3: Run focused tests**

```powershell
uv run pytest tests/test_release_classification.py tests/test_vps_patch.py tests/test_windows_application_update.py tests/test_github_patch_release.py tests/test_update_service.py --basetemp=.test-tmp/delete-bridge-focused -q
```

Expected: all pass.

- [ ] **Step 4: Run canonical updater gate**

```powershell
make test-updater
```

Windows fallback:

```powershell
uv run python tools/platform_release_gate.py updater
```

Expected: validate/apply/skipped-version/rollback/user-state/process checks pass.

- [ ] **Step 5: Run repository gates**

```powershell
make verify
make test
```

Windows fallback:

```powershell
uv run python tools/platform_release_gate.py current-verify
uv run python tools/platform_release_gate.py current-test
```

Expected: both pass. Smeta benchmark is not required because protected smeta code is unchanged.

- [ ] **Step 6: Inspect cumulative public-base diff**

```powershell
git diff --name-status 9cddee74b4818bf03d9f3e8b75ac920c85c19692..HEAD
git diff --check
git status --short
```

Confirm every deleted runtime path is allowlisted and cumulative ancestry includes modified `tools/vps_patch_apply.py`. Do not run `--publish`, `apply-local`, `update-local`, `make ship`, or installer commands.

- [ ] **Step 7: Create one DoD-complete commit**

Stage the implementation, tests, docs, version surfaces and ledger, then run:

```powershell
git diff --cached --check
git commit -m "feat(updater): support transactional runtime deletion"
```

Expected: one coherent commit; working tree clean. Publication and installed-Legion acceptance require a separate explicit owner instruction.
