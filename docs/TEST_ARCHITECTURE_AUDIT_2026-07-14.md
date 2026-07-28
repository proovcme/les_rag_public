# Аудит тестов относительно текущей архитектуры Л.Е.С.

Дата среза: 2026-07-14. Версия дерева: подготовка `0.24.1`, сборка `410`.

## Исполнено 2026-07-17

- `make test`, `make test-release`, `make test-architecture` и `make verify` теперь используют одну
  каноническую LES-коллекцию: **2680 collected / 2671 passed / 9 skipped** на версии 0.24.37/build 458;
- 11 файлов feature-off Unified/Construction Harness исключены из обычных и release-гейтов и
  доступны только явно через `make test-legacy`;
- `test_artel*` исключены: ARTEL остаётся отдельным продуктом со своим release-гейтом;
- 49 агрегатных повторов из пяти смешанных файлов удалены, 96 полезных extraction/sidecar/API
  проверок сохранены;
- семь always-green `assert ... or True` удалены. Границы профилей закреплены
  `tests/test_test_profiles.py`.

Прямой `uv run pytest` использует тот же default из `pytest.ini`. Физические 3057 тестов доступны
только при явном обходе default; поддерживаемый архивный вход — `make test-legacy`, ARTEL запускается
в отдельном продукте.

## Второй проход 2026-07-28

Полная серия 0.24.46 была зелёной (`2712 passed / 9 skipped`), но не заметила два реальных дефекта:
active smeta-base содержала 180 080 строк без provenance, а smeta Qdrant-кандидаты не доходили до
reranker. Причина была в профиле доказательств: тесты создавали собственные SQLite/mock-ответы,
два harness-теста зависели от случайного состояния локальной active-базы, а тест batch retrieval
прямо требовал `rerank_deferred` при пяти и более запросах.

В 0.24.47 введены разные уровни:

- `make test-unit` — быстрые hermetic контракты;
- `make test-integration` — временные базы и поведенческие границы, включая отказ builder заменить
  canonical SQLite при missing provenance, batch rerank и полный selected-table menu;
- `make smoke-active-artifacts` — фактические active SHA/count/provenance;
- `make smoke-smeta-rerank` — живой A/B model-visible порядка с обязательным `rerank_status=ok`;
- `make smoke-basic-release` — живой HTTP/UI/product path.

Первый живой rerank smoke честно упал: `rag.reason=base_revision_mismatch`, а в Qdrant отсутствует
сконфигурированная `les_smeta_norm_cards`; поэтому `rerank_status=not_attempted`. Это отдельный
runtime/index repair, который нельзя скрывать зелёным unit-тестом или чинить подменой manifest.

## Вердикт

В исходном срезе собирались **2926 тестов из 303 файлов**. После release-bootstrap и
version-contract и clean-RRF regression текущая коллекция содержит **2931 тест**. Число большое, но само по себе не является
показателем качества. По отношению к канонической архитектуре результат такой:

| Класс | Тестов | Что это значит |
|---|---:|---|
| Текущие контуры и действующие модули | 2498 | Проверяют код, который остаётся частью текущей архитектуры: RAG/evidence, ingestion/Л.И.С.Т., smeta, API/UI/runtime/release и действующие доменные модули |
| Текущие проверки, смешанные со старым Unified Harness | 145 | Внутри файлов есть полезные проверки sidecar/extraction/routes, но рядом лежат сквозные повторы старых v0.3-v0.16 и импорты feature-off harness |
| Явно исторический feature-off контур | 288 | 11 файлов напрямую тестируют `construction_harness_service` или `unified_construction_harness_service`; это не доказательство работоспособности современного product path |
| **Всего** | **2931** | Полная регрессионная коллекция, а не 2931 одинаково полезный release-гейт |

После построчного просмотра пяти смешанных файлов выявлено ещё **49 агрегатных исторических/
дублирующих тестов**. Поэтому рабочая оценка полезного набора для фактической архитектуры —
**2594 теста** (`2931 - 288 - 49`). Из них не все являются release-критичными: значительная часть
защищает отдельные включённые модули.

## Как определялась полезность

Тест считается относящимся к фактической архитектуре, если он проверяет хотя бы одну действующую
границу из `AGENTS.md`, `MODULE_INDEX.md` и `CODE_MAP.md`:

- `dense + bm25_sparse → native RRF → rerank → parent/context expansion`;
- ingestion, тип документа, чанки, provenance, карты и адресное чтение Л.И.С.Т.;
- общий model-first evidence/chat contract;
- smeta model-first mapping и детерминированные единицы, ресурсы, РИМ, цены и XLSX;
- действующий API, вложения, история, GUI, безопасность, Windows/Tauri bootstrap/update/release;
- реально поставляемый доменный модуль, указанный в `MODULE_INDEX.md` как `✅` или `🟡`.

Тест не считается доказательством текущей архитектуры, если он запускает выключенный по умолчанию
keyword-harness, проверяет только существование старой функции или повторно вызывает тесты прежних
версий под новым именем.

## Полезные группы

Классификация ниже сделана по файлу и основной ответственности. Она нужна для понимания назначения,
а не для сложения независимых метрик: слабые source-contract проверки могут входить в любую группу.

| Группа | Файлов | Тестов | Оценка |
|---|---:|---:|---|
| RAG, retrieval и evidence | 41 | 296 | Критично. Здесь находятся RRF/readiness, named-vector contract, Qdrant parse/index, retrieval, rerank, evidence packet, notebook navigation и source excerpts |
| Документы, ingestion и Л.И.С.Т. | 34 | 381 | Критично. Проверяет фактическое чтение PDF/таблиц, process isolation, project maps, electrical/drawing readers и stale provenance |
| Сметы и цены | 43 | 313 | Критично для сметного модуля. Проверяет model/code boundary, ГЭСН, РИМ, ФГИС, КАЦ, количества, артефакты и human-facing result |
| Платформа, API, GUI и выпуск | 56 | 521 | Критично для поставки. Проверяет Windows/Tauri, bootstrap, updater, runtime, безопасность, вложения, idempotency, версии и Совушку |
| Прочие действующие доменные и служебные модули | 118 | 1132 | Полезно как модульная регрессия, но не всё должно блокировать базовый RAG-релиз: CAD/BIM, ARTEL, почта, формы, ВОР, сверка, журналы и т. п. |
| Исторический Unified/Construction Harness | 11 | 288 | Не должен считаться подтверждением текущего релиза |

Четыре первые группы дают **1511** проверок основных продуктовых границ. Ещё **1132** проверки
относятся к реально существующим, но не всегда включённым в конкретную поставку модулям.

## Явно исторические файлы

Эти 11 файлов (`288` тестов) проверяют feature-off архитектуру v0.3-v0.12 либо старый workbook
resource-cost слой:

- `test_construction_harness.py` — 16;
- `test_resource_cost_v05.py` — 45;
- `test_resource_cost_v06.py` — 31;
- `test_unified_adapters_v09.py` — 21;
- `test_unified_async_v10.py` — 24;
- `test_unified_construction_harness.py` — 25;
- `test_unified_construction_v04.py` — 37;
- `test_unified_filebody_v12.py` — 33;
- `test_unified_live_v07.py` — 19;
- `test_unified_operational_v08.py` — 17;
- `test_unified_real_v11.py` — 20.

Они могут временно оставаться архивной регрессией, пока из старых сервисов не вынесены последние
используемые adapters/classifiers. Но зелёный результат этих тестов нельзя предъявлять как качество
современного RAG или сметного контура.

## Смешанные файлы

| Файл | Всего | Полезно сейчас | Старые агрегатные повторы | Решение |
|---|---:|---:|---:|---|
| `test_sidecar_policy_v14.py` | 15 | 10 | 5 | Перенести write/staleness в current sidecar suite, затем убрать файл |
| `test_route_and_runtime_v17.py` | 35 | 20 | 15 | Оставить API/route/.xls проверки; удалить цепочку `test_vNN_*_regression` |
| `test_doc_extract_v13.py` | 30 | 25 | 5 | Сохранить extraction/source-ref; вынести зависимости от старого harness |
| `test_extracted_smoke_v15.py` | 15 | 9 | 6 | Полезные реальные sidecar-smoke перенести в отдельный environment profile |
| `test_sidecar_ops_v16.py` | 50 | 32 | 18 | Основной current sidecar suite; удалить повторные вызовы предыдущих поколений |

Именно эти повторные `test_v03...test_v16` создают иллюзию дополнительного покрытия: новый тест
часто лишь ещё раз вызывает уже существующую старую функцию.

## Слабые проверки

- В **25 файлах / 254 collected tests** встречаются проверки текста исходников (`read_text` +
  `assert "строка" in source`). Они полезны для packaging/install contracts, но слабее поведенческого
  теста: переименование или рефакторинг ломает их, а неверное поведение может остаться зелёным.
- Найдено **7 бессодержательных утверждений** вида
  `assert ... in (...) or True`. Они всегда проходят и должны быть удалены либо заменены одной
  реальной проверкой, что feature-off harness выключен без env.
- Skip/fixture-зависимые проверки должны быть отдельным environment/live профилем. Успешная полная
  локальная серия не заменяет Windows installed-runtime smoke и настоящий Qdrant RRF probe.

## Правильные гейты

1. `make verify` — синтаксис и сбор канонической LES-коллекции; это не проверка поведения.
2. `make test` / `make test-release` — полный текущий LES без 11 исторических файлов и без
   `test_artel*`. `make test-architecture` оставлен совместимым псевдонимом.
3. `make test-rag-core` — обязательная короткая проверка RAG-контракта.
4. `make test-mail` / `make test-mail-release` — отдельный offline/static профиль Е.Ж.И.К.;
   второй дополнительно компилирует Tauri. COM, Scheduled Task, реальный intake/index/open
   подтверждаются только установленным Windows-smoke.
5. `make test-legacy` — ручной архивный прогон 288 тестов, не release-доказательство.
6. Windows release smoke — единственное подтверждение установленного production-контура:
   bootstrap/API/UI/Qdrant и реальный `dense + sparse → RRF → rerank`.

Исторический контрольный запуск профиля до разделения LES/ARTEL/mail: **2638 passed, 6 warnings in
229.33 s**. Контроль после разделения 2026-07-17: **2687 collected, 2684 passed, 3 skipped,
9 warnings in 294.76 s**. Этот контроль был сделан до очистки. С 0.24.37 49 повторов удалены,
а 96 полезных проверок оставлены в тех же пяти файлах до их последующего переименования по
текущим сервисам.

Исключение 288 legacy-тестов почти не ускорило прогон: полная серия ранее заняла 226.56 s.
Основное время сейчас тратят действующие интеграционные проверки, а не исторический harness:

- staging Windows runtime — 32.07 s и 17.61 s;
- end-to-end auto smeta route — 18.11 s;
- три проверки реального norm search/model-choice — 16.93 s, 13.64 s и 8.98 s;
- реальный ГЭСН PDF — 15.86 s;
- `CrossEncoderReranker` passthrough — 10.76 s (конструктор поднимает тяжёлый backend даже там,
  где тесту достаточно проверить преобразование результата);
- реестр служебных источников — 10.74 s;
- smeta notebook/context memory — 7.15 s.

Эти тесты в основном полезны, но относятся к интеграционному/packaging профилю. С 2026-07-17
почта вынесена в явный `make test-mail`, а ARTEL исключён из LES architecture profile. Их не следует
удалять ради скорости; нужно устранить случайную загрузку тяжёлых backend в unit-тестах и отделить
быстрый pull-request gate от полного release gate.

## Оставшийся план очистки

1. Сначала вынести `classify_doc_type` и оставшиеся source adapters из
   `unified_construction_harness_service` в текущие сервисы.
2. Переименовать/перенести 96 сохранённых полезных проверок из пяти исторически названных файлов в
   тесты действующих сервисов без изменения покрытия.
3. ~~Удалить 49 агрегатных `test_vNN_*_regression` и 7 always-green assertions.~~ Выполнено в 0.24.37.
4. После отсутствия runtime-импортов переместить или удалить 11 исторических файлов и сами
   feature-off harness services.
5. Постепенно заменять source-string assertions на вызов API/функции; оставить текстовые проверки
   только там, где сам файл является контрактом поставки (PowerShell, Tauri resources, manifest).
6. Не сокращать модульные тесты только ради меньшего числа. Сокращать дубли и мёртвые пути; качество
   RAG принимать retrieval/evidence и живыми golden/smoke, а не общим количеством pytest.
