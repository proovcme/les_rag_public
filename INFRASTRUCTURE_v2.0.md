# 🖥️ Инфраструктура Л.Е.С. v2.0+ (Mac Mini M4 + host LaunchAgents + MLX)

**Статус:** ✅ Активна | **Обновлено:** 25.05.2026 | **Версия:** 3.6 no-Docker runtime
**Архитектура:** Headless Mac Mini M4 / 24 GB + ZeroTier P2P + host LaunchAgents (Qdrant + Proxy + UI + indexer) + MLX Native Host. Docker Desktop/OrbStack удалены из штатного контура. Ollama сохранён как резерв.

## 📋 Узлы сети (ZeroTier)
| Устройство | Роль | IP-адрес | Доступ | ОС |
|---|---|---|---|---|
| Mac Mini M4 | Сервер / Хост | 10.195.146.98 | SSH, UI:8051, API:8050, Qdrant:6333, MLX:8080 | macOS 26.4.1 |
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

## 🤖 MLX Host / модельный стек
**Сервис:** `mlx_host.py`, порт `8080`

| Модель | Роль | Примечание |
|---|---|---|
| `mlx-community/Qwen3-14B-4bit` | main LLM, RAG-ответы | Metal / Apple Silicon |
| `mlx-community/Qwen3-4B-4bit` | Т.О.С.К.А., validation, rerank | выгружается по TTL |
| `BAAI/bge-m3` | embeddings | MPS / локально |

Запуск:
```bash
./start_mlx.command
```

## 🧠 Runtime memory profiles
Актуальная политика памяти вынесена в отдельный runbook:
[`RUNTIME_MEMORY_PROFILES.md`](./RUNTIME_MEMORY_PROFILES.md).

Главное правило: сервисы могут быть подняты, но модели не должны жить в памяти
без активного lease под конкретную операцию. Memory guard имеет право выгружать
только LES-модели и останавливать LES-owned jobs/services; чужие процессы macOS,
GUI, IDE и браузеры он не трогает.

## 🤖 Ollama Конфигурация (резерв)
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

Ollama не является основным runtime. Использовать только как fallback/локального помощника.

## 🧭 Host LaunchAgents v3.6
**Путь:** `~/Library/LaunchAgents/` и plist-файлы проекта.

| LaunchAgent | Порт | Роль | Статус |
|---|---:|---|---|
| `me.ovc.les.qdrant` | 6333/6334 | Qdrant local binary, storage `data/qdrant/` | active |
| `me.ovc.les.proxy` | 8050 | FastAPI ядро, RAG, CRAG, auth, metrics | active |
| `com.les.sovushka` | 8051/8066 | Sovushka Lite chat + NiceGUI admin/Qdrant visualizer | active |
| `me.ovc.les.mlx` | 8080 | MLX LLM/validator/embedder | active |
| `me.ovc.les.qwen-index-until-done` | — | guarded qwen indexing loop (`batch_limit=1`) | active while pending |
| `me.ovc.les.pauk` | — | SSH tunnel fallback | loaded, normally stopped |

## 🌐 П.А.У.К. / публичный контур
| Маршрут | Назначение | Backend |
|---|---|---|
| `https://les.ovc.me/api/*` | API proxy | `localhost:8050` |
| `https://les.ovc.me/` | Sovushka Lite chat shell | `localhost:8051` |
| `https://les.ovc.me/classic` | Legacy NiceGUI chat shell | `localhost:8051` |
| `https://les.ovc.me/les` | Admin shell | `localhost:8051` |

Чат и админка разделены на уровне routes. Основной `/` отдаёт статический Lite-shell
без NiceGUI client state; rich NiceGUI chat сохранён на `/classic`, админка на `/les`.

**Зависимости Proxy (`requirements.txt`):**
FastAPI, Uvicorn, Pydantic v2, LlamaIndex, Qdrant-client, `pymupdf4llm`, `mammoth`, `extract-msg`, `pandas`, `sse-starlette`, `psutil`.

**Хранение данных:**
- `./data/qdrant/` → Qdrant local storage
- `./data/les_meta.db` → SQLite метаданные датасетов/документов
- `./data/les_metrics.db` → SQLite time-series метрики П.Р.О.Р.А.Б.
- `./storage/datasets/` → Физические UUID-папки загруженных файлов
- `./RAG_Content/` → Исходники (NTD, BIM, MAIL) для загрузки
- `./frontend/`, `./backend/` → Hot-reload кода без пересборки

## 🔄 Сценарии эксплуатации
### 1. Полный сброс питания
1. Подача 220В → Mac Mini включается (`autorestart 1`).
2. Загрузка macOS → автологин `ovc`.
3. Запуск launchd agents: Qdrant, proxy, MLX, UI, при необходимости indexer.
4. Docker не нужен и не должен быть частью штатного восстановления.
**Итог:** Через 60 сек доступен `http://localhost:8050` и SSH.

### 2. Проверка состояния
```bash
# Статус launchd-сервисов
launchctl list | grep -E 'les|sovushka|qdrant|mlx'

# Qdrant
curl -s http://localhost:6333/healthz

# Метрики системы
curl -s http://localhost:8050/api/metrics | python3 -m json.tool

# UI health and Lite shell
curl -s http://localhost:8051/healthz
curl -I http://localhost:8051/

# Логи индексации и proxy
tail -f logs/qwen_index_until_done.log
tail -f logs/proxy.log
```

### 3. Пересборка ядра (при обновлении кода)
```bash
cd ~/Projects/LES_v2
launchctl kickstart -k gui/$(id -u)/me.ovc.les.proxy
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
| Runtime | No-Docker host LaunchAgents, без Docker socket/daemon | ✅ |
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
| 25.05.2026 | Docker Desktop/OrbStack удалены из runtime; Qdrant переведён на local binary + LaunchAgent. |
| 10.05.2026 | Исправлен persistence: проброс `./data` и `./storage` в volumes. |
| 22.05.2026 | Основной runtime зафиксирован на MLX Host; Ollama переведён в резерв. |
| 22.05.2026 | Разделены UI routes: `/` чат, `/les` админка. |
| 22.05.2026 | `restart_sovushka.command` запускает `.venv/bin/python3` и пишет реальный PID. |

📅 **Документация актуальна на:** 22.05.2026


## 🧭 Host runtime v3.6 (Обновлено 25.05.2026)
- Uvicorn работает в production-режиме. Авто-релоад отключён во избежание deadlock'ов и лишних fork-процессов.
- Метрики (П.Р.О.Р.А.Б.) собираются неблокирующим фоновым циклом (`asyncio.to_thread` + `psutil` + SQLite + Qdrant).
- Данные лежат на host: `./data`, `./storage`, `./RAG_Content`, `./frontend`, `./backend`. Qdrant storage — `./data/qdrant`.
- Прокси использует `asyncio.to_thread` для всех дисковых операций → event-loop не зависает под нагрузкой.

## 📝 История изменений
| Дата | Изменение |
|---|---|
| 10.05.2026 | Фикс Uvicorn hot-reload deadlock, переход на production-режим. |
| 10.05.2026 | Внедрён фоновый коллектор метрик, неблокирующий кэш. |
| 10.05.2026 | Delta-Sync, идемпотентная регистрация, рекурсивный обход. |
| 10.05.2026 | Потоковый JSON-парсер для логов LLM (200MB+). |
