# Windows State and Installer Cycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Windows runtime create mutable data directly in persistent state, reject junction-only path ownership, catch clean-start failures before NSIS compression, and reuse the offline dependency cache across LES-only version bumps.

**Architecture:** `backend.runtime_paths` becomes the one product boundary for `data`, `storage`, `logs`, `RAG_Content`, and `artifacts`. A Programs-shaped prebundle smoke runs the staged runtime before Tauri packaging, while a normalized dependency fingerprint separates third-party cache identity from the local LES version. The existing exact-installer smoke and hard-update rollback remain the final release gates.

**Tech Stack:** Python 3.12/3.13, pathlib, tomllib, PowerShell 5.1, uv, Tauri 2, NSIS, pytest.

**Spec:** `docs/superpowers/specs/2026-08-29-windows-state-and-installer-cycle-design.md`

## Global Constraints

- Mutable Windows state remains below `%LOCALAPPDATA%\LES`; replaceable code remains below `%LOCALAPPDATA%\Programs\LES`.
- Production Python must not create directories through application-tree junctions.
- No dependency is added and no protected `proxy/smeta_core/**` file is modified.
- Prebundle and isolated installed smoke use unique roots and never read or mutate production state.
- Docker, Qdrant, answer models, and embedding models remain external capabilities; core proxy/UI readiness is distinct from capability readiness.
- Production is updated only after prebundle and exact-installer gates pass; hard-update rollback preserves state.
- The implementation release becomes `0.29.2`, build `628`, desktop `5.1.628`.

---

### Task 1: Persistent mutable-path boundary and clean proxy startup

**Files:**
- Create: `backend/runtime_paths.py`
- Create: `tests/test_runtime_paths.py`
- Modify: `tools/install_les.py`
- Modify: `tests/test_install_les.py`
- Modify: `proxy/routers/artifacts.py`
- Modify: `proxy/routers/chat.py`
- Modify: `backend/diagnostics.py`
- Modify: `sovushka/state.py`
- Test: `tests/test_artifact_revision_service.py`
- Test: `tests/test_installer_windows.py`

**Interfaces:**
- Produces: `mutable_path(relative: str | Path) -> Path` and `mutable_root(name: str) -> Path`.
- Contract: allowed first components are exactly `data`, `storage`, `logs`, `RAG_Content`, and `artifacts`.
- Contract: when `LES_WINDOWS_STATE_ROOT` is set, returned paths are below that exact root; otherwise repository-relative behavior is preserved.
- Contract: absolute inputs and unknown relative roots raise `MutablePathError` rather than silently escaping ownership.

- [ ] **Step 1: Normalize generated version surfaces left by the failed diagnostic build**

Run:

```powershell
uv run python tools/sync_version_contract.py
git diff -- desktop/tauri/package-lock.json desktop/tauri/src-tauri/tauri.conf.json
```

Expected: build-generated drift returns to the committed `0.29.1 / 627 / 5.1.627` contract; the diagnostic test edit remains visible.

- [ ] **Step 2: Write failing path-boundary tests**

Add to `tests/test_runtime_paths.py`:

```python
from pathlib import Path

import pytest

from backend.runtime_paths import MutablePathError, mutable_path


def test_windows_state_root_owns_registered_mutable_path(tmp_path, monkeypatch):
    monkeypatch.setenv("LES_WINDOWS_STATE_ROOT", str(tmp_path / "state"))
    assert mutable_path("storage/artifacts/files") == tmp_path / "state/storage/artifacts/files"


def test_unknown_mutable_root_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("LES_WINDOWS_STATE_ROOT", str(tmp_path / "state"))
    with pytest.raises(MutablePathError, match="registered mutable root"):
        mutable_path("scratch/result.json")


def test_absolute_input_is_rejected(tmp_path):
    with pytest.raises(MutablePathError, match="relative"):
        mutable_path(tmp_path / "outside")
```

Extend the existing real Programs+junction test in `tests/test_install_les.py` so it asserts that `storage/artifacts/files` is created in the state target.

- [ ] **Step 3: Run the boundary tests and verify RED**

Run:

```powershell
uv run pytest tests/test_runtime_paths.py tests/test_install_les.py -q --basetemp=.test-tmp/state-path-red
```

Expected: FAIL because `backend.runtime_paths` does not exist and the clean storage layout is incomplete.

- [ ] **Step 4: Implement the minimal boundary**

Create `backend/runtime_paths.py` with this public shape:

```python
from __future__ import annotations

import os
from pathlib import Path

MUTABLE_ROOTS = frozenset({"data", "storage", "logs", "RAG_Content", "artifacts"})


class MutablePathError(ValueError):
    pass


def mutable_path(relative: str | Path) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute():
        raise MutablePathError("mutable path must be relative")
    if not candidate.parts or candidate.parts[0] not in MUTABLE_ROOTS:
        raise MutablePathError("mutable path must use a registered mutable root")
    state = os.getenv("LES_WINDOWS_STATE_ROOT", "").strip()
    return Path(state).joinpath(*candidate.parts) if state else candidate


def mutable_root(name: str) -> Path:
    return mutable_path(name)
```

Add `storage/artifacts` and `storage/artifacts/files` to `REQUIRED_DIRS`; keep `path.resolve().mkdir(...)` in `ensure_dirs()` so Windows creates through the real junction target during compatibility initialization.

- [ ] **Step 5: Route import-time startup stores through the boundary**

Replace only mutable default paths in the listed files, for example:

```python
from backend.runtime_paths import mutable_path

artifact_revision_store = ArtifactRevisionStore(
    mutable_path("storage/artifacts/meta.db"),
    mutable_path("storage/artifacts/files"),
)
```

Use the same boundary for chat workbook storage, diagnostics logs, and Sovushka proxy logs. Do not change explicit caller-provided absolute paths.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run:

```powershell
uv run pytest tests/test_runtime_paths.py tests/test_install_les.py tests/test_artifact_revision_service.py tests/test_installer_windows.py -q --basetemp=.test-tmp/state-path-green
```

Expected: all tests pass, including the real Programs+junction behavior test.

- [ ] **Step 7: Commit the boundary**

```powershell
git add backend/runtime_paths.py tools/install_les.py tests/test_runtime_paths.py tests/test_install_les.py proxy/routers/artifacts.py proxy/routers/chat.py backend/diagnostics.py sovushka/state.py tests/test_artifact_revision_service.py tests/test_installer_windows.py
git commit -m "fix(windows): route mutable startup paths to state"
```

---

### Task 2: Migrate product-owned mutable defaults and add an architecture gate

**Files:**
- Create: `tests/test_mutable_path_architecture.py`
- Modify: `proxy/routers/bor.py`
- Modify: `proxy/routers/datasets.py`
- Modify: `proxy/routers/checklist_review.py`
- Modify: `proxy/routers/files.py`
- Modify: `proxy/routers/doc_review.py`
- Modify: `proxy/routers/documents.py`
- Modify: `proxy/routers/field.py`
- Modify: `proxy/routers/notebooks.py`
- Modify: `proxy/routers/normcontrol.py`
- Modify: `proxy/routers/mail.py`
- Modify: `proxy/routers/lsr.py`
- Modify: `proxy/routers/kac.py`
- Modify: `proxy/routers/runtime.py`
- Modify: `proxy/services/candidate_acceptance_service.py`
- Modify: `proxy/services/bor_service.py`
- Modify: `proxy/services/colbert_generation_service.py`
- Modify: `proxy/services/context_memory_service.py`
- Modify: `proxy/services/construction_harness_service.py`
- Modify: `proxy/services/doc_review_service.py`
- Modify: `proxy/services/fgis_update_service.py`
- Modify: `proxy/services/fgis_price_service.py`
- Modify: `proxy/services/fsem_machinist_service.py`
- Modify: `proxy/services/forms_service.py`
- Modify: `proxy/services/gesn_api_service.py`
- Modify: `proxy/services/gesn_fgis_service.py`
- Modify: `proxy/services/gesn_service.py`
- Modify: `proxy/services/gesn_update_service.py`
- Modify: `proxy/services/harvest_service.py`
- Modify: `proxy/services/incoming_control_service.py`
- Modify: `proxy/services/les_action_service.py`
- Modify: `proxy/services/list_office_service.py`
- Modify: `proxy/services/mail_query_service.py`
- Modify: `proxy/services/mail_sync_service.py`
- Modify: `proxy/services/notebook_service.py`
- Modify: `proxy/services/notebook_study_service.py`
- Modify: `proxy/services/normcontrol_service.py`
- Modify: `proxy/services/plan_fact_service.py`
- Modify: `proxy/services/project_document_registry_service.py`
- Modify: `proxy/services/project_pdf_extract_service.py`
- Modify: `proxy/services/project_summary_service.py`
- Modify: `proxy/services/project_table_registry_service.py`
- Modify: `proxy/services/raptor_publication_service.py`
- Modify: `proxy/services/reconcile_service.py`
- Modify: `proxy/services/runtime_config_registry_service.py`
- Modify: `proxy/services/rag_advanced_policy_service.py`
- Modify: `proxy/services/smeta_chat_application_service.py`
- Modify: `proxy/services/smeta_norm_store.py`
- Modify: `proxy/services/spec_to_bor_service.py`
- Modify: `proxy/services/table_query_service.py`
- Modify: `proxy/services/unified_construction_harness_service.py`
- Modify: `proxy/services/verify_service.py`
- Modify: `proxy/services/work_log_service.py`
- Modify: `backend/mail_ingest.py`
- Modify: `backend/qdrant_adapter.py`

**Interfaces:**
- Consumes: `backend.runtime_paths.mutable_path` from Task 1.
- Produces: an AST-based gate that rejects new product-owned literal mutable paths outside `backend/runtime_paths.py` and an explicit legacy allowlist.
- Protected `proxy/smeta_core/**` remains allowlisted and unchanged.

- [ ] **Step 1: Write the failing AST gate**

Create `tests/test_mutable_path_architecture.py` to parse Python files and report calls shaped like `Path("storage/...")`, `Path("data/...")`, `Path("logs/...")`, `Path("artifacts/...")`, or `Path("RAG_Content/...")`. The literal allowlist is limited to:

```python
ALLOWLIST_PREFIXES = (
    "proxy/smeta_core/",
)
ALLOWLIST_READ_ONLY = {
    "proxy/services/native_open_service.py",
    "backend/mail_ingest.py",
}
```

The test must report `file:line:literal` for every violation and assert the list is empty.

- [ ] **Step 2: Run the architecture test and verify RED**

Run:

```powershell
uv run pytest tests/test_mutable_path_architecture.py -q --basetemp=.test-tmp/mutable-architecture-red
```

Expected: FAIL listing the exact remaining product-owned mutable literals.

- [ ] **Step 3: Migrate routers and services mechanically**

For every violation in the listed files, replace the relative literal at its ownership boundary:

```python
from backend.runtime_paths import mutable_path

_STORAGE_ROOT = mutable_path("storage/datasets")
_OUT_DIR = mutable_path("storage/checklist_review")
OUTPUT_DIR = mutable_path("data/forms_out")
```

Keep function parameters that intentionally accept caller-supplied paths unchanged. Do not replace read-only `relative_to(Path("RAG_Content"))` comparisons; those remain in `ALLOWLIST_READ_ONLY` because they describe a logical document reference, not directory ownership.

- [ ] **Step 4: Run architecture and affected behavior tests**

Run:

```powershell
uv run pytest tests/test_mutable_path_architecture.py tests/test_datasets_router.py tests/test_mail_router.py tests/test_sovushka_chat.py tests/test_runtime_router.py tests/test_rag_advanced_policy_service.py -q --basetemp=.test-tmp/mutable-architecture-green
```

Expected: all tests pass and the violation report is empty.

- [ ] **Step 5: Commit the migration**

```powershell
git add backend proxy tests/test_mutable_path_architecture.py
git commit -m "refactor(runtime): enforce persistent mutable paths"
```

---

### Task 3: Programs-shaped prebundle smoke

**Files:**
- Create: `tools/windows_prebundle_smoke.py`
- Create: `tests/test_windows_prebundle_smoke.py`
- Modify: `tools/build_tauri_app.py`
- Modify: `tests/test_installer_windows.py`

**Interfaces:**
- Produces: `run_prebundle_smoke(runtime_root: Path, *, timeout_seconds: int = 300) -> dict[str, object]`.
- Produces CLI: `uv run python tools/windows_prebundle_smoke.py --runtime-root PATH --timeout-seconds 300`.
- Success result includes `ok`, `runtime_root`, `state_root`, `proxy_port`, `ui_port`, `proxy_pid`, and `ui_pid`.
- Failure raises `PrebundleSmokeError` containing bootstrap code, message, and bounded log tail.

- [ ] **Step 1: Write failing orchestration tests**

In `tests/test_windows_prebundle_smoke.py`, use a fake staged runtime whose PowerShell bootstrap writes deterministic `bootstrap-status.json` and `windows-light-state.json`. Assert that the runner:

```python
def test_prebundle_smoke_uses_programs_shaped_runtime_and_isolated_state(fake_runtime):
    result = run_prebundle_smoke(fake_runtime, timeout_seconds=20)
    assert result["ok"] is True
    assert "Programs" in result["runtime_root"]
    assert result["state_root"] != str(Path(os.environ["LOCALAPPDATA"]) / "LES")


def test_prebundle_smoke_surfaces_bootstrap_failure(fake_failed_runtime):
    with pytest.raises(PrebundleSmokeError, match="services_api_not_ready"):
        run_prebundle_smoke(fake_failed_runtime, timeout_seconds=20)
```

The fixture must create real files and execute a real child process; only network health responses may use a local temporary HTTP server.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
uv run pytest tests/test_windows_prebundle_smoke.py -q --basetemp=.test-tmp/prebundle-red
```

Expected: FAIL because the runner does not exist.

- [ ] **Step 3: Implement the standalone prebundle runner**

The implementation must:

```python
programs = Path(os.environ["LOCALAPPDATA"]) / "Programs"
test_root = programs / f"LES-prebundle-smoke-{uuid.uuid4().hex}"
runtime = test_root / "runtime"
state = test_root / "state"
```

Copy the staged runtime without following reparse points, launch `bootstrap.ps1` with `LES_RELEASE_SMOKE=1`, `LES_RELEASE_SMOKE_DISABLE_DOCKER=1`, `LES_TAURI_SHELL=1`, and the isolated `LES_WINDOWS_STATE_ROOT`, then poll terminal bootstrap status. Verify API/UI HTTP readiness and direct `python.exe`/`pythonw.exe` process identity. In `finally`, stop only the PIDs/ports recorded in the isolated state and remove only `test_root` after confirming it is below the exact Programs parent and begins with `LES-prebundle-smoke-`.

- [ ] **Step 4: Insert the gate before npm/Tauri**

In `tools/build_tauri_app.build`, preserve this order:

```python
count = stage_runtime(...)
if os.sys.platform.startswith("win"):
    run_prebundle_smoke(RESOURCES / "runtime")
subprocess.run([npm_executable(), "run", "tauri", ...], check=True)
```

The builder must not expose a release-mode skip flag. Unit tests may inject the runner callable into `build()` to avoid running a live smoke during ordinary hermetic tests.

- [ ] **Step 5: Run focused tests and one live staged-runtime smoke**

Run:

```powershell
uv run pytest tests/test_windows_prebundle_smoke.py tests/test_installer_windows.py -q --basetemp=.test-tmp/prebundle-green
uv run python tools/windows_prebundle_smoke.py --runtime-root desktop/tauri/src-tauri/resources/runtime --timeout-seconds 300
```

Expected: tests pass; live JSON reports `ok: true`, live proxy/UI PIDs, and an isolated Programs/state root that is removed after shutdown.

- [ ] **Step 6: Commit the prebundle gate**

```powershell
git add tools/windows_prebundle_smoke.py tools/build_tauri_app.py tests/test_windows_prebundle_smoke.py tests/test_installer_windows.py
git commit -m "feat(windows): gate runtime before NSIS packaging"
```

---

### Task 4: Dependency-only offline cache fingerprint

**Files:**
- Modify: `tools/build_tauri_app.py`
- Modify: `tests/test_installer_windows.py`
- Modify: `installers/windows/app/bootstrap.ps1`

**Interfaces:**
- Produces: `windows_dependency_fingerprint(lock_path: Path, *, extra: str, contracts: Sequence[Path]) -> str`.
- The normalized lock keeps all fields but replaces only the editable root package version with `"<local-project-version>"`.
- `uv-cache-contract.json` keeps `lock_sha256` and adds `dependency_fingerprint` plus `fingerprint_schema = "les.windows-dependency-fingerprint.v1"`.

- [ ] **Step 1: Write failing fingerprint tests**

Use two synthetic lock files that differ only in the editable `les-v2` version and assert equal fingerprints. Add separate cases changing a registry package version, selected extra, Python contract hash, and uv contract hash; each must produce a different fingerprint.

```python
def test_windows_cache_fingerprint_ignores_only_local_project_version(tmp_path):
    first = write_lock(tmp_path / "a.lock", local_version="0.29.1", qdrant="1.18.0")
    second = write_lock(tmp_path / "b.lock", local_version="0.29.2", qdrant="1.18.0")
    assert fingerprint(first) == fingerprint(second)


def test_windows_cache_fingerprint_changes_with_dependency(tmp_path):
    first = write_lock(tmp_path / "a.lock", local_version="0.29.1", qdrant="1.18.0")
    second = write_lock(tmp_path / "b.lock", local_version="0.29.1", qdrant="1.19.0")
    assert fingerprint(first) != fingerprint(second)
```

- [ ] **Step 2: Run fingerprint tests and verify RED**

Run:

```powershell
uv run pytest tests/test_installer_windows.py -k "cache_fingerprint" -q --basetemp=.test-tmp/cache-fingerprint-red
```

Expected: FAIL because the dependency fingerprint does not exist.

- [ ] **Step 3: Implement deterministic normalization**

Parse `uv.lock` with `tomllib`, locate the single package whose source is `{editable = "."}`, replace only its `version`, then hash canonical JSON plus the exact extra and contract bytes:

```python
payload = tomllib.loads(lock_path.read_text(encoding="utf-8"))
editable = [p for p in payload["package"] if p.get("source") == {"editable": "."}]
if len(editable) != 1:
    raise RuntimeError("expected one editable root package in uv.lock")
editable[0]["version"] = "<local-project-version>"
```

Use the resulting digest only for the persistent release-cache filename. Continue embedding and validating the full `lock_sha256` so the installed environment remains exact.

Build the reusable archive with `uv sync --no-install-project`: third-party wheels and build
requirements are cached, while the editable LES package is always built from the staged runtime.
After creating the archive, run one full `uv sync --locked --offline` against a fresh temporary
environment to prove the cache can install the staged local project without network access.

- [ ] **Step 4: Verify cache reuse without building NSIS**

Stage two temporary runtimes with synthetic version-only lock changes and the same supplied cache archive. Assert `stage_windows_uv_cache()` reports the same dependency fingerprint and valid, different full lock hashes. Then change a third-party package and assert a new cache filename is selected.

Run:

```powershell
uv run pytest tests/test_installer_windows.py -k "uv_cache or cache_fingerprint" -q --basetemp=.test-tmp/cache-fingerprint-green
```

Expected: all selected tests pass without Tauri or NSIS execution.

Add a bootstrap contract test requiring `fingerprint_schema` and a 64-character
`dependency_fingerprint`. `Resolve-UvCache` must reject a missing or malformed fingerprint while
continuing to verify the exact full `lock_sha256` and archive SHA-256 before extraction.

- [ ] **Step 5: Commit the cache fix**

```powershell
git add tools/build_tauri_app.py installers/windows/app/bootstrap.ps1 tests/test_installer_windows.py
git commit -m "perf(windows): reuse dependency cache across version bumps"
```

---

### Task 5: Documentation, version, and full offline gates

**Files:**
- Modify: `config/version.json`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `desktop/tauri/package.json`
- Modify: `desktop/tauri/package-lock.json`
- Modify: `desktop/tauri/src-tauri/Cargo.toml`
- Modify: `desktop/tauri/src-tauri/Cargo.lock`
- Modify: `desktop/tauri/src-tauri/tauri.conf.json`
- Modify: `docs/ALGO-windows-lifecycle.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `docs/RELEASE_LEDGER.md`
- Modify: `docs/SOFTWARE_VERSIONS.md`
- Modify: `docs/VERSIONING.md`
- Modify: `docs/TEST_INVENTORY.md`

**Interfaces:**
- Consumes every gate from Tasks 1–4.
- Produces exact release identity `0.29.2 / 628 / 5.1.628`.

- [ ] **Step 1: Update the canonical version contract**

Set `config/version.json` to:

```json
{
  "schema": "les.version.v1",
  "product_version": "0.29.2",
  "build_number": 628,
  "desktop_version": "5.1.628",
  "harness_schema_version": "0.24"
}
```

Run `uv lock` only to synchronize the local editable package version, then run `uv run python tools/sync_version_contract.py` for derived surfaces.

- [ ] **Step 2: Update canonical lifecycle documentation**

Document these exact contracts:

- mutable directory ownership uses `backend.runtime_paths`;
- Programs+junction behavior is a Windows acceptance boundary;
- prebundle smoke precedes NSIS;
- dependency fingerprint ignores only the editable LES version;
- exact installed smoke and hard rollback remain mandatory.

Update the `install` and `ops/test` MODULE_INDEX rows and add the `0.29.2 / build 628` ledger entry. Do not claim production deployment yet.

- [ ] **Step 3: Run focused Windows and version gates**

```powershell
uv run pytest tests/test_runtime_paths.py tests/test_mutable_path_architecture.py tests/test_install_les.py tests/test_windows_prebundle_smoke.py tests/test_installer_windows.py tests/test_software_versions.py -q --basetemp=.test-tmp/windows-cycle
git diff --check
```

Expected: all tests pass and no whitespace errors.

- [ ] **Step 4: Run repository gates**

```powershell
make verify
make test
```

Expected: `make verify` collects the current canonical suite; `make test` passes all 920-or-more collected behavior tests with only documented upstream deprecation warnings.

- [ ] **Step 5: Run Tauri compile without bundling**

```powershell
uv run python tools/platform_release_gate.py tauri-compile
```

Expected: Cargo/Tauri compile succeeds for desktop `5.1.628` without NSIS compression.

- [ ] **Step 6: Commit release metadata and docs**

```powershell
git add config/version.json pyproject.toml uv.lock desktop/tauri docs/ALGO-windows-lifecycle.md docs/MODULE_INDEX.md docs/RELEASE_LEDGER.md docs/SOFTWARE_VERSIONS.md docs/VERSIONING.md docs/TEST_INVENTORY.md
git commit -m "chore(release): prepare LES 0.29.2 build 628"
```

---

### Task 6: One final installer, exact smoke, and Legion full-mode update

**Files:**
- Build output: `dist/LES-Setup.exe`
- Runtime status: `%LOCALAPPDATA%\LES\logs\windows-light-state.json`
- Update status: `%LOCALAPPDATA%\LES\artifacts\updates\hard-update-status.json`
- Modify after success: `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes committed head, verified baseline archive, prebundle smoke, exact-installer smoke, and `tools/windows_update_engine.py` through `tools/windows_production_deploy.ps1`.
- Produces a running installed `full` runtime with exact version/build/commit identity.

- [ ] **Step 1: Confirm the source tree and production baseline**

```powershell
git status --short
git rev-parse HEAD
Invoke-RestMethod http://127.0.0.1:8050/api/version | ConvertTo-Json -Depth 6
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8051/healthz | Select-Object StatusCode
```

Expected: source tree is clean; production still reports `0.28.2 / build 589` before replacement; UI returns 200.

- [ ] **Step 2: Build exactly once**

```powershell
$env:LES_SMETA_BASELINE_ARCHIVE='C:\Users\Oleg\les_rag\dist\LES-smeta-baseline.zip'
uv run python tools/build_windows_installer.py --version 0.29.2 --build-number 628
Get-FileHash -LiteralPath dist\LES-Setup.exe -Algorithm SHA256
```

Expected: prebundle smoke reports green before NSIS starts; one final `dist/LES-Setup.exe` and SHA-256 are produced.

- [ ] **Step 3: Run exact installed smoke in a unique isolated root**

Silently install the exact artifact below a GUID-qualified `%LOCALAPPDATA%\LES-release-smoke\...\app`, set a sibling isolated state root, then run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools\windows_release_smoke.ps1 `
  -RuntimeRoot $IsolatedRuntime -StateRoot $IsolatedState -ExpectedVersion 0.29.2
```

Expected: two bootstraps reach terminal ready, second reports `environment_action=skipped`, API/UI and process contracts pass, and smoke cleanup succeeds.

- [ ] **Step 4: Apply the same SHA-256-verified installer with rollback**

Create a `les.windows-hard-update.v1` job containing exact installer path/hash, install root `%LOCALAPPDATA%\Programs\LES`, state root `%LOCALAPPDATA%\LES`, version `0.29.2`, build `628`, desktop `5.1.628`, and the exact 40-character HEAD commit. Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools\windows_production_deploy.ps1 -Job $JobPath
```

Expected: application tree replacement succeeds; on any failure the updater restores the prior application tree and leaves state intact.

- [ ] **Step 5: Verify full mode from a fresh shell**

Check:

```powershell
Invoke-RestMethod http://127.0.0.1:8050/api/version | ConvertTo-Json -Depth 8
Invoke-RestMethod http://127.0.0.1:8050/api/health | ConvertTo-Json -Depth 8
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8051/healthz | Select-Object StatusCode
Get-Content -LiteralPath "$env:LOCALAPPDATA\LES\logs\windows-light-state.json" -Raw
```

Expected: exact `0.29.2 / 628 / HEAD`, `runtime_alignment=true`, mode `full`, live direct Python proxy/UI PIDs, API available, and UI 200. Qdrant/model availability is reported truthfully as ready or degraded and is not fabricated.

- [ ] **Step 6: Record the actual deployment and commit**

Update `docs/RELEASE_LEDGER.md` with the observed installed commit, installer SHA-256, API/UI result, mode, and any real degraded external capability. Then:

```powershell
git add docs/RELEASE_LEDGER.md
git commit -m "docs(release): record Legion 0.29.2 deployment"
git status --short
```

Expected: clean source tree and a ledger that matches `/api/version`; no push, merge, tag, or public release is performed.
