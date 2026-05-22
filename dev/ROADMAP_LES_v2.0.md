# Roadmap развития системы Л.Е.С. v1.5 → v2.0

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
- **Метаданные и хранение:** SQLite (`les_meta.db`) вместо MySQL. UUID-датасеты в `storage/datasets/`. Исходники в `RAG_Content/`. Persistence через Docker volumes.
- **Т.О.С.К.А. v2.0:** Нативный CRAG-пайплайн в прокси. Pre-Check → Retrieval → Generation → Post-Check. Прозрачная валидация без чёрных ящиков.
- **Мониторинг и UI:** SSE-стрим, Chart.js графики, real-time метрики (CPU/RAM/latency/CRAG/очередь/скорость), фильтры логов.
- **Управление датасетами:** Вкладка UI с маппингом `Источник → Индекс`, кнопка `🔄 Загрузить в индекс`, автообновление статусов, `/api/rag/sources`, `/api/rag/sync/{folder}`.
- **Устойчивость:** `asyncio.Semaphore(2)` для индексации, защита Ollama от concurrency storm, строгая Pydantic-валидация чата.
- **Ресурсная эффективность:** 2 контейнера, RAM ~14–16 ГБ, стабильная работа на Mac M4 / 24 GB без свопа.

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
- **Семантическое кэширование:** базовый слой внедрён для `VERIFIED` ответов с dataset-scope invalidation по snapshot датасетов.
- **Динамическая выгрузка эмбеддера:** агрессивный TTL для `bge-m3` после retrieval, чтобы освобождать память под основную LLM во время генерации.
- **Параллельная валидация:** асинхронная проверка streaming-чанков вместо ожидания полного ответа перед запуском валидатора.
- **Аппаратный тюнинг MLX:** бенчмарки Flash Attention на длинном контексте и смешанного квантования 14B модели.
- **Parquet для таблиц:** базовый XLSX/XLS/CSV ingestion внедрён: row-level chunks для Qdrant + `.parquet` artifacts рядом с датасетом. Для PDF добавлен экспериментальный PyMuPDF-first слой с pdfplumber fallback и `needs_ocr` marker. Следующий шаг — table-aware retrieval и расширение схем смет/спецификаций.
- **Document Router:** добавлен быстрый deterministic probe/classify/complexity слой перед ingestion, чтобы выбирать `markdown`, `parquet`, `markdown_pdf_tables` или `markdown_needs_ocr` и писать rich metadata в Qdrant payload.

📅 **Документ актуализирован:** 22.05.2026 — split UI + premium chat/artifacts + cache/router/parquet stabilization


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
