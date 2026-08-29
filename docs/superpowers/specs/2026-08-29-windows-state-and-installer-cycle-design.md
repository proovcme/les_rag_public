# Windows state paths and installer cycle

Date: 2026-08-29  
Status: proposed, owner-approved direction; written review pending

## Problem

The installed Windows runtime lives below `%LOCALAPPDATA%\Programs\LES`, while mutable LES state
lives below `%LOCALAPPDATA%\LES`. Compatibility junctions expose `data`, `storage`, `logs`,
`RAG_Content`, and `artifacts` below the application tree. On Legion, Windows returns
`ERROR_ALREADY_EXISTS` when Python creates a missing directory through those junctions, although
reads and ordinary file writes work. Existing installations can hide the defect because the
directories already exist; a clean installed smoke exposes it.

The installer build cycle amplifies every failure. `LES-Setup.exe` embeds Python, the offline uv
dependency cache, the local reranker stack, and the verified baseline. The cache key currently
tracks the complete `uv.lock`, so a LES-only version bump invalidates a dependency cache whose
third-party contents did not change. NSIS then recompresses roughly 500 MB before the first real
installed-runtime check.

## Decision

Mutable paths are state-root-owned. Production code must not create directories through an
application-tree junction. A single Windows-aware path boundary resolves mutable roots directly
to `LES_WINDOWS_STATE_ROOT`; junctions remain a legacy compatibility surface for reads and for
already-existing paths, not an ownership API.

The release pipeline gains a prebundle gate. It starts the staged runtime from a Programs-shaped
application path with an isolated state root and proves bootstrap, proxy, and UI readiness before
NSIS compression. The final installed smoke remains mandatory and validates the exact installer
bytes, but it is no longer the first integration test.

The offline cache identity is based on dependency inputs, not the LES package version. It includes
the Python and uv contracts, selected extras, platform, and a normalized third-party dependency
projection. A changed dependency, extra, interpreter, or binary contract invalidates the cache;
changing only `product_version` does not. The local LES package is built from the staged source and
is not treated as a reusable third-party wheel.

## Components

1. **Persistent path boundary**
   - Exposes state-root paths for `data`, `storage`, `logs`, `RAG_Content`, and `artifacts`.
   - Keeps non-Windows and repository development behavior unchanged.
   - Migrates startup-time directory creation and stores that currently use relative mutable paths.
   - Fails visibly if installed Windows code attempts an unregistered mutable root.

2. **Programs+junction acceptance**
   - Uses a unique directory below `%LOCALAPPDATA%\Programs` and a unique isolated state root.
   - Exercises real directory creation and real proxy/UI startup.
   - Never reads or modifies `%LOCALAPPDATA%\LES` production state.
   - Removes only its exact generated paths after processes stop.

3. **Prebundle runtime smoke**
   - Runs after runtime staging and offline-cache preparation, before Tauri/NSIS bundling.
   - Requires bootstrap terminal `ready`, live API, live UI, and console-free direct Python PIDs.
   - A failure stops the build without producing a release installer.

4. **Dependency cache fingerprint**
   - Produces a deterministic manifest explaining every fingerprint input.
   - Reuses the archive for a LES-only version bump.
   - Rebuilds on any third-party resolution or runtime-contract change.
   - Is verified again when bootstrap consumes the archive.

## Flow

1. Synchronize product version surfaces.
2. Stage the exact runtime source.
3. Resolve or build the verified dependency cache using the dependency fingerprint.
4. Run Programs-shaped prebundle smoke against isolated state.
5. Build Tauri/NSIS once.
6. Install the exact artifact into a second isolated root and run installed release smoke twice.
7. Apply the same SHA-256-verified artifact to production through the existing hard-update engine.
8. Verify version, commit, `full` mode, API/UI, process identity, and available capabilities; roll
   back the application tree automatically on failure while preserving state.

## Error handling and rollback

- No prebundle or installed-smoke failure may stop or mutate the production LES instance.
- Production replacement begins only after both gates pass.
- State paths are never part of application-tree rename/delete operations.
- A cache fingerprint mismatch is a build failure, never a network repair during installation.
- Optional Docker, Qdrant, and model capabilities remain explicit degraded states; proxy/UI startup
  is the core gate. Capability-specific acceptance remains separate and truthful.

## Tests and acceptance

- A Windows behavior test reproduces `mkdir` through a junction below `Programs` and proves the
  state-path boundary creates the directory in the real target.
- Startup tests cover every registered mutable root and reject an unregistered relative root.
- Cache tests prove version-only reuse and dependency/runtime invalidation.
- Prebundle smoke proves proxy/UI startup from a clean state before NSIS.
- Existing `make verify`, `make test`, Tauri compile, installed release smoke, and hard-update
  rollback gates remain mandatory.

## Scope

This change does not alter user RAG data, protected smeta algorithms, model routing, retrieval
contracts, or public publication. Splitting the 500 MB installer into optional downloadable packs
is a later release-size project; this design first removes repeated rebuilds and makes the current
offline installer reliable.
