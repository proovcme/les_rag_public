# ALGO-context-memory — память чата и паспорт датасета

## Назначение

Дать ЛЕС “взрослую” рабочую память без подмены evidence: текущий чат получает компактный паспорт
диалога, а каждый выбранный датасет — детерминированный паспорт корпуса. С 0.24.0.29 над паспортами
появился общий `notebook_v1`: компактная карта содержания/поиска для датасетов и служебных источников
(первый системный блокнот — ГЭСН). С 0.24.0.4 паспорт может быть
`metadata` или `deep`: глубокий слой читает только уже готовый lexical index, без reindex/OCR/LLM. С 0.24.0.17
паспорт получает `quality`-оценку полезности и замер прогрева: cold rebuild против тёплого чтения кэша.
Паспорта и блокноты ускоряют маршрутизацию и понимание задачи, но не являются источником фактов, норм или чисел.
С 0.24.0.177 обычный prompt получает не полный служебный dump карты, а компактный
`dataset_brief_for_model_v1`: brief объясняет модели, что за корпус выбран, какие файлы открыть первыми,
как file cards связаны с реальными чанками, и какой маршрут чтения подходит под текущий вопрос. Модель и
режимный prompt остаются главным слоем решения; brief только помогает не заблудиться в датасете.
С 0.24.0.206 typed memory дополнительно хранит `source_layers`, `retrieval_routes` и компактный
`dataset_source_graph_v1`: модель видит, что означает каждый слой данных, какой маршрут чтения подходит
под тип вопроса и какие файлы являются первыми точками входа. Это системное улучшение RAG-навигации,
а не режимный шаблон ответа.
С 0.24.0.207 оператор может добавить к датасету `operator_guidance`: короткое человеческое пояснение
для модели о том, как читать корпус. Это поле сохраняется в профиле/sidecar и попадает в prompt как
навигационная подсказка, но не является evidence и не заменяет найденные фрагменты, таблицы или расчёт.
В том же слое сметные нормативные архивы `SMETA_RU_NORM/FSNB` типизируются как `normative`, а служебные
файлы `manifest/dataset_card/preprocess_state` понижаются в first-files, чтобы модель открывала нормы,
а не упаковочную ведомость самой базы.

## Точки входа

- `proxy/services/context_memory_service.py` — сборка/хранение профилей.
- `PATCH /api/rag/datasets/{dataset_id}/profile/guidance` — сохранить операторское пояснение для модели;
  no-reindex, пишет только профиль/sidecar и синхронизирует typed memory.
- `sovushka/pages/documents.py` — no-AI вкладка «Документы»: документы/фрагменты и человеческая витрина
  карты датасета (`source_layers`, `retrieval_routes`, `слой -> файлы`, `operator_guidance`).
- `proxy/services/notebook_service.py` — `notebook_v1` поверх профилей и служебных источников;
  ГЭСН-блокнот генерируется из локальной базы норм и даёт карту сборников; обычный prompt получает
  `dataset_brief_for_model_v1` вместо полного технического dump typed memory.
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
fragments. Исходные файлы не читаются. `lexical_chunks` — поддерживаемая проекция уже
проиндексированного корпуса: при parse-переиндексации файла `backend/qdrant_adapter.py` удаляет старые
FTS-строки этого файла и записывает новые из тех же Qdrant payloads. Для существующих рантаймов допустим
no-reindex backfill через `tools/build_lexical_index.py` из Qdrant payloads; это ремонт состояния, а не
новый источник evidence.

`quality` — компактная вычисляемая оценка паспорта: документы, чанки, примеры файлов, ключевые слова,
типы/расширения, наличие lexical/deep-сигналов, фрагменты, нормативные ссылки и таблицы. Статусы:
`good`, `partial`, `weak`, `empty`. Это качество навигационного паспорта, не оценка истинности будущего ответа.

`notebook_v1` — тонкая обёртка над паспортом: `notebook_summary` (назначение, типы документов,
предметные области, ключевые термины, нормативные ссылки, ограничения, как искать внутри),
`prompt_excerpt`, `context_role=navigation`, `is_evidence=false`. Для ГЭСН notebook строит
`collections`: идентификатор сборника, область работ, частые термины, единицы и примеры кодов из
локальной базы. Идентификатор учитывает тип базы: обычный строительный `ГЭСН38` и монтажный
`ГЭСНм38` не схлопываются в один раздел, потому что это разные нормативные области.

`dataset_reader_map_v1` — модельный reader-pass поверх typed memory. Он сохраняется в
`dataset_memory.reader_output` со статусом `reader_status=model` и содержит навигационную сводку:
тип корпуса, какие файлы открывать под разные вопросы, роли ключевых файлов, пробелы и рекомендации
ответчику. Это не evidence и не готовый ответ; broad RAG использует его, чтобы выбрать файлы/разделы,
после чего всё равно делает обычный retrieval по источникам.

`dataset_brief_for_model_v1` — компактная упаковка для prompt. Он собирается из `dataset_memory`,
`file_cards`, `important_files`, `known_gaps`, `source_layers`, `retrieval_routes`,
`dataset_source_graph_v1` и, если есть, `reader_output`. Связь с чанками явная:
`file_name` в brief совпадает с `doc_name/file_name` в Qdrant payload и `lexical_chunks`, а точечный
добор идёт через `doc_filter` по этому имени. Поэтому brief может подсказать, какой файл открыть, но
утверждение в видимом ответе должно опираться уже на retrieved chunk/table row/graph atom/calculation trace.

`source_layers` — детерминированное описание слоёв корпуса: `text`, `tables`, `calculations`,
`technical_docs`, `drawings`, `graphics`, `cad_bim`, `normative`, `estimate`. Для каждого слоя хранится
роль, типичные вопросы и правило проверки evidence. Например `tables` говорит модели искать ВОР,
спецификации, суммы и количества, но числа всё равно брать из строк таблицы и считать кодом.
Для сметных нормативных архивов признаки `SMETA_RU_NORM`, `FSNB`, `ГЭСН/ФЕР/ФСЭМ/ФСБЦ/ФГИС` дают слой
`normative` и роли конкретных баз (`ГЭСН`, `ГЭСНм`, `ГЭСНп`, `ФЕР`, `ФСЭМ`, `ФСБЦ материалы`,
`ФСБЦ оборудование`, `сплит-форма/ФГИС`). Обычные проектные ЛСР/ВОР из `TABLE_SMETA` остаются
`estimate/calculations`; код не превращает любую смету в нормативный корпус.

`retrieval_routes` — карта “тип вопроса → какие слои/роли/файлы открыть первыми”. Она не выбирает ответ:
для project overview предпочитает состав проекта/ПЗ/задание; для сметы — tables/calculations/estimate;
для табличного вопроса — tables/calculations; для CAD/BIM — cad_bim/drawings/graphics. Нормативный маршрут
включается только если в датасете есть слой `normative`, чтобы обычный проектный текст не выдавался за
СП/ГОСТ.

`dataset_source_graph_v1` — компактный навигационный граф `dataset -> layer -> role -> top files`.
Он нужен для ориентации модели и UI, не для доказательства фактов. В prompt наружу уходит человеческая
связка “слой -> файлы”, а не служебный JSON-граф.

`operator_guidance` — комментарий оператора для модели. Примеры: “это рабочая ПД, актуальные данные брать
из ПЗ и ВОР”, “старые КП использовать только как ориентир”, “сначала читать том ИОС 5.2”. Поле хранится
в `les_dataset_profiles.profile_json`, sidecar `_les_dataset_profile.json` и, при наличии cached typed
memory, дублируется в `dataset_memory.memory_json`. Это не evidence: модель может использовать подсказку
для навигации, но фактические утверждения всё равно подтверждаются retrieved chunks/table rows/graph atoms
или расчётной трассой.

Служебные файлы индекса (`.pdf_preprocess_state.json`, `manifest`, `dataset_card`, `group_classifier`) не
удаляются из карты, но получают soft-downrank в `important_files`, `retrieval_routes`,
`dataset_source_graph_v1.top_files_by_layer` и notebook `priority_files`. Если полезных файлов нет, они
остаются fallback; если есть реальные нормы/ПЗ/ВОР, модель сначала видит их.

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
9. `run_dataset_reader_pass()` может обогатить typed memory модельной навигацией. В broad study-ответах
   `/api/chat` best-effort запускает этот проход перед `notebook_study`; если не успевает, ставит фон.
10. `dataset_memory_prompt_excerpt()` строит `dataset_brief_for_model_v1` с учётом текущего вопроса:
    для сметы, нормоконтроля, широкого обзора и табличного запроса меняется только маршрут чтения,
    а не факты.
11. Brief добавляет `source_layers`, `retrieval_routes` и связку `слой -> файлы`, чтобы модель сначала
    выбрала правильный слой/документ, а уже потом делала retrieval по источнику.
12. Если у профиля датасета есть `operator_guidance`, brief и обычный context-memory block добавляют его
    как комментарий оператора для модели. Это влияет на чтение корпуса, но не повышает статус факта.
13. `build_dataset_notebook()` и `service_source_notebooks()` дают общий notebook-контекст для режимов.
14. `estimate_harness` получает `LES_SYSTEM_PROMPT + smeta prompt + ГЭСН notebook excerpt + tool contract`.

## Границы

- Паспорт не доказывает ответ. Любая норма, цена, объём и расчёт должны идти из retrieved context,
  structured data или расчётного сервиса.
- `dataset_brief_for_model_v1` не выбирает вывод за модель и не является контрактом ответа. Он помогает
  выбрать файлы/слои, но модель и режимный prompt остаются выше.
- Notebook не является отдельным механизмом под режим: это общий навигационный слой. Режимы только выбирают,
  какой excerpt добавить к своему prompt.
- Паспорт чата не является долговременной памятью оператора. Команды `запомни:` остаются в
  `memory_service.py`.
- Паспорт датасета не запускает переиндексацию и не читает тяжёлые файлы.
- Deep-паспорт зависит от наличия `lexical_chunks`; если lexical index не готов, профиль честно пишет
  `available=false`. Если Qdrant points есть, а lexical пустой, сначала строится FTS-проекция из Qdrant
  payloads без OCR/reindex, затем обычная индексация поддерживает её сама.
- Benchmark меряет только паспортный слой (`les_dataset_profiles` + sidecar + lexical sample). Он не является
  полноценным RAG quality benchmark и не гарантирует ускорение генерации модели.
- Ошибка записи профиля не ломает чат: слой best-effort, пишет warning.

## Тесты

- `tests/test_context_memory_service.py` — sidecar датасета, deep-профиль из bounded lexical index,
  quality-сигналы, warmup/benchmark/notebook, ГЭСН-блокнот, обновление chat-profile через
  `save_chat_history`, prompt-block с явной маркировкой `НЕ evidence`, `operator_guidance` как
  navigation-not-evidence.
- `tests/test_dataset_memory_service.py` — typed memory, file cards, source layers, retrieval routes,
  `dataset_source_graph_v1`, compact brief для модели, normative route только при наличии normative-слоя,
  `operator_guidance` в model brief, `SMETA_RU_NORM` как normative source, роли ГЭСН/ФСЭМ/ФСБЦ,
  soft-downrank служебных files, обратная совместимость старой memory без новых полей.
- `tests/test_notebook_api.py` — публичные notebook endpoints и endpoint сохранения `profile/guidance`.
- `tests/test_static_assets.py` — вкладка «Документы», карта датасета и поле пояснения для модели.
