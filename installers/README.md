# LES Installers

This folder contains boxed-install entrypoints for platform profiles.

The installers are intentionally thin adapters around the repository runtime:

- `desktop/tauri/` + `tools/build_tauri_app.py` build the canonical native Mac/Windows shell.
- `linux/install.sh` prepares Linux Docker/systemd/server-remote-model profiles.
- `windows/install.ps1` prepares Windows Docker/lite profiles.
- `tools/build_release_artifacts.py` builds distributable archives without local data.

Local corpora, `.env`, model files, Qdrant data, logs, snapshots and private samples
must never be packed into release archives.

## macOS — double-click app (no terminal)

The goal is AnythingLLM/LM-Studio-grade UX: drag `LES.app` to Applications,
double-click, and the stack (Qdrant + MLX host + proxy + Sovushka) comes up and
opens in the browser. No `uv` dance, no terminal.

Design: a **Tauri 2 native shell** around the existing NiceGUI application.
The `.app` carries a Rust window/tray, a clean code export plus
`macos/app/bootstrap.sh`, which on first launch installs `uv` if missing, runs
`uv sync --extra mac-mlx`, downloads model weights and starts LES services.
Tauri waits for `:8051/healthz`, then navigates the same native webview to
Совушка. Progress starts with an embedded splash; full bootstrap detail is in
`~/Library/Logs/LES/bootstrap.log`. The runtime is
materialized into `~/Library/Application Support/LES` (override with `LES_HOME`).

The shell is not a UI rewrite and contains no RAG/smeta/domain decisions. It
owns only lifecycle, health waiting, navigation and the tray. `tools/les_shell.py`
is retained as a legacy browser/pywebview fallback, not the release entrypoint.

```bash
# Build the bundle and a drag-to-install .dmg (macOS only):
uv run python tools/build_tauri_app.py --version 5.1.0 --bundles app,dmg
# -> dist/LES.app + dist/LES.dmg
```

Model weights and venv are NOT bundled — the `.dmg` stays ~20 MB; weights are
fetched on first run. Drop an icon at `macos/app/LES.icns` to brand the bundle.

## Linux Docker

```bash
./installers/linux/install.sh --profile linux-docker --init-env --sync
./installers/linux/install.sh --profile linux-docker --start
```

## Linux Systemd User Units

```bash
./installers/linux/install.sh --profile linux-systemd --init-env --sync --install-units
systemctl --user start les-proxy les-ui
```

Qdrant and model runtime can be native, Docker or remote depending on `.env`.

## Windows — double-click installer (no terminal)

Same UX goal as macOS, but Windows has no Apple MLX — the engine is
cloud / ollama / lemonade, picked in the Sovushka GUI (no weights bundled).

The same Tauri source builds an NSIS per-user installer (`LES-Setup.exe`, no
admin) on a Windows host. Its Rust shell invokes the existing PowerShell
bootstrap, waits for the dynamic Windows-light UI port and owns the native
window/tray. Python remains the backend sidecar; pywebview is not installed.

```bash
# Build on Windows; other hosts only create a transfer bundle:
uv run python tools/build_windows_installer.py --version 5.1.0
# Windows -> dist/LES-Setup.exe
# macOS/Linux -> dist/LES-windows-tauri-source.zip for transfer to Windows
```

`bootstrap.ps1` carries Cyrillic UI strings and is stored UTF-8 with BOM for
Windows PowerShell 5.1. `windows/app/LES.ico` brands the Tauri bundle.

## Windows (advanced: docker / lite profiles)

```powershell
powershell -ExecutionPolicy Bypass -File .\installers\windows\install.ps1 -Profile windows-lite -InitEnv -Sync
powershell -ExecutionPolicy Bypass -File .\installers\windows\install.ps1 -Profile windows-docker -Start
```

Windows Docker uses named volumes for Qdrant and regular bind mounts for repository
content. Keep production corpora outside git and mount/copy them explicitly.

## macOS Reinstall Stress

```bash
uv run python tools/clean_install_smoke.py --profile server-remote-model --run-tests --build-artifact
./installers/macos/uninstall.sh
uv run lesctl init --profile mac-native
./installers/macos/install.sh
```

The uninstall script is dry-run by default. Actual service removal requires
`--confirm`; runtime/corpus deletion also requires `--confirm-purge-data`.

See `docs/MAC_REINSTALL_STRESS.md`.
