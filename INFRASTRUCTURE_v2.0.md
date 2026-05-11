# 🖥️ Инфраструктура Л.Е.С. v2.0 (Mac Mini M4 + Docker + Ollama)

**Статус:** ✅ Активна | **Обновлено:** 10.05.2026 | **Версия:** 2.0  
**Архитектура:** Headless Mac Mini M4 / 24 GB + ZeroTier P2P + Docker (Qdrant + Proxy) + Ollama Native

## 📋 Узлы сети (ZeroTier)
| Устройство | Роль | IP-адрес | Доступ | ОС |
|---|---|---|---|---|
| Mac Mini M4 | Сервер / Хост | 10.195.146.98 | SSH, Docker, Ollama, UI:8050 | macOS 26.4.1 |
| MacBook Air | Клиент / Управление | 10.195.146.176 | SSH, Browser | macOS |
| Lenovo Legion | Клиент / Управление | 10.195.146.20 | SSH, Browser | Windows 11 |

**Параметры сети:**  
Network ID: `8d1c312afa249de4` | Подсеть: `10.195.146.0/24` | Транспорт: P2P (UDP 9993)

## 🍎 Базовая настройка Mac Mini M4
| Параметр | Команда / Значение | Назначение |
|---|---|---|
| FileVault | Off | Отключено для автономной загрузки |
| Автологин | `sudo defaults write ... autoLoginUser ovc` | Автоматический вход |
| Авторестарт | `sudo pmset -a autorestart 1` | Включение после сбоя питания |
| Сон | `sudo pmset -a sleep 0 disksleep 0` | Запрет спящего режима |
| Сеть | Ethernet (en0) приоритет №1 | Стабильный линк, ZeroTier не мешает |

## 🤖 Ollama Конфигурация (Модельный стек)
**Файл:** `~/.ollama/env`
```env
OLLAMA_NUM_PARALLEL=1
OLLAMA_MAX_LOADED_MODELS=1
OLLAMA_KEEP_ALIVE=10m
OLLAMA_CONTEXT_LENGTH=8192
```

**Модели:**
| Модель | Размер | Роль | RAM |
|---|---|---|---|
| `qwen3:14b` | 9.3 GB | RAG-чат, Т.О.С.К.А. валидация | ~9.3 GB |
| `qwen2.5-coder:14b` | 9.0 GB | Генерация кода (Roo Code) | ~9.0 GB |
| `bge-m3:latest` | 1.2 GB | Эмбеддинги (векторизация чанков) | ~1.2 GB |

Ollama автоматически выгружает неактивную модель. Параллельно в RAM живут только чат + эмбеддинг (~10.5 GB).

## 🐳 Сервисы и контейнеры v2.0
**Путь:** `~/Projects/LES_v2/docker-compose.yml`

| Сервис | Образ | Порт | RAM | Роль |
|---|---|---|---|---|
| les-qdrant | qdrant/qdrant:latest | 6333 | ~1.5 GB | Векторная БД, хранение чанков и payload |
| les-proxy | python:3.11-slim (custom) | 8050 | ~0.5 GB | FastAPI ядро, CRAG, ConverterRouter, SSE, Metrics |

**Зависимости Proxy (`requirements.txt`):**  
FastAPI, Uvicorn, Pydantic v2, LlamaIndex, Qdrant-client, `pymupdf4llm`, `mammoth`, `extract-msg`, `pandas`, `sse-starlette`, `psutil`.

**Хранение данных (Volumes):**
- `./data/qdrant/` → Volume векторной БД
- `./data/les_meta.db` → SQLite метаданные датасетов/документов
- `./data/les_metrics.db` → SQLite time-series метрики П.Р.О.Р.А.Б.
- `./storage/datasets/` → Физические UUID-папки загруженных файлов
- `./RAG_Content/` → Исходники (NTD, BIM, MAIL) для загрузки
- `./frontend/`, `./backend/` → Hot-reload кода без пересборки

## 🔄 Сценарии эксплуатации
### 1. Полный сброс питания
1. Подача 220В → Mac Mini включается (`autorestart 1`).
2. Загрузка macOS → автологин `ovc`.
3. Запуск Login Items → Docker Desktop, Ollama.
4. `docker compose up -d` (если не настроен автозапуск compose).
**Итог:** Через 60 сек доступен `http://localhost:8050` и SSH.

### 2. Проверка состояния
```bash
# Статус контейнеров
docker ps --format "table {{.Names}}\t{{.Status}}"

# Память моделей Ollama
ollama ps

# Метрики системы
curl -s http://localhost:8050/api/metrics | python3 -m json.tool

# Логи индексации
docker logs -f les-proxy | grep -E "\[PARSE\]|\[CONVERT\]"
```

### 3. Пересборка ядра (при обновлении кода)
```bash
cd ~/Projects/LES_v2
docker compose build proxy && docker compose up -d proxy
```

### 4. Массовая загрузка нормативки
Через UI С.О.В.У.Ш.К.А. → вкладка **Датасеты** → кнопка `🔄 Загрузить в индекс` напротив нужной папки.  
Или через API: `POST /api/rag/sync/NTD`

## 🛡️ Безопасность
| Уровень | Мера | Статус |
|---|---|---|
| Сеть | ZeroTier P2P, закрытая подсеть | ✅ |
| Доступ | SSH по ключам, UI без пароля (локально) | ✅ |
| Данные | Полностью локально, Zero-Cloud | ✅ |
| Контейнеры | Изоляция сетей Docker, `unless-stopped` | ✅ |
| Модели | Лимиты RAM, автовыгрузка, контекст 8K | ✅ |
| Нагрузка | `asyncio.Semaphore(2)` на индексацию | ✅ |

## 📝 История изменений
| Дата | Изменение |
|---|---|
| 10.05.2026 | Создана инфраструктура v2.0. Отказ от RAGFlow/ES/MySQL/MinIO. |
| 10.05.2026 | Внедрён стек Qdrant + FastAPI + LlamaIndex + Ollama. |
| 10.05.2026 | Настроен ConverterRouter (pymupdf4llm, mammoth, pandas). |
| 10.05.2026 | Фиксация Ollama env, приоритет Ethernet, структура storage/datasets. |
| 10.05.2026 | Внедрены SQLite-метрики, SSE-логи, Chart.js дашборды. |
| 10.05.2026 | Реализован UI Sync: `/api/rag/sources`, `/api/rag/sync/{folder}`, вкладка Датасеты. |
| 10.05.2026 | Исправлен persistence: проброс `./data` и `./storage` в volumes. |

📅 **Документация актуальна на:** 10.05.2026


## 🐳 Сервисы и контейнеры v2.0 (Обновлено 10.05.2026)
- Uvicorn работает в production-режиме. Авто-релоад отключён во избежание deadlock'ов при маппинге volumes.
- Метрики (П.Р.О.Р.А.Б.) собираются неблокирующим фоновым циклом (`asyncio.to_thread` + `psutil` + SQLite + Qdrant).
- Volumes проброшены полностью: `./data`, `./storage`, `./RAG_Content`, `./frontend`, `./backend`. Данные переживают рестарты.
- Прокси использует `asyncio.to_thread` для всех дисковых операций → event-loop не зависает под нагрузкой.

## 📝 История изменений
| Дата | Изменение |
|---|---|
| 10.05.2026 | Фикс Uvicorn hot-reload deadlock, переход на production-режим. |
| 10.05.2026 | Внедрён фоновый коллектор метрик, неблокирующий кэш. |
| 10.05.2026 | Delta-Sync, идемпотентная регистрация, рекурсивный обход. |
| 10.05.2026 | Потоковый JSON-парсер для логов LLM (200MB+). |
