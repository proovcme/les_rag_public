# 🌲 Л.Е.С. — Локальная Единая Система

**Локальная RAG-система для работы с нормативной документацией.**  
Работает полностью офлайн на Apple Silicon (Mac Mini M4). Никакие данные не покидают локальную сеть.

**Актуальный статус: 23.05.2026.** С.О.В.У.Ш.К.А. разделена на лёгкий чат и админку: `https://les.ovc.me/` открывает премиальный чат с выезжающей историей и панелью артефактов, `https://les.ovc.me/les` открывает админский контур. Runtime стабилизирован: Qdrant живёт в OrbStack/Docker, `les-proxy` и SQLite работают на host через LaunchAgent `me.ovc.les.proxy`, MLX Host обслуживает LLM/validator/embedder. Intake/RAG усилен smart validation, deterministic routing, clarification gate, smart upload, micro-indexing и первым parquet-backed table query слоем.

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
│       ├── /api/* → 10.195.146.98:8050           │
│       └── /*     → 10.195.146.98:8051           │
│             ├── /     → AI ЧАТ + история        │
│             └── /les  → админка Л.Е.С.          │
│                                                 │
│  Только HTTPS-релей. RAG/SQLite/UI/LLM не живут │
│  на VPS; вся механика работает на Mac Mini.     │
└─────────────────────────────────────────────────┘
         │  ZeroTier `8d1c312afa249de4`
┌────────▼────────────────────────────────────────┐
│  Mac Mini M4 / 24 GB (Ж.А.Б.А.)                │
│                                                 │
│  С.О.В.У.Ш.К.А.  (NiceGUI UI, порт 8051)       │
│  les-proxy        (FastAPI host, порт 8050)      │
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
│  Qdrant  (OrbStack/Docker, порт 6333)           │
└─────────────────────────────────────────────────┘
```

---

## Модули системы

| Аббревиатура | Расшифровка | Роль |
|---|---|---|
| **Л.Е.С.** | Локальная Единая Система | Оркестратор, API Gateway |
| **Ж.А.Б.А.** | Жёсткая Аппаратная База Аналитики | Mac Mini (хост) |
| **С.А.М.О.В.А.Р.** | Система Автономная Машинной Обработки Внутренних Архивов РАГ | RAG / Qdrant |
| **Т.О.С.К.А.** | Терминал Оценки, Самопроверки и Контроля Архитектуры | CRAG валидатор |
| **С.О.В.У.Ш.К.А.** | Система Обработки и Выдачи: Умная, Шаблонизированная, Классифицированная, Автоматизированная | UI (NiceGUI) |
| **П.Р.О.Р.А.Б.** | Программа Регулярной Оценки Работы Автономной Базы | Метрики / диагностика |
| **К.О.Т.** | Куратор Отраслевой Терминологии | Семантический фильтр |
| **В.О.Л.К.** | Внутренний Охранный Локальный Контур | Auth / RBAC |
| **П.А.У.К.** | Периметровый Автономный Узел Коммуникаций | VPS relay |
| **С.У.Х.А.Р.И.К.** | Система Управления Холодными Архивами и Резервными Источниками Комплекса | Снапшоты / бэкапы |
| **Е.Ж.И.К.** | *(расшифровка уточняется)* | IMAP / почта |

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
| Артефакты | Таблицы/JSON/Mermaid/SVG в правой панели чата, XLSX/CSV ingestion и Parquet artifacts |

---

## Быстрый старт

### Требования
- Mac с Apple Silicon (M1/M2/M4) и минимум 16 GB RAM (рекомендуется 24 GB)
- OrbStack или Docker Desktop; штатно используется только Qdrant-контейнер
- [uv](https://docs.astral.sh/uv/) (`brew install uv`)
- Python 3.12+

### Установка

```bash
git clone https://github.com/yourname/les-rag-public
cd les-rag-public

# Зависимости
uv sync

# Конфигурация
cp env.example .env
# Отредактируй .env — укажи модели и пароль

# Запуск всего контура: Qdrant в OrbStack/Docker, proxy/MLX/UI на host
./les.command start
```

Открой `http://localhost:8051` для чата или `http://localhost:8051/les` для админки.

### Добавление документов

```bash
# Положи PDF/DOCX в папку
mkdir -p RAG_Content/MyDocs
cp my_norms/*.pdf RAG_Content/MyDocs/

# Сухой smart-plan: покажет accepted/rejected и будущие индексы
curl -s http://localhost:8050/api/rag/smart-plan | python3 -m json.tool

# Smart sync: файлы раскладываются по классифицированным индексам
curl -X POST http://localhost:8050/api/rag/sync-smart \
  -H 'Content-Type: application/json' \
  -d '{"source_root":"RAG_Content","parse":false}'

# Smart upload одного файла: индекс выбирается автоматически
curl -X POST http://localhost:8050/api/rag/upload-smart \
  -F "file=@my_smeta.csv"
```

---

## RAG Pipeline

```
Запрос пользователя
      │
      ▼
Clarification gate
      ├── широкий/неясный запрос → NEEDS_CLARIFICATION + вопросы
      └── узкий запрос → retrieval
      │
      ▼
Векторный поиск (BGE-M3 + Qdrant)  top-8 чанков
      │
      ▼ [опционально, включается в UI]
Реранкер (Qwen3-4B batch) → top-5 релевантных чанков
      │
      ▼
Table query gate
      ├── найден parquet_path + табличный вопрос → точный VERIFIED ответ из Parquet
      └── нет табличного ответа → LLM
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
- Артефакт в правой панели чата с копированием JSON/SVG/Mermaid

Расширенные параметры запроса вынесены из основной области в модальное окно **Расширенный запрос**: формат, датасет, стиль, реранкер и шаблон вывода. История чатов открывается выезжающей левой панелью.

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

Публичные маршруты UI:
- `https://les.ovc.me/` — устойчивый чатовый контур, не монтирует админские страницы.
- `https://les.ovc.me/les` — админский контур, доступен только admin/trusted.

---

## Управление памятью

Система оптимизирована под ограниченную RAM Mac Mini:

| Процесс | RAM |
|---------|-----|
| MLX (Qwen3-14B) | зависит от квантования |
| MLX (Qwen3-4B val) | зависит от квантования |
| les-proxy (host LaunchAgent) | Python-процесс, без Docker VM |
| les-qdrant (OrbStack/Docker) | ≤ 1 GB |
| **Итого** | **~10 GB** |

В штатном режиме Docker/OrbStack держит только Qdrant. Docker-proxy оставлен как opt-in profile `docker-proxy`, чтобы SQLite работал напрямую на host, а не через bind mount VM.

`les.command` поднимает Qdrant через OrbStack, а `les-proxy` — как host LaunchAgent `me.ovc.les.proxy`.

`mlx_host.py` читает `.env` самостоятельно при старте — не зависит от оболочки запуска.

### Performance flags

```bash
# Кэширует только VERIFIED ответы. Переиндексация датасета инвалидирует scope через chunk_count.
SEMANTIC_CACHE_ENABLED=true
SEMANTIC_CACHE_THRESHOLD=0.94

# Экспериментальный PDF tables → Parquet слой. Markdown ingestion PDF остаётся основным fallback.
PDF_TABLE_EXTRACTION_ENABLED=false
PDF_TABLE_MAX_PAGES=30
PDF_TABLE_MAX_TABLES=50
DOC_ROUTER_SAMPLE_PAGES=3
```

### Новое в релизе 22.05.2026

- Чат Совушки отделён от админки: меньше фоновых UI-зависимостей на основном рабочем экране.
- `reconnect_timeout=180` и `chat_pending` помогают переживать долгие RAG-запросы и реконнекты.
- Premium chat layout: нижний composer, левая drawer-история, правая панель артефактов.
- `restart_sovushka.command` запускает UI через `.venv/bin/python3`, чтобы не сваливаться в системный Python 3.9.
- Добавлены semantic cache, document router, Parquet/XLSX/CSV pipeline и тесты для них.

### Новое в релизе 23.05.2026

- **Smart intake:** `verify_source_file()` отбрасывает служебные директории, UUID staging, неподдержанные расширения, пустые и слишком крупные файлы (`RAG_SOURCE_MAX_MB`, default `100`).
- **Smart plan/sync:** `/api/rag/smart-plan` и `/api/rag/sync-smart` строят deterministic route по имени, пути, типу, размеру и probes без LLM.
- **Smart upload:** `/api/rag/upload-smart` сохраняет файл потоково, классифицирует через Document Router, сам выбирает/создаёт `*_Index` и запускает guarded parse `limit=1`.
- **Clarification gate:** `/api/chat` возвращает `NEEDS_CLARIFICATION` и уточняющие вопросы до retrieval/LLM, если запрос слишком широкий.
- **Table query MVP:** `proxy/services/table_query_service.py` читает `.parquet` по `parquet_path` из payload и считает суммы/количества без генерации LLM.
- **OrbStack runtime:** Docker/OrbStack держит только `les-qdrant`; `les-proxy` вынесен на host LaunchAgent `me.ovc.les.proxy`, SQLite больше не работает через VM bind mount.
- **Micro-indexing:** safe loop `tools/rag_safe_parse_loop.py` индексирует по одному файлу, проверяет RAM/swap и `points_match_sqlite_chunks`.
- **Memory guard fix:** `swap_pct=0.0` больше не превращается в `100.0` в safe-loop и server-side parse admission.
- **Startup hardening:** `les.command` стартует Qdrant, MLX, host-proxy и UI без дублирования уже живых listener-процессов.
- **Resource Governor v1:** `/api/indexing-mode` разделяет рабочий чат и индексацию, ставит chat generation на паузу, управляет unload MLX и приоритетом индексов.
- **Parse scheduler v2:** приоритет `NTD_FIRE → GKRF → NTD_ELECTRICAL → NTD_STRUCTURAL → TABLE_SMETA → NTD_OTHER`, post-batch memory hysteresis, `warm_embedder`, phase timings.
- **BGE/chunk knobs:** `BGE_BATCH_SIZE`, `RAG_EMBED_BATCH`, `RAG_CHUNK_SIZE`, `RAG_CHUNK_OVERLAP`, `RAG_PARSE_POST_MAX_SWAP_PCT`.
- **Финальное состояние сессии:** `indexed_files=9`, `pending_files=792`, `chunks=850`, Qdrant points `850`, `points_match_sqlite_chunks=true`, `errors=0`.
- **Проверки:** `uv run pytest` → `107 passed`; `git diff --check` → OK.

### Следующая сессия

Начать с независимой оценки архитектуры: пройти runtime/resource-governor/indexing/RAG-quality как внешний reviewer, не продолжая кодинг до формулировки рисков, границ и приоритетов.

---

## Быстрая диагностика

```bash
# Все сервисы
curl -s http://localhost:8050/api/diag | python3 -c \
  "import sys,json; [print(f\"{r['status'].upper():6} {r['name']}\") for r in json.load(sys.stdin)['checks']]"

# Метрики (файлы, чанки, RAM, CPU)
curl -s http://localhost:8050/api/metrics | python3 -m json.tool

# Логи в реальном времени
tail -f logs/proxy.log | grep -E "\[CHAT\]|\[PARSE\]|\[ERROR\]"
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

### RAG golden set после milestone индексирования

```bash
uv run python tools/rag_golden_set.py \
  --key-db data/les_meta.db \
  --key-role user
```

Golden set использует `/api/rag/retrieve-debug`, поэтому проверяет качество найденных источников без запуска LLM. Базовые NTD-кейсы лежат в `golden/ntd_golden_set.json`; после каждого блока micro-indexing команда должна проходить без падений и показывать ожидаемые source/content hints.

### Indexing mode

```bash
# Включить режим индексации: выгружает MLX-модели, ставит chat generation на паузу
curl -X POST http://localhost:8050/api/indexing-mode \
  -H 'Content-Type: application/json' \
  -d '{"enabled":true,"reason":"night batch","unload_models":true}'

# Один приоритетный batch: NTD_FIRE → GKRF → NTD_ELECTRICAL → NTD_STRUCTURAL → TABLE_SMETA → NTD_OTHER
curl -X POST http://localhost:8050/api/rag/parse-scheduler \
  -H 'Content-Type: application/json' \
  -d '{"batch_limit":1,"max_batches":1,"background":false,"stop_on_error":true}'

# Короткая warm-embedder серия: не выгружать BGE-M3 между файлами, но остановиться после batch при росте swap
curl -X POST http://localhost:8050/api/rag/parse-scheduler \
  -H 'Content-Type: application/json' \
  -d '{"batch_limit":1,"max_batches":3,"warm_embedder":true,"post_batch_max_swap_pct":60,"background":false,"stop_on_error":true}'

# Вернуться к рабочему чату
curl -X POST http://localhost:8050/api/indexing-mode \
  -H 'Content-Type: application/json' \
  -d '{"enabled":false,"reason":"work/chat"}'
```

В `indexing-mode` чат-генерация возвращает `409`, чтобы не грузить main LLM параллельно с embedder. Clarification/retrieval/golden запускаются только после явного возврата в chat mode.

Ответ `parse-scheduler` содержит phase timings по batch: `convert_sec`, `chunk_sec`, `embed_sec`, `upsert_sec`, `count_sec`. Это основной диагностический сигнал для ускорения индексации; на контрольном NTD_FIRE-файле bottleneck был в `embed_sec`.

Операторские env-ручки:

```env
BGE_MODEL=BAAI/bge-m3
BGE_BATCH_SIZE=16              # внутренний batch sentence-transformers; меньше = ниже peak memory
RAG_EMBED_BATCH=16             # чанков за один HTTP-запрос к /v1/embeddings
RAG_CHUNK_SIZE=900             # больше chunk = меньше embedding-вызовов
RAG_CHUNK_OVERLAP=80
RAG_PARSE_POST_MAX_SWAP_PCT=60 # auto-stop после batch
```

### Browser smoke UI

```bash
# Локально: trusted localhost/ZeroTier должен сразу открыть admin shell
uv run --with playwright python tools/browser_smoke.py --trusted-local

# VPS/public URL: проверка логина admin/user и границ видимости вкладок
LES_UI_URL=https://les.ovc.me \
LES_ADMIN_KEY="$ADMIN_PASSWORD" \
LES_USER_KEY="user-key" \
uv run --with playwright python tools/browser_smoke.py \
  --question "Ширина путей эвакуации"
```

При первом запуске на машине может понадобиться браузер Playwright:

```bash
uv run --with playwright python -m playwright install chromium
```

Browser smoke проверяет admin-вкладки, user-вкладки, отсутствие admin-разделов у user и, если передан вопрос, появление ответа в UI-чате.

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
│   └── services/             ← JobService, retrieval, SafeRAG, clarification, table query
├── start_mlx.command
├── stop_mlx.command
├── start_pauk.command        ← резервный SSH tunnel к VPS
├── stop_pauk.command
├── pauk_launchd.plist        ← launchd автозапуск туннеля (Mac Mini)
├── mlx_host.py               ← MLX Native Host
├── backend/
│   ├── mlx_adapter.py        ← MLXMemoryManager
│   ├── qdrant_adapter.py     ← EmbedClient + RAG
│   ├── smart_index.py        ← source verification + smart plan
│   ├── document_router.py    ← deterministic ingestion classifier
│   ├── parquet_writer.py     ← table normalization + parquet artifacts
│   ├── converter.py          ← PDF/DOCX/XLSX → текст
│   ├── metrics_collector.py
│   └── interface.py
├── tools/
│   ├── runtime_smoke.py      ← post-deploy smoke: auth/UI/runtime/RAG
│   └── browser_smoke.py      ← Playwright smoke: UI admin/user scenarios
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
- [x] Startup hardening — ожидание Docker daemon перед запуском proxy/Qdrant
- [x] Proxy modularization — активные endpoints вынесены в routers/services, `legacy_app.py` оставлен shim
- [x] Stabilization: runtime smoke для локального/VPS post-deploy контура
- [x] Stabilization: browser smoke UI admin/user сценариев
- [ ] RAG quality hardening: hybrid retrieval (dense + exact/sparse), расширение golden set, trace/audit
- [x] RAG intake hardening: smart-plan, source verification, size guard, excluded dirs
- [x] Chat clarification gate — broad запросы получают уточняющие вопросы до retrieval/LLM
- [x] Performance: semantic cache для VERIFIED ответов с dataset-scope invalidation
- [ ] Performance backlog: streaming validation, embedder TTL/offload, MLX tuning
- [x] Indexing mode + parse scheduler — приоритетные батчи pending файлов с memory hysteresis
- [ ] Folder Watcher — автосинк новых файлов
- [x] Parquet pipeline для XLSX/XLS/CSV — row-level chunks + `.parquet` artifacts
- [x] Experimental PDF tables → Parquet — PyMuPDF first, pdfplumber fallback, `needs_ocr` marker
- [x] Table query MVP — суммы/количества из Parquet по `parquet_path` без LLM
- [x] Document Router — быстрый probe/classify/complexity перед выбором ingestion pipeline
- [ ] XLS/CSV export — выдача табличных результатов как готовых файлов
- [ ] Field Intake — внешние формы загрузки в карантинный `FIELD_Index`
- [ ] Е.Ж.И.К. — IMAP коннектор для почты
- [ ] VLM pipeline — анализ PDF-чертежей

### Backlog ускорения и оптимизации

- **Семантическое кэширование:** базовый слой внедрён для `VERIFIED` ответов. Ключ учитывает semantic similarity и snapshot датасетов (`chunk_count`), чтобы переиндексация инвалидировала старые ответы.
- **Динамическая выгрузка эмбеддера:** держать `bge-m3` в памяти только во время retrieval/warm path, затем выгружать по агрессивному TTL, освобождая RAM/MPS для основной LLM.
- **Параллельная валидация:** перейти от post-factum проверки полного ответа к асинхронной проверке чанков по мере streaming generation, чтобы снизить time-to-first-token в UI.
- **Аппаратный тюнинг MLX:** проверить Flash Attention на длинном контексте и смешанное квантование 14B модели: критичные слои в 8 bit, остальные в 4 bit.
- **Табличный контур:** базовый Parquet ingestion внедрён для XLSX/XLS/CSV. PDF tables слой добавлен как экспериментальный `PDF_TABLE_EXTRACTION_ENABLED`: PyMuPDF `find_tables()` first, pdfplumber fallback, сканы помечаются `needs_ocr`. Первый query слой уже читает parquet напрямую для сумм/количеств; следующий шаг — фильтры, группировки, сравнение смет и UI-таблица `table_query.rows`.
- **Полевой загрузчик:** внешняя форма через П.А.У.К. для загрузки актов, фотоотчётов, предписаний и комментариев в изолированный карантинный датасет `FIELD_Index`, без смешивания с нормативной базой.
- **Выдача XLS/CSV:** экспорт табличных ответов и AG Grid результатов в цифровой артефакт для смет, ведомостей и рабочей документации.
