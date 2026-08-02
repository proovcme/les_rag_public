# Memory Core — проектная advisory-память LES

## Verified smeta learning (v1)

Published estimate traces are captured as candidates for audit. They become
model-facing advisory or reusable catalog routes only after an explicit user
lock/root-admin confirmation changes trust to `accepted_project` (or after a
root-admin verified-pattern review). A calculated row with
`review_status=model_batch_candidate` is not captured at all. Recall remains
project-scoped and `is_evidence=false`; it may shorten catalog navigation but
cannot select a norm or skip current typed evidence.

## Назначение и границы

Memory Core сохраняет подтверждённые grounded-turns в durable queue, извлекает из них кандидаты проектных фактов локальной моделью и хранит compact traces опубликованных смет. Источником истины остаются документы, typed readers и нормативные каталоги. Memory не является evidence текущего ответа и никогда не выбирает норму.

## Точки входа

- `proxy/memory_core/` — contracts, SQLite store, validation, conflicts и configuration;
- `proxy/services/memory_port.py` — `MemoryPort` и безопасный `NullMemoryPort`;
- `proxy/services/chat_evidence_application_service.py` — один post-success enqueue hook обычного RAG и advisory recall;
- `proxy/services/memory_worker_service.py` — локальный low-priority extractor;
- `proxy/services/smeta_chat_application_service.py` → `memory_smeta_observer.py` — read-only capture после публикации сметы;
- `proxy/routers/memory.py` — root-admin `/api/memory/status|config|entries|review|promote`;
- `sovushka/pages/diag.py` — панель «Память проектов» в «Конфигурация».

## Хранение

Таблицы `memory_entries`, `memory_evidence_refs`, `memory_conflicts`, `memory_project_snapshots`, `memory_ingest_queue`, `memory_smeta_traces`, `memory_observer_cursors` и `memory_config` живут в канонической MetaDB. Все project records требуют положительный `project_id`. Store не обращается к Qdrant.

## Поток

`grounded RAG response → strict predicate → queue INSERT → local extractor → candidate facts → deterministic conflict marking → project snapshot`.

`published priced smeta → read-only projection → project smeta trace`. Если опубликованный результат не несёт typed catalog route с edition/revision, трасса остаётся advisory и не используется как route cache.

## Конфигурация

- `LES_MEMORY_MODE=off|shadow|on` — default `off`;
- `LES_MEMORY_SMETA_CAPTURE=true|false` — default `true`, инертно при `off`;
- `LES_MEMORY_SMETA_RECALL=off|advisory|route_reuse` — default `off`;
- `LES_MEMORY_LOCAL_MODEL` — локальная Ollama-модель extractor.

Root-admin GUI/API сохраняет явный выбор в MetaDB; он имеет приоритет над поставляемым env-default и применяется после штатного перезапуска.

## Проверки

`tests/test_memory_core.py`, `tests/test_memory_api.py`, `tests/test_memory_ui_contract.py`, `tests/test_smeta_memory_isolation.py`. Регрессия смет проверяется отдельно; защищённый `proxy/smeta_core/document_workflow.py` Memory не меняет.
