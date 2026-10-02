# Версии программного контура ЛЕС

Канонический паспорт совместимости. Версия продукта и номер сборки берутся только из
[`config/version.json`](../config/version.json). Полный Python-граф фиксирует `uv.lock`.

Таблица описывает candidate `0.31.148`/build`876`/Tauri`5.1.876`;
установлен `0.31.147`/build`875` commit
`cde0a14c0c2a27df38876d1d84956f78e7c7515a`. 876 добавляет явные wire-параметры
подключения и общий renderer probe/inference без provider/model эвристик.
Операторские ограничения контекста/ответа не называются наблюдаемой ёмкостью.
Focused465 passed, full canonical876/install/live pending; dependency graph прежний.
Installed875 technical smoke/repack прошли; professional acceptance не подтверждена.
Состояние и точные receipts — RELEASE_LEDGER, раздел876.

Ниже сохранена историческая запись875 до установки:
candidate `0.31.147`/build`875`/Tauri`5.1.875`;
установлен `0.31.146`/build`874` commit
`c4253e38ea9539eb841e993eb373a42665079c0a`. 875 содержит narrow saved-repack
replay guard и поддержку standalone artifact_kind transport для row decoder.
Native-capacity resume сохраняет literal query state и truthful overflow trace;
read binder резервирует весь original query range до новых native Q refs.
Deferred raw cursor не зависит от native handles и сохраняет исходный alias order.
Reopened review instruction требует все предложенные прежние операции; ordinary
continuation сохраняет delta. Код не восстанавливает omitted review rows.
Pinned pricebook SHA и model-authored rows сохраняются; missing immutable
artifact/checkpoint не запускает новый расчёт под старой identity.
Focused cache100/transport139/native-read143/review316 passed. Second875 gates
после последнего source freeze GREEN: verify25.59s; test3128 passed/20 existing
skipped/5 warnings318.59s (wrapper320.12s); architecture10.42s/baseline7.86s/
active artifacts0.61s, все exit0. Receipts: `artifacts/verify_875_second.exit.json`,
`artifacts/test_875_second.exit.json`, `artifacts/architecture_875_second.exit.json`,
`artifacts/baseline_875_second.exit.json`, `artifacts/active_artifacts_875_second.exit.json`.
Exact install и fresh comparative live875 pending; ready не заявлено.
Installed874 professional FAILED: BAP260.5s, B0~79s без файла, SKS~387s overflow;
EOM821.75s partial ВОР23/56, первое24-row JSON тело потерял parser (875 replay
exact-equal). SKS continue16.56s без answer phase, BAP remark738.11s с файлом
ещё не принят. Готовность заказчику не заявлена.

Следующие замеры относятся к прежнему состоянию872/871:
candidate 0.31.144/build 872; установлен 0.31.143/build 871
(`e8657ba38eed88dac8de327b5e4dd9b2999869f4`). API/GUI и 19 runtime hashes сверены;
native EXE858 retained. Candidate872: UTF-8 Windows prepare fixture, literal
previously-shown full-code navigation при missing exact read и lossless unread
pointer-field aliases. Код не выбирает норму и не расширяет context/GPU budget.
SECOND canonical 871: 2925 passed / 20 existing opt-in skipped / 5 warnings,
verify/architecture/baseline/active artifacts exit0. Private prepare 871 отдельно
сохранил 2924 passed / 1 encoding fixture failure / 20 skipped / 6 warnings
(219.48s). CP866 + UTF-8 Python воспроизвели byte0xaa; после восстановления
production UTF-8 preamble и strict capture — 17 passed (4.18s). Exact prepare872 pending.
Metadata872 verify0 (23.48s), 2945 collected; version/docs/release31 passed (4.99s),
documentation contract0. Полный canonical872 pending.
Installed native RRF871 exit0 (0.91s). Original basic90s: 7 pass / 1 warn /
2 timeout fail (182.59s; wrapper183.91s), glossary/project по90s. Separate finite
180s run: exit0, 10 PASS / 0 WARN / 0 FAIL за112.66s; glossary61.547s,
project48.687s. Исходный failed run сохранён; latency изменчива.
Professional871 **FAILED**: same-identity B0 331.73s required46993/budget46246
(+747), семь read frames; B1 92.17s required47433 (+1187), paused20remaining/
0accepted, шесть exact cards delivered; оба без XLSX. Visible131k trial не изменил
observed physical KV65536 pages×page_size1 при advertised262144. Исходная65k
policy восстановлена в public bindingr6; GPU/KV/server/model не менялись.
Готовность заказчику не заявлена.
Техническая доступность не доказывает профессиональное качество.
Фактические receipts и состояние выпуска — [`RELEASE_LEDGER.md`](RELEASE_LEDGER.md).

## Версия ЛЕС

| Поле | Значение | Назначение |
|---|---:|---|
| Версия продукта | `0.31.148` | Единственный пользовательский номер по схеме `X.Y.Z` |
| Номер сборки | `876` | Монотонный номер Windows-пакета; не является четвёртой частью версии |
| Версия пакета Tauri/NSIS | `5.1.876` | Внутренняя монотонная версия установщика для обновления существующих `5.1.x` |
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
