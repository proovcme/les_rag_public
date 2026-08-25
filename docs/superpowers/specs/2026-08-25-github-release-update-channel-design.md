# GitHub Release Update Channel Design

**Status:** approved design, implementation pending
**Target:** full installer release `0.28.2`; default channel for later releases

## Goal

Make GitHub Releases the sole default source for LES Windows updates. Most
releases must publish a small verified patch without rebuilding the three-hour
offline installer. A full `LES-Setup.exe` is reserved for changes that cannot be
safely applied inside the existing runtime contract.

The installed user still initiates every update explicitly. There are no
background installs and no automatic fallback to `les.ovc.me`.

## Release classes

Every shipped product change keeps its SemVer, monotonic build number, exact tag
and release ledger entry. Release class is independent from version numbering:

| Class | GitHub assets | Use when |
|---|---|---|
| `patch` | `les-update.json`, legacy `latest.json`, `les-patch.zip`, `les-patch.zip.sha256`, release notes | all changed runtime files are inside the patch allowlist; dependencies and native/bootstrap contract are unchanged |
| `full` | `les-update.json`, legacy `latest.json`, `LES-Setup.exe`, `LES-Setup.exe.sha256`, release evidence | Python/dependency/offline-cache contract, installer/bootstrap, native Tauri/Rust shell, persistent-state migration or another hard boundary changed |

`0.28.2 / build 589` is necessarily `full`: it installs the repaired bootstrap
and the GitHub patch client. `0.28.3 / build 590` is planned as `patch`: it adds
LSR/VOR Python tools without a new installer.

## GitHub layout

Repository: `proovcme/les_rag_public`.

Discovery uses the documented stable latest-asset URL:

```text
https://github.com/proovcme/les_rag_public/releases/latest/download/les-update.json
```

Every release also carries the existing `latest.json`. On a patch release it is
an exact compatibility pointer to the most recent full release and its
tag-specific installer assets. Thus a pre-`0.28.2` client that checks
`/releases/latest/download/latest.json` can still upgrade to the full `0.28.2`
base even when GitHub's latest release is `0.28.3` or newer. The two discovery
schemas have different names and purposes and are never conflated.

The discovery document contains a tag-specific, immutable archive URL, never a
second `latest` URL:

```text
https://github.com/proovcme/les_rag_public/releases/download/v0.28.3/les-patch.zip
```

The release is assembled as a draft with every asset present, verified, then
published. GitHub release immutability must be enabled before this becomes the
production channel. Assets and tags are never replaced after publication.

Official references:

- <https://docs.github.com/en/repositories/releasing-projects-on-github/linking-to-releases>
- <https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases>

## Feed and trust contract

`les-update.json` uses a new `les.github-update-feed.v1` schema and includes:

- exact repository `proovcme/les_rag_public`;
- release tag, product version, build number and target commit;
- release class `patch|full`;
- minimum compatible installed version/build and exact permitted base commits;
- tag-specific asset URL, byte size and SHA-256;
- embedded `les.vps-patch.v2` runtime manifest for patch releases;
- installer URL/SHA only for full releases.

The client accepts only HTTPS discovery at the exact repository latest-asset
path. Asset redirects are allowed only through GitHub-owned HTTPS release hosts,
with a bounded redirect count. The downloaded bytes must match the manifest
size/SHA and the archive's internal manifest before any process is stopped.
Repository, tag, version, build and target commit must agree at every layer.

GitHub availability failure is explicit `update_channel_unavailable`; it never
damages or stops the installed LES. There is no silent VPS or raw-branch
fallback. An operator/testing environment override remains possible only through
the existing explicit environment setting and retains the same validation.

## Patch classification

The publisher calculates the full Git diff from the installed full-release base
to the target commit.

Patch runtime payload may contain only the existing bounded roots/files accepted
by builder, API and detached helper. New `.py` files under `backend/`, `proxy/`
or `sovushka/` are allowed and are removed on rollback if they did not exist in
the base.

The following are build-only version surfaces. They may be omitted from a patch
only when a structural validator proves that the sole semantic change is the
version copied from `config/version.json`:

- `pyproject.toml`: project `version` only; any `requires-python`, dependency,
  optional-dependency or build-system change forces `full`;
- `desktop/tauri/package.json` and root package-lock version fields only;
- LES package version in `desktop/tauri/src-tauri/Cargo.toml` and `Cargo.lock`;
- `desktop/tauri/src-tauri/tauri.conf.json` version only;
- `docs/VERSIONING.md` and `docs/SOFTWARE_VERSIONS.md` are non-runtime docs.

`uv.lock`, Python contract/cache, `installers/windows/app/**`, Cargo dependency
graph, native sources/binaries, migrations, baseline payload and unknown runtime
paths force `full`. Classification is fail-closed and emits the exact trigger
paths/reasons. It never silently drops an unclassified change.

## Publication transaction

1. Require a clean pushed public release commit and exact version contract.
2. Classify `patch|full` before expensive build work.
3. Run the release-class gates.
4. For `patch`, build the content-addressed archive and test it against an
   isolated copy of the last full Windows runtime, including rollback.
5. Create a draft GitHub Release for the exact tag.
6. Upload all assets and release notes.
7. Download the draft assets, verify size/SHA/internal manifest and tag/commit.
8. Publish once; immutability then prevents mutation.
9. Verify the stable latest discovery URL resolves to the just-published tag.
10. Verify legacy `/latest/download/latest.json` still resolves to the most
    recent full installer from both old and current clients.

Failure before publication deletes the draft or leaves it unpublished. Failure
after publication creates a newer correcting release; published assets/tags are
never overwritten.

## Gates and expected duration

Patch publishing does not build NSIS/Tauri, rebuild the offline dependency cache,
run dependency sync, provision the smeta baseline or reinstall Windows. It still
runs `make verify`, `make test`, update-engine tests, isolated apply/rollback and
the feature-specific acceptance gate.

No hard wall-clock promise is part of correctness. The operational objective is
that package/build/apply publication work completes within 30 minutes on the
release host, excluding an explicitly separate long model-quality benchmark.
The pipeline records durations per stage so regressions are visible.

## Acceptance

- a patch-only change produces no installer and publishes all immutable assets;
- a dependency, `uv.lock`, bootstrap or native change selects `full` before build;
- a version-only `pyproject.toml` change is safely omitted, while any dependency
  change cannot be omitted;
- installed `0.28.2` discovers and applies `0.28.3` from GitHub without VPS,
  network dependency sync or user-state mutation;
- installed `0.28.1` still discovers the full `0.28.2` installer after a later
  patch release becomes GitHub latest;
- corrupted archive, wrong repository/tag/commit, unexpected redirect or unknown
  path fails before stop;
- skipped intermediate patches update directly from the last compatible full
  base, and foreign local edits remain fail-closed;
- apply failure restores changed files, removes newly added files and restarts the
  previous build;
- release docs clearly distinguish `patch` from `full` and show why a full build
  was selected.
