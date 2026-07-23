# Roadmap развития системы Л.Е.С. v1.5 → v2.0

## ✅ Выполнено в v4.0 Hybrid Structural-Semantic (31.05.2026)
- **Microsoft MarkItDown**: Интегрирован универсальный офисный парсер для презентаций (`.pptx`), Word-документов (`.docx`, `.doc`), таблиц (`.xlsx`, `.xls`) и XML-схем с автоматическим mammoth/pandas fallbacks.
- **MLX GLM-OCR (Visual RAG)**: Нативный визуальный OCR на базе мультимодальной VLM-модели `mlx-community/GLM-OCR-4bit` для отсканированных или пустых PDF. Интегрирован механизм агрессивной очистки Metal GPU памяти (`mlx.core.metal.clear_cache()`) и сборщика мусора Python после каждого пакета страниц.
- **Google LangExtract**: Построен механизм извлечения строгих требований по Pydantic-схеме `EngineeringRule` (субъект, параметр, оператор, численное значение, единица измерения, дополнительные условия) с привязкой к точным символьным координатам в тексте чанка.
- **SQLite Таблица `structured_rules`**: Интегрировано реляционное хранилище извлеченных требований в SQLite метабазу с индексами по документам и файлам. На 01.06.2026 это schema/code-ready состояние; активная база ещё не наполнена правилами (`0` rows) до targeted reindex нормативных документов.
- **Изолированные тесты**: Написаны верификационные тесты в песочнице `scratch/` для MarkItDown, LangExtract и GLM-OCR.
- **Завершение кампаний переиндексации (Факт)**:
  * **`NTD_FIRE_Index`**: Успешно переиндексировано **135 файлов из 135** (31 481 чанк в Qdrant). Последний errored-файл `СП 2.13130 .docx` полностью исцелен и доиндексирован (303 чанка).
  * **`BOOKS_Index`**: Успешно переиндексирован тяжелый 596-страничный справочник Schneider Electric (40 МБ, 3 222 векторных чанка) за 7.7 минут.
  * **Neural Engine (ANE) & GPU Routing**: Обход бага зануления внимания M-чипов при FP16 вычислениях на CPU (за счет переключения compute units на `all`).

## 🟢 Live baseline 01.06.2026 — local consistency closed
- **Корпус:** authoritative live corpus расширен до `1211` файлов.
- **Индекс:** `1211 indexed / 0 pending / 0 errors`, `142193` SQLite chunks.
- **Qdrant:** `142193` points, `points_match_sqlite_chunks=true`; stale Qdrant points удалены после backup/snapshot.
- **Validator:** live default `rules`; Core ML MiniLM package сохранён для measured compare/probe.
- **Embeddings:** Core ML Qwen3 Embedding `0.6B`, `compute_units=all`, ANE/GPU eligible.
- **Quality gate:** FIRE/HVAC retrieval acceptance `golden/domain_fire_hvac_set.json` проходит `16/16`.
- **Regression gate:** full `uv run pytest -q` проходит `357 passed` (2 SWIG deprecation warnings).


## ✅ Выполнено в v3.3 Stabilization / Premium Chat (22.05.2026)
- **Split UI:** `https://les.ovc.me/` теперь лёгкий чатовый контур; `https://les.ovc.me/les` — отдельная админка. Чат больше не зависит от монтирования админских страниц.
- **Premium С.О.В.У.Ш.К.А.:** нижний composer, кнопка `Расширенный запрос`, модальное окно параметров, левая выезжающая история чатов, правая панель `Артефакты` в стиле Claude.
- **Долгие RAG-запросы:** `reconnect_timeout=180` и `chat_pending` уменьшают видимость срывов при реконнекте.
- **Restart hardening:** `restart_sovushka.command` запускает UI через `.venv/bin/python3` и пишет реальный PID слушателя.
- **Semantic cache:** внедрён кэш только для `VERIFIED` ответов с dataset-scope invalidation.
- **Document Router:** быстрый deterministic probe/classify/complexity слой перед ingestion.
- **Parquet/XLSX/CSV:** row-level chunks для Qdrant и `.parquet` artifacts рядом с датасетом.
- **Qdrant visualizer:** добавлен локальный визуализатор как отдельный tool/workbench.

## ✅ Выполнено в v1.5.0 (08.05.2026)
- К.О.Т. v1.1: Интеграция с Speckle GraphQL API.
- С.У.Х.А.Р.И.К. v1.0: Бэкапы MySQL/ES в MinIO.
- В.О.Л.К. RBAC: 4 роли, JWT-сессии.
- Е.Ж.И.К. OCR v2.1: Tesseract для вложений.
- Унификация `RAGFLOW_API_URL`.

## 🚀 Выполнено в v2.0 Core (10.05.2026)
- **Архитектурный рефакторинг:** Полный отказ от RAGFlow, Elasticsearch, MySQL, MinIO, Redis, Celery. Переход на FastAPI + Qdrant + LlamaIndex.
- **Модельный стек:** `qwen3:14b` (RAG/чат), `qwen2.5-coder:14b` (код), `bge-m3:latest` (эмбеддинги). Ollama-оркестрация с лимитами RAM.
- **ConverterRouter:** Lightweight-парсинг без нейросетей. `pymupdf4llm` (PDF/каталоги), `mammoth` (DOCX), `extract-msg` (EML/MSG), `pandas` (XLSX/CSV).
- **Structure-Aware Chunking:** Нарезка по заголовкам и структуре документов (MarkdownNodeParser + SentenceSplitter). Сохранение контекста ГОСТ/СП.
- **Метаданные и хранение:** SQLite (`les_meta.db`) вместо MySQL. UUID-датасеты в `storage/datasets/`. Исходники в `RAG_Content/`. Qdrant persistence в `data/qdrant/` без Docker volumes.
- **Т.О.С.К.А. v2.0:** Нативный CRAG-пайплайн в прокси. Pre-Check → Retrieval → Generation → Post-Check. Прозрачная валидация без чёрных ящиков.
- **Мониторинг и UI:** SSE-стрим, Chart.js графики, real-time метрики (CPU/RAM/latency/CRAG/очередь/скорость), фильтры логов.
- **Управление датасетами:** Вкладка UI с маппингом `Источник → Индекс`, кнопка `🔄 Загрузить в индекс`, автообновление статусов, `/api/rag/sources`, `/api/rag/sync/{folder}`.
- **Устойчивость:** `asyncio.Semaphore(2)` для индексации, защита Ollama от concurrency storm, строгая Pydantic-валидация чата.
- **Ресурсная эффективность:** no-Docker host runtime, Qdrant/proxy/MLX/UI через LaunchAgents, guarded indexing `batch_limit=1`.

## 🛠 Запланировано в v2.1 (Краткосрочно)
- **Retry-логика в прокси:** graceful fallback при занятости MLX/Ollama reserve, автоматические повторы с экспоненциальной задержкой.
- **Folder Watcher:** Автоматическая синхронизация новых файлов из `RAG_Content/` в индексы (аналог v1.5, но под Qdrant).
- **RBAC v2.0:** Полноценная JWT-аутентификация, маскирование `.env`, ролевые бейджи в UI, защита `/api/rag/*` и `/api/system/env`.
- **С.У.Х.А.Р.И.К. v2.0:** Снапшоты Qdrant, инкрементальные бэкапы `storage/datasets/`, ротация по дням, экспорт метрик в PNG/CSV.
- **CRAG Post-Check v2:** Автоматическая проверка цитат, детекция противоречий, оценка "воды", строгий инженерный стиль.

## 🔮 Среднесрочная перспектива (v2.2+)
- **Deep BIM Linking:** Семантическая связь ответов LLM с ExpressID в IFC.
- **Сравнение версий нормативов:** Дифф СП/ГОСТ ("что изменилось в 2024 vs 2020").
- **Multi-project Support:** Изоляция проектов, датасетов и ролей.
- **Plugin Architecture:** Импорт из Revit, Tekla, NanoCAD через внешние плагины.
- **XLS/CSV Export:** выдача готовых табличных файлов из результатов чата и AG Grid.
- **Field Intake:** внешние формы П.А.У.К. для полевой загрузки файлов, фотоотчётов, актов и комментариев в карантинный датасет.
- **Mobile Field Form:** лёгкая мобильная форма для стройплощадки без доступа к админке и сложному чату.
- **Artifact Export:** скачивание готовых JSON/XLSX/CSV/SVG/Mermaid из правой панели артефактов.
- **Proxy/WebSocket диагностика:** если чат всё ещё срывается около 60 секунд, проверять внешний proxy/websocket timeout или рестарт процесса Совушки.

## ⚡ Backlog ускорения и оптимизации
- **GUI visibility для индексации:** в админке нужен детальный список файлов по датасетам с фильтрами по `dataset/status`, показом `last_error`, `chunk_count`, pipeline/route metadata и быстрыми действиями для `ERROR`/`PENDING` (retry, очистка ошибки, просмотр пути). Счётчики датасета должны раскрывать конкретные файлы, чтобы ошибка индексации не оставалась только числом в панели.
- **Семантическое кэширование:** базовый слой внедрён для `VERIFIED` ответов с dataset-scope invalidation по snapshot датасетов.
- **Динамическая выгрузка эмбеддера:** агрессивный TTL для `bge-m3` после retrieval, чтобы освобождать память под основную LLM во время генерации.
- **Параллельная валидация:** асинхронная проверка streaming-чанков вместо ожидания полного ответа перед запуском валидатора.
- **Аппаратный тюнинг MLX:** бенчмарки Flash Attention на длинном контексте и смешанного квантования 14B модели.
- **Embed pipeline tuning:** после завершения qwen-индексации отдельно разобрать `embed_sec` как главный bottleneck. Идеи для проработки: увеличить `RAG_EMBED_BATCH` при стабильной RAM/MPS, проверить adaptive chunking для тяжёлых СП/ГОСТ, сравнить скорость/качество Qwen embeddings и BGE-M3 на golden set, ввести режим быстрой первичной индексации и последующей качественной переиндексации.
- **Post-indexing Q&A hardening:** после завершения индексации пройти тракт `/api/chat` без нагрузки на индексатор: корректно показывать `409 indexing mode` в UI, заменить `innerHTML`-рендер ответов/источников на безопасный DOM, протащить фактический inferred `dataset_filter` в ответ API, расширить контекст Т.О.С.К.А. для валидации и держать reranker под общим LLM semaphore.
- **Small-model preprocessing policy:** сейчас малая модель используется как Т.О.С.К.А.-валидатор и опциональный reranker, а препроцессинг вопроса выполняется deterministic router/clarification gate. После индексации решить, стоит ли включать малую модель перед retrieval для query rewrite, intent classification и multi-hop decomposition, с явным memory budget и fallback на rule-based роутинг.
- **К.О.Т. semantic terminology filter:** после индексации оформить текущие hardcoded правила `query_router`/`clarification_service`/`retrieval_service` в отдельный настраиваемый слой К.О.Т.: taxonomy доменов, словарь терминов/синонимов, YAML/SQLite-конфиг с UI-редактором, trace в `/api/chat` (`route_reason`, inferred `dataset_filter`, clarification reasons) и golden-set тесты на инженерные формулировки.
- **RAG modernization plan:** после завершения индексации выполнять по `RAG_MODERNIZATION_PLAN.md`: baseline golden set, batch/chunk benchmark, query instructions, hybrid dense+sparse/RRF, retrieval evaluator, conditional reranker, RAPTOR-lite и GraphRAG-lite только после доказанной пользы.
- **Adaptive chunking + GUI profiles:** вынести в админку профили чанкинга (`default`, `normative`, `table`, `pdf_ocr`, `email`) с настройками `chunk_size`, `chunk_overlap`, min/max chunk size, склейкой коротких пунктов, запретом разрыва нумерованных пунктов и таблиц. Добавить preview chunking по выбранному файлу и явную кнопку reindex affected documents; изменение настроек должно помечать документы как требующие переиндексации, а не смешивать старые и новые чанки молча.
- **Parquet для таблиц:** базовый XLSX/XLS/CSV ingestion внедрён: row-level chunks для Qdrant + `.parquet` artifacts рядом с датасетом. Для PDF добавлен экспериментальный PyMuPDF-first слой с pdfplumber fallback и `needs_ocr` marker. Следующий шаг — table-aware retrieval и расширение схем смет/спецификаций.
- **Document Router:** добавлен быстрый deterministic probe/classify/complexity слой перед ingestion, чтобы выбирать `markdown`, `parquet`, `markdown_pdf_tables` или `markdown_needs_ocr` и писать rich metadata в Qdrant payload.

📅 **Документ актуализирован:** 01.06.2026 — local consistency baseline, Core ML ANE/GPU embedding, rules validator default, structured_rules pre-population state


## 🚀 Выполнено в v2.0 Core (Факт на 10.05.2026)
- Архитектурный рефакторинг: FastAPI + Qdrant + LlamaIndex + Ollama.
- ConverterRouter: pymupdf4llm, mammoth, extract-msg, pandas, потоковый JSON.
- Structure-Aware Chunking: нарезка по заголовкам ГОСТ/СП.
- Метаданные: SQLite, UUID-датасеты, Delta-Sync, рекурсия.
- Т.О.С.К.А. v2.0: нативный CRAG, фильтрация по датасетам в UI.
- Метрики и логи: фоновый коллектор, SSE-стрим, Chart.js, сохранение состояния чипов.
- Стабильность: production Uvicorn, asyncio.to_thread, идемпотентность, volumes.
- Индексировано 807 файлов, 1316 чанков. Система работает без свопа и рестартов.

## 🛠 Запланировано в v2.1 (Краткосрочно)
- Retry-логика в прокси, graceful fallback при занятости Ollama.
- Folder Watcher: автосинхронизация новых/изменённых файлов.
- RBAC v2.0: JWT, роли, маскирование .env, ролевые бейджи.
- С.У.Х.А.Р.И.К. v2.0: снапшоты Qdrant, инкрементальные бэкапы storage/.
