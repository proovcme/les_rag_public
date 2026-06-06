# LES Installers

This folder contains boxed-install entrypoints for platform profiles.

The installers are intentionally thin adapters around the repository runtime:

- `linux/install.sh` prepares Linux Docker/systemd/server-remote-model profiles.
- `windows/install.ps1` prepares Windows Docker/lite profiles.
- `tools/build_release_artifacts.py` builds distributable archives without local data.

Local corpora, `.env`, model files, Qdrant data, logs, snapshots and private samples
must never be packed into release archives.

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

## Windows

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
./installers/macos/install.sh --init-env
```

The uninstall script is dry-run by default. Actual service removal requires
`--confirm`; runtime/corpus deletion also requires `--confirm-purge-data`.

See `docs/MAC_REINSTALL_STRESS.md`.

