# Версии программного контура ЛЕС

Канонический паспорт совместимости. Версия продукта и номер сборки берутся только из
[`config/version.json`](../config/version.json). Полный Python-граф фиксирует `uv.lock`.

## Версия ЛЕС

| Поле | Значение | Назначение |
|---|---:|---|
| Версия продукта | `0.29.0` | Единственный пользовательский номер по схеме `X.Y.Z` |
| Номер сборки | `592` | Монотонный номер Windows-пакета; не является четвёртой частью версии |
| Версия пакета Tauri/NSIS | `5.1.592` | Внутренняя монотонная версия установщика для обновления существующих `5.1.x` |
| Схема строительного контура | `0.24` | Внутренняя версия контракта; в пользовательский номер не входит |

`0.28.2` — release candidate с идемпотентным offline bootstrap, optional Docker/Qdrant,
ограничениями profile text и GitHub Releases update channel. Статус фактической установки и публикации фиксируется только в
`docs/RELEASE_LEDGER.md`. Новая несовместимая возможность получает следующий minor SemVer;
готовый стабильный продукт — `1.0.0`.

## Рабочий контур Windows

Снимок проверен на контрольной Windows-машине 14 июля 2026 года. «Проверено» описывает воспроизведённую среду, а не
разрешение бесконтрольно обновлять компоненты.

| Компонент | Зафиксировано в проекте | Проверено на Legion | Роль |
|---|---|---|---|
| Windows | Windows 11 x64 | Windows 11 Pro `10.0.26200` | Целевая рабочая система |
| Python | bundled portable CPython `3.13.12`, SHA-256 проверяется при staging и перед распаковкой без MSI/реестра; `uv` запрещено скачивать интерпретатор | `3.13.12` | API, интерфейс, обработка документов |
| uv | bundled `0.11.29`, SHA-256 проверяется при staging/bootstrap; exact lock + offline cache, без system/network fallback | release smoke обязателен | Среда и воспроизводимые зависимости |
| Docker Desktop | внешний optional runtime, версия не зашита | Docker `29.3.1` | Один из способов локального запуска Qdrant |
| Qdrant | `qdrant/qdrant:v1.17.1` | `1.17.1` | Dense и sparse индексы, нативный RRF |
| Ollama | внешний user-managed runtime; wizard показывает status и официальный адрес | `0.31.1` | Один из локальных answer/embedding providers |
| Основная модель | выбирается пользователем в настроенном provider; у ЛЕС нет обязательной модели | Big Qwen и `qwen3.5:9b` проверялись отдельно | Ответы и работа с инструментами |
| FreeToken | внешний loopback OpenAI-compatible runtime, запускаемый своим GUI | `0.1.1+g30aa89115` | Альтернативная локальная генерация; ЛЕС не запускает второй engine |
| FreeToken Big Qwen | выбирается оператором в FreeToken GUI | `Qwen3.6-35B-A3B-NVFP4`, API metadata context `262144`; live accepted `28001` input + `512` reserve, GUI window `30000`; derived LES prompt cap `57600` chars | Большая локальная MoE-модель; transport принудительно отключает thinking, сохраняет dialogue memory и наполняет общий multi-document evidence до безопасной capacity |
| Эмбеддер | отдельная user-configured роль; опубликованный индекс требует совместимую identity/размерность | `bge-m3:latest`, `1024` в принятом корпусе | Dense-векторы |
| ColBERT late interaction | `BAAI/bge-m3`, token vectors `1024`; optional, GUI-controlled | требует live preflight/сборку sibling generation для `0.27.54` | MaxSim rerank до общего cross-encoder |
| RAPTOR summarizer | local Ollama `qwen3.5:9b` или deterministic extractive fallback; optional, GUI-controlled | требует live publication acceptance для `0.27.54` | Navigation-only summary tree; не evidence |
| Реранжировщик | `BAAI/bge-reranker-v2-m3`, optional и выключен по умолчанию | отдельный `sentence-transformers` вес проверялся | Экспериментальный реранк после RRF; отсутствие сохраняет RRF |

`latest` запрещён для Qdrant: изменение серверной версии способно изменить формат хранения и
поведение поиска без изменения кода ЛЕС. Для моделей Ollama тег остаётся частью их идентификатора;
перед заменой фактического содержимого модели нужен отдельный контроль качества.

## Сборочный контур Windows

Эти программы нужны на Windows-сборщике для создания EXE, но не устанавливаются пользователю вместе с ЛЕС.

| Компонент | Зафиксировано | Проверено на Legion |
|---|---|---|
| Node.js | lock-файл npm | `24.14.0` |
| npm | `package-lock.json` | `11.9.0` |
| Rust | `Cargo.lock` | `rustc 1.97.0`, Cargo `1.97.0` |
| Tauri CLI | `2.11.4` | `2.11.4` |
| Tauri | `2.11.5` | собирается Cargo |
| tauri-build | `2.6.3` | собирается Cargo |

## Python-пакеты ядра

Точные версии читаются из `uv.lock`. На текущем зафиксированном графе ключевые пакеты:

| Пакет | Версия |
|---|---:|
| FastAPI | `0.136.1` |
| NiceGUI | `3.12.0` |
| qdrant-client | `1.18.0` |
| ollama (Python-клиент) | `0.6.2` |
| Qwen-Agent | `0.0.34` |
| Google ADK | `2.5.0` |
| Google GenAI | `2.12.1` |
| Starlette | `1.3.1` |
| websockets | `15.0.1` |
| pytest | `9.0.3` |

## Правило обновления компонентов

1. Не использовать плавающий образ инфраструктуры.
2. Сначала изменить этот паспорт и lock/config.
3. Прогнать `make test`, `make test-rag-core` и живой Windows-smoke.
4. Для Qdrant дополнительно проверить существующий named volume и откат.
5. Для модели повторить качество инструментов, RAG и сметного сценария.
