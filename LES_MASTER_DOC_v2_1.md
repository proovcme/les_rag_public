# 🦉 Л.Е.С. — Локальная Единая Система
## Мастер-документ v2.1 | 15.05.2026

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

### Ключевые изменения v2.0 → v2.1 (текущая)
- С.О.В.У.Ш.К.А. переехала на **NiceGUI** (порт 8051) — единая Python-кодовая база
- Форма запроса: 8 форматов выдачи (текст / спецификация / схема / таблица / Mermaid / SVG / по образцу)
- Вкладка диагностики с Mermaid-топологией и автоматическими чеками
- `/api/diag` — новый эндпоинт полной диагностики (11 чеков)
- Т.О.С.К.А. v2: три независимых счётчика (VERIFIED / NO_DATA / HALLUCINATION)
- `dataset_filter` в `/api/chat` — фильтр по имени папки без UUID

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
| **В.О.Л.К.** | Внутренний Охранный Локальный Контур | RBAC, JWT-аутентификация | 🔨 В разработке |
| **С.У.Х.А.Р.И.К.** | Система Управления Холодными Архивами и Резервными Источниками Комплекса | Снапшоты Qdrant, бэкапы | 🔨 В разработке |
| **Е.Ж.И.К.** | *(расшифровка уточняется)* | Обработка почты IMAP/EML | ⏳ Запланирован |
| **П.А.У.К.** | Периметровый Автономный Узел Коммуникаций | Сетевой контур: ZeroTier P2P + DNS + SSL | 🆕 В проектировании |

### П.А.У.К. — детали
**Состав:**
- **ZeroTier** — текущий P2P транспорт (Network `8d1c312afa249de4`, подсеть `10.195.146.0/24`)
- **Caddy** (не Cuddy) — reverse proxy с автоматическим HTTPS
- **DNS** — домен `les.ovc.me` → маршрутизация сервисов
- **SSL** — Let's Encrypt через Caddy ACME

**Целевая топология П.А.У.К.:**
```
Интернет → les.ovc.me (DNS) → ZeroTier → Caddy :443
                                               ├── / → С.О.В.У.Ш.К.А. :8051
                                               ├── /api → Л.Е.С. прокси :8050
                                               └── /qdrant → Qdrant :6333 (только внутри)
```

**Планируемый `Caddyfile`:**
```caddyfile
les.ovc.me {
    reverse_proxy /api/* localhost:8050
    reverse_proxy /* localhost:8051
    tls {
        protocols tls1.2 tls1.3
    }
}
```

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
├── MLX Native Host (FastAPI, порт 8080) — LLM + Embeddings на Metal
│   ├── Qwen3-14B-4bit   (main, RAG + Roo Code, TTL 300с)
│   ├── Qwen3-4B-4bit    (val, Т.О.С.К.А. валидатор, TTL 120с)
│   └── bge-m3           (embed, постоянно в памяти)
│
├── Ollama          (порт 11434) — резервный LLM-сервер
│   ├── qwen3:14b
│   └── bge-m3:latest
│
└── С.О.В.У.Ш.К.А. (NiceGUI, порт 8051) — UI v5.0
    ├── ОБЗОР        — карта модулей, стек
    ├── С.А.М.О.В.А.Р. — AG Grid датасетов, jobs
    ├── П.Р.О.Р.А.Б.   — метрики, MLX, Docker, Т.О.С.К.А. v2
    ├── AI ЧАТ       — чат + Форма запроса (8 форматов)
    ├── ГРАФ         — Mermaid редактор + превью
    └── ДИАГНОСТИКА  — 11 чеков, topology map, лог
```

### 3.2. Поток данных (RAG)
```
Запрос → /api/chat
  → dataset_filter resolve (имя → UUID)
  → Qdrant retrieve (bge-m3 embeddings, top-k=5)
  → Chunks → Prompt building
  → MLX Host / Ollama (Qwen3-14B)
  → Т.О.С.К.А. /api/validate (Qwen3-4B)
      VERIFIED → ответ
      NO_DATA  → "нет данных"
      HALLUCINATION → заблокировано
  → crag_stats обновляются
  → Ответ клиенту
```

### 3.3. Структура файлов проекта
```
LES_v2/
├── proxy_server.py           # FastAPI ядро (848 строк, v2.1)
├── sovushka_ng.py            # Точка входа С.О.В.У.Ш.К.А. v5.0 (~90 строк)
├── sovushka/                 # Модульный пакет UI (страницы, компоненты, стейт)
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
    chunk_count INTEGER
);
CREATE TABLE documents (
    id TEXT PRIMARY KEY,
    dataset_id TEXT REFERENCES datasets(id),
    file_name TEXT,
    content TEXT              -- Markdown после конвертации
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
| Устройство | Роль | IP | ОС |
|---|---|---|---|
| Mac Mini M4 / 24 GB | Сервер Л.Е.С. | 10.195.146.98 | macOS |
| MacBook Air | Клиент / управление | 10.195.146.176 | macOS |
| Lenovo Legion | Клиент / управление | 10.195.146.20 | Windows 11 |

ZeroTier Network: `8d1c312afa249de4` | UDP 9993 | P2P

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
| main_engine | `mlx-community/Qwen3-14B-4bit` | 300с | RAG + Roo Code |
| val_engine | `mlx-community/Qwen3-4B-4bit` | 120с | Т.О.С.К.А. валидация |
| embed | `bge-m3` | ∞ | Эмбеддинги (постоянно) |

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

#### Шаг 2. Скачать модели Ollama
```bash
ollama pull qwen3:14b
ollama pull qwen2.5-coder:14b
ollama pull bge-m3:latest
# Проверка
ollama list
```

#### Шаг 3. Настроить `.env`
```env
# Режим MLX (рекомендуется)
LLM_MODEL=mlx-community/Qwen3-14B-4bit
EMBED_MODEL=bge-m3
OLLAMA_URL=http://host.docker.internal:8080

# Режим Ollama (резервный)
# LLM_MODEL=qwen3:14b
# EMBED_MODEL=bge-m3:latest
# OLLAMA_URL=http://host.docker.internal:11434

MLX_MODEL=mlx-community/Qwen3-14B-4bit
MLX_VAL_MODEL=mlx-community/Qwen3-4B-4bit
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

### 5.6. П.А.У.К. — настройка Caddy + SSL (будущее)
```bash
# Установить Caddy
brew install caddy

# Caddyfile (~/Projects/LES_v2/Caddyfile)
cat > Caddyfile << 'EOF'
les.ovc.me {
    reverse_proxy /api/* localhost:8050
    reverse_proxy /* localhost:8051
}
EOF

# Запустить
caddy run --config Caddyfile

# Автозапуск
brew services start caddy
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
| `/api/chat` | POST | RAG-чат + Т.О.С.К.А. v2 | ✅ `dataset_filter` |
| `/api/logs/stream` | GET | SSE логи | — |

#### POST /api/chat — расширенное
```json
{
  "question": "Какие требования к вентиляции по СП 60?",
  "dataset_ids": null,
  "dataset_filter": "NTD"
}
```
- `dataset_ids` — список UUID (старый способ)
- `dataset_filter` — **имя папки** из RAG_Content (новый, удобный). `"NTD"` → автоматически резолвится в UUID датасета `NTD_Index`

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
| `/api/generate` | POST | Ollama-формат |
| `/v1/chat/completions` | POST | OpenAI-формат |
| `/v1/models` | GET | Список моделей |
| `/api/embeddings` | POST | Ollama эмбеддинги |
| `/v1/embeddings` | POST | OpenAI эмбеддинги |
| `/api/validate` | POST | Т.О.С.К.А. v2: VERIFIED/NO_DATA/HALLUCINATION |
| `/api/switch_model` | POST | Смена модели без рестарта |

---

## 7. ТЕХНИЧЕСКИЕ ВОПРОСЫ И РЕШЕНИЯ

### 7.1. Нужен ли реранкер?

**Короткий ответ:** да, на этапе 2.2, но не сейчас.

**Детали:**  
Текущий пайплайн: `bge-m3` → top-k=5 чанков по косинусному сходству → Qwen3.  
Реранкер (cross-encoder) улучшает **точность релевантности** за счёт более дорогого попарного сравнения.

**Когда реранкер даст результат:**
- Индекс > 5000 чанков (сейчас ~1316 — ещё рано)
- Начнутся жалобы на нерелевантные ответы при наличии данных в индексе
- Появится multi-document поиск по нескольким датасетам

**Варианты реализации:**
```python
# Вариант 1: BGE Reranker (MLX-native, рекомендуется)
# mlx-community/bge-reranker-v2-m3-4bit
# Встроить в qdrant_adapter.py: retrieve() → rerank() → top-3

# Вариант 2: Qwen3-4B как реранкер (уже есть в памяти!)
# Промпт: "Оцени релевантность чанка вопросу. Ответь: RELEVANT / NOT_RELEVANT"
# Это уже частично делает Т.О.С.К.А. на выходе, но можно сдвинуть на вход

# Вариант 3: LlamaIndex cross-encoder (CPU)
from llama_index.postprocessor import SentenceTransformerRerank
reranker = SentenceTransformerRerank(model="cross-encoder/ms-marco-MiniLM-L-6-v2", top_n=3)
```

**Рекомендация:** начать с Qwen3-4B как реранкером на входе — он уже загружен, не требует новых зависимостей. Промпт отдельным вызовом перед генерацией.

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

**Версия:** v2.1 | **Дата:** 15.05.2026

### 8.1. Сводная таблица v2.1

| Модуль | Тестов | ✅ OK | ⬜ Не тест. | ❌ Failed | % |
|---|---|---|---|---|---|
| Л.Е.С. (Proxy) | 6 | 5 | 1 | 0 | 83% |
| С.А.М.О.В.А.Р. (RAG) | 8 | 6 | 2 | 0 | 75% |
| Т.О.С.К.А. (CRAG) | 5 | 4 | 1 | 0 | 80% |
| С.О.В.У.Ш.К.А. v5.0 (NiceGUI) | 8 | 7 | 1 | 0 | 87% |
| П.А.У.К. (сеть) | 4 | 2 | 2 | 0 | 50% |
| Ресурсы | 5 | 3 | 2 | 0 | 60% |
| **ИТОГО** | **36** | **27** | **9** | **0** | **75%** |

### 8.2. Детальные чеки

#### Л.Е.С. (Proxy v2.1)
| # | Проверка | Ожидание | Статус |
|---|---|---|---|
| 1.1 | `GET /api/health` | `{"status":"ok"}` | ✅ |
| 1.2 | `GET /api/metrics` crag_verified_rate | float 0..1 | ✅ |
| 1.3 | `GET /api/status` proxy.uptime_sec | int > 0 | ✅ |
| 1.4 | `GET /api/diag` — 11 чеков | overall: ok/warn/err | ✅ |
| 1.5 | `POST /api/chat` dataset_filter | Резолв NTD → UUID | ✅ |
| 1.6 | No-Cache заголовки | Cache-Control: no-store | ⬜ |

#### С.О.В.У.Ш.К.А. v5.0
| # | Проверка | Статус |
|---|---|---|
| 4.1 | Запуск `python3 sovushka_ng.py` без ошибок | ✅ (после фикса py39) |
| 4.2 | Вкладка AI ЧАТ — форма запроса открывается | ✅ |
| 4.3 | Формат «Спецификация» → AG Grid с данными | ✅ |
| 4.4 | Формат «Mermaid» → диаграмма рендерится | ✅ |
| 4.5 | Вкладка ДИАГНОСТИКА → кнопка запускает чеки | ✅ |
| 4.6 | Mermaid-топология окрашивается по результатам | ✅ |
| 4.7 | Загрузка образца CSV/JSON/XLSX | ✅ |
| 4.8 | Совместимость Python 3.9 | ✅ (from __future__) |

### 8.3. Нерешённые задачи (бэклог испытаний)
| Задача | Приоритет |
|---|---|
| Нагрузочный тест: 5 параллельных чат-запросов | 🔴 |
| Тест EML/MSG парсинга на реальных письмах | 🔴 |
| Latency чата под нагрузкой (< 5 сек) | 🟠 |
| Swap = 0 при полной нагрузке | 🟠 |
| Тест Caddy HTTPS les.ovc.me | 🟡 |
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

### ✅ v2.2 (17.05.2026) — Текущая
- **С.О.В.У.Ш.К.А. v5.0 (Модульная архитектура)**
- Монолит `sovushka_ng.py` (2300 строк) разбит на пакет `sovushka/`
- Нативная авторизация (В.О.Л.К.) без инъекций `<script>`
- Исправлены проблемы с блокировкой Event Loop (httpx Client) и зависанием загрузки (CDN favicon)
- Таблицы переведены на `ui.table` для совместимости с NiceGUI 3.6+

### 🛠 v2.2 (Краткосрочно)
| Задача | Описание |
|---|---|
| **Folder Watcher** | Автосинк новых файлов из RAG_Content/ |
| **Retry-логика** | Graceful fallback при занятости Ollama |
| **Parquet пайплайн** | Табличные данные в Parquet вместо Markdown |
| **Реранкер** | Qwen3-4B как cross-encoder перед генерацией |
| **Е.Ж.И.К. v1** | Тест EML/MSG на реальных письмах → IMAP коннектор |
| **П.А.У.К.** | Caddy + les.ovc.me + SSL (Let's Encrypt) |
| **chunk_count** | Исправить колонку в SQLite (сейчас всегда 0) |

### 🔮 v2.3+ (Среднесрочно)
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

## ПРИЛОЖЕНИЕ А — Текущее состояние индексов (15.05.2026)

```
Docker:       les-proxy UP, les-qdrant UP
MLX Host:     порт 8080, Qwen3-14B + Qwen3-4B + bge-m3
NTD_Index:    801 файл — уточнить статус после реиндекса
CLAUDE_Index: 4 файла, INDEXED
QWEN_Index:   1 файл, INDEXED
Чанков:       ~1316 (данные до реиндекса)
```

## ПРИЛОЖЕНИЕ Б — Быстрые команды

```bash
# Запустить всё
./start_mlx.command && docker compose up -d && python3 sovushka_ng.py

# Статус одной строкой
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

📅 **Документ актуализирован:** 15.05.2026 — v2.1 NiceGUI Edition  
✍️ **Авторы:** Claude (Клодыч) · Qwen (Кен) · Gemini (Панорамыч)
