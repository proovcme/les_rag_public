# 🦉 Л.Е.С. — Локальная Единая Система v2.0

## Описание
Л.Е.С. v2.0 — суверенный инженерный RAG-стек для работы с BIM-данными, нормативной документацией (ГОСТ/СП), проектной перепиской и каталогами. Построен на принципах **Fully Local / Zero-Cloud / Lightweight**.  
В v2.0 полностью исключены тяжёлые зависимости (RAGFlow, Elasticsearch, MySQL, MinIO, Redis, Celery). Ядро переписано на FastAPI + LlamaIndex + Qdrant. Конфиденциальные данные никогда не покидают локальный контур.

## 🔑 Ключевые изменения v2.0
- **Ядро:** FastAPI Proxy + Qdrant (векторный поиск) + LlamaIndex (оркестрация).
- **Модели:** `qwen3:14b` (чат/RAG), `qwen2.5-coder:14b` (код/Roo Code), `bge-m3:latest` (эмбеддинги).
- **Конвертация:** Lightweight Converter Router (`pymupdf4llm`, `mammoth`, `extract-msg`, `pandas`). Без Docling/нейросетей на этапе парсинга.
- **Чанкинг:** Structure-Aware (MarkdownNodeParser + SentenceSplitter). Нарезка по заголовкам ГОСТ/СП, а не по токенам.
- **Метаданные:** SQLite (`les_meta.db`) вместо MySQL. UUID-датасеты в `storage/datasets/`.
- **Т.О.С.К.А. (CRAG):** Нативный Python-пайплайн в прокси (Pre-Check → Retrieval → Generation → Post-Check).
- **Мониторинг:** SSE-стрим + Chart.js в С.О.В.У.Ш.К.Е. Без Grafana/Metabase.
- **Ресурсы:** 2 контейнера (Qdrant + Proxy). RAM ~14–16 ГБ. Запуск на Mac M4 / 24 GB без свопа.

## 🗺️ Карта архитектуры v2.0
| Модуль | Расшифровка | Роль | Реализация v2.0 |
|---|---|---|---|
| Л.Е.С. | Локальная Единая Система | Оркестратор, API Gateway | `proxy_server.py` (FastAPI) |
| С.А.М.О.В.А.Р. | Система Автономная Машинной Обработки Внутренних Архивов РАГ | Ядро RAG и поиска | Qdrant + LlamaIndex + `bge-m3` |
| Т.О.С.К.А. | Терминал Оценки, Самопроверки и Контроля Архитектуры | CRAG-валидация, фильтр галлюцинаций | Native Python pipeline в прокси |
| В.О.Л.К. | Внутренний Охранный Локальный Контур | RBAC, аутентификация | JWT-токены, SQLite, middleware |
| С.О.В.У.Ш.К.А. | Система Обработки и Выдачи... | Интеллектуальный UI | `frontend/sovushka.html` + Chart.js |
| С.У.Х.А.Р.И.К. | Система Управления Холодными Архивами... | Бэкапы и архивация | Снапшоты Qdrant + `storage/` |
| П.Р.О.Р.А.Б. | Программа Регулярной Оценки Работы Автономной Базы | Метрики и диагностика | `/api/metrics`, SSE-логи, psutil |

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
| С.О.В.У.Ш.К.А. (Dashboard) | http://localhost:8050 | Главный UI с чатом, метриками, логами |
| Qdrant Dashboard | http://localhost:6333/dashboard | Управление коллекциями и точками |
| Ollama API | http://localhost:11434 | Локальный LLM-сервер (на хосте) |

## 📡 Топология портов
| Порт | Сервис | Роль |
|---|---|---|
| 8050 | proxy (Л.Е.С.) | Единая точка входа, Static & API Gateway |
| 6333 | qdrant | Векторная база данных (UI + API) |
| 11434 | ollama (хост) | LLM и Embedding сервер |

## 📁 Структура проекта v2.0
```
LES_v2/
├── proxy_server.py           # FastAPI ядро, роуты, CRAG, SSE
├── docker-compose.yml        # Qdrant + Proxy
├── Dockerfile.proxy          # Сборка контейнера
├── requirements.txt          # Зависимости (FastAPI, LlamaIndex, Qdrant, pymupdf4llm...)
├── .env                      # Конфиг моделей и путей
│
├── backend/
│   ├── __init__.py
│   ├── interface.py          # Контракт RAGBackend
│   ├── qdrant_adapter.py     # Адаптер Qdrant + LlamaIndex + Structure-Aware Chunking
│   └── converter.py          # ConverterRouter (PDF/DOCX/EML/XLSX → Markdown)
│
├── frontend/
│   └── sovushka.html         # UI с Chart.js, SSE-логами, чатом
│
├── storage/
│   └── datasets/             # Физические UUID-папки датасетов
│
├── RAG_Content/              # Исходники для загрузки (NTD, BIM, MAIL)
│
├── data/
│   ├── qdrant/               # Volume Qdrant
│   └── les_meta.db           # SQLite метаданные датасетов/документов
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
| `/api/metrics` | GET | Агрегированные метрики (CPU/RAM/RAG/CRAG) |

### RAG & Datasets
| Endpoint | Method | Описание |
|---|---|---|
| `/api/rag/datasets` | GET/POST | Список/создание датасетов |
| `/api/rag/upload/{id}` | POST | Загрузка файла → конвертация → индексация |
| `/api/rag/delta` | GET | Дельта-анализ файлов |
| `/api/chat` | POST | Чат с Т.О.С.К.А. валидацией |

## 🛠 Текущее состояние v2.0
✅ **Работает:**
- Полный пайплайн: Файл → ConverterRouter → Structure-Aware Chunking → bge-m3 → Qdrant → Retrieval → qwen3 → CRAG → Ответ.
- Поддержка PDF (pymupdf4llm), DOCX (mammoth), EML/MSG, XLSX/CSV.
- SQLite-метаданные, UUID-датасеты в `storage/datasets/`.
- SSE-логи, базовый UI, healthcheck.

⏳ **В работе:**
- Полная загрузка папки NTD и валидация на тяжёлых ГОСТ/СП.
- Retry-логика в прокси для устойчивости к нагрузке Ollama.
- Дашборды Chart.js, фильтры логов, экспорт метрик.
- RBAC v2.0 (JWT), бэкапы Qdrant (С.У.Х.А.Р.И.К.).

📅 **Документация актуализирована:** 10.05.2026 — релиз v2.0 Core
