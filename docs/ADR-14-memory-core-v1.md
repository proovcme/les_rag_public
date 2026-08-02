# ADR-14 — Memory Core v1

> **Locked learning rule (2026-08-02):** smeta traces with candidate trust are
> stored for review but never recalled. Advisory and route reuse require
> `accepted_project|verified_pattern`. Rows calculated as
> `model_batch_candidate` are excluded from capture, so Memory cannot amplify
> an unconfirmed model choice. Explicit user mapping lock/root-admin review is
> the promotion signal; Memory never confirms itself.

**Статус:** принято · **Дата:** 2026-08-02

## Решение

Memory Core — изолированный сосед RAG, а не новый центр LES. Он хранит проектные факты и проверяемые трассы в общей MetaDB, работает через заменяемый `MemoryPort` и по умолчанию выключен. Память является только advisory-контекстом: она не считается evidence текущего запроса, не заменяет поиск и не принимает сметные решения.

Режимы:

- `off` — `NullMemoryPort`, без recall, очереди и фонового worker;
- `shadow` — строгий capture и извлечение кандидатов, без recall;
- `on` — capture и ограниченный project-scoped advisory recall.

Сметный capture включается отдельным флагом. Сметный recall имеет режимы `off`, `advisory`, `route_reuse`; фактически он доступен только при общем `mode=on`. Выпуск поставляется с `LES_MEMORY_MODE=off`.

## Зафиксированные границы

Обычный RAG-turn ставится в очередь только одновременно при выполнении условий: разрешён положительный `project_id`; `crag_status == VERIFIED`; маршрут — обычный grounded evidence-flow; cache hit отсутствует; evidence packet содержит хотя бы одну ссылку с `is_evidence=true`. `UNVALIDATED`, free/no-evidence, ЛИСТ и сметный маршрут в очередь обычного RAG не попадают. `dataset_id` никогда не становится проектом неявно.

Recall всегда фильтруется по `project_id`; межпроектного recall нет. Факты нельзя повысить до function/global scope. Root-admin может повысить только проверенные non-fact kinds — трассы и паттерны.

Текст LLM/RAG создаёт только `candidate`. Код может подтвердить лишь typed exact locator либо вычисление с формулой, входами и evidence. Memory не подтверждает саму себя. При несовместимых значениях обе записи становятся `disputed`; confidence не выбирает победителя.

Request path ограничен bounded SQLite recall и одним `INSERT` в durable queue. Извлечение выполняет только локальная модель, один worker, через общий LLM semaphore и лишь при свободном слоте. Ошибка Memory всегда fail-open и не отменяет ответ чата или опубликованную смету.

Успешная смета наблюдается только после публикации XLSX и JSON trace, при положительном `project_id` и finality `priced_draft|priced_final`. Observer читает результат и не изменяет `proxy/smeta_core/`. Route reuse допускается лишь для того же проекта, точной нормализованной сигнатуры работы и совпадающей редакции/ревизии каталога. Передаётся только family/collection/section/table; норма, применимость, коэффициенты, ресурсы и цена не переносятся. Если typed route или identity редакции отсутствуют, reuse закрыт.

API `/api/memory/*` доступен только root-admin. GUI сохраняет явный операторский выбор в MetaDB для следующего штатного старта и отдельно подтверждает опасный `route_reuse`. Сохранённый выбор имеет приоритет над поставляемым env-default, иначе выключенный по умолчанию модуль нельзя было бы включить из GUI.

## Не входит в v1

Memory fast-path, пропуск RAG, Qdrant-индекс памяти, cloud extractor, автоматические переходы режимов, переписывание smeta/RIM, UI просмотра фактов и разрешения конфликтов.

## Откат

Установить `LES_MEMORY_MODE=off` и штатно перезапустить LES. При этом все точки интеграции получают `NullMemoryPort`; таблицы Memory в MetaDB остаются неактивными и могут быть сохранены для аудита.
