# Windows Bootstrap Idempotency Design

**Status:** proposed design, owner review pending
**Target:** planned `0.28.2` patch release

## Goal

Make repeated offline Windows launches boring and deterministic. A usable LES
core must start without Docker/Qdrant, and an already verified Python environment
must not be resolved again merely because the desktop application was opened.

This design addresses two independently observed failures:

1. an optional Docker/Qdrant capability was surfaced as a fatal bootstrap
   failure after the bundled Python environment and baseline had succeeded;
2. a later launch repeated `uv sync --locked --offline`. Because the project
   advertised unbounded future Python support, `uv` evaluated a Python 3.14
   branch which the bundled Python 3.13.12 cache did not contain.

No user data was damaged in either case.

## Product contract

- LES core means the desktop shell, API, UI, profile storage, typed local
  services and diagnostics that do not require an external engine.
- Docker, Qdrant, answer providers and embedding providers are user-managed
  capabilities. Their absence changes capability status; it does not invalidate
  the installed core.
- Search/index operations that require Qdrant fail locally with an actionable
  capability error. They do not turn an otherwise successful launch into a
  broken installation.
- A launch distinguishes at least these operator-visible conditions:
  `docker_engine_unavailable`, `qdrant_unavailable`, and
  `python_environment_invalid`. One generic “installation damaged” message is
  forbidden.
- Reopening the same installed build with the same runtime contract performs a
  health probe and skips dependency synchronization.

This supersedes the older wording in `ALGO-windows-lifecycle.md` that requires
Docker/Qdrant before proxy/UI startup. That document must be corrected in the
implementation change; the provider-neutral `0.28.1` product contract is the
current direction.

## Supported Python range

`pyproject.toml` and the generated `uv.lock` must declare the actually supported
range:

```toml
requires-python = ">=3.12,<3.14"
```

The packaged runtime remains pinned by the release payload (currently Python
3.13.12). The upper bound is a compatibility statement, not a request to add or
remove dependencies. Lock regeneration must produce no Python 3.14 resolution
branch, and the offline cache must be built and tested against the exact shipped
lock and runtime.

## Lock-bound environment marker

After a successful sync and post-sync probe, bootstrap atomically writes a
small versioned marker beside the persistent venv. The marker contains only
reproducible installation identity:

- marker schema version;
- SHA-256 of `uv.lock`;
- normalized `requires-python` value;
- bundled Python version and executable payload identity;
- bundled `uv` version;
- offline-cache contract/hash already verified by bootstrap;
- selected dependency extra (`windows-reranker` or the legacy desktop fallback);
- platform/architecture and installed runtime root identity.

It contains no secrets, user settings or machine-specific mutable health data.
It is written through temporary-file plus atomic replace only after both sync
and probe succeed. A failed sync or failed probe never advances the marker.

## Decision table

| Marker | Venv probe | Bootstrap action |
|---|---|---|
| exact match | healthy | skip `uv sync`; continue startup |
| missing or stale | healthy | run one locked/offline sync, probe, then replace marker |
| any | unhealthy | run one repair sync against the packaged lock/cache, probe, then replace marker |
| exact match | probe cannot execute | report `python_environment_invalid`; one bounded repair attempt is allowed |
| sync/probe still fails | unhealthy | fail core startup with the exact Python-environment diagnostic |

Bootstrap must not recursively delete a usable venv as a normal first action.
If repair requires replacement, it must use a bounded recoverable sibling path
and must never be triggered by Docker/Qdrant failure.

The health probe must prove more than `sys.executable`: it checks the expected
Python version/range and imports the minimal LES startup modules used by the API
and UI. It must remain offline, fast and independent of live providers.

## Optional capability startup

Docker and Qdrant probing happens independently from Python environment
validation:

1. Docker executable absent or engine stopped -> record
   `docker_engine_unavailable` and continue.
2. Docker available but Qdrant cannot be started/reached -> record
   `qdrant_unavailable` and continue.
3. Qdrant available -> expose the RAG/index capability and run its capability
   checks.

The terminal bootstrap state may be `ready` with structured capability warnings.
The API/UI health response must expose those warnings without labelling the
Python installation corrupted. Feature endpoints that need the missing
capability return their own bounded 503/status response.

## Profile text limits

The patch release also closes unbounded user-editable profile fields:

- user-authored skill revision: maximum 8,000 Unicode characters;
- user-authored prompt revision: maximum 16,000 Unicode characters.

These are storage-field limits, not total model-context limits. Factory content,
evidence, working memory and the assembled inference packet use the model preset
and `ContextGovernor` budgets defined for `0.29.0`.

The service layer is authoritative. API schema and UI mirror the same constants;
the editor shows `current / limit`, warns before the limit, and disables save
when over it. Direct service calls, migration/import and API writes cannot bypass
validation. Existing over-limit immutable revisions remain readable for
compatibility but cannot be copied/published unchanged without shortening; the
implementation must report that state explicitly rather than truncate content.

## Release verification

The release payload is accepted only if all of the following pass:

- unit tests for marker identity, atomic write and every decision-table branch;
- static/behavior tests proving Docker and Qdrant failures never call the fatal
  Python-environment path;
- profile service/API/UI tests for exact 8,000/16,000 boundaries and counters;
- lock assertions proving `<3.14` and no Python 3.14 resolution branch;
- an isolated Windows test that installs exclusively from the packaged offline
  cache, reaches ready, stops LES, and launches the same installation a second
  time with network disabled;
- the second launch proves `uv sync` was skipped, the same venv was retained,
  and API/UI became ready;
- the same two-launch scenario with Docker stopped proves core readiness and
  distinct capability warnings;
- `make verify`, `make test`, and the Windows release smoke required by the
  release process.

## Non-goals

- No dependency additions.
- No changes to `proxy/smeta_core/**` or restoration of the removed specialized
  estimate chat route.
- No automatic installation or selection of Docker, Qdrant, Ollama, FreeToken
  or another provider.
- No claim that RAG works while its required Qdrant/embedding capability is
  absent; only LES core remains available.

## Rollback

The marker is an optimization and integrity record, not the environment itself.
An older bootstrap may ignore it. Rolling back the application keeps the
persistent venv and user state; if its lock identity differs, the older/newer
bootstrap performs its normal single locked/offline reconciliation.
