# Release Acceptance Orchestrator Design

## Purpose

A LES release is an installed and accepted artifact, not merely a GitHub tag or
archive. Public publication is the final transition after the exact candidate
has been installed on Legion by the production installer/updater, smoked,
rolled back, installed again, and independently verified.

Legion is the mandatory release host until the owner assigns another host. It
is currently allowed to use the primary LES installation because there is no
accepted working production version to preserve. The design keeps the host
adapter replaceable so a separate Windows profile or installation root can be
introduced later without changing the release contract.

## Scope

The orchestrator covers both Windows release classes:

- `patch`: cumulative bounded runtime update from every advertised compatible
  base, delivered through the existing Windows updater;
- `full`: Tauri/NSIS installer required by structural, dependency, bootstrap,
  native shell, baseline, or unknown runtime changes.

macOS may reuse the common artifact and publication contracts later, but the
first implementation does not change the macOS updater. RAG, model behavior,
Qdrant ownership, user datasets, and `proxy/smeta_core/**` are out of scope.

## Non-negotiable release invariant

GitHub publication is forbidden until all of the following refer to the same
source commit and byte-identical artifacts:

1. clean local HEAD and pushed private branch;
2. public `main` candidate source;
3. prepared artifact manifest and SHA-256 values;
4. Legion acceptance receipt;
5. GitHub tag, downloaded assets, and public update feed.

Changing source, version, build number, manifest, archive, installer, checksum,
or release notes after acceptance invalidates the receipt. Publication cannot
be forced past a failed or stale acceptance result.

## Architecture

Create `tools/release_orchestrator.py` as the only public release entry point.
It coordinates existing implementations instead of rebuilding them:

- `release_classification.py` chooses `patch` or `full`;
- `github_patch_release.py` builds and publishes a soft patch;
- `patch_release.py` and Windows PowerShell scripts build/install a full NSIS
  release;
- `vps_patch.py`, `vps_patch_apply.py`, and `windows_update_engine.py` perform
  the production soft-update lifecycle;
- `windows_release_smoke.ps1` and `windows_updater_smoke.ps1` provide installed
  runtime probes.

The existing scripts remain adapters and must not independently claim a public
release. Their publish functions receive the same provenance and acceptance
checks as the orchestrator, so direct invocation fails closed.

## State machine

Each attempt has an immutable `release_id` derived from target commit, product
version, build number, release class, and artifact-manifest SHA. State is stored
under `dist/release-work/<release_id>/release-state.json`.

Valid transitions are:

```text
planned
  -> prepared
  -> legion_installed
  -> legion_smoke_passed
  -> rollback_passed
  -> legion_reinstalled
  -> accepted
  -> draft_uploaded
  -> draft_verified
  -> published
  -> postflight_verified
```

Any failure transitions to `failed` with the failed stage, sanitized command
result, recovery result, and last known Legion identity. A failed attempt cannot
be published. Resume is allowed only when the commit, artifacts, host, starting
identity, and completed-stage evidence still match exactly.

## Commands

The checked-in CLI exposes:

```text
release_orchestrator.py prepare --host legion
release_orchestrator.py accept --release-id <id>
release_orchestrator.py publish --release-id <id>
release_orchestrator.py run --host legion --publish
release_orchestrator.py status --release-id <id>
```

`run` performs the same persisted transitions as the separate commands.
`--publish` is always explicit. Make exposes one canonical wrapper,
`make release`, and the old ambiguous release targets are documented as
internal adapters.

## Prepare gate

Preparation requires a clean pushed branch, synchronized version contract and
generated code runtime map, `make verify`, `make test`, `make test-updater`, and
`make public-check`. The classifier selects the release class automatically and
records every reason. An unknown or protected path always selects or requires a
full release; it never weakens the classifier.

Patch preparation builds a cumulative package from the declared full-release
base and proves isolated apply, skipped-version behavior, explicit deletion,
and byte-exact rollback for every advertised base identity. Full preparation
builds the exact NSIS installer and performs the existing isolated clean-install
smoke. Prepared assets are content-addressed and become read-only inputs to all
later stages.

## Legion acceptance

Acceptance first records the actual installed version, build, deployed commit,
application root, state root, configured capability availability, and bounded
state invariants. The procedure refuses an unexpected starting identity.

The exact prepared candidate is then installed through the same production
path used by the GUI:

- soft patch: updater service, scheduled task, and transactional update engine;
- full release: Tauri/NSIS installer and the normal bootstrap/update engine.

After restart, mandatory smoke verifies:

- exact product version, build, and deployed commit;
- one LES desktop instance and expected direct Python processes;
- proxy `/api/version` and health, Sovushka `/healthz`, and update status;
- persistent application/state boundary and unchanged protected state paths;
- every capability that was available before the update is still available;
- when Qdrant was available before the update, creation, indexing, native-RRF
  retrieval, and cleanup of a uniquely named temporary acceptance dataset;
- a second cold restart with the same identity and health results.

An external component absent before the update is recorded as `N/A`, not
silently installed and not treated as a core failure. An available component
that disappears after the update is a release failure.

The acceptance sequence then performs a controlled rollback to the captured
starting application tree, repeats core identity/API/UI/process checks, and
installs the same candidate a second time. Publication requires the final
candidate installation to be healthy. User state is never restored from a
release archive because it never enters the application transaction.

## Acceptance receipt

`release-receipt.json` is an append-only machine artifact containing:

- release ID, class, version/build, source and base commits;
- SHA-256 and byte size of every candidate asset;
- Legion host identity and starting/final installed identities;
- each state transition with timestamps and bounded durations;
- smoke results, capability continuity, rollback and reinstallation results;
- protected-state boundary evidence;
- overall `accepted: true|false`.

The receipt contains no credentials, environment values, private paths beyond
sanitized install/state role names, document text, dataset names from the user,
or logs. Publication includes the accepted receipt as a release asset and also
binds its SHA-256 in the update feed.

## Publication

Publication requires `accepted: true` and re-hashes all inputs before doing any
GitHub operation. Public `main` must equal the accepted target commit. A draft
release is created with explicit `--target <commit>`, the canonical assets are
uploaded, downloaded into a fresh directory, and compared byte for byte. Only
then is the draft published.

Postflight independently verifies:

```text
accepted commit = private branch = public main = release tag = feed target
accepted asset hashes = downloaded public asset hashes
```

If draft upload or verification fails, the draft remains unpublished and the
attempt is resumable. If publication succeeds but postflight fails, the command
reports a critical immutable-release incident and never marks the attempt
`postflight_verified`.

## Documentation and operator surface

`docs/RELEASE_PROCEDURE.md` becomes the short canonical operator runbook and is
linked from `SKILL.md`, `VERSIONING.md`, `INSTALL_RUNBOOK.md`, `CODE_MAP.md`, and
`MODULE_INDEX.md`. Obsolete release directions in `GUARDRAILS.md` are removed or
redirected. The release ledger records release intent before the tagged commit;
the public receipt records the actual post-publication fact, avoiding a commit
that falsely claims its own future publication.

## Testing and acceptance of the procedure

Unit and integration tests must prove:

- invalid state transitions and stale receipts fail closed;
- source or one-byte artifact drift invalidates acceptance;
- publication cannot run before Legion acceptance and final reinstallation;
- public-main or tag mismatch blocks publication;
- patch and full adapters expose the same receipt contract;
- failure at every mutation stage attempts the correct rollback;
- resume never repeats a completed irreversible transition;
- sanitized receipts cannot contain secrets or user document content.

The procedure itself is accepted only after a non-public rehearsal on Legion:
prepare a candidate, install it, smoke it, roll it back, reinstall it, and stop
before publication. The next public release must then be performed exclusively
through the new orchestrator.

`v0.30.7` is a transitional published candidate: its package simulation and
GitHub provenance are verified, but it does not retroactively satisfy this
design until the same public bytes pass the Legion installed acceptance cycle.
