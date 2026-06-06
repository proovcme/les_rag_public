# Установка Л.Е.С.

Л.Е.С. сейчас имеет референсный локальный host-runtime на macOS Apple Silicon, но упаковка переводится в профильную модель для macOS, Linux и Windows. Базовый контур: Qdrant `:6333`, model host `:8080`, FastAPI proxy `:8050`, Sovushka Lite UI `:8051`.

## Требования

- Python `3.12+`
- `uv`
- Qdrant: локальный binary, Docker/named volume или remote Qdrant
- 16 GB RAM минимум, 24 GB+ комфортно
- Node/npm нужны только для пересборки `frontend/cad_bim_viewer`

Платформенные профили описаны в `docs/PLATFORMS.md`, план коробочной упаковки — в `docs/PACKAGING.md`.

## Быстрый старт

```bash
git clone git@github.com:proovcme/les_rag.git
cd les_rag

uv sync
uv run lesctl doctor --profile mac-native
uv run lesctl init --profile mac-native
uv run lesctl install --profile mac-native
```

`lesctl install` подготавливает директории, `.env` и зависимости. launchd-сервисы
регистрируются при первом `lesctl start`.

После этого отредактируйте `.env`:

- замените `JWT_SECRET`, `ADMIN_PASSWORD`, `SOVUSHKA_STORAGE_SECRET`;
- оставьте `TRUSTED_NETWORKS=127.0.0.0/8,::1/128` для локального старта;
- добавляйте VPN/LAN CIDR только если понимаете, кто получит admin-доступ;
- не коммитьте `.env` и реальные API keys.

macOS wrapper:

```bash
./installers/macos/install.sh --init-env
```

## Запуск

Через новый CLI entrypoint после `uv sync`:

```bash
uv run lesctl start --profile mac-native --include-ui --memory-preflight
```

Для Linux Docker profile:

```bash
./installers/linux/install.sh --profile linux-docker --init-env --sync
./installers/linux/install.sh --profile linux-docker --start
```

Для Linux systemd user units:

```bash
./installers/linux/install.sh --profile linux-systemd --init-env --sync --install-units
systemctl --user start les-proxy les-ui
```

Для Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\installers\windows\install.ps1 -Profile windows-lite -InitEnv -Sync
powershell -ExecutionPolicy Bypass -File .\installers\windows\install.ps1 -Profile windows-docker -Start
```

Через существующий launch helper:

```bash
./start_les.command
```

Открыть:

- Lite chat: `http://127.0.0.1:8051/`
- Lite Admin: `http://127.0.0.1:8051/les`
- FastAPI health: `http://127.0.0.1:8050/api/health`
- MLX health: `http://127.0.0.1:8080/api/health`

## Проверка

```bash
uv run les-install --check
uv run lesctl doctor --profile mac-native
uv run lesctl init --profile mac-native
uv run lesctl status
curl -fsS http://127.0.0.1:8050/api/health | python3 -m json.tool
curl -fsS http://127.0.0.1:8080/api/health | python3 -m json.tool
curl -fsS http://127.0.0.1:8051/healthz | python3 -m json.tool
curl -fsS -X POST http://127.0.0.1:8050/api/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"smoke","top_k":1,"include_trace":true}' | python3 -m json.tool
```

На пустом fresh install `/api/health` может вернуть HTTP 200 со
`status=degraded`, `rag.status=empty`, `datasets=0`, `chunks=0`. Это означает,
что runtime поднят, но корпус еще не загружен.

## Остановка

```bash
uv run lesctl stop --include-ui
```

или:

```bash
./stop_les.command
```

## Переустановка на Mac с нуля

Перед настоящим сносом сначала прогоните safe smoke в temp-копии:

```bash
uv run python tools/clean_install_smoke.py --profile server-remote-model --run-tests --build-artifact
```

Dry-run uninstall:

```bash
./installers/macos/uninstall.sh
```

Настоящий destructive сценарий описан в [docs/MAC_REINSTALL_STRESS.md](docs/MAC_REINSTALL_STRESS.md).

## Индексация документов

Положите документы в `RAG_Content/` и сначала посмотрите dry-run:

```bash
curl -fsS 'http://127.0.0.1:8050/api/rag/smart-plan?source_root=RAG_Content' \
  | python3 -m json.tool
```

Регистрация и guarded indexing:

```bash
curl -X POST http://127.0.0.1:8050/api/rag/sync-smart \
  -H 'Content-Type: application/json' \
  -d '{"source_root":"RAG_Content","parse":false}'

curl -X POST http://127.0.0.1:8050/api/runtime/dispatcher/reindex/start \
  -H 'Content-Type: application/json' \
  -d '{}'
```

Не запускайте полный reindex без причины: на рабочем корпусе это эксплуатационная операция, а не часть установки.

## CAD/BIM

LES принимает CAD/BIM как JSON-first pipeline. Raw IFC/DWG/RVT/DXF допускаются на upload boundary, но надежный путь для индексации: exporter -> canonical `cad_bim_graph.json` -> `/api/cad-bim/import`.

Standalone viewer лежит в `standalone/cad_bim_viewer/`. Он не требует LES backend, npm или сети:

```bash
cd standalone/cad_bim_viewer
./serve.sh 8095
```

Открыть: `http://127.0.0.1:8095/?source=models/demo.cad_bim_graph.json`.

## Обновление

```bash
git pull
uv sync
uv run lesctl restart --include-ui
```

После изменений в зависимостях:

```bash
uv lock --check
uv run pytest -q
```

## Release artifacts

Коробочные архивы собираются без локальных данных, `.env`, логов, snapshots,
Qdrant storage, private samples и `RAG_Content`:

```bash
uv run python tools/build_release_artifacts.py --profile linux-docker
uv run python tools/build_release_artifacts.py --profile windows-docker
```

Результат пишется в `dist/`.

## Что не входит в git

Локальные данные, индексы, runtime-логи и private samples не должны попадать в commit:

- `data/`
- `storage/`
- `RAG_Content/`
- `logs/`
- `artifacts/`
- `snapshots/`
- `local_private_archive/`
- `standalone/cad_bim_viewer/ifc-sample/`
