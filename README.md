# 🌲 Л.Е.С. — Локальная Экспертная Система

**Локальная RAG-система для работы с нормативной документацией.**  
Работает полностью офлайн на Apple Silicon (Mac Mini M4). Никакие данные не покидают локальную сеть.

---

## Что это

Л.Е.С. — это система для поиска и анализа технических норм, СП, ГОСТ, проектной документации. Задаёшь вопрос на русском языке — получаешь ответ со ссылками на источники и оценкой достоверности.

```
Вопрос: "Минимальная ширина пути эвакуации по СП 1.13130?"
Ответ:  "Не менее 1,2 м (п. 4.3.4 СП 1.13130.2022). [VERIFIED]"
         └── Источник: СП 1.13130.2022.pdf, стр. 12
```

---

## Архитектура

```
Интернет → les.ovc.me
                │
┌───────────────▼─────────────────────────────────┐
│  VPS П.А.У.К. (Debian 13, 185.185.71.196)       │
│                                                 │
│  Caddy :443  (Let's Encrypt, les.ovc.me)        │
│       ├── /api/* → proxy_server :8050           │
│       └── /*     → sovushka_ng  :8051           │
│                                                 │
│  ZeroTier mesh → Mac Mini                       │
│       ├── 10.195.146.98:6333 → Qdrant           │
│       └── 10.195.146.98:8080 → MLX Host         │
└─────────────────────────────────────────────────┘
         │  ZeroTier `8d1c312afa249de4`
┌────────▼────────────────────────────────────────┐
│  Mac Mini M4 / 24 GB (Ж.А.Б.А.)                │
│                                                 │
│  С.О.В.У.Ш.К.А.  (NiceGUI UI, порт 8051)       │
│  les-proxy        (FastAPI,    порт 8050)        │
│       ├── proxy_server.py → proxy.app           │
│       ├── proxy/security.py (server-side RBAC)  │
│       ├── RAG pipeline  (С.А.М.О.В.А.Р.)        │
│       ├── Т.О.С.К.А.    (SafeRAG валидация)     │
│       └── В.О.Л.К.      (ключи, SQLite)         │
│                                                 │
│  MLX Native Host  (порт 8080)                   │
│       ├── Qwen3-14B-4bit     (LLM, Metal)        │
│       ├── Qwen3-4B-4bit      (валидатор)         │
│       └── BGE-M3             (эмбеддинги, MPS)   │
│                                                 │
│  Qdrant  (векторная база, порт 6333)            │
└─────────────────────────────────────────────────┘
```

---

## Модули системы

| Аббревиатура | Расшифровка | Роль |
|---|---|---|
| **С.О.В.У.Ш.К.А.** | Система Оперативного Взаимодействия с Умной Шкатулкой Корпоративных Активов | UI (NiceGUI) |
| **С.А.М.О.В.А.Р.** | Система Автоматической Масштабируемой Обработки Векторных Архивов Регламентов | RAG / Qdrant |
| **Т.О.С.К.А.** | Технология Оценки Соответствия Контента Архивным данным | CRAG валидатор |
| **В.О.Л.К.** | Валидатор Ограничений Лиц и Ключей | Auth / RBAC |
| **П.А.У.К.** | Периметральный Аванпост Удалённого Контроля | VPS прокси |
| **Е.Ж.И.К.** | Ежедневный Журнализатор Инженерной Корреспонденции | IMAP / почта |
| **Ж.А.Б.А.** | — | Mac Mini (хост) |

---

## Стек

| Компонент | Технология |
|---|---|
| LLM | `mlx-community/Qwen3-14B-4bit` via MLX |
| Валидатор | `mlx-community/Qwen3-4B-4bit` (CRAG: VERIFIED / NO_DATA / HALLUCINATION) |
| Эмбеддинги | [BGE-M3](https://huggingface.co/BAAI/bge-m3) via sentence-transformers + MPS |
| Векторная база | [Qdrant](https://qdrant.tech/) |
| Backend | FastAPI + LlamaIndex |
| Frontend | [NiceGUI](https://nicegui.io/) v5.0 |
| Auth | В.О.Л.К. — server-side API guards, API-ключи + SQLite, trusted local/ZeroTier contour, trusted-proxy boundary для forwarded headers |
| Внешний доступ | Caddy + Let's Encrypt + ZeroTier mesh; SSH tunnel только резерв |
| Форматы документов | PDF, DOCX, XLSX, CSV, EML, MSG, JSON, MD, TXT |

---

## Быстрый старт

### Требования
- Mac с Apple Silicon (M1/M2/M4) и минимум 16 GB RAM (рекомендуется 24 GB)
- Docker Desktop
- [uv](https://docs.astral.sh/uv/) (`brew install uv`)
- Python 3.12+

### Установка

```bash
git clone https://github.com/yourname/les-rag-public
cd les-rag-public

# Зависимости
uv sync

# Конфигурация
cp .env.example .env
# Отредактируй .env — укажи модели и пароль

# Запуск
docker compose up -d          # Qdrant + les-proxy
./start_mlx.command           # MLX Host (LLM + Embeddings)
uv run python3 sovushka_ng.py # UI
```

Открой `http://localhost:8051`

### Добавление документов

```bash
# Положи PDF/DOCX в папку
mkdir -p RAG_Content/MyDocs
cp my_norms/*.pdf RAG_Content/MyDocs/

# Запусти индексацию через UI или curl
curl -X POST http://localhost:8050/api/rag/sync/MyDocs
```

---

## RAG Pipeline

```
Запрос пользователя
      │
      ▼
Векторный поиск (BGE-M3 + Qdrant)  top-8 чанков
      │
      ▼ [опционально, включается в UI]
Реранкер (Qwen3-4B batch) → top-5 релевантных чанков
      │
      ▼
Промпт = системный + контекст + вопрос
      │
      ▼
Qwen3-14B (MLX, Metal)
      │  ответ
      ▼
Т.О.С.К.А. валидация (Qwen3-4B)
      │  VERIFIED / NO_DATA / HALLUCINATION
      ▼
Ответ пользователю + источники
```

---

## Форматы вывода

С.О.В.У.Ш.К.А. умеет форматировать ответ в:
- Свободный текст
- Спецификацию оборудования (по ГОСТ 21.110)
- JSON-дерево / иерархическую схему
- Mermaid-диаграмму (flowchart, sequence, ER)
- SVG-схему
- Произвольную таблицу

---

## Внешний доступ (П.А.У.К.)

Система доступна через HTTPS без открытия портов домашней сети:

```
Интернет → les.ovc.me (VPS, Caddy, SSL)
                │
          proxy/UI на VPS
                │
          ZeroTier mesh
                │
         Mac Mini :6333/:8080
```

Доступ по ключам (В.О.Л.К.):
- `admin` — полный интерфейс
- `user`  — только AI ЧАТ
- Local/ZeroTier IP (`127.0.0.1`, `10.195.146.x`) — trusted admin автобайпас, ключ не нужен
- Внешний доступ через `les.ovc.me` — ключ обязателен

---

## Управление памятью

Система оптимизирована под ограниченную RAM Mac Mini:

| Процесс | RAM |
|---------|-----|
| MLX (Qwen3-14B) | зависит от квантования |
| MLX (Qwen3-4B val) | зависит от квантования |
| les-proxy (Docker) | ≤ 512 MB |
| les-qdrant (Docker) | ≤ 1 GB |
| **Итого** | **~10 GB** |

Docker-контейнеры имеют жёсткий `mem_limit` в `docker-compose.yml`.

`les.command` запускает **MLX Watchdog** — фоновый процесс, который перезапускает MLX через 30 секунд при падении (OOM kill). Виден в `./les.command status`.

`mlx_host.py` читает `.env` самостоятельно при старте — не зависит от оболочки запуска.

---

## Быстрая диагностика

```bash
# Все сервисы
curl -s http://localhost:8050/api/diag | python3 -c \
  "import sys,json; [print(f\"{r['status'].upper():6} {r['name']}\") for r in json.load(sys.stdin)['checks']]"

# Метрики (файлы, чанки, RAM, CPU)
curl -s http://localhost:8050/api/metrics | python3 -m json.tool

# Логи в реальном времени
docker logs -f les-proxy 2>&1 | grep -E "\[CHAT\]|\[PARSE\]|\[ERROR\]"
```

### Runtime smoke после деплоя

```bash
# Локальный контур: localhost/ZeroTier считается trusted admin, no-key boundary пропускается
uv run python tools/runtime_smoke.py \
  --admin-key "$ADMIN_PASSWORD" \
  --question "Ширина путей эвакуации"

# VPS/public URL: без ключа admin endpoint обязан вернуть 401/403
LES_PROXY_URL=https://les.ovc.me \
LES_UI_URL=https://les.ovc.me \
LES_ADMIN_KEY="$ADMIN_PASSWORD" \
LES_USER_KEY="user-key" \
uv run python tools/runtime_smoke.py \
  --expect-external-auth \
  --question "Ширина путей эвакуации"
```

Smoke проверяет health/status/metrics/diag, загрузку UI shell, auth boundary для admin/user ключей и опциональные живые RAG-вопросы.

---

## Структура репозитория (публичная версия)

```
les-rag-public/
├── README.md
├── pyproject.toml
├── .env.example
├── docker-compose.yml
├── Dockerfile.proxy
├── proxy/                    ← Proxy v3: app, security, services, storage
│   ├── app.py                ← create_app(), startup, middleware, router wiring
│   ├── legacy_app.py         ← compatibility shim for old imports
│   ├── routers/              ← auth, chat, datasets, runtime, diagnostics, jobs
│   ├── security.py           ← X-API-Key/Bearer, admin/user guards
│   └── services/             ← JobService, retrieval, SafeRAG policy
├── start_mlx.command
├── stop_mlx.command
├── start_pauk.command        ← резервный SSH tunnel к VPS
├── stop_pauk.command
├── pauk_launchd.plist        ← launchd автозапуск туннеля (Mac Mini)
├── mlx_host.py               ← MLX Native Host
├── backend/
│   ├── mlx_adapter.py        ← MLXMemoryManager
│   ├── qdrant_adapter.py     ← EmbedClient + RAG
│   ├── converter.py          ← PDF/DOCX/XLSX → текст
│   ├── metrics_collector.py
│   └── interface.py
├── tools/
│   └── runtime_smoke.py      ← post-deploy smoke: auth/UI/runtime/RAG
├── sovushka/                 ← UI модули (рефакторинг)
│   ├── config.py             ← PROXY_URL, MLX_URL, UI_PORT
│   ├── state.py
│   ├── styles.py
│   └── pages/
│       ├── chat.py
│       ├── samovar.py
│       └── ...
└── sovushka_ng.py            ← точка входа UI
```

**Не входит в публичную версию:** `.env`, ключи, данные индексов.

---

## Лицензия

MIT — используй, форкай, улучшай.  
Если делаешь что-то интересное на этой базе — открой issue, интересно посмотреть.

---

## Дорожная карта

- [x] RAG pipeline (Qdrant + BGE-M3 + Qwen3)
- [x] CRAG валидация (Т.О.С.К.А.) — VERIFIED / NO_DATA / HALLUCINATION
- [x] NiceGUI интерфейс (С.О.В.У.Ш.К.А.) v5.0 — модульная архитектура
- [x] Светлая и тёмная тема — персистентная через `app.storage.user`, WCAG AA контрасты
- [x] Внешний доступ через VPS (П.А.У.К.) — Caddy + Let's Encrypt + ZeroTier, `les.ovc.me` live
- [x] Auth по ключам (В.О.Л.К.) — admin/user роли, временные ключи, привязка к устройству (fingerprint)
- [x] Proxy v3 — тонкий `proxy_server.py`, пакет `proxy/`, server-side guards для admin/user endpoints
- [x] Stabilization tests — pytest regression для trusted network и API-key RBAC boundary
- [x] История чатов (SQLite `chat_history`) — выживает рестарт процесса
- [x] SafeRAG error handling — таймаут/ошибка валидатора → safe fallback, неподтверждённый ответ не отдаётся как нормальный
- [x] Rate limiting (≤ 2 параллельных LLM-запроса), защита от prompt injection, path traversal
- [x] `les.command` — единый скрипт управления (start/stop/restart/status)
- [x] Proxy modularization — активные endpoints вынесены в routers/services, `legacy_app.py` оставлен shim
- [x] Stabilization: runtime smoke для локального/VPS post-deploy контура
- [ ] Stabilization: browser smoke UI admin/user сценариев
- [ ] RAG quality hardening: hybrid retrieval (dense + exact/sparse), golden set, trace/audit
- [ ] Folder Watcher — автосинк новых файлов
- [ ] Parquet pipeline для смет и спецификаций
- [ ] Е.Ж.И.К. — IMAP коннектор для почты
- [ ] VLM pipeline — анализ PDF-чертежей
