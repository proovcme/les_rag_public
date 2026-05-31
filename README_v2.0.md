# 🦉 Л.Е.С. — Локальная Единая Система v2.0 Core

> **Актуализация 31.05.2026 (Modernization Campaign):** Текущий контур полностью no-Docker. Завершена интеграция гибридного RAG-пайплайна: **Microsoft MarkItDown** (конвертер), **Google LangExtract** (реляционные правила в SQLite `structured_rules`) и **MLX GLM-OCR** (нативный VLM-OCR на GPU). Выполнен полный guarded-реиндекс по конвейеру `markdown_pdf_tables` для пожарного датасета **`NTD_FIRE_Index`** (135 файлов, 31 481 чанков) и тяжелого справочника **`BOOKS_Index`** (40 МБ, 596 страниц, 3 222 чанка) с динамическими RAM-гардами (выгрузка idle-моделей при 6.2 GB RAM). CoreML вычисления переведены на Neural Engine и GPU (`COREML_EMBED_COMPUTE_UNITS=all`), что ускорило векторизацию в 10 раз и исключило баг зануления внимания Apple AMX.


## Описание
Л.Е.С. v2.0 — суверенный инженерный RAG-стек для работы с нормативной документацией (ГОСТ/СП), проектной перепиской, каталогами и BIM-данными. Построен на принципах **Fully Local / Zero-Cloud / Lightweight**.  
В v2.0 полностью исключены тяжёлые зависимости (RAGFlow, Elasticsearch, MySQL, MinIO, Redis, Celery). Ядро переписано на **FastAPI + LlamaIndex + Qdrant**. Конфиденциальные данные никогда не покидают локальный контур.

## 🔑 Ключевые изменения v2.0 → текущий runtime
- **Ядро:** FastAPI Proxy + Qdrant (векторный поиск) + LlamaIndex (оркестрация).
- **Модели:** основной контур переведён на MLX Host (`mlx-community/Qwen3-14B-4bit`, `Qwen3-4B-4bit`, `bge-m3`); Ollama остаётся резервом.
- **Конвертация:** Lightweight ConverterRouter (`pymupdf4llm`, `mammoth`, `extract-msg`, `pandas`). Без Docling/нейросетей на этапе парсинга.
- **Чанкинг:** Structure-Aware (MarkdownNodeParser + SentenceSplitter). Нарезка по заголовкам ГОСТ/СП, а не по токенам.
- **Метаданные:** SQLite (`les_meta.db`) вместо MySQL. UUID-датасеты в `storage/datasets/`.
- **Т.О.С.К.А. (CRAG):** Нативный Python-пайплайн в прокси (Pre-Check → Retrieval → Generation → Post-Check).
- **UI:** С.О.В.У.Ш.К.А. на NiceGUI: `/` — премиальный AI-чат с drawer-историей и правой панелью артефактов, `/les` — админка.
- **Управление датасетами:** UI-вкладка с маппингом `Источник → Индекс`, кнопка `🔄 Загрузить в индекс`, автообновление статусов.
- **Ресурсы:** host LaunchAgents для Qdrant, proxy, MLX и UI. Docker-контейнеры в штатном runtime отсутствуют.
- **Документы и таблицы:** Document Router выбирает маршрут ingestion; XLSX/CSV пишутся row-level chunks и `.parquet` artifacts.
- **Ускорение:** semantic cache кэширует только `VERIFIED` ответы с invalidation по dataset scope.

## 🗺️ Карта архитектуры v2.0
| Модуль | Расшифровка | Роль | Реализация v2.0 |
|---|---|---|---|
| Л.Е.С. | Локальная Единая Система | Оркестратор, API Gateway | `proxy_server.py` (FastAPI) |
| С.А.М.О.В.А.Р. | Система Автономная Машинной Обработки Внутренних Архивов РАГ | Ядро RAG и поиска | Qdrant + LlamaIndex + `bge-m3` |
| Т.О.С.К.А. | Терминал Оценки, Самопроверки и Контроля Архитектуры | CRAG-валидация, фильтр галлюцинаций | Native Python pipeline в прокси |
| В.О.Л.К. | Внутренний Охранный Локальный Контур | RBAC, аутентификация | JWT-токены, SQLite, middleware (в разработке) |
| С.О.В.У.Ш.К.А. | Система Обработки и Выдачи... | Интеллектуальный UI | `sovushka_ng.py` (`/` чат, `/les` админка) |
| С.У.Х.А.Р.И.К. | Система Управления Холодными Архивами... | Бэкапы и архивация | Снапшоты Qdrant + `storage/` (в разработке) |
| П.Р.О.Р.А.Б. | Программа Регулярной Оценки Работы Автономной Базы | Метрики и диагностика | `/api/metrics`, SSE-логи, `psutil` |

## 🚀 Инструкция по запуску
### Предварительные требования
- Локальный Qdrant binary `/Users/ovc/.local/bin/qdrant` (порт 6333)
- MLX Host на хосте (порт 8080) с Qwen3/Qwen embeddings; Ollama опционален как резерв
- Mac M4 / 24 GB RAM (или аналог)

### Быстрый старт
```bash
# 1. Запуск host-runtime через launchd/команды проекта
launchctl kickstart -k gui/$(id -u)/me.ovc.les.qdrant
launchctl kickstart -k gui/$(id -u)/me.ovc.les.proxy
launchctl kickstart -k gui/$(id -u)/me.ovc.les.mlx

# 2. Проверка статуса
curl http://localhost:6333/healthz
curl http://localhost:8050/api/health
```

### Доступ к сервисам
| Сервис | URL | Описание |
|---|---|---|
| С.О.В.У.Ш.К.А. Chat | `http://localhost:8051/` | Основной чат, история, артефакты |
| С.О.В.У.Ш.К.А. Admin | `http://localhost:8051/les` | Метрики, датасеты, диагностика, В.О.Л.К. |
| Qdrant Dashboard | `http://localhost:6333/dashboard` | Управление коллекциями и точками |
| Ollama API | `http://localhost:11434` | Локальный LLM-сервер (на хосте) |

## 📡 Топология портов
| Порт | Сервис | Роль |
|---|---|---|
| 8050 | proxy (Л.Е.С.) | Единая точка входа, API Gateway |
| 8051 | sovushka_ng.py | С.О.В.У.Ш.К.А. UI (NiceGUI) |
| 6333 | qdrant | Векторная база данных (UI + API) |
| 8080 | mlx_host.py | MLX LLM + Embeddings (на Metal) |
| 11434 | ollama (хост) | Резервный LLM контур |

## 📁 Структура проекта v2.0
```
LES_v2/
├── proxy_server.py           # FastAPI ядро, роуты, CRAG, SSE, метрики
├── qdrant_launchd.plist      # Qdrant local binary :6333
├── proxy_launchd.plist       # FastAPI proxy :8050
├── docker-compose.yml        # legacy/archived Docker fallback, не штатный runtime
├── Dockerfile.proxy          # legacy Docker proxy image
├── requirements.txt          # Зависимости (FastAPI, LlamaIndex, Qdrant, pymupdf4llm...)
├── .env                      # Конфиг моделей и путей
│
├── backend/
│   ├── __init__.py
│   ├── interface.py          # Контракт RAGBackend
│   ├── qdrant_adapter.py     # Адаптер Qdrant + LlamaIndex + Structure-Aware Chunking
│   ├── converter.py          # ConverterRouter (PDF/DOCX/EML/XLSX → Markdown)
│   └── metrics_collector.py  # SQLite time-series метрики
│
├── sovushka_ng.py            # Точка входа UI v5.0 (NiceGUI)
├── sovushka/                 # Модульный пакет UI
│   ├── config.py, state.py, styles.py, auth.py
│   ├── components/           # header, logterm, charts
│   └── pages/                # overview, samovar, prorab, chat, mermaid_page, diag, volk
├── storage/
│   └── datasets/             # Физические UUID-папки датасетов
│
├── RAG_Content/              # Исходники для загрузки (NTD, BIM, MAIL)
│
├── data/
│   ├── qdrant/               # Volume Qdrant
│   ├── les_meta.db           # SQLite метаданные датасетов/документов
│   └── les_metrics.db        # SQLite метрики П.Р.О.Р.А.Б.
│
└── tests/
    └── test_proxy.py         # Smoke-тесты API
```

## 🔌 API Endpoints v2.0
### Системные
| Endpoint | Method | Описание |
|---|---|---|
| `/api/health` | GET | Статус системы и бэкенда |
| `/api/logs/stream` | GET | SSE-стрим структурированных логов |
| `/api/metrics` | GET | Агрегированные метрики (CPU/RAM/RAG/CRAG/очередь/скорость) |

### RAG & Datasets
| Endpoint | Method | Описание |
|---|---|---|
| `/api/rag/sources` | GET | Сканирование `RAG_Content/`, маппинг папок на датасеты |
| `/api/rag/sync/{folder}` | POST | Создание датасета, копирование файлов, запуск индексации |
| `/api/rag/datasets` | GET/POST | Список/создание датасетов |
| `/api/rag/upload/{id}` | POST | Загрузка файла → конвертация → индексация |
| `/api/rag/delta` | GET | Дельта-анализ файлов (заглушка) |
| `/api/chat` | POST | Чат с Т.О.С.К.А. валидацией |

## 🛠 Текущее состояние v2.0
### ✅ Работает:
- Полный пайплайн: Файл → ConverterRouter → Structure-Aware Chunking → `bge-m3` → Qdrant → Retrieval → `qwen3` → CRAG → Ответ.
- Поддержка PDF (`pymupdf4llm`), DOCX (`mammoth`), EML/MSG, XLSX/CSV.
- SQLite-метаданные, UUID-датасеты в `storage/datasets/`, Qdrant persistence в `data/qdrant/`.
- SSE-логи, Chart.js графики, real-time метрики, фильтры логов.
- Вкладка **Датасеты**: маппинг `Источник → Индекс`, кнопка `🔄 Загрузить в индекс`, автообновление статусов.
- Concurrency control: `asyncio.Semaphore(2)` для индексации, защита Ollama от перегрузки.
- Healthcheck, строгая Pydantic-валидация чата, обработка ошибок Ollama.

### ⏳ В работе / Бэклог:
- Полная загрузка папки NTD и валидация на тяжёлых ГОСТ/СП/каталогах.
- Retry-логика в прокси для устойчивости к занятости Ollama.
- RBAC v2.0 (JWT), маскирование `.env`, ролевые бейджи.
- С.У.Х.А.Р.И.К. v2.0: снапшоты Qdrant, инкрементальные бэкапы `storage/`.
- Folder Watcher для автоматической синхронизации новых файлов.
- Deep BIM Linking, сравнение версий нормативов, multi-project support.

📅 **Документация актуализирована:** 22.05.2026 — split UI, premium chat/artifacts, semantic cache, document router, Parquet pipeline


## 📊 Фактический статус системы (Аудит 17.05.2026)
✅ Подтверждено работой в production:
- Uvicorn запущен без `--reload`. Hot-reload отключён для стабильности host-runtime.
- Метрики собираются фоновым async-циклом каждые 3 сек. HTTP-запросы не блокируются.
- Delta-Sync (size+mtime) + идемпотентная регистрация в SQLite исключают дубли.
- Рекурсивный обход папок (`rglob`) видит вложенные файлы любой глубины.
- UI держит состояние чекбоксов датасетов при автообновлении.
- Индексировано: 807 файлов, 1316 чанков (NTD, CLAUDE, QWEN). RAM прокси ~1 ГБ.
- Логи чистые: 0 ошибок, 0 циклов рестарта, SSE-стрим стабилен.

### 🤖 Работа с AI-ассистентом (Aider)
Для локальных правок кода и документации интегрирован Aider + Ollama (`qwen2.5-coder:14b`).
- **Путь:** `/Users/ovc/Library/Python/3.9/bin/aider`
- **Запуск:** `cd ~/Projects/LES_v2 && /Users/ovc/Library/Python/3.9/bin/aider --model ollama_chat/qwen2.5-coder:14b --openai-api-base http://localhost:11434/v1 --yes-always <файлы> --message "задача"`
- **Правила:** Указывать ≤3–4 файла. Для кода — EN промпт, для доков — RU. Лимит контекста ~32k токенов. После правок `.py` → `launchctl kickstart -k gui/$(id -u)/me.ovc.les.proxy`.
- **Откаты:** `git status` перед стартом. Откат: `git checkout <commit> -- <file>`.
