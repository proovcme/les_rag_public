# Roadmap развития системы Л.Е.С. v1.5 → v2.0

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
- **Метаданные и хранение:** SQLite (`les_meta.db`) вместо MySQL. UUID-датасеты в `storage/datasets/`. Исходники в `RAG_Content/`.
- **Т.О.С.К.А. v2.0:** Нативный CRAG-пайплайн в прокси. Pre-Check → Retrieval → Generation → Post-Check. Прозрачная валидация без чёрных ящиков.
- **Ресурсная эффективность:** 2 контейнера, RAM ~14–16 ГБ, стабильная работа на Mac M4 / 24 GB без свопа.

## 🛠 Запланировано в v2.1 (Краткосрочно)
- **Дашборды и метрики:** Chart.js в С.О.В.У.Ш.К.Е, real-time графики latency/CRAG/RAM, фильтры логов, экспорт PNG/CSV.
- **Устойчивость:** Retry-логика в прокси, graceful fallback при занятости Ollama, очереди задач для тяжёлой индексации.
- **RBAC v2.0:** Полноценная JWT-аутентификация, маскирование `.env`, ролевые бейджи в UI.
- **С.У.Х.А.Р.И.К. v2.0:** Снапшоты Qdrant, инкрементальные бэкапы `storage/datasets/`, ротация по дням.

## 🔮 Среднесрочная перспектива (v2.2+)
- **Deep BIM Linking:** Семантическая связь ответов LLM с ExpressID в IFC.
- **Сравнение версий нормативов:** Дифф СП/ГОСТ ("что изменилось в 2024 vs 2020").
- **Multi-project Support:** Изоляция проектов, датасетов и ролей.
- **Plugin Architecture:** Импорт из Revit, Tekla, NanoCAD через внешние плагины.
- **Voice Control:** Whisper для голосового ввода на стройплощадке.
- **Mobile Dashboard:** Адаптивная версия UI для планшетов.

📅 **Документ актуализирован:** 10.05.2026 — статус после релиза v2.0 Core
