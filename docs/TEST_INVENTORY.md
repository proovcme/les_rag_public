# TEST_INVENTORY — текущая карта проверок ЛЕС

0.31.5: `test_chat_workspace_ui` включает настоящий NiceGUI render114 чатов
с многострочным названием и проверку, что проекты/управление не потерялись.
`test_sovushka_uikit` ловит переносы/кавычки/слэши в accessible label.
Read-only `tools/chat_workspace_ui_probe.js` — ручной browser gate для viewport,
clipping ancestors и высоты строк; выполнять после layout-изменений на desktop
и390px с открытой панелью. Он не заменяется static CSS assertions.
[Условия и фактическая приёмка](acceptance/chat-workspace-0.31.5.md).

`WORKSPACE_TESTS` (0.31.0) входит в канонический gate: `test_chat_session_service`,
`test_workspace_router`, `test_workspace_memory`, `test_workspace_memory_router`,
`test_workspace_context`, `test_chat_workspace_ui`. Проверяет scope/миграцию,
CRUD и исключение памяти, сохранение evidence в model packets, гонки навигации
и общий UI kit. Изолированная живая проверка memory conditioning на Qwen3.5:9B
описана в [модуле проектов](modules/project-workspace.md); не заменяет installed приёмку.

> **Статус: актуально.** Источник команд — `Makefile`; состав конкретных наборов
> задают его именованные переменные. Исторические счётчики и описание прежних
> поколений тестов перенесены в
> [`archive/TEST_INVENTORY_HISTORY_2026-08-30.md`](archive/TEST_INVENTORY_HISTORY_2026-08-30.md).

## Канонический gate

| Команда | Что доказывает | Чего не доказывает |
|---|---|---|
| `make verify` | version drift, импорт/синтаксис и сбор текущего явно перечисленного набора | живые сервисы и качество ответа модели |
| `make test` | короткий текущий contract/behavior gate `CURRENT_TESTS` | весь исторический репозиторий, GPU, пользовательский корпус |
| `make test-updater` | soft/hard update, rollback, persistent-state isolation, release receipt, Windows/Mac updater contracts | NSIS-сборку и установленный live runtime |
| `make test-rag-core` | contract native dense+sparse/RRF, атомарную alias activation/rollback, retrieval и index integrity | recall конкретного пользовательского корпуса |
| `make test-mail` | IMAP/Outlook registry, dedup, intake, API/UI и static Windows sidecar | живой Outlook COM на Legion |
| `make test-mail-release` | `test-mail` плюс Tauri compile-check | установленный Outlook и реальный ящик |

`make test` и `make verify` используют workspace-local
`.test-tmp/<profile>`. Непредсказуемый системный `%TEMP%` на Windows не является
частью контракта.

## Что входит в текущий LES

- Evidence/chat: scope `none | selected | all`, evidence packet, context governor,
  typed citations/source navigation, immutable model-visible evidence manifest,
  explicit source-only capability, research tools и отсутствие кодового final вместо модели.
  Отдельные регрессии фиксируют обычные model-authored query lines, либеральное
  снятие только presentation wrappers, запрет memory-driven подмены provider,
  runtime-relative attachment handoff и неизменность model-owned workbook rows.
- RAG: contract-versioned named `dense + bm25_sparse`, native RRF, rerank,
  profile-owned overfetch/diversity/evidence limits, hierarchy/parent expansion,
  dimensional readiness, ready-generation guard для ColBERT и dataset integrity.
  Сметный integration-набор отдельно проверяет exact-SHA sibling-сборку
  SQLite+RAG, транзакционный rollback файлов и alias, startup reconciliation,
  фоновое восстановление, межпроцессную гонку, stale/fresh lock, произвольное
  переименование базы/alias, locked SQLite, недоступный Qdrant и явный
  GUI-warning при рассогласовании. `test_update_resilience_matrix.py`
  fail-closed связывает эти проверки с dataset/general-RAG/baseline/soft/hard
  update и не даёт им исчезнуть из именованных гейтов;
  отдельный boundary-test
  подтверждает, что живые source adapters используют самостоятельный document classifier,
  а не выключенный Unified Harness.
- Models: connection registry, secrets boundary, capability resolution,
  OpenAI-compatible transport и одинаковый governed path для 9B/35B.
- UI: общий UIKit, WCAG AA, документы, чат, источники, model connections и
  отсутствие скрытого автоматического scope.
- Runtime/release: Windows process ownership, persistent-state boundary,
  bounded model queue, resident-model admission, отключаемые startup mutations
  для изолированной приёмки, safe public errors, lightweight/full update, legacy
  `les.release-attempt.v1` и раздельные
  `les.release-gate-receipt.v1` / `les.release-artifact.v1` /
  `les.release-acceptance.v2` / `les.release-publication.v1` и публичную
  проекцию `les.release-receipt.v2`; тесты фиксируют exact commit/tree/policy,
  неизменность artifact при failed acceptance, SHA-drift, revocation и выбор
  только успешной попытки. Publication требует accepted artifact, сохраняет
  draft/postflight checkpoints и не может вызвать builder. До Tauri/NSIS отдельный registry-тест сверяет
  literal `python -m` callsites с реально staged модулями и runtime manifest;
  незарегистрированный или отсутствующий entrypoint падает fail-closed.
  Registry покрывает dotted/simple `python -m`, staged Python/PowerShell/EXE;
  lock-bound `uvicorn` объявлен отдельно. Неопределённый acceptance failure
  блокирует retry до записанного operator reconciliation и не разрешает смену host.
  Full acceptance дополнительно связывает canonical hard-update job по SHA и
  сверяет все mutation roots до запуска Windows update engine.
  Installed acceptance и rollback сохраняются;
  native-RRF fixture не может схлопнуться в zero-chunk, а его exact временный
  dataset удаляется без snapshot всей пользовательской коллекции.
- Профессиональные модули: только их действующие contract-тесты. Сметный
  benchmark запускается отдельно и не заменяется общим pytest.

Точный перечень файлов всегда берётся из `CURRENT_TESTS` в `Makefile`. Новый
активный модуль добавляется туда в том же коммите, что и его код.

## Отдельные профили

| Профиль | Назначение |
|---|---|
| `make test-unit` | быстрые чистые unit-контракты |
| `make test-smoke` | герметичный offline API/scope/version smoke |
| `make test-integration` | временные SQLite/API/release-артефакты |
| `make test-model-connections-live` | явная opt-in проверка реального model endpoint |
| `make live-workbook-acceptance` | owner-authorized реальный workbook/model run |
| `make smoke-general-native-rrf` | установленный пользовательский RAG и native RRF |
| `make smoke-smeta-rerank` | active smeta base → RRF → reranker |
| `make smoke-basic-release` | живые API/UI после установки кандидата |

Live-профиль не запускается автоматически против пользовательских данных.
Отсутствующий Qdrant или корпус получает `N/A`, а не синтетический `PASS`.

## Историческая диагностика

- `make test-legacy` — 11 файлов прежнего Unified/Construction Harness.
- `make test-legacy-full` — repository-wide диагностика без отдельных ARTEL и
  legacy-harness профилей.
- Эти команды не являются release evidence и не входят в updater.

Исторический тест удаляется только вместе с доказанно удалённым поведением.
Большое число файлов в `tests/` само по себе не означает большое продуктовое
ядро: карта кода помечает тесты и ручные CLI как `TEST_OR_TOOL_ONLY`, но не
объявляет их мусором.

## Живые приёмки

### Тест № 1 — не мешает ли harness модели

Первым проверяется контрольный прямой путь на одинаковых входах:

`модель → сформулированные ею запросы → штатный RAG → та же модель`.

Затем та же модель, задача, вложение и dataset проходят через штатный ЛЕС.
Проверка fail-closed, если harness:

- передал модели меньше исходного текста или evidence, чем baseline;
- подменил поисковые запросы или предметные решения модели;
- показал `NO_DATA`, хотя вложение или RAG-результаты были доступны;
- повторил одинаковый отклонённый вызов либо дошёл до deadline вместо результата;
- ухудшил source coverage/инженерное решение относительно baseline без явной
  причины в trace.

Это installed live acceptance, а не pytest с заранее заданными ответами модели.
Unit/contract-тесты запускаются после него для закрепления уже доказанного
поведения и не могут превратить провал этого теста в `PASS`.

| Изменение | Обязательная дополнительная проверка |
|---|---|
| inference/RAG/workflow | тест № 1: direct model baseline ↔ штатный harness на одинаковых входах |
| retrieval/router при наличии корпуса | `tools/rag_golden_set.py` и открытая dataset-story acceptance |
| Windows выпуск | `make release`: install → smoke → rollback → restored smoke → reinstall |
| сметное поведение | защищённый benchmark из `AGENTS.md` |
| classic Outlook | установленный Legion COM/task/index/open smoke |
| model binding | explicit model-connection live acceptance |

Публичный выпуск допустим только после принятого installed receipt. Offline
pytest не подменяет этот результат.

## Правило сопровождения

При изменении поведения:

1. сначала тест, который падает на старом коде;
2. минимальное исправление;
3. точечный прогон;
4. `make verify` и `make test`;
5. обновление этой карты только при изменении профиля или границы проверки.

Не добавлять сюда хронологию релизов и старые числа `passed`: состояние выпуска
живёт в [`RELEASE_LEDGER.md`](RELEASE_LEDGER.md), история — в Git и архиве.
