# ALGO-context-memory — память чата и паспорт датасета

## Назначение

Дать ЛЕС “взрослую” рабочую память без подмены evidence: текущий чат получает компактный паспорт
диалога, а каждый выбранный датасет — детерминированный паспорт корпуса. С 0.24.0.29 над паспортами
появился общий `notebook_v1`: компактная карта содержания/поиска для датасетов и служебных источников
(первый системный блокнот — ГЭСН). С 0.24.0.4 паспорт может быть
`metadata` или `deep`: глубокий слой читает только уже готовый lexical index, без reindex/OCR/LLM. С 0.24.0.17
паспорт получает `quality`-оценку полезности и замер прогрева: cold rebuild против тёплого чтения кэша.
Паспорта и блокноты ускоряют маршрутизацию и понимание задачи, но не являются источником фактов, норм или чисел.

## Точки входа

- `proxy/services/context_memory_service.py` — сборка/хранение профилей.
- `proxy/services/notebook_service.py` — `notebook_v1` поверх профилей и служебных источников;
  ГЭСН-блокнот генерируется из локальной базы норм и даёт карту сборников.
- `proxy/services/prompt_registry_service.py` — общий LES prompt и режимные prompts; smeta получает
  ГЭСН-блокнот перед tool-contract.
- `proxy/services/memory_service.py` — короткая история текущей сессии (`session_memory`,
  `session_user_questions`, `session_recent_retrieval_traces`) для прямых LLM-путей,
  детерминированного состояния smeta/object и продолжений tool-расчётов.
- `proxy/routers/chat.py` — подмешивает паспорт в RAG-промпт после resolve scope и обновляет профиль
  при `save_chat_history`; в `free`/read-attachment добавляет `session_memory` как фон, а в явном
  `smeta` использует вопросы сессии для переноса полей объектной сметы и `retrieval_trace` прошлых
  tool-ответов для продолжений вроде «учти высотные работы».
- `GET /api/chat/memory/{session_id}` — просмотр паспорта чата.
- `GET /api/rag/datasets/{dataset_id}/profile?depth=deep|metadata` — просмотр паспорта датасета.
- `GET /api/notebooks/{dataset_id}?depth=deep|metadata` — просмотр notebook/passport датасета.
- `POST /api/notebooks/warmup` — прогрев notebook-слоя без reindex.
- `GET /api/service-sources/notebooks` — системные блокноты, сейчас `gesn`.
- `POST /api/rag/datasets/{dataset_id}/profile/refresh?depth=deep|metadata` — принудительная пересборка паспорта датасета.
- `POST /api/rag/datasets/profiles/warmup` — прогрев паспортов выбранных/всех датасетов.
- `POST /api/rag/datasets/profiles/benchmark` — no-reindex замер: `cold_rebuild_ms` против `warm_read_ms`,
  `speedup_x`, `quality_status/score` по каждому датасету.
- Sidecar датасета: `storage/datasets/{dataset_id}/_les_dataset_profile.json`.

## Данные

SQLite `data/les_meta_qwen.db`:

- `les_chat_profiles(session_id, profile_json, turn_count, updated_at)`.
- `les_dataset_profiles(dataset_id, profile_json, content_signature, profile_path, updated_at)`.

`metadata`-паспорт датасета строится только из известных метаданных `datasets`/`documents`: имя, статус,
количество файлов/чанков, расширения, типы документов, домены, route-dataset, статусы и примеры файлов.

`deep`-паспорт добавляет bounded-read по `lexical_chunks`: число lexical-чанков/документов, top-документы,
частые headings, ключевые слова по содержанию, нормативные ссылки, table-signal и короткие representative
fragments. Исходные файлы не читаются.

`quality` — компактная вычисляемая оценка паспорта: документы, чанки, примеры файлов, ключевые слова,
типы/расширения, наличие lexical/deep-сигналов, фрагменты, нормативные ссылки и таблицы. Статусы:
`good`, `partial`, `weak`, `empty`. Это качество навигационного паспорта, не оценка истинности будущего ответа.

`notebook_v1` — тонкая обёртка над паспортом: `notebook_summary` (назначение, типы документов,
предметные области, ключевые термины, нормативные ссылки, ограничения, как искать внутри),
`prompt_excerpt`, `context_role=navigation`, `is_evidence=false`. Для ГЭСН notebook строит
`collections`: идентификатор сборника, область работ, частые термины, единицы и примеры кодов из
локальной базы. Идентификатор учитывает тип базы: обычный строительный `ГЭСН38` и монтажный
`ГЭСНм38` не схлопываются в один раздел, потому что это разные нормативные области.

Паспорт чата обновляется из факта сохранённого ответа: последний вопрос/ответ, route, scope, датасеты,
статус, принятые допущения и MISSING/blockers, извлечённые простыми regex из ответа.

Короткая история сессии (`session_memory`) — отдельный слой: последние Q/A текущего `session_id`,
подмешанные в prompt как фон. Для smeta/object используется строже: список прошлых вопросов
пользователя (`session_user_questions`) — для детерминированного merge полей `object/material/floors/area`,
а последние `retrieval_trace` (`session_recent_retrieval_traces`) — только как параметры уже выполненных
инструментов (масса, ярусы, статус, ставки) для продолжений расчёта. Это не источник норм, цен или новых
итоговых чисел.

## Поток

1. `/api/chat` получает вопрос.
2. Обычный scope/project/dataset resolver определяет реальные `dataset_ids`.
3. `build_context_memory_block()` читает/создаёт deep-паспорта выбранных датасетов (лимит в prompt)
   и читает паспорт сессии.
4. Блок добавляется к `memory_block` как фон:
   `Память контекста (... НЕ evidence)`.
5. После ответа `save_chat_history()` пишет историю и вызывает `update_chat_profile()`.
6. При изменении состава `documents`/`datasets` меняется `content_signature`; паспорт датасета
   пересобирается и sidecar перезаписывается.
7. `warmup_dataset_profiles()` может заранее прогреть паспорта без запроса в чат.
8. `benchmark_dataset_profile_warmup()` принудительно пересобирает паспорт, затем сразу читает кэш и
   возвращает разницу скорости. Это проверяет пользу прогрева без переиндексации и без запуска LLM.
9. `build_dataset_notebook()` и `service_source_notebooks()` дают общий notebook-контекст для режимов.
10. `estimate_harness` получает `LES_SYSTEM_PROMPT + smeta prompt + ГЭСН notebook excerpt + tool contract`.

## Границы

- Паспорт не доказывает ответ. Любая норма, цена, объём и расчёт должны идти из retrieved context,
  structured data или расчётного сервиса.
- Notebook не является отдельным механизмом под режим: это общий навигационный слой. Режимы только выбирают,
  какой excerpt добавить к своему prompt.
- Паспорт чата не является долговременной памятью оператора. Команды `запомни:` остаются в
  `memory_service.py`.
- Паспорт датасета не запускает переиндексацию и не читает тяжёлые файлы.
- Deep-паспорт зависит от наличия `lexical_chunks`; если lexical index не готов, профиль честно пишет
  `available=false`.
- Benchmark меряет только паспортный слой (`les_dataset_profiles` + sidecar + lexical sample). Он не является
  полноценным RAG quality benchmark и не гарантирует ускорение генерации модели.
- Ошибка записи профиля не ломает чат: слой best-effort, пишет warning.

## Тесты

- `tests/test_context_memory_service.py` — sidecar датасета, deep-профиль из bounded lexical index,
  quality-сигналы, warmup/benchmark/notebook, ГЭСН-блокнот, обновление chat-profile через
  `save_chat_history`, prompt-block с явной маркировкой `НЕ evidence`.
- `tests/test_notebook_api.py` — публичные notebook endpoints.
