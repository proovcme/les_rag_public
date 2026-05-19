# 🦉 Л.Е.С. — Локальная Единая Система
## Мастер-документ v2.7 | 19.05.2026

> Единый источник истины. Объединяет README, ROADMAP, Архитектуру, Инфраструктуру, Словарь, Программу испытаний.  
> Авторы: Клодыч (Claude), Кен (Qwen), Панорамыч (Gemini).

---

## 📋 СОДЕРЖАНИЕ

1. [Концепция и принципы](#1-концепция-и-принципы)
2. [Словарь акронимов](#2-словарь-акронимов)
3. [Архитектура системы](#3-архитектура-системы)
4. [Инфраструктура](#4-инфраструктура)
5. [Установка и запуск](#5-установка-и-запуск)
6. [API Reference](#6-api-reference)
7. [Технические вопросы и решения](#7-технические-вопросы-и-решения)
8. [Программа испытаний](#8-программа-испытаний)
9. [Roadmap](#9-roadmap)
10. [Работа с AI-ассистентами](#10-работа-с-ai-ассистентами)

---

## 1. КОНЦЕПЦИЯ И ПРИНЦИПЫ

**Л.Е.С. v2.0** — суверенный инженерный RAG-стек для работы с нормативной документацией (ГОСТ/СП), проектной перепиской, каталогами и BIM-данными.

### Принципы
| Принцип | Реализация |
|---|---|
| **Fully Local** | Все модели на устройстве, нет cloud API |
| **Zero-Cloud** | Данные никогда не покидают локальный контур |
| **Lightweight** | 2 Docker-контейнера, без RAGFlow/ES/MySQL/MinIO/Redis/Celery |
| **Sovereign** | Полный контроль над кодом, данными, моделями |

### Ключевые изменения v1.5 → v2.0
- Полный отказ от RAGFlow, Elasticsearch, MySQL, MinIO, Redis, Celery
- Ядро: FastAPI + LlamaIndex + Qdrant
- Модели: Ollama-оркестрация (`qwen3:14b`, `bge-m3:latest`)
- MLX Native Host: Qwen3-14B + Qwen3-4B + bge-m3 на Apple Silicon Metal

### Ключевые изменения v2.0 → v2.1
- С.О.В.У.Ш.К.А. переехала на **NiceGUI** (порт 8051) — единая Python-кодовая база
- Форма запроса: 8 форматов выдачи (текст / спецификация / схема / таблица / Mermaid / SVG / по образцу)
- Вкладка диагностики с Mermaid-топологией и автоматическими чеками
- `/api/diag` — новый эндпоинт полной диагностики (11 чеков)
- Т.О.С.К.А. v2: три независимых счётчика (VERIFIED / NO_DATA / HALLUCINATION)
- `dataset_filter` в `/api/chat` — фильтр по имени папки без UUID

### Ключевые изменения v2.6 → v2.7 (текущая)
- **SafeRAG петля** — при HALLUCINATION автоматический retry: строгий промпт + сужение до top-1 документа; после 2 неудач ответ блокируется (`_SAFE_FALLBACK`)
- **Концентрация источников** — `_concentrate_sources()`: после retrieval отбрасываем все документы кроме top-2 по max-score; убирает "контаминацию контекста" (4 несвязанных документа в одном ответе)
- **Т.О.С.К.А. v3: релевантность** — судья теперь ставит HALLUCINATION не только за противоречие контексту, но и за ответ не по теме вопроса
- **ИСТОРИЯ чатов** — новый таб, сессионная группировка (UUID per conversation), клик → переход в чат с восстановлением истории; `/api/chat/sessions` эндпоинт
- **Шапка-однополосник** — объединены header + tabbar в одну sticky-полосу 44px; убрана мёртвая кнопка РАГ/КОД
- **Шрифт ISOCPEUR** — чат-пузыри рендерятся шрифтом автокадовского черчения; подключён через `@font-face` из `/static/fonts/`
- **Контраст** — пересмотрены CSS-переменные тёмной и светлой тем (`--text`, `--dim`, `--border`), Quasar-оверрайды для селектов и списков
- **Watchdog памяти** — `memory_guard_loop()` в `mlx_host.py`: ≥70% swap → выгрузка val-модели; ≥85% → kill non-essential processes; TTL: val=120с, main=300с
- **Сессионный `session_id`** — передаётся в `/api/chat`, сохраняется в `chat_history`; новая сессия при сбросе чата

### Ключевые изменения v2.2 → v2.3
- **Т.О.С.К.А.: исправлен статус UNKNOWN** — `enable_thinking=False` для Qwen3-4B (валидатор не думает, сразу отвечает), `max_tokens` поднят с 10 до 64
- **С.О.В.У.Ш.К.А.: убрана обрезка ответа** — лимит 600 символов в чат-пузыре снят, ответ полный
- **С.О.В.У.Ш.К.А.: индикатор прогресса** — тикер `⟳ Генерирую... Nс` обновляется каждую секунду пока ИИ думает
- **С.О.В.У.Ш.К.А.: персистентность таба** — активная вкладка сохраняется в `app.storage.user`, не сбрасывается при reconnect
- **С.О.В.У.Ш.К.А.: светлая тема** — `Quasar.Dark.set()` переключает Quasar-компоненты, добавлен `--pauk`, улучшены контрасты

---

## 2. СЛОВАРЬ АКРОНИМОВ

| Акроним | Полное название | Роль | Статус |
|---|---|---|---|
| **Л.Е.С.** | Локальная Единая Система | Оркестратор, API Gateway (`proxy_server.py`) | ✅ Live |
| **Ж.А.Б.А.** | Жёсткая Аппаратная База Аналитики | Физический фундамент (Mac Mini M4 / 24 GB) | ✅ Live |
| **С.А.М.О.В.А.Р.** | Система Автономная Машинной Обработки Внутренних Архивов РАГ | Ядро RAG: Qdrant + LlamaIndex + bge-m3 | ✅ Live |
| **Т.О.С.К.А.** | Терминал Оценки, Самопроверки и Контроля Архитектуры | CRAG-валидация, фильтр галлюцинаций | ✅ Live |
| **С.О.В.У.Ш.К.А.** | Система Обработки и Выдачи: Умная, Шаблонизированная, Классифицированная, Автоматизированная | UI на NiceGUI (порт 8051) | ✅ v5.0 (Модульная) |
| **П.Р.О.Р.А.Б.** | Программа Регулярной Оценки Работы Автономной Базы | Метрики, диагностика, `/api/metrics` | ✅ Live |
| **К.О.Т.** | Куратор Отраслевой Терминологии | Семантический фильтр инженерного языка | 🔨 В разработке |
| **В.О.Л.К.** | Внутренний Охранный Локальный Контур | RBAC, ключи доступа (SQLite) | ✅ Live |
| **П.А.У.К.** | Периметровый Автономный Узел Коммуникаций | VPS-relay: Caddy + ZeroTier mesh | ✅ Live |
| **С.У.Х.А.Р.И.К.** | Система Управления Холодными Архивами и Резервными Источниками Комплекса | Снапшоты Qdrant, бэкапы | 🔨 В разработке |
| **Е.Ж.И.К.** | *(расшифровка уточняется)* | Обработка почты IMAP/EML | ⏳ Запланирован |

### П.А.У.К. — детали

**Состав:**
- **VPS** — Debian 13, `185.185.71.196`, ZeroTier `10.195.146.136`
- **ZeroTier** — self-hosted сеть `8d1c312afa249de4`, подсеть `10.195.146.0/24`
- **Caddy** — reverse proxy с автоматическим HTTPS (Let's Encrypt)
- **DNS** — `les.ovc.me` → `185.185.71.196`

**Топология (live, v2.7+):**
```
Интернет → les.ovc.me → Caddy (VPS :443)
                             ├── /api/* → localhost:8050 (proxy_server на VPS)
                             └── /*     → localhost:8051 (sovushka_ng на VPS)
                                              │
                             ZeroTier mesh (10.195.146.0/24)
                                              │
                             Mac Mini (Ж.А.Б.А.) — 10.195.146.98
                                  ├── :6333 Qdrant
                                  └── :8080 MLX Host
```

**ZeroTier:**
- VPS: `10.195.146.136`, Mac Mini: `10.195.146.98`, сеть `8d1c312afa249de4`
- VPS `.env`: `QDRANT_URL=http://10.195.146.98:6333`, `OLLAMA_URL=http://10.195.146.98:8080`

**SSH туннель (резерв, не активен):**
```
~/Library/LaunchAgents/me.ovc.les.pauk.plist  — НЕ удалять, использовать как fallback
# Запустить при необходимости: launchctl load ~/Library/LaunchAgents/me.ovc.les.pauk.plist
# Также вернуть в .env: QDRANT_URL=http://127.0.0.1:6333 / OLLAMA_URL=http://127.0.0.1:8080
```

**VPS systemd-сервисы:**
```
les_proxy.service  — uvicorn proxy_server:app --port 8050
sovushka.service   — python3 sovushka_ng.py   --port 8051
caddy.service      — Caddy (автозапуск, Let's Encrypt)
zerotier-one.service
```
Конфиг: `/root/les_v2/.env` (читается через `EnvironmentFile=` в systemd)

**`/etc/caddy/Caddyfile`:**
```caddyfile
les.ovc.me {
    reverse_proxy /api/* localhost:8050
    reverse_proxy /* localhost:8051
}
```

**В.О.Л.К. — доступ:**
| Откуда | Ключ | Роль |
|--------|------|------|
| ZeroTier (`10.x.x.x`) | не нужен | user (auto-bypass) |
| Интернет | `les_75f0507b502d2ab1` | user |
| Интернет | `les_aed1ff4721f776e1` (melnik) | admin |

Ключи хранятся в `/root/les_v2/data/les_meta.db`, таблица `auth_keys`.

---

## 3. АРХИТЕКТУРА СИСТЕМЫ

### 3.1. Стек (текущий)
```
Mac Mini M4 / 24 GB  (Ж.А.Б.А.)
│
├── Docker
│   ├── les-proxy   (FastAPI, порт 8050) — Л.Е.С. ядро, RAG, CRAG, API
│   └── les-qdrant  (Qdrant, порт 6333)  — С.А.М.О.В.А.Р. векторная база
│
├── MLX Native Host (FastAPI, порт 8080) — основной LLM + Embeddings на Metal
│   ├── Qwen3.5-9B-MLX-4bit        (main, RAG, TTL 300с, ~6 GB RAM)
│   ├── Qwen3-4B-Instruct-2507-4bit (val, Т.О.С.К.А.+реранкер, TTL 120с, ~2.5 GB)
│   └── bge-m3                      (embed, постоянно в памяти)
│
└── С.О.В.У.Ш.К.А. (NiceGUI, порт 8051) — UI v5.0
    ├── ОБЗОР        — карта модулей, стек
    ├── С.А.М.О.В.А.Р. — AG Grid датасетов, jobs
    ├── П.Р.О.Р.А.Б.   — метрики, MLX, Docker, Т.О.С.К.А. v2
    ├── AI ЧАТ       — чат + Форма запроса (8 форматов)
    ├── ГРАФ         — Mermaid редактор + превью
    └── ДИАГНОСТИКА  — 11 чеков, topology map, лог
```

> **Примечание v2.2:** Ollama полностью выведен из основного пайплайна. `sovushka/config.py` содержит `MLX_URL = "http://127.0.0.1:8080"` как единственный LLM-бэкенд. Ollama остаётся установленным как аварийный резерв.

### 3.2. Поток данных (SafeRAG v2.7)
```
Запрос → /api/chat
  → dataset_filter resolve (имя → UUID)
  → Qdrant retrieve (bge-m3 embeddings, top-k=8)
  → [опц.] Реранкер (Qwen3-4B batch, 1 вызов) → top-5
  → _concentrate_sources(): top-2 документа по max-score, min_score=0.45
  │
  ├─ Попытка 1: нормальный промпт, 12 000 симв., top-2 docs
  │     → MLX Host Qwen3.5-9B генерирует ответ
  │     → Т.О.С.К.А. /api/validate (Qwen3-4B)
  │         VERIFIED  → ответ клиенту ✓
  │         NO_DATA   → "нет данных" ✓
  │         HALLUCINATION → переход к попытке 2
  │
  └─ Попытка 2: строгий промпт, 6 000 симв., top-1 doc
        → MLX Host Qwen3.5-9B генерирует ответ
        → Т.О.С.К.А. /api/validate (Qwen3-4B)
            VERIFIED  → ответ клиенту ✓
            NO_DATA   → "нет данных" ✓
            HALLUCINATION → ⚠ SAFE_FALLBACK (блокировка)

  → crag_stats обновляются (verified / no_data / hallucination)
  → История сохраняется в chat_history (с session_id)
  → Ответ клиенту
```

### 3.3. Структура файлов проекта
```
LES_v2/
├── proxy_server.py           # FastAPI ядро (848 строк, v2.1)
├── sovushka_ng.py            # Точка входа С.О.В.У.Ш.К.А. v5.0 (~90 строк)
├── sovushka/                 # Модульный пакет UI (страницы, компоненты, стейт)
│   ├── config.py             # PROXY_URL, MLX_URL, UI_PORT
├── mlx_host.py               # MLX Native Host (порт 8080)
├── start_mlx.command         # Запуск MLX через uv run
├── stop_mlx.command
├── docker-compose.yml        # les-qdrant + les-proxy
├── Dockerfile.proxy          # python:3.11-slim + docker-ce-cli
├── requirements.txt
├── .env                      # LLM_MODEL, EMBED_MODEL, OLLAMA_URL...
│
├── backend/
│   ├── __init__.py
│   ├── interface.py          # Контракт RAGBackend / DatasetInfo
│   ├── qdrant_adapter.py     # Qdrant + LlamaIndex + rglob
│   ├── converter.py          # PDF/DOCX/EML/XLSX → Markdown
│   ├── mlx_adapter.py        # MLXMemoryManager (TTL, Lock, gc)
│   └── metrics_collector.py  # SQLite time-series метрики
│
├── frontend/
│   └── sovushka.html         # Legacy HTML (резерв)
│
├── storage/datasets/         # UUID-папки загруженных файлов
├── RAG_Content/              # Исходники (NTD/, BIM/, MAIL/, ...)
└── data/
    ├── qdrant/               # Volume Qdrant
    ├── les_meta.db           # SQLite: datasets, documents
    └── les_metrics.db        # SQLite: time-series метрики
```

### 3.4. Схема базы данных (SQLite)

**les_meta.db:**
```sql
CREATE TABLE datasets (
    id TEXT PRIMARY KEY,      -- UUID
    name TEXT,                -- "NTD_Index"
    status TEXT,              -- IDLE / PARSING / INDEXED / FAILED
    doc_count INTEGER,
    chunk_count INTEGER       -- ⚠ сейчас всегда 0, fix запланирован
);
CREATE TABLE documents (
    id TEXT PRIMARY KEY,
    dataset_id TEXT REFERENCES datasets(id),
    file_name TEXT,
    content TEXT              -- Markdown после конвертации
);
CREATE TABLE auth_keys (
    key TEXT PRIMARY KEY,
    role TEXT,                -- "admin" | "user"
    comment TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE chat_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    question TEXT,
    answer TEXT,
    sources TEXT,             -- JSON-массив ссылок
    crag_status TEXT,         -- VERIFIED | NO_DATA | HALLUCINATION
    latency_sec REAL,
    tokens INTEGER
);
```

**les_metrics.db:**
```sql
CREATE TABLE metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    cpu REAL, ram_used REAL, ram_total REAL,
    swap_used REAL, disk_used REAL, disk_total REAL,
    ollama_ram REAL, network_ok INTEGER
);
```

---

## 4. ИНФРАСТРУКТУРА

### 4.1. Физические узлы (ZeroTier)
| Устройство | Роль | ZeroTier IP | Внешний IP | ОС |
|---|---|---|---|---|
| Mac Mini M4 / 24 GB (Ж.А.Б.А.) | Сервер Л.Е.С. | 10.195.146.98 | — | macOS |
| MacBook Air | Клиент / управление | 10.195.146.176 | — | macOS |
| Lenovo Legion | Клиент / управление | 10.195.146.20 | — | Windows 11 |
| VPS box-925292 (П.А.У.К.) | Relay, HTTPS, Caddy | 10.195.146.136 | 185.185.71.196 | Debian 13 |

ZeroTier Network: `8d1c312afa249de4` | UDP 9993 | self-hosted controller

### 4.2. Порты сервисов
| Порт | Сервис | Описание |
|---|---|---|
| **8050** | les-proxy (Docker) | Л.Е.С. API Gateway |
| **8051** | sovushka_ng.py | С.О.В.У.Ш.К.А. NiceGUI UI |
| **8080** | mlx_host.py (native) | MLX LLM + Embeddings |
| **6333** | les-qdrant (Docker) | Qdrant векторная база |
| **11434** | Ollama (native) | Резервный LLM |
| **443** | Caddy (П.А.У.К.) | HTTPS les.ovc.me |

### 4.3. Ollama конфигурация
**`~/.ollama/env`:**
```env
OLLAMA_NUM_PARALLEL=1
OLLAMA_MAX_LOADED_MODELS=1
OLLAMA_KEEP_ALIVE=10m
OLLAMA_CONTEXT_LENGTH=8192
```

| Модель | Размер | Роль | RAM |
|---|---|---|---|
| `qwen3:14b` | 9.3 GB | RAG-чат, Т.О.С.К.А. (резерв) | ~9.3 GB |
| `qwen2.5-coder:14b` | 9.0 GB | Roo Code | ~9.0 GB |
| `bge-m3:latest` | 1.2 GB | Embeddings (резерв) | ~1.2 GB |

### 4.4. MLX стек
| Движок | Модель | TTL | Назначение |
|---|---|---|---|
| main_engine | `mlx-community/Qwen3.5-9B-MLX-4bit` | 300с | RAG (~6 GB RAM) |
| val_engine | `mlx-community/Qwen3-4B-Instruct-2507-4bit` | 120с | Т.О.С.К.А. + реранкер (~2.5 GB) |
| embed | `BAAI/bge-m3` | ∞ | Эмбеддинги (постоянно) |

### 4.5. Mac Mini — базовая конфигурация
```bash
# Отключение сна
sudo pmset -a sleep 0 disksleep 0

# Автозапуск после отключения питания
sudo pmset -a autorestart 1

# Приоритет Ethernet
# System Settings → Network → Ethernet → порядок интерфейсов
```

---

## 5. УСТАНОВКА И ЗАПУСК

### 5.1. Предварительные требования
- **Mac M4 / 24 GB** (или совместимый Apple Silicon)
- **Docker Desktop** — установить с docker.com
- **Ollama** — `brew install ollama`
- **Python 3.9+** — системный или через `brew install python@3.11`
- **uv** — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **ZeroTier** — https://zerotier.com (для сетевого контура П.А.У.К.)

### 5.2. Первый запуск (с нуля)

#### Шаг 1. Клонировать / скачать проект
```bash
cd ~/Projects
git clone <repo> LES_v2
cd LES_v2
```

#### Шаг 2. (пропустить — Ollama не используется)
MLX модели скачиваются автоматически при первом запросе из HuggingFace.

#### Шаг 3. Настроить `.env`
```env
LLM_MODEL=mlx-community/Qwen3.5-9B-MLX-4bit
EMBED_MODEL=bge-m3
MLX_URL=http://host.docker.internal:8080

MLX_MODEL=mlx-community/Qwen3.5-9B-MLX-4bit
MLX_VAL_MODEL=mlx-community/Qwen3-4B-Instruct-2507-4bit
RERANKER_ENABLED=false   # включается через переключатель в UI чата

QDRANT_URL=http://qdrant:6333
JWT_SECRET=les_v2_secret_key_change_in_prod
ADMIN_PASSWORD=admin123
```

#### Шаг 4. Запустить Docker стек
```bash
docker compose up -d
# Проверка
docker ps
curl http://localhost:8050/api/health
```

#### Шаг 5. Запустить MLX Host
```bash
chmod +x start_mlx.command stop_mlx.command
./start_mlx.command
# Проверка
curl http://localhost:8080/api/health
```
> Для автозапуска: добавить `start_mlx.command` в **System Settings → General → Login Items**.

#### Шаг 6. Установить зависимости NiceGUI
```bash
pip3 install nicegui httpx openpyxl
# Проверка версии (нужна ≥ 3.6.1)
python3 -c "import nicegui; print(nicegui.__version__)"
```

#### Шаг 7. Запустить С.О.В.У.Ш.К.А.
```bash
python3 sovushka_ng.py
# Открыть в браузере:
# http://localhost:8051
```

### 5.3. Известные проблемы при установке

#### ❌ TypeError: unsupported operand type(s) for |
**Причина:** `sovushka_ng.py` написан с `from __future__ import annotations` для поддержки Python 3.9, но строка запускается до применения этого импорта.  
**Решение:** Убедись что первая строка файла — `from __future__ import annotations`. В v4.0 (исправленном) это уже сделано.

#### ❌ Конфликт зависимостей aider-chat
```
aider-chat requires pydantic==2.11.4, but you have pydantic 2.13.4
```
**Это не критично** — Л.Е.С. работает. Aider использовать с:
```bash
# Восстановление aider
pip3 install huggingface-hub==0.30.2 pillow==11.2.1 tokenizers==0.21.1 \
    markupsafe==3.0.2 typing-inspection==0.4.0 pydantic==2.11.4
```

#### ❌ NotOpenSSLWarning (LibreSSL)
```
urllib3 v2 only supports OpenSSL 1.1.1+, currently 'LibreSSL 2.8.3'
```
**Это предупреждение**, не ошибка. Система работает. Для подавления:
```bash
pip3 install urllib3==1.26.20
```

#### ❌ MLX Host не запускается
```bash
# Проверить что uv установлен
which uv
# Проверить PID файл
cat logs/mlx_host.pid
# Запустить вручную
uv run python3 mlx_host.py
```

### 5.4. Пересборка при изменениях кода

```bash
# Прокси (в Docker)
docker compose build proxy && docker compose up -d proxy

# MLX Host
./stop_mlx.command && ./start_mlx.command

# С.О.В.У.Ш.К.А. (просто перезапустить)
# Ctrl+C → python3 sovushka_ng.py
```

### 5.5. Проверка состояния системы
```bash
# Контейнеры
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# Все сервисы разом
curl -s http://localhost:8050/api/health | python3 -m json.tool
curl -s http://localhost:8080/api/health | python3 -m json.tool
curl -s http://localhost:6333/collections | python3 -m json.tool

# Полная диагностика (11 чеков)
curl -s http://localhost:8050/api/diag | python3 -m json.tool

# Модели Ollama
ollama ps

# Метрики
curl -s http://localhost:8050/api/metrics | python3 -m json.tool

# Логи прокси
docker logs -f les-proxy | grep -E "\[PARSE\]|\[CHAT\]|\[DIAG\]"
```

### 5.6. П.А.У.К. — управление транспортом

**Основной транспорт — ZeroTier (активен):**
```bash
# Проверка связности
ping -c 3 10.195.146.98      # с VPS → Mac Mini
ping -c 3 10.195.146.136     # с Mac Mini → VPS

# Qdrant через ZeroTier
curl -s http://10.195.146.98:6333/healthz

# MLX через ZeroTier
curl -s http://10.195.146.98:8080/api/health
```

**Резервный транспорт — SSH tunnel (не активен, plist сохранён):**
```bash
# Активировать при необходимости (Mac Mini)
launchctl load ~/Library/LaunchAgents/me.ovc.les.pauk.plist
# Деактивировать
launchctl unload ~/Library/LaunchAgents/me.ovc.les.pauk.plist
# Статус
launchctl list me.ovc.les.pauk
# Лог
tail -f ~/Projects/LES_v2/logs/pauk.log
```

**Проверка связности с VPS:**
```bash
# Qdrant (ZeroTier)
ssh root@185.185.71.196 "curl -s http://10.195.146.98:6333/healthz"

# MLX (ZeroTier)
ssh root@185.185.71.196 "curl -s http://10.195.146.98:8080/api/health"

# HTTPS снаружи
curl -s https://les.ovc.me/api/health
```

**Управление VPS-сервисами:**
```bash
ssh root@185.185.71.196
systemctl status les_proxy.service sovushka.service caddy.service
systemctl restart les_proxy.service
journalctl -u les_proxy.service -n 20
```

**Добавить ключ доступа (через proxy API):**
```bash
curl -s https://les.ovc.me/api/keys \
  -H "X-API-Key: les_aed1ff4721f776e1" \
  -d '{"role":"user","comment":"новый пользователь"}'
```

### 5.7. Runbook — аварийное восстановление

#### ❌ SSH-туннель упал (les.ovc.me недоступен)
```bash
# На Mac Mini — проверить статус
launchctl list me.ovc.les.pauk
# Вывод: нет PID → туннель не запущен

# Перезапустить через launchd
launchctl stop me.ovc.les.pauk
launchctl start me.ovc.les.pauk

# Или вручную
~/Projects/LES_v2/stop_pauk.command
~/Projects/LES_v2/start_pauk.command

# Проверка с VPS-стороны
ssh root@185.185.71.196 "curl -s http://127.0.0.1:8080/api/health"
```

#### ❌ MLX Host завис (чат возвращает 503)
```bash
# Остановить
~/Projects/LES_v2/stop_mlx.command
sleep 3

# Проверить что процесс умер
ps aux | grep mlx_host

# Перезапустить
~/Projects/LES_v2/start_mlx.command

# Проверка (модели грузятся ~30с)
curl -s http://localhost:8080/api/health
```

#### ❌ Qdrant потерял коллекцию (RAG пустой)
```bash
# Проверить коллекции
curl -s http://localhost:6333/collections | python3 -m json.tool

# Если коллекция есть, но RAG не отвечает — проверить Docker
docker ps | grep qdrant
docker logs les-qdrant --tail 20

# Если данные потеряны — переиндексировать
curl -X POST http://localhost:8050/api/rag/sync/NTD
# Ждать: статус PARSING → INDEXED (~15-30 мин для 800+ файлов)
```

#### ❌ les-proxy в restart loop
```bash
docker logs les-proxy --tail 30
# Частые причины:
# 1. .env не найден → проверить наличие файла
# 2. Qdrant недоступен → docker ps, docker start les-qdrant
# 3. Ошибка кода → git log, git stash, docker compose up -d
```

#### ❌ С.О.В.У.Ш.К.А. падает при запуске
```bash
# На Mac Mini
cd ~/Projects/LES_v2
python3 sovushka_ng.py
# Смотреть traceback — обычно:
# ImportError → pip3 install nicegui httpx
# Connection refused :8050 → убедиться что les-proxy UP
```

#### ❌ VPS-сервис упал (les_proxy / sovushka)
```bash
ssh root@185.185.71.196
systemctl status les_proxy.service
journalctl -u les_proxy.service -n 50
systemctl restart les_proxy.service
```

---

## 6. API REFERENCE

### 6.1. Прокси (порт 8050)
| Endpoint | Метод | Описание | Новое в v2.1 |
|---|---|---|---|
| `/api/health` | GET | Статус бэкенда | — |
| `/api/mode` | GET/POST | Режим РАГ/КОД | — |
| `/api/status` | GET | Ollama + Docker + **proxy секция** | ✅ `proxy.uptime_sec` |
| `/api/settings` | GET/POST | Настройки → .env + restart | — |
| `/api/metrics` | GET | CPU/RAM/RAG/**CRAG v2** | ✅ 3 отдельных rate |
| `/api/diag` | GET | **Полная диагностика 11 чеков** | ✅ Новый |
| `/api/rag/sources` | GET | Папки RAG_Content | — |
| `/api/rag/datasets` | GET/POST | Датасеты | — |
| `/api/rag/datasets/{id}` | DELETE | Удалить датасет | — |
| `/api/rag/datasets` | DELETE | Сброс всех | — |
| `/api/rag/sync/{folder}` | POST | Синк папки | — |
| `/api/rag/upload/{id}` | POST | Загрузка файла | — |
| `/api/jobs` | GET | История jobs | — |
| `/api/chat` | POST | RAG-чат + Т.О.С.К.А. v2 | ✅ `dataset_filter`, `reranker_enabled` |
| `/api/logs/stream` | GET | SSE логи | — |

#### POST /api/chat — расширенное
```json
{
  "question": "Какие требования к вентиляции по СП 60?",
  "dataset_ids": null,
  "dataset_filter": "NTD",
  "reranker_enabled": false
}
```
- `dataset_ids` — список UUID (старый способ)
- `dataset_filter` — **имя папки** из RAG_Content. `"NTD"` → автоматически резолвится в UUID датасета `NTD_Index`
- `reranker_enabled` — `true/false/null`. `null` = берётся из env `RERANKER_ENABLED`. Управляется переключателем в UI чата.

#### GET /api/metrics — структура ответа
```json
{
  "system": {
    "cpu": 23.4, "ram_used": 14.2, "ram_total": 24.0,
    "disk_used": 180, "disk_total": 460, "ollama_ram": 9.3
  },
  "pipeline": {
    "crag_pass_rate": 0.82,
    "crag_verified_rate": 0.82,
    "crag_nodata_rate": 0.12,
    "crag_halluc_rate": 0.06,
    "total_requests": 147,
    "latency_search": [...],
    "latency_gen": [...]
  },
  "rag": { "datasets": 4, "files": 809, "chunks": 1316, "status": "ready" },
  "queue": { "llm_waiting": 0 }
}
```

#### GET /api/diag — структура ответа
```json
{
  "overall": "ok",
  "ok_count": 10, "warn_count": 1, "err_count": 0,
  "total_ms": 3240,
  "timestamp": "2026-05-15T14:30:00",
  "checks": [
    {
      "name": "les-proxy :8050",
      "status": "ok",
      "value": "UP 7200s",
      "expected": "UP",
      "message": "port 8050 | qwen3:14b",
      "latency_ms": 2.1
    }
    // ... 10 остальных чеков
  ]
}
```

### 6.2. MLX Host (порт 8080)
| Endpoint | Метод | Описание |
|---|---|---|
| `/api/health` | GET | Статус + обе модели + TTL |
| `/api/ps` | GET | Ollama-совместимый список загруженных моделей |
| `/api/generate` | POST | Ollama-формат |
| `/v1/chat/completions` | POST | OpenAI-формат |
| `/v1/models` | GET | Список моделей |
| `/api/embeddings` | POST | Ollama эмбеддинги |
| `/v1/embeddings` | POST | OpenAI эмбеддинги |
| `/api/validate` | POST | Т.О.С.К.А. v2: VERIFIED/NO_DATA/HALLUCINATION |
| `/api/switch_model` | POST | Смена модели без рестарта |

#### GET /api/ps — пример ответа
```json
{
  "models": [
    {
      "name": "mlx-community/Qwen3-14B-4bit",
      "model": "mlx-community/Qwen3-14B-4bit",
      "details": {"family": "qwen3"}
    }
  ]
}
```
Используется `proxy_server.py` и `metrics_collector.py` для опроса статуса загруженных движков.

---

## 7. ТЕХНИЧЕСКИЕ ВОПРОСЫ И РЕШЕНИЯ

### 7.1. Реранкер — статус и архитектура

**Статус:** ✅ Реализован в v2.6, управляется переключателем в UI чата.

**Архитектура (batch-режим):**
- Qdrant возвращает top-8 чанков
- Реранкер формирует **один** LLM-запрос с 8 чанками → получает JSON-массив оценок [0..10]
- Топ-5 по оценке идут в контекст генерации

**Файл:** `backend/reranker.py`, класс `Reranker(mode="batch")`

**Когда включать:**
- Датасет > 5000 чанков
- Жалобы на нерелевантные ответы при наличии данных
- Multi-document поиск по нескольким датасетам

**Производительность:** batch-режим = 1 LLM-вызов (~5с) vs sequential = 20 вызовов (~100с).

**Управление:**
- UI: переключатель «Реранкер» в панели настроек чата
- API: `"reranker_enabled": true` в теле `/api/chat`
- Default: `RERANKER_ENABLED=false` в `.env`

### 7.2. Parquet для хранения таблиц

**Короткий ответ:** нужен, добавить в `converter.py` как альтернативный output.

**Проблема сейчас:** XLSX/CSV конвертируются в Markdown-таблицы. При большом объёме (сметы, спецификации на 1000+ строк) Markdown ломает структуру, токены тратятся на разметку, поиск по числам деградирует.

**Решение — Parquet-пайплайн:**
```python
# В converter.py — добавить ветку для табличных данных
import pyarrow as pa
import pyarrow.parquet as pq

def convert_xlsx_to_parquet(path: Path) -> Path:
    """XLSX → Parquet для числовых таблиц (сметы, спецификации)."""
    df = pd.read_excel(path)
    out = path.with_suffix('.parquet')
    pq.write_table(pa.Table.from_pandas(df), out)
    return out

# В qdrant_adapter.py — при поиске по Parquet:
# 1. Загружаем Parquet в pandas
# 2. Векторизуем строки как "{колонка}: {значение}" (структурный чанк)
# 3. Payload содержит ссылку на Parquet + row_index для точного извлечения
```

**Что даёт:**
- Сжатие ~5-10x против CSV
- Типизированные числа (не строки) — точный поиск по суммам, кол-вам
- Быстрая фильтрация без LLM для табличных запросов типа "все позиции > 100 шт."
- Интеграция с AG Grid в С.О.В.У.Ш.К.А. напрямую

**Приоритет:** 🟠 v2.2, после стабилизации текущего стека. Зависимости: `pyarrow`, `pandas` (уже есть).

### 7.3. Логика в MLX — что можно реализовать?

**Qwen3 на MLX уже поддерживает:**
- Thinking mode (`/think` в промпте) — развёрнутое рассуждение перед ответом
- Function calling — структурированный JSON output
- Tool use — вызов функций из промпта
- Batch inference — несколько запросов параллельно
- Streaming — токен за токеном через SSE

**Что реализуемо прямо сейчас в mlx_host.py:**

```python
# 1. Structured output (JSON schema enforcement)
# Qwen3 умеет следовать JSON schema без fine-tuning
# Промпт: "Отвечай ТОЛЬКО JSON по схеме: {...}"
# Использование: форма запроса «Спецификация» → валидный JSON гарантирован

# 2. Self-consistency (3 прогона → мажоритарное голосование)
# При HALLUCINATION запускать 2 повторных прогона → если 2/3 VERIFIED → принять
async def validate_with_consistency(question, answer, context, n=3):
    results = await asyncio.gather(*[validate_once(...) for _ in range(n)])
    return max(set(results), key=results.count)

# 3. Chain-of-thought для сложных инженерных запросов
# Промпт: "<think>\n" → Qwen3 даёт reasoning block → потом ответ
# Parsing: отделяем <think>...</think> от финального ответа

# 4. Gemma 4 26B как VLM — анализ PDF-скриншотов
# mlx_lm.generate() с image input → описание листа чертежа → чанк в Qdrant
```

**Для Gemma 4:**
- Лучше для reasoning и зрения (VLM)
- Хуже для кода
- Рекомендуется для: PDF-листы с чертежами, таблицы-изображения, OCR-ассист

**Рекомендация по распределению:**
| Задача | Модель |
|---|---|
| RAG-ответ, спецификации | Qwen3-14B |
| Т.О.С.К.А. валидация | Qwen3-4B |
| Код, скрипты | Qwen2.5-Coder-14B (Ollama) |
| VLM: PDF-листы, чертежи | Gemma 4 26B |
| Реранкинг | Qwen3-4B (повторное использование) |

### 7.4. Когда переходить к работе с почтой (Е.Ж.И.К.)?

**Текущая готовность:**
- `converter.py` уже поддерживает **EML/MSG** через `extract-msg` и `email` stdlib
- Pipeline: `.eml` → `converter.py` → Markdown (тема + тело + вложения) → Qdrant
- Тест по программе испытаний: статус ⬜ (не проверен)

**Что нужно для полноценного Е.Ж.И.К.:**
```
1. IMAP-коннектор (imaplib или aioimaplib)
   → папки: Входящие, Отправленные, Проект X
   → фильтры: отправитель, тема, дата, вложения
   → инкрементальная загрузка (только новые / изменённые)

2. Attachment pipeline
   → PDF/DOCX вложения → через существующий ConverterRouter
   → Изображения → через Gemma 4 VLM (если нужно)

3. Thread reconstruction
   → сшивание цепочек писем по Message-ID / In-Reply-To
   → один чанк = одна переписка (не одно письмо)

4. Индексация в С.А.М.О.В.А.Р.
   → dataset_id = "MAIL_Index" (или по проектам)
   → payload: {from, to, date, subject, thread_id}
```

**Рекомендуемый порядок:**
1. ✅ Сначала: протестировать EML/MSG через `/api/rag/sync` на реальных письмах
2. ✅ Затем: добавить `/api/mail/connect` с IMAP credentials
3. ✅ Потом: Folder Watcher для автосинка почты

**Ориентировочный старт:** после стабилизации NTD индекса и реализации Folder Watcher (v2.1). **Срок: v2.2**.

---

## 8. ПРОГРАММА ИСПЫТАНИЙ

**Версия:** v2.4 | **Дата:** 18.05.2026

### 8.1. Сводная таблица v2.4

| Модуль | Тестов | ✅ OK | ⬜ Не тест. | ❌ Failed | % |
|---|---|---|---|---|---|
| Л.Е.С. (Proxy) | 6 | 5 | 1 | 0 | 83% |
| С.А.М.О.В.А.Р. (RAG) | 8 | 6 | 2 | 0 | 75% |
| Т.О.С.К.А. (CRAG) | 5 | 5 | 0 | 0 | 100% |
| С.О.В.У.Ш.К.А. v5.0 (NiceGUI) | 14 | 14 | 0 | 0 | 100% |
| П.А.У.К. (сеть) | 6 | 5 | 1 | 0 | 83% |
| Ресурсы | 5 | 3 | 2 | 0 | 60% |
| **ИТОГО** | **44** | **38** | **6** | **0** | **86%** |

### 8.2. Детальные чеки

#### Л.Е.С. (Proxy v2.3)
| # | Проверка | Ожидание | Статус |
|---|---|---|---|
| 1.1 | `GET /api/health` | `{"status":"ok"}` | ✅ |
| 1.2 | `GET /api/metrics` crag_verified_rate | float 0..1 | ✅ |
| 1.3 | `GET /api/status` proxy.uptime_sec | int > 0 | ✅ |
| 1.4 | `GET /api/diag` — 11 чеков | overall: ok/warn/err | ✅ |
| 1.5 | `POST /api/chat` dataset_filter | Резолв NTD → UUID | ✅ |
| 1.6 | No-Cache заголовки | Cache-Control: no-store | ⬜ |

#### Т.О.С.К.А. (CRAG v2.5)
| # | Проверка | Статус |
|---|---|---|
| 3.1 | Чат с нормативом → VERIFIED | ✅ |
| 3.2 | Нерелевантный вопрос → NO_DATA | ✅ |
| 3.3 | Источники в ответе | ✅ |
| 3.4 | Статус UNKNOWN не возникает при штатной работе | ✅ (`enable_thinking=False` + `max_tokens=64`) |
| 3.5 | Ошибка/таймаут валидатора → UNKNOWN, не VERIFIED | ✅ (default `"UNKNOWN"`) |
| 3.6 | HTTP != 200 от валидатора → NO_DATA | ✅ |
| 3.7 | `crag_stats["verified"]` не растёт при UNKNOWN | ✅ |
| 3.8 | Нагрузка: 5 параллельных запросов | ⬜ |

#### С.О.В.У.Ш.К.А. v5.0
| # | Проверка | Статус |
|---|---|---|
| 4.1 | Запуск `python3 sovushka_ng.py` без ошибок | ✅ |
| 4.2 | Вкладка AI ЧАТ — форма запроса открывается | ✅ |
| 4.3 | Формат «Спецификация» → таблица с данными | ✅ |
| 4.4 | Формат «Mermaid» → диаграмма рендерится | ✅ |
| 4.5 | Вкладка ДИАГНОСТИКА → кнопка запускает чеки | ✅ |
| 4.6 | Mermaid-топология окрашивается по результатам | ✅ |
| 4.7 | Загрузка образца CSV/JSON/XLSX | ✅ |
| 4.8 | Совместимость Python 3.9 | ✅ |
| 4.9 | Ответ чата не обрезается (был лимит 600 симв.) | ✅ |
| 4.10 | Тикер прогресса во время генерации | ✅ |
| 4.11 | Активная вкладка сохраняется при реконнекте | ✅ |
| 4.12 | Светлая тема — Quasar-компоненты читаемы | ✅ |
| 4.13 | Тема (тёмная/светлая) сохраняется при WebSocket-реконнекте | ✅ (`app.storage.user["dark_theme"]`) |
| 4.14 | `--dim` в светлой теме: контраст ≥ 4.5:1 (WCAG AA) | ✅ (`#424a53`, 7:1) |
| 4.15 | П.Р.О.Р.А.Б. timer не вызывает clear() без изменений — вкладки стабильны | ✅ (`_prev_render`) |
| 4.16 | Двойная отправка запроса заблокирована (`_sending` guard) | ✅ |
| 4.17 | История чата загружается после рестарта процесса | ✅ (`/api/chat/history`) |
| 4.18 | Роль `user` — видна только вкладка «AI ЧАТ» | ✅ |
| 4.19 | В.О.Л.К.: ключ с истёкшим `expires_at` отклоняется | ✅ |
| 4.20 | В.О.Л.К.: повторный вход с другого браузера — 403 (device_bound) | ✅ |
| 4.21 | В.О.Л.К.: сброс привязки устройства через кнопку 📱✕ | ✅ |
| 4.22 | Вопрос > 4000 симв. → 422 (валидация pydantic) | ✅ |
| 4.23 | Rate limit: 3-й одновременный запрос → 429 | ✅ |

### 8.3. Нерешённые задачи (бэклог испытаний)
| Задача | Приоритет |
|---|---|
| Нагрузочный тест: 5 параллельных чат-запросов | 🔴 |
| Тест EML/MSG парсинга на реальных письмах | 🔴 |
| Latency чата под нагрузкой (< 5 сек) | 🟠 |
| Swap = 0 при полной нагрузке | 🟠 |
| Qdrant fallback при падении во время парсинга | 🟠 |
| Тест Caddy HTTPS les.ovc.me | ✅ |
| SSH туннель: Mac Mini → VPS (Qdrant + MLX) | ✅ |
| В.О.Л.К.: auto-bypass ZeroTier IP (10.x.x.x) | ✅ |
| В.О.Л.К.: ключи admin/user в SQLite | ✅ |
| Нагрузочный тест П.А.У.К. (keepalive туннеля) | 🟡 |
| No-Cache заголовки в прокси | ⚪ |

---

## 9. ROADMAP

### ✅ v2.0 Core (10.05.2026) — Выполнено
- FastAPI + Qdrant + LlamaIndex — полный рефакторинг
- ConverterRouter: PDF/DOCX/EML/XLSX → Markdown
- Structure-Aware Chunking (MarkdownNodeParser + SentenceSplitter)
- Т.О.С.К.А. v2: нативный CRAG пайплайн
- SQLite метаданные, UUID-датасеты, Delta-Sync
- 807 файлов, 1316 чанков, 0 рестартов, Swap=0

### ✅ v2.1 (15.05.2026)
- **С.О.В.У.Ш.К.А. v4.0 NiceGUI** — полный переезд с HTML/JS на Python
- Форма запроса: 8 форматов выдачи (текст/спецификация/схема/структура/таблица/Mermaid/SVG/по образцу)
- AG Grid везде: датасеты, jobs, таблицы ответов, спецификации
- Вкладка ДИАГНОСТИКА: 11 чеков, Mermaid-топология, лог
- `/api/diag` — новый эндпоинт полной диагностики
- Т.О.С.К.А.: три счётчика (VERIFIED/NO_DATA/HALLUCINATION)
- `dataset_filter` в `/api/chat` — фильтр по имени папки
- Фикс Python 3.9 совместимости (`from __future__ import annotations`)

### ✅ v2.2 (17–18.05.2026)
- **С.О.В.У.Ш.К.А. v5.0 (Модульная архитектура)**
- Монолит `sovushka_ng.py` (2300 строк) разбит на пакет `sovushka/`
- Нативная авторизация (В.О.Л.К.) без инъекций `<script>`
- Исправлены проблемы с блокировкой Event Loop (httpx Client) и зависанием загрузки (CDN favicon)
- Таблицы переведены на `ui.table` для совместимости с NiceGUI 3.6+
- Полный отказ от Ollama-fallback, переход на MLX как единственный LLM-бэкенд
- Персистентность истории чатов (`chat_history` в `les_meta.db`)

### ✅ v2.3 (18.05.2026)
- **Т.О.С.К.А. UNKNOWN → исправлен** — `enable_thinking=False` + `max_tokens` 10→64 в `/api/validate`
- **Чат: убрана обрезка ответа** — лимит 600 символов снят, ответ показывается полностью
- **Чат: тикер прогресса** — `⟳ Генерирую... Nс` с анимацией пока ИИ обрабатывает запрос
- **Чат: персистентность вкладки** — `app.storage.user["last_tab"]` переживает WebSocket-реконнект
- **Светлая тема: полный фикс** — `Quasar.Dark.set()` переключает все компоненты, `--pauk` обновляется, контрасты WCAG AA
- `apply_chat_template` в `MLXMemoryManager` поддерживает `enable_thinking=False` с fallback

### ✅ v2.4 (18.05.2026)
- **П.А.У.К. — запущен** — VPS Debian 13 (`185.185.71.196`), Caddy + Let's Encrypt, `les.ovc.me` live
- **SSH reverse tunnel** — Mac Mini → VPS: порты 6333 (Qdrant) и 8080 (MLX), launchd `me.ovc.les.pauk` (выведен из эксплуатации в v2.8, plist сохранён как резерв)
- **В.О.Л.К. — ключи live** — SQLite `auth_keys`, admin/user роли, auto-bypass для ZeroTier IP
- **VPS systemd** — `les_proxy.service` + `sovushka.service` с `EnvironmentFile=/root/les_v2/.env`
- **С.О.В.У.Ш.К.А.: тема переживает реконнект** — состояние тёмной/светлой темы перенесено из локального dict в `app.storage.user["dark_theme"]`; при WebSocket-реконнекте светлая тема восстанавливается через `ui.timer(0.1, once=True)`
- **С.О.В.У.Ш.К.А.: `--dim` в светлой теме** — цвет исправлен `#656d76` → `#424a53` (контраст 7:1, WCAG AA)
- **П.Р.О.Р.А.Б.: стабилизация DOM** — `mlx_models_container.clear()` и `docker_container.clear()` вызываются только при изменении данных (`_prev_render` dict); устранено хаотичное переключение вкладок

### ✅ v2.5 (18.05.2026) — Текущая
- **Т.О.С.К.А.: критический баг исправлен** — `crag_status` по умолчанию `"UNKNOWN"` вместо `"VERIFIED"`; ошибки/таймауты валидатора и ответы HTTP != 200 больше не засчитываются как «проверено»
- **Т.О.С.К.А.: статистика** — `crag_stats["verified"]` растёт только при явном `VERIFIED`; всё остальное (UNKNOWN, NO_DATA) идёт в `no_data`/`crag_fail`
- **MLX: `_get_engine()` точное совпадение** — убран fuzzy-матч `"4B" in model_name`; маршрутизация только по `model_name == VAL_MODEL`
- **С.О.В.У.Ш.К.А.: защита от двойной отправки** — `_sending` guard + `props("disabled")` на input и кнопках во время запроса (был баг: `"disable"` → исправлено `"disabled"`)
- **С.О.В.У.Ш.К.А.: история чатов** — загружается из `GET /api/chat/history?limit=40` при первом открытии страницы; выживает рестарт процесса
- **В.О.Л.К.: типы ключей** — `permanent` (∞) и `1` (1 день), поле `expires_at` в `auth_keys`
- **В.О.Л.К.: привязка к устройству** — browser fingerprint (userAgent + экран + таймзона + canvas); `device_fingerprint` в SQLite; кнопка 📱✕ для сброса
- **В.О.Л.К.: разделение ролей UI** — `user` видит только вкладку «AI ЧАТ»; все остальные вкладки скрыты; `_default_tab = tab_chat`
- **Безопасность**: rate limit `llm_queue_size >= 2 → 429`; валидация вопроса ≤ 4000 симв.; path traversal защита на sync-папку; system prompt hardened
- **`les.command`** — единый скрипт управления (start/stop/restart/sovushka/status + интерактивное меню)
- **`bg_loop` стабилизация** — каждый тик обёрнут в `try/except`; падение одного рефреша не роняет весь цикл

### ✅ v2.6 (19.05.2026)
- **Модели обновлены:** LLM `Qwen3-14B` → `Qwen3.5-9B-MLX-4bit` (-3 GB RAM); валидатор → `Qwen3-4B-Instruct-2507-4bit`
- **mlx_host.py читает .env самостоятельно** — `os.environ.setdefault()` при старте, независим от оболочки запуска
- **MLX Watchdog** — фоновый процесс в `les.command`, автоперезапуск MLX через 30с при OOM kill
- **Docker mem_limit:** `proxy=512m`, `qdrant=1g` — защита от вытеснения MLX из RAM
- **Реранкер batch-режим:** top_k 20→8, mode sequential→batch (1 вызов вместо 20, ~100с→~5с)
- **Переключатель реранкера в UI чата** — по умолчанию выключен (`RERANKER_ENABLED=false`)

### 🛠 v2.7 (Краткосрочно)
| Задача | Описание |
|---|---|
| **Folder Watcher** | Автосинк новых файлов из RAG_Content/ |
| **Retry-логика** | Graceful fallback при занятости MLX |
| **Qdrant fallback** | Обработка ошибок Qdrant при парсинге документов |
| **Parquet пайплайн** | Табличные данные в Parquet вместо Markdown |
| **Е.Ж.И.К. v1** | Тест EML/MSG на реальных письмах → IMAP коннектор |
| **chunk_count** | Исправить колонку в SQLite (сейчас всегда 0) |

### 🔮 v2.6+ (Среднесрочно)
| Задача | Описание |
|---|---|
| **В.О.Л.К. v2** | JWT RBAC, ролевые бейджи, маскирование .env |
| **С.У.Х.А.Р.И.К. v2** | Снапшоты Qdrant, инкрементальные бэкапы |
| **VLM пайплайн** | Gemma 4: PDF-листы → скриншоты → описание → Qdrant |
| **Deep BIM Linking** | Связь ответов LLM с ExpressID в IFC |
| **Multi-project** | Изоляция проектов и датасетов |
| **Voice Control** | Whisper для голосового ввода |

---

## 10. РАБОТА С AI-АССИСТЕНТАМИ

### Roo Code (VS Code Extension)
```
Provider:  OpenAI Compatible
Base URL:  http://localhost:8080/v1
API Key:   any
Model:     mlx-community/Qwen3-14B-4bit
```
Для кода лучше переключить на `Qwen2.5-Coder` или `Qwen3-14B`.

### Aider
```bash
cd ~/Projects/LES_v2
/Users/ovc/Library/Python/3.9/bin/aider \
  --model ollama_chat/qwen2.5-coder:14b \
  --openai-api-base http://localhost:11434/v1 \
  --yes-always proxy_server.py backend/qdrant_adapter.py \
  --message "Fix the retry logic in chat endpoint"
```
**Правила:**
- Указывать ≤ 3–4 файла
- EN промпт для кода, RU для документации
- После правок `.py` → `docker compose restart proxy`
- `git status` перед стартом, `git checkout <commit> -- <file>` для отката

### Claude (Клодыч)
Работает через claude.ai. Контекст между сессиями — через `SESSION_SUMMARY.md`.  
Обновлять `SESSION_SUMMARY.md` в конце каждой сессии!

---

## ПРИЛОЖЕНИЕ А — Текущее состояние индексов (18.05.2026)

```
Docker:       les-proxy UP, les-qdrant UP
MLX Host:     порт 8080, Qwen3-14B + Qwen3-4B + bge-m3
NTD_Index:    801 файл — уточнить статус после реиндекса
CLAUDE_Index: 4 файла, INDEXED
QWEN_Index:   1 файл, INDEXED
Чанков:       ~1316 (данные до реиндекса)
```

> Актуальное состояние — через UI вкладка П.Р.О.Р.А.Б. или:
> ```bash
> curl -s http://localhost:8050/api/metrics | python3 -c \
>   "import sys,json; m=json.load(sys.stdin)['rag']; print(f\"{m['files']} файлов, {m['chunks']} чанков\")"
> ```

**После правок — что перезапускать:**
| Изменён файл | Команда |
|---|---|
| `proxy_server.py` | `docker compose restart proxy` |
| `mlx_host.py` | `./les.command stop && ./les.command start` |
| `sovushka/**` | `./les.command sovushka` |
| `.env` | `docker compose restart proxy && ./les.command stop && ./les.command start` |

## ПРИЛОЖЕНИЕ Б — Быстрые команды

```bash
# Запустить всё (включает watchdog для MLX)
./les.command start

# Остановить всё
./les.command stop

# Статус
./les.command status

# Перезапустить только UI
./les.command sovushka

# Статус одной строкой (низкоуровневый)
docker ps --format "{{.Names}}:{{.Status}}" && curl -s localhost:8050/api/health && curl -s localhost:8080/api/health

# Диагностика
curl -s localhost:8050/api/diag | python3 -c "import sys,json; d=json.load(sys.stdin); [print(f\"{r['status'].upper():6} {r['name']:30} {r['value']}\") for r in d['checks']]"

# Логи в реальном времени
docker logs -f les-proxy 2>&1 | grep -E "\[CHAT\]|\[PARSE\]|\[DIAG\]|\[ERROR\]"

# Перезапуск прокси
docker compose restart proxy

# Остановить всё
./stop_mlx.command && docker compose down
```

---

📅 **Документ актуализирован:** 19.05.2026 — v2.6: модели Qwen3.5-9B + Qwen3-4B-2507, watchdog, mem_limit, реранкер batch-режим, переключатель в UI  
✍️ **Авторы:** Claude (Клодыч) · Qwen (Кен) · Gemini (Панорамыч)
