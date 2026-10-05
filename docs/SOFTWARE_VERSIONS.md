# Версии программного контура ЛЕС

Кандидат0.31.167/build895: адрес ресурса exact-card и конфликтующие строки книги.
Исходный runtime89450f8eb06; новая профессиональная приёмка pending. Dependency graph
не изменён; fgis-mcp0.3.1 прочитан как внешний исходник, пакет не установлен.
NativeEXE5.1.813 сохраняется; текущий публичныйmain142c41c6 содержитbuild712.
Canonical895:3312passed/20existing skipped, metadata31; остальные offline gates PASS.
Текущий установленный runtime: `/api/version`; контрольные receipts: artifacts/live_895.

Кандидат0.31.166/build894: query target публикуется с принятой попыткой.
Установлена893 ac042060, canonical3276passed/20existing skipped; B0/B1 без XLSX.
Зависимости прежние, EXE5.1.813, профессиональная приёмка не пройдена.

Кандидат0.31.165/build893: инструкции по фазам поиска/итога; зависимости прежние.
Installed892 d26f0df2; nativeRRF PASS, basic8PASS/1WARN/1FAIL, synthetic B1 без XLSX.
Профессиональная приёмка не пройдена; EXE5.1.813 не пересобран.

Кандидат0.31.164/build892: точный query envelope/commentary, зависимости прежние.
Installed891 `4f435358`, canonical3272passed/20existing skipped, nativeRRF PASS,
basic9PASS/1WARN. Синтетические B0/B1 дали XLSX, профессиональная приёмка не пройдена.
Native EXE5.1.813 не пересобран. FreeToken r8/64k; Flash r3 output8192 отключён.

Кандидат `0.31.161` / build `889`: выдача частичного workbook при cloud budget stop.
Зависимости неизменны. Installed888 `e84afdee`: offline3242passed/20existing skipped,
RRF PASS, basic9PASS/1WARN; liveFlash БАП12/19, customer-ready false.
Canonical889:3249passed/20existing skipped, остальные offline gates exit0.
Install/live889 pending. NativeEXE5.1.813 не пересобран.

Кандидат `0.31.160` / build `888`: финальный protocol guard и строгий basic smoke.
Зависимости неизменны. Installed887 `962d965b`: RRF PASS, basic9PASS/1WARN,
answer audit FAIL (raw tool frame). Canonical888:3242passed/20existing skipped,
остальные offline gates exit0. Install/live888 pending.
Нативный EXE по-прежнему5.1.813; профессиональная приёмка не заявлена.

Кандидат `0.31.159` / build `887`: provider reasoning_content в native продолжениях.
Зависимости неизменны. Installed886 `efb28f25`: после возврата FreeToken r8/64k
nativeRRF PASS, basic10PASS/0WARN/0FAIL, но answer audit выявил raw tool-call
в history766 (ложноположительный basic). Canonical887:3226passed/20existing skipped,
остальные offline gates exit0. Install/live protocol887 pending.
Реальный desktop EXE остаётся5.1.813; новый установщик не собран.

Кандидат `0.31.158` / build `886`: ограниченный native receipt replay и точная
диагностика read stops. Dependency graph прежний. Installed885 `10c3c827`:
canonical3206passed/20existing skipped, RRF PASS, basic9PASS/1WARN/0FAIL.
FreeToken128k B0 завершился без XLSX по повторному запросу; приёмка не пройдена.
Canonical886:3216passed/20existing skipped, verify/architecture/docs exit0.
Install886 pending. Native EXE остаётся5.1.813.

Кандидат `0.31.157` / build `885`: восстановление legacy read ledger через
цепочку продолжений документа. Зависимости неизменны. Installed884 `8c2fb702`:
RRF PASS, basic9PASS/1WARN/0FAIL. Native EXE остаётся5.1.813.
Canonical885:3206passed/20existing skipped; verify/architecture/docs exit0.
Install885 pending; профессиональная готовность не подтверждена.

Кандидат `0.31.156`/build`884`/Tauri`5.1.884`: накопление receipts после resume,
без изменения dependency graph. Canonical/install pending. Installed883
`22a88e81`: smoke9PASS/1WARN/0FAIL, nativeRRF PASS. Flash B1 и продолжение дали
14 успешных чтений норм,257092tokens, затем budget stop; готового XLSX нет.
Native EXE остаётся5.1.813; профессиональная приёмка не пройдена.

Кандидат `0.31.155`/build`883`/Tauri`5.1.883`: подтверждение доставки исходных
evidence для чтения по Qx.Hy. Dependency graph прежний; related245passed,
canonical3203passed/20existing skipped; verify/architecture/docs exit0.
Install/live pending. Installed882 `1b09191c`, nativeRRF PASS,
basic9PASS/1WARN/0FAIL. Native EXE остаётся5.1.813; готовность не подтверждена.

Канонический паспорт совместимости. Версия продукта и номер сборки берутся только из
[`config/version.json`](../config/version.json). Полный Python-граф фиксирует `uv.lock`.

Кандидат `0.31.154`/build`882`/Tauri`5.1.882`: wire-admission optional context и
native budget checkpoint. Dependency graph прежний; related146passed,
canonical3196passed/20existing skipped, verify/architecture/docs exit0; live
pending. Установлен881 `95de9b32`, RRF PASS, basic9PASS/1WARN/0FAIL.
Flash B1 stopped budget после66364 tokens, final/XLSX нет; ready не подтверждено.

Кандидат `0.31.153`/build`881`/Tauri`5.1.881`: safe budget diagnostics через
HTTP/SSE/history, без изменения dependency graph. Профильные91passed,
canonical8813191passed/20existing skipped. Установлен880 `6554b3fe`, smoke10PASS после запуска Ollama;
BAP Flash B0 stopped budget113s, XLSX нет. Готовность не подтверждена.

Таблица описывает кандидат `0.31.152`/build`880`/Tauri`5.1.880`;
880 добавляет необязательный GUI-бюджет облачного хода; dependency graph прежний.
Canonical880:3189passed/20existing skipped, verify/architecture/docs exit0.
Установка/профессиональная приёмка880 pending. Установлен879:
879 сохраняет техническую причину native capacity stop в итоговой диагностике.
Dependency graph прежний; related48passed, canonical8793178passed/20existing
skipped, verify/architecture/docs exit0. Установлен Python runtime879,
commit `1b5c0b40564b199895584e20caa3a9a3663dee60`, exact stamp/rawSHA проверены.
NativeRRF exit0; basic smoke7PASS/1WARN/2FAIL (оба chat timeout180s).
Поздняя история: завершены225/266s, research deadline после5/8 web calls,
raw tool markup в одном ответе. Приёмка не пройдена; native EXE5.1.813 сохранён.
Предыдущий установленный контроль:
установлен Python runtime `0.31.150`/build`878` commit
`cc6d8b5d58e8a5536bcceb1efcb8283d612b7d76`: metadata имени/единицы ценовых
кандидатов. Focused131passed; canonical3177passed; exact install/SHA/nativeRRF
подтверждены, basic9PASS/1WARN/0FAIL. FreeToken engine0.1.3+g52322e984:
B0 thinking11rows/confirmed0; B1capacity54351/46171estimatedtokens, нет XLSX.
Price-pointer path этими прогонами не вызван. Профессиональная приёмка FAILED.
Installed876 canonical:
3174 passed; smoke9PASS/1WARN; Alibaba B0/B1 завершились с partial XLSX,
профессиональная готовность не подтверждена. Native EXE остаётся5.1.813.
Состояние и точные receipts — RELEASE_LEDGER, раздел878/879.

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
| Версия продукта | `0.31.167` | Единственный пользовательский номер по схеме `X.Y.Z` |
| Номер сборки | `895` | Монотонный номер Windows-пакета; не является четвёртой частью версии |
| Версия пакета Tauri/NSIS | `5.1.895` | Внутренняя монотонная версия установщика для обновления существующих `5.1.x` |
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
