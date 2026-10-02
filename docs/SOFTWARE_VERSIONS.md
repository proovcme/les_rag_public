# Версии программного контура ЛЕС

Канонический паспорт совместимости. Версия продукта и номер сборки берутся только из
[`config/version.json`](../config/version.json). Полный Python-граф фиксирует `uv.lock`.

Таблица описывает candidate 0.31.143/build 871; установлен 870
(`7ba406a1d90744b0917b9a4950956df77753fc52`). Canonical 870: 2906 passed /
20 existing opt-in skipped / 5 warnings; architecture и pinned baseline exit0.
Профессиональная приёмка 870 FAILED; capacity delivery 871 source/tests frozen:
initial focused 392 passed (21.54s), fixture admission 119 passed (15.60s).
SECOND canonical 871: 2925 passed / 20 existing opt-in skipped / 5 warnings;
verify/architecture/baseline/active artifacts exit0. Первый FAILED gate 2923 pass /
2 fixture failures сохранён, production source8 не менялся. Candidate READY FOR
INSTALL; installed/live/private exact installer871 pending, native EXE858 retained.
Это не professional proof реальной модели. Native RRF 870 exit0; basic smoke с 90s
дал 8 passed / 1 warning / 1 project-timeout FAIL. Отдельный finite 180s
hardware-calibrated smoke: exit0, 10 PASS / 0 WARN / 0 FAIL за 85.55s;
glossary/project 31.640s/51.438s, оба ниже исходного 90s. Измеренный FreeToken
request p95 128.233s объясняет явный лимит; исходный failed run сохранён.
Техническая доступность не доказывает профессиональное качество.
Фактические receipts и состояние выпуска — [`RELEASE_LEDGER.md`](RELEASE_LEDGER.md).

## Версия ЛЕС

| Поле | Значение | Назначение |
|---|---:|---|
| Версия продукта | `0.31.143` | Единственный пользовательский номер по схеме `X.Y.Z` |
| Номер сборки | `871` | Монотонный номер Windows-пакета; не является четвёртой частью версии |
| Версия пакета Tauri/NSIS | `5.1.871` | Внутренняя монотонная версия установщика для обновления существующих `5.1.x` |
| Схема строительного контура | `0.24` | Внутренняя версия контракта; в пользовательский номер не входит |

`0.29.2` — release candidate с идемпотентным offline bootstrap, внешним Qdrant по HTTP,
ограничениями profile text и GitHub Releases update channel. Docker не входит в lifecycle ЛЕС
и остаётся лишь одним из пользовательских способов запуска Qdrant. Статус фактической установки и публикации фиксируется только в
`docs/RELEASE_LEDGER.md`. Новая несовместимая возможность получает следующий minor SemVer;
готовый стабильный продукт — `1.0.0`.

## Рабочий контур Windows

Снимок проверен на контрольной Windows-машине 29 августа 2026 года. «Проверено» описывает воспроизведённую среду, а не
разрешение бесконтрольно обновлять компоненты.

| Компонент | Зафиксировано в проекте | Проверено на Legion | Роль |
|---|---|---|---|
| Windows | Windows 11 x64 | Windows 11 Pro `10.0.26200` | Целевая рабочая система |
| Python | bundled portable CPython `3.13.12`, SHA-256 проверяется при staging и перед распаковкой без MSI/реестра; `uv` запрещено скачивать интерпретатор | `3.13.12` | API, интерфейс, обработка документов |
| uv | bundled `0.11.29`, SHA-256 проверяется при staging/bootstrap; exact lock + offline cache, без system/network fallback | release smoke обязателен | Среда и воспроизводимые зависимости |
| Docker Desktop | не является runtime ЛЕС; версия не зашита | Docker `29.3.1` | Только один из внешних способов запустить Qdrant |
| Qdrant | внешний HTTP-сервис; container-профили фиксируют `qdrant/qdrant:v1.17.1`, GUI хранит `QDRANT_URL` | native Windows `1.19.0`; существующая collection `les_rag_v563`, 101 366 points | Dense и sparse индексы, нативный RRF |
| Ollama | внешний user-managed runtime; wizard показывает status и официальный адрес | `0.31.1` | Один из локальных answer/embedding providers |
| Основная модель | выбирается пользователем в настроенном provider; у ЛЕС нет обязательной модели | Big Qwen и `qwen3.5:9b` проверялись отдельно | Ответы и работа с инструментами |
| FreeToken | внешний loopback OpenAI-compatible runtime, запускаемый своим GUI | `0.1.1+g30aa89115` | Альтернативная локальная генерация; ЛЕС не запускает второй engine |
| FreeToken Big Qwen | выбирается оператором в FreeToken GUI | `Qwen3.6-35B-A3B-NVFP4`, API metadata context `262144`; LES default window `35000` (factory 35B), rebuild clamps to GPU-feasible KV with min MoE; extended preset needs observed KV ≥ 16384 | Большая локальная MoE-модель; transport принудительно отключает thinking, сохраняет dialogue memory и наполняет общий multi-document evidence до безопасной capacity |
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
