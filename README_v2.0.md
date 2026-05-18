# 🦉 Л.Е.С. — Локальная Единая Система v2.0 Core

## Описание
Л.Е.С. v2.0 — суверенный инженерный RAG-стек для работы с нормативной документацией (ГОСТ/СП), проектной перепиской, каталогами и BIM-данными. Построен на принципах **Fully Local / Zero-Cloud / Lightweight**.  
В v2.0 полностью исключены тяжёлые зависимости (RAGFlow, Elasticsearch, MySQL, MinIO, Redis, Celery). Ядро переписано на **FastAPI + LlamaIndex + Qdrant**. Конфиденциальные данные никогда не покидают локальный контур.

## 🔑 Ключевые изменения v2.0
- **Ядро:** FastAPI Proxy + Qdrant (векторный поиск) + LlamaIndex (оркестрация).
- **Модели:** `qwen3:14b` (чат/RAG), `qwen2.5-coder:14b` (код), `bge-m3:latest` (эмбеддинги). Ollama-оркестрация с лимитами RAM.
- **Конвертация:** Lightweight ConverterRouter (`pymupdf4llm`, `mammoth`, `extract-msg`, `pandas`). Без Docling/нейросетей на этапе парсинга.
- **Чанкинг:** Structure-Aware (MarkdownNodeParser + SentenceSplitter). Нарезка по заголовкам ГОСТ/СП, а не по токенам.
- **Метаданные:** SQLite (`les_meta.db`) вместо MySQL. UUID-датасеты в `storage/datasets/`.
- **Т.О.С.К.А. (CRAG):** Нативный Python-пайплайн в прокси (Pre-Check → Retrieval → Generation → Post-Check).
- **Мониторинг:** SSE-стрим + Chart.js в С.О.В.У.Ш.К.Е. Без Grafana/Metabase.
- **Управление датасетами:** UI-вкладка с маппингом `Источник → Индекс`, кнопка `🔄 Загрузить в индекс`, автообновление статусов.
- **Ресурсы:** 2 контейнера (Qdrant + Proxy). RAM ~14–16 ГБ. Запуск на Mac M4 / 24 GB без свопа.

## 🗺️ Карта архитектуры v2.0
| Модуль | Расшифровка | Роль | Реализация v2.0 |
|---|---|---|---|
| Л.Е.С. | Локальная Единая Система | Оркестратор, API Gateway | `proxy_server.py` (FastAPI) |
| С.А.М.О.В.А.Р. | Система Автономная Машинной Обработки Внутренних Архивов РАГ | Ядро RAG и поиска | Qdrant + LlamaIndex + `bge-m3` |
| Т.О.С.К.А. | Терминал Оценки, Самопроверки и Контроля Архитектуры | CRAG-валидация, фильтр галлюцинаций | Native Python pipeline в прокси |
| В.О.Л.К. | Внутренний Охранный Локальный Контур | RBAC, аутентификация | JWT-токены, SQLite, middleware (в разработке) |
| С.О.В.У.Ш.К.А. | Система Обработки и Выдачи... | Интеллектуальный UI | `sovushka_ng.py` (NiceGUI v5.0 модульный) |
| С.У.Х.А.Р.И.К. | Система Управления Холодными Архивами... | Бэкапы и архивация | Снапшоты Qdrant + `storage/` (в разработке) |
| П.Р.О.Р.А.Б. | Программа Регулярной Оценки Работы Автономной Базы | Метрики и диагностика | `/api/metrics`, SSE-логи, `psutil` |

## 🚀 Инструкция по запуску
### Предварительные требования
- Docker Desktop / Docker Engine + Compose
- Ollama на хосте (порт 11434) с моделями: `qwen3:14b`, `qwen2.5-coder:14b`, `bge-m3:latest`
- Mac M4 / 24 GB RAM (или аналог)

### Быстрый старт
```bash
# 1. Запуск стека
docker compose up -d

# 2. Проверка статуса
curl http://localhost:8050/api/health

# 3. Пересборка прокси (при изменениях кода)
docker compose build proxy && docker compose up -d proxy
```

### Доступ к сервисам
| Сервис | URL | Описание |
|---|---|---|
| С.О.В.У.Ш.К.А. (Dashboard) | `http://localhost:8051` | Главный UI с чатом, метриками, логами, управлением датасетами |
| Qdrant Dashboard | `http://localhost:6333/dashboard` | Управление коллекциями и точками |
| Ollama API | `http://localhost:11434` | Локальный LLM-сервер (на хосте) |

## 📡 Топология портов
| Порт | Сервис | Роль |
|---|---|---|
| 8050 | proxy (Л.Е.С.) | Единая точка входа, API Gateway |
| 8051 | sovushka_ng.py | С.О.В.У.Ш.К.А. UI (NiceGUI) |
| 6333 | qdrant | Векторная база данных (UI + API) |
| 11434 | ollama (хост) | LLM и Embedding сервер |
| 8080 | mlx_host.py | MLX LLM + Embeddings (на Metal) |

## 📁 Структура проекта v2.0
```
LES_v2/
├── proxy_server.py           # FastAPI ядро, роуты, CRAG, SSE, метрики
├── docker-compose.yml        # Qdrant + Proxy (volumes: data, storage, frontend, backend)
├── Dockerfile.proxy          # Сборка контейнера
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
- SQLite-метаданные, UUID-датасеты в `storage/datasets/`, persistence через Docker volumes.
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

📅 **Документация актуализирована:** 17.05.2026 — релиз v5.0 UI (NiceGUI Modular)


## 📊 Фактический статус системы (Аудит 17.05.2026)
✅ Подтверждено работой в production:
- Uvicorn запущен без `--reload`. Hot-reload отключён для стабильности Docker.
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
- **Правила:** Указывать ≤3–4 файла. Для кода — EN промпт, для доков — RU. Лимит контекста ~32k токенов. После правок `.py` → `docker compose restart proxy`.
- **Откаты:** `git status` перед стартом. Откат: `git checkout <commit> -- <file>`.

