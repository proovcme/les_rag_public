# INSTALL_RUNBOOK — boxed install on a clean Mac / Windows

Operator runbook for taking ЛЕС from a fresh repo to a double-click app on a
**clean target machine**. This is the honest version: every step that needs a
human at a real Mac/Windows box, an Apple/Microsoft signature, or a VM is marked
**[ручками]** (manual / cannot be done in CI or on the build box).

Audience: Олег. Build box = your dev Mac. Target = the clean machine the app
ships to.

---

## 0. What's automated vs. what isn't

| Stage | Automated (build box) | [ручками] on target / needs signature |
|---|---|---|
| Icons | `tools/build_icons.py` (Pillow fallback or cairosvg) | — |
| Build `.app` / `.dmg` | `tools/build_tauri_app.py --bundles app,dmg` | — |
| Build Win installer | `tools/build_windows_installer.py` on Windows | Windows host/VM is required for the final Tauri/NSIS EXE |
| First launch / bootstrap | `bootstrap.sh` / `bootstrap.ps1` (uv, sync, onboarding, weights, shell) | runs **only on the target**, needs network |
| Provider/key/model | `tools/onboard_provider.py` (first-run default) + GUI «Настройки» | cloud key is pasted by a human |
| Gatekeeper / SmartScreen | — | **[ручками]** unblock, or buy Developer ID / Authenticode |

There is **no Developer ID / Apple notarization / Windows Authenticode** yet.
The bundles are **ad-hoc signed** (Mac) / **unsigned** (Win). On a clean machine
the OS *will* warn — see §4. Real signing is a paid, account-bound step that
cannot be faked here; it's tracked in §6.

---

## 1. One-time prep on the build box (Mac)

```bash
# Icons — regenerate .icns/.ico from installers/icon/les.svg.
# Pillow is already in the runtime env (built-in fallback renderer); cairosvg
# gives full SVG fidelity if you install it.
uv run --with pillow python tools/build_icons.py
#   -> installers/macos/app/LES.icns
#   -> installers/windows/app/LES.ico
# (committed assets; only rerun when les.svg changes)
```

Sanity-check the offline gate before building anything:

```bash
make verify        # syntax + import smoke + pytest collect (no Qdrant/MLX)
```

---

## 2. Build the macOS bundle (on the Mac build box)

```bash
uv run python tools/build_tauri_app.py --version X.Y.Z --bundles app,dmg
# -> dist/LES.app + dist/LES.dmg
```

- `--sign` = **ad-hoc** codesign (`codesign --sign -`). Enough to run locally;
  **not** enough to clear Gatekeeper on someone else's Mac without §4.
- Weights and the venv are NOT bundled. The clean Python runtime source is bundled and
  materialized into `~/Library/Application Support/LES` on first launch.

**[ручками]** Copy `dist/LES.dmg` to the clean Mac (AirDrop / USB / download).

---

## 3. Build the Windows installer

The final Tauri/NSIS `LES-Setup.exe` must be built on Windows. A Mac build does
not produce an old look-alike EXE under the same name.

```bash
uv run python tools/build_windows_installer.py --version X.Y.Z
```

- Windows → `dist/LES-Setup.exe` through Tauri/NSIS.
- macOS/Linux → `dist/LES-windows-tauri-source.zip`; transfer it to Windows and
  run the same command there.

**[ручками]** Copy the installer/zip to the clean Windows machine.

---

## 4. First launch on the CLEAN target

The target needs **network** on first launch (uv install, `uv sync`, optional
model-weight download). After that it can run offline (local provider).

### macOS

1. Open `LES.dmg`, drag `LES.app` to Applications.
2. First open: because the app is ad-hoc signed (not notarized), Gatekeeper
   blocks it. **[ручками]** right-click → **Open** → **Open** (or
   `System Settings → Privacy & Security → Open Anyway`). One time per machine.
3. The bootstrap runs with no terminal:
   - installs `uv` if missing,
   - `uv sync --extra mac-mlx` (Tauri is already the desktop shell),
   - `lesctl init --profile mac-native`,
   - `onboard_provider.py --skip-if-configured` → sets a **local MLX** default,
   - `onboard_models.py` → downloads weights (first run only, resumable),
   - Tauri waits for health and loads `:8051/les` in the native window.
   Progress = macOS notifications; errors = a dialog; full log in
   `~/Library/Logs/LES/bootstrap.log`.

### Windows

1. Run `LES-Setup.exe` (per-user, **no admin**). It drops the code export under
   `%LOCALAPPDATA%\Programs\LES` + Start-Menu/Desktop shortcuts.
2. First launch: SmartScreen warns (unsigned). **[ручками]** **More info →
   Run anyway**. One time per machine.
3. The shortcut → `launcher.vbs` (hidden) → `bootstrap.ps1`:
   - installs `uv` (winget or official script),
   - `uv sync` (no MLX and no pywebview on Windows),
   - `lesctl init --profile windows-lite`,
   - `onboard_provider.py --skip-if-configured --provider ollama` → local
     **ollama** default (no cloud key needed to boot),
   - `onboard_models.py --skip-if-cloud`,
   - optional Qdrant via Docker if Docker is present,
   - brings the stack up via `start-light.ps1`; Tauri opens the live UI.
   Progress = tray balloons; errors = a dialog; log in
   `%LOCALAPPDATA%\LES\logs\bootstrap.log`.

---

## 5. Pick / change the engine (provider, key, model)

First-run picks a safe **local** default so the very first chat works. To use a
cloud model or change the model:

- **Primary path (gui-first):** Совушка → **«Настройки»** → провайдер / ключ /
  модель. Applies live (no restart for MLX model switch). This is the canonical
  place; the wizard is only a cold-start convenience.
- **CLI (before the GUI is up, or scripted):**
  ```bash
  uv run python tools/onboard_provider.py                       # interactive
  uv run python tools/onboard_provider.py --provider openrouter --api-key sk-...
  uv run python tools/onboard_provider.py --show                # current provider
  ```
  Writes the same `.env` keys the GUI uses (`LES_LLM_PROVIDER`,
  `<PROVIDER>_MODEL/_API_KEY/_BASE_URL`, `LES_CLOUD_CONSENT`).

Per ADR-11 (LLM-minimalism): local first, cloud opt-in, key never invented.
Cloud providers are **only** OpenRouter / OpenAI (no direct Anthropic).

---

## 6. What still requires money / a signature / a VM — be honest

These are **not** code gaps; they cannot be closed without paid accounts or
real target hardware:

- **Apple notarization** — needs a paid Apple Developer ID, `codesign` with that
  identity, `notarytool submit`, `stapler staple`. Until then every clean Mac
  shows the Gatekeeper prompt (§4) once. Ad-hoc `--sign` is all the build box
  can do.
- **Windows Authenticode** — needs a paid code-signing cert + `signtool`. Until
  then SmartScreen warns once per machine.
- **Windows Tauri/NSIS build host** — the final `.exe` requires Windows. From
  the Mac the builder emits a staged Tauri source zip, not a misleading EXE.
- **Clean-machine smoke** — the only true test of the boxed install is running
  it on a Mac/Windows that has never seen the repo. This **[ручками]** step is
  Олег's: do not assume its result. `tools/clean_install_smoke.py` rehearses the
  *Linux/server* path in a temp clone, but it does not exercise the
  Gatekeeper/SmartScreen/desktop-shell path.

---

## 7. Quick reference

| Want | Command |
|---|---|
| Regenerate icons | `uv run --with pillow python tools/build_icons.py` |
| Offline gate | `make verify` |
| Build Mac app + dmg | `tools/build_tauri_app.py --version X.Y.Z --bundles app,dmg` |
| Stage/build Win installer | `tools/build_windows_installer.py --version X.Y.Z` |
| Set provider (first run) | `tools/onboard_provider.py [--provider …]` |
| Pre-pull weights | `tools/onboard_models.py [--skip-if-cloud]` |
| Logs (Mac) | `~/Library/Logs/LES/bootstrap.log` |
| Logs (Win) | `%LOCALAPPDATA%\LES\logs\bootstrap.log` |
