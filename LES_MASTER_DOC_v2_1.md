# 🦉 Л.Е.С. — Локальная Единая Система
## Мастер-документ v4.0 | 31.05.2026

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
| **Lightweight** | Qdrant/proxy/SQLite/MLX/UI на host LaunchAgents, без Docker runtime и без RAGFlow/ES/MySQL/MinIO/Redis/Celery |
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
- **Шрифт чата** — используется системный monospace fallback; битый `ISOCPEUR.ttf` удалён из `/static/fonts/`
- **Контраст** — пересмотрены CSS-переменные тёмной и светлой тем (`--text`, `--dim`, `--border`), Quasar-оверрайды для селектов и списков
- **Watchdog памяти** — `memory_guard_loop()` in `mlx_host.py`: ≥70% swap → выгрузка val-модели; ≥85% → kill non-essential processes; TTL: val=120с, main=300с
- **Сессионный `session_id`** — передаётся в `/api/chat`, сохраняется в `chat_history`; новая сессия при сбросе чата

### Ключевые изменения v2.8 (патч — OOM при индексации)
- **Throttling sync_folder** — цикл обхода файлов теперь делает `await asyncio.sleep(0.1)` на каждой итерации; event loop не блокируется при обходе 800+ файлов (NTD)
- **`_PARSE_SEMAPHORE`** — отдельный семафор для `parse_dataset` в `sync_folder._run()`, изолирован от остальных путей (`parse_semaphore` сохранён для upload)
- **`os.nice(10)` перед парсингом** — снижает CPU-приоритет процесса bge-m3 эмбеддинга; ядро отдаёт ресурсы UI/API при конкуренции
- **mem_limit подтверждён** — `docker-compose.yml` уже содержал `proxy=512m`, `qdrant=1g`; дополнительных изменений не потребовалось
- **Цель:** Load Average при SYNC NTD (801 файл) не выше 5; система остаётся отзывчивой

### Ключевые изменения v3.0 (Proxy Architecture + Auth Boundary)
- **Тонкий ASGI entrypoint:** `proxy_server.py` теперь только создаёт `app`; основная логика вынесена в пакет `proxy/`.
- **Server-side auth boundary:** admin/user guards в `proxy/security.py`; UI-сессия С.О.В.У.Ш.К.А. больше не считается защитой API.
- **Trusted contour:** только loopback и явно заданные `TRUSTED_NETWORKS` получают роль `TRUSTED_NETWORK_ROLE` без ключа. Продуктовый default — `127.0.0.0/8,::1/128` → `admin`; VPN/LAN CIDR добавляется только в приватном `.env`.
- **Forwarded headers boundary:** `X-Forwarded-For` / `X-Real-IP` принимаются только от IP из `TRUSTED_PROXY_NETWORKS`; внешний клиент больше не может сам назначить себе trusted IP через header.
- **CORS allowlist:** `allow_origins=["*"]` заменён на `CORS_ALLOWED_ORIGINS`.
- **Docker control opt-in:** proxy-контейнер больше не получает Docker socket по умолчанию; Docker CLI/status/restart включаются только через `LES_ENABLE_DOCKER_CONTROL=true` и явный mount socket.
- **Upload limits:** `/api/rag/upload/*` сохраняет файлы потоково, проверяет `RAG_UPLOAD_SUFFIXES` and `MAX_UPLOAD_MB`.

### Ключевые изменения v3.2 (Legacy retirement, 21.05.2026)
- **Legacy runtime закрыт:** `proxy/legacy_app.py` больше не содержит endpoints и оставлен только как compatibility shim для старых импортов.
- **Композиция приложения:** `proxy/app.py` владеет `create_app()`, startup, middleware, shared state и подключением routers.
- **Routers/services:** активные `auth`, `settings`, `chat`, `chat_history`, `datasets`, `runtime`, `diagnostics`, `jobs`, `logs`, `rerank`, root status page вынесены из legacy в `proxy/routers/*`; retrieval/SafeRAG/job логика живёт в `proxy/services/*`.
- **Mail/Parquet не активны:** `/api/mail/*` и `/api/mail/index-table` отсутствуют в runtime; будущие Е.Ж.И.К./Parquet должны проектироваться заново.
- **Проверки:** `pytest -q`, `compileall`, import smoke `proxy_server`/`sovushka_ng`, route smoke без `/api/mail/*`, `docker compose config --quiet`.
- **Durable jobs:** `proxy/services/job_service.py` хранит RAG sync jobs в SQLite, `/api/jobs` объединяет persisted + live jobs.
- **SafeRAG hardening:** `UNKNOWN` от валидатора блокируется safe fallback, как и `HALLUCINATION`; неподтверждённый ответ не отдаётся как нормальный.
- **Read-only diagnostics:** `/api/diag` больше не вызывает `/api/chat`, не пишет историю и не меняет CRAG counters.
- **Safe storage:** upload filenames санитизируются, sync вложенных папок сохраняет относительные пути, одинаковые имена в разных подпапках не должны конфликтовать.
- **С.О.В.У.Ш.К.А. hardening:** API-ошибки 401/403/409 показываются как реальные ошибки, raw SVG/XML больше не исполняется как HTML, пользовательский текст экранируется.

### Ключевые изменения v3.3 (Split UI + Premium Chat, 22.05.2026)
- **Split UI:** `<your-domain>/` открывает только лёгкий AI-чат и историю; `<your-domain>/les` открывает админский контур. Основной чат больше не монтирует обзор, Самовар, Прораб, диагностику и В.О.Л.К.
- **Premium chat:** центральная рабочая зона, нижний composer, кнопки `Отправить` и `Расширенный запрос`.
- **Расширенный запрос:** бывшая правая форма вынесена в модальное окно с форматом, датасетом, стилем, реранкером, шаблоном и preview промпта.
- **История:** левая выезжающая панель с сессиями; выбор сессии восстанавливает чат.
- **Артефакты:** правая панель показывает структурированные результаты: текст, JSON/table, спецификации, Mermaid, SVG и схемы.
- **Reconnect mitigation:** `reconnect_timeout=180` и `chat_pending` сохраняют видимость выполняющегося RAG-запроса после реконнекта.
- **Restart hardening:** `restart_sovushka.command` запускает `.venv/bin/python3`, а не системный Python 3.9, и сохраняет реальный PID слушателя.
- **Data pipeline:** semantic cache, Document Router, XLSX/CSV row-level chunks и Parquet artifacts покрыты тестами.

### Ключевые изменения v3.4 (Smart intake + Table query, 23.05.2026)
- **Source verification:** `backend/smart_index.py` проверяет каждый входной файл и возвращает `accepted/rejected + reason`: `excluded_dir`, `uuid_staging_dir`, `unsupported_suffix`, `empty_file`, `file_too_large`.
- **Memory-safe intake:** `RAG_SOURCE_MAX_MB` ограничивает размер исходника для smart-plan, default `100`; служебные `CLAUDE/QWEN` и UUID staging не попадают в кандидаты.
- **Smart plan/sync:** `/api/rag/smart-plan` и `/api/rag/sync-smart` раскладывают документы по deterministic route без LLM: `NTD_FIRE`, `NTD_ELECTRICAL`, `NTD_STRUCTURAL`, `NTD_OTHER`, `GKRF`, `TABLE_*`.
- **Smart upload:** `/api/rag/upload-smart` потоково принимает файл, классифицирует через `backend/document_router.py`, сам находит или создаёт нужный `*_Index`, затем запускает guarded parse `limit=1`.
- **Clarification gate:** `/api/chat` до retrieval/LLM останавливает слишком широкие запросы и возвращает `NEEDS_CLARIFICATION`, `clarifying_questions`, `suggested_filters`.
- **Table query MVP:** `proxy/services/table_query_service.py` читает `.parquet` по `parquet_path` из Qdrant payload и считает суммы/количества без генерации LLM. Ответ возвращается как `VERIFIED` с полем `table_query`.
- **Startup hardening:** legacy compose path в `les.command` ждёт Docker daemon и прекращает старт при ошибке compose.
- **Историческая проверка v3.4:** `uv run pytest` → `82 passed`; `git diff --check` → OK.

### Ключевые изменения v3.5 (Runtime stabilization + micro-indexing, 23.05.2026)
- **Docker Desktop снят с критического пути:** система переведена на OrbStack; штатный compose поднимает только `les-qdrant`.
- **Host-proxy:** `les-proxy` вынесен из Docker и запускается через LaunchAgent `me.ovc.les.proxy`; SQLite `data/les_meta.db` больше не работает через VM bind mount.
- **Docker-proxy opt-in:** сервис `proxy` в `docker-compose.yml` оставлен только под profile `docker-proxy`.
- **Host URLs:** локальный runtime использует `MLX_URL=http://127.0.0.1:8080` и `QDRANT_URL=http://127.0.0.1:6333`; Docker overrides сохранены в compose.
- **Safe micro-indexing:** `tools/rag_safe_parse_loop.py` индексирует `batch=1`, перед стартом проверяет RAM/swap, после старта сверяет SQLite chunks и Qdrant points.
- **Memory guard fix:** `swap_pct=0.0` больше не трактуется как `100.0` в safe-loop и `/api/rag/parse-scheduler`.
- **Dataset status fix:** limited parse (`limit=1`) возвращает dataset в `IDLE`, а не оставляет его в `PARSING`.
- **Контрольный прогон:** после перехода micro-index увеличил состояние до `indexed_files=5`, `pending_files=796`, `chunks=529`, `qdrant.points=529`, `points_match_sqlite_chunks=true`.
- **Проверки:** `uv run pytest` → `97 passed`; `git diff --check` и `docker compose config --quiet` → OK.

### Ключевые изменения v3.6 (No-Docker runtime + guarded qwen indexing, 25.05.2026)
- **Docker удалён из штатного контура:** Docker Desktop/OrbStack, Docker helper/LaunchDaemons, CLI symlinks и пользовательские Docker data/cache удалены. Остался только macOS-protected пустой `~/Library/Containers/com.docker.docker` metadata-каталог, не являющийся runtime.
- **Qdrant local binary:** Qdrant запускается напрямую через LaunchAgent `me.ovc.les.qdrant`, binary `/Users/ovc/.local/bin/qdrant`, storage `data/qdrant/`, порты `6333/6334`.
- **Host autostart:** активные LaunchAgents: `me.ovc.les.qdrant`, `me.ovc.les.proxy`, `me.ovc.les.mlx`, `com.les.sovushka`, `me.ovc.les.qwen-index-until-done`; `me.ovc.les.pauk` сохранён как stopped fallback.
- **Indexer watch:** qwen indexing идёт через `tools/qwen_index_until_done.py` с `batch_limit=1`, memory guard, active-job guard и hourly heartbeat-watch.
- **GUI/diagnostics cleanup:** диагностика и обзор больше не вызывают `docker ps`; Docker runtime отображается как intentionally removed.

### Ключевые изменения v4.0 (Hybrid Structural-Semantic, 31.05.2026)
- **Microsoft MarkItDown**: Интегрирован универсальный офисный парсер для презентаций (`.pptx`), Word-документов (`.docx`, `.doc`), таблиц (`.xlsx`, `.xls`) и XML-схем с автоматическим mammoth/pandas fallbacks.
- **MLX GLM-OCR (Visual RAG)**: Нативный визуальный OCR на базе мультимодальной VLM-модели `mlx-community/GLM-OCR-4bit` для отсканированных или пустых PDF. Интегрирован механизм агрессивной очистки Metal GPU памяти (`mlx.core.metal.clear_cache()`) и сборщика мусора Python после каждого пакета страниц.
- **Google LangExtract**: Построен механизм извлечения строгих требований по Pydantic-схеме `EngineeringRule` (субъект, параметр, оператор, численное значение, единица измерения, дополнительные условия) с привязкой к точным символьным координатам в тексте чанка.
- **SQLite Таблица `structured_rules`**: Интегрировано реляционное хранилище извлеченных требований в SQLite метабазу с индексами по документам и файлам для быстрого структурированного поиска.
- **Изолированные тесты**: Написаны верификационные тесты в песочнице `scratch/` для MarkItDown, LangExtract и GLM-OCR.

- **Table query MVP:** `proxy/services/table_query_service.py` читает `.parquet` по `parquet_path` из Qdrant payload и считает суммы/количества без генерации LLM. Ответ возвращается как `VERIFIED` с полем `table_query`.
- **Startup hardening:** legacy compose path в `les.command` ждёт Docker daemon и прекращает старт при ошибке compose.
- **Историческая проверка v3.4:** `uv run pytest` → `82 passed`; `git diff --check` → OK.

### Ключевые изменения v3.5 (Runtime stabilization + micro-indexing, 23.05.2026)
- **Docker Desktop снят с критического пути:** система переведена на OrbStack; штатный compose поднимает только `les-qdrant`.
- **Host-proxy:** `les-proxy` вынесен из Docker и запускается через LaunchAgent `me.ovc.les.proxy`; SQLite `data/les_meta.db` больше не работает через VM bind mount.
- **Docker-proxy opt-in:** сервис `proxy` в `docker-compose.yml` оставлен только под profile `docker-proxy`.
- **Host URLs:** локальный runtime использует `MLX_URL=http://127.0.0.1:8080` и `QDRANT_URL=http://127.0.0.1:6333`; Docker overrides сохранены в compose.
- **Safe micro-indexing:** `tools/rag_safe_parse_loop.py` индексирует `batch=1`, перед стартом проверяет RAM/swap, после старта сверяет SQLite chunks и Qdrant points.
- **Memory guard fix:** `swap_pct=0.0` больше не трактуется как `100.0` в safe-loop и `/api/rag/parse-scheduler`.
- **Dataset status fix:** limited parse (`limit=1`) возвращает dataset в `IDLE`, а не оставляет его в `PARSING`.
- **Контрольный прогон:** после перехода micro-index увеличил состояние до `indexed_files=5`, `pending_files=796`, `chunks=529`, `qdrant.points=529`, `points_match_sqlite_chunks=true`.
- **Проверки:** `uv run pytest` → `97 passed`; `git diff --check` и `docker compose config --quiet` → OK.

### Ключевые изменения v3.6 (No-Docker runtime + guarded qwen indexing, 25.05.2026)
- **Docker удалён из штатного контура:** Docker Desktop/OrbStack, Docker helper/LaunchDaemons, CLI symlinks и пользовательские Docker data/cache удалены. Остался только macOS-protected пустой `~/Library/Containers/com.docker.docker` metadata-каталог, не являющийся runtime.
- **Qdrant local binary:** Qdrant запускается напрямую через LaunchAgent `me.ovc.les.qdrant`, binary `/Users/ovc/.local/bin/qdrant`, storage `data/qdrant/`, порты `6333/6334`.
- **Host autostart:** активные LaunchAgents: `me.ovc.les.qdrant`, `me.ovc.les.proxy`, `me.ovc.les.mlx`, `com.les.sovushka`, `me.ovc.les.qwen-index-until-done`; `me.ovc.les.pauk` сохранён как stopped fallback.
- **Indexer watch:** qwen indexing идёт через `tools/qwen_index_until_done.py` с `batch_limit=1`, memory guard, active-job guard и hourly heartbeat-watch.
- **GUI/diagnostics cleanup:** диагностика и обзор больше не вызывают `docker ps`; Docker runtime отображается как intentionally removed.

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
| **С.А.М.О.В.А.Р.** | Система Автономной Машинной Обработки Внутренних Архивов RAG | Ядро RAG: Qdrant + LlamaIndex + bge-m3 | ✅ Live |
| **Т.О.С.К.А.** | Терминал Оценки, Самопроверки и Контроля Архитектуры | CRAG-валидация, фильтр галлюцинаций | ✅ Live |
| **С.О.В.У.Ш.К.А.** | Система Обработки и Выдачи: Умная, Шаблонизированная, Классифицированная, Автоматизированная | UI на NiceGUI (порт 8051) | ✅ v5.0 (Модульная) |
| **П.Р.О.Р.А.Б.** | Программа Регулярной Оценки Работы Автономной Базы | Метрики, диагностика, `/api/metrics` | ✅ Live |
| **Д.И.А.Г.Н.О.З.** | Диспетчер Инфраструктурного Анализа Готовности, Нагрузки, Ошибок и Здоровья | Живая карта контура, `/api/diag` | ✅ Live |
| **К.О.Т.** | Куратор Отраслевой Терминологии | Семантический фильтр инженерного языка | 🔨 В разработке |
| **В.О.Л.К.** | Внутренний Охранный Локальный Контур | RBAC, ключи доступа (SQLite) | ✅ Live |
| **П.А.У.К.** | Периметровый Автономный Узел Коммуникаций | VPS-relay: Caddy + ZeroTier mesh | ✅ Live |
| **С.У.Х.А.Р.И.К.** | Система Управления Холодными Архивами и Резервными Источниками Комплекса | Снапшоты Qdrant, бэкапы | 🔨 В разработке |
| **Е.Ж.И.К.** | *(расшифровка уточняется)* | Обработка почты IMAP/EML | ⏳ Запланирован |

### П.А.У.К. — детали

**Состав:**
- **VPS** — Debian 13, `<public-vps-ip>`, ZeroTier `<relay-vpn-ip>`
- **ZeroTier** — self-hosted сеть `<vpn-network-id>`, подсеть `<trusted-vpn-cidr>`
- **Caddy** — reverse proxy с автоматическим HTTPS (Let's Encrypt)
- **DNS** — `<your-domain>` → `<public-vps-ip>`

**Топология (live, v2.9+):**
```
Интернет → <your-domain> → Caddy (VPS :443)
                             ├── /api/* → <app-host-vpn-ip>:8050 (les-proxy на Mac)
                             └── /*     → <app-host-vpn-ip>:8051 (С.О.В.У.Ш.К.А. на Mac)
                                              │
                             Mac Mini (Ж.А.Б.А.) — <app-host-vpn-ip>
                                  ├── :8050 les-proxy / API / RAG
                                  ├── :8051 NiceGUI UI
                                  ├── :6333 Qdrant
                                  └── :8080 MLX Host
```

**ZeroTier:**
- VPS: `<relay-vpn-ip>`, Mac Mini: `<app-host-vpn-ip>`, сеть `<vpn-network-id>`
- VPS не запускает приложение и не хранит runtime-состояние; Caddy ходит к Mac Mini по `<app-host-vpn-ip>:8050/8051`.

**SSH туннель (резерв, не активен):**
```
~/Library/LaunchAgents/me.ovc.les.pauk.plist  — НЕ удалять, использовать как fallback
# Запустить при необходимости: launchctl load ~/Library/LaunchAgents/me.ovc.les.pauk.plist
# На время аварии переключить Caddy на 127.0.0.1:8050 / 127.0.0.1:8051
```

**VPS systemd-сервисы:**
```
caddy.service      — Caddy (автозапуск, Let's Encrypt)
zerotier-one.service
```
`les_proxy.service` и `sovushka.service` на VPS должны быть `disabled/inactive`.
SQLite, storage, Qdrant, MLX, RAG и UI живут только на Mac Mini.

**`/etc/caddy/Caddyfile`** (репо: `deploy/pauk/Caddyfile`)**:**
```caddyfile
<your-domain> {
    reverse_proxy /api/* <app-host-vpn-ip>:8050
    reverse_proxy /* <app-host-vpn-ip>:8051
}
```

**Деплой Caddy на VPS:**
```bash
bash deploy/pauk/deploy.sh   # Caddyfile → VPS; app-сервисы выключены
```

**В.О.Л.К. — доступ:**
| Откуда | Ключ | Роль |
|--------|------|------|
| Localhost (`127.0.0.1`, `::1`) | не нужен | `TRUSTED_NETWORK_ROLE`, по умолчанию `admin` |
| ZeroTier (`<trusted-vpn-cidr>`) при прямом доступе к сервисам | не нужен | `TRUSTED_NETWORK_ROLE`, по умолчанию `admin` |
| `<your-domain>`, если Caddy видит клиента как `<private-vpn-ip>` | не нужен | Caddy ставит `X-LES-Trusted-Network: 1`; proxy/UI доверяют заголовку только от `TRUSTED_PROXY_NETWORKS` |
| Интернет / внешний контур через VPS (`<your-domain>`) | нужен | `user` или `admin` по записи в `auth_keys` |

Ключи хранятся в `/root/les_v2/data/les_meta.db`, таблица `auth_keys`. Боевые значения ключей в документацию не заносить; управлять через UI В.О.Л.К. или `/api/auth/keys*`.

---

## 3. АРХИТЕКТУРА СИСТЕМЫ

### 3.1. Стек (текущий)
```
Mac Mini M4 / 24 GB  (Ж.А.Б.А.)
│
├── Host LaunchAgents
│   ├── me.ovc.les.proxy    (FastAPI, порт 8050) — Л.Е.С. ядро, RAG, CRAG, API
│   ├── me.ovc.les.qdrant   (Qdrant, порт 6333)  — С.А.М.О.В.А.Р. векторная база
│   └── me.ovc.les.qwen-index-until-done — guarded qwen indexing loop
│
├── MLX Native Host (FastAPI, порт 8080) — основной LLM + Embeddings на Metal
│   ├── Qwen3-14B-4bit             (main, RAG, TTL 300с)
│   ├── Qwen3-4B-4bit              (val, Т.О.С.К.А.+реранкер, TTL 120с)
│   ├── GLM-OCR-4bit               (ocr, ленивый OCR на GPU Metal)
│   └── bge-m3                      (embed, постоянно в памяти)
│
├── Ingestion & OCR Pipelines
│   ├── Microsoft MarkItDown        (универсальный офисный конвертер с fallbacks)
│   ├── MLX-Native GLM-OCR          (распознавание сканированных/пустых PDF)
│   └── Google LangExtract          (извлечение EngineeringRule в SQLite)
│
└── С.О.В.У.Ш.К.А. (NiceGUI, порт 8051) — UI v5.0+
    ├── /            — AI ЧАТ, история, артефакты, расширенный запрос
    └── /les         — ОБЗОР, С.А.М.О.В.А.Р., П.Р.О.Р.А.Б., КВАДРАНТ, Д.И.А.Г.Н.О.З., В.О.Л.К.
```

> **Примечание v2.2:** Ollama полностью выведен из основного пайплайна. `sovushka/config.py` содержит `MLX_URL = "http://127.0.0.1:8080"` как единственный LLM-бэкенд. Ollama остаётся установленным как аварийный резерв.

### 3.2. Поток данных (SafeRAG v2.7)
```
Запрос → /api/chat
  → clarification gate: широкий запрос → NEEDS_CLARIFICATION + вопросы
  → dataset_filter resolve (имя → UUID)
  → Qdrant retrieve (bge-m3 embeddings, top-k=8)
  → [опц.] Реранкер (Qwen3-4B batch, 1 вызов) → top-5
  → _concentrate_sources(): top-2 документа по max-score, min_score=0.45
  → table query gate: parquet_path + табличный запрос → VERIFIED из Parquet без LLM
  │
  ├─ Попытка 1: нормальный промпт, 12 000 симв., top-2 docs
  │     → MLX Host main-модель генерирует ответ
  │     → Т.О.С.К.А. /api/validate (Qwen3-4B)
  │         VERIFIED  → ответ клиенту ✓
  │         NO_DATA   → "нет данных" ✓
  │         HALLUCINATION → переход к попытке 2
  │
  └─ Попытка 2: строгий промпт, 6 000 симв., top-1 doc
        → MLX Host main-модель генерирует ответ
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
├── proxy_server.py           # Тонкий ASGI entrypoint: app = create_app()
├── proxy/                    # LES Proxy v3: app/security/services/storage/...
│   ├── app.py                # create_app(), startup, middleware, router wiring
│   ├── legacy_app.py         # compatibility shim для старых импортов
│   ├── routers/              # auth, chat, datasets, runtime, diagnostics, jobs, logs
│   ├── security.py           # RequestUser, X-API-Key/Bearer, role guards
│   ├── services/             # JobService, retrieval, SafeRAG policy
│   │                          # clarification gate, table query service
│   └── storage/              # safe upload paths, source-folder validation
├── sovushka_ng.py            # Точка входа С.О.В.У.Ш.К.А. v5.0 (~90 строк)
├── sovushka/                 # Модульный пакет UI (страницы, компоненты, стейт)
│   ├── config.py             # PROXY_URL, MLX_URL, UI_PORT
├── mlx_host.py               # MLX Native Host (порт 8080)
├── start_mlx.command         # Запуск MLX через uv run
├── stop_mlx.command
├── qdrant_launchd.plist      # host LaunchAgent для Qdrant :6333/:6334
├── qwen_index_launchd.plist  # host LaunchAgent для guarded qwen indexing
├── proxy_launchd.plist       # host LaunchAgent для les-proxy :8050
├── docker-compose.yml        # legacy/archived Docker fallback, не штатный runtime
├── Dockerfile.proxy          # legacy/opt-in Docker proxy image
├── requirements.txt
├── .env                      # LLM_MODEL, EMBED_MODEL, MLX_URL, QDRANT_URL, TRUSTED_NETWORKS...
│
├── backend/
│   ├── __init__.py
│   ├── interface.py          # Контракт RAGBackend / DatasetInfo
│   ├── smart_index.py        # verify_source_file(), smart plan
│   ├── document_router.py    # deterministic route_document()
│   ├── parquet_writer.py     # XLSX/CSV/PDF tables → Parquet + row chunks
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
    key_value TEXT PRIMARY KEY,
    holder_name TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT 'user',       -- "admin" | "user"
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    expires_at TEXT DEFAULT NULL,
    device_fingerprint TEXT DEFAULT NULL
);
CREATE TABLE chat_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    question TEXT,
    answer TEXT,
    sources TEXT,             -- JSON-массив ссылок
    crag_status TEXT,         -- VERIFIED | NO_DATA | HALLUCINATION
    latency_sec REAL,
    tokens INTEGER,
    session_id TEXT DEFAULT NULL
);
CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    status TEXT NOT NULL,
    source TEXT DEFAULT '',
    dataset_id TEXT DEFAULT '',
    dataset_name TEXT DEFAULT '',
    total INTEGER DEFAULT 0,
    processed INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    message TEXT DEFAULT '',
    result TEXT DEFAULT '',
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE structured_rules (
    id          TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    file_key    TEXT NOT NULL,
    chunk_id    TEXT NOT NULL,
    subject     TEXT NOT NULL,
    parameter   TEXT NOT NULL,
    operator    TEXT NOT NULL,
    value       REAL NOT NULL,
    unit        TEXT NOT NULL,
    condition   TEXT,
    char_start  INTEGER NOT NULL,
    char_end    INTEGER NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
| Mac Mini M4 / 24 GB (Ж.А.Б.А.) | Сервер Л.Е.С. | <app-host-vpn-ip> | — | macOS |
| MacBook Air | Клиент / управление | <client-vpn-ip> | — | macOS |
| Lenovo Legion | Клиент / управление | <client-vpn-ip> | — | Windows 11 |
| VPS box-925292 (П.А.У.К.) | Relay, HTTPS, Caddy | <relay-vpn-ip> | <public-vps-ip> | Debian 13 |

ZeroTier Network: `<vpn-network-id>` | UDP 9993 | self-hosted controller

### 4.2. Порты сервисов
| Порт | Сервис | Описание |
|---|---|---|
| **8050** | les-proxy (host LaunchAgent) | Л.Е.С. API Gateway |
| **8051** | sovushka_ng.py | С.О.В.У.Ш.К.А. NiceGUI UI |
| **8080** | mlx_host.py (native) | MLX LLM + Embeddings |
| **6333** | Qdrant local binary (`me.ovc.les.qdrant`) | Qdrant векторная база |
| **11434** | Ollama (native) | Резервный LLM |
| **443** | Caddy (П.А.У.К.) | HTTPS <your-domain> |

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
| main_engine | `mlx-community/Qwen3-14B-4bit` | 300с | RAG |
| val_engine | `mlx-community/Qwen3-4B-4bit` | 120с | Т.О.С.К.А. + реранкер |
| embed | `BAAI/bge-m3` | ∞ | Эмбеддинги (постоянно) |
| ocr_engine | `mlx-community/GLM-OCR-4bit` | lazy | Визуальный OCR / VLM (с Metal GPU cache cleaning) |

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
- **Qdrant local binary** — `/Users/ovc/.local/bin/qdrant`, storage `data/qdrant/`; Docker не требуется
- **Ollama** — не требуется для основного контура, только аварийный резерв
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
LLM_MODEL=mlx-community/Qwen3-14B-4bit
EMBED_MODEL=bge-m3
MLX_URL=http://127.0.0.1:8080

MLX_MODEL=mlx-community/Qwen3-14B-4bit
MLX_VAL_MODEL=mlx-community/Qwen3-4B-4bit
RERANKER_ENABLED=false   # включается через переключатель в UI чата

QDRANT_URL=http://127.0.0.1:6333
JWT_SECRET=les_v2_secret_key_change_in_prod
ADMIN_PASSWORD=admin123
TRUSTED_NETWORKS=127.0.0.0/8,::1/128
TRUSTED_NETWORK_ROLE=admin
TRUSTED_PROXY_NETWORKS=127.0.0.0/8,::1/128
# Example for a private deployment:
# TRUSTED_NETWORKS=127.0.0.0/8,::1/128,<trusted-vpn-cidr>
CORS_ALLOWED_ORIGINS=http://localhost:8080,http://127.0.0.1:8080,http://localhost:8050,http://127.0.0.1:8050
LES_ENABLE_DOCKER_CONTROL=false
RAG_UPLOAD_SUFFIXES=.pdf,.docx,.doc,.eml,.msg,.xlsx,.xls,.csv,.json,.jsonl,.md,.txt
MAX_UPLOAD_MB=100
MAX_PST_UPLOAD_MB=2048
SOVUSHKA_STORAGE_SECRET=change_me_to_random_string_32chars
```

> Факт по коду на 21.05.2026: `mlx_host.py` и `env.example` дефолтят `mlx-community/Qwen3-14B-4bit` / `mlx-community/Qwen3-4B-4bit`, а часть исторической документации v2.6 описывает `Qwen3.5-9B-MLX-4bit` / `Qwen3-4B-Instruct-2507-4bit`. Перед деплоем считать источником истины `.env`; если нужен 9B-профиль, его надо явно задать в `.env`.

#### Шаг 4. Запустить Qdrant как host LaunchAgent
```bash
launchctl bootstrap gui/$(id -u) ~/Projects/LES_v2/qdrant_launchd.plist 2>/dev/null || true
launchctl kickstart -k gui/$(id -u)/me.ovc.les.qdrant
curl http://localhost:6333/collections
```

#### Шаг 5. Запустить MLX Host и host-proxy
```bash
chmod +x les.command
.venv/bin/python3 tools/les_runtime_control.py start-core --include-ui
# Проверка
curl http://localhost:8080/api/health
curl http://localhost:8050/api/health
```
> `les-proxy` запускается как LaunchAgent `me.ovc.les.proxy`; Docker-proxy включается только явно через profile `docker-proxy`.

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
# Прокси (host LaunchAgent)
launchctl kickstart -k gui/$(id -u)/me.ovc.les.proxy

# MLX Host
./stop_mlx.command && ./start_mlx.command

# С.О.В.У.Ш.К.А. (просто перезапустить)
# Ctrl+C → python3 sovushka_ng.py
```

### 5.5. Проверка состояния системы
```bash
# LaunchAgents
launchctl list | grep -E 'les|sovushka|qdrant|mlx'

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

# Логи прокси / индексатора
tail -f logs/proxy.log
tail -f logs/qwen_index_until_done.log
```

### 5.6. П.А.У.К. — управление транспортом

**Основной транспорт — ZeroTier (активен):**
```bash
# Проверка связности
ping -c 3 <app-host-vpn-ip>      # с VPS → Mac Mini
ping -c 3 <relay-vpn-ip>     # с Mac Mini → VPS

# Qdrant через ZeroTier
curl -s http://<app-host-vpn-ip>:6333/healthz

# MLX через ZeroTier
curl -s http://<app-host-vpn-ip>:8080/api/health
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
ssh root@<public-vps-ip> "curl -s http://<app-host-vpn-ip>:6333/healthz"

# MLX (ZeroTier)
ssh root@<public-vps-ip> "curl -s http://<app-host-vpn-ip>:8080/api/health"

# HTTPS снаружи
curl -s https://<your-domain>/api/health
```

**Управление VPS-сервисами:**
```bash
ssh root@<public-vps-ip>
systemctl status les_proxy.service sovushka.service caddy.service
systemctl restart les_proxy.service
journalctl -u les_proxy.service -n 20
```

**Добавить ключ доступа (через proxy API):**
```bash
curl -s https://<your-domain>/api/auth/keys \
  -H "X-API-Key: <admin-key>" \
  -H "Content-Type: application/json" \
  -d '{"key_value":"les_new_key","holder_name":"user name","role":"user","expires_days":0}'
```

### 5.7. Runbook — аварийное восстановление

#### ❌ SSH-туннель упал (<your-domain> недоступен)
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
ssh root@<public-vps-ip> "curl -s http://127.0.0.1:8080/api/health"
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

# Если коллекция есть, но RAG не отвечает — проверить host LaunchAgents
launchctl print gui/$(id -u)/me.ovc.les.qdrant
tail -n 50 logs/qdrant.log

# Если данные потеряны — переиндексировать
curl -X POST http://localhost:8050/api/rag/sync/NTD
# Ждать: статус PARSING → INDEXED (~15-30 мин для 800+ файлов)
```

#### ❌ les-proxy в restart loop
```bash
tail -n 50 logs/proxy.log
# Частые причины:
# 1. .env не найден → проверить наличие файла
# 2. Qdrant недоступен → launchctl kickstart -k gui/$(id -u)/me.ovc.les.qdrant
# 3. Ошибка кода → git log, git stash, launchctl kickstart -k gui/$(id -u)/me.ovc.les.proxy
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
ssh root@<public-vps-ip>
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
| `/api/status` | GET | MLX/Qdrant/proxy status, Docker отсутствует в штатном runtime | ✅ no-Docker runtime |
| `/api/settings` | GET/POST | Настройки → .env + restart | — |
| `/api/metrics` | GET | CPU/RAM/RAG/**CRAG v2** | ✅ 3 отдельных rate |
| `/api/diag` | GET | **Полная диагностика 11 чеков** | ✅ Новый |
| `/api/rag/sources` | GET | Папки RAG_Content | — |
| `/api/rag/smart-plan` | GET | Smart audit входящих: accepted/rejected summary, route plan | ✅ v3.4 |
| `/api/rag/sync-smart` | POST | Smart sync по deterministic route в classified indexes | ✅ v3.4 |
| `/api/rag/datasets` | GET/POST | Датасеты | — |
| `/api/rag/datasets/{id}` | DELETE | Удалить датасет | — |
| `/api/rag/datasets` | DELETE | Сброс всех | — |
| `/api/rag/sync/{folder}` | POST | Синк папки | — |
| `/api/rag/upload/{id}` | POST | Загрузка файла | — |
| `/api/rag/upload-smart` | POST | Умная загрузка: classify → `*_Index` → guarded parse | ✅ v3.4 |
| `/api/jobs` | GET | История jobs | — |
| `/api/chat` | POST | RAG-чат + clarification + table query + Т.О.С.К.А. | ✅ `NEEDS_CLARIFICATION`, `table_query` |
| `/api/logs/stream` | GET | SSE логи | — |

**Auth/RBAC факт v3.0:**
- `X-API-Key: <key>` или `Authorization: Bearer <key>` проверяются по SQLite `auth_keys`.
- Без ключа допускаются только IP из `TRUSTED_NETWORKS`; роль задаёт `TRUSTED_NETWORK_ROLE`.
- `user` имеет доступ к чату, истории, чтению статуса/метрик/датасетов; destructive/admin endpoints требуют `admin`.
- `/api/auth/keys`, `/api/auth/keys/toggle`, `/api/auth/keys/reset-device`, `/api/auth/keys/delete` требуют admin. Старый `DELETE /api/auth/keys/{key_value}` оставлен только для совместимости; UI использует body endpoint, чтобы не класть ключ в URL.
- `/api/settings` принимает `llm_model`, `embed_model`, `mlx_url`; рестарт только при `POST /api/settings?restart=true`.

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
- При широком запросе возвращает `crag_status: "NEEDS_CLARIFICATION"`, `clarifying_questions`, `suggested_filters` и не запускает retrieval/LLM.
- При табличном запросе и наличии `parquet_path` в retrieved payload может вернуть `crag_status: "VERIFIED"` и `table_query` без генерации LLM.

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

### 7.5. OOM при индексации больших папок (NTD, 800+ файлов)

**Проблема:** `POST /api/rag/sync/NTD` запускает цикл из 800+ итераций без `await`, блокирует event loop; затем `parse_dataset` пытается встроить все файлы разом через bge-m3 — Load Average 39, Mac Mini неуправляем.

**Решение (v2.8 патч, `proxy_server.py`):**

| Мера | Место | Эффект |
|---|---|---|
| `await asyncio.sleep(0.1)` | конец каждой итерации в `sync_folder` | event loop дышит между файлами |
| `async with _PARSE_SEMAPHORE:` | `sync_folder._run()` | максимум 3 параллельных parse-job |
| `os.nice(10)` | перед `parse_dataset()` | CPU-приоритет ниже UI/API |
| Host LaunchAgents + `batch_limit=1` | launchd + parse scheduler | индексатор не вытесняет MLX/UI из RAM |

**Что НЕ трогать:** `backend/qdrant_adapter.py`, `backend/converter.py`, `mlx_host.py`.

**Критерий успеха:** SYNC NTD (801 файл) не поднимает Load Average выше 5.

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
| 4.5 | Вкладка Д.И.А.Г.Н.О.З. → кнопка запускает чеки | ✅ |
| 4.6 | Живая карта контура окрашивается по результатам | ✅ |
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
| Тест Caddy HTTPS <your-domain> | ✅ |
| SSH туннель: Mac Mini → VPS (Qdrant + MLX) | ✅ |
| В.О.Л.К.: auto-bypass только для configured trusted networks (`127.0.0.0/8`, `::1/128`, `<trusted-vpn-cidr>`) | ✅ |
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
- Вкладка Д.И.А.Г.Н.О.З. (Диспетчер Инфраструктурного Анализа Готовности, Нагрузки, Ошибок и Здоровья): 11 чеков, живая карта контура, лог
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
- **П.А.У.К. — запущен** — VPS Debian 13 (`<public-vps-ip>`), Caddy + Let's Encrypt, `<your-domain>` live
- **SSH reverse tunnel** — Mac Mini → VPS: порты 6333 (Qdrant) и 8080 (MLX), launchd `me.ovc.les.pauk` (выведен из эксплуатации в v2.8, plist сохранён как резерв)
- **В.О.Л.К. — ключи live** — SQLite `auth_keys`, admin/user роли, auto-bypass для ZeroTier IP
- **VPS runtime упразднён** — на VPS остаются только `caddy.service` и `zerotier-one.service`; `les_proxy.service` и `sovushka.service` disabled/inactive
- **С.О.В.У.Ш.К.А.: тема переживает реконнект** — состояние тёмной/светлой темы перенесено из локального dict в `app.storage.user["dark_theme"]`; при WebSocket-реконнекте светлая тема восстанавливается через `ui.timer(0.1, once=True)`
- **С.О.В.У.Ш.К.А.: `--dim` в светлой теме** — цвет исправлен `#656d76` → `#424a53` (контраст 7:1, WCAG AA)
- **П.Р.О.Р.А.Б.: стабилизация DOM** — heavy UI containers обновляются только при изменении данных (`_prev_render` dict); устранено хаотичное переключение вкладок.

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
- **Исторически:** Docker mem_limit `proxy=512m`, `qdrant=1g`; в текущем v3.6 runtime это заменено host LaunchAgents и guarded indexing.
- **Реранкер batch-режим:** top_k 20→8, mode sequential→batch (1 вызов вместо 20, ~100с→~5с)
- **Переключатель реранкера в UI чата** — по умолчанию выключен (`RERANKER_ENABLED=false`)

### ✅ v2.8 (19.05.2026)
- **П.А.У.К. — ZeroTier как основной транспорт** — SSH reverse tunnel выведен из эксплуатации; `QDRANT_URL` и `MLX_URL` на VPS теперь указывают на ZeroTier IP Mac Mini (`<app-host-vpn-ip>`); plist туннеля сохранён как резерв
- **deploy/pauk/** — инфраструктура VPS добавлена в репо: `les_proxy.service`, `sovushka.service`, `Caddyfile`, `.env.example`, `deploy.sh`
- **VPS синхронизирован с репо** — rsync Mac Mini → VPS, proxy_server.py обновлён до текущей версии
- **OOM-защита sync_folder** — `await asyncio.sleep(0.1)` в цикле файлов + `_PARSE_SEMAPHORE` + `os.nice(10)` перед `parse_dataset`; индексация NTD (801 файл) больше не убивает систему (см. раздел 7.5)

### ✅ v3.0 (21.05.2026)
- **Proxy v3 package** — добавлен пакет `proxy/`; `proxy_server.py` сокращён до entrypoint, контейнер монтирует `./proxy:/app/proxy`.
- **В.О.Л.К. server-side** — admin endpoints защищены на уровне FastAPI dependencies: `/api/auth/keys*`, destructive `/api/rag/*`, `/api/settings`, `/api/warmup`, `/api/rerank`.
- **С.О.В.У.Ш.К.А. → Proxy auth** — UI API-клиент передаёт `X-API-Key` из `app.storage.user`; local/configured trusted bypass даёт роль `admin` без ключа.
- **Settings safety** — `/api/settings` принимает только allowlisted поля, валидирует `MLX_URL`, рестарт только явно через `?restart=true`.
- **SafeRAG UNKNOWN policy** — timeout/500 валидатора больше не пропускает неподтверждённый ответ пользователю.
- **Diagnostics safety** — `/api/diag` проверяет MLX health вместо вызова `/api/chat`.
- **Relative paths in RAG** — `backend/qdrant_adapter.py` принимает `relative_path`; sync не схлопывает вложенные папки.

### ✅ v3.1 Stabilization (21.05.2026)
- **Regression tests:** добавлен `pytest.ini` и `tests/test_proxy_security.py`; проверяются trusted local/configured private network admin, внешний IP без ключа → 401, admin/user key roles, user → 403 на admin guard, disabled/expired key → 401.
- **Default alignment:** `proxy/config.py` fallback `LLM_MODEL` приведён к `mlx-community/Qwen3-14B-4bit`; host runtime использует `MLX_URL=http://127.0.0.1:8080`.
- **VPS env alignment:** `deploy/pauk/.env.example` использует `MLX_URL`, `TRUSTED_NETWORKS`, `TRUSTED_NETWORK_ROLE`, `SOVUSHKA_STORAGE_SECRET`.
- **VPS UI service:** `deploy/pauk/sovushka.service` теперь читает `EnvironmentFile=/root/les_v2/.env`, как заявлено в runbook.

### ✅ v3.6 Qwen Embedding Index Run (23.05.2026)
- **Embedding profiles:** добавлен `backend/rag_config.py`; активный профиль выбирает модель, API model name, Qdrant collection, SQLite meta DB, vector size и chunk geometry.
- **Qwen profile:** `LES_EMBED_PROFILE=qwen`, `EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B`, `EMBED_MODEL=qwen3-embedding-0.6b`, `RAG_COLLECTION_NAME=les_rag_qwen3_06b`, `RAG_META_DB_PATH=./data/les_meta_qwen.db`.
- **BGE baseline сохранён:** legacy `les_rag` / `data/les_meta.db` не смешивается с Qwen-векторами.
- **Qwen chunk density:** профиль Qwen использует `1400/100` вместо BGE `900/80`; на первых 18 общих файлах Qwen дал `2045` chunks против `3306` у BGE (`ratio=0.619`).
- **Index-until-done:** добавлен `tools/qwen_index_until_done.py` и LaunchAgent `me.ovc.les.qwen-index-until-done`; runner ждёт активный scheduler и запускает следующие waves до `pending_files=0`.
- **П.А.У.К. emergency fallback:** при отказе ZeroTier-доступа VPS→Mac Caddy временно переключён на `127.0.0.1:8050/8051`, которые публикуются через reverse SSH tunnel. `start_pauk.command` исправлен на `ssh -f -n -N`.
- **Проверки:** `pytest -q`, import smoke `proxy_server`/`sovushka_ng`, `compileall`, `docker compose config --quiet`.

### ✅ v3.2 Legacy retirement (21.05.2026)
- **Proxy modularization завершён:** активные endpoints вынесены из `proxy/legacy_app.py` в routers/services; `legacy_app.py` теперь только compatibility shim.
- **SafeRAG chat router:** `/api/chat` живёт в `proxy/routers/chat.py`, retrieval вынесен в `proxy/services/retrieval_service.py`.
- **Runtime honesty:** mail/parquet endpoints не подключены к FastAPI runtime; черновики сохранены как материал для будущего редизайна.
- **Проверки:** `pytest -q`, `compileall`, import smoke `proxy_server`/`sovushka_ng`, route smoke без `/api/mail/*`, `docker compose config --quiet`.

### ✅ v3.4 Smart intake + table query (23.05.2026)
- **Smart source audit:** `verify_source_file()` и `/api/rag/smart-plan` дают bounded summary по rejected без огромных списков.
- **Smart upload:** `/api/rag/upload-smart` классифицирует одиночный upload и отправляет его в нужный classified index.
- **Clarification router:** `proxy/services/clarification_service.py` защищает chat от широких запросов до retrieval/LLM.
- **Table query service:** `proxy/services/table_query_service.py` читает Parquet artifact из `storage/datasets/{dataset_id}/_parquet/...` и считает точные суммы/количества.
- **Startup guard:** legacy compose path в `les.command` больше не продолжает запуск при недоступном Docker daemon.
- **Историческая проверка v3.4:** `uv run pytest` → `82 passed`; `git diff --check` → OK.
- **Runtime stabilization:** Qdrant остался в OrbStack/Docker, `les-proxy` вынесен на host LaunchAgent `me.ovc.les.proxy`, Docker-proxy переведён в opt-in profile.
- **Micro-indexing:** безопасный `batch=1` через `tools/rag_safe_parse_loop.py`; контроль после перехода: `indexed_files=5`, `pending_files=796`, `chunks=529`, Qdrant points `529`, `points_match_sqlite_chunks=true`.
- **Golden set v1:** `tools/rag_golden_set.py` проверяет `/api/rag/retrieve-debug` по базовым NTD-вопросам из `golden/ntd_golden_set.json` без запуска LLM.
- **Indexing mode v1:** `/api/indexing-mode` включает ресурсный режим индексации: выгружает MLX-модели, ставит chat generation на паузу и отдаёт приоритетный порядок `NTD_FIRE → GKRF → NTD_ELECTRICAL → NTD_STRUCTURAL → TABLE_SMETA → NTD_OTHER`.
- **Parse phase timing:** `parse_dataset` возвращает `timings` по фазам `convert/chunk/embed/upsert/count`; контрольный batch NTD_FIRE показал bottleneck в `embed_sec`.
- **Memory hysteresis:** `parse-scheduler` умеет post-batch stop по `post_batch_min_free_gb/post_batch_max_swap_pct`, а `warm_embedder=true` держит BGE-M3 между короткими batch-ами и выгружает его в конце.
- **BGE/chunk knobs:** добавлены env `BGE_MODEL`, `BGE_BATCH_SIZE`, `RAG_EMBED_BATCH`, `RAG_CHUNK_SIZE`, `RAG_CHUNK_OVERLAP`, `RAG_PARSE_POST_MAX_SWAP_PCT`.
- **Финальный runtime snapshot:** `indexed_files=9`, `pending_files=792`, `chunks=850`, Qdrant points `850`, `points_match_sqlite_chunks=true`, `errors=0`; режим `chat`, chat generation allowed.
- **Проверки v3.5:** `uv run pytest` → `107 passed`; `git diff --check`; live `/api/indexing-mode` и `/api/health`.

### Старт следующей сессии
- Провести **независимую оценку архитектуры** перед дальнейшим кодингом.
- Проверить отдельно: Resource Governor, MLX/BGE memory model, scheduler strategy, RAG quality gates, границы chat/indexing mode, документацию операторских процедур.
- Не начинать новые фичи до списка архитектурных рисков и приоритетов.

### 🛠 v3.6 (Краткосрочно)
| Задача | Описание |
|---|---|
| **Indexing mode polish** | Persistent progress, UI status, аварийный auto-return в chat mode |
| **Parse scheduler v3** | Backoff, пауза при swap, persistent progress, автоостановка при mismatch |
| **NiceGUI timers** | Убрать/обернуть timers, которые стреляют после удаления parent slot |
| **Runtime watchdog polish** | Единый status для LaunchAgents `proxy/mlx/sovushka` и Qdrant |
| **Table query v2** | Фильтры по `code/name/section`, группировки, top rows, сравнение смет/спецификаций |
| **UI table query** | Показывать `table_query.rows` как таблицу в панели артефактов |
| **RAG quality hardening** | Выполнять по `RAG_MODERNIZATION_PLAN.md`: baseline golden set, query instructions, hybrid dense+sparse/RRF, retrieval evaluator, conditional reranker |
| **RAPTOR/GraphRAG-lite** | После baseline: parent retrieval, summary layers и лёгкий граф `document -> clause -> referenced norm -> topic`; полный GraphRAG не запускать без доказанной пользы |
| **Embedding bottleneck** | После завершения qwen indexing: benchmark `RAG_EMBED_BATCH`, chunk profiles и hash-cache; не увеличивать concurrency вслепую |
| **Folder Watcher** | Автосинк новых файлов из RAG_Content/ |
| **Е.Ж.И.К. v1** | Спроектировать заново: EML/MSG/PST/IMAP ingest, privacy model, тесты на реальных письмах |
| **Golden set** | Расширить v1 retrieval set до 5-10 живых NTD-вопросов с проверкой ответов `/api/chat` после каждого indexing milestone |

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
- После правок `.py` → перезапустить нужный host LaunchAgent (`me.ovc.les.proxy`, `com.les.sovushka`, `me.ovc.les.mlx`)
- `git status` перед стартом, `git checkout <commit> -- <file>` для отката

### Claude (Клодыч)
Работает через claude.ai. Контекст между сессиями — через `SESSION_SUMMARY.md`.
Обновлять `SESSION_SUMMARY.md` в конце каждой сессии!

---

## ПРИЛОЖЕНИЕ А — Текущее состояние индексов (25.05.2026)

```
Runtime:      no-Docker; Qdrant local binary + host LaunchAgent me.ovc.les.qdrant
Proxy/UI:     me.ovc.les.proxy :8050; com.les.sovushka :8051/:8066
MLX Host:     порт 8080, Qwen3.5 main / Qwen3 validator / Qwen3-Embedding-0.6B embedder
RAG status:   degraded до завершения полного Qwen batch parse
Files:        801 total; Qwen indexing running until pending=0
Chunks:       Qwen writes to les_rag_qwen3_06b; Qdrant points match SQLite chunks
Memory:       parse guard проверяет RAM/swap после каждого файла; runner batch_limit=1
```

> Актуальное состояние — через UI вкладка П.Р.О.Р.А.Б. или:
> ```bash
> curl -s http://localhost:8050/api/metrics | python3 -c \
>   "import sys,json; m=json.load(sys.stdin)['rag']; print(f\"{m['files']} файлов, {m['chunks']} чанков\")"
> ```

**После правок — что перезапускать:**
| Изменён файл | Команда |
|---|---|
| `proxy_server.py`, `proxy/**`, `backend/**` | `launchctl kickstart -k gui/$(id -u)/me.ovc.les.proxy` |
| `mlx_host.py` | `launchctl kickstart -k gui/$(id -u)/me.ovc.les.mlx` |
| `sovushka/**`, `sovushka_ng.py` | `launchctl kickstart -k gui/$(id -u)/com.les.sovushka` |
| `qdrant_launchd.plist` | `launchctl kickstart -k gui/$(id -u)/me.ovc.les.qdrant` |
| `.env` | перезапустить proxy + MLX + UI LaunchAgents |

## ПРИЛОЖЕНИЕ Б — Быстрые команды

```bash
# Аварийно поднять весь host-runtime:
# Qdrant + MLX + proxy + guarded Qwen indexer + UI
./start_les.command

# Локальный launchd-status без proxy
.venv/bin/python3 tools/les_runtime_control.py status

# Остановить контур, оставив С.О.В.У.Ш.К.А. как диспетчерскую
.venv/bin/python3 tools/les_runtime_control.py stop-core

# Поднять контур из CLI
.venv/bin/python3 tools/les_runtime_control.py start-core --include-ui

# Перезапустить только UI LaunchAgent
launchctl kickstart -k gui/$(id -u)/com.les.sovushka

# Статус одной строкой (низкоуровневый)
launchctl list | grep -E 'les|sovushka|qdrant|mlx' && curl -s localhost:8050/api/health && curl -s localhost:6333/healthz

# Диагностика
curl -s localhost:8050/api/diag | python3 -c "import sys,json; d=json.load(sys.stdin); [print(f\"{r['status'].upper():6} {r['name']:30} {r['value']}\") for r in d['checks']]"

# Логи в реальном времени
tail -f logs/proxy.log | grep -E "\[CHAT\]|\[PARSE\]|\[DIAG\]|\[ERROR\]"

# Перезапуск прокси
launchctl kickstart -k gui/$(id -u)/me.ovc.les.proxy

# Остановить индексацию, не трогая Qdrant
launchctl bootout gui/$(id -u)/me.ovc.les.qwen-index-until-done
```

---

📅 **Документ актуализирован:** 25.05.2026 — v3.6 no-Docker host runtime, local Qdrant LaunchAgent, guarded Qwen indexer, hourly watch
📅 **Документ сверян с кодом:** 25.05.2026 — launchd services, active RAG profile config, Qwen runner, Qdrant/SQLite match checks, Sovushka emergency runtime controls
✍️ **Авторы:** Claude (Клодыч) · Qwen (Кен) · Gemini (Панорамыч)
