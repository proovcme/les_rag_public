# API и внешние подключения ЛЕС

Этот документ описывает публичный сетевой контракт без снимка конкретной установки. Адреса частных машин, активные модели, API-ключи и факт настройки пользовательского provider не являются частью документации продукта.

## Узлы и адреса по умолчанию

| Узел | Локальный адрес | Назначение |
|---|---|---|
| Backend ЛЕС | `http://127.0.0.1:8050` | FastAPI, документы, RAG, память, инструменты и runtime status |
| Совушка | `http://127.0.0.1:8051` | NiceGUI для Tauri, browser и PWA |
| Qdrant | `http://127.0.0.1:6333` | Внешний vector store; адрес задаётся конфигурацией |
| Model endpoint | задаётся пользователем | OpenAI-compatible generation или embeddings |

`https://les.ovc.me` — отдельный публичный симулятор леса и homepage проекта. Он не является endpoint ЛЕС, update origin, proxy, fallback или хранилищем release assets.

## Режимы размещения

- `full`: backend и Совушка на одном узле;
- `backend`: только headless API;
- `ui`: Совушка подключается к явно указанному backend;
- модели и Qdrant могут находиться на том же узле или в доверенной сети.

Публичный интернет-доступ не включается по умолчанию. LAN/ZeroTier адрес считается `private_network`; удалённый provider должен использовать HTTPS. Конкретные IP/CIDR принадлежат установке пользователя и не публикуются в репозитории.

## Основные API

| Группа | Примеры |
|---|---|
| Состояние | `GET /api/health`, `GET /api/version`, `GET /api/status` |
| Чат | `POST /api/chat`, `POST /api/chat/stream` |
| Документы | `/api/documents/*`, `/api/rag/datasets*`, `/api/rag/upload*` |
| Поиск | `POST /api/search`, `POST /api/rag/retrieve-debug` |
| Модели | `/api/model-connections*` |
| Инструменты | `GET /api/tools/registry`, `POST /api/tools/shortlist`, `POST /api/tools/call` |
| Конфигурация | `/api/runtime/*`, `/api/settings/*` |

Точная схема текущего runtime: `GET /openapi.json`; интерактивное представление: `GET /docs`. Статический список маршрутов в документации не является источником истины и поэтому здесь не дублируется.

## Подключения моделей

Модель регистрируется через backend ЛЕС. Публичная browser-проекция не получает API secret и не обращается к model endpoint напрямую.

Для подключения задаются:

- protocol `openai_compatible`;
- base URL;
- model ID;
- locality: loopback, private network или remote;
- requested context;
- masked secret, если он требуется.

Роли `answer`, `embeddings` и `local_fallback` назначаются независимо. Успешный models probe не доказывает поддержку streaming, tools или embeddings: каждая capability проверяется отдельно.

## Qdrant и retrieval

Qdrant — внешний HTTP-сервис. LES installer не устанавливает и не запускает его. Docker может использоваться самим пользователем, но не входит в lifecycle продукта.

Production collection содержит named `dense` и `bm25_sparse` vectors. Retrieval выполняет native RRF, затем lexical safety и parent/context expansion. Отсутствующий Qdrant снижает capability RAG, но не должен блокировать core UI/API.

## Auth и границы доступа

- loopback и явно доверенная сеть могут получать настроенную роль;
- внешний доступ требует явной авторизации;
- административные endpoints нельзя публиковать без отдельного gateway и policy;
- операции с индексом, backup, secrets и runtime settings считаются опасными;
- browser не должен получать endpoint secrets или читать произвольные server paths.

## Облачные provider

При выборе облачного OpenAI-compatible API ему передаётся текст запроса и сформированный evidence-контекст. ЛЕС не переключает локальную модель на облачную молча. Cloud consent и назначение роли должны быть явными, а secret хранится masked.

## Внешние источники

Импорт ФГИС, cloud-drive mirrors, IMAP и другие intake adapters являются отдельными интеграциями. Они не входят в горячий model path автоматически и не считаются настроенными только потому, что код адаптера присутствует в репозитории.

## Для разработчика

Карта реализации: [CODE_MAP.md](CODE_MAP.md). Статусы модулей: [MODULE_INDEX.md](MODULE_INDEX.md). Версии внешнего ПО: [SOFTWARE_VERSIONS.md](SOFTWARE_VERSIONS.md). Публичные границы данных: [public/privacy-and-data-boundaries.md](public/privacy-and-data-boundaries.md).
