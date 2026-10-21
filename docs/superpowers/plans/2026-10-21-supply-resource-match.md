# Подтверждение соответствия ресурса поставке — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Не объявлять поставку полностью посчитанной только потому, что цена выбранного кода есть в книге; сохранить предметное решение за моделью.

**Architecture:** Один необязательный транспортный объект `supply_resource_match` становится обязательным основанием финансовой полноты для прямого модельного resource_code поставки. Код проверяет буквальную идентичность утверждения и источников, не выбирает изделия. Неподтверждённые сопоставления возвращаются той же модели внутри существующего единственного resource proof; нового предметного цикла нет.

**Tech Stack:** Python 3.12, существующие row-contract/parser, RIM и resource-proof, pytest/uv; без зависимостей и миграции БД.

**Spec:** AGENTS.md; измеренные `artifacts/live_979/candidate979_ordinary01/` и `candidate979_b0_01/`; `docs/modules/rag-evidence-flow.md`, `docs/ALGO-lsr-assembly.md`.

## Global Constraints

- Рабочее дерево `.worktrees/qwen-finalization`; installed979/babaf652 остаётся отдельным проверенным target.
- Не менять выбранные моделью codes/titles/quantities, не разбирать coverage предметной регуляркой, не переносить пять norm-match flags на поставки.
- Не подменять цену кодом; автор утверждения соответствия — модель либо существующее доверенное подтверждение инженера. Обход для human price требует действительно заданной конечной confirmed_price из trusted overlay, включая 0; одно confirmed_by=operator после уточнения количества/единицы не подтверждает цену.
- Не менять Qdrant/SQLite/manifest; не добавлять запросы на behalf модели, зависимости, профиль или автоматические повторные циклы.
- Source/revision/evidence ownership и сохранение принятых строк остаются существующими.

## Review Focus

- Цена правильного кода не доказывает соответствие исходному изделию.
- Прежнее yes не должно переноситься при смене resource_code, title или evidence_refs.
- Работы, коммерческие строки без resource_code и доверенные цены инженера сохраняют свои отдельные контракты.
- N поставок ограничены существующим пакетным proof; отложенные явно названы и остаются незакрытыми.
- Поставки не исчезают из файла/добора, когда цена известна, а соответствие неизвестно.
- Контракт одинаково виден B0/B1; supply-only долг запускает тот же bounded proof и без групп нормы/книги цен.
- source_title привязывает утверждение к модельной операции; модель дополнительно сверяет показанный исходный контекст, характеристики и примечания. Код их семантически не интерпретирует.

## Контракт

`supply_resource_match` — модельный JSON-объект:
`{source_title, resource_code, decision, reason, source_refs}`.
`decision` = `yes|no|unknown`. Для подтверждения нужны непустое reason, буквальное совпадение source_title с title своей операции, resource_code с выбранным кодом, непустое множество source_refs, равное evidence_refs этой операции. Прежняя проверка фактической доставки/принадлежности кода этим ссылкам обязательна отдельно. Сам объект не доказывает профессиональную правильность yes и не является обещанием точности90%.

## Task 1: финансовый fail-closed guard

**Files:** `proxy/services/model_resource_binding_service.py`, `proxy/services/rim_lsr_trace_service.py`, `tests/test_rim_lsr_trace_service.py`.

- [x] RED: у cited/book-priced direct supply без подтверждения, с no/unknown, пустым reason, устаревшим code/title/refs нет confirmed/full amount; строка, выбранный код, quantity и предварительная сумма сохраняются.
- [x] GREEN: чистый helper `supply_resource_match_substantiated(row)` проверяет только контракт. Положительный случай, порядок refs, trusted operator price и коммерческая строка без resource_code проверяются отдельно.
- [x] Отдельная причина `supply_resource_match_unsubstantiated`, русское пояснение и существующий retry по финансовому пробелу; не маскировать как отсутствие цены.

## Task 2: единый транспорт и существующий resource proof

**Files:** `proxy/services/model_lsr_result_contract.py`, `proxy/services/model_workbook_terminal_transport_service.py`, `proxy/services/lsr_resource_group_proof_service.py`, `proxy/services/chat_evidence_application_service.py`; существующие contract/proof tests.

- [x] Сначала RED на JSON/native/табличный transport и сохранение объекта при proof/revision merge; без отдельного формата.
- [x] Инструкция и native schema явно объясняют, что код ресурса внутри нормы может быть монтажным расходником, а не исходным изделием. Выбор и подтверждение делает модель.
- [x] Существующий resource proof дополнить source-title/selected-code/literal-resource-name/unit/ref для прямых неподтверждённых поставок. Не выбирать замену, цену или соответствие кодом.
- [x] Один bounded round на пакет; непроверенные/deferred mappings названы и остаются открытыми. Возврат тем же parser/rows_after_proof_round. Принятые соседние строки и ценовая база не меняются.

## Task 3: доказательства и выпуск

- [ ] Related owner/consumer tests, включая historical positive fixtures с явным новым модельным утверждением; не ослаблять assertions.
- [x] Проверить, что неподтверждённая поставка попадает в readiness retry, а принятые строки/выбранные codes/book/evidence сохранены.
- [ ] Обновить модульные docs/MODULE_INDEX/TEST_INVENTORY/ledger, version contract и runtime map; затем verify/architecture/full canonical checks.
- [ ] Только после source review — exact install/rollback и live ordinary+B0+естественное замечание инженера. Сверить физические файлы, не число шифров.
- [ ] Не объявлять готовность ВОР/ЛСР/90% по этому финансовому guard; профессиональные ошибки норм и profile qualification остаются отдельной измеряемой задачей.

## Измеренное дополнение: прежняя выданная ревизия

- [x] RED→GREEN: actual calculator version0.7 в result/snapshot, LSR-only execution identity, запрет старого repack argument replay и сохранение версии старого checkpoint.
- [x] Передать точную financial projection, включая пустую, в no-model packaging event. Не приписывать текущую версию старому файлу.
- [x] Старый issued parent/child требует технического no-model repack до financial gap reopening; raw decisions/book/overrides сохраняются. Existing UI action/reconnect сохраняют флаг и прежний файл.
- [x] Guard/transport/price339passed и repack/lineage/zero155passed; receipts в `artifacts/offline_980/`. Counts пересекаются и не складываются в приёмку.
- [ ] Полный canonical gate, exact980 installer и новые installed B0/B1/engineer hint controls.

## Коррекция границы результата — candidate981

Full980:32failed/7022passed/20skipped/953.45s; installer не создан. Отрицательные
логи сохраняются. Positive authored supply fixtures, строгая разрешённая дельта
инструкции и размер required context исправляются без отмены assertions.
Новый proof ошибочно принимал код изделия модельной VOR как финансовый долг.
ROOT2RED/1positive→3GREEN; current result declaration теперь ограничивает
groups/supply/resume финансового proof итоговой LSR. Related54passed/6.67s.
QueryVOR→resultLSR остаётся разрешённым. Финальный target теперь981, не980;
новый canonical gate, exact installer и профессиональный live контроль pending.

## Установленная контрольная точка981 и следующий ограниченный ремонт

- [x] Exact981/fd17b383: main7057passed, updater328passed, local full NSIS,
  install/rollback/reinstall accepted. Это не gate профессионального качества.
- [x] Read-only SQLite quick_check и Qdrant49818: повреждение/потеря базы не найдены.
- [x] Старый979 файл пересчитан без модели: raw7decisions/book сохранены,
  confirmed576.49 переведены в preliminary, calc0.7. Физический XLSX проверен.
- [x] Натуральный engineer hint: model5calls/573.718s; физический расчёт не улучшен.
  Raw добавка есть, но proof размножает anonymous new proposal; literal wrong
  expected_revision2 не принимается против durable1. Модель также не сдала
  числовую кратность4 и вновь назвала монтажную ленту кабелем.
- [x] Понятное пояснение supply match в реальном XLSX: ROOT8RED/2positive→10GREEN.
- [x] Стабилизировать только transport identity непринятых операций ВНУТРИ
  существующего bounded proof, без semantic/title/code dedup и без нового цикла.
  До proof приложение выдаёт каждой новой строке временный непрозрачный ID;
  mapping и current proof rows сохраняются в existing pending checkpoint.
  Модель получает эти ID и immutable durable base revisions. Между proof rounds
  обновление адресуется ID, а не новым empty-ID proposal. До admission временные
  ID снимаются только по собственному issued mapping и тому же source locator;
  durable IDs/revisions, CAS и предметные поля не меняются. Unknown/forged ID и
  literal expected_revision2 остаются ошибками. Одинаковые новые строки не
  сливаются эвристикой: сами ограничения duplicate admission не ослабляются.
- [x] RED→GREEN helper/merge/restart + actual sheet proof/checkpoint regression,
  related gates. В новых proof frames нет выдуманного revision2.
  Временные parent IDs не становятся durable связями: role-independent
  child-only guard сохраняет proposal, а соседей не блокирует. ROOT
  active-parent6RED и malformed state2RED→related79GREEN; context54GREEN.
- [ ] Bundle candidate982, документация/version/runtime-map/verify/test,
  exact installer и установленный B0/B1/натуральное замечание. До этого
  installed981, customer_ready=false; не объявлять новые исправления установленными.
- [ ] После транспортной проверки отдельно измерить применимость норм,
  множители, НР/СП, прямые поставки, ВОР из разных файлов и большой вход.
  Код не исправляет ошибочный профессиональный yes и не извлекает множитель
  из coverage; readiness не подтверждается одним успешным сохранением файла.
