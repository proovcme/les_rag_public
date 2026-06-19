# Установка Л.Е.С.

Л.Е.С. имеет несколько профилей запуска. Базовый контур: Qdrant `:6333`,
model/provider endpoint, FastAPI proxy `:8050`, Sovushka Lite UI `:8051`.

Два пути: **установка в один клик** (дабл-клик `.app`/`.exe`, без терминала —
ниже) или **ручной CLI** через `uv` + `lesctl` (со раздела «Требования»).

## Установка в один клик (без терминала)

Цель — UX уровня AnythingLLM/LM Studio: дабл-клик, и весь стек
(Qdrant + модель/провайдер + proxy + Совушка) поднимается и открывается в
браузере. Веса не входят в установщик — на первом запуске докачиваются
(Mac) либо движок берётся облачный/ollama/lemonade (Windows).

### macOS — `LES.app` / `LES.dmg`

Соберите бандл из исходников (macOS, есть `uv`):

```bash
git clone https://github.com/proovcme/les_rag_public.git
cd les_rag_public
uv run python tools/build_macos_app.py --version 0.1.4 --sign   # -> dist/LES.app
uv run python tools/build_macos_dmg.py --version 0.1.4          # -> dist/LES.dmg
```

Перетащите `LES.app` в «Программы» и запустите двойным кликом. На первом
запуске бутстрап ставит `uv` (если нет), выполняет `uv sync --extra mac-mlx`,
докачивает локальную модель (Qwen3.5-4B-MLX + эмбеддер), поднимает службы и
открывает `http://127.0.0.1:8051/les`. Прогресс — в нотификациях, лог —
`~/Library/Logs/LES/bootstrap.log`. Рантайм разворачивается в
`~/Library/Application Support/LES` (override `LES_HOME`).

### Windows — `LES-Setup.exe`

Windows без Apple MLX → движок облачный / `ollama` / `lemonade` (выбор в GUI
Совушки), веса не бандлятся. Соберите установщик (NSIS):

```bash
uv run python tools/build_windows_installer.py --version 0.1.4
# NSIS установлен -> dist/LES-Setup.exe; иначе -> dist/LES-windows-portable.zip
# + печать команды makensis для сборки .exe на Windows.
```

`LES-Setup.exe` ставит per-user (без админа) в `%LOCALAPPDATA%\Programs\LES`,
создаёт ярлыки в меню «Пуск» и на рабочем столе. Двойной клик → бутстрап
ставит `uv`, `uv sync`, поднимает proxy + UI (`start-light.ps1`) и открывает
браузер. Лог — `%LOCALAPPDATA%\LES\logs\bootstrap.log`.

Артефакты установщика (`.dmg`/`.exe`) намеренно не прикладываются к релизам —
собирайте из исходников этого репозитория, чтобы бандл содержал ровно его код.

## Требования

- Python `3.12+`
- `uv`
- Qdrant: локальный binary, Docker/named volume или remote Qdrant
- 16 GB RAM минимум, 24 GB+ комфортно
- Node/npm нужны только для пересборки `frontend/cad_bim_viewer`

## Быстрый старт

```bash
git clone https://github.com/proovcme/les_rag_public.git
cd les_rag_public

uv sync
uv run lesctl doctor --profile mac-native
uv run lesctl init --profile mac-native
uv run lesctl install --profile mac-native --init-env
```

`lesctl install` подготавливает директории, `.env` и зависимости. launchd-сервисы
регистрируются при первом `lesctl start`.

После этого отредактируйте `.env`:

- замените `JWT_SECRET`, `ADMIN_PASSWORD`, `SOVUSHKA_STORAGE_SECRET`;
- оставьте `TRUSTED_NETWORKS=127.0.0.0/8,::1/128` для локального старта;
- добавляйте VPN/LAN CIDR только если понимаете, кто получит admin-доступ;
- не коммитьте `.env` и реальные API keys.

macOS wrapper, если он есть в выбранном snapshot:

```bash
./installers/macos/install.sh --init-env
```

## Запуск

Через новый CLI entrypoint после `uv sync`:

```bash
uv run lesctl start --profile mac-native --include-ui --memory-preflight
```

Для Linux Docker profile, если Docker/installers включены в snapshot:

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
powershell -ExecutionPolicy Bypass -File .\installers\windows\start-light.ps1 -Provider lemonade -StartQdrant
```

`windows-lite` не ставит MLX/CoreML и не требует локальную Apple Silicon
модель. Это легкий профиль для Windows/Revit host: Qdrant + LES proxy + UI,
а генерация уходит в OpenAI-compatible provider.

Поддерживаемые provider presets:

- `lemonade`: `LEMONADE_BASE_URL=http://127.0.0.1:13305/api/v1`
- `ollama`: `OLLAMA_BASE_URL=http://127.0.0.1:11434`
- `openrouter`: `OPENROUTER_BASE_URL=https://openrouter.ai/api/v1`
- `openai`: `OPENAI_BASE_URL=https://api.openai.com/v1`
- `openai-compatible`: любой совместимый `OPENAI_BASE_URL`

Примеры:

```powershell
# Lemonade local server
.\installers\windows\start-light.ps1 -Provider lemonade -Model "your-model" -StartQdrant

# Ollama OpenAI-compatible endpoint
.\installers\windows\start-light.ps1 -Provider ollama -Model "qwen3:8b" -StartQdrant

# OpenRouter
$env:OPENROUTER_API_KEY = "..."
.\installers\windows\start-light.ps1 -Provider openrouter -Model "openai/gpt-4.1-mini" -StartQdrant

# OpenAI
$env:OPENAI_API_KEY = "..."
.\installers\windows\start-light.ps1 -Provider openai -Model "gpt-4.1-mini" -StartQdrant
```

Важно: `start-light.ps1` удобен для ручного smoke. Для постоянной эксплуатации
на Windows нужен service/scheduled-task wrapper; короткая SSH-сессия может
завершить дочерние процессы после выхода.

Docker profile остается отдельным вариантом:

```powershell
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

На Windows light MLX health не ожидается: вместо него проверяйте
`GET /api/settings`, поле `providers.active`, и `GET /api/status`, поле
`proxy.llm_provider`.

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
