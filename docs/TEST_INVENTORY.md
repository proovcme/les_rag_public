# TEST_INVENTORY — текущая карта проверок ЛЕС

Build 843: query instruction must permit a model-authored mounting operation
instead of literal product-label copying; the reader preserves that query.
Result instruction requests the table first and excludes marker-only expansion.
Both regressions failed before correction. Installed/model outcome pending;
offline prompt contracts do not prove professional norm selection.

Build 842: three regression cases reproduce the missing output-ID contract,
mounting resources calculated on explicit supply/header roles, and non-work
ciphers inflating selected-work-norm counts. The role test asserts no norm
lookup/calculation, preserved authored role/code/source, and an explicit conflict.
Before: 3 failed / 86 passed; after: 119 passed, including 782 identity/money tests.

Build 841: regression cases in `test_chat_evidence_application_service.py`
cover surplus explanatory cells with known unit/quantity, echoed durable IDs,
checkpoint revision continuity, rejection of invented/moved IDs, exact-card
sharing with all eight query refs, distinct-source isolation, and shared
prior citations retaining immutable IDs. The required-prefix fixture uses two
distinct sources to continue testing that neither legal prefix may be cut.
Focused chat/research/architecture gate: 284 passed. Live acceptance remains
separate: 840 B1 finished with 23/75 accounted, 0 calculated, 920.8 seconds;
0 omitted cards per delivered page establishes transport only, not quality.

Build 839: seven regression cases in `test_model_research_tool_service.py`,
`test_chat_evidence_application_service.py`, `test_rim_lsr_trace_service.py`
prove the pre-existing loss of NR/SP options and the authored rule ID.
They cover all four visible formats, review projection, exact catalog source
checksums without private paths/selection, calculator forwarding, missing choice
remaining ambiguous and a foreign-collection choice rejected. A bounded model
message preserves the complete required typed-card prefix or omits the card;
it never cuts the legal candidate block midway. Before: 7 failed;
after: 248 passed across the related tool/chat/RIM/catalog/refinement suites.
The actual model choice and full customer LSR remain subject to installed live gates.

Build 838: four runtime-facts tests in `test_chat_evidence_application_service.py`
check a fixed observed date, actual catalog names without private paths, absence
of code-side price/norm selection, non-estimator isolation, empty catalog, and
1000-file bounded rendering with explicit partial inventory. Focused 174 passed.
This does not establish professional applicability or financial completeness.

Build 837: `test_estimator_card_keeps_source_resource_evidence_without_inventing_composition`
in `test_model_research_tool_service.py` reproduces dropped typed resource evidence,
checks unchanged source fields and explicit missing work composition, and forbids
invented applicability/selection. Before fix: 1 failed/9 passed; after: tool-service
and norm-browser suites 42 passed. Financial live acceptance remains separate.
`test_sheet_packet_prompts_do_not_request_the_whole_sheet_again` reproduces the
contradictory whole-sheet instruction for a one-row packet; packet/refinement
and chat tests pass (178). It does not impose a fixed operation count.
Three `test_vor_readiness_*` in `test_chat_evidence_application_service.py`
verify preserved authored unresolved gaps, unchanged row roles/quantities,
independence from norms/prices, and separate delivery/completeness flags.
This closes live-observed hidden questions in the initial 837 PDF VOR.

Build 836: `test_completed_replay_after_restart_keeps_calculation_snapshot_and_same_file`
in `test_workbook_tool_service.py` verifies immutable calculation metadata and
same revision/SHA on replay through a newly created checkpoint/artifact context.

Build 835: `test_artifact_revision_service.py` reproduces the installed 834
duplicate revision-number failure after local repack and concurrent deliveries
from the same parent. `test_workbook_chat_refinement.py` verifies a freeform
remark reopens the original document without a model planning handshake,
preserves all prior decisions and operator confirmations, and forwards all
five applicability flags and citations. These checks do not prove financial
readiness; installed model → RAG → XLSX acceptance remains mandatory.

Build 775: table divider width regression preserves both material and work
rows at one locator for short/equal/long dividers; existing invalid-divider
and invalid-numeric-cell protections remain covered in
`tests/test_chat_evidence_application_service.py`.


Build 772: `tests/test_freetoken_cache_profile_service.py` covers ACTIVE engine
selection independent of legacy provider, generation admission and cancellation
while a rebuild worker still runs. Settings reads use the non-mutating probe in
`tests/test_proxy_routers.py`. These do not replace live workbook acceptance.

`tests/test_lsr_source_coverage_service.py` and `tests/test_lsr_packet_integrity.py`:
material self-links, links to non-work decisions and all unresolved locators in
sources larger than the 80-item display limit remain open without rewriting rows.

`tests/test_lsr_packet_integrity.py`: low output budgets, invalid source
fragments and resumption of broken links without changing model norms.
`tests/test_lsr_source_coverage_service.py`: relative work-row coordinates
remain scoped to the source sheet and preserve explicit cross-sheet links.
`tests/test_installer_windows.py`: startup logs and `windows-light-state.json`
use the direct persistent-state path on a clean Windows install; runtime
junctions remain compatibility readers, not the creation path.
`tests/test_runtime_paths.py`: clean Windows state owns proxy/RAG MetaDB paths
and a fresh `JobService` creates its SQLite file directly under state `data`.

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

- Terminal LSR path: регрессия фиксирует ровно два вызова 9B-класса
  (model-authored queries и terminal result), отсутствие post-model quality
  loop в обычном запросе **включая sheet-pass**, неизменную передачу решений в
  workbook adapter и один идемпотентный packaging retry по той же checkpoint.
  Adapter принимает явный шифр `EXACT`/`ANALOGUE` без `EXACT_VERIFIED`;
  неизвестный код, единицы и model `MISSING` остаются unbound
  (`test_workbook_tool_service`, `test_rim_lsr_trace_service`,
  `test_chat_evidence_application_service`). Durable packet checkpoint
  (`test_workbook_research_job_service`) переживает pause/resume без повторного
  поиска кэшированных запросов: `should_cancel` остаётся истинным после `pause()`,
  иначе живой цикл продолжает пакеты. Этап Б: расчёт отказывается от позиции, если авторство модели по количеству/единице расходится с каталогом исходника без явного основания пересчёта — строка остаётся видимой как `unconfirmed_quantity` и не попадает ни в одну сумму; этап В разводит состояния строки в `readiness` (учтена/операция/норма/применимость/объём/расчёт/цены), заголовок `row_role=header` учитывается как `structure_accounted` без монтажной нормы, подтверждённая и предварительная суммы разделены (`test_rim_lsr_trace_service`, `test_lsr_result_readiness_service`); этап Г: namespace evidence различает попытки пакета (`:a<n>`), chunk meta хранит запрос модели (`model_query_text`), событие `search_cache` — sheet/packet/locators/queries, строка решения — `_evidence_check` (происхождение цитаты шифра без изменения статуса модели) (`test_chat_evidence_application_service`, `test_workbook_research_job_service`); этап Д: результат ЛСР содержит `price_basis` (запрошенная база — аргумент `pricebook`, уровень цен из текста исходника или период из вопроса — против фактических region/quarter книги; exact/mismatch/unspecified/no_book), несовпадение блокирует размерность цен до явного подтверждения альтернативы и печатается в шапке XLSX; список отсутствующих цен называет позицию, количество с единицей, проверенную базу и зависимые итоги (`test_workbook_tool_service`, `test_lsr_result_readiness_service`, `test_rim_trace_xlsx`); материал без количества больше не получает молча qty=1 (`test_rim_lsr_trace_service`). Точечное reopen locator сохраняет чужие
  решения. Этап А: `operation_id` устойчив через pause/resume/пересборку,
  несколько разных операций на одном локаторе не склеиваются, повтор того же
  решения не дублирует позицию, уточнение дописывает ревизию в
  `workbook_research_revisions`, запоздалая запись по устаревшему
  `base_revision` отклоняется (`test_workbook_research_job_service`, 12 тестов). `ChatRequest.comparative_acceptance_variant` принимает `B0_DIRECT`
  (`test_sovushka_chat`). Покрытие исходника,
  нормы и цены — `test_lsr_source_coverage_service`,
  `test_lsr_result_readiness_service`; UI уточнения/подтверждения без модели —
  `test_sovushka_chat`. Панель артефактов показывает новый XLSX сверху и
  прокручивает карточку готовности (`order_chat_file_artifacts`).
  Toast нового файла и кнопок ЛСР (resume/repack/confirm) входят в слот
  чата (`_notify` / `notify_in_element`); оценка
  remaining-time — `format_job_ready_eta_line` (`test_sovushka_chat`,
  `test_indexing_eta`). Reconnect closed-count uses accepted source rows
  when work-role is empty (`workbook_job_to_pending_progress`). N/M uses
  catalog work count, not accepted_all+leftover (`45/75` not `35/65`).
  History open hydrates a running job without a PENDING stub
  (`hydrate_chat_pending_from_workbook`). A paused first pass is not live
  assembly (`format_paused_assembly_notice`, `list_open`). Continue показывает leftover/accepted и seed ETA
  (`format_lsr_resume_display`, `sheet_pass_progress_counts`).
  Обрыв SSE после `tool_progress` не отменяет и не задерживает runner (`detach_chat_runner_after_disconnect`,
  `test_chat_stream_w51`) и не показывает «Соединение прервано»
  (`format_detached_stream_notice`, `follow_detached_chat_history`);
  реконнект не дублирует PENDING (`should_render_local_chat_pending`,
  `format_in_progress_assembly_notice`); live N/M и ETA после обрыва SSE
  читаются из checkpoint (`list_active`, `workbook_job_to_pending_progress`);
  повторный Continue не dual-run (`claim_or_join_sheet_pass`).
  Очередь модели ждёт `LES_MODEL_QUEUE_WAIT_SEC` (`test_runtime_admission`);
  мастер запуска идемпотентен; NSIS копируется из `CARGO_TARGET_DIR`
  (`test_tauri_desktop`). Контракт упаковки принимает operator `confirmed_data`
  (`test_workbook_tool_service`, `test_workbook_tool_contracts`,
  `test_chat_evidence_application_service`). Overflow workbook result
  остаётся у оператора (`test_chat_lsr_executor_keeps_overflow_workbook_for_operator`).
  Единый sheet-pass для малого и большого каталога —
  `test_chat_evidence_application_service`. Пустой `search_sources`
  (`missing`) не abort'ит пакет до таблицы строк
  (`model_search_result_blocks_packet`). Конверсия единиц только с источником
  и без угадывания габарита из названия — `test_rim_lsr_trace_service`.

- ADR-16 (сметный путь): систематический сбор кандидатов кодом — `test_lsr_candidate_query_service`
  (дословная композиция из ячеек, drop-if-ungrounded, происхождение
  `original`/`derived`/`model`, лимит = interrupted/deferred, а не «нормы нет»);
  применижность нормы — `test_lsr_norm_applicability` (`EXACT` от модели ≠
  подтверждённая применимость, `norm_code` с evidence другого шифра не закрывает
  готовность, `ANALOGUE_CANDIDATE` без обоснования остаётся черновиком);
  групповые ресурсы — `test_lsr_group_resource_specificity`; ценовая база —
  `test_lsr_price_basis_explicit` (город ≠ ценовая зона, отсутствующий квартал
  предлагается и не применяется, запрошенная база не подменяется другой книгой,
  список доступных книг видим); владение ценой — `test_lsr_price_ownership`
  (подтверждённая цена оператора и выбранная книга сильнее ставки из карточки
  нормы; помеченная ставка карточки считается, но остаётся в
  `preliminary_amount`, называется в `price_gaps` и не делает позицию полной);
  замаскированная незакрытость — `test_lsr_disguised_gaps` (§ 11: «демонтаж»,
  посчитанный нормой «монтаж», остаётся вопросом; совпадающие и неоднозначные
  формулировки ложного вопроса не дают; шт не пересчитывается в 100 м²;
  подтверждённая цена материала не закрывает отсутствующую норму работ;
  двойной учёт одного предмета в двух ролях и неадресованное подтверждение не
  становятся подтверждённой суммой).
  Архитектурный gate закрепляет всё четырьмя кодами:
  `DERIVED_QUERY_SEMANTIC_INVENTION`, `QUERY_PROVENANCE_MISSING`,
  `PRICE_BASIS_SILENT_DEFAULT`, `UNOWNED_PRICE_SOURCE`
  (`test_architecture_contract_gate`).

- LSR quality gate: нейтральная проверка карточки, сохранение последнего
  `CONFLICT` после исчерпания поиска, отдельный честный `MISSING`, store-card
  и PDF Markdown source catalog с устойчивыми локаторами и точным work-row count;
  verify и выпуск доступного partial-XLSX при нуле подтверждённых строк.

- Evidence/chat: scope `none | selected | all`, evidence packet, context governor,
  typed citations/source navigation, immutable model-visible evidence manifest,
  explicit source-only capability, research tools и отсутствие кодового final вместо модели.
  Отдельные регрессии фиксируют обычные model-authored query lines, либеральное
  снятие только presentation wrappers, запрет memory-driven подмены provider,
  runtime-relative attachment handoff и неизменность model-owned workbook rows.
  Reader принимает короткий markdown-divider, заголовок монтажа с `norm_code` и
  явные спецификационные таблицы без нормы; stream keepalive и PENDING-history
  покрыты `test_chat_stream_w51` / `test_chat_history_router`.
  Заголовки model-authored `Qn`, которые не влезают в остаток окна, не роняют
  чат: регрессия фиксирует split/omit вместо `MODEL_RAG_EVIDENCE_BUDGET_TOO_SMALL_FOR_ALL_QUERY_HEADERS`.
  FreeToken KV: default 35000, 35B lift from legacy <16384, rebuild clamp к
  `max_feasible_kv`, ACTIVE выравнивает KV в начале хода
  (`test_freetoken_cache_profile_service`).
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
  OpenAI-compatible transport, наблюдаемый KV FreeToken (`/v1/cache/status`)
  и одинаковый governed path для 9B/35B.
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
