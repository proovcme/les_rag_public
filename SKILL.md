---
name: les
description: Use when developing, operating, testing, packaging, releasing, or troubleshooting LES and Sovushka.
---

# LES operator and developer skill

## Start here

Work from the repository root; never assume a personal absolute path. Read, in order:

1. `AGENTS.md` — safety, current architecture and Definition of Done.
2. `docs/MODULE_INDEX.md` — module ownership and status.
3. `docs/CODE_MAP.md` — request, indexing, desktop and release entry points.
4. The module document linked by `MODULE_INDEX`.
5. `docs/SOFTWARE_VERSIONS.md` and `docs/RELEASE_LEDGER.md` for a release.

For Sovushka UI work also read `skills/sovushka-ui/SKILL.md` and
`docs/modules/sovushka-uikit.md` before editing. Do not read `.env`, credentials,
runtime data, logs, model caches or private corpora.

## Product contract

- LES is a local construction evidence harness. A model interprets and connects evidence; code
  calculates, validates structure and preserves provenance.
- Every searchable dataset uses the shared contract-versioned Qdrant collection with named
  `dense + bm25_sparse`, native RRF and context expansion. Optional reranking must never erase
  native-RRF results.
- Do not add query hardcodes, dataset-specific boosts or professional answers implemented in code.
- Typed readers and calculators return exact evidence; they do not choose an engineering or
  estimating decision for the model.
- The active estimator path is attachment + selected dataset → model-authored queries → shared RAG
  → the same model's result → calculation/XLSX packaging. `proxy/smeta_core/document_workflow.py`
  is historical/experimental compatibility code, not the product chat core.

## Runtime surfaces

| Surface | Default | Purpose |
|---|---:|---|
| Proxy | `http://127.0.0.1:8050` | API and application services |
| Sovushka | `http://127.0.0.1:8051` | NiceGUI user/admin interface |
| Qdrant | `http://127.0.0.1:6333` | optional local vector store |
| MLX host | `http://127.0.0.1:8080` | optional macOS model host |

Always read effective runtime state through `/api/version`, health endpoints and the GUI. Do not infer
deployment state from the working tree or an old note.

## Windows public release

The public Windows artifact is a per-user Tauri/NSIS `LES-Setup.exe`.

- Replaceable application: `%LOCALAPPDATA%\Programs\LES`.
- Persistent state: `%LOCALAPPDATA%\LES`.
- The installer contains SHA-256-verified portable Python, `uv.exe`, the exact `uv.lock`, and an
  offline Windows dependency cache created from that lock. Bootstrap must not use system Python,
  system `uv`, winget or a network package fallback.
- Ollama, FreeToken, Lemonade, OpenAI-compatible APIs, Docker Desktop and Qdrant are external
  user-managed components. Their absence is a visible capability warning, not an installation or
  core-start failure.
- Generation, embeddings and vector storage are independent roles. Never silently choose a
  provider or model.
- The setup surface is a status/catalogue screen. `start_from_setup` depends only on the LES core.
- Mutable state and user documents never enter the replaceable application tree or a release asset.

Primary implementation:

- `tools/build_tauri_app.py` — stage platform payload and offline dependency cache.
- `installers/windows/app/bootstrap.ps1` — verify and materialize the bundled runtime.
- `installers/windows/state.ps1` — persistent-state boundary and junctions.
- `desktop/tauri/src-tauri/src/lib.rs` — native lifecycle and provider status probes.
- `desktop/tauri/web/{index.html,wizard.js}` — provider-neutral setup catalogue.
- `tools/windows_release_smoke.ps1` — installed-artifact acceptance.

User recovery is documented in `docs/public/windows-troubleshooting.md`; the only current public
release procedure is `docs/RELEASE_PROCEDURE.md`.

## External providers

LES may connect to Ollama, FreeToken, Lemonade or a compatible remote API. The user owns installation,
model selection, licences and resource limits. An answer provider does not automatically provide a
compatible embedding endpoint. Show the configured effective value and its source in Sovushka.

When debugging a provider:

1. Check its own health/model endpoint outside LES.
2. Check the effective LES provider, URL, model and context window in Configuration.
3. Check answer and embedding roles separately.
4. Reproduce with a minimal request before changing prompts or retrieval.
5. Preserve the original exception and provider response in diagnostics; do not replace it with a
   generic fallback.

## Common operations

Use the product controls instead of killing broad process classes:

```text
uv run python tools/les_runtime_control.py status
uv run python tools/les_runtime_control.py start
uv run python tools/les_runtime_control.py stop
uv run python tools/les_doctor.py
```

On Windows use checked-in PowerShell/CLI entry points with UTF-8 files and argument lists. Do not pipe
Cyrillic scripts through PowerShell stdin and do not build destructive commands by concatenating
strings. Before changing an installed runtime, dry-run against the resolved
`%LOCALAPPDATA%\Programs\LES` target.

On macOS use the `mac-native` profile and repository scripts. When dependency sync is required,
keep the MLX extra: `uv sync --extra mac-mlx`. macOS is a supported reference/development profile,
not a source of hidden Windows defaults. Linux profiles are documented in `docs/PLATFORMS.md` and
`installers/README.md`.

## Development workflow

1. Narrow scope via `MODULE_INDEX` and `CODE_MAP`; inspect related tests before code.
2. Preserve unrelated dirty worktree changes.
3. Add a regression test first for features and bug fixes.
4. Make the smallest coherent change; no broad exception swallowing or test weakening.
5. Update the module doc and its `MODULE_INDEX` row in the same change.
6. Bump `config/version.json` and run the version synchronizer for a release change.
7. Run focused tests, then the canonical gates.

Canonical local gates:

```text
make verify
make test
```

If `make` is unavailable on Windows, run the exact commands from the corresponding Makefile target.
Use workspace-local pytest temp directories, for example `--basetemp=.test-tmp/<gate>`.

Additional gates are scoped by change:

- UI/Tauri: focused UI tests, `node --check`, `cargo check`.
- Public surface: `make public-check`.
- Windows release: build the real EXE and run installed clean-install smoke.
- Retrieval: focused retrieval tests and a live domain golden only when its user corpus exists.
- Mail: `make test-mail-release` plus the documented live Outlook gate when applicable.

Passing unit tests does not prove an installer. A public Windows release is acceptable only after the
exact `LES-Setup.exe` installs into an isolated location, starts its bundled runtime, reports the
expected `/api/version`, passes API/UI/index/process checks and can be rolled back.

## Versioning and release

`config/version.json` is the only source for product SemVer, monotonic build number and desktop
package version. Keep `docs/SOFTWARE_VERSIONS.md` and `docs/RELEASE_LEDGER.md` synchronized.

Public release has one operator entry point:

```text
make release RELEASE_ARGS='run --host legion --publish'
```

It prepares immutable candidate bytes, installs them on Legion, runs smoke,
controlled rollback and reinstall, then publishes an accepted draft and performs
independent postflight. Do not publish through the internal patch/full adapters.
The exact stages, resume rules and stop conditions are in
`docs/RELEASE_PROCEDURE.md`.

Never publish runtime state, `.env`, credentials, private datasets, logs, caches, local archives or
model weights.

## Data and destructive-action safety

Do not delete or recreate `data/qdrant/`, `data/les_meta_qwen.db`, `storage/`, `RAG_Content/`,
`structured_rules`, installed state or Qdrant volumes without an explicit user request and verified
target. Do not run a full reindex merely to fix one dataset. Prefer dataset integrity inspection and a
bounded repair job. Preserve a known rollback for deploys and schema/index changes.

## Documentation contract

Current documentation follows this chain:

- public start: `README.md`, `docs/public/overview.md`;
- users: `docs/WINDOWS_DESKTOP.md`, `docs/public/windows-troubleshooting.md`;
- developers: `docs/public/developer-guide.md`, `docs/MODULE_INDEX.md`, `docs/CODE_MAP.md`;
- operators/releases: this skill, `docs/RELEASE_PROCEDURE.md`, `docs/INSTALL_RUNBOOK.md`,
  `docs/SOFTWARE_VERSIONS.md`, `docs/RELEASE_LEDGER.md`;
- future work: `ROADMAP_TO_V1.md`.

Historical documents live in `docs/archive/` and are context, not instructions. When code and a
current document disagree, stop, verify the behavior, and update the canonical document with the fix.
