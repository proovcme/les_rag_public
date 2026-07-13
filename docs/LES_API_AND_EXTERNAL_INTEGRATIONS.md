# API и внешние подключения Л.Е.С.

> **Статус:** актуально по коду на 2026-07-14.
> **Версия кода:** читается из `config/version.json`; версии внешнего ПО —
> [SOFTWARE_VERSIONS.md](SOFTWARE_VERSIONS.md).
> При расхождении этого файла с `GET /api/version`, `GET /openapi.json` или кодом роутера правы runtime и код.

## Назначение

Это единая карта сетевых границ Л.Е.С.: какие процессы слушают порты, какие API доступны внутри системы,
куда Л.Е.С. может ходить наружу, какие подключения включены сейчас и где задаётся конфигурация.

Документ **не содержит секретов**. Значения API-ключей, OAuth-токенов, паролей, SSH-ключей и содержимое
`.env` сюда не переносятся. Перечислены только имена переменных и безопасный факт настройки.

## Короткая схема

```text
Браузер
  ├─ локально / ZeroTier ───────────────> Совушка :8051
  │                                        └─ /lite-api/* ──> proxy :8050
  └─ https://les.ovc.me ─> VPS/P.A.U.K. ───────────────────> Совушка :8051
                                                           └─ proxy :8050
proxy :8050
  ├─ LLM / embeddings / rerank ─────────> MLX host :8080
  ├─ vectors ───────────────────────────> Qdrant :6333
  ├─ optional local vision/chat ────────> Ollama :11434
  ├─ optional local OpenAI-compatible ─> Lemonade :13305
  ├─ cloud LLM, only with consent ─────> OpenAI-compatible / OpenRouter
  ├─ source update, not chat hot path ─> ФГИС ЦС
  ├─ optional source mirrors ──────────> Google Drive / Яндекс Диск
  ├─ optional mail intake ─────────────> IMAP
  └─ optional price discovery ─────────> public supplier web
```

## 1. Локальные сервисы

| Компонент | Адрес по умолчанию | Назначение | Внешняя публикация |
|---|---|---|---|
| LES proxy | `http://127.0.0.1:8050` | Основной FastAPI: чат, RAG, сметы, документы, проекты, настройки и эксплуатация | Напрямую наружу не публикуется |
| Совушка | `http://127.0.0.1:8051` | GUI и мост `/lite-api/*` в :8050 | Через `https://les.ovc.me` |
| MLX host | `http://127.0.0.1:8080` | Локальные LLM, embeddings, rerank, validation | Только локальный backend |
| Qdrant | `http://127.0.0.1:6333` | Dense и sparse-векторы RAG | Только локальный backend |
| Ollama | `http://127.0.0.1:11434` | Необязательный локальный LLM/VLM/OCR | Не публикуется |
| Lemonade | `http://127.0.0.1:13305/api/v1` | Необязательный OpenAI-compatible runtime | Не публикуется |

Главные точки здоровья:

- proxy: `GET http://127.0.0.1:8050/api/health`;
- версия и совпадение dev/runtime: `GET http://127.0.0.1:8050/api/version`;
- MLX: `GET http://127.0.0.1:8080/api/health`;
- Совушка: `GET http://127.0.0.1:8051/healthz`;
- Qdrant: `GET http://127.0.0.1:6333/collections`.

## 2. Публичный и доверенный доступ

### Публичный вход

`https://les.ovc.me` приходит на VPS и далее по reverse SSH-туннелю P.A.U.K. к Совушке.
Совушка передаёт API-вызовы через `/lite-api/{path}` в proxy. Это один API, а не отдельная
облегчённая бизнес-логика.

### ZeroTier

Доверенный путь: `http://10.195.146.98:8051/les`. Сеть `10.195.146.0/24` может получать роль,
заданную `TRUSTED_NETWORK_ROLE`, если запрос прошёл trust-проверку. Диагностика:
`GET /api/auth/trust` либо `GET /lite-api/auth/trust`.

### Авторизация

Proxy принимает ключ через `X-API-Key`, `Authorization: Bearer ...` или доверенную сеть.
OpenAPI показывает заголовки, но не кодирует точную роль endpoint. Истина по роли находится в
`Depends(require_user)` и `Depends(require_admin)` роутера. Операции, меняющие индекс, настройки,
ключи, backup и системные данные, следует считать административными.

## 3. Основной proxy API

Proxy на момент снимка содержит **257 маршрутов**, **278 методов HTTP** и **43 группы**.
Интерактивная схема: `http://127.0.0.1:8050/docs`; машинная схема:
`http://127.0.0.1:8050/openapi.json`.

Практические группы:

- `chat`, `search`, `rerank`, `tools` — модель, retrieval и tool harness;
- `rag`, `files`, `documents`, `notebooks` — датасеты, ingestion, карты и чтение;
- `lsr`, `prices`, `kac`, `bor`, `estimates` — сметный и ресурсный контур;
- `cad-bim`, `diff`, `ontology`, `edges` — CAD/BIM и граф;
- `doc-review`, `normcontrol`, `verify`, `extract` — проверка документации;
- `projects`, `worklog`, `field`, `incoming-control`, `forms` — проектные данные;
- `runtime`, `settings`, `auth`, `jobs`, `logs` — эксплуатация.

### Официальный сценарий внешней ЛСР

Внешняя интеграция не загружает разовый исходник в датасет и не использует административный
`/api/rag/attach`. Единственный поддерживаемый сценарий:

1. `POST /api/chat/attachments` — `multipart/form-data`, поле `file`, пользовательский ключ доступа и
   обязательный заголовок `Idempotency-Key`. Ответ содержит временный `read_<id>`; файл не попадает
   в индекс.
2. `POST /api/chat` — JSON с `question`, `mode: "smeta"`, полученным `attachment_id` и тем же
   `Idempotency-Key`.
3. Ответ чата содержит обычный человеческий текст и `artifact.downloads.xlsx`. Файл скачивается
   авторизованным `GET /api/smeta-artifacts/download?path=...`.

Одинаковый ключ и одинаковое тело возвращают исходный результат без повторного вызова модели.
Повтор во время ещё выполняющегося запроса получает `409` и `Retry-After`; тот же ключ с другим
файлом или телом также получает `409`. Временное вложение одноразовое: после успешной сборки ЛСР
оно удаляется, а повтор всего запроса обслуживается сохранённым идемпотентным ответом.

```bash
JOB_ID="lsr-20260713-001"
ATTACHMENT_ID="$(curl -fsS -X POST "https://les.ovc.me/api/chat/attachments" \
  -H "Authorization: Bearer $LES_API_KEY" \
  -H "Idempotency-Key: $JOB_ID" \
  -F "file=@ВОР.pdf" | python3 -c 'import json,sys; print(json.load(sys.stdin)["attachment_id"])')"

curl -fsS -X POST "https://les.ovc.me/api/chat" \
  -H "Authorization: Bearer $LES_API_KEY" \
  -H "Idempotency-Key: $JOB_ID" \
  -H "Content-Type: application/json" \
  -d "{\"question\":\"Сделай ЛСР\",\"mode\":\"smeta\",\"attachment_id\":\"$ATTACHMENT_ID\"}"
```

`POST /api/rag/attach?mode=read|quick|index` остаётся административным маршрутом Совушки и
совместимости. Передача файла в base64 внутри `/api/chat` не поддерживается: она обходит единый
контракт размера, формата, срока жизни и целостности вложения.

## 4. Совушка и Lite bridge

Совушка не создаёт второй предметный API. Она даёт GUI и собственные маршруты:

| Метод | Маршрут | Назначение |
|---|---|---|
| `GET` | `/`, `/les`, `/les/lite` | Lite GUI |
| `GET` | `/classic`, `/les/classic` | Classic GUI |
| `*` | `/lite-api/{path}` | Мост к proxy `/api/{path}` |
| `GET` | `/healthz` | Здоровье Совушки |
| `GET` | `/lite-runtime/status` | Статус runtime для GUI |
| `GET` | `/lite-runtime/reindex-status` | Статус переиндексации |
| `GET` | `/lite-runtime/pick-folder` | Локальный выбор папки |
| `POST` | `/lite-runtime/action/{action}` | Ограниченные локальные runtime-действия |
| `GET` | `/les/cad-bim-viewer` | Встроенный CAD/BIM viewer |
| `GET` | `/graph`, `/graph-cosmos` | Графовые представления |
| `GET` | `/m5`, `/display/m5` | M5 display |

Код: `sovushka/lite_bridge.py`, `sovushka_ng.py`, `sovushka/m5_display.py`.

## 5. Внутренний MLX API

MLX host имеет отдельный OpenAPI `3.2.0` на `:8080/openapi.json`.

| Метод | Маршрут | Назначение |
|---|---|---|
| `GET` | `/api/health` | Состояние backend |
| `GET` | `/api/host_memory` | Память хоста |
| `GET` | `/api/ps` | Загруженные модели |
| `POST` | `/api/switch_model` | Переключить модель |
| `POST` | `/api/unload_all`, `/api/unload_val` | Выгрузить модели |
| `POST` | `/api/validate` | Проверка ответа |
| `POST` | `/api/generate`, `/api/embeddings` | Ollama-compatible API |
| `POST` | `/v1/chat/completions` | OpenAI-compatible chat |
| `POST` | `/v1/embeddings` | OpenAI-compatible embeddings |
| `POST` | `/v1/rerank` | Reranker |
| `GET` | `/v1/models` | Список моделей |

Пользовательский GUI обращается к proxy/Совушке, а не к MLX host напрямую.

## 6. Внешние подключения

| Подключение | Назначение | Адрес/протокол | Переменные | Состояние снимка |
|---|---|---|---|---|
| ProxyAPI / OpenAI-compatible | Облачный чат и сметная модель | `https://api.proxyapi.ru/openai/v1` | `OPENAI_BASE_URL`, `OPENAI_MODEL`, `OPENAI_API_KEY` | **Включено**: provider `openai`, модель `gpt-5.4`, consent=true |
| OpenRouter-compatible | Альтернативный cloud provider | обычно `https://openrouter.ai/api/v1` | `OPENROUTER_BASE_URL`, `OPENROUTER_MODEL(S)`, `OPENROUTER_API_KEY` | URL/ключ заданы, но активный provider — не OpenRouter |
| Ollama | Локальный chat/VLM/OCR | `http://127.0.0.1:11434` | `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_API_KEY` | Не настроен как чат-провайдер |
| Lemonade | Локальный OpenAI-compatible runtime | `http://127.0.0.1:13305/api/v1` | `LEMONADE_BASE_URL`, `LEMONADE_MODEL`, `LEMONADE_API_KEY` | Не настроен |
| ФГИС ЦС | ГЭСН, регионы/периоды, Сплит-формы | `https://fgiscs.minstroyrf.ru/api` | `LES_FGIS_TIMEOUT`, `LES_FGIS_FILE_TIMEOUT`, `LES_FGIS_VIA_SSH` | Реализовано; query-time читает локальные снимки |
| Smetnoedelo API | Дополнительный импорт норм | `https://api.smetnoedelo.ru/cs/` | конфигурация импортера | Не расчётная истина |
| Google Drive | Облачная папка → mirror → ingestion | `https://www.googleapis.com/drive/v3` | `LES_GOOGLE_DRIVE_ACCESS_TOKEN`, `LES_CLOUD_DRIVE_MIRROR_ROOT` | OAuth не настроен |
| Яндекс Диск | Облачная папка → mirror → ingestion | `https://cloud-api.yandex.net/v1/disk` | `LES_YANDEX_DISK_TOKEN`, `LES_CLOUD_DRIVE_MIRROR_ROOT` | Web API не настроен; локальная sync-папка обнаружена |
| IMAP | Почта → `.eml` → `MAIL_Index` | IMAP/IMAPS | `MAIL_IMAP_*`, `MAIL_IMAP_POLL_SEC` | Не настроен |
| KАЦ web discovery | Кандидаты ценовых предложений | публичный web, DuckDuckGo HTML | policy/timeout KAC service | Опционально; не нормативная цена сама по себе |
| P.A.U.K. / VPS | Публичный вход `les.ovc.me` | reverse SSH + HTTPS | ключи вне git | Эксплуатационный вход |
| ZeroTier | Приватный доступ и trusted auth | `10.195.146.0/24` | `TRUSTED_NETWORKS`, `TRUSTED_PROXY_*` | Включено |
| Speckle | Ранее живой GraphQL-коннектор | ранее `https://speckle.ovc.me/graphql` | legacy `SPECKLE_*` | **Удалено 2026-06-14**; `/api/speckle/*` возвращает 404 |

### Важная граница ФГИС

Сеть ФГИС используется для **обновления локальных источников**, а не для каждого ответа модели.
Горячий расчёт раскрывает норму и цену из локальных версионированных SQLite/Parquet/manifest.

Операторские endpoint’ы:

- `POST /api/service-sources/fgis/update` и `GET .../status` — полный update цен;
- `POST /api/service-sources/gesn_base/fgis-update` и `GET .../status` — pipeline ГЭСН;
- `GET /api/prices/sources/subjects`, `GET /api/prices/sources/periods` — навигация;
- `POST /api/prices/update` — обновление выбранной книги.

## 7. Конфигурация без секретов

| Контур | Переменные |
|---|---|
| Proxy/MLX/Qdrant | `MLX_URL`, `MLX_MODEL`, `LLM_MODEL`, `QDRANT_URL`, `RAG_COLLECTION_NAME`, `RAG_META_DB_PATH` |
| Cloud LLM | `LES_CLOUD_CONSENT`, `OPENAI_BASE_URL/MODEL/API_KEY`, `OPENROUTER_BASE_URL/MODEL/API_KEY` |
| Локальные альтернативы | `OLLAMA_BASE_URL/MODEL/API_KEY`, `LEMONADE_BASE_URL/MODEL/API_KEY` |
| Сметная модель | `LES_SMETA_DOCUMENT_PROVIDER`, `LES_SMETA_DOCUMENT_MODEL` |
| ФГИС | `LES_FGIS_TIMEOUT`, `LES_FGIS_FILE_TIMEOUT`, `LES_FGIS_VIA_SSH`, `LES_DEFAULT_PRICEBOOK` |
| Cloud drives | `LES_GOOGLE_DRIVE_ACCESS_TOKEN`, `LES_YANDEX_DISK_TOKEN`, `LES_CLOUD_DRIVE_MIRROR_ROOT` |
| Почта | `MAIL_IMAP_*`, `MAIL_ATTACHMENT_*`, `MAIL_VLM_*` |
| Доступ | `TRUSTED_NETWORKS`, `TRUSTED_NETWORK_ROLE`, `TRUSTED_PROXY_NETWORKS`, `TRUSTED_PROXY_HEADER` |
| Speckle legacy | `SPECKLE_*` не означает наличие живого коннектора |

`GET /api/settings` возвращает безопасный операторский снимок: URL, модели и только булевы
`*_key_set` / `*_password_set`. Секреты обратно не выдаются.

## 8. Текущее состояние и риски

Снимок на 2026-07-12:

- cloud LLM включён через OpenAI-compatible ProxyAPI, модель `gpt-5.4`;
- локальный основной MLX в settings — `mlx-community/Qwen3.5-9B-OptiQ-4bit`;
- Google Drive и Яндекс Disk Web API не настроены, локальная папка Яндекс Диска обнаружена;
- IMAP не настроен; Speckle-коннектор отсутствует;
- `/api/version` показывает `runtime_alignment.status=divergent`;
- live RAG health `degraded` из-за pending/error файлов — это состояние корпуса, не отсутствие API.

Риски:

1. `env.example` содержит исторические переменные. Наличие переменной не доказывает живую интеграцию.
2. OpenAPI не различает user/admin роль формально; dependency в коде — источник истины.
3. `/lite-api/*` — мост: сбой возможен в Совушке, proxy, auth или reverse tunnel.
4. Background status может устареть после смерти процесса; проверять `running/pid` и `updated_at`.
5. Внешний источник становится evidence только после intake, версии и provenance.

## 9. Где менять и проверять

| Задача | Код/источник |
|---|---|
| Proxy routers | `proxy/app.py`, `proxy/routers/*.py` |
| Маршрутизация LLM | `proxy/routers/chat.py`, `proxy/services/runtime_admission.py` |
| Настройки providers | `proxy/routers/settings.py`, `env.example` |
| Lite bridge | `sovushka/lite_bridge.py`, `sovushka_ng.py` |
| MLX API | `mlx_host.py` |
| Qdrant/RAG | `backend/qdrant_adapter.py`, `proxy/services/retrieval_service.py` |
| Cloud drives | `proxy/services/cloud_drive_service.py`, `proxy/routers/datasets.py` |
| IMAP | `backend/mail_ingest.py`, `proxy/routers/mail.py` |
| ФГИС | `proxy/services/fgis_*_service.py`, `proxy/routers/prices.py`, `proxy/routers/service_sources.py` |
| Туннели | `dev/TUNNELS_AND_REMOTE_ACCESS.md` |
| Авторизация | `proxy/security.py`, `proxy/routers/auth.py` |

## Приложение A. Полный реестр proxy endpoint’ов

Реестр ниже снят из живого `http://127.0.0.1:8050/openapi.json`. После изменения роутов его следует переснять.

| Метод | Путь | Tag | OpenAPI summary |
|---|---|---|---|
| `GET` | `/` | status-page | Status Page |
+| `GET` | `/` | status-page | Status Page |
| `GET` | `/api/auth/keys` | auth | Auth List Keys |
| `POST` | `/api/auth/keys` | auth | Auth Create Key |
| `POST` | `/api/auth/keys/delete` | auth | Auth Delete Key Body |
| `POST` | `/api/auth/keys/reset-device` | auth | Auth Reset Device |
| `POST` | `/api/auth/keys/toggle` | auth | Auth Toggle Key |
| `DELETE` | `/api/auth/keys/{key_value}` | auth | Auth Delete Key |
| `GET` | `/api/auth/trust` | auth | Auth Trust |
| `POST` | `/api/auth/verify` | auth | Auth Verify |
| `GET` | `/api/backup/archives` | runtime | List Backup Archives |
| `POST` | `/api/backup/create` | runtime | Create Backup |
| `POST` | `/api/backup/delete` | runtime | Delete Backup |
| `POST` | `/api/backup/restore` | runtime | Restore Backup |
| `GET` | `/api/backup/status` | runtime | Get Backup Status |
| `GET` | `/api/bor/reconcile` | bor | Reconcile Preview |
| `GET` | `/api/bor/reconcile/download` | bor | Reconcile Download |
| `POST` | `/api/bor/reconcile/generate` | bor | Reconcile Generate |
| `GET` | `/api/bor/{dataset_id}/download` | bor | Bor Download |
| `GET` | `/api/bor/{dataset_id}/from-spec` | bor | Spec Bor Preview |
| `GET` | `/api/bor/{dataset_id}/from-spec/download` | bor | Spec Bor Download |
| `POST` | `/api/bor/{dataset_id}/from-spec/generate` | bor | Spec Bor Generate |
| `POST` | `/api/bor/{dataset_id}/generate` | bor | Bor Generate |
| `GET` | `/api/bor/{dataset_id}/plan-fact` | bor | Plan Fact Preview |
| `GET` | `/api/bor/{dataset_id}/plan-fact/download` | bor | Plan Fact Download |
| `POST` | `/api/bor/{dataset_id}/plan-fact/generate` | bor | Plan Fact Generate |
| `GET` | `/api/bor/{dataset_id}/preview` | bor | Bor Preview |
| `GET` | `/api/cad-bim/element` | cad-bim | Cad Bim Element Context |
| `GET` | `/api/cad-bim/graph/summary` | cad-bim | Cad Bim Graph Summary |
| `GET` | `/api/cad-bim/highlight` | cad-bim | Cad Bim Get Highlight |
| `POST` | `/api/cad-bim/highlight` | cad-bim | Cad Bim Set Highlight |
| `POST` | `/api/cad-bim/import` | cad-bim | Cad Bim Import |
| `GET` | `/api/cad-bim/imports` | cad-bim | Cad Bim Imports |
| `GET` | `/api/cad-bim/source` | cad-bim | Cad Bim Source |
| `POST` | `/api/chat` | chat | Chat |
| `POST` | `/api/chat/attachments` | search | Create Chat Attachment |
| `GET` | `/api/chat/history` | chat | Get Chat History |
| `POST` | `/api/chat/history/{history_id}/feedback` | chat | Save Chat Feedback |
| `GET` | `/api/chat/learning` | chat | Get Learning History |
| `GET` | `/api/chat/memory/{session_id}` | chat | Get Chat Memory |
| `GET` | `/api/chat/sessions` | chat | Get Chat Sessions |
| `POST` | `/api/chat/stream` | chat | Chat Stream |
| `GET` | `/api/commands` | chat | List Chat Commands |
| `GET` | `/api/decisions` | decisions | Decisions List |
| `POST` | `/api/decisions` | decisions | Decisions Create |
| `GET` | `/api/decisions/{decision_id}` | decisions | Decisions Get |
| `PATCH` | `/api/decisions/{decision_id}` | decisions | Decisions Status |
| `POST` | `/api/decisions/{new_id}/supersedes/{old_id}` | decisions | Decisions Supersede |
| `GET` | `/api/diag` | diagnostics | Run Diagnostics |
| `GET` | `/api/diff/cad-bim` | diff | Cad Bim Diff |
| `GET` | `/api/diff/cad-bim/imports` | diff | Cad Bim Imports |
| `POST` | `/api/diff/text` | diff | Text Diff |
| `GET` | `/api/doc-review/rulepacks` | doc-review | Doc Review Rulepacks |
| `POST` | `/api/doc-review/{dataset_id}/decision` | doc-review | Doc Review Set Decision |
| `GET` | `/api/doc-review/{dataset_id}/decisions` | doc-review | Doc Review Decisions |
| `GET` | `/api/doc-review/{dataset_id}/download` | doc-review | Doc Review Download |
| `POST` | `/api/doc-review/{dataset_id}/run` | doc-review | Doc Review Run |
| `GET` | `/api/documents/by-id/{doc_id}` | documents | Document By Id |
| `GET` | `/api/documents/by-id/{doc_id}/chunks` | documents | Document Chunks By Id |
| `POST` | `/api/documents/by-id/{doc_id}/open-native` | documents | Open Document Native |
| `GET` | `/api/documents/datasets` | documents | Document Datasets |
| `GET` | `/api/documents/datasets/{dataset_id}/chunks/{doc_name}` | documents | Document Chunks |
| `GET` | `/api/documents/datasets/{dataset_id}/documents` | documents | Dataset Documents |
| `GET` | `/api/documents/search` | documents | Document Search |
| `GET` | `/api/edges` | edges | Edges List |
| `POST` | `/api/edges/backfill` | edges | Edges Backfill |
| `GET` | `/api/edges/for` | edges | Edges For |
| `GET` | `/api/estimates/item/{estimate_id}` | estimates | Estimate Get |
| `GET` | `/api/estimates/{project_id}` | estimates | Estimates List |
| `POST` | `/api/estimates/{project_id}/import` | estimates | Estimate Import |
| `GET` | `/api/external-radar/summary` | external-radar | External Radar Summary |
| `POST` | `/api/extract/structured` | extract | Structured |
| `POST` | `/api/field` | field | Field Create |
| `GET` | `/api/field` | field | Field List |
| `GET` | `/api/field/download` | field | Field Download |
| `POST` | `/api/field/export` | field | Field Export |
| `POST` | `/api/field/extract-asbuilt` | field | Field Extract Asbuilt |
| `GET` | `/api/field/summary` | field | Field Summary |
| `PATCH` | `/api/field/{entry_id}` | field | Field Patch |
| `DELETE` | `/api/field/{entry_id}` | field | Field Delete |
| `GET` | `/api/filemap/candidates` | filemap | Filemap Candidates |
| `POST` | `/api/filemap/index` | filemap | Filemap Index |
| `POST` | `/api/filemap/scan` | filemap | Filemap Scan |
| `GET` | `/api/filemap/search` | filemap | Filemap Search |
| `GET` | `/api/filemap/stats` | filemap | Filemap Stats |
| `GET` | `/api/forms` | forms | Forms List |
| `GET` | `/api/forms/{form_id}/download` | forms | Forms Download |
| `GET` | `/api/forms/{form_id}/fields` | forms | Forms Fields |
| `POST` | `/api/forms/{form_id}/generate` | forms | Forms Generate |
| `GET` | `/api/health` | runtime | Health |
| `GET` | `/api/incoming-control/{project_id}/act/{control_id}` | incoming-control | Act |
| `GET` | `/api/incoming-control/{project_id}/download` | incoming-control | Download |
| `POST` | `/api/incoming-control/{project_id}/export` | incoming-control | Export |
| `GET` | `/api/incoming-control/{project_id}/journal` | incoming-control | Journal |
| `GET` | `/api/incoming-control/{project_id}/quality-docs` | incoming-control | Quality Docs |
| `POST` | `/api/incoming-control/{project_id}/quality-docs` | incoming-control | Add Quality Doc |
| `POST` | `/api/incoming-control/{project_id}/records` | incoming-control | Add Record |
| `GET` | `/api/indexing-mode` | runtime | Get Indexing Mode |
| `POST` | `/api/indexing-mode` | runtime | Set Indexing Mode |
| `GET` | `/api/jobs` | jobs | Get Jobs |
| `GET` | `/api/jobs/summary` | jobs | Get Jobs Summary |
| `POST` | `/api/kac/analyze` | kac | Kac Analyze |
| `GET` | `/api/kac/download` | kac | Kac Download |
| `POST` | `/api/kac/generate` | kac | Kac Generate |
| `POST` | `/api/kac/lsr-lines` | kac | Kac Lsr Lines |
| `GET` | `/api/kac/needs` | kac | Kac Needs |
| `GET` | `/api/les-md/context/{project_id}` | les_md | Les Md Context |
| `POST` | `/api/les-md/draft` | les_md | Les Md Draft |
| `POST` | `/api/les-md/read` | les_md | Les Md Read |
| `GET` | `/api/live` | runtime | Live Stream |
| `GET` | `/api/logs/recent` | logs | Recent Logs |
| `GET` | `/api/logs/stream` | logs | Log Stream |
| `POST` | `/api/lsr/assemble` | lsr | Lsr Assemble |
| `GET` | `/api/lsr/download` | lsr | Lsr Download |
| `POST` | `/api/lsr/export` | lsr | Lsr Export |
| `GET` | `/api/lsr/gesn` | lsr | Gesn List |
| `GET` | `/api/lsr/gesn/{code}/expand` | lsr | Gesn Expand |
| `POST` | `/api/lsr/lsr-trace` | lsr | Lsr Multi Trace |
| `POST` | `/api/lsr/lsr-trace/export` | lsr | Lsr Multi Trace Export |
| `POST` | `/api/lsr/lsr-trace/from-rows` | lsr | Lsr Multi Trace From Rows |
| `POST` | `/api/lsr/lsr-trace/from-rows/export` | lsr | Lsr Multi Trace From Rows Export |
| `GET` | `/api/lsr/norms/browse` | lsr | Smeta Norm Browse |
| `POST` | `/api/lsr/rim-trace` | lsr | Lsr Rim Trace |
| `POST` | `/api/lsr/rim-trace/export` | lsr | Lsr Rim Trace Export |
| `POST` | `/api/lsr/stesnennost/apply` | lsr | Stesn Apply |
| `GET` | `/api/lsr/stesnennost/conditions` | lsr | Stesn Conditions |
| `POST` | `/api/mail/import-apple-mail` | mail | Import Apple Mail |
| `POST` | `/api/mail/import-archive` | mail | Import Mail Archive |
| `POST` | `/api/mail/import-imap` | mail | Import Imap Mail |
| `POST` | `/api/mail/import-local` | mail | Import Local Mail |
| `GET` | `/api/mail/messages` | mail | List Mail Messages |
| `POST` | `/api/mail/push` | mail | Push Mail |
| `GET` | `/api/mail/status` | mail | Mail Status |
| `GET` | `/api/mail/threads` | mail | List Mail Threads |
| `GET` | `/api/mail/threads/{thread_key}` | mail | Get Mail Thread |
| `GET` | `/api/metrics` | runtime | Get Metrics |
| `GET` | `/api/mode` | runtime | Get Mode |
| `POST` | `/api/mode` | runtime | Set Mode |
| `GET` | `/api/normcontrol/{dataset_id}/download` | normcontrol | Normcontrol Download |
| `POST` | `/api/normcontrol/{dataset_id}/run` | normcontrol | Normcontrol Run |
| `POST` | `/api/notebooks/warmup` | notebooks | Warmup Notebooks |
| `GET` | `/api/notebooks/{dataset_id}` | notebooks | Dataset Notebook |
| `GET` | `/api/notebooks/{dataset_id}/memory` | notebooks | Dataset Typed Memory |
| `POST` | `/api/notebooks/{dataset_id}/memory/read` | notebooks | Read Dataset Memory |
| `POST` | `/api/notebooks/{dataset_id}/memory/refresh` | notebooks | Refresh Dataset Typed Memory |
| `POST` | `/api/notes` | notes | Notes Create |
| `GET` | `/api/notes` | notes | Notes List |
| `DELETE` | `/api/notes/{note_id}` | notes | Notes Delete |
| `GET` | `/api/ontology/backbone` | ontology | Ontology Backbone |
| `GET` | `/api/ontology/cde-summary` | ontology | Containers Cde Summary |
| `GET` | `/api/ontology/containers` | ontology | Containers List |
| `POST` | `/api/ontology/containers` | ontology | Containers Register |
| `POST` | `/api/ontology/containers/state` | ontology | Containers Set State |
| `POST` | `/api/ontology/containers/supersede` | ontology | Containers Supersede |
| `GET` | `/api/ontology/elements` | ontology | Ontology Elements |
| `GET` | `/api/ontology/lbs` | ontology | Ontology Lbs |
| `GET` | `/api/prices/books` | prices | Prices Books |
| `POST` | `/api/prices/import` | prices | Prices Import |
| `GET` | `/api/prices/lookup` | prices | Prices Lookup |
| `POST` | `/api/prices/lookup-batch` | prices | Prices Lookup Batch |
| `GET` | `/api/prices/needs` | prices | Prices Needs |
| `GET` | `/api/prices/search` | prices | Prices Search |
| `GET` | `/api/prices/sources/periods` | prices | Prices Sources Periods |
| `GET` | `/api/prices/sources/subjects` | prices | Prices Sources Subjects |
| `POST` | `/api/prices/update` | prices | Prices Update |
| `GET` | `/api/projects` | projects | Projects List |
| `POST` | `/api/projects` | projects | Projects Create |
| `GET` | `/api/projects/{project_id}` | projects | Projects Get |
| `PATCH` | `/api/projects/{project_id}` | projects | Projects Status |
| `DELETE` | `/api/projects/{project_id}` | projects | Projects Delete |
| `GET` | `/api/projects/{project_id}/dossier` | projects | Projects Dossier |
| `POST` | `/api/projects/{project_id}/links` | projects | Projects Link |
| `GET` | `/api/projects/{project_id}/links` | projects | Projects Links |
| `DELETE` | `/api/projects/{project_id}/links` | projects | Projects Unlink |
| `GET` | `/api/prompts` | prompts | List Prompts |
| `PATCH` | `/api/prompts/{prompt_key}` | prompts | Update Prompt |
| `DELETE` | `/api/prompts/{prompt_key}` | prompts | Reset Prompt |
| `POST` | `/api/rag/attach` | rag | Attach Chat File |
| `GET` | `/api/rag/browse-external` | rag | Browse External |
| `GET` | `/api/rag/cloud-drives` | rag | Cloud Drives |
| `POST` | `/api/rag/cloud-drives/list` | rag | Cloud Drive List |
| `POST` | `/api/rag/cloud-drives/sync` | rag | Cloud Drive Sync |
| `DELETE` | `/api/rag/datasets` | rag | Delete All Datasets |
| `GET` | `/api/rag/datasets` | rag | List Datasets |
| `POST` | `/api/rag/datasets` | rag | Create Dataset |
| `POST` | `/api/rag/datasets/profiles/benchmark` | rag | Benchmark Dataset Context Profiles |
| `POST` | `/api/rag/datasets/profiles/warmup` | rag | Warmup Dataset Context Profiles |
| `DELETE` | `/api/rag/datasets/{dataset_id}` | rag | Delete Dataset |
| `GET` | `/api/rag/datasets/{dataset_id}/document-registry` | rag | Document Registry Endpoint |
| `POST` | `/api/rag/datasets/{dataset_id}/document-registry/build` | rag | Document Registry Build Endpoint |
| `POST` | `/api/rag/datasets/{dataset_id}/extract-body/dry-run` | rag | Extract Body Dry Run |
| `POST` | `/api/rag/datasets/{dataset_id}/extract-body/write` | rag | Extract Body Write |
| `GET` | `/api/rag/datasets/{dataset_id}/extraction-status` | rag | Extraction Status Endpoint |
| `PATCH` | `/api/rag/datasets/{dataset_id}/group` | rag | Set Dataset Group |
| `POST` | `/api/rag/datasets/{dataset_id}/pdf-extract/run` | rag | Pdf Extract Run Endpoint |
| `GET` | `/api/rag/datasets/{dataset_id}/pdf-extract/status` | rag | Pdf Extract Status Endpoint |
| `GET` | `/api/rag/datasets/{dataset_id}/pdf-extract/summary` | rag | Pdf Extract Summary Endpoint |
| `GET` | `/api/rag/datasets/{dataset_id}/profile` | rag | Dataset Context Profile |
| `PATCH` | `/api/rag/datasets/{dataset_id}/profile/guidance` | rag | Update Dataset Operator Guidance |
| `PATCH` | `/api/rag/datasets/{dataset_id}/profile/kind` | rag | Update Dataset Kind |
| `POST` | `/api/rag/datasets/{dataset_id}/profile/refresh` | rag | Refresh Dataset Context Profile |
| `POST` | `/api/rag/datasets/{dataset_id}/reconcile` | rag | Reconcile Dataset Endpoint |
| `POST` | `/api/rag/datasets/{dataset_id}/repair` | rag | Repair Dataset |
| `PATCH` | `/api/rag/datasets/{dataset_id}/sensitivity` | rag | Set Dataset Sensitivity |
| `POST` | `/api/rag/datasets/{dataset_id}/table-registry/build` | rag | Table Registry Build Endpoint |
| `GET` | `/api/rag/datasets/{dataset_id}/table-registry/summary` | rag | Table Registry Summary Endpoint |
| `GET` | `/api/rag/datasets/{dataset_id}/tables/search` | rag | Table Registry Search Endpoint |
| `GET` | `/api/rag/datasets/{dataset_id}/tables/{table_id}` | rag | Table Registry Read Endpoint |
| `GET` | `/api/rag/datasets/{dataset_id}/virtual-volume` | rag | Virtual Volume Endpoint |
| `GET` | `/api/rag/documents` | rag | List Documents |
| `POST` | `/api/rag/external/check` | rag | Check External Dataset |
| `POST` | `/api/rag/external/intake-plan` | rag | External Intake Plan |
| `POST` | `/api/rag/external/sync` | rag | Sync External Dataset |
| `GET` | `/api/rag/file/raw` | files | Rag File Raw |
| `GET` | `/api/rag/file/text` | files | Rag File Text |
| `GET` | `/api/rag/graph/edges` | rag | Graph Reference Edges |
| `GET` | `/api/rag/graph/full` | rag | Graph Full |
| `POST` | `/api/rag/index-external` | rag | Index External |
| `POST` | `/api/rag/parse-batch/{dataset_id}` | rag | Parse Dataset Batch |
| `POST` | `/api/rag/parse-scheduler` | rag | Parse Scheduler |
| `GET` | `/api/rag/readiness` | rag | Get Rag Readiness |
| `POST` | `/api/rag/retrieve-debug` | rag | Retrieve Debug |
| `GET` | `/api/rag/smart-plan` | rag | Smart Plan |
| `GET` | `/api/rag/sources` | rag | List Sources |
| `POST` | `/api/rag/sync-smart` | rag | Sync Smart |
| `POST` | `/api/rag/sync/{folder}` | rag | Sync Folder |
| `GET` | `/api/rag/tree` | files | Rag Tree |
| `POST` | `/api/rag/upload-smart` | rag | Upload File Smart |
| `POST` | `/api/rag/upload/{dataset_id}` | rag | Upload File |
| `GET` | `/api/rag/watch/reindex-plan` | rag | Folder Reindex Plan |
| `POST` | `/api/rag/watch/scan` | rag | Folder Watch Scan |
| `GET` | `/api/rag/watch/status` | rag | Folder Watch Status |
| `POST` | `/api/rerank` | rerank | Rerank Direct |
| `POST` | `/api/runtime/dispatcher/mlx/unload` | runtime | Runtime Dispatcher Mlx Unload |
| `POST` | `/api/runtime/dispatcher/reindex/pause` | runtime | Runtime Dispatcher Reindex Pause |
| `POST` | `/api/runtime/dispatcher/reindex/resume` | runtime | Runtime Dispatcher Reindex Resume |
| `POST` | `/api/runtime/dispatcher/reindex/start` | runtime | Runtime Dispatcher Reindex Start |
| `POST` | `/api/runtime/dispatcher/route-changes/pause` | runtime | Runtime Dispatcher Route Changes Pause |
| `POST` | `/api/runtime/dispatcher/route-changes/start` | runtime | Runtime Dispatcher Route Changes Start |
| `GET` | `/api/runtime/dispatcher/route-changes/status` | runtime | Runtime Dispatcher Route Changes Status |
| `GET` | `/api/runtime/dispatcher/status` | runtime | Runtime Dispatcher Status |
| `GET` | `/api/scope/options` | runtime | Scope Options Endpoint |
| `POST` | `/api/scope/resolve` | runtime | Scope Resolve Endpoint |
| `POST` | `/api/search` | search | Search |
| `GET` | `/api/service-sources` | service-sources | List Service Sources |
| `POST` | `/api/service-sources/fgis/update` | service-sources | Fgis Update |
| `GET` | `/api/service-sources/fgis/update/status` | service-sources | Fgis Update Status |
| `POST` | `/api/service-sources/gesn_base/fgis-update` | service-sources | Gesn Fgis Update |
| `GET` | `/api/service-sources/gesn_base/fgis-update/status` | service-sources | Gesn Fgis Update Status |
| `GET` | `/api/service-sources/notebooks` | service-sources | List Service Source Notebooks |
| `GET` | `/api/service-sources/{source_id}` | service-sources | Get Service Source |
| `POST` | `/api/service-sources/{source_id}/process` | service-sources | Process Source |
| `GET` | `/api/settings` | settings | Get Settings |
| `POST` | `/api/settings` | settings | Save Settings |
| `POST` | `/api/settings/mlx-model` | settings | Set Mlx Model |
| `POST` | `/api/settings/preset` | settings | Set Preset |
| `GET` | `/api/settings/presets` | settings | List Presets |
| `GET` | `/api/smeta-artifacts/download` | chat | Smeta Artifact Download |
| `GET` | `/api/status` | runtime | Get Status |
| `POST` | `/api/tasks` | tasks | Tasks Create |
| `GET` | `/api/tasks` | tasks | Tasks List |
| `PATCH` | `/api/tasks/{task_id}` | tasks | Tasks Patch |
| `POST` | `/api/tools/call` | tools | Tool Call |
| `GET` | `/api/tools/filesystem/list` | tools | Filesystem List |
| `GET` | `/api/tools/filesystem/roots` | tools | Filesystem Roots |
| `GET` | `/api/tools/registry` | tools | Tool Registry |
| `POST` | `/api/tools/shortlist` | tools | Tool Shortlist |
| `POST` | `/api/verify/extract` | verify | Verify Extract |
| `GET` | `/api/verify/image` | verify | Verify Image |
| `GET` | `/api/verify/list` | verify | Verify List |
| `POST` | `/api/verify/save` | verify | Verify Save |
| `GET` | `/api/version` | runtime | Version |
| `POST` | `/api/warmup` | runtime | Warmup Models |
| `GET` | `/api/worklog/{project_id}` | worklog | Worklog Get |
| `GET` | `/api/worklog/{project_id}/download` | worklog | Worklog Download |
| `POST` | `/api/worklog/{project_id}/export` | worklog | Worklog Export |
| `PATCH` | `/api/worklog/{project_id}/meta` | worklog | Worklog Set Meta |
