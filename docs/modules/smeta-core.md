# Smeta Core — единое сметное ядро

> **Статус 2026-07-17: ✅ код и документ синхронизированы.** Канонический PDF→ЛСР путь —
> model-owned evidence loop через переключаемый agent runner и один расчёт общей ревизии.

## Архитектурная граница

```text
исходник / ВОР / спецификация
  → source_intake: строки, количества, единицы, координаты
  → SmetaAgentRunner: native | Qwen-Agent | Google ADK
  → модель + skills/smeta/references/document-mapping-agent.md
  → search_norms_batch: RRF dense+sparse, только кандидаты
  → read_norms_batch: фактические карточки Typed SQLite
  → submit_lsr_mapping: решения той же модели по строкам текущего пакета
  → calculator: единицы, ресурсы, цены, РИМ, НР/СП, НДС
  → formula XLSX + журнал проверки + короткий ответ
```

Модель выбирает работы, декомпозицию, запросы, нормы, аналоги, coverage и ресурсные действия
`add|replace|exclude|reuse`. Код не выбирает, не переписывает и не возвращает на профессиональный
retry решение модели. Он проверяет только машинную адресацию (`work_id`, отсутствие дублей и форму
transport payload); непрочитанная карточка, несовместимая единица и неполные доказательные поля сохраняются
в модельной ревизии как построчные расчётные blockers. Python не содержит второго профессионального
prompt: фазовый контракт находится внутри canonical skill package и содержит только правила mapping,
а не нерелевантные этой фазе РИМ/ФГИС/НР/СП и оформление ответа.

`SmetaNormToolSession` хранит показанные карточки, принятые строки и trajectory. Все runner'ы
исполняют один и тот же контракт; встроенные RAG, MCP, Google Search и code interpreter выключены.
`native` остаётся default до живого профессионального гейта. `qwen_agent` использует локальный
Ollama; Qwen-Agent управляет loop, но на актуальном Ollama включает raw function serialization,
так как Nous text wrapper возвращает серверный `500 EOF`. `google_adk` — прямой Google API только
после `LES_CLOUD_CONSENT=true`; отсутствие ключа или
согласия является явной ошибкой без fallback.

Отдельных обязательных resource-review, impact-review, dominant-review и
`finish_norm_selection` нет. После полного structured mapping выполняется один расчёт без нового
обращения к модели.

## Точки входа

- `proxy.smeta_core.application` — единственная публичная application-граница смет: model-first
  workflow, расчёт уже принятых решений, immutable revision и finality.
- `proxy.smeta_core.document_workflow.run_vor_pdf_workflow` — zero-state PDF→ЛСР.
- `proxy.smeta_core.document_workflow._run_batch_norm_agent` — тонкий tool-loop модели.
- `proxy.smeta_core.document_workflow.SmetaNormToolSession` — единое состояние и исполнение LES tools.
- `proxy.services.smeta_agent_runner_service` — общий интерфейс и адаптеры Qwen-Agent/Google ADK.
- `tools/smeta_agent_benchmark.py` — изолированный quick/full гейт исходной ВОР; его проверки не
  импортируются production workflow.
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
  Облачная модель по умолчанию получает всю ВОР одним разговором. Локальная production-модель
  получает транспортные пакеты до 10 строк с общим контекстом соседних строк: это защищает `work_id`
  и tool JSON от смешивания/обрыва, но не выбирает нормы и не дробит общую immutable-ревизию.
  Полный список чужих `work_id` в пакет не копируется: для проверки coverage используются только
  `neighbor_context` текущих строк, иначе локальная модель ошибочно вызывает tools по всей ВОР.
  `LES_SMETA_DOCUMENT_BATCH_SIZE=0` явно возвращает один разговор; положительное значение меняет
  только размер транспортного пакета.
  Если модель без изменения содержания вложила `work_id` внутрь `technology_check`, transport
  переносит только этот идентификатор на верхний уровень. Норма, applicability, ограничения,
  resource actions и профессиональная аргументация остаются буквально модельными. Аналогично,
  одиночный `norm_code` в `read_norms_batch` принимается как одноэлементный `norm_codes`; значение
  кода не исправляется и не подменяется. Python не дополняет и не отклоняет профессиональное решение
  из-за отсутствующей анкеты, непрочитанной карточки или несовместимой единицы. Расчётный слой
  проверяет возможность вычисления построчно: несовместимая строка остаётся в ревизии модели и
  получает blocker, а остальные строки продолжают считаться.
- `proxy.smeta_core.norm_browser.browse_norms_many` — пакетный RRF-поиск.
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

### `search_norms_batch`

Принимает любое число независимых `work_id` и поисковых формулировок. Одинаковые запросы
дедуплицируются, embedding/retrieval выполняются пакетно. Результаты не смешиваются между строками.
Score и порядок кандидатов не являются выбором нормы.

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

- `bind` — выбранная открытая норма, явные exact/analog и applicability, полный `technology_check`
  (совпавшие/отсутствующие/лишние операции, посторонние ресурсы, условия, пересечения и их разрешение)
  и массив ресурсных действий;
- `covered_by` — доказанное покрытие другой исходной строкой;
- `unbound` — модель осознанно оставила работу открытой и передала `unbound_evidence`: минимум две
  реально выполненные поисковые формулировки, открытые карточки, причины неприменимости и проверку
  coverage/decomposition.

Эти требования находятся в runtime skill. Python не заставляет модель повторно выбирать норму из-за
неполной анкеты, неоткрытой карточки или несовместимого измерителя. Он сохраняет решение модели,
а расчётный слой помечает невычислимую строку blocker-ом и продолжает остальные. Каждое
`add|replace|exclude|reuse` по skill требует причины и `basis_ref`; неполное ресурсное действие также
становится построчным расчётным blocker, а не причиной переписывать mapping. Runtime skill требует от модели
не считать частичное технологическое совпадение exact и сверять выбранные нормы между строками, чтобы
подготовительные операции и слои не оплачивались дважды.
JSON Schema является transport-контрактом, а не профессиональным validator: значения полей создаёт
та же модель из собственной conversation history; Python их не дописывает и не меняет.

Число строк и поисковых ходов не зашито под один тестовый объект. Транспорт поддерживает минимум
50 строк тем же контрактом. Для локальной модели технический budget по умолчанию — 6 evidence-ходов
на пакет, после чего та же модель фиксирует решение по уже собранным доказательствам. Это предел
латентности, а не число кандидатов или code-side выбор нормы; cloud сохраняет 64 хода.

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
живую базу. Clean-install smoke повторно проверяет фактические SQLite после установки.
Это гейт норм/ресурсов и ФСЭМ, а не ценовой гейт: региональная Сплит-форма выбирается по субъекту,
ценовой зоне и периоду после установки. Без неё точные цены остаются `MISSING`.

Операторское полное обновление ФГИС имеет отдельный persistent status contract. Он различает запуск,
получение каталога, загрузку Сплит-форм, загрузку ГЭСН и локальные стадии unify/SQLite/RAG; возвращает
heartbeat, текущий регион/период или сборник/отдел, completed/total/remaining, скачанные байты,
среднюю скорость и ETA. Живой PID без свежего heartbeat объясняется как ожидание ответа ФГИС или
длительная локальная операция; исчезнувший PID при `status=running` маркируется как прерванный job.

Гейты:

- `tests/test_smeta_core.py` — три инструмента, model-owned выбор, полный technology/resource evidence,
  50 строк, единицы и один расчёт.
- `tests/test_rim_trace_xlsx.py` — форма РИМ, официальное наименование и пустая missing price.
- `tests/test_smeta_prompt_freedom.py` — отсутствие объектных якорей и скрытого selector.
- `tests/test_prompt_registry_service.py` — загрузка полного canonical skill и prompt registry.
- `tests/test_specification_to_bor_contract.py` — model-owned декомпозиция и quantity trace.
- `tests/test_smeta_release_baseline.py` — SHA/count/integrity, clean provision и запрет overwrite.
- `tests/test_installer_windows.py` — baseline в bootstrap и обязательная Windows-smoke проверка.
- `tools/smeta_document_live_smoke.py` — реальная ВОР, выбранная модель, отключённый fallback и
  обязательный ненулевой XLSX; `--only-row` оставлен для диагностики tool-контракта.
- `make verify` и `make test` — релизный офлайн-гейт.

## Открытые долги

- Доказать полноту всех семейств/редакций сверх общего floor и закрыть полный ценовой контур ФГИС/КАЦ.
- Повторять live zero-state ВОР→XLSX для каждой production-модели перед выпуском и отдельно
  оценивать профессиональное качество выбранных норм; зелёный transport не равен экспертизе.
- Завершить clean dense+sparse reindex общего RAG и только после гейтов переключить alias.

Эти долги влияют на качество/полноту денег, но не дают права возвращать кодовый выбор норм или
многоступенчатый оркестратор.
