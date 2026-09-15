# RAG evidence flow

## Назначение

Обычный чат и model-authored estimate используют один принцип: модель сама
формулирует запросы и пишет итог, код только выполняет retrieval, сохраняет
provenance и механически исполняет разрешённый постпроцессинг. Дополнительного
planner/model-review шага и JSON-протокола между моделью и RAG нет.

## Активный поток

1. Effective chat profile задаёт `candidate_k`, `document_diversity_k` и
   `model_evidence_k`. Заводские значения — `64 / 2 / 6`; пользовательская
   ревизия хранит свои значения, GUI показывает effective policy.
2. Native dense+sparse RRF получает широкий `candidate_k`. Код удаляет только
   точные дубли фрагментов и ограничивает число фрагментов одного физического
   документа, затем передаёт модели `model_evidence_k` результатов.
3. Для model-authored запросов каждая группа сохраняется независимо как
   `Qx.Hy`; ранние запросы не могут вытеснить поздние. Если заголовки всех
   `Q`/`H` не влезают в остаток окна, код не падает: влезающий префикс
   показывается, остаток запросов на sheet-pass идёт следующим техническим
   пакетом без нового поиска, а в одном выстреле честно попадает в
   `omitted_evidence_refs`. Карточки по-прежнему omit, а не shred.
   Транспорт принимает обычные строки. Кавычки и явно написанная самой моделью
   оболочка `search_sources("…")` снимаются только синтаксически; вступительная
   проза при наличии таких строк не превращается в дополнительный запрос.
   Пакетный sheet-pass — тот же порядок, что у малого исходника: модель
   формулирует запросы, получает источники, принимает решения, код считает.
   Порог «маленький/большой документ» не выбирает другой контур. Первое
   принятое решение модели по строке сохраняется, обязательный verifier
   и кодовые заглушки при исчерпании попыток не запускаются. Кэш запросов и
   незакрытые locators живут в `workbook_research_jobs`; повтор поиска
   обработанного не выполняется, повтор упаковки XLSX — без модели.
   Оператор может уточнить выбранные locator или внести подтверждённые
   данные (`conversion_factor`/`conversion_source`) без смены шифра.
   Упаковка XLSX принимает то же `confirmed_data` в контракте
   `build_lsr_workbook`; поле доходит до расчёта, а не отвергается schema.
4. Фактически показанные модели chunks образуют immutable evidence manifest.
   Следующая реплика получает компактный индекс использованного evidence и тот
   же frozen scope, но не повторные полные тела фрагментов.
5. Source map хранит `evidence_ref`, `source_ref`, страницу и typed locator:
   `file_excerpt`, `norm_card`, `web_result` или `unavailable`. UI отдельно
   показывает найденные, показанные модели и процитированные источники.
6. `selected_sources_only=true` исполняемо удаляет web capability; при `false`
   web остаётся доступен согласно профилю. Между репликами флаг наследуется из
   manifest, если пользователь не изменил его явно.
7. Web policy принадлежит GUI: `simple` использует рабочий DuckDuckGo,
   `extended` запрашивает SearXNG и даёт модели отдельный `web_read` для
   выбранной страницы через Crawl4AI. Недоступный расширенный поиск явно
   деградирует в simple; код не выбирает страницу за модель.
8. После финального ответа упаковочный reader читает явные таблицы или явные
   подписанные поля. Короткий divider `:--`, заголовок «Норматив монтажа
   (norm_code)» и спецификационная таблица без `norm_code` допустимы; `###`
   задаёт секцию, если это не заголовок `Строка N`. Обычный заголовок
   `Строка N: название` допустим, если сам блок содержит явные поля. Reader не
   извлекает решение из произвольной прозы, не переписывает значения модели и
   не выбирает ЛСР/ВОР по тексту вопроса.

## Надёжность и readiness

- Параллельный model request ждёт публичный semaphore API до bounded timeout;
  приватный `_value` не читается. Отмена освобождает только реально полученный
  permit.
- HTTP/SSE/model-visible tool result получают стабильный код и операторский
  текст; класс исключения и diagnostic detail остаются в логах/trace.
- Readiness разделяет `backend_available`, `contract_complete`,
  `optional_stages` и per-query `query_quality`. Слабый отдельный запрос не
  делает исправный backend или контракт красным.
- RAPTOR по умолчанию `off`. ColBERT вызывается только при status `ready`,
  закрытом breaker и audited active-generation contract с полной multivector
  readiness; отсутствие такой генерации — обычный `not_ready` bypass.
- Приёмочный runtime может выставить
  `LES_STARTUP_BACKGROUND_MUTATIONS=false`: startup тогда не запускает repair,
  generation reconciliation и resume supervisors. Default остаётся `true` и
  виден в runtime registry.
- Admission различает загрузку точной локальной answer-model и чужой модели.
  Для уже резидентной модели действует отдельный жёсткий RAM floor; swap guard
  сохраняется. Chat не заменяет выбранный Ollama/MLX provider по уровню RAM.

## Точки входа

- `proxy/services/chat_profile_service.py`
- `proxy/services/retrieval_candidate_service.py`
- `proxy/services/retrieval_service.py`
- `proxy/services/model_research_tool_service.py`
- `proxy/services/chat_evidence_application_service.py`
- `proxy/services/lsr_source_coverage_service.py`
- `proxy/services/lsr_result_readiness_service.py`
- `proxy/services/workbook_research_job_service.py`
- `proxy/services/chat_evidence_manifest_service.py`
- `proxy/services/chat_capability_scope_service.py`
- `proxy/services/source_locator_service.py`
- `proxy/services/runtime_admission.py`
- `proxy/services/web_{research_config,search,page_reader}_service.py`
- `proxy/services/rag_{readiness,pipeline_status,advanced_policy}_service.py`
- `sovushka/pages/{chat,profiles,diag}.py`

Сметное ядро `proxy/smeta_core/**` этим модулем не изменяется.
