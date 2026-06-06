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

Latest destructive result: 2026-06-06 passed on macOS arm64 from fresh clone
`/Users/ovc/Projects/LES_v2_reinstall_stress` at commit `508fb0d`.
Qdrant, MLX Host, les-proxy and Sovushka UI were healthy after reinstall.
Empty-index `/api/search` returned HTTP 200 in `0.045s` with
`retrieval_trace.mode=empty`.

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

2026-06-06 destructive run used same-volume quarantine instead of copying large
runtime folders:

```text
local_private_archive/20260606_mac_reinstall_stress/quarantine/
```

Moved sizes from the source worktree were:

```text
.env 8K
.venv 1.7G
data 2.7G
storage 3.9G
RAG_Content 1.0G
logs 590M
artifacts 35G
snapshots 34G
```

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
uv run lesctl install --profile mac-native
```

`lesctl install` prepares local directories and `.env`; launchd plist files are
rendered and installed by `lesctl start`.

Edit `.env` and set at least:

- `JWT_SECRET`
- `ADMIN_PASSWORD`
- `SOVUSHKA_STORAGE_SECRET`
- provider keys if using remote model mode

Then start:

```bash
uv run lesctl start --profile mac-native --include-ui --no-indexer --memory-preflight
uv run lesctl status --profile mac-native
curl -fsS http://127.0.0.1:8050/api/health | python3 -m json.tool
```

## 7. Acceptance

The reinstall stress test passes when:

- no stale launchd service from the old install remains;
- `.env` is created only from `env.example` and then edited by operator;
- `uv sync` succeeds;
- `lesctl doctor --profile mac-native` succeeds;
- `lesctl start --profile mac-native --include-ui` starts Qdrant, MLX Host, proxy and UI;
- Qdrant `:6333`, MLX Host `:8080`, proxy `:8050` and UI `:8051` health endpoints return HTTP 200;
- on an empty fresh corpus, proxy `/api/health` may return `status=degraded` with `rag.status=empty`;
- empty `/api/search` returns HTTP 200 without warming embedding/model paths;
- Lite UI opens at `http://127.0.0.1:8051/`;
- no private corpus or local archive appears in git status or release artifacts.

## 8. 2026-06-06 Destructive Run Log

Source worktree before purge: `/Users/ovc/Projects/LES_v2`, branch
`codex/les-closeout-20260527`, starting commit `dcd2a45`.

Runtime before purge:

- Qdrant loaded/running on `:6333`;
- MLX Host loaded/running on `:8080`;
- les-proxy loaded/running on `:8050`;
- Sovushka UI was not loaded;
- `me.ovc.les.pauk` remained as external tunnel service and is not part of
  `installers/macos/uninstall.sh`.

Executed uninstall:

```bash
./installers/macos/uninstall.sh \
  --confirm \
  --purge-venv \
  --purge-env \
  --purge-runtime-data \
  --purge-corpora \
  --confirm-purge-data
```

After uninstall, core LES launchd labels and plist files were removed. `pauk`
plist remained intentionally because it is outside the core runtime uninstall
list.

Fresh install:

```bash
git clone --branch codex/les-closeout-20260527 git@github.com:proovcme/les_rag.git \
  /Users/ovc/Projects/LES_v2_reinstall_stress
cd /Users/ovc/Projects/LES_v2_reinstall_stress
uv sync
uv run lesctl init --profile mac-native --json
uv run lesctl install --profile mac-native --init-env
uv run lesctl start --profile mac-native --include-ui --no-indexer --memory-preflight
```

Errors found and fixed during the run:

- launchd plist templates contained the old hardcoded
  `/Users/ovc/Projects/LES_v2` root. Fixed in `dcd2a45` by rendering plist
  templates for the current clone root.
- `proxy.storage.file_storage` existed only as ignored local content because
  `.gitignore` ignored `storage/` directories. Fixed in `951e3a3` by tracking
  `proxy/storage` explicitly.
- Sovushka crashed in a clean clone when `static/` did not exist. Fixed in
  `951e3a3` by creating `static/` during install/init and making static mount
  conditional.
- MLX Host blocked FastAPI startup while synchronously preloading tokenizers
  from Hugging Face. Fixed in `d508c28` by making tokenizer preload lazy by
  default; `MLX_PRELOAD_TOKENIZERS=true` restores eager behavior.
- `/api/search` on an empty fresh index warmed embedding before returning no
  chunks. Fixed in `508fb0d` by short-circuiting empty dataset scope.

Verification after fixes:

```bash
uv run pytest -q tests/test_retrieval_service.py tests/test_datasets_router.py \
  tests/test_mlx_adapter.py tests/test_file_storage.py tests/test_install_les.py \
  tests/test_les_runtime_control.py tests/test_lesctl.py
# 72 passed, 2 warnings

uv run lesctl status --profile mac-native
# qdrant ok, mlx ok, proxy ok, ui ok; indexer intentionally not loaded

curl -fsS http://127.0.0.1:6333/collections
curl -fsS http://127.0.0.1:8080/api/health
curl -fsS http://127.0.0.1:8050/api/health
curl -fsS http://127.0.0.1:8051/healthz

curl -fsS -X POST http://127.0.0.1:8050/api/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"smoke","top_k":1,"include_trace":true}'
# HTTP 200, elapsed 0.045s, count=0, retrieval_trace.mode=empty
```
