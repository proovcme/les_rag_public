# LES Installers

This folder contains boxed-install entrypoints for platform profiles.

The installers are intentionally thin adapters around the repository runtime:

- `macos/app/` + `tools/build_macos_app.py` build a double-click `LES.app` (see below).
- `linux/install.sh` prepares Linux Docker/systemd/server-remote-model profiles.
- `windows/install.ps1` prepares Windows Docker/lite profiles.
- `tools/build_release_artifacts.py` builds distributable archives without local data.

Local corpora, `.env`, model files, Qdrant data, logs, snapshots and private samples
must never be packed into release archives.

## macOS — double-click app (no terminal)

The goal is AnythingLLM/LM-Studio-grade UX: drag `LES.app` to Applications,
double-click, and the stack (Qdrant + MLX host + proxy + Sovushka) comes up and
opens in the browser. No `uv` dance, no terminal.

Design: a **lightweight bootstrap** (chosen over a fully self-contained
PyInstaller bundle). The `.app` carries a clean code export plus
`macos/app/bootstrap.sh`, which on first launch installs `uv` if missing, runs
`uv sync --extra mac-mlx --extra desktop`, downloads model weights
(`tools/onboard_models.py`, download-on-first-run), then launches the **desktop
shell** (`tools/les_shell.py`). Progress shows as macOS notifications; failures
as a dialog; full detail in `~/Library/Logs/LES/bootstrap.log`. The runtime is
materialized into `~/Library/Application Support/LES` (override with `LES_HOME`).

The shell is a thin native window + tray (pywebview + pystray) **around** the
existing Sovushka web UI — not a reimplementation. It owns lifecycle
(start / restart / stop / open logs from the tray, so no terminal is needed),
shows a splash while the stack comes up, then loads `127.0.0.1:8051/les`. With
the `desktop` extra absent it degrades to opening the default browser
(`python -m tools.les_shell --no-gui`).

```bash
# Build the bundle and a drag-to-install .dmg (macOS only):
uv run python tools/build_macos_app.py --version 0.1.0 --sign   # -> dist/LES.app
uv run python tools/build_macos_dmg.py --version 0.1.0          # -> dist/LES.dmg
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

Design mirrors the mac bundle: an NSIS per-user installer (`LES-Setup.exe`,
no admin) drops the clean code export under `%LOCALAPPDATA%\Programs\LES` and a
Start-Menu/Desktop shortcut → `app/launcher.vbs` (runs hidden) → `app/bootstrap.ps1`,
which on first launch installs `uv` (winget or the official script), runs
`uv sync`, `lesctl init --profile windows-lite`, optionally starts Qdrant
(Docker if present), brings up proxy + UI via `start-light.ps1`, and opens the
browser. Progress shows as tray balloons, failures as a dialog; full detail in
`%LOCALAPPDATA%\LES\logs\bootstrap.log`.

```bash
# Stage + build (NSIS auto-detected; without it, writes a portable zip + the
# makensis command to run on a Windows box). Runs on any OS for staging:
uv run python tools/build_windows_installer.py --version 0.1.0   # -> dist/LES-Setup.exe | LES-windows-portable.zip
```

`bootstrap.ps1` and `LES.nsi` carry Cyrillic UI strings and are stored UTF-8
**with BOM** so Windows PowerShell 5.1 / NSIS render them correctly. Drop an icon
at `windows/app/LES.ico` to brand the shortcuts.

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
