# GitHub Release Update Channel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship GitHub Releases as the default fail-closed source for lightweight LES patches, with full installer builds only on deterministic hard-boundary changes.

**Architecture:** Reuse the existing content-addressed patch builder/apply engine, replace VPS discovery/publication with immutable GitHub release assets, and add a structural release classifier ahead of expensive work. `0.28.2` delivers the client in a full installer; later compatible SemVer releases use the same updater without NSIS or dependency rebuilds.

**Tech Stack:** Python 3.12–3.13, httpx/urllib, GitHub CLI, PowerShell 5.1, Git, pytest, existing Windows update engine.

**Spec:** `docs/superpowers/specs/2026-08-25-github-release-update-channel-design.md`

## Global Constraints

- Default repository is exactly `proovcme/les_rag_public`; default discovery URL is `https://github.com/proovcme/les_rag_public/releases/latest/download/les-update.json`.
- No dependency additions, background installation, VPS fallback, user-state mutation or package-network sync.
- Published GitHub assets/tags are immutable; corrections use a newer release.
- Unknown or structurally non-version-only paths force `full` before expensive build work.
- Every task uses red test → minimal implementation → focused green test → commit.

---

### Task 1: Deterministic patch/full classifier

**Files:**
- Create: `tools/release_classification.py`
- Create: `tests/test_release_classification.py`
- Modify: `tools/vps_patch.py`

**Interfaces:**
- Produces: `classify_release(base: str, target: str, *, root: Path) -> ReleaseClassification`
- Produces: `ReleaseTrigger(path: str, reason: str)`
- Produces: `ReleaseClassification(kind: Literal["patch", "full"], runtime_files: tuple[str, ...], triggers: tuple[ReleaseTrigger, ...], ignored_version_surfaces: tuple[str, ...])`
- Consumes later: Tasks 3 and 5 use the returned `kind`, `runtime_files` and `triggers` without recomputing policy.

- [ ] **Step 1: Write failing classification tests**

```python
def test_version_only_pyproject_is_patch(repo):
    result = classify_release(repo.base, repo.version_only, root=repo.root)
    assert result.kind == "patch"
    assert "pyproject.toml" in result.ignored_version_surfaces

def test_dependency_or_bootstrap_change_is_full(repo):
    for target in (repo.dependency_change, repo.uv_lock_change, repo.bootstrap_change):
        result = classify_release(repo.base, target, root=repo.root)
        assert result.kind == "full"
        assert result.triggers
```

- [ ] **Step 2: Run tests and retain the expected import failure**

Run: `uv run pytest tests/test_release_classification.py -q`
Expected: FAIL because `tools.release_classification` does not exist.

- [ ] **Step 3: Implement structural validators and classifier**

Parse TOML/JSON with the standard library and existing project utilities. Compare
documents after replacing only the contract-owned version fields with one sentinel.
Treat `uv.lock`, `installers/windows/app/**`, native sources, migrations, baseline
payload and every unknown path as `full`; never reuse the current broad desktop skip.

```python
@dataclass(frozen=True)
class ReleaseTrigger:
    path: str
    reason: str

@dataclass(frozen=True)
class ReleaseClassification:
    kind: Literal["patch", "full"]
    runtime_files: tuple[str, ...]
    triggers: tuple[ReleaseTrigger, ...]
    ignored_version_surfaces: tuple[str, ...]

def classify_release(base: str, target: str, *, root: Path) -> ReleaseClassification:
    changes = changed_paths(base, target, root=root)
    return classify_changed_paths(changes, base=base, target=target, root=root)
```

- [ ] **Step 4: Route `_automatic_patch_files` through the classifier**

Return `runtime_files` only when `kind == "patch"`; otherwise raise an error that
lists every exact trigger path/reason.

- [ ] **Step 5: Run focused tests**

Run: `uv run pytest tests/test_release_classification.py tests/test_vps_patch.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/release_classification.py tools/vps_patch.py tests/test_release_classification.py tests/test_vps_patch.py
git commit -m "feat(release): classify lightweight and full updates"
```

### Task 2: GitHub feed and client trust boundary

**Files:**
- Modify: `proxy/services/update_service.py`
- Modify: `tests/test_update_service.py`
- Modify: `tests/test_vps_patch.py`

**Interfaces:**
- Produces: `GITHUB_UPDATE_FEED_SCHEMA = "les.github-update-feed.v1"`
- Produces: `GITHUB_PATCH_MANIFEST_URL`
- Produces: `_trusted_github_update_url(url: str, *, asset: bool = False) -> bool`
- Consumes: existing `_download`, patch manifest validation and detached apply job.

- [ ] **Step 1: Replace VPS-origin tests with GitHub trust tests**

```python
def test_default_patch_feed_is_exact_public_github_release():
    assert update_service.GITHUB_PATCH_MANIFEST_URL == (
        "https://github.com/proovcme/les_rag_public/"
        "releases/latest/download/les-update.json"
    )

@pytest.mark.parametrize("url", [
    "https://example.invalid/releases/latest/download/les-update.json",
    "http://github.com/proovcme/les_rag_public/releases/latest/download/les-update.json",
    "https://github.com/other/les_rag_public/releases/latest/download/les-update.json",
])
def test_foreign_or_insecure_update_urls_are_rejected(url):
    assert not update_service._trusted_github_update_url(url)
```

- [ ] **Step 2: Run focused tests and confirm red**

Run: `uv run pytest tests/test_update_service.py tests/test_vps_patch.py -q`
Expected: FAIL on missing GitHub patch constants/policy.

- [ ] **Step 3: Implement GitHub discovery validation**

Validate schema, exact repository, tag `v<product_version>`, monotonic build,
release class, target commit, compatible bases, tag-specific asset URL, bytes and
SHA-256. Preserve an explicit environment override for isolated tests but apply
the same schema/hash/path validation.

```python
GITHUB_UPDATE_FEED_SCHEMA = "les.github-update-feed.v1"
GITHUB_PATCH_MANIFEST_URL = (
    "https://github.com/proovcme/les_rag_public/"
    "releases/latest/download/les-update.json"
)

def validate_github_update_feed(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema") != GITHUB_UPDATE_FEED_SCHEMA:
        raise UpdateError("Неподдерживаемая схема обновления")
    if payload.get("repository") != "proovcme/les_rag_public":
        raise UpdateError("Обновление относится другому репозиторию")
    version = str(payload.get("product_version") or "")
    if payload.get("tag") != f"v{version}":
        raise UpdateError("Версия и тег обновления не совпадают")
    return payload
```

- [ ] **Step 4: Make channel failure non-destructive**

Return `update_channel_unavailable` before scheduling the helper when discovery,
redirect, download or manifest validation fails. Remove the default
`https://les.ovc.me/updates/latest.json` path and any automatic fallback.

- [ ] **Step 5: Run focused tests**

Run: `uv run pytest tests/test_update_service.py tests/test_vps_patch.py tests/test_windows_application_update.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add proxy/services/update_service.py tests/test_update_service.py tests/test_vps_patch.py tests/test_windows_application_update.py
git commit -m "feat(updates): trust GitHub release patch assets"
```

### Task 3: Build GitHub release assets

**Files:**
- Modify: `tools/vps_patch.py`
- Create: `tools/github_patch_release.py`
- Create: `tests/test_github_patch_release.py`
- Modify: `Makefile`

**Interfaces:**
- Produces: `build_github_patch_release(base: str, target: str, output: Path, *, full_feed: Path) -> dict[str, Any]`
- Produces assets: `les-update.json`, legacy `latest.json`, `les-patch.zip`, `les-patch.zip.sha256`, `release-notes.md`
- Consumes: Task 1 classification and existing `build_patch` archive format.

- [ ] **Step 1: Write an exact asset-set test**

```python
def test_patch_release_builds_no_installer(tmp_path, git_fixture):
    result = build_github_patch_release(
        git_fixture.base,
        git_fixture.target,
        tmp_path,
        full_feed=git_fixture.full_feed,
    )
    assert set(path.name for path in tmp_path.iterdir()) == {
        "les-update.json", "latest.json", "les-patch.zip",
        "les-patch.zip.sha256", "release-notes.md"
    }
    assert result["release_class"] == "patch"
    assert not (tmp_path / "LES-Setup.exe").exists()
```

- [ ] **Step 2: Run the test and confirm red**

Run: `uv run pytest tests/test_github_patch_release.py -q`
Expected: FAIL because the builder does not exist.

- [ ] **Step 3: Implement the asset builder**

Use tag-specific archive URL
`https://github.com/proovcme/les_rag_public/releases/download/v{version}/les-patch.zip`.
Embed the existing patch manifest, exact release identity, compatible bases,
archive bytes and SHA in `les.github-update-feed.v1`.

```python
feed = {
    "schema": "les.github-update-feed.v1",
    "repository": "proovcme/les_rag_public",
    "release_class": "patch",
    "tag": f"v{contract['product_version']}",
    "target_commit": target,
    "asset": {"url": archive_url, "bytes": archive_size, "sha256": archive_sha},
    "patch": patch_manifest,
}
```

Copy the validated `les.update.v1` identity of the most recent full release into
legacy `latest.json`; its version/commit and installer URLs remain the full base,
not the current patch tag.

- [ ] **Step 4: Add the lightweight make target**

Add `github-patch-release` to `.PHONY` and execute:

```make
github-patch-release:
	uv run python tools/github_patch_release.py $(GITHUB_PATCH_RELEASE_ARGS)
```

- [ ] **Step 5: Run focused tests**

Run: `uv run pytest tests/test_github_patch_release.py tests/test_vps_patch.py tests/test_test_profiles.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/github_patch_release.py tools/vps_patch.py tests/test_github_patch_release.py Makefile tests/test_test_profiles.py
git commit -m "feat(release): build lightweight GitHub patch assets"
```

### Task 4: Isolated apply, rollback and skipped-version gate

**Files:**
- Modify: `tests/test_windows_application_update.py`
- Modify: `tests/test_github_patch_release.py`
- Modify: `tools/github_patch_release.py`

**Interfaces:**
- Consumes: release assets from Task 3 and existing `vps_patch_apply.py` helper.
- Produces: release evidence fields `apply_ok`, `rollback_ok`, `new_file_removed_on_rollback`, `skipped_version_ok`, and per-stage durations.

- [ ] **Step 1: Add failing apply/rollback scenarios**

Create base → intermediate → target commits. Apply target directly to an isolated
base runtime, then inject a health failure and assert rollback restores changed
bytes, removes a target-only `proxy/new_tool.py`, restores the deploy stamp and
starts the previous build.

- [ ] **Step 2: Run focused tests and confirm red evidence fields**

Run: `uv run pytest tests/test_windows_application_update.py tests/test_github_patch_release.py -q`
Expected: FAIL until the release gate records all required evidence.

- [ ] **Step 3: Add the isolated gate**

Make `github_patch_release.py` refuse publication unless the package passes
direct base→target apply and forced rollback. Record stage durations without
imposing a correctness timeout below existing bounded updater timeouts.

```python
evidence = run_isolated_update_gate(base_runtime, assets)
required = ("apply_ok", "rollback_ok", "new_file_removed_on_rollback", "skipped_version_ok")
if not all(evidence.get(name) is True for name in required):
    raise RuntimeError("GitHub patch apply/rollback gate failed")
```

- [ ] **Step 4: Run focused tests**

Run: `uv run pytest tests/test_windows_application_update.py tests/test_github_patch_release.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/github_patch_release.py tests/test_github_patch_release.py tests/test_windows_application_update.py
git commit -m "test(updates): gate GitHub patch apply and rollback"
```

### Task 5: Immutable draft publication

**Files:**
- Modify: `tools/github_patch_release.py`
- Modify: `tests/test_github_patch_release.py`
- Modify: `docs/PUBLICATION_CHECKLIST.md`

**Interfaces:**
- Produces CLI flags: `--publish --notes-file PATH`
- Produces: `publish_github_patch_release(tag: str, assets: Sequence[Path], notes: Path) -> None`
- Consumes: authenticated `gh`, clean pushed commit, assets and evidence from Tasks 3–4.

- [ ] **Step 1: Add command-recording publication tests**

Assert the publisher creates a non-prerelease draft for exact
`v{product_version}`, uploads the five unique assets, downloads them for
verification, then publishes. Assert an
existing tag/release, dirty tree, commit mismatch or missing asset fails before
publication.

- [ ] **Step 2: Run tests and confirm red**

Run: `uv run pytest tests/test_github_patch_release.py -q`
Expected: FAIL because publish flow is absent.

- [ ] **Step 3: Implement draft → verify → publish**

Use `gh release create ... --draft`, `gh release upload`, `gh release download`,
local SHA/internal-manifest verification, then `gh release edit <tag> --draft=false`.
Never use `--clobber`; a published correction requires a higher version.

```python
run(["gh", "release", "create", tag, "--repo", REPOSITORY, "--draft", "--notes-file", notes])
run(["gh", "release", "upload", tag, *asset_paths, "--repo", REPOSITORY])
verify_downloaded_release_assets(tag, expected_assets)
run(["gh", "release", "edit", tag, "--repo", REPOSITORY, "--draft=false"])
```

- [ ] **Step 4: Add immutable-release preflight**

Before production publication, require repository immutability to be enabled and
report `github_release_immutability_required` when it is not. Do not attempt to
change repository settings from the release script.

```bash
gh api repos/proovcme/les_rag_public/immutable-releases
```

- [ ] **Step 5: Run focused tests**

Run: `uv run pytest tests/test_github_patch_release.py tests/test_publication_check.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/github_patch_release.py tests/test_github_patch_release.py docs/PUBLICATION_CHECKLIST.md
git commit -m "feat(release): publish immutable GitHub patch releases"
```

### Task 6: Ship the channel foundation in full release 0.28.2

**Files:**
- Modify: `docs/VPS_PATCH_CHANNEL.md`
- Modify: `docs/ALGO-windows-lifecycle.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `docs/CODE_MAP.md`
- Modify: `docs/TEST_INVENTORY.md`
- Modify: `docs/SOFTWARE_VERSIONS.md`
- Modify: `docs/RELEASE_LEDGER.md`
- Modify: `config/version.json`

**Interfaces:**
- Produces installed base: `0.28.2 / build 589 / desktop 5.1.589`.
- Produces next accepted path: installed `0.28.2` can consume a patch-class `0.28.3` from GitHub.

- [ ] **Step 1: Update canonical documentation**

Rename VPS-channel product language to GitHub update channel, document both
release classes and exact full triggers, and retain VPS material only as
historical migration context.

- [ ] **Step 2: Synchronize version surfaces**

Set `config/version.json` to product `0.28.2`, build `589`, desktop `5.1.589`, then
run `make version-sync`.

- [ ] **Step 3: Run offline and updater gates**

Run: `make verify`
Expected: PASS with the current canonical collection.

Run: `make test`
Expected: PASS.

Run: `make test-updater`
Expected: PASS, including classification, GitHub trust, isolated apply and rollback.

- [ ] **Step 4: Build and accept the one required full installer**

Execute the `0.28.2` full Windows release plan, including two consecutive offline
starts. Verify the installed client resolves the GitHub latest feed but reports
no update when the exact build is current. Publish both `les-update.json` and the
existing legacy `latest.json` alongside the installer/checksum.

- [ ] **Step 5: Verify the next patch without publishing it**

Build a synthetic `0.28.3` Python-only patch against the installed `0.28.2` base,
apply it in the isolated runtime and prove no installer, uv sync or VPS access.
Then emulate an installed `0.28.1` client against the patch release's legacy
`latest.json` and prove it still resolves the `0.28.2` installer.

- [ ] **Step 6: Commit release preparation**

```bash
git add config/version.json pyproject.toml desktop/tauri/package.json desktop/tauri/package-lock.json desktop/tauri/src-tauri/Cargo.toml desktop/tauri/src-tauri/Cargo.lock desktop/tauri/src-tauri/tauri.conf.json docs/VERSIONING.md docs/VPS_PATCH_CHANNEL.md docs/ALGO-windows-lifecycle.md docs/MODULE_INDEX.md docs/CODE_MAP.md docs/TEST_INVENTORY.md docs/SOFTWARE_VERSIONS.md docs/RELEASE_LEDGER.md
git commit -m "release: prepare GitHub update channel in LES 0.28.2"
```
