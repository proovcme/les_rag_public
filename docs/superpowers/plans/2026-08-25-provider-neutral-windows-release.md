# Provider-neutral Windows Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish LES 0.28.1 with a self-contained Windows core installer and a provider-neutral dependency/status screen.

**Architecture:** The Windows bundle stages verified Python, uv, and a Windows-specific offline uv cache. Bootstrap starts LES independently of optional model/index engines and exposes their state to a Tauri compatibility catalogue; provider/model configuration remains inside Sovushka.

**Tech Stack:** Python 3.12, uv, PowerShell 5.1, Rust/Tauri 2, static HTML/CSS/JavaScript, pytest, GitHub CLI.

**Spec:** `docs/superpowers/specs/2026-08-25-provider-neutral-windows-release-design.md`

## Global Constraints

- Product version is `0.28.1`; build number is `588`.
- No changes under `proxy/smeta_core/**`.
- Do not add a package, JavaScript, or Markdown-editor dependency.
- Do not install or choose third-party model engines for the user.
- `LES-Setup.exe` must not need preinstalled Python or uv and must not download Python packages at first launch.
- Public `main` and the GitHub Release change only after all local and installed-Windows gates pass.

---

### Task 1: Offline LES core payload

**Files:**
- Modify: `tools/build_tauri_app.py`
- Modify: `installers/windows/app/bootstrap.ps1`
- Modify: `config/windows_python.json`
- Test: `tests/test_tauri_desktop.py`
- Test: `tests/test_installer_windows.py`

**Interfaces:**
- Produces: `stage_windows_uv_cache(runtime: Path, source: Path | None = None) -> int` and `installers/windows/tools/uv-cache-contract.json` in the staged runtime.
- Bootstrap consumes the contract as `UV_CACHE_DIR` and executes `uv sync --locked --offline --python <bundled-python> --no-python-downloads --extra windows-reranker`.

- [ ] Add failing tests which require a verified staged offline cache, `--offline`, and the absence of `Install-Uv`, `winget install --id=astral-sh.uv`, and `irm https://astral.sh/uv/install.ps1` from bootstrap.
- [ ] Run `uv run pytest tests/test_tauri_desktop.py tests/test_installer_windows.py -q --basetemp=.test-tmp/windows-installer-red` and verify failures name the missing offline-cache contract and forbidden fallbacks.
- [ ] Implement cache staging with a SHA-256 manifest and make the Windows release build fail before packaging when Python, uv, or the offline cache is absent or invalid.
- [ ] Make bootstrap accept only the bundled verified Python/uv/cache and emit `bundled_runtime_unavailable` with a reinstall instruction on integrity failure.
- [ ] Run the focused tests and require zero failures.

### Task 2: Provider-neutral degraded bootstrap

**Files:**
- Modify: `installers/windows/app/bootstrap.ps1`
- Modify: `installers/windows/start-light.ps1`
- Modify: `tools/onboard_provider.py`
- Test: `tests/test_installer_windows.py`
- Test: `tests/test_onboard_provider.py`

**Interfaces:**
- Bootstrap writes warnings with codes `answer_engine_unavailable`, `embedding_engine_unavailable`, and `qdrant_unavailable` without returning `setup_required`.
- Existing `.env` provider values remain unchanged; an empty provider remains empty until Sovushka configuration saves a choice.

- [ ] Add failing tests proving clean Windows bootstrap does not invoke `onboard_provider.py --provider ollama`, does not require an Ollama model, and can reach service startup without Docker/Qdrant.
- [ ] Run the two focused test files and verify they fail on the current forced-Ollama/setup-required behavior.
- [ ] Remove clean-install provider mutation and convert external-engine requirements to warnings; guard Docker/Qdrant operations behind actual availability.
- [ ] Ensure `start-light.ps1` can start proxy/UI with an empty configured provider while reporting unavailable model functions instead of terminating the process.
- [ ] Run the focused tests and require zero failures.

### Task 3: Compatibility catalogue setup screen

**Files:**
- Modify: `desktop/tauri/src-tauri/src/lib.rs`
- Modify: `desktop/tauri/web/index.html`
- Modify: `desktop/tauri/web/wizard.js`
- Test: `tests/test_tauri_desktop.py`

**Interfaces:**
- `setup_snapshot` returns `configured_provider`, `providers`, `embeddings`, `docker`, `qdrant`, `core_ready`, and `ui_ready`.
- `start_from_setup(app)` starts/opens LES without writing a model choice.
- `open_setup_link(kind)` exposes only reviewed third-party documentation/download URLs.

- [ ] Add failing static/contract tests for Ollama, FreeToken, Lemonade and OpenAI-compatible cards; separate answer/embedding/index sections; no Qwen recommendation; no winget install command; and an enabled core start independent of external readiness.
- [ ] Run `uv run pytest tests/test_tauri_desktop.py -q --basetemp=.test-tmp/setup-catalogue-red` and verify the old six-step Ollama wizard causes the expected failures.
- [ ] Implement bounded provider probes and provider-neutral JSON in Rust without new dependencies.
- [ ] Rebuild the static page using the existing token vocabulary, status rows, 40 px actions, responsive one-column layout, visible focus, reduced motion, and one `role=status` message.
- [ ] Implement rendering and actions in `wizard.js`; retain the ten-second bounded refresh and prevent concurrent refresh/lifecycle calls.
- [ ] Run the focused test and `cargo check --manifest-path desktop/tauri/src-tauri/Cargo.toml` and require zero failures.

### Task 4: Public product documentation and version

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `SKILL.md`
- Modify: `skills/sovushka-ui/SKILL.md`
- Modify: `ROADMAP_TO_V1.md`
- Modify: `docs/WINDOWS_DESKTOP.md`
- Modify: `docs/INSTALL_RUNBOOK.md`
- Modify: `docs/PLATFORMS.md`
- Modify: `installers/README.md`
- Modify: `docs/modules/sovushka-uikit.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `docs/CODE_MAP.md`
- Modify: `docs/SOFTWARE_VERSIONS.md`
- Modify: `docs/RELEASE_LEDGER.md`
- Modify: `docs/PUBLICATION_CHECKLIST.md`
- Modify: `docs/TEST_INVENTORY.md`
- Create: `docs/public/windows-troubleshooting.md`
- Create: `docs/public/developer-guide.md`
- Modify: `config/version.json`
- Test: `tests/test_software_versions.py`
- Test: `tests/test_publication_check.py`

**Interfaces:**
- `README.md` becomes the public end-user entry point and links the latest GitHub Release before developer instructions.
- `docs/public/windows-troubleshooting.md` maps each emitted Windows bootstrap error code to symptom, read-only check, safe recovery, expected result, and log path.
- `docs/public/developer-guide.md` describes architecture, offline Windows payload construction, verification, and release without private infrastructure assumptions.
- Version endpoints and desktop packaging consume `0.28.1 / 588` from `config/version.json`.

- [ ] Add/update failing documentation/version assertions for `0.28.1`, build `588`, installer-first quick start, provider-role language, and complete bootstrap-error-code coverage in the public troubleshooting guide.
- [ ] Run the two focused tests and verify they fail against the old public contract.
- [ ] Replace the README; add public Windows troubleshooting and developer guides; update `AGENTS.md`, both relevant skills, roadmap, platform matrix, module/code/install/release documentation, and installer notes so they describe the implemented provider-neutral/offline installer exactly. Cover installer integrity, WebView2, venv repair, occupied ports, provider reachability, embeddings, Docker/Qdrant, updates, logs, and data-preserving reset.
- [ ] In `ROADMAP_TO_V1.md`, distinguish shipped work from future universal tools, managed memory/context, stability, macOS/Linux support, and Lemonade work.
- [ ] Update `config/version.json` and synchronized desktop/release metadata.
- [ ] Run focused documentation/version tests and require zero failures.

### Task 5: Verification, Legion install, and GitHub publication

**Files:**
- Create/update build outputs only under ignored `dist/`
- Modify public remote `main` and create GitHub tag/release only after gates

**Interfaces:**
- Release assets are `dist/LES-Setup.exe`, `dist/LES-Setup.exe.sha256`, and `dist/latest.json`.
- Public release tag is `v0.28.1` in `proovcme/les_rag_public`.

- [ ] Run `make verify`, `make test`, `make test-mail-release`, and `make public-check`; stop on the first failure and preserve its evidence.
- [ ] Commit the complete code/docs/version change and push the exact commit to the private release branch.
- [ ] Run the canonical Windows release builder on Legion; require a real isolated EXE install, API/UI readiness, direct-Python process contract, and an installed release report with `ok=true`.
- [ ] Run a configured native-RRF smoke when the user corpus is available; record `N/A: corpus absent` rather than weakening the gate when it is not.
- [ ] Verify installer SHA-256, generate `latest.json` and release notes, and download-compare all published assets after GitHub Release creation.
- [ ] Fetch public `main`, run publication scrub on the exact outgoing tree, then update it with `git push --force-with-lease public <verified-commit>:main`.
- [ ] Create GitHub Release `v0.28.1` only from the verified public-main commit and confirm the release page and asset names through `gh release view`.
