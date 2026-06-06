# LES Versioning

LES uses SemVer-style product releases for boxed/private builds.

## Private LES

Private release tags use plain SemVer:

```text
vMAJOR.MINOR.PATCH
```

Examples:

```text
v0.1.0
v0.1.1
v0.2.0
```

Rules:

- `MAJOR` changes for incompatible API/runtime contract changes.
- `MINOR` changes for new boxed capabilities, platform support or product
  integrations.
- `PATCH` changes for installer, packaging, docs, regression and runtime fixes.
- After publishing `vX.Y.Z`, `pyproject.toml` should move to the next
  development version, for example `X.Y.(Z+1).dev0`.

## Public Snapshot

Public-safe releases use a descriptive suffix because they are not identical to
the private product release:

```text
vMAJOR.MINOR.PATCH-public-<scope>
```

Examples:

```text
v0.1.1-public-atlas
v0.1.2-public-boxed-install
```

Public releases must not contain `.env`, corpora, indexes, logs, model weights,
private archives, local deployment state or secrets.

## Release Gates

Before a private boxed release:

```bash
uv run pytest -q
uv lock --check
git diff --check
uv run lesctl doctor --profile mac-native
uv run python tools/build_release_artifacts.py --profile mac-native --name les-vX.Y.Z-mac-native
```

For Linux and Windows releases, mark artifacts as `hardware-smoked` only after
they pass on a real matching host. Otherwise use `packaged/not hardware-smoked`
in release notes.

## Current Baseline

- Latest private release: `v0.1.0`.
- Current development version: `0.1.1.dev0`.
- Latest public snapshot release: `v0.1.2-public-boxed-install`.
