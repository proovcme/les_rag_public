# Windows Bootstrap and Profile Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan.

**Goal:** Ship `0.28.2` as an idempotent offline Windows bootstrap plus authoritative prompt/skill limits.

**Architecture:** A small PowerShell environment-contract module computes and atomically records the exact lock/runtime/cache identity. `bootstrap.ps1` syncs only on contract mismatch or failed health, while Docker/Qdrant remain optional capability warnings. Profile text limits are enforced in the service, mirrored by the API, and shown with existing UI-kit components.

**Tech Stack:** PowerShell 5.1, Python 3.12, uv, FastAPI/Pydantic, SQLite, NiceGUI, pytest.

**Spec:** `docs/superpowers/specs/2026-08-25-windows-bootstrap-idempotency-design.md`

## Global Constraints

- Do not add dependencies, read secrets, start services or touch user state.
- Do not copy `pyproject.toml` and `uv.lock` independently in release assembly.
- Preserve existing oversized revisions as readable; reject only new publication
  until content is reduced below the limit.
- UI work must reuse `panel`, `status_badge`, `action_button`, CodeMirror and the
  existing meta-label styles; add no primitive.
- Each task follows red test → focused green test → commit.

---

### Task 1: Bound the Python support contract

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `tests/test_installer_windows.py`
- Modify: `tests/test_software_versions.py`

**Steps:**

1. Add failing assertions that both project metadata and lock metadata declare
   `>=3.12,<3.14`, and that the bundled contract remains Python `3.13.12`.
2. Run `uv run pytest tests/test_installer_windows.py tests/test_software_versions.py -q`
   and retain the failing output.
3. Change `requires-python`, then run `uv lock` with the repository uv without
   changing dependency versions.
4. Re-run the two tests and inspect `git diff -- pyproject.toml uv.lock` to prove
   only the Python marker graph changed.
5. Commit: `fix(installer): bind offline lock to supported Python`

### Task 2: Implement the lock-bound environment marker

**Files:**
- Create: `installers/windows/app/venv-contract.ps1`
- Create: `tests/test_windows_venv_contract.py`
- Modify: `installers/windows/app/bootstrap.ps1`

**Interface:**

```powershell
Get-LesVenvContract -Root $Root -State $State -BundledPython $BundledPython -Uv $Uv -Extra $Extra
Test-LesVenvContract -Expected $expected -MarkerPath $markerPath
Test-LesVenvHealth -Python $VenvPython
Write-LesVenvContractAtomically -Contract $expected -MarkerPath $markerPath
```

The JSON contains schema, `uv.lock` SHA-256, `requires-python`, bundled Python
identity/version, uv version, offline-cache identity, selected extra, platform
and canonical runtime root.

**Steps:**

1. Write PowerShell-spawning tests for exact match, missing marker, lock mismatch,
   corrupt JSON and a venv whose Python cannot import the core package.
2. Run `uv run pytest tests/test_windows_venv_contract.py -q` and confirm red.
3. Implement pure contract/health functions. Write the marker through a sibling
   temporary file plus same-directory `Move-Item`; never leave a success marker
   before health passes.
4. Dot-source the module from bootstrap without yet changing sync policy.
5. Re-run the focused test and commit: `feat(installer): add offline venv contract marker`

### Task 3: Make bootstrap repair bounded and optional services non-fatal

**Files:**
- Modify: `installers/windows/app/bootstrap.ps1`
- Modify: `tests/test_installer_windows.py`

**Steps:**

1. Replace static tests that encode unconditional sync or deleted diagnostics
   with behavior contracts for: exact marker skips sync; mismatch syncs once;
   unhealthy venv gets one remove-and-rebuild attempt; second failure reports
   `python_environment_invalid`.
2. Add assertions that Docker-engine absence reports
   `docker_engine_unavailable`, Qdrant absence reports `qdrant_unavailable`, and
   neither can set terminal bootstrap state to `failed` after core health passes.
3. Run `uv run pytest tests/test_installer_windows.py -q` and confirm red.
4. Implement the decision table around the current `uv sync` block. Preserve uv
   stderr capture, offline flags and the existing Tauri/desktop-extra selection.
5. Write the marker only after sync and health succeed. A tray restart with an
   exact marker proceeds directly to baseline/core startup.
6. Re-run the focused test and commit: `fix(installer): make offline bootstrap idempotent`

### Task 4: Enforce profile text limits at the authoritative boundary

**Files:**
- Modify: `proxy/services/chat_profile_service.py`
- Modify: `proxy/routers/profiles.py`
- Modify: `tests/test_chat_profile_service.py`
- Modify: `tests/test_profiles_router.py`

**Interface:**

```python
PROFILE_PROMPT_MAX_CHARS = 16_000
PROFILE_SKILL_MAX_CHARS = 8_000

def validate_profile_text(kind: str, text: str) -> str: ...
```

**Steps:**

1. Add boundary tests for `limit`, `limit + 1`, whitespace normalization and an
   old oversized stored revision that remains returned by `registry_snapshot`.
2. Add API tests expecting 200 at the limit and 422/409 with stable code
   `profile_text_too_long` above it.
3. Run both focused files and confirm red.
4. Validate inside `publish_text_revision`; mirror limits in Pydantic fields but
   keep the service authoritative for non-HTTP callers.
5. Return limits in registry metadata so UI does not duplicate numbers.
6. Re-run and commit: `fix(profiles): enforce prompt and skill publication limits`

### Task 5: Add counters and explicit over-limit feedback

**Files:**
- Modify: `sovushka/pages/profiles.py`
- Modify: `tests/test_profiles_ui.py`

**Steps:**

1. Add source-level UI tests requiring `current / limit` counters for both
   CodeMirror editors, warning status at the limit and disabled save above it.
2. Run `uv run pytest tests/test_profiles_ui.py -q` and confirm red.
3. Read limits from `/api/profiles`, update counters on editor change, and reuse
   existing meta text/status/action components. Existing oversized content stays
   visible, but `Сохранить версию` explains why it is disabled.
4. Run the UI test, then perform the Sovushka checklist at 1280×800, 1024×768 and
   390×844 with keyboard focus and both themes.
5. Commit: `feat(profiles): show authoritative prompt and skill budgets`

### Task 6: Prove two consecutive offline starts

**Files:**
- Modify: `tools/windows_release_smoke.ps1`
- Modify: `tests/test_installer_windows.py`

**Steps:**

1. Add a static/fixture contract that the smoke invokes bootstrap twice against
   one isolated state root, captures both status files, and fails unless pass two
   reports `environment_action=skipped`.
2. Add a Docker-disabled pass that still requires API/UI ready. Assert zero
   package-network access and identical `pyproject.toml`/`uv.lock` payload origin.
3. Run the focused test and confirm red, implement the second pass, then re-run.
4. On Legion release candidate, execute:
   `powershell -ExecutionPolicy Bypass -File tools/windows_release_smoke.ps1`
   twice: fresh isolated state and tray-style restart. Archive both machine-readable
   statuses in the release evidence directory.
5. Commit: `test(release): gate consecutive offline Windows bootstrap`

### Task 7: Documentation, version and release gates

**Files:**
- Modify: `docs/ALGO-windows-lifecycle.md`
- Modify: `docs/modules/chat-profiles.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `docs/SOFTWARE_VERSIONS.md`
- Modify: `docs/RELEASE_LEDGER.md`
- Modify: `config/version.json`
- Modify via `make version-sync`: `pyproject.toml`, `desktop/tauri/package.json`,
  `desktop/tauri/package-lock.json`, `desktop/tauri/src-tauri/Cargo.toml`,
  `desktop/tauri/src-tauri/Cargo.lock`, `desktop/tauri/src-tauri/tauri.conf.json`,
  `docs/VERSIONING.md`, `docs/SOFTWARE_VERSIONS.md`

**Steps:**

1. Document the marker decision table, optional capability codes, limits and
   exact recovery behavior. Remove any claim that Docker is required for core.
2. Set product `0.28.2`, build `589`, desktop `5.1.589`, then run
   `make version-sync`.
3. Run focused tests from Tasks 1–6, then `make verify` and `make test`.
4. Run `git diff --check` and `git status --short`; inspect that no protected
   smeta core or user-state path changed.
5. Commit: `release: prepare LES 0.28.2 installer integrity hotfix`
