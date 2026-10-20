# ALGO-context-memory — память чата и паспорт датасета

## Кандидат975 — текущая READ-фаза и durable proof

`PHASE_INSTRUCTION` — один required непустой литерал read-задачи, не evidence/финализация.
Без native reasoning он следует после данных, иначе перед неизменённой текущей
assistant/tool цепочкой. Совмещение с `TERMINAL_REQUEST` отклоняется, None сохраняет wire.
Phase/frame/exchanges проходят общие exact/cloud/conservative guards;
`replay.required` с shared catalogs сохраняется. Переполнение видно до model call.

Pending checkpoint хранит public answer, literal evidence/IDs, scope и preset.
Новый человеческий resume продолжает proof без query/answer и прежней private native
цепочки; scope/preset mismatch останавливается технически. Только actual call/receipt
и delivered body доказывают чтение, не checkpoint/requested choice.
Candidate975 ещё не установлен и не подтверждён профессиональной live-приёмкой.

<!-- candidate939-proof-kind-sampling:v1 -->
## 939: необязательные sampling controls

ChatOptions хранит nullable top_p (0<value<=1), top_k (integer>0 либо-1) и
presence_penalty (-2..2). None не входит в snapshot/wire; legacy{} не меняется.
Явный0 сохраняется. Общий sampling_parameters применяется к OpenAI-compatible
body, native Ollama options и capability probes. FreeToken count_tokens не
получает generation-only параметры, но exact provider-wire SHA их учитывает.
Provider400 остаётся видимой ошибкой; retry не удаляет пользовательский sampler.
Ни UI echo, ни MockTransport не доказывают эффективные параметры backend.

Официальная рекомендация [Qwen3.6](https://huggingface.co/Qwen/Qwen3.6-35B-A3B#best-practices)
для non-thinking: temperature0.7, top_p0.8, top_k20, presence_penalty1.5.
Это основание отдельного конечного опыта, не скрытый default продукта.
Сравнение сохраняет один commit/model/profile/question/source/scope и все
отрицательные результаты; три изменённых параметра и случайность не позволяют
объявить причинный вывод по одному удачному файлу.

## Кандидат 0.31.185 / 913 — явный контекст в пределах наблюдаемой ёмкости

Явный положительный запрос контекста подключения ограничивается наблюдаемой ёмкостью backend, затем ограничениями workflow. Фабричный предел 32768 без явного запроса сохранён; неизвестная ёмкость, tools, batching, reasoning и output guards не меняются. Настройка и effective value остаются публичными. Модель, профиль, запросы, порядок RRF и предметные решения не изменяются.

requested_context_tokens отображается через operator input_tokens/input_token_limit в resolve_execution_preset. Positive observed capacity остаётся жёстким пределом явного запроса; profile restrictions продолжают только сужать. Метаданные модели не являются измерением GPU памяти.

Frozen913 offline canonical gates PASS: 4076 passed, 20 skipped, 5 warnings in 259.17s (0:04:19); mail: 66 passed, 4 warnings in 6.36s; metadata: 31 passed in 4.38s.

## 887: бюджетирование provider reasoning

NativeToolExchange содержит optional reasoning_content как точную строку протокола.
as_messages передаёт его в assistant field, render считает его вместе с calls/replies.
Весь exchange остаётся обязательным и неделимым; reasoning не превращается в
evidence/content и не обрезается для обхода capacity или cloud budget. Public trace
показывает только размер и IDs tool-exchange, без тела. Persisted receipts не содержат
reasoning, новый ход не синтезирует старую CoT. Активный runner использует complete.

## Кандидат882: ограничение полного wire-body при облачном бюджете

`ContextGovernor.pack(admit_messages=...)` дополнительно проверяет целые messages
через чистый preflight транспорта. Он использует тот же OpenAI-compatible body и
тот же резерв, что реальная отправка, без HTTP и списания резерва. Обязательные
profile/request, реестр доказательств, exact reads и native exchanges не режутся.
Optional discovery groups входят целиком или получают omission
`wire_budget_exhausted`, сохраняя IDs/cursor и доступность через readers.
Если не помещается обязательный набор, `ContextRequiredWireOverflow` преобразуется
в технический CloudBudgetStop; бюджет не увеличивается и fallback не запускается.
Проверка включена для remote-budget sheet-answer/replay и B0/B1 native continuation;
для local/unlimited путь прежний. Итоговая транспортная проверка остаётся последней
границей перед каждым HTTP. Это ограничение расхода, не оценка применимости норм.

## Model-owned evidence-first context (0.30.1 / build 635)

Обычный чат использует фактическую наблюдаемую или явно заданную ёмкость
подключённой модели. Фабричные значения 9B/35B являются только fallback, а не
скрытым потолком. Generation и safety reserves вычитаются ровно один раз.

После обязательных profile/request Governor упаковывает evidence и source map
раньше tool exchange, checkpoint, working memory и dialogue. Память и notebook
остаются advisory/navigation и при дефиците окна не вытесняют документы.
Каждый selector и финальный model call получает собственный packet trace с
точным текстом и SHA-256 блоков `EVIDENCE`/`SOURCE_MAP`, а также устойчивыми
ID/cursor не вошедших объектов. Это операторская проверка того, что реально
видела модель; trace не оценивает и не переписывает её ответ.

## Durable workflow checkpoints (0.29.0 / build 618)

`workflow_checkpoint_service` хранит только bounded рабочее состояние: identity
сессии, инструмента, server-owned attachment и его SHA-256, canonical hash
аргументов, model-decision revision, последний progress, missing/blockers и
готовую artifact revision. Повтор с тем же idempotency key возобновляет ту же
запись; смена вложения, hash, аргументов или решения fail-closed конфликтует.
Prompt dumps не сохраняются. `dataset_ids=None` и `[]` имеют одну identity.

## Назначение

Дать ЛЕС “взрослую” рабочую память без подмены evidence: текущий чат получает компактный паспорт
диалога, а каждый выбранный датасет — детерминированный паспорт корпуса. С 0.24.0.29 над паспортами
появился общий `notebook_v1`: компактная карта содержания/поиска для датасетов и служебных источников
(первый системный блокнот — ГЭСН). С 0.24.0.4 паспорт может быть
`metadata` или `deep`: глубокий слой читает только уже готовый lexical index, без reindex/OCR/LLM. С 0.24.0.17
паспорт получает `quality`-оценку полезности и замер прогрева: cold rebuild против тёплого чтения кэша.
Паспорта и блокноты ускоряют маршрутизацию и понимание задачи, но не являются источником фактов, норм или чисел.

## Единый ContextGovernor

В кандидате877 sheet-pass query generation сохраняет исходную карту выбранных
источников до обработки пакетов и добавляет ссылки только из решений текущего
пакета (`model_rag_prior_page_context`). Изменяемая карта показа предыдущего
answer-пакета в новый query prompt не переносится. Это исправляет утечку контекста
между пакетами, не меняя запросов/решений модели, raw evidence, durable cache,
answer-контекста и упаковки. Regression проходит через настоящий chat-service,
две группы строк, native reads и XLSX: новая query-карта пуста при отсутствии
исходной карты/прежних решений этого пакета, все четыре решения и их bindings
сохранены, сумма fixture прежняя. Focused88/canonical3175 passed;
installed live877 pending.

Основание — сохранённый installed876 B1 trace:331489 из539864 оценённых входных
токенов относились к повторным query SOURCE_MAP (61,4%). Это оценки Governor,
не биллинг провайдера и не уже измеренная экономия кандидата877.

Канонический кандидат больше не обрезает prompt независимыми строковыми лимитами.
Все производители отдают типизированные объекты из `ContextKind`: profile prefix,
tool shortlist, request, evidence/current read frame, source map, tool exchange,
checkpoint, working memory, dialogue, phase instruction и terminal request.
`ContextGovernor` сначала резервирует generation и
safety budget, затем сохраняет обязательные объекты и упаковывает остальные в
этом фиксированном порядке.

Объект либо входит целиком, либо получает omission с устойчивым ID/cursor.
Переполнение обязательного request/profile/checkpoint возвращает
`CONTEXT_REQUIRED_SECTION_OVERFLOW` до вызова модели. Старый
`fit_prompt_sections()` оставлен как переходный адаптер над тем же governor и
больше не режет произвольную строку или JSON посередине.

## Typed advisory projection

`typed_memory_projection_service.py` читает существующие паспорта чата,
адресуемые ходы сессии, заметки оператора, MemoryPort и сохранённые trace refs.
SQLite-источники открываются `mode=ro`: projection не создаёт схемы, не пишет
профили и не пересобирает notebook. Он также не копирует prompt dump. Результат состоит из
`checkpoint`, `blocker`, `decision`, `evidence_locator`, `continuity` и
`advisory_fact`; каждый item имеет стабильный ID, project scope,
`context_role=advisory_state` и неизменное `is_evidence=false`.

Решение модели хранится как payload со ссылкой `revision_ref`, а не
переписывается в новый «факт». Dataset/notebook остаётся живой навигацией и
проецируется как locator. Полные объекты остаются в исходных хранилищах;
лимит projection возвращает omitted count/cursor. Старые `session_memory()` и
`build_context_memory_block()` сериализуют bounded typed views для сохранения
пользовательской непрерывности на время миграции.

## Обычный чат

Кандидат 876 добавляет к immutable revision подключения `chat_options`:
выбор `max_tokens | max_completion_tokens`, передачу температуры из профиля либо
её явное отсутствие, протокол рассуждения и положительный `requested_output_tokens`.
Миграция добавляет только JSON-колонку с `{}`; прежние revisions, bindings и capability
snapshots сохраняются. Пустые options наследуют прежнее поле output из snapshot.
Create/copy/edit проходят существующий API и CAS, назначения ролей не меняются.

Один `ChatOptions.parameters()` формирует параметры capability probe и inference.
Оператор явно выбирает `unconfigured | effort | enabled | enable_thinking`:
в первом режиме remote не получает control и фактический reasoning неизвестен;
`effort` передаёт `reasoning_effort=none` для false и заявленное `enabled_effort` для true;
`enabled` передаёт nested `reasoning.enabled`, `enable_thinking` — top-level boolean.
Значение boolean берётся из выбранного профиля; имя модели/провайдера не выбирает протокол.
Прежние FreeToken `chat_template_kwargs.enable_thinking` и Ollama-native `think`
сохраняются. Probe не требует `tool_choice`; отклонённый параметр остаётся видимым
HTTP 400/UNKNOWN и не вызывает скрытый повтор с другими options.

Запрошенные context/output — декларация оператора, не наблюдаемая ёмкость backend.
Для remote с обоими положительными пределами профиль может задать больший purpose
reserve внутри этих границ; output-only способен только сузить прежний default.
Наблюдаемое локальное окно и workflow restrictions остаются жёсткими верхними пределами,
generation/safety reserves вычитаются один раз. GUI и trace разделяют requested,
effective, source, наблюдаемое окно и restart=false; базовый резерв подключения
не подписывается как лимит фактического вызова после применения профиля.

Граница совместимости: транспорт не сохраняет и не возвращает историческое
`reasoning_content`. Поэтому многоходовое thinking=true у provider, требующего его
повторной передачи, ещё не подтверждено (например, [Alibaba preserved thinking](https://www.alibabacloud.com/help/en/model-studio/qwen-api-via-openai-chat-completions)).
Явный профиль false с режимом `enable_thinking` передаёт false, а не полагается на
provider default. Offline wire/migration/CAS/GUI/capacity suite: 465 passed;
architecture guard: exit 0. Облачная live-приёмка и профессиональная готовность
этими проверками не доказаны. Точки входа — `model_connection_contracts`,
`model_connection_registry_service`, `model_connection_resolver_service`,
`model_capability_service`, `openai_compatible_transport_service`,
`llm_transport_profile_service`, `model_execution_preset_service`,
`routers/model_connections`, `sovushka/pages/model_connections`;
регрессии — `test_model_connection_chat_options{,_registry}.py`.

После окончательного выбора provider чат один раз разрешает execution preset.
Тот же preset ограничивает shortlist/batch и оба фактических обращения модели:
`tool_decision`, затем `answer`. Для каждого обращения строится отдельный
`ContextPacket`, но порядок и правила объектов едины. Profile prefix и текущий
request обязательны; checkpoint/working memory, evidence, source map, tool
exchange и dialogue входят только целиком. Поэтому прежняя финальная сборка по
независимому числу символов и отдельное обрезание dataset navigation удалены.

Notebook и паспорта памяти не заменены и не пересобираются: typed projection
читает их как advisory/navigation и передаёт governor адресуемые элементы.
Фактами ответа остаются только evidence/source rows. В `shadow` selector-выдача
повторно используется для проверки максимум одного canonical call; нового
model call и записи эффектов нет, пользователь получает прежний legacy answer.
Trace содержит route, preset, reserves, token/item counts и omission cursors.
Для доказательного слоя он дополнительно хранит точные model-visible
`EVIDENCE`/`SOURCE_MAP` и их SHA-256; profile, память и полный prompt остаются
редактированными, ответ модели не модифицируется.
Если облачный provider падает и маршрут деградирует на локальный MLX, preset
разрешается заново, packet перепаковывается до локального вызова, а все
последующие retry сохраняют уже локальный budget. Selector и fallback required
overflow не проглатываются: чат возвращает typed 422 до следующего model call.
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
С 0.24.0.210 typed memory добавляет `dataset_topic_map_v1` и `dataset_section_map_v1`: модель получает
аналог source guide/оглавления уровня датасета. Topic map связывает инженерные темы с файлами, разделами
и поисковыми синонимами; section map берёт bounded-сигналы `section_heading/parent_heading` из
`lexical_chunks`, если они есть. Это верхняя навигация над чанками: тема ведёт к документу/разделу,
а фактическое утверждение всё равно требует обычного retrieval по источнику.
С 0.24.0.211 обычный RAG при выбранном датасете делает topic-guided retrieval pass: вопрос выбирает
тему из `dataset_topic_map_v1`, её файлы/разделы идут в `doc_filter`, затем выполняется широкий fallback.
Focus учитывает lexical `_rank_score` и поднимает лучший широкий fallback-документ вне выбранных картой
файлов в видимое контекстное окно, чтобы тема не превращалась в закрытый фильтр. Trace пишет выбранную
тему, файлы, разделы, targeted/fallback counts, promoted fallback и not-found files.
С 0.24.0.212 вкладка «Документы» показывает темы и разделы карты человеку, а кнопка “Спросить по теме”
открывает чат с `scope=ds:<dataset_id>` и предзаполненным вопросом. Trace summary в чате кратко
показывает выбранную тему, targeted/fallback counts и promoted fallback-документ.

## Точки входа

- `proxy/services/context_governor_service.py` — типы кандидатов, единый packer,
  omission cursor и typed required-overflow.
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
Для внутренних таблиц Smeta.RU/FSNB (`A_SRF_F`, `A_SRF_TR`, `A_SRF_VR`, `B_NORMTYPE`,
`LEVEL_COST` и т.п.) memory добавляет человеческие роли: таблица норм/расценок, таблица
ресурсов нормы, иерархия разделов, тип нормативной базы, ценовой уровень. Это навигация
для модели по корпусу, не автоматический выбор нормы и не расчёт.
File cards дополнительно несут `navigation_terms`: короткие поисковые синонимы для модели
и target retrieval. Например `A_SRF_F` получает “нормы/расценки/шифр нормы”, `A_SRF_TR` —
“ресурсы нормы/машины/материалы”, pricebook — “ФГИС ЦС/цены ресурсов/регион/квартал”.
Это не evidence и не расширение фактов; это оглавление, по каким словам открывать нужный файл.

`dataset_topic_map_v1` — карта предметных тем датасета: “паспорт объекта”, “пожарная сигнализация и
противопожарная автоматика”, “слаботочные системы”, “ОВ/противодымная вентиляция”, “электроснабжение”,
“ВОР/сметы” и т.п. Каждая тема хранит aliases, первые файлы, видимые headings и confidence. Карта не
говорит, что решение подтверждено; она говорит модели, где искать. Поэтому запрос вида “сводка по
пожарной автоматике” должен сначала попасть в тему и её файлы/разделы, а не в случайный общий чанк.

`dataset_section_map_v1` — компактное оглавление из `lexical_chunks.section_heading/parent_heading`.
Оно не читает исходные PDF/DOCX заново и не запускает OCR/reindex. Если headings отсутствуют, карта честно
остаётся пустой, а модель опирается на file cards/reader-pass. Если headings есть, brief показывает
документ → разделы, чтобы второй проход retrieval мог открывать конкретный файл через `doc_filter`.

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
12. Brief добавляет `topic_map` и `section_map`: модель видит тему, первые документы и внутренние заголовки
    как оглавление корпуса. Это помогает сделать NBLM-подобный source guide без подмены ответа кодом.
13. Перед обычным широким retrieval чат выбирает topic source guide: `dataset_topic_selection_v1`
    берёт matching topic, `top_files/top_sections`, запускает targeted `doc_filter` retrieval, а затем
    добавляет широкий fallback. Это всё ещё навигация: выводы берутся только из retrieved chunks.
14. Если у профиля датасета есть `operator_guidance`, brief и обычный context-memory block добавляют его
    как комментарий оператора для модели. Это влияет на чтение корпуса, но не повышает статус факта.
15. `build_dataset_notebook()` и `service_source_notebooks()` дают общий notebook-контекст для режимов.
16. `estimate_harness` получает `LES_SYSTEM_PROMPT + smeta prompt + ГЭСН notebook excerpt + tool contract`.

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
  `dataset_source_graph_v1`, `dataset_topic_map_v1`, `dataset_section_map_v1`, compact brief для модели,
  `dataset_topic_selection_v1`, normative route только при наличии normative-слоя, `operator_guidance` в model brief,
  `SMETA_RU_NORM` как normative source, роли ГЭСН/ФСЭМ/ФСБЦ, soft-downrank служебных files,
  обратная совместимость старой memory без новых полей.
- `tests/test_notebook_api.py` — публичные notebook endpoints и endpoint сохранения `profile/guidance`.
- `tests/test_static_assets.py` — вкладка «Документы», карта датасета и поле пояснения для модели.
