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
   `Qx.Hy`; ранние запросы не могут вытеснить поздние.
4. Фактически показанные модели chunks образуют immutable evidence manifest.
   Следующая реплика получает компактный индекс использованного evidence и тот
   же frozen scope, но не повторные полные тела фрагментов.
5. Source map хранит `evidence_ref`, `source_ref`, страницу и typed locator:
   `file_excerpt`, `norm_card`, `web_result` или `unavailable`. UI отдельно
   показывает найденные, показанные модели и процитированные источники.
6. `selected_sources_only=true` исполняемо удаляет web capability; при `false`
   web остаётся доступен согласно профилю. Между репликами флаг наследуется из
   manifest, если пользователь не изменил его явно.

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

## Точки входа

- `proxy/services/chat_profile_service.py`
- `proxy/services/retrieval_candidate_service.py`
- `proxy/services/retrieval_service.py`
- `proxy/services/model_research_tool_service.py`
- `proxy/services/chat_evidence_application_service.py`
- `proxy/services/chat_evidence_manifest_service.py`
- `proxy/services/chat_capability_scope_service.py`
- `proxy/services/source_locator_service.py`
- `proxy/services/runtime_admission.py`
- `proxy/services/rag_{readiness,pipeline_status,advanced_policy}_service.py`
- `sovushka/pages/{chat,profiles,diag}.py`

Сметное ядро `proxy/smeta_core/**` этим модулем не изменяется.
