# LES Mac Reinstall Stress Test

Goal: prove LES can be removed from a Mac and installed from zero without hidden local assumptions.

This runbook has two modes:

- clean-room smoke: copies the repository into a temporary folder and installs there;
- destructive Mac reinstall: stops/removes launchd services and optionally purges local runtime data.

Do not purge data unless the current corpus, indexes and samples are backed up or intentionally disposable.

## 1. Clean-Room Smoke

Run this first. It does not touch the working LES runtime:

```bash
uv run python tools/clean_install_smoke.py \
  --profile server-remote-model \
  --run-tests \
  --build-artifact
```

Expected result:

- `uv sync` succeeds in a fresh copy;
- `lesctl doctor --profile server-remote-model` succeeds;
- `lesctl install --profile server-remote-model --init-env` creates runtime dirs and `.env`;
- focused installer tests pass;
- release archive can be built without private runtime data.

Latest non-destructive result: 2026-06-06 passed on macOS arm64 with
`server-remote-model`, focused installer tests `14 passed`, and
`les-linux-docker-clean-smoke.tar.gz` artifact build inside the temporary copy.

## 2. Pre-Destructive Backup

Before removing the real Mac runtime:

```bash
uv run lesctl status
uv run python tools/build_release_artifacts.py --profile mac-native
```

Back up or intentionally discard:

- `.env`
- `data/`
- `storage/`
- `RAG_Content/`
- `logs/`
- `artifacts/`
- `snapshots/`
- local model/cache folders outside this repo

## 3. Dry-Run Uninstall

```bash
./installers/macos/uninstall.sh
```

This only prints launchd services and files that would be removed.

## 4. Service Uninstall

Stops LES launchd services and removes LES plists from `~/Library/LaunchAgents`:

```bash
./installers/macos/uninstall.sh --confirm
```

This preserves `.env`, `.venv`, `data`, `storage`, `RAG_Content`, logs and artifacts.

## 5. Full Runtime Purge

Use only for the actual reinstall stress test:

```bash
./installers/macos/uninstall.sh \
  --confirm \
  --purge-venv \
  --purge-env \
  --purge-runtime-data \
  --purge-corpora \
  --confirm-purge-data
```

`--purge-runtime-data` removes `data`, `storage`, `logs`, `artifacts`, `snapshots`.
`--purge-corpora` removes `RAG_Content`.

## 6. Install From Zero

From a fresh clone:

```bash
git clone git@github.com:proovcme/les_rag.git
cd les_rag
git checkout codex/les-closeout-20260527
uv sync
uv run lesctl init --profile mac-native
./installers/macos/install.sh
```

Edit `.env` and set at least:

- `JWT_SECRET`
- `ADMIN_PASSWORD`
- `SOVUSHKA_STORAGE_SECRET`
- provider keys if using remote model mode

Then start:

```bash
./installers/macos/install.sh --start --include-ui
uv run lesctl status
curl -fsS http://127.0.0.1:8050/api/health | python3 -m json.tool
```

## 7. Acceptance

The reinstall stress test passes when:

- no stale launchd service from the old install remains;
- `.env` is created only from `env.example` and then edited by operator;
- `uv sync` succeeds;
- `lesctl doctor --profile mac-native` succeeds;
- `lesctl start --profile mac-native --include-ui` starts Qdrant, MLX Host, proxy and UI;
- `/api/health` returns `ok`;
- Lite UI opens at `http://127.0.0.1:8051/`;
- no private corpus or local archive appears in git status or release artifacts.
