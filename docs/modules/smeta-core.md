# Smeta Core — единое сметное ядро

> Единый человеко-машинный паспорт всего модуля —
> [SMETA_MODULE_EXPLAINED.md](../SMETA_MODULE_EXPLAINED.md): архитектура, skill, полный active prompt,
> Qwen row-loop, ФСНБ/ФГИС, расчёт, UI, настройки, тесты и ограничения.

> **Статус 2026-07-28: ✅ код и документ синхронизированы.** Канонический PDF→ЛСР путь —
> model-owned evidence loop, immutable построчный mapping, обязательная глобальная модельная ревизия,
> автoчерновик и отдельный пользовательский lock перед финальным расчётом.
> Архитектурное решение и судьба экспериментальных веток зафиксированы в
> [ADR-13](../ADR-13-smeta-session-workflow.md).

## Архитектурная граница

```text
исходник / ВОР / спецификация
  → source_intake: строки, количества, единицы, координаты
  → SmetaAgentRunner: native | Qwen-Agent | Google ADK
  → модель + skills/smeta/references/document-mapping-agent.md
  → browse_norm_catalog: typed-карта семейство → сборник → официальная таблица
  → smeta_scope_plan_v1: scoped(base_types/collections) | global, всегда выбран моделью
  → search_norms_batch: ScopePlan → RRF/FTS + rerank либо полный listing выбранной таблицы
  → read_norms_batch: фактические карточки Typed SQLite
  → submit_lsr_mapping: завершённое решение той же модели по активной строке/пакету
  → smeta_row: готовая строка сразу появляется в живой таблице чата
  → professional_conflict_v1: детерминированные противоречия без выбора ответа
  → global_review: та же модель проверяет всю ВОР и создаёт новую immutable revision
  → calculator: единицы, ресурсы, цены, РИМ, НР/СП, НДС
  → priced_draft XLSX → пользовательский mapping_locked → отдельный финальный расчёт
```

Модель выбирает работы, декомпозицию, запросы, нормы, аналоги, coverage и ресурсные действия
`add|replace|exclude|reuse`. Код не выбирает и не переписывает решение модели. Он проверяет машинную
адресацию и выявляет доказуемые профессиональные противоречия; они передаются той же модели в
обязательную cross-row ревизию, но не содержат готовой замены. Непрочитанная карточка и несовместимая
единица сохраняются в модельной ревизии как построчные расчётные blockers. Неполный
`technology_check` возвращается той же модели как ошибка terminal-полноты; код не оценивает её
профессиональный вывод. Python не содержит второго профессионального
prompt: фазовый контракт находится внутри canonical skill package и содержит только правила mapping,
а не нерелевантные этой фазе РИМ/ФГИС/НР/СП и оформление ответа.

`SmetaNormToolSession` хранит показанные карточки, принятые строки и trajectory. Все runner'ы
исполняют один и тот же контракт; встроенные RAG, MCP, Google Search и code interpreter выключены.
`native` остаётся default до живого профессионального гейта. `qwen_agent` использует локальный
Ollama; Qwen-Agent управляет loop, но на актуальном Ollama включает raw function serialization,
так как Nous text wrapper возвращает серверный `500 EOF`. `google_adk` — прямой Google API только
после `LES_CLOUD_CONSENT=true`; отсутствие ключа или
согласия является явной ошибкой без fallback.

Если Qwen-Agent завершил исследование обычным текстом без `submit_lsr_mapping`, runner повторно
предъявляет **той же модели и той же истории** только требование terminal serialization. Это один
ограниченный recovery-этап, а не fallback и не выбор кода. Для `unbound` session сверяет перечисленные
запросы и открытые коды с фактической tool trajectory; при расхождении возвращает модели
`allowed_evidence`, чтобы она сама исправила provenance. Для существующего `bind` recovery требует
полный `technology_check`. Пустой или выдуманный evidence не создаёт `row_ready`.
Если structured terminal показывает, что для собственного решения модели физически не открыты
карточки или не выполнены поиски, JSON-починка недостаточна: та же Qwen один раз возвращается в LES
tool-loop с точным validation feedback, сама выбирает evidence и затем повторяет terminal. Для ошибок
только формы исследование не возобновляется.

В тестовом `qwen_agent`-режиме ВОР является одной задачей, но transport запускает её последовательно
по одной активной строке. Каждая следующая строка получает исходные поля, соседний контекст и
компактный `task_state` со всеми уже принятыми моделью решениями. Этот журнал нужен для coverage и
поиска дублей; Python его не редактирует и не выбирает решение. После успешного
`submit_lsr_mapping` session публикует `row_ready`, application переводит его в SSE `smeta_row`, а
Совушка обновляет таблицу внутри текущего сообщения. Черновые кандидаты в таблицу не выводятся.

Отдельных обязательных resource-review, impact-review, dominant-review и `finish_norm_selection` нет.
После построчного mapping обязательна одна глобальная модельная ревизия всей таблицы. Её расчёт имеет
статус `priced_draft`; endpoint `/api/smeta-mappings/{revision_id}/lock` создаёт пользовательскую
immutable lock-ревизию и только затем отдельный финальный расчёт.
Одинаковая норма у похожих строк того же раздела/измерителя создаёт
`possible_duplicate_norm_binding`: validator ничего не меняет, а требует у global review или
пользователя явной проверки coverage и двойного учёта. Неразрешённый warning остаётся в draft.

## Точки входа

- `proxy.smeta_core.application` — единственная публичная application-граница смет: model-first
  workflow, расчёт уже принятых решений, immutable revision и finality.
- `proxy.smeta_core.document_workflow.run_vor_pdf_workflow` — zero-state PDF→ЛСР.
- `proxy.smeta_core.document_workflow._run_batch_norm_agent` — тонкий tool-loop модели.
- `proxy.smeta_core.document_workflow.SmetaNormToolSession` — единое состояние и исполнение LES tools.
- `proxy.smeta_core.professional_review` — typed mapping revisions, evidence budgets, conflict-validator
  и quality metrics; профессиональных решений не принимает.
- `proxy.services.smeta_agent_runner_service` — общий интерфейс и адаптеры Qwen-Agent/Google ADK.
- `tools/smeta_agent_benchmark.py` — изолированный quick/full гейт исходной ВОР; его проверки не
  импортируются production workflow.
  Последовательный quick-тест запускается так:
  `uv run python tools/smeta_agent_benchmark.py <путь-к-ВОР.xlsx> --engine qwen_agent --phase quick --batch-size 1`.
- `proxy.services.smeta_chat_application_service` — application flows ordinary smeta и PDF→ЛСР:
  безопасно открывает одноразовое вложение, координирует RAG/model/progress, сохраняет artifact/trace
  и возвращает response envelope. Профессиональных решений не принимает.
- `proxy.services.smeta_chat_adapter_service` — smeta transport/RAG adapters, prompts и parsers:
  runtime провайдера, document exchange, evidence packet, model-owned lookup/choice и numeric audit.
  Router этих реализаций не содержит и не собирает их вручную.
  Модель документа задаётся отдельно от модели обычного чата (`LES_SMETA_DOCUMENT_MODEL`). Для
  чистого сравнения резерв можно отключить пустым `LES_SMETA_DOCUMENT_FALLBACK_MODEL`.
  Для Ollama используется нативный `/api/chat`, потому что совместимый `/v1/chat/completions` теряет
  tool-calls `gemma4:12b`; tool results переводятся в нативное поле `tool_name`, а OpenAI-поля
  `name/tool_call_id` не передаются как будто это тот же протокол. Это transport-различие, а не
  отдельная логика выбора норм.
  Облачная модель по умолчанию получает всю ВОР одним разговором. Локальный native runner
  получает транспортные пакеты до 5 строк с общим контекстом соседних строк: это защищает `work_id`
  и tool JSON от смешивания/обрыва, но не выбирает нормы и не дробит общую immutable-ревизию.
  Оба document exchange используют `temperature=0`; локальный повторяемый профиль дополнительно
  передаёт `LES_SMETA_DOCUMENT_SEED` (default `0`) и сохраняет seed в trace. Нормализованные
  model-authored запросы и пакетные tool-вызовы сортируются перед retrieval без изменения scope.
  Qwen-Agent по умолчанию получает одну активную строку и накопленный `task_state` общей задачи.
  Ordinary-text завершение получает ограниченный same-model terminal recovery; отсутствие или
  расхождение `unbound_evidence` с tool trace отклоняет только transport-пакет, не решение модели.
  Полный список чужих `work_id` в пакет не копируется: для проверки coverage используются только
  `neighbor_context` текущих строк, иначе локальная модель ошибочно вызывает tools по всей ВОР.
  `LES_SMETA_DOCUMENT_BATCH_SIZE=0` явно возвращает один разговор; положительное значение меняет
  только размер транспортного пакета. Значение `1` включает накопленный последовательный контекст
  только для `qwen_agent`; профессиональные решения остаются модельными.
  Если модель без изменения содержания вложила `work_id` внутрь `technology_check`, transport
  переносит только этот идентификатор на верхний уровень. Норма, applicability, ограничения,
  resource actions и профессиональная аргументация остаются буквально модельными. Аналогично,
  одиночный `norm_code` в `read_norms_batch` принимается как одноэлементный `norm_codes`; значение
  кода не исправляется и не подменяется. Python не дополняет профессиональное решение. Отсутствующая
  обязательная анкета возвращается модели как ошибка transport-полноты; непрочитанная карточка или
  несовместимая единица сохраняют решение, но расчётный слой
  проверяет возможность вычисления построчно: несовместимая строка остаётся в ревизии модели и
  получает blocker, а остальные строки продолжают считаться.
- `proxy.smeta_core.norm_browser.browse_norm_catalog` — актуальная typed-навигация по семействам,
  сборникам и таблицам без статического списка в prompt.
- `proxy.smeta_core.norm_browser.browse_norms_many` — пакетный scoped RRF/FTS + configured reranker;
  выбранные моделью `table_codes` возвращаются полным официальным меню без ranking.
- `proxy.smeta_core.calculator.calculate_visible_rows_revision` — один расчёт решения модели.
- `proxy.services.smeta_user_message_service` — человеческое сообщение из готовой summary.
- `proxy.routers.chat` — request context, вызов application flow и общий history/response contract.

`estimate_harness_service` временно исполняет старый tool-loop только за
`smeta_core.application`; это implementation adapter, а не самостоятельная точка входа.
`construction_harness_service` и `unified_construction_harness_service` помечены
`LEGACY_PRIVATE`, остаются feature-off для старых evidence-fixtures и не входят в сметный маршрут.
Их старый `gesn_expand` больше не выбирает первый candidate кодом: он останавливается на
model-visible candidate list.

## Инструменты модели

### `browse_norm_catalog`

Возвращает текущую карту `family → collection → table` typed-каталога. Семейство, сборник и таблицу
выбирает модель. Повтор одной страницы возвращает короткий `already_seen`. Каталог является
навигацией, а не решением о применимости нормы.

### `search_norms_batch`

Принимает любое число независимых `work_id`, поисковые формулировки с обязательным `search_intent`
и выбранные моделью `base_types`/`collections`/`table_codes`. Обычный shortlist проходит configured
cross-encoder даже в batch из пяти и более строк; transport failure виден как `rerank_status`.
Выбранная таблица возвращается полностью по коду, без top-k и rerank: код не скрывает selector-range
и не выбирает строку. Кандидат сразу показывает `source_ref` и краткий
состав работ, а также `norm_key`, редакцию, семейство/сборник, совместимость измерителя, количество и
виды ресурсов, ресурсный preview и `matched_query`. Поля объясняют происхождение кандидата, но не
содержат code-side решения о применимости.
Одинаковые запросы
дедуплицируются, embedding/retrieval выполняются пакетно. Результаты не смешиваются между строками.
Score и порядок кандидатов не являются выбором нормы.
Если модель случайно переносит каталожный `limit=100` в ranked search, одна страница ограничивается
настроенным `candidate_limit`; `requested_limit`, фактический `page_size` и `has_more` остаются видимы,
а продолжение доступно явным `page`. Это защита model-context, не скрытый top-1.

### `read_norms_batch`

Открывает выбранные карточки из Typed SQLite: идентичность, измеритель, состав работ, ресурсы и
источники. Норму нельзя связать со строкой, пока модель её не открыла. По умолчанию ответ не повторяет
весь длинный список ресурсов для каждой нормы: модель видит их количество/виды и полный состав работ.
Если состав ресурсов влияет на решение или нужны `resource_actions`, сама модель повторяет чтение с
`include_resources=true` и получает все ресурсы без лимита. Полная карточка всё время остаётся в
расчётном контуре; это экономия model-context, а не удаление evidence.

Оба evidence tools доступны модели на каждом ходу. Python не назначает следующий tool. Если модель
завершила ход обычным текстом, нативный Ollama agent loop закончен и та же модель получает отдельный
вызов `format: JSON Schema`, который только сериализует её mapping. `tools` и `format` не смешиваются
в одном запросе.
Если модель подряд повторила полностью идентичный детерминированный tool-call, workflow также
останавливается сразу: повтор не меняет evidence и не должен превращаться в многоминутный цикл.
Профессиональная полнота evidence определяется skill и моделью, а не Python-gate.
Если Ollama-модель дважды сериализовала `items`/`rows` как JSON-строку внутри аргументов,
transport рекурсивно распаковывает только контейнеры JSON/Python literal. Все `work_id`, коды и
решения остаются дословными; исполняемый `eval` не используется.
Batch-level `page`/`limit`, которые Qwen кладёт рядом с `items`, применяются к элементам без своих
значений; это сохраняет выбранную моделью страницу вместо молчаливого возврата page 0.

### Structured model mapping

Передаёт завершённую модельную ревизию по исходным строкам через provider-enforced JSON Schema:

- `bind` — выбранная открытая норма, явные exact/analog и applicability, модельный
  `candidate_evaluations` и полный `technology_check`
  (совпавшие/отсутствующие/лишние операции, посторонние ресурсы, условия, пересечения и их разрешение)
  и массив ресурсных действий;
- `covered_by` — доказанное покрытие другой исходной строкой;
- `unbound` — модель осознанно оставила работу открытой и передала `unbound_evidence`: минимум две
  реально выполненные поисковые формулировки, открытые карточки, причины неприменимости и проверку
  coverage/decomposition.

Эти требования находятся в runtime skill. Python возвращает неполную обязательную анкету той же
модели на transport-исправление, но не меняет её норму или вывод. Неоткрытая карточка и несовместимый
измеритель сохраняют решение модели, а расчётный слой помечает невычислимую строку blocker-ом и
продолжает остальные. Каждое
`add|replace|exclude|reuse` по skill требует причины и `basis_ref`; неполное ресурсное действие также
становится построчным расчётным blocker, а не причиной переписывать mapping. Runtime skill требует от модели
не считать частичное технологическое совпадение exact и сверять выбранные нормы между строками, чтобы
подготовительные операции и слои не оплачивались дважды.
JSON Schema является transport-контрактом, а не профессиональным validator: значения полей создаёт
та же модель из собственной conversation history; Python их не дописывает и не меняет.

`candidate_evaluations` фиксирует оценку выбранной карточки по операции, объекту, измерителю, области
и чужим ресурсам. Если search показал несколько карточек, transport требует открыть и сравнить выбранную хотя
бы с одной реально открытой отклонённой/спорной альтернативой. Код проверяет ссылки и полноту,
но не оценивает причины и не меняет `selected|rejected|uncertain`.

Глобальная ревизия получает bounded-карту карточек: идентичность, до 12 операций, агрегат ресурсов и
до 8 примеров вместо полного ресурсного списка. Для спорной строки полная карточка повторно открывается
тем же `read_norms_batch`; typed evidence не заменяется summary.

Число строк и поисковых ходов не зашито под один тестовый объект. Транспорт поддерживает минимум
50 строк тем же контрактом. Локальный task имеет до 10 модельных ходов и независимые технические
лимиты: четыре search-вызова, четыре read-вызова, 12 открытых карточек и 180 секунд. На границе та же
модель фиксирует решение по уже собранным доказательствам. Это предел латентности, а не число
кандидатов или code-side выбор нормы. Terminal `submit_lsr_mapping` всегда разрешён после исчерпания
evidence budget: лимит обязан остановить дальнейший поиск, но не может отклонить уже принятое
моделью решение. Cloud сохраняет 64 модельных хода.

## Нормативное хранилище и retrieval

Typed SQLite — расчётная истина. `norm_key = base_type:bare_code` отделяет одинаковые цифровые коды
разных семейств. Qdrant является навигационным sibling-индексом. Поиск использует dense+sparse и RRF;
при несовпадении fingerprint/контракта dense не маскируется как исправный.

Структура базы, формула количества и источники РИМ описаны в
[`skills/smeta/references/gesn-storage.md`](../../skills/smeta/references/gesn-storage.md).

## Количества и деньги

```text
norm_quantity = source_quantity × unit_conversion_factor
resource_quantity = norm_quantity × per_unit × quantity_coefficient
```

Исходное количество входит в расчёт один раз. `quantity_multiplier` в tool-контракте отсутствует.
Альтернативные представления одного трудового ресурса дедуплицируются до денег.

Missing price хранится как `null`, не как бесплатный ресурс. В частичной ЛСР показывается известная
рассчитанная часть, а в редактируемом XLSX ячейки цены и стоимости такого ресурса остаются пустыми.
Строка работы показывает официальное название нормы и через `/` фактическое описание исходной работы;
шапка явно называет ресурсно-индексный метод (РИМ). НДС задаётся параметром расчёта; для текущего
сценария используется 22%.

## Артефакт и история

Формульный XLSX, trace и download contract сохраняются вместе с сообщением. При открытии истории
Совушка должна восстановить карточку того же файла без повторного расчёта и без вызова модели.
Внешний ответ формируется отдельно от машинного JSON и не показывает служебные имена полей.

## Clean-install baseline и гейты

Windows release не строит нормативную базу из случайного локального parquet. `make patch-release`
создаёт `LES-smeta-baseline.zip` из canonical typed source/SQLite/manifest/integrity и ФСЭМ,
проверяет SHA и нижние границы 40 000 норм / 1 500 машин, передаёт архив на Legion и встраивает в EXE.
Bootstrap разворачивает его только в пустой persistent state. `build_smeta_structured_base` до замены
канонического файла проверяет `minimum_norms`, поэтому результат 171 или 14 570 норм не может затереть
живую базу. Все проверочные SQLite-соединения закрываются до `replace`, поэтому тот же атомарный
контракт работает на Windows, где открытый файл нельзя переименовать. Clean-install smoke повторно
проверяет фактические SQLite после установки.
Это гейт норм/ресурсов и ФСЭМ, а не ценовой гейт: региональная Сплит-форма выбирается по субъекту,
ценовой зоне и периоду после установки. Без неё точные цены остаются `MISSING`.

Операторское полное обновление ФГИС имеет отдельный persistent status contract. Он различает запуск,
получение каталога, загрузку Сплит-форм, загрузку ГЭСН и локальные стадии unify/SQLite/RAG; возвращает
heartbeat, текущий регион/период или сборник/отдел, completed/total/remaining, скачанные байты,
среднюю скорость и ETA. Живой PID без свежего heartbeat объясняется как ожидание ответа ФГИС или
длительная локальная операция; исчезнувший PID при `status=running` маркируется как прерванный job.

Гейты:

- `tests/test_smeta_core.py` — catalog/table/search/read, model-owned выбор, полный technology/resource evidence,
  50 строк, единицы и один расчёт.
- `tests/test_smeta_norm_browser.py`, `tests/test_smeta_rerank_ab_probe.py` — batch rerank,
  явный transport status, полный table listing и контракт живого A/B smoke.
- `tests/test_rim_trace_xlsx.py` — форма РИМ, официальное наименование и пустая missing price.
- `tests/test_smeta_prompt_freedom.py` — отсутствие объектных якорей и скрытого selector.
- `tests/test_prompt_registry_service.py` — загрузка полного canonical skill и prompt registry.
- `tests/test_specification_to_bor_contract.py` — model-owned декомпозиция и quantity trace.
- `tests/test_smeta_release_baseline.py` — SHA/count/integrity, clean provision и запрет overwrite.
- `tests/test_installer_windows.py` — baseline в bootstrap и обязательная Windows-smoke проверка.
- `tools/smeta_document_live_smoke.py` — реальная ВОР, выбранная модель, отключённый fallback и
  обязательный ненулевой XLSX; `--only-row` оставлен для диагностики tool-контракта.
- `make verify`, `make test-unit`, `make test-integration` и `make test` — офлайн-гейты;
  `make smoke-active-artifacts` проверяет active base, `make smoke-smeta-rerank` — живую
  цепочку active base → Qdrant/RRF → cross-encoder.

## Открытые долги

- Доказать полноту всех семейств/редакций сверх общего floor и закрыть полный ценовой контур ФГИС/КАЦ.
- Повторять live zero-state ВОР→XLSX для каждой production-модели перед выпуском и отдельно
  оценивать профессиональное качество выбранных норм; зелёный transport не равен экспертизе.
- Завершить clean dense+sparse reindex общего RAG и только после гейтов переключить alias.

Эти долги влияют на качество/полноту денег, но не дают права возвращать кодовый выбор норм или
многоступенчатый оркестратор.
