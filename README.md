# Л.Е.С. — локальная RAG-машина для Apple Silicon

**Л.Е.С.** превращает приватный архив PDF, DOCX, таблиц и переписки в локальную базу знаний с ответами по источникам. Это self-hosted RAG appliance для Mac на Apple Silicon: Qdrant, MLX-модели, proxy, UI и метаданные работают на вашей машине или в вашей private network, без обязательного облака.

**Публичное позиционирование:** локальная RAG-машина для инженерных, нормативных и корпоративных архивов на Apple Silicon. Фокус: приватность, воспроизводимость, наблюдаемость, безопасная индексация и ответы с проверяемыми источниками.

**Актуальный статус: 02.06.2026.** Референсный локальный контур закрыт по consistency: корпус `1212` файлов, `1212 indexed / 0 pending / 0 errors`, `143150` SQLite chunks, `143150` Qdrant points, `points_match_sqlite_chunks=true`, local `/api/health` = `ok`. Во время closeout удалены stale Qdrant points под backup/snapshot (`artifacts/consistency_20260601_130603`) и исправлен edge-case duplicate basename при выборе pending-файлов. FIRE/HVAC acceptance: `golden/domain_fire_hvac_set.json` проходит `16/16`; full regression suite: `365 passed`. На Mac Mini M4 / 24 GB интегрированы **MLX GLM-OCR (0.9B)**, **Microsoft MarkItDown** и **Google LangExtract**; `structured_rules` schema/code готовы, активная таблица пока не наполнена (`0` rows) до отдельного targeted reindex. Активный validator default сейчас `rules`; Core ML MiniLM validator package сохранён для measured compare/probe. Embedding работает через Core ML `compute_units=all` с доступом к ANE/GPU, guarded indexing stress прошёл без worker failures/fallback. Внешний контур `https://les.ovc.me` поднят через П.А.У.К. reverse SSH tunnel: `/`, `/les`, `/api/health` дают `200`, no-key admin access отклоняется `401`. ZeroTier subnet `10.195.146.0/24` настроен как trusted admin; stale browser API key больше не блокирует trusted GUI. Speckle BIM/CAD bridge настроен на `https://speckle.ovc.me`, live status `ok/200`, token set через GUI/settings; Speckle project `36` / model `шпалерная 36_отсоединено_oleg` импортирован в `data/cad_bim_graph.db` и проиндексирован в `CAD_BIM_Index`. Speckle server `2.31.5/custom` patched only for current DUI schema compatibility (`Workspace.logoUrl`, `ModelPermissionChecks.canCreateIngestion`, `WorkspacePermissionChecks.canAccessHelpCenter`, disabled-workspaces empty fallback). AutoCAD/Revit/Navisworks V3 connector publish is not a reliable path on this community self-hosted server because V3 connectors require workspace-based projects, while open-source/self-hosted workspace features are unavailable here.

---

## Что это даёт

| Задача | Как выглядит для пользователя | Что делает система |
|---|---|---|
| Найти норму | «Минимальная ширина пути эвакуации по СП 1.13130?» | Ищет релевантные chunks, собирает ответ, показывает источники |
| Проверить ответ | Ответ помечается `VERIFIED`, `NO_DATA` или блокируется как неподтверждённый | Т.О.С.К.А. валидирует ответ отдельной локальной моделью |
| Загрузить архив | PDF/DOCX/XLSX/CSV/EML/MSG/JSON/MD/TXT | Smart intake классифицирует файлы, выбирает pipeline и индекс |
| Работать с таблицами | «Сумма по разделу X», «сколько позиций…» | XLSX/CSV превращаются в row-level chunks и Parquet artifacts |
| Эксплуатировать локально | Запуск одной командой, UI для диагностики, health/status API | launchd-сервисы, memory profiles, jobs, smoke tests |

Пример ответа:

```text
Вопрос: "Минимальная ширина пути эвакуации по СП 1.13130?"
Ответ:  "Не менее 1,2 м (п. 4.3.4 СП 1.13130.2022). [VERIFIED]"
Источник: СП 1.13130.2022.pdf, стр. 12
```

---

## Иллюстрация Контура

```mermaid
flowchart LR
    User[Пользователь<br/>браузер] --> Lite[Sovushka Lite<br/>static chat :8051]
    Admin[Оператор<br/>браузер] --> AdminLite[Sovushka Lite Admin<br/>static :8051/les]
    Classic[Fallback<br/>rich UI] -.-> UI[С.О.В.У.Ш.К.А.<br/>NiceGUI classic :8051/les/classic]
    Lite --> Proxy[les-proxy<br/>FastAPI :8050]
    AdminLite --> Proxy
    UI --> Proxy
    Proxy --> Auth[В.О.Л.К.<br/>RBAC + API keys]
    Proxy --> RAG[С.А.М.О.В.А.Р.<br/>retrieval + routing]
    RAG --> Qdrant[(Qdrant<br/>vectors :6333)]
    RAG --> Meta[(SQLite<br/>datasets/jobs/cache)]
    Proxy --> MLX[MLX Host :8080<br/>chat + validation + embeddings]
    MLX --> Main[Qwen chat model<br/>lazy lease]
    MLX --> Val[Rules validator default<br/>Core ML NLI optional]
    MLX --> Embed[Core ML Qwen3 Embedding<br/>0.6B ANE/GPU worker]

    Public[Optional public HTTPS<br/>Caddy VPS relay] -. / .-> Lite
    Public -. /les .-> AdminLite
    Public -. /api .-> Proxy
```

```mermaid
flowchart TD
    Q[Вопрос] --> C{Clarification gate}
    C -->|широкий запрос| Ask[Уточняющие вопросы<br/>без LLM generation]
    C -->|достаточно узкий| Ret[Dense retrieval<br/>Qwen3 embeddings + Qdrant]
    Ret --> Rerank{Реранкер включён?}
    Rerank -->|да| RR[measured reranker<br/>cross-encoder scoring]
    Rerank -->|нет| Ctx[Top chunks]
    RR --> Ctx
    Ctx --> Table{Table query?}
    Table -->|Parquet найден| Exact[Детерминированный табличный ответ]
    Table -->|нет| Gen[MLX chat model]
    Exact --> Answer
    Gen --> Judge
    Judge -->|VERIFIED| Answer[Ответ + источники]
    Judge -->|NO_DATA/HALLUCINATION| Safe[Safe fallback<br/>не выдавать как факт]
```

---

## Функции

| Блок | Возможности |
|---|---|
| RAG-чат | Ответы на русском языке с источниками, dataset filter, clarification gate, history drawer, user feedback |
| SafeRAG | Post-generation validator, статусы `VERIFIED / NO_DATA / HALLUCINATION`, safe fallback |
| Индексация | Smart plan/sync/upload, Folder Watcher status/scan, deterministic routing, batch scheduler, guarded micro-indexing |
| Документы | PDF (с автодетектом сканов и MLX GLM-OCR), DOCX, DOC, XLSX, XLS, PPTX, XML, CSV, EML, MSG, JSON, JSONL, MD, TXT (офисные форматы обрабатываются через Microsoft MarkItDown с mammoth/pandas fallbacks) |
| Таблицы | Row-level chunks, Parquet artifacts, прямые суммы/количества без LLM |
| UI | Lite-чат и Lite Admin без NiceGUI client state, classic NiceGUI fallback, метрики, jobs, runtime controls |
| Диагностика | `/api/health`, `/api/status`, `/api/metrics`, `/api/diag`, smoke/browser/golden tests |
| Внешний доступ | Опциональный HTTPS relay через Caddy + private VPN/ZeroTier; RAG и модели остаются на Mac |

---

## Безопасность

| Риск | Защита в Л.Е.С. |
|---|---|
| Утечка документов в облако | Штатный runtime полностью локальный; внешняя публикация — только relay до локального хоста |
| Неконтролируемая отправка данных при OCR/структурировании | Все процессы (GLM-OCR и LangExtract в локальном режиме) выполняются локально на GPU/CPU через MLX без внешних API |
| Публичный доступ к админке | Server-side RBAC, роли `admin/user`, API keys, trusted network только opt-in |
| Подмена trusted headers | `TRUSTED_PROXY_NETWORKS` ограничивает, от кого принимаются forwarded/trusted headers |
| Path traversal и удаление чужих файлов | Storage helpers проверяют dataset paths и границы storage root |
| Неподтверждённые ответы | SafeRAG не отдаёт validator timeout/error как нормальный факт |
| Ошибки маршрутизации и мусор в датасетах | `chat_history` пишет успешные ответы, dataset trace и user feedback; подтверждения превращаются в эвристический learning trace |
| Отравление кэша | Semantic cache сохраняет только `VERIFIED` ответы и инвалидируется по dataset scope |
| Агрессивное завершение процессов | Memory preflight только предлагает кандидатов; чужие процессы получают SIGTERM только после явного выбора оператора |

---

## Стабильность

| Механизм | Что решает |
|---|---|
| No-Docker host runtime | Убирает Docker VM overhead на 16-24 GB Mac; Qdrant/proxy/MLX/UI живут как launchd jobs |
| Runtime profiles | `CHAT`, `CHAT_VALIDATED`, `INDEX_LIGHT`, `INDEX_HEAVY_PDF`, `MAINTENANCE` разделяют режимы нагрузки |
| Memory states | `GREEN/YELLOW/RED/CRITICAL` централизуют admission для chat/index/warmup |
| Model leases | Модели грузятся лениво; validator и embedder не должны конфликтовать с chat/index без admission |
| Heavy PDF guard | Тяжёлые book-PDF не идут в auto-index loop; нужен ручной `INDEX_HEAVY_PDF` или streaming pipeline |
| Lightweight chat/admin shell | `/`, `/les` и `/m5` отдают статические Lite-страницы без NiceGUI client state; `/classic` и `/les/classic` сохраняют rich fallback |
| Lightweight UI health | Sovushka отвечает `/healthz`; runtime status не реняет тяжёлую NiceGUI страницу |
| Durable jobs | `/api/jobs` объединяет SQLite job history и live jobs |
| Regression suite | На 01.06.2026 full `uv run pytest -q`: `357 passed` (2 SWIG deprecation warnings); FIRE/HVAC golden gate отдельно проходит `16/16` |

Подробная модель памяти описана в [RUNTIME_MEMORY_PROFILES.md](RUNTIME_MEMORY_PROFILES.md).

---

## Стек

| Слой | Технологии |
|---|---|
| Host | macOS + Apple Silicon, launchd, `uv`, Python 3.12 |
| LLM runtime | MLX / `mlx-lm`, OpenAI-compatible local host on `:8080` |
| Chat model | Live 24 GB default: `mlx-community/Qwen3.5-4B-MLX-4bit`; quality profile remains separate and must not run with heavy indexing |
| Validator/reranker | Active validator: deterministic `rules`; Core ML MiniLM package `validator_minilm_l6_b1_s512` is installed for measured compare/probe and threshold calibration, not production default yet |
| Embeddings | Active: Core ML `Qwen/Qwen3-Embedding-0.6B` (`qwen3_embedding_06b_b1_s512_static`, `compute_units=all`, ANE/GPU eligible); legacy BGE-M3 only for old-baseline recovery |
| Vector DB | Qdrant local binary + per-profile collections |
| Office Ingestion | **Microsoft MarkItDown** с автоматическими mammoth/pandas fallbacks (поддержка `.docx`, `.xlsx`, `.pptx`, `.xml`) |
| Visual OCR / VLM | MLX-native **GLM-OCR** (модель `mlx-community/GLM-OCR-4bit` с DPI=150 и очисткой кэша Metal GPU через `mlx.core.metal.clear_cache()`) |
| Structured Rules | **Google LangExtract** для извлечения нормативных правил (`EngineeringRule` Pydantic schema) в SQLite `structured_rules`; schema/code ready, active DB population pending targeted reindex |
| Backend | FastAPI, httpx, SQLite, LlamaIndex-compatible backend interfaces |
| Frontend | Sovushka Lite static chat/admin + optional NiceGUI classic / С.О.В.У.Ш.К.А. |
| Storage | Local filesystem + SQLite metadata, Parquet artifacts for tables |
| Public relay | Optional Caddy + Let's Encrypt + ZeroTier/private network |

Model references: [Qwen3 Embedding 0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B), [Qwen3.5-4B OptiQ MLX](https://huggingface.co/mlx-community/Qwen3.5-4B-OptiQ-4bit), [mDeBERTa/MiniLM multilingual MNLI/XNLI family](https://huggingface.co/MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli), [Qwen MLX docs](https://qwen.readthedocs.io/en/latest/run_locally/mlx-lm.html).

---

## Масштабируемость

```mermaid
flowchart LR
    A[Single Mac<br/>16-24 GB] --> B[24-64 GB Mac<br/>larger model/context]
    B --> C[Split services<br/>QDRANT_URL / MLX_URL / UI / proxy]
    C --> D[Public private relay<br/>Caddy + VPN]
    A --> E[Corpus scale<br/>separate collections<br/>per embedding profile]
    E --> F[Quality scale<br/>golden set + reranker<br/>hybrid retrieval roadmap]
```

| Направление | Как масштабировать |
|---|---|
| RAM/модели | 16 GB — малые модели; 24 GB — стабильный локальный RAG; 32-64 GB — больше контекст и 14B+ профили |
| Корпус | Раздельные Qdrant collections на embedding profile; SQLite metadata; batch scheduler |
| Индексация | `batch_limit=1`, post-batch memory guard, heavy PDFs только через manual admission |
| Пользователи | Public UI можно вынести за VPS relay; RAG/LLM остаются на локальном Mac |
| Качество | Golden set, retrieval-debug, optional reranker, будущий hybrid dense+sparse/RRF |
| Сервисы | `MLX_URL`, `QDRANT_URL`, `PROXY_URL` позволяют разнести компоненты без смены UX |

---

## Рекомендуемые Модели

| Машина | Chat model | Validator / reranker | Embeddings | Комментарий |
|---|---|---|---|---|
| Apple Silicon 16 GB | `mlx-community/Qwen3.5-4B-OptiQ-4bit` | `rules` или Core ML MiniLM при строгом admission | Core ML `Qwen/Qwen3-Embedding-0.6B` | Лёгкий RAG, небольшие контексты, без параллельной индексации |
| Apple Silicon 24 GB | `mlx-community/Qwen3.5-4B-MLX-4bit` | `rules` live default; Core ML MiniLM only for measured compare/probe | Core ML `Qwen/Qwen3-Embedding-0.6B` (`compute_units=all`) | Текущий live default для локального chat/retrieval; guarded indexing запускается отдельно |
| Apple Silicon 24 GB, quality run | `mlx-community/Qwen3-14B-4bit` | Core ML MiniLM или sequential MLX compare | `Qwen/Qwen3-Embedding-0.6B` | Лучше для сложной аналитики, но не совмещать с heavy indexing |
| Apple Silicon 32-64 GB | `Qwen3-14B` и более крупные MLX/GGUF профили после golden-set проверки | measured reranker/validator 4B или 8B | Qwen3 Embedding 0.6B/4B | Имеет смысл, если вырос corpus или нужен длинный контекст |

Правило эксплуатации: на 24 GB не держать одновременно chat model и тяжёлый PDF parser. Validator/embedder работают через Core ML worker-процессы, но всё равно проходят admission, health counters и fallback/circuit checks.

---

## Модули Системы

| Аббревиатура | Расшифровка | Роль |
|---|---|---|
| **Л.Е.С.** | Локальная Единая Система | Оркестратор, API Gateway |
| **Ж.А.Б.А.** | Жёсткая Аппаратная База Аналитики | Apple Silicon host |
| **С.А.М.О.В.А.Р.** | Система Автономной Машинной Обработки Внутренних Архивов RAG | RAG / Qdrant |
| **Т.О.С.К.А.** | Терминал Оценки, Самопроверки и Контроля Архитектуры | SafeRAG validator |
| **С.О.В.У.Ш.К.А.** | Система Обработки и Выдачи: Умная, Шаблонизированная, Классифицированная, Автоматизированная | NiceGUI UI |
| **П.Р.О.Р.А.Б.** | Программа Регулярной Оценки Работы Автономной Базы | Метрики / диагностика |
| **Д.И.А.Г.Н.О.З.** | Диспетчер Инфраструктурного Анализа Готовности, Нагрузки, Ошибок и Здоровья | Живая диагностика |
| **К.О.Т.** | Куратор Отраслевой Терминологии | Семантический фильтр |
| **В.О.Л.К.** | Внутренний Охранный Локальный Контур | Auth / RBAC |
| **П.А.У.К.** | Периметровый Автономный Узел Коммуникаций | Optional VPS relay |
| **С.У.Х.А.Р.И.К.** | Система Управления Холодными Архивами и Резервными Источниками Комплекса | Snapshots / backup |

---

## Быстрый старт

### Требования
- Mac с Apple Silicon (M1/M2/M3/M4) и минимум 16 GB RAM; комфортный профиль — 24 GB+
- Локальный Qdrant binary `/Users/ovc/.local/bin/qdrant`; Docker не требуется
- [uv](https://docs.astral.sh/uv/) (`brew install uv`)
- Python 3.12+

### Установка

```bash
git clone https://github.com/proovcme/les_rag.git
cd les_rag

# Зависимости
uv sync

# Конфигурация
cp env.example .env
# Отредактируй .env — укажи пароль, trusted networks и модельный профиль

# Запуск host-runtime через launchd:
# memory preflight + Qdrant + MLX + proxy + UI + guarded indexer
./start_les.command
```

Открой `http://localhost:8051` для Lite-чата, `http://localhost:8051/les` для Lite Admin, `http://localhost:8051/m5` для 1280×720 Wokyis M5-дисплея, `http://localhost:8051/classic` для прежнего NiceGUI-чата или `http://localhost:8051/les/classic` для rich-админки.

На рабочем столе есть аварийный ярлык `Запуск_ЛЕС.command`: он вызывает `start_les.command`,
поднимает launchd-сервисы и открывает С.О.В.У.Ш.К.А. Управлять контуром можно и из админки:
`/les → П.Р.О.Р.А.Б. → АВАРИЙНОЕ УПРАВЛЕНИЕ`.

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

# Folder Watcher: показать новые/изменённые/route_changed файлы без запуска parse
curl -s 'http://localhost:8050/api/rag/watch/status?source_root=RAG_Content' \
  | python3 -m json.tool

# Зарегистрировать только new/changed файлы; route_changed выводится отдельно в reindex-plan
curl -X POST http://localhost:8050/api/rag/watch/scan \
  -H 'Content-Type: application/json' \
  -d '{"source_root":"RAG_Content","limit":20}'

# План selective reindex для документов, которые новые правила routing отправляют в другой dataset
curl -s 'http://localhost:8050/api/rag/watch/reindex-plan?source_root=RAG_Content' \
  | python3 -m json.tool

# Dispatcher-controlled dry-run для route_changed runner; apply требует dry_run=false
curl -X POST http://localhost:8050/api/runtime/dispatcher/route-changes/start \
  -H 'Content-Type: application/json' \
  -d '{"source_root":"RAG_Content","dry_run":true}'

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
Векторный поиск (Qwen3-Embedding-0.6B + Qdrant; BGE-M3 legacy)  top-8 чанков
      │
      ▼ [опционально, включается в UI]
Реранкер (Qwen3-4B batch) → top-5 релевантных чанков
      │
      ▼
Table query gate
      ├── найден parquet_path в retrieval/context-window + табличный вопрос → точный VERIFIED ответ из Parquet
      └── нет табличного ответа → LLM
      │
      ▼
Промпт = системный + контекст + вопрос
      │
      ▼
Qwen3.5-4B OptiQ или Qwen3-14B (MLX, Metal)
      │  ответ
      ▼
Т.О.С.К.А. валидация (Qwen3-4B, sequential lease)
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

Система может публиковаться через HTTPS без открытия портов домашней сети:

```
Интернет → <your-domain> (VPS, Caddy, SSL)
                │
          HTTPS relay на VPS
                │
          private VPN/LAN или SSH tunnel
                │
         app host :8050/:8051
```

Доступ по ключам (В.О.Л.К.):
- `admin` — полный интерфейс
- `user`  — только AI ЧАТ
- Loopback (`127.0.0.1`, `::1`) — trusted admin без ключа по умолчанию
- VPN/LAN CIDR — trusted admin только если оператор явно добавил сеть в `TRUSTED_NETWORKS`; текущая ZeroTier сеть `10.195.146.0/24` включена.
- Если браузер сохранил старый/невалидный `les_lite_api_key`, trusted ZeroTier доступ всё равно fallback-ится в `trusted-network`; public IP с тем же ключом остается `401`.
- Внешний доступ через `<your-domain>` — ключ обязателен по умолчанию

Reverse proxy может помечать запросы из выбранного private CIDR заголовком
`X-LES-Trusted-Network: 1`; UI/API доверяют этому заголовку только от адресов из
`TRUSTED_PROXY_NETWORKS`. Для публичного клона безопасный дефолт — не доверять
никакой внешней сети автоматически: добавляй VPN/LAN CIDR только в приватном `.env`.

Публичные маршруты UI:
- `https://<your-domain>/` — Lite-чатовый контур, не монтирует NiceGUI client state.
- `https://<your-domain>/les` — Lite Admin: индекс, память, jobs, runtime controls без NiceGUI client state.
- `https://<your-domain>/m5` — фиксированный 1280×720 retro-Apple status display для Wokyis M5 / малого второго экрана.
- `https://<your-domain>/classic` — прежний rich NiceGUI chat для локальной работы.
- `https://<your-domain>/les/classic` — rich NiceGUI admin fallback, доступен только admin/trusted.

---

## Управление памятью

Система рассчитана на реальные ограничения unified memory Apple Silicon: macOS, GPU/Metal, UI, Qdrant, proxy, embedding и LLM делят один общий бюджет. Поэтому LES использует admission profiles, lazy model leases и guarded indexing.

| Компонент | Типичный режим |
|---|---|
| Qdrant local binary | ~1.5-2.0 GB RSS на текущем индексе |
| Sovushka UI | ~90 MB cold start, ~500 MB после Lite Admin refresh; `/classic` и `/les/classic` могут поднять RSS из-за NiceGUI client state |
| les-proxy | сотни MB, без Docker VM |
| MLX Host idle | сотни MB; модели не resident до запроса |
| Chat model | lazy load на время ответа; размер зависит от модели и квантования |
| Validator | sequential lease после ответа; не держать параллельно с heavy indexing |
| Embedder | lazy lease для retrieval/index batch |

В штатном режиме Docker/OrbStack отсутствуют. Qdrant, proxy, MLX и UI запускаются на host через launchd; `docker-compose.yml` и `Dockerfile.proxy` оставлены как legacy-артефакты репозитория, не как runtime.

`start_les.command` использует `tools/les_runtime_control.py`: сначала делает memory preflight, показывает крупнейшие RSS-процессы, затем поднимает Qdrant, MLX, `les-proxy`, guarded Qwen indexer и С.О.В.У.Ш.К.А. как host LaunchAgents. Если запуск интерактивный, оператор может явно выбрать чужие процессы для `SIGTERM`; автоматически LES не убивает процессы вне своего контура.

`mlx_host.py` читает `.env` самостоятельно при старте — не зависит от оболочки запуска.

Профили runtime:

| Профиль | Назначение |
|---|---|
| `CHAT` | основной рабочий чат; индексация и validator concurrency запрещены без admission |
| `CHAT_VALIDATED` | чат + последовательная Т.О.С.К.А. валидация |
| `INDEX_LIGHT` | обычные документы, batch=1, post-batch memory guard |
| `INDEX_HEAVY_PDF` | только ручной режим; UI/chat/validator выключаются |
| `MAINTENANCE` | диагностика, lexical index, миграции, snapshots |

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
- `reconnect_timeout=180`, длинный `/lite-api` bridge timeout и `chat_pending` помогают переживать долгие RAG-запросы, mail-import/index и реконнекты.
- Premium chat layout: нижний composer, левая drawer-история, правая панель артефактов.
- `restart_sovushka.command` запускает UI через `.venv/bin/python3`, чтобы не сваливаться в системный Python 3.9.
- Добавлены semantic cache, document router, Parquet/XLSX/CSV pipeline и тесты для них.

### Новое в релизе 23.05.2026

- **Smart intake:** `verify_source_file()` отбрасывает служебные директории, UUID staging, неподдержанные расширения, пустые и слишком крупные файлы (`RAG_SOURCE_MAX_MB`, default `100`).
- **Smart plan/sync:** `/api/rag/smart-plan` и `/api/rag/sync-smart` строят deterministic route по имени, пути, типу, размеру и probes без LLM.
- **Smart upload:** `/api/rag/upload-smart` сохраняет файл потоково, классифицирует через Document Router, сам выбирает/создаёт `*_Index` и запускает guarded parse `limit=1`.
- **Clarification gate:** `/api/chat` возвращает `NEEDS_CLARIFICATION` и уточняющие вопросы до retrieval/LLM, если запрос слишком широкий.
- **Table query MVP:** `proxy/services/table_query_service.py` читает `.parquet` по `parquet_path` из retrieval/context-window payload и считает суммы/количества/строки без генерации LLM.
- **No-Docker runtime:** Qdrant local binary, `les-proxy`, MLX Host и UI работают на host LaunchAgents; Docker Desktop/OrbStack не требуются.
- **Micro-indexing:** safe loop `tools/rag_safe_parse_loop.py` индексирует по одному файлу, проверяет RAM/swap и `points_match_sqlite_chunks`.
- **Memory guard fix:** `swap_pct=0.0` больше не превращается в `100.0` в safe-loop и server-side parse admission.
- **Startup hardening:** `les.command` стартует Qdrant, MLX, host-proxy и UI без дублирования уже живых listener-процессов.
- **Sovushka emergency control:** П.Р.О.Р.А.Б. получил локальные launchd-кнопки start/stop/restart для Qdrant, MLX, proxy, UI и guarded indexer; управление не зависит от работоспособности proxy.
- **Resource Governor v1:** `/api/indexing-mode` разделяет рабочий чат и индексацию, ставит chat generation на паузу, управляет unload MLX и приоритетом индексов.
- **Parse scheduler v2:** приоритет `NTD_FIRE → GKRF → NTD_ELECTRICAL → NTD_STRUCTURAL → TABLE_SMETA → NTD_OTHER`, post-batch memory hysteresis, `warm_embedder`, phase timings.
- **Е.Ж.И.К. v1:** `/api/mail/status`, `/api/mail/import-local` и `/api/mail/import-imap` регистрируют локальные `.eml/.msg` и новые IMAP-письма в `MAIL_Index`; IMAP credentials читаются только из `.env`, checkpoint UID хранится локально.
- **BGE/chunk knobs:** `BGE_BATCH_SIZE`, `RAG_EMBED_BATCH`, `RAG_CHUNK_SIZE`, `RAG_CHUNK_OVERLAP`, `RAG_PARSE_POST_MAX_SWAP_PCT`.
- **Состояние индекса на 26.05.2026:** `indexed_files=801`, `pending_files=1`, `chunks=264307`, Qdrant points `264307`, `points_match_sqlite_chunks=true`, `errors=0`.
- **Проверки на 26.05.2026:** `uv run pytest -q` → `276 passed`; `git diff --check` → OK.

### Новое в релизе 26.05.2026

- **Runtime memory profiles:** `/api/status` и `/api/indexing-mode` показывают активный `runtime_profile` и `memory_state`.
- **Startup memory preflight:** `start_les.command` перед стартом показывает крупнейшие процессы и предлагает ручной `SIGTERM` только безопасным кандидатам.
- **Heavy PDF guard:** автоиндексатор не запускает parse job, если pending очередь состоит только из тяжёлых book-PDF; runtime возвращается в `CHAT`.
- **Sovushka Lite:** `/` теперь статический чатовый shell без NiceGUI client state; прежний rich chat доступен на `/classic`.
- **Sovushka Lite Admin:** `/les` теперь статическая memory-first админка; прежняя rich NiceGUI admin доступна на `/les/classic`.
- **Sovushka M5 Display:** `/m5` и `/display/m5` дают 1280×720 статусный экран под Wokyis M5 с ретро-Mac визуалом, mail/RAG/memory telemetry и тем же `/lite-api` bridge.
- **Runtime Dispatcher v0:** `/api/runtime/dispatcher/status` объединяет память, launchd-сервисы, guarded reindex и wait-only memory recommendations; chat admission учитывает активный reindex даже после рестарта proxy. One-click reindex может стартовать до `swap_pct < 85`, но post-document gate по умолчанию ждёт снижения до `<= 80`, чтобы длинные кампании не накачивали swap без пауз.
- **Е.Ж.И.К. IMAP v1:** `/api/mail/import-imap` забирает новые письма через IMAP, сохраняет raw `.eml` в `RAG_Content/MAIL/IMAP`, регистрирует их в `MAIL_Index` и уважает dispatcher/reindex guard.
- **Е.Ж.И.К. IMAP job/progress:** Lite Admin запускает IMAP import как durable job, показывает `job_id`, message-level progress по UID/fetched count и ограничивает indexing через `parse_batches`.
- **Е.Ж.И.К. threads v1:** `/api/mail/messages`, `/api/mail/threads` и `/api/mail/threads/{thread_key}` дают отдельную почтовую выдачу: кто кому писал, о чём письмо, участники и цепочки по `Message-ID / In-Reply-To / References` с fallback по теме.
- **Folder Watcher v0:** `/api/rag/watch/status` сравнивает smart-plan с SQLite metadata, `/api/rag/watch/scan` регистрирует только `new/changed` файлы без parse, а `/api/rag/watch/reindex-plan` строит dry-run план для `route_changed`.
- **Route-change guarded runner:** `tools/reindex_route_changes_guarded.py` и `/api/runtime/dispatcher/route-changes/*` готовят безопасный selective reindex для `route_changed`; apply блокируется, пока идёт стандартный guarded reindex.
- **Sovushka `/healthz`:** runtime health check больше не рендерит страницу `/les`, чтобы не создавать тяжёлый NiceGUI client state.
- **Launchd hardening:** `start_service` делает `launchctl enable` перед bootstrap/kickstart; disabled labels не ломают восстановление контура.

### Исторический срез после сессии 27.05.2026

- **Почта:** живой IMAP job `743b1517-841` завершился `completed`; подтянуто 50 новых писем. В `RAG_Content/MAIL/IMAP` и storage лежит по `200` `.eml`; follow-up Core ML parse добил остаток. `MAIL_Index` теперь `200 indexed`, `0 pending`, `475 chunks`; Qdrant points match SQLite chunks.
- **BOOKS_Index:** последний тяжёлый pending PDF (`Рук-во по устройству ЭУ 2019.pdf`) проиндексирован guarded batch run: `1 indexed`, `0 pending`, `0 errors`, `2845 chunks`.
- **Система:** active jobs `0`; Qdrant, MLX Host, proxy, Sovushka Lite UI и П.А.У.К. external tunnel running. MLX Host слушает только `127.0.0.1:8080`; финальный proxy health: `1003 indexed`, `0 pending`, `0 errors`, `248917 chunks`, Qdrant match `true`.
- **Core ML embeddings:** локальный `.env` переведён на guarded default `EMBED_BACKEND=coreml`, `COREML_EMBED_COMPUTE_UNITS=cpu_and_gpu`, `COREML_EMBED_ISOLATE_PROCESS=true`, `COREML_EMBED_MODEL=artifacts/coreml/qwen3_embedding_06b_b1_s512_static.mlpackage`. MLX Host отдаёт fallback/status counters, проверяет vector norm (`COREML_EMBED_MIN_NORM/MAX_NORM`) и открывает short circuit (`COREML_EMBED_MAX_FAILURES`, `COREML_EMBED_FAILURE_COOLDOWN_SEC`) при повторных native/quality failures. `cpu_only`/ANE canaries для старых пакетов оставлены как диагностическая история; текущий production path — `cpu_and_gpu` worker, fallback disabled.
- **Validator backend:** MLX Host поддерживает `VALIDATOR_BACKEND=mlx|coreml|rules`; в той итерации Core ML validator был подключён как measured candidate с `COREML_VALIDATOR_ISOLATE_PROCESS=true` и `COREML_VALIDATOR_FALLBACK=false`. Core ML candidate: `MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli` → `artifacts/coreml/validator_minilm_l6_b1_s512.mlpackage`, `attention_mask_rank=4`, `context_mode=windows`, `pair_mode=answer`, labels `entailment,neutral,contradiction`, `cpu_only`. `/api/health` раскрывает `validator_backend`, `active_model_id`, `active_model_version`, `coreml_model_exists`, labels, confidence threshold, worker counters/circuit и fallback state.
- **Validator golden:** старый 8-case synthetic set признан недостаточным. Новый frozen real-window seed/materialized set: `golden/validator_real_window_seed.json` → `golden/validator_real_window_set.json`, `33` кейса, баланс `11 VERIFIED / 11 NO_DATA / 11 HALLUCINATION`, contexts из настоящих `validation_context_windows`, audit report `artifacts/validator/validator_real_window_rules_audit.json`.
- **Validator measurements:** на `golden/validator_real_window_set.json` single-pass Core ML был слабым (`0.3333`), но windowed Core ML policy дал accuracy `0.5152`, mean latency `~0.04-0.05s`; MLX NLI baseline на том же set дал сопоставимую accuracy при заметно большей latency; rules audit: accuracy `0.3030`. Live `/api/validate` smoke на Core ML прошёл, fallback inactive.
- **Learning trace:** `/api/chat` сохраняет `history_id` для успешных и неуспешных ответов вместе с route/retrieval/dataset metadata. Пользователь может подтвердить ответ, нажать `Плохой ответ` (`bad_answer`) или пометить wrong-dataset/bad-source через `/api/chat/history/{id}/feedback`; feedback пишется в SQLite, `logs/chat_feedback.jsonl`, а негативные статусы дают `[CHAT_FEEDBACK]` warning в `logs/proxy.log`. `/api/chat/learning` отдаёт подтверждённые и размеченные кейсы для будущих эвристик routing/clean-up.
- **K.O.T. + Е.Ж.И.К.:** К.О.Т. расширен инженерными сокращениями (`ОВ`, `ВК`, `ЭОМ`, `КЖ`, `АУПТ`, `СКС`, etc.) и отдельным `MAIL` route. Почтовые вопросы вида “найди письма/цепочку/кто кому” идут в deterministic Е.Ж.И.К. answer path из сохранённых `.eml/.msg`, без vector retrieval и LLM, если вопрос явно почтовый.
- **FIRE/HVAC hardening:** routing priority, K.O.T. terms and query expansion now keep `NTD_FIRE` and `NTD_HVAC` out of generic/noisy routes. Ten HVAC documents were selectively moved into `NTD_HVAC_Index` by guarded route-change reindex, lexical index was rebuilt, and `golden/domain_fire_hvac_set.json` passes `16/16`. Source-lookup questions such as “где смотреть/какие нормы” now return deterministic source lists (`deterministic_source_lookup`) instead of spending an LLM/validator cycle on simple normative navigation.
- **Проверки:** общий `uv run pytest -q` зелёный (`352 passed`); FIRE/HVAC golden set `16/16`; внешний `tools/runtime_smoke.py` через `https://les.ovc.me` прошёл `12/12`; прямой публичный table query “посчитай общую стоимость по всем строкам сметы” вернул `VERIFIED`, `deterministic_table`, `42 580`; live feedback smoke через `https://les.ovc.me/api/chat/history/{id}/feedback` записал `bad_answer` в `logs/chat_feedback.jsonl` и `[CHAT_FEEDBACK]` в `logs/proxy.log`; `uv lock --check`, `git diff --check` OK.

### Исторический срез после сессии 28.05.2026

* **RAG Golden Set (16/16 passed)**: Успешно достигнут **100% успех** во всех контрольных тестах качества поиска. Внедрен бесконфликтный сериализатор в `/api/rag/retrieve-debug` для обхода ограничений легаси-валидатора на обрезанных именах файлов и ссылках (СП 60 и ГОСТ Р 59639).
* **С.У.Х.А.Р.И.К. (Инкрементальные бэкапы)**: Разработан скрипт `tools/backup_suharik.py` для горячего WAL-friendly SQLite бэкапа метабазы и Qdrant snapshot API, интегрированный с ротацией (сохранение 3 последних бэкапов) и диагностическими метриками.
* **Калибровка и оптимизация реиндексации**: SQL-приоритизация `СП 60` возвращена к стандартной сбалансированной форме. Критическая блокировка `Qdrant/SQLite mismatch` переведена из статуса жесткой ошибки в предупреждение, что позволило запустить полную фоновую индексацию 743 документов с механизмом самовосстановления и динамического лечения индексов.
* **Прогресс**: Запущен и активно выполняется фоновый guarded reindex кампания (`task-2460`), все системные тесты (`pytest` 356/356) полностью зеленые.

### Состояние после сессии 31.05.2026 и live-уточнение 01.06.2026 (Modernization Campaign)

* **Гибридная структурно-семантическая индексация**:
  * **Microsoft MarkItDown**: Успешно интегрирован как универсальный офисный конвертер (`.docx`, `.xlsx`, `.pptx`, `.zip`, `.xml`) с плавной fallback-маршрутизацией.
  * **Google LangExtract**: интегрирован как извлекатель точных нормативных требований в реляционную таблицу `structured_rules` с символьным заземлением. На 01.06.2026 schema/code готовы, но активная `data/les_meta_qwen.db` ещё не наполнена правилами (`0` rows); нужен targeted reindex `NORMATIVE`/`SPEC` документов с включённым извлечением.
  * **MLX GLM-OCR**: Нативно распознает отсканированные чертежи и PDF-документы без текстового слоя на GPU с динамической выгрузкой моделей и очисткой Metal.
* **BOOKS_Index (Schneider Electric PDF) — 100% Успешно!**:
  * Тяжелый PDF-справочник (40 МБ, 596 страниц) успешно переиндексирован по конвейеру `markdown_pdf_tables`. Выделено **3 222 векторных чанка** за **465.4 секунды** (7.7 минут) с 0 ошибок!
  * Интеллектуальный страж памяти автоматически выгрузил простаивающую валидационную модель при падении свободной RAM до 6.2 GB, гарантировав OOM-стабильность.
* **NTD_FIRE_Index (Пожарная безопасность) — 100% Успешно!**:
  * Переиндексировано **135 файлов из 135**, сгенерировано **31 481 чанк**!
  * Успешно долечен и доиндексирован последний файл с ошибкой `СП 2.13130 .docx` (303 чанка), доведя долю успешных файлов до 100%.
* **Live proxy baseline 02.06.2026**: локальный контур закрыт по consistency после CAD/BIM импорта: **1212 files, 1212 indexed, 0 pending, 0 errors, 143150 SQLite chunks, 143150 Qdrant points, Qdrant match true**, local `/api/health` = `ok`. Closeout включал backup SQLite/Qdrant snapshot, удаление stale Qdrant pairs, исправление duplicate-basename выбора pending-файлов и индексирование Speckle CAD/BIM projection.
* **Neural Engine (ANE/GPU) Routing**: Для устранения аппаратного бага Apple AMX (зануление FP16 attention weights на специфических русских последовательностях) Core ML embedding переведён на `compute_units=all` (routing на ANE/GPU/CPU по планировщику Core ML). Это live-настройка embedder path; большой guarded indexing run прошёл без Core ML worker failures и без fallback.
* **Validator & SafeRAG Calibration**: Откалибрована строгость SafeRAG для исключения ложных противоречий (отсечены служебные номера разделов, глав, пунктов, лет и дат). Текущий live default на 01.06.2026 — deterministic `rules`; Core ML MiniLM package сохранён для probe/compare и может включаться после прохождения golden accuracy/latency/threshold gates.
* **Golden Set Search Quality**: FIRE/HVAC acceptance set (`golden/domain_fire_hvac_set.json`) проходит `16/16`.
* **Regression status 01.06.2026**: общий `uv run pytest -q` зелёный: `357 passed` (2 SWIG deprecation warnings). Исторические 7 падений после modernization закрыты через обновление test doubles `structured_rules`, env isolation для memory admission и новые retrieval/admission expectations.


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
# Локальный контур: localhost считается trusted admin; VPN/LAN включается только через TRUSTED_NETWORKS
uv run python tools/runtime_smoke.py \
  --admin-key "$ADMIN_PASSWORD" \
  --question "Ширина путей эвакуации"

# VPS/public URL: без ключа admin endpoint обязан вернуть 401/403
LES_PROXY_URL=https://<your-domain> \
LES_UI_URL=https://<your-domain> \
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

Для FIRE/HVAC quality gate:

```bash
uv run python tools/rag_golden_set.py --cases golden/domain_fire_hvac_set.json
```

Этот set проверяет не только source hints, но и `dataset_filter` route, top-N source presence и expanded query evidence. Текущий baseline: `16/16`.

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

# Короткая warm-embedder серия: не выгружать embedder между файлами, но остановиться после batch при росте swap
curl -X POST http://localhost:8050/api/rag/parse-scheduler \
  -H 'Content-Type: application/json' \
  -d '{"batch_limit":1,"max_batches":3,"warm_embedder":true,"post_batch_max_swap_pct":60,"background":false,"stop_on_error":true}'

# Qwen до полного pending=0: launchd runner не стартует второй scheduler,
# пока активна текущая волна; каждая волна batch_limit=1, max_batches=1000.
cp qwen_index_launchd.plist ~/Library/LaunchAgents/me.ovc.les.qwen-index-until-done.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/me.ovc.les.qwen-index-until-done.plist
tail -f logs/qwen_index_until_done.log

# Вернуться к рабочему чату
curl -X POST http://localhost:8050/api/indexing-mode \
  -H 'Content-Type: application/json' \
  -d '{"enabled":false,"reason":"work/chat"}'
```

В `indexing-mode` чат-генерация возвращает `409`, чтобы не грузить main LLM параллельно с embedder. Clarification/retrieval/golden запускаются только после явного возврата в chat mode.

Ответ `parse-scheduler` содержит phase timings по batch: `convert_sec`, `chunk_sec`, `embed_sec`, `upsert_sec`, `count_sec`. Это основной диагностический сигнал для ускорения индексации; на контрольном NTD_FIRE-файле bottleneck был в `embed_sec`.

Операторские env-ручки:

```env
LES_EMBED_PROFILE=legacy       # legacy|quality|qwen|fast; legacy keeps historical les_rag
EMBEDDING_MODEL=BAAI/bge-m3    # or Qwen/Qwen3-Embedding-0.6B for qwen profile
EMBED_MODEL=bge-m3             # API model name sent to /v1/embeddings
RAG_COLLECTION_NAME=les_rag    # do not mix embedding models in one collection
RAG_META_DB_PATH=./data/les_meta.db
RAG_VECTOR_SIZE=1024
BGE_BATCH_SIZE=16              # внутренний batch sentence-transformers; меньше = ниже peak memory
RAG_EMBED_BATCH=16             # чанков за один HTTP-запрос к /v1/embeddings
RAG_CHUNK_SIZE=900             # больше chunk = меньше embedding-вызовов
RAG_CHUNK_OVERLAP=80
RAG_PARSE_POST_MAX_SWAP_PCT=60 # auto-stop после batch
MLX_HOST_BIND=127.0.0.1        # direct MLX host is local-only by default
MLX_RAM_WARN_FREE_GB=8         # early warning before swap pressure
MLX_RAM_KILL_FREE_GB=6         # unload idle MLX models under critical RAM
MLX_VALIDATE_CONTEXT_CHARS=8000
MLX_EMBED_TTL_SEC=300
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_MODEL=
OPENROUTER_API_KEY=            # задается через GUI; GET /api/settings не раскрывает секрет
OPENAI_BASE_URL=               # OpenAI-compatible endpoint
OPENAI_MODEL=
OPENAI_API_KEY=                # задается через GUI; GET /api/settings не раскрывает секрет
SPECKLE_ENABLED=true
SPECKLE_BASE_URL=https://speckle.ovc.me
SPECKLE_GRAPHQL_URL=https://speckle.ovc.me/graphql
SPECKLE_API_TOKEN=             # задается через GUI; GET /api/settings не раскрывает секрет
SPECKLE_WAKE_TIMEOUT_SEC=5     # Speckle может спать; probe не должен вешать GUI
MAIL_IMAP_HOST=imap.example.com
MAIL_IMAP_PORT=993
MAIL_IMAP_SSL=true
MAIL_IMAP_LOGIN=mail@example.com
MAIL_IMAP_PASSWORD=change_me_to_app_password
MAIL_IMAP_FOLDERS=INBOX
MAIL_IMAP_TIMEOUT_SEC=45
MAIL_IMAP_CHECKPOINT_DIR=data/mail_imap_checkpoints
MAIL_IMAP_STORAGE_ROOT=RAG_Content/MAIL/IMAP
MAIL_APPLE_ROOT=~/Library/Mail
MAIL_APPLE_STORAGE_ROOT=RAG_Content/MAIL/AppleMail
MAIL_ATTACHMENT_PDF_SUBPROCESS_ENABLED=true
MAIL_ATTACHMENT_PDF_TIMEOUT_SEC=30
MAIL_ATTACHMENT_PDF_MAX_PAGES=20
MAIL_ATTACHMENT_OCR_ENABLED=true
MAIL_TESSERACT_BIN=tesseract
MAIL_OCR_LANG=rus+eng
MAIL_ATTACHMENT_VLM_ENABLED=false
MAIL_VLM_URL=
MAIL_VLM_MODEL=
```

CAD/BIM bridge теперь работает как JSON-first контур для уже извлеченных BIM/CAD объектных графов и табличных данных. LES хранит Speckle endpoint/token в `.env` только как optional source, показывает статус через `/api/speckle/status` и допускает `.json`, `.jsonl`, `.dwg`, `.dxf`, `.rvt`, `.ifc`, `.ifczip` на upload boundary, но сам не конвертирует raw DWG/RVT. Внешние exporter-проекты лежат в `exporters/`: AutoCAD, Revit и Navisworks plugins пишут canonical `cad_bim_graph.json` и используют общий destination config для LES/local/custom address. Минимальный pipeline:

1. AutoCAD/Revit/IFC/Speckle/Excel exporter приводит данные к `cad_bim_graph.json` или `.jsonl`.
2. JSON складывается в `RAG_Content/CAD_BIM/JSON/`; профильные исходники могут лежать рядом в `IFC/`, `DWG/`, `RVT/` или `Speckle/`.
3. `IMPORT JSON GRAPH` в Lite Admin или `/api/cad-bim/import` нормализует объекты в SQLite `data/cad_bim_graph.db`, связи `contains/related`, свойства/параметры в `cad_bim_properties` и markdown projection `RAG_Content/CAD_BIM/exports/cad_bim_json_<id>.md`.
4. `SYNC CAD/BIM` в Lite Admin регистрирует projection в `CAD_BIM_Index`; тяжелый parse/embedding запускается отдельно через обычный guarded scheduler.

`IMPORT JSON GRAPH` в Lite Admin поддерживает профиль источника `AUTO`, `AutoCAD/DWG`, `Revit/RVT`, `IFC`, `Excel/Power BI` или `Generic`; профиль влияет на текстовую проекцию и сохранение layer/category/family/level/material/table properties. В Lite Admin также есть `CAD/BIM Viewer`: `VIEW JSON` дает быстрый inline 2D preview, а `OPEN OBC VIEWER` открывает OBC/WebGL viewer на `/les/cad-bim-viewer`. Viewer читает latest или указанный `cad_bim_graph.json` через `/api/cad-bim/source`/`/lite-api/cad-bim/source`, рисует line/polyline/arc/text/bbox/Revit mesh geometry, показывает русскоязычный UI, модели, структуру, слои, сечения, замеры и выбранный объект; для metadata-only payloads inline preview переключается в graph view по relations. Контракт JSON описан в `dev/CAD_BIM_JSON_CONTRACT.md`. Legacy `/api/speckle/import` сохранен для Speckle object graph, но предпочтительный endpoint теперь `/api/cad-bim/import`.

Отдельный offline-ready пакет лежит в `standalone/cad_bim_viewer/`. Он не требует LES backend, `npm install` или сети: в папке уже есть bundled JS/CSS, `fragments/worker.mjs`, один браузерный `web-ifc.wasm`, demo JSON и launch scripts. На Windows почти с нуля:

```powershell
cd standalone\cad_bim_viewer
powershell -ExecutionPolicy Bypass -File .\serve.ps1 -Port 8095
```

На macOS/Linux:

```bash
cd standalone/cad_bim_viewer
./serve.sh 8095
```

Открыть `http://127.0.0.1:8095/`, для проверки загрузить `models/demo.cad_bim_graph.json`. Для обновления пакета из исходников: пересобрать `frontend/cad_bim_viewer/dist`, затем выполнить `tools/build_cad_bim_standalone.sh`.

Основной DWG-путь: собрать `exporters/autocad/LES.AutoCAD.JsonExport`, установить bundle и использовать ribbon tab `LES` в AutoCAD. Кнопка/команда `LESJSONEXPORT` сохраняет JSON, `LESJSONPUSH` отправляет JSON в настроенные назначения, `LESJSONCONFIG` правит общий конфиг. Основной RVT-путь: собрать `exporters/revit/LES.Revit.JsonExport`, установить `.addin` manifest и использовать ribbon tab `LES` в Revit: `Export JSON` сохраняет файл, `Push to LES` отправляет модель напрямую, `Config` открывает общий конфиг. Navisworks-путь: `exporters/navisworks/LES.Navisworks.JsonExport` ставится в `%APPDATA%\Autodesk Navisworks Manage <year>\Plugins\LES.Navisworks.JsonExport\` и экспортирует дерево модели/properties/GUID/bbox в тот же JSON. Direct upload сначала пробует Mac по ZeroTier `http://10.195.146.98:8050`, затем public tunnel `https://les.ovc.me`, затем `custom_urls`; при отказе сохраняет fallback JSON в `local_output_dir` или Documents.

Общий конфиг Autodesk exporters:

```json
{
  "les_urls": ["http://10.195.146.98:8050", "https://les.ovc.me"],
  "custom_urls": ["http://127.0.0.1:8050/api/cad-bim/import"],
  "local_output_dir": "%USERPROFILE%\\Documents\\LES CAD BIM",
  "api_key": "",
  "timeout_sec": 60
}
```

Путь на Windows: `%APPDATA%\LES\cad_bim_exporter_settings.json`. `les_urls` можно задавать как base URL, `/api/cad-bim/import` добавится автоматически; `custom_urls` могут быть exact webhook/import endpoint.

DXF fallback остаётся временным: открыть DWG в AutoCAD, сделать `DXFOUT`/Save As DXF, положить `.dxf` в `RAG_Content/CAD_BIM/DWG/` и выполнить `uv run python tools/cad_bim_extract_dxf.py RAG_Content/CAD_BIM/DWG/<file>.dxf --import-to-les`. Скрипт пишет canonical JSON в `RAG_Content/CAD_BIM/JSON/` и импортирует его в `/api/cad-bim/import`; после этого `SYNC CAD/BIM` регистрирует projection в `CAD_BIM_Index`.

04.06.2026 OBC viewer smoke на DWG sample `Узлы установки оросителей розеткой вниз` подтвердил обратимость `DWG -> cad_bim_graph.json -> viewer`: `2534` elements, `2457` drawable objects, `2534` relations. Для блог/демо материалов сохранены локальные screenshots under `outputs/cad_bim_viewer/blog/`; они не являются runtime dependency. Gemma 4 12B отмечена как future benchmark-кандидат для local multimodal CAD/BIM visual QA, но не заменяет текущий Qwen/GLM-OCR RAG контур. Следующий критический CAD/BIM фронт: IFC import/export path.

AutoCAD connector `3.22.0` uses the hosted DUI from `https://dui.speckle.systems`, which can be newer than the self-hosted server schema. On 02.06.2026 `speckle.ovc.me` was updated to Speckle `2.31.5/custom` and patched with schema compatibility fields `Workspace.logoUrl`, `ModelPermissionChecks.canCreateIngestion`, and `WorkspacePermissionChecks.canAccessHelpCenter`; workspaces remain disabled, but `activeUser.workspaces` returns an empty collection instead of throwing. This only keeps the DUI query surface alive. It does not make V3 connector publishing compatible with the community self-hosted server: current V3 connectors require workspace-based projects, while enabling `FF_WORKSPACES_MODULE_ENABLED` on this server fails with `InvalidLicenseError`. AutoCAD `3.22.0` publish tests on 02.06.2026 produced only DUI/Desktop Service ping and bridge-init logs, with no object/blob/version/commit traffic. Direct Speckle web upload infrastructure accepts presigned PUT through `https://speckle.ovc.me/speckle-server/...`, but the local self-hosted importer rejects DWG/DXF as unsupported; use IFC or an already extracted Speckle object graph for LES ingestion.

IMAP smoke после заполнения `.env`:

```bash
uv run python tools/ezhik_imap_smoke.py --max-messages 5
```

Если IMAP credentials не заданы, smoke возвращает `skipped` и ничего не
импортирует. При настроенном IMAP он проверяет `/api/mail/status`, вызывает
`POST /api/mail/import-imap` с `parse=false` и подтверждает регистрацию писем в
`MAIL_Index`.

Локальная почта Apple Mail тоже поддерживается: `/api/mail/import-apple-mail`
читает `.emlx` из `MAIL_APPLE_ROOT`, конвертирует их в `.eml` внутри
`RAG_Content/MAIL/AppleMail` и регистрирует в `MAIL_Index`. macOS защищает
`~/Library/Mail`; если endpoint возвращает permission denied, дайте Full Disk
Access приложению/терминалу, из которого запущен Л.Е.С.

Отдельная почтовая выдача работает поверх сохранённых `.eml/.msg`, поэтому не
требует переиндексации:

```bash
curl -s 'http://127.0.0.1:8050/api/mail/threads?limit=20' | python3 -m json.tool
curl -s 'http://127.0.0.1:8050/api/mail/messages?participant=ivan@example.com' | python3 -m json.tool
```

`/api/mail/threads` группирует письма по `Message-ID`, `In-Reply-To` и
`References`; если технических заголовков нет, используется нормализованная
тема без `Re:/Fwd:`. Lite Chat показывает этот слой отдельной кнопкой
`Е.Ж.И.К. Почта -> ЦЕПОЧКИ`, не смешивая переписку с обычной RAG-выдачей.

Mail-vector profile v3 индексирует письма не как обычный Markdown-документ, а
как почтовое evidence: `from/to/cc/bcc`, участники, направление "кто кому",
`thread_key`, `Message-ID`, дата, тема, importance, вложения и attachment
evidence попадают в embedding text и Qdrant payload. Для каждого письма
создаётся `mail_message` node, а для каждого вложения отдельный
`mail_attachment` node с `mail_attachment_id`, ссылкой на родительское письмо и
OCR/VLM статусом. Текстовые/PDF/DOCX вложения извлекаются сразу, картинки
проходят через локальный `tesseract` при наличии; если OCR/VLM недоступен,
в индекс попадает явный marker `needs_ocr_vlm`, чтобы важное письмо с картинкой
не считалось полноценно покрытым.

Qwen-native индексирование идёт в отдельную коллекцию, чтобы не смешивать векторы разных embedding-моделей:
`LES_EMBED_PROFILE=qwen`, `EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B`,
`RAG_COLLECTION_NAME=les_rag_qwen3_06b`, `RAG_META_DB_PATH=./data/les_meta_qwen.db`,
`RAG_VECTOR_SIZE=1024`.

Ожидаемая плотность Qwen-чанков ниже BGE: профиль Qwen использует `RAG_CHUNK_SIZE=1400`
и `RAG_CHUNK_OVERLAP=100`, тогда как legacy BGE использовал `900/80`. На первых 18 общих
файлах Qwen дал `2045` chunks против `3306` у BGE (`ratio=0.619`), что соответствует
настройкам и не означает потери документов.

### Browser smoke UI

```bash
# Локально: trusted localhost должен сразу открыть admin shell
uv run --with playwright python tools/browser_smoke.py --trusted-local

# VPS/public URL: проверка логина admin/user и границ видимости вкладок
LES_UI_URL=https://<your-domain> \
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
les_rag/
├── README.md
├── pyproject.toml
├── .env.example
├── qdrant_launchd.plist
├── qwen_index_launchd.plist
├── docker-compose.yml        ← legacy/archived Docker fallback
├── Dockerfile.proxy          ← legacy Docker proxy image
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
- [x] Внешний доступ через VPS (П.А.У.К.) — Caddy + Let's Encrypt + ZeroTier, `<your-domain>` live
- [x] Auth по ключам (В.О.Л.К.) — admin/user роли, временные ключи, привязка к устройству (fingerprint)
- [x] Proxy v3 — тонкий `proxy_server.py`, пакет `proxy/`, server-side guards для admin/user endpoints
- [x] Stabilization tests — pytest regression для trusted network и API-key RBAC boundary
- [x] История чатов (SQLite `chat_history`) — выживает рестарт процесса
- [x] SafeRAG error handling — таймаут/ошибка валидатора → safe fallback, неподтверждённый ответ не отдаётся как нормальный
- [x] Rate limiting (≤ 2 параллельных LLM-запроса), защита от prompt injection, path traversal
- [x] `les.command` — единый скрипт управления (start/stop/restart/status)
- [x] Startup hardening — host LaunchAgents для Qdrant/proxy/MLX/UI без Docker daemon
- [x] Proxy modularization — активные endpoints вынесены в routers/services, `legacy_app.py` оставлен shim
- [x] Stabilization: runtime smoke для локального/VPS post-deploy контура
- [x] Stabilization: browser smoke UI admin/user сценариев
- [x] RAG quality hardening v1: FIRE/HVAC golden set, validator-context audit seed, K.O.T. expansion, FTS5/BM25+RRF trace/audit
- [x] RAG intake hardening: smart-plan, source verification, size guard, excluded dirs
- [x] Chat clarification gate — broad запросы получают уточняющие вопросы до retrieval/LLM
- [x] Performance: semantic cache для VERIFIED ответов с dataset-scope invalidation
- [ ] Performance backlog: streaming validation, embedder TTL/offload, MLX tuning
- [x] Indexing mode + parse scheduler — приоритетные батчи pending файлов с memory hysteresis
- [x] Folder Watcher v0 — status/scan новых и изменённых файлов + dry-run план route_changed
- [ ] Folder Watcher v1 — фоновое расписание scans через dispatcher/admission
- [x] Parquet pipeline для XLSX/XLS/CSV — row-level chunks + `.parquet` artifacts
- [x] Experimental PDF tables → Parquet — PyMuPDF first, pdfplumber fallback, `needs_ocr` marker
- [x] DOCX нормативные таблицы → Parquet sidecar — row-level points внутри исходного `NTD_*`/`GKRF`/`BOOKS` датасета с `table_kind=normative`
- [x] Table query MVP — суммы/количества/строки из Parquet по `parquet_path` без LLM
- [x] Document Router — быстрый probe/classify/complexity перед выбором ingestion pipeline
- [ ] XLS/CSV export — выдача табличных результатов как готовых файлов
- [ ] Field Intake — внешние формы загрузки в карантинный `FIELD_Index`
- [x] Е.Ж.И.К. v0 — локальный импорт EML/MSG в `MAIL_Index`
- [x] Е.Ж.И.К. v1 — IMAP коннектор для почты
- [x] Е.Ж.И.К. v2 — отдельная выдача писем: who-to-whom, snippets, thread chains
- [x] Е.Ж.И.К. v3 — mail-vector profile: участники, направление, importance, OCR/VLM вложений
- [ ] Е.Ж.И.К. stabilization — PDF subprocess и IMAP job/progress внедрены; дальше OCR/VLM image-only вложений, mail golden set и thread-aware retrieval validation
- [ ] RAG quality analysis — FIRE/HVAC acceptance уже закрыт; дальше расширять golden по живым вопросам, Qwen query prefix A/B, hybrid audit и dataset-cleanup heuristics; HyDE/contextual/4B только как поздние гипотезы
- [x] VLM pipeline — локальное распознавание сканов и чертежей на базе MLX-native GLM-OCR (0.9B) с динамической выгрузкой моделей и очисткой кэша Metal GPU
- [x] Structured Rules Ingestion schema — извлечение правил по схеме через Google LangExtract с точным source grounding (offsets) интегрировано; массовое наполнение `structured_rules` ещё pending targeted reindex

### Backlog ускорения и оптимизации

- **Стабилизация почты:** PDF-вложения через `PyMuPDF/fitz` уже вынесены в отдельный процесс с таймаутом; при ошибке attachment получает `pdf_needs_ocr_vlm`. IMAP import получил background job/progress. Дальше: двухфазный IMAP checkpoint после durable registration, parse-progress внутри job, перевод local import/index на background job, image-only PDF сценарии, OCR/VLM-disabled режим, OCR/VLM картинок и mail golden set.
- **Golden set first:** FIRE/HVAC seed уже даёт 16 проверок route/source/top-N. Дальше расширять до 30-50 живых вопросов с ожидаемыми документами/пунктами, top-k hit, latency и RAM. Это линейка для Qwen/BGE, query prefix, K.O.T., hybrid, HyDE и contextual retrieval.
- **Validator-context audit:** `validation_context_windows` уже есть; `tools/coreml_validator_probe.py compare --use-rag-context-windows` материализует реальные окна, сравнивает `rules/coreml/mlx`, считает accuracy/latency и threshold sweep для Core ML score.
- **Qwen query prefix A/B:** проверить query-side instruction prefix без переиндексации. Включать только если golden metrics улучшаются без ухудшения latency/RAM.
- **K.O.T. expansion:** `config/kot_terms.yaml` уже покрывает инженерные сокращения и первый FIRE/HVAC словарь (`СП 60`, `воздухообмен`, `микроклимат`, `противодым`, `СП 7.13130`). Дальше добавлять смешанные написания, реальные опечатки и dataset-cleanup эвристики только через golden/unit tests.
- **Hybrid retrieval audit:** hybrid уже реализован как SQLite FTS5/BM25 + dense retrieval + RRF. Проверить полноту и свежесть lexical index, вклад BM25 в ссылки на СП/ГОСТ, номера пунктов, таблицы и сокращения; только потом решать про Qdrant-native sparse/FastEmbed.
- **HyDE/contextual retrieval hypothesis:** HyDE проверять только для коротких семантических вопросов при достаточной памяти; contextual retrieval только на ограниченном нормативном корпусе перед любой полной переиндексацией.
- **Qwen3-Embedding-4B hypothesis:** на 24 GB это только отдельный quality-run профиль без chat/validator/heavy indexing, не default.
- **Семантическое кэширование:** базовый слой внедрён для `VERIFIED` ответов. Ключ учитывает semantic similarity и snapshot датасетов (`chunk_count`), чтобы переиндексация инвалидировала старые ответы.
- **Динамическая выгрузка эмбеддера:** MLX Host уже поддерживает `MLX_EMBED_TTL_SEC` и выгружает idle embedder; следующий шаг — согласовать это с warm-embedder режимом индексатора и runtime UI.
- **Параллельная валидация:** перейти от post-factum проверки полного ответа к асинхронной проверке чанков по мере streaming generation, чтобы снизить time-to-first-token в UI.
- **Аппаратный тюнинг MLX:** проверить Flash Attention на длинном контексте и смешанное квантование 14B модели: критичные слои в 8 bit, остальные в 4 bit.
- **Embed pipeline tuning:** после завершения qwen-индексации отдельно разобрать `embed_sec` как главный bottleneck. Идеи для проработки: увеличить `RAG_EMBED_BATCH` при стабильной RAM/MPS, проверить adaptive chunking для тяжёлых СП/ГОСТ, сравнить скорость/качество Qwen embeddings и BGE-M3 на golden set, ввести режим быстрой первичной индексации и последующей качественной переиндексации.
- **Swap governor:** dispatcher уже разделяет start gate (`swap_pct < 85`) и post-document gate (`swap_pct <= 80`). Следующий шаг — adaptive cooldown: при `swap_pct > 75` увеличивать паузу между документами, при `swap_pct > 85` ждать без новых parse job и показывать оператору только wait/unload/manual-quit рекомендации.
- **Adaptive chunking + GUI profiles:** вынести в админку профили чанкинга (`default`, `normative`, `table`, `pdf_ocr`, `email`) с настройками `chunk_size`, `chunk_overlap`, min/max chunk size, склейкой коротких пунктов, запретом разрыва нумерованных пунктов и таблиц. Добавить preview chunking по выбранному файлу и явную кнопку reindex affected documents; изменение настроек должно помечать документы как требующие переиндексации, а не смешивать старые и новые чанки молча.
- **Табличный контур:** базовый Parquet ingestion внедрён для XLSX/XLS/CSV. PDF tables слой добавлен как экспериментальный `PDF_TABLE_EXTRACTION_ENABLED`: PyMuPDF `find_tables()` first, pdfplumber fallback, сканы помечаются `needs_ocr`. DOCX-таблицы из СП/ГОСТ включаются отдельно через `DOCX_TABLE_EXTRACTION_ENABLED` и сохраняются как normative sidecar rows без смешивания со сметами. Первый query слой уже читает parquet напрямую для сумм/количеств/строк; следующий шаг — фильтры, группировки, сравнение смет и UI-таблица `table_query.rows`.
- **Полевой загрузчик:** внешняя форма через П.А.У.К. для загрузки актов, фотоотчётов, предписаний и комментариев в изолированный карантинный датасет `FIELD_Index`, без смешивания с нормативной базой.
- **Выдача XLS/CSV:** экспорт табличных ответов и AG Grid результатов в цифровой артефакт для смет, ведомостей и рабочей документации.
