---
name: les
description: Use when working on the local LES_v2 repository, LES runtime, Core ML/MLX/Qdrant/Sovushka/PAUK/VOLK workflows, runtime health, indexing, external les.ovc.me access, docs, tests, or cleanup.
---

# LES Operator Skill

## Workspace

Use `/Users/ovc/Projects/LES_v2` as the project root for development.

## Philosophy / Model-First LES

- **Модель первична:** она читает вопрос, связывает источники, выбирает ход, задаёт уточнения и формулирует ответ. Код не подменяет модель готовыми объектными ответами.
- **Каждый датасет — мини-RAG/блокнот:** inventory, typed memory, reader-pass, file cards и target retrieval должны давать модели условия понять корпус, а не заменять это шаблонами.
- **Код хранит проверяемую память:** граф, факты, версии, provenance, source-map, табличные строки, CAD/BIM-связи и расчёты. Числа считает код; утверждения модели должны опираться на evidence.
- **Запрещены ситуационные костыли:** не добавлять правила вида “если дача/БАИ/столп — сделай X”. Исправлять системный корень: retrieval, memory, typing, prompt, tool contract, graph или calculator.
- **Если ответ съехал на соседний файл/шум:** чинить навигацию, strict target-file retrieval и память датасета; не писать fallback-ответ по похожим источникам.
- **Сметы model-first:** модель раскладывает задачу и выбирает ход; код сопоставляет нормы, проверяет единицы/применимость/provenance и считает ГЭСН/РИМ. Без объектных hardcode-шаблонов.

**Runtime clone:** launchd services (proxy/sovushka/mlx/qdrant) run from **`/Users/ovc/LES`** (подтверждено `WorkingDirectory` в `~/Library/LaunchAgents/me.ovc.les.*.plist` + cwd процесса; origin клона — `LES_v2_reinstall_stress`, не dev-репо). **Клон диверговый** (живые незакоммиченные правки), поэтому деплой = **порт правок файлами**: правка в LES_v2 → `cp`/точечный Edit изменённых файлов в `/Users/ovc/LES` → `launchctl kickstart -k gui/$(id -u)/me.ovc.les.proxy` (и `com.les.sovushka` для GUI). НЕ `git pull` (история расходится). Перед перезаписью файла из dirty-set (`proxy/routers/chat.py`, `datasets.py`, `parquet_writer.py`, `samovar.py`, …) — патчить Edit'ом, не overwrite (есть рантайм-онли диверженция). Editing LES_v2 alone does NOT change the live system.

> ⚠️ **`uv sync` в рантайм-клоне ОБЯЗАТЕЛЬНО с `--extra mac-mlx`** (`uv sync --extra mac-mlx`). `mlx-lm`/`mlx-vlm` — в опциональной группе `mac-mlx` (`[project.optional-dependencies]`); голый `uv sync` (например, после `uv add`) **выкашивает их из venv → MLX-host падает на `ModuleNotFoundError: No module named 'mlx_lm'`** и весь RAG/эмбеддер ложатся. Симптом: `[WARNING] MLX /api/ps error: All connection attempts failed`, ретрив → HTTP 500. Лечение: `uv sync --extra mac-mlx` в клоне + `launchctl kickstart -k gui/$(id -u)/me.ovc.les.mlx`. (Инцидент 2026-06-14.)
>
> ⚠️ **Доп. зависимости рантайма ставились через `uv pip install`, НЕ `uv add`** (чтобы не дёрнуть sync и не выкосить mlx): `libpff-python` (архивы `.pst`, extra `mail-pst`), `mcp` (MCP-сервер, extra `mcp`). Любой `uv sync` их тоже уберёт — после sync либо `uv pip install libpff-python mcp`, либо синкать `--extra mac-mlx --extra mail-pst --extra mcp`. (2026-06-19.)

Current runtime posture:

- **Production target: Legion / Windows.** Canonical stack: Tauri + FastAPI/NiceGUI,
  Ollama `qwen3.5:9b`, Ollama `bge-m3:latest` embeddings, dedicated
  native cross-encoder `BAAI/bge-reranker-v2-m3`, Qdrant Docker container
  `les-light-qdrant` with named volume `les-qdrant-data`. Tauri keeps replaceable
  code under `%LOCALAPPDATA%\Programs\LES`, while `.env`, venv, MetaDB,
  `storage`, `RAG_Content`, artifacts and logs persist under `%LOCALAPPDATA%\LES`;
  `installers/windows/state.ps1` owns backup-first idempotent migration/junctions.
  Mac is the development/reference runtime and must not
  silently supply Windows production defaults.
- The endpoints below describe the current Mac reference/public runtime until
  the Legion cutover is explicitly completed.

- Proxy: `http://127.0.0.1:8050`
- Sovushka UI (NiceGUI): `http://127.0.0.1:8051` → `/classic` (чат), `/les/classic` (админка). HTML-шеллы lite удалены (W5.4/5.5): `/` и `/les` редиректят в NiceGUI; мост `/lite-api/*` сохранён.
- MLX Host: `http://127.0.0.1:8080`
- Qdrant: `http://127.0.0.1:6333`
- External: `https://les.ovc.me` through P.A.U.K. reverse SSH tunnel and V.O.L.K. API keys; on 2026-06-01 external smoke passes `12/12`.
- ZeroTier trusted GUI/API access: `TRUSTED_NETWORKS=127.0.0.0/8,::1/128,10.195.146.0/24`, `TRUSTED_NETWORK_ROLE=admin`. Trusted clients should open `/classic`, `/les/classic` and `/lite-api/*` without a key; stale browser keys fallback to `trusted-network`, while public clients still receive `401`.
- **КРИТ для public-401:** `TRUSTED_PROXY_NETWORKS` ОБЯЗАН включать ZeroTier-IP VPS-Caddy — `127.0.0.0/8,::1/128,10.195.146.136/32`. Иначе Mac игнорирует `X-Forwarded-For` + заголовок `X-LES-Trusted-Network` (Caddy ставит `1` для `@zerotier`, `""` для public) и падает на peer-IP Caddy (∈ TRUSTED_NETWORKS) → **весь public-трафик идёт как доверенный admin** (дыра, чинено 2026-06-26). Проверка: `curl -D- https://les.ovc.me/classic` → `307 → /login`; `POST /api/chat` без ключа → `401`. Без ключа пускает только ZeroTier-прямой `10.195.146.98`.

## First Checks

Before changing runtime behavior, inspect:

```bash
cd /Users/ovc/Projects/LES_v2
curl -fsS http://127.0.0.1:8050/api/health | python3 -m json.tool
curl -fsS http://127.0.0.1:8080/api/health | python3 -m json.tool
launchctl list | grep -E 'les|sovushka|qdrant|mlx'
```

Live baseline on 2026-06-01:

- Local consistency is closed: `1212` files, `1212` indexed, `0` pending, `0` errors.
- `143150` SQLite chunks match `143150` Qdrant points; `points_match_sqlite_chunks=true`, local proxy health is `ok`.
- Main model: `mlx-community/Qwen3.5-9B-OptiQ-4bit`. На Mac mini M4/24 ГБ прогретый официальный benchmark `512 input / 384 output` дал `152,5 tok/s` prefill и `11,19 tok/s` decode; uniform 4-bit — `91,1/7,19 tok/s`. Облако остаётся явным выбором через proxyapi.ru; локальная 9B — приватный default.
- Embedder: Core ML `Qwen/Qwen3-Embedding-0.6B`, `qwen3_embedding_06b_b1_s512_static.mlpackage`, `compute_units=all`, isolated worker, fallback disabled.
- Validator live default: deterministic `rules`. Core ML `MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli` package exists for measured compare/probe, not current production default.
- Hybrid retrieval: production default — named `dense` + `bm25_sparse` и Qdrant native `Fusion.RRF`; SQLite FTS остаётся третьим exact-word/file safety channel перед общим rerank/context expansion. Любая новая production generation создаётся только с `les.rag.index-contract.v2`; обычный parse без совместимого contract запрещён, а named-point без обоих vector channels не записывается. Полный перенос выполняется переэмбеддингом через `tools/build_rag_contract_sibling.py`; долгий resume запускает `tools/rag_generation_supervisor.py` как bounded-retry launchd job. Обязательны remote embedder identity, source/child/exclusion accounting, canonical dataset payload, полный FTS, live filtered RRF каждого dataset и только затем атомарный Qdrant+SQLite alias switch. Noise без BM25-токенов получает audited exclusion, а не synthetic token. Текущий runtime остаётся lexical-only до завершения clean generation; fail-closed guard не обходить.
- **Полный clean rebuild (0.24.0.385):** рантайм использует стабильные aliases `les_rag` и `les_smeta_norm_cards`; номера поколений не протекают в конфигурацию потребителей. Общий `les_rag` активирован на `les_rag_qwen3_06b_native_v2` после `34/34` filtered live RRF и полного `258 367/258 367` dense+sparse/fingerprint+FTS gate; сметный alias указывает на `les_smeta_norm_cards_v3`. Readiness валидирует live embedder по model/backend из immutable generation contract, а не по runtime default. Старые поколения сохраняются до подтверждённого production smoke и известного rollback.
- **Системные датасеты модулей (0.24.0.352):** MetaDB identity `dataset_scope=system` + `module_id`. `SMETA_SERVICE_Index`, `SMETA_RU_NORM_*` и `GESN_NORMS_2022_PDF` принадлежат модулю `smeta`, показываются отдельно в scope и автоматически добавляются только к smeta-turn. Test-only `TABLE_SMETA_Index` удалён 2026-07-10: active Qdrant `690`, canary `310`, FTS `690`, MetaDB `103`, storage; системные ГЭСН/ФГИС source files сохранены. Generated `SMETA_SERVICE/**` регистрировать в `SMETA_SERVICE_Index`, не в проектный/table dataset; parse только после совместимого production index contract.
- Reranker (W2.2): cross-encoder `BAAI/bge-reranker-v2-m3` via `POST /v1/rerank` (MLX host on Mac or local `sentence_transformers` backend on Windows; lazy/TTL, separate from the answer-model semaphore). Windows bootstrap runs `tools/onboard_reranker.py`: resumable Hub download, exact SHA-256, corrupt-weight quarantine, semantic model-load probe and atomic verification marker. Do not publish or manually rename a partial weight to `model.safetensors`; rerank readiness requires the verified marker for the unchanged file.
- **Скан-OCR: локальный путь — `RAG_OCR_BACKEND=tesseract`** (бинарь `brew install tesseract tesseract-lang`, `rus+eng`, зовётся subprocess'ом → НЕ конфликтует с venv/MLX). Прочитал русский акт котельной чисто; RapidOCR не годен (нет кириллицы), Surya 0.20 требует llama.cpp + ломает transformers. `backend/ocr_parser.TesseractOCRParser` + `make_ocr_parser`. **Важно:** `converter._parse_pdf` теперь на сканах (нет текстового слоя) сразу зовёт наш OCR, минуя встроенный eng-OCR pymupdf4llm (он давал латинскую кашу на кириллице). Env: `RAG_OCR_TESSERACT_LANG/DPI/PSM/BIN`. Cloud-OCR дорог; gemma-12B на OCR душит чат (двойная работа) → снято на tesseract.
- Visual OCR (скан-PDF, старый VLM-путь): `RAG_OCR_BACKEND=ollama`, модель `gemma4:12b` (vision/грязный вход; GLM-OCR удалён). `backend/ocr_parser.make_ocr_parser` → `OllamaVisualOCRParser` (OpenAI-совместимый vision на `OLLAMA_BASE_URL`, как mail-VLM путь). MLX-VLM путь сохранён под `RAG_OCR_BACKEND=mlx` (явная MLX-VLM модель). Деградация мягкая, если vision недоступен.
- Office Ingestion: Microsoft MarkItDown with graceful fallbacks to mammoth/pandas.
- Structured Rules: Google LangExtract schema extraction to SQLite `structured_rules` table with exact character offsets; active table is expected to be empty until targeted `NORMATIVE`/`SPEC` reindex populates it.
- CAD/BIM импорт — из локального JSON/JSONL (внешний Speckle-коннектор удалён 2026-06-14). `POST /api/cad-bim/import` принимает inline payload или `source_path` из `RAG_Content/CAD_BIM/JSON`, профили `AUTO/AutoCAD(DWG)/Revit(RVT)/IFC/Excel/Generic`, строит `data/cad_bim_graph.db` (свойства в `cad_bim_properties`) и markdown-проекции в `RAG_Content/CAD_BIM/exports/`; они индексируются в `CAD_BIM_Index`. Вьювер АТЛАС (`/les/cad-bim-viewer`, W5.7), граф и подсветка в чате (`/api/cad-bim/highlight`, W6.7) — работают поверх этого. `.dwg/.rvt/.ifc` конвертируются внешними коннекторами в JSON до импорта.

## Guardrails

- Do not run a full reindex unless the user explicitly asks and the reason is documented.
- Do not delete `data/qdrant/`, `data/les_meta_qwen.db`, `storage/`, or `RAG_Content/`.
- Do not resurrect old BGE or unused MLX validator caches unless a focused benchmark needs them.
- Keep secrets out of git docs. Use environment variables or the operator password manager for V.O.L.K. keys.
- Treat `VALIDATOR_BACKEND=rules` as the current stable live default; re-evaluate Core ML validator only after golden accuracy, latency and confidence-threshold gates are clean.
- Keep `cpu_and_ne` Core ML experiments behind a focused stability gate; previous canaries showed native crash risk.
- Treat FIRE/HVAC quality as a domain acceptance problem, not as one-off answer fixes. Run `uv run python tools/rag_golden_set.py --cases golden/domain_fire_hvac_set.json` after retrieval/router changes; current baseline is `16/16`.
- Preserve the SQLite `structured_rules` table. Do not drop or wipe it unless explicitly executing a targeted structured index rebuild.
- Keep the `_parse_with_markitdown` fallback pipeline intact to guarantee clean mammoth/pandas conversion if python dependencies are altered.
- **MLX VLM OCR Operational Safeguards** (актуально только при `RAG_OCR_BACKEND=mlx`; дефолтный скан-OCR теперь ollama/gemma — см. выше):
  - **AutoImageProcessor / Torchvision Requirement**: Hugging Face `transformers`' `AutoImageProcessor` silently falls back to a plain `TokenizersBackend` if `torchvision` (and `torch`) is missing. This completely disables image feature processing and results in blank OCR. Always list both packages as explicit dependencies in `pyproject.toml` to lock perfectly matched versions (`torchvision==0.25.0`, `torch==2.10.0` on M-series chips) and prevent C++ operator registry mismatches (`RuntimeError: operator torchvision::nms does not exist`).
  - **Template Formatting**: For `GLM-OCR` visual models, always apply the chat template using `apply_chat_template` on the task prompt (e.g. `"Text Recognition:"`) to correctly format and align visual token placeholders `<|image|>` for the language model.
  - **Repetition Mitigation**: In dense document OCR tasks, always pass `repetition_penalty=1.2`, `repetition_context_size=64`, and explicit length constraints like `max_tokens=1024` to prevent infinite token loops at the end of the page text.

## Version / Scope / Sidecar (Unified Construction Harness v0.16–v0.23)

Флаг `LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED` — **OFF по умолчанию** (не менять). Число версии `HARNESS_VERSION` в `proxy/services/version_service.py` — **двигать каждую версию v0.NN** (иначе UI/бейдж отстаёт).

```bash
# что РЕАЛЬНО запущено (app/harness/git_commit ≠ deployed_commit, deploy stamp, alignment, флаги; без секретов)
curl -fsS http://127.0.0.1:8050/api/version | python3 -m json.tool
# область поиска: 28 датасетов (проекты/датасеты/непривязанные/системные)
curl -fsS http://127.0.0.1:8050/api/scope/options | python3 -m json.tool
curl -fsS -X POST http://127.0.0.1:8050/api/scope/resolve -H 'content-type: application/json' \
  -d '{"scope":{"scope_type":"project","project_ids":[2]}}' | python3 -m json.tool
# подготовка документов к поиску (sidecar) — dry-run; запись только env+confirm:
curl -fsS -X POST http://127.0.0.1:8050/api/rag/datasets/<id>/extract-body/dry-run | python3 -m json.tool
```

**Deploy stamp — ⚠ ОБЯЗАТЕЛЬНО после КАЖДОГО cp-деплоя** (иначе `deployed_commit` врёт — реальный инцидент 2026-06-25: выкатил GUI-файл, забыл re-stamp → стамп застрял на старом коммите). Деплой = `cp` файлов в `/Users/ovc/LES` (git HEAD рантайма отстаёт — это норма). Финальный шаг любого деплоя:

```bash
# после cp файлов в /Users/ovc/LES:
uv run python -c "from datetime import datetime,timezone; from pathlib import Path; \
from proxy.services.version_service import write_deploy_stamp; \
print(write_deploy_stamp(dev_root=Path('.'), runtime_root=Path('/Users/ovc/LES'), \
deployed_at=datetime.now(timezone.utc).isoformat(timespec='seconds')))"
# затем рестарт затронутых сервисов: launchctl kickstart -k gui/$(id -u)/me.ovc.les.proxy (и/или com.les.sovushka)
```

`/api/version.deployed_commit` = что реально скопировано; `deploy_stamp.status` (`ok`/`stale`) + `hash_mismatch_files` ловят дрейф по хэшам бандла (вкл. `sovushka/*` с v0.22); `runtime_alignment` = расхождение repo↔runtime.

## Tests

Инвентарь тестов v0.16–v0.23 (~2067 тестов, 218 файлов) — **[docs/TEST_INVENTORY.md](docs/TEST_INVENTORY.md)**. Гейт `make verify` (офлайн); базовый L1 HTTP-смоук — `make smoke-basic` (`tools/basic_function_smoke.py`). Run before finalizing meaningful changes:

```bash
uv run pytest -q
make verify
git diff --check
uv lock --check
```

For public access checks, use an admin key from the environment, not from committed docs:

```bash
uv run python tools/runtime_smoke.py \
  --proxy-url https://les.ovc.me \
  --ui-url https://les.ovc.me \
  --qdrant-url http://127.0.0.1:6333 \
  --admin-key "$LES_ADMIN_KEY" \
  --expect-external-auth
```

## Common Runtime Actions

One-shot runtime health report (W7.2 — ports/RAM/disk/GPU/inference/embedder/cloud-providers/Qdrant collections; offline-safe, names the cause when a service is down; exit 1 on any FAIL):

```bash
uv run lesctl doctor          # human report with [OK]/[WARN]/[FAIL]
uv run lesctl doctor --json   # machine-readable
# legacy platform/profile install checks: uv run lesctl doctor --profile-check
```

Restart proxy after backend changes:

```bash
launchctl kickstart -k gui/$(id -u)/me.ovc.les.proxy
```

Restart MLX Host after model/env changes:

```bash
launchctl kickstart -k gui/$(id -u)/me.ovc.les.mlx
```

Restart Sovushka UI after frontend/static UI changes:

```bash
launchctl kickstart -k gui/$(id -u)/com.les.sovushka
```

If external `les.ovc.me` returns 502 while local services are healthy, check or restart P.A.U.K. reverse tunnel with the project runbook in `dev/TUNNELS_AND_REMOTE_ACCESS.md`.

**GUI-first:** ВОР, нормоконтроль и дифф доступны из админки → вкладка **ИНСТРУМЕНТЫ** (выбор датасета/импортов, кнопки, скачивание xlsx прямо в браузер). CLI-формы ниже — для скриптов/диагностики.

Generate a bill of quantities (ВОР) from indexed specifications (deterministic, no LLM; needs proxy restart after first deploy):

```bash
curl -fsS -X POST http://127.0.0.1:8050/api/bor/<dataset_id>/generate | python3 -m json.tool
# preview: GET /api/bor/<dataset_id>/preview?limit=50 · download: GET /api/bor/<dataset_id>/download
```

Index an external folder **by reference** (in-place, sources NOT copied; path must be inside `LES_EXTERNAL_SOURCE_ROOTS`):

```bash
curl -fsS -X POST http://127.0.0.1:8050/api/rag/index-external -H 'content-type: application/json' \
  -d '{"path":"/abs/external/folder","dataset_id":"<id>","parse":true}' | python3 -m json.tool
# only Qdrant/Parquet/meta land in LES; originals stay external (copied_to_storage=false)
```

Сводка/сумма по любому пользовательскому табличному датасету (сметы/ВОР/КС-2) — **детерминированная SUM по полному Parquet, не LLM** (ADR-11). Передаётся реальный `dataset_filter=<dataset name>`; фиксированного `TABLE_SMETA` больше нет. Поле выбирается по запросу (метраж/объём → qty, стоимость → amount); `.xls` читаются через `xlrd`+конвертацию в `parquet_writer`. Типизированный ретрив норм — за флагом `LES_TYPED_RETRIEVAL` (LLM-роутер по каталогу + кэш `doc_router_cache`).

Preprocess heavy PDFs before indexing (clean + split >40MB; originals go to `_originals/`, idempotent via state file):

```bash
uv run python tools/pdf_preprocess.py RAG_Content/<folder>/ --dry-run   # сначала посмотреть
uv run python tools/pdf_preprocess.py RAG_Content/<folder>/             # выполнить
# или вместе с индексацией: uv run python tools/qwen_index_until_done.py --preprocess-dirs RAG_Content/<folder>
```

Switch the chat LLM (provider/model) — **no restart needed**, applies per-request:

- GUI: `http://127.0.0.1:8051/les/classic` → шапка **⚙** (диалог настроек) → **LLM Provider** → выбрать mlx / ollama / openrouter / openai, указать модель → **💾 Сохранить**. Строка «СЕЙЧАС ОТВЕЧАЕТ» показывает активный провайдер/модель; валидация Т.О.С.К.А. работает только на MLX, остальные дают UNVALIDATED. (Там же — Mail/IMAP.)
- CLI: `curl -X POST http://127.0.0.1:8050/api/settings -H 'Content-Type: application/json' -d '{"llm_provider":"ollama","ollama_model":"gemma4:12b"}'` (персистится в .env runtime-клона). Вернуться: `-d '{"llm_provider":"mlx"}'`.
- Локальная RAG-модель — `MLX_MODEL=mlx-community/Qwen3.5-9B-OptiQ-4bit`. Единый default/список GUI хранится в `proxy/local_model_registry.py`; env-выбор оператора имеет приоритет. OptiQ прошёл русский ответ, OpenAI tool calls, tool-result continuation и живой BAI RRF smoke. Gemma 4 12B в Ollama (`gemma4:12b`) остаётся vision/грязным входом, не автоматическим вторым агентом.
- Windows `windows-lite`: bootstrap требует полный локальный контур `uv + Ollama + Docker Desktop + Qdrant`; отсутствующие компоненты ставит через winget (для `uv` есть официальный скрипт), а при невозможности пишет точный `bootstrap-status.json` с официальным адресом установки. Полурабочий GUI без Qdrant запрещён. `start-light.ps1 -Provider ollama -Model qwen3.5:9b` синхронизирует `OLLAMA_MODEL=LLM_MODEL`, model-owned attachment/smeta следует выбранному локальному Ollama (не фиктивному MLX fallback), embeddings — `bge-m3:latest`, `EMBED_BACKEND=ollama`, `RAG_VECTOR_SIZE=1024`. Реранкер допускается только после SHA-256 + semantic load-probe `tools/onboard_reranker.py`; повреждённый вес не оставлять под published именем.
- Windows update — только вручную из настроек: `GET /api/update/check`, затем отдельный admin `POST /api/update/install`. Публичный выпуск обязан содержать прямой `latest.json`, `LES-Setup.exe` и `LES-Setup.exe.sha256`; серверная часть не зависит от GitHub API, проверяет адрес GitHub и SHA-256 до запуска NSIS. Не добавлять таймер, фоновую проверку или автоустановку.
- Облако: **из РФ Cloudflare и OpenRouter режутся** → используем OpenAI-совместимый `proxyapi.ru` (`OPENAI_BASE_URL=https://openai.api.proxyapi.ru/v1`, `OPENAI_MODEL=gpt-4.1`, `LES_LLM_PROVIDER=openai`). `LES_CLOUD_MODEL_TIMEOUT_SEC=8` чтобы мёртвое облако не висело.

Task tracker from chat (deterministic regex+SQL, no LLM, works even under memory-guard): «поставь задачу …» / «что по задачам?» / «задача N готова». API: `POST/GET /api/tasks`, `PATCH /api/tasks/{id}`.

Operator memory from chat (same mechanics): «запомни: …» / «заметки» / «забудь заметку N». Relevant notes and past good answers are mixed into the answer context automatically (lexical recall, no LLM; also visible to Т.О.С.К.А. validation).

Inspect service sources required by smeta/normcontrol (what files LES needs and what is missing):

```bash
curl -fsS http://127.0.0.1:8050/api/service-sources | python3 -m json.tool
```

Canonical source contract lives in `config/service_sources.yaml`. Current groups: ГЭСН base
(`data/gesn_base/*.parquet` + seed), ФГИС ЦС price books (`data/price_base/*.parquet`), smeta YAML
coefficients/templates, СПДС rulepack, normative SPDS RAG dataset, and layout-reference. The same status is
visible in GUI: **Инструменты → Служебные источники данных**.

Run formal normcontrol checks (NK-01 sheet formats, NK-02 scans, NK-03 cipher, NK-04 ведомость↔files; deterministic, no LLM):

```bash
curl -fsS -X POST http://127.0.0.1:8050/api/normcontrol/<dataset_id>/run | python3 -m json.tool
# report: GET /api/normcontrol/<dataset_id>/download
```

Run RAG-led СПДС doc-review (ГОСТ Р 21.101-2026): чат-режим `Нормоконтроль` или API ниже. JSON содержит
`defense_contract_v1` и `normalized_remarks`; чатовый ответ — человеческий отчёт с evidence/action таблицами. D4-001 формат листа
проверяется по PDF-геометрии/ГОСТ 2.301; D4-002 text-layer проверяет, что сигнатуры основной надписи
попали в ожидаемую нижнюю правую зону листа. Полная проверка заполнения всех граф требует
layout-reference.

```bash
curl -fsS -X POST http://127.0.0.1:8050/api/doc-review/<dataset_id>/run \
  -H 'Content-Type: application/json' -d '{"rulepack":"gost_r_21_101_2026"}' | python3 -m json.tool
```

Check ZeroTier access from any ZT device (each line = endpoint probe; non-200 → что именно «не пускает»):

```bash
python3 tools/zerotier_access_smoke.py --host 10.195.146.98
```

Map an existing file archive without indexing it (metadata only, no LLM; then index selectively):

```bash
curl -fsS -X POST http://127.0.0.1:8050/api/filemap/scan -H 'Content-Type: application/json' -d '{"path":"/Volumes/Archive"}' | python3 -m json.tool
# поиск: GET /api/filemap/search?q=СП+60 · обзор: GET /api/filemap/stats · кандидаты: GET /api/filemap/candidates
# проиндексировать ветку из карты (без копирования файлов вручную):
curl -fsS -X POST http://127.0.0.1:8050/api/filemap/index -H 'Content-Type: application/json' -d '{"dataset_name":"Архив_ОВ","path_prefix":"Проект/ОВ","parse":true}' | python3 -m json.tool
# UI: вкладка С.А.М.О.В.А.Р. → блок «КАРТА АРХИВА» (скан + папки-кандидаты с кнопкой ИНДЕКС)
```

Diff two CAD/BIM imports or two document revisions (deterministic, no LLM):

```bash
curl -fsS "http://127.0.0.1:8050/api/diff/cad-bim?import_a=<id1>&import_b=<id2>" | python3 -m json.tool
# import ids: sqlite3 data/cad_bim_graph.db "SELECT id, source, created_at FROM cad_bim_imports"
# text revisions: POST /api/diff/text {"text_a": ..., "text_b": ...}
```

Field volume journal (W8.1/W8.4): CRUD + SQL aggregations + xlsx; numbers are SQL, not LLM. Chat: «запиши объём 50 м3 монолитная плита захватка 3» records; «сколько монолитная плита выполнено за июнь 2026?» answers from confirmed entries.

```bash
curl -fsS -X POST http://127.0.0.1:8050/api/field -H 'Content-Type: application/json' \
  -d '{"position":"монолитная плита","volume":50,"unit":"м3","zahvatka":"3","entry_date":"2026-06-10"}'
curl -fsS "http://127.0.0.1:8050/api/field/summary?zahvatka=3&date_from=2026-06-01&date_to=2026-06-30" | python3 -m json.tool
curl -fsS -X POST http://127.0.0.1:8050/api/field/export && curl -fsSJO http://127.0.0.1:8050/api/field/download  # xlsx
# GUI: вкладка ОБЪЁМЫ (ввод/свод/журнал/экспорт)
```

Viewer↔chat highlight (W6.7): a chat answer over CAD/BIM chunks fills the "last highlight"
snapshot; the ATLAS viewer polls it and recolors elements (no manual selection, no LLM).

```bash
curl -fsS "http://127.0.0.1:8050/api/cad-bim/highlight" | python3 -m json.tool   # {seq, source_ids, import_id, question}
# manual drive (other UIs/tests): POST /api/cad-bim/highlight {"source_ids": ["ELEM-1"], "import_id": "<id>"}
```

## Документы/таблицы/команды/MCP (W11.x, 2026-06-18/19)

- **Сверка ВОР↔КС-2↔смета↔ИД:** `GET /api/bor/reconcile?datasets=a,b&by=dataset` (preview), `POST …/reconcile/generate` (xlsx). Чат: «сверь ведомости и акты». Числа из Parquet, 0 LLM. Флаги match/mismatch/gap/single.
- **ВОР из спецификации (форма 9):** `GET/POST /api/bor/{id}/from-spec[/generate]`; чат «сделай ВОР из спецификации». GUI: ВОР-карта → переключатель «Свод / Работы из спец.(Ф9)».
- **Типовые формы:** `GET /api/forms`, `POST /api/forms/{id}/generate` → docx/xlsx/html. Есть: `aosr`, `spec_gost21110` (ГОСТ 21.110 ф.1), `vor`, `smeta_lsr` (ЛСР 421/пр), `ks2`/`ks3` (Госкомстат 100). Дескрипторы — `config/forms/*.yaml` (`columns`+`table`; родной бланк — `templates.xlsx`, подстановка `{{key}}` + якорь `{{rows}}`).
- **Сводка проекта:** чат «дай сводку проекта» → стадия+ТЭП+состав (`project_summary_service`, каркас; ТЭП-якоря калибровать на реальных доках).
- **/-команды чата:** `GET /api/commands`; `/спецификация //вор //смета //акт //сверка //сводка //мсп //команды`. GUI — «/»-палитра в композере.
- **Почта/архивы Outlook:** IMAP из GUI (Самовар → карта OUTLOOK/IMAP, пресеты M365/Outlook.com; параметры в `POST /api/mail/import-imap`); архивы `POST /api/mail/import-archive` (`.olm` Mac — stdlib; `.pst` Windows — нужен `libpff`; `.msg` индексируется как файл). Авто-синхрон — `MAIL_IMAP_*` в .env.
- **Скрепка чата:** внешний пользовательский путь — `POST /api/chat/attachments` (обязательный `Idempotency-Key`, временный read-файл без индексации) → `attachment_id` → идемпотентный `POST /api/chat`; повтор готового запроса возвращается до модели. Административный `POST /api/rag/attach?mode=read|quick|index` остаётся Совушке/совместимости: `read` прикрепляет файл к следующему сообщению, `quick` делает временный табличный датасет для сверки, `index` добавляет документ в RAG-базу. UI после галочки обязан показать системное сообщение в чате и плашку composer «к следующему сообщению». Браузер папок: `GET /api/rag/browse-external`.
- **Сметное ценообразование (2026-06-22):** **ФГИС ЦС lookup** — `GET /api/prices/lookup?code=…` и `POST /api/prices/lookup-batch` (точные цены по одному/нескольким кодам из «Сплит-формы»; пакет читает книгу один раз), `/search`, `GET /api/prices/books`, `POST /api/prices/import`; **добор из ФГИС ЦС** — `GET /api/prices/sources/subjects`, `/sources/periods?subject=…`, `POST /api/prices/update`, `GET /api/prices/needs?code=…`; общий операторский updater `POST /api/service-sources/fgis/update` скачивает публичный каталог, последние Сплит-формы всех ценовых зон и ГЭСН, статус — `/status`; GUI «Инструменты → Источники данных → СКАЧАТЬ ФГИС ЦС». Фоновые PID проверяются через `process_status.pid_running`: на Windows запрещён `os.kill(pid, 0)`, потому что polling не должен завершать updater. Закрытые Bearer/captcha поверхности не обходятся. **КАЦ** — `POST /api/kac/analyze` (≥3 КП→экономичный), `/lsr-lines`, `/generate`, `GET /api/kac/needs`; GUI «КАЦ». **Глоссарий/онтология** — `les_glossary`; источник `config/domain/smeta_ontology.yaml`, RAG-глоссарий `docs/smeta_ontology.md`. **Коэф. стеснённости** — `GET /api/lsr/stesnennost/conditions`, `POST /api/lsr/stesnennost/apply`; GUI «Коэффициент стеснённости». **ГЭСН норма→ресурсы** — `GET /api/lsr/gesn`, `GET /api/lsr/gesn/{code}/expand?qty=…`. **Движок сборки ЛСР** — `POST /api/lsr/assemble`; GUI «Сборка ЛСР». Числа считает код, профессиональные решения остаются модели. Каноны: `docs/ALGO-{fgis-price,kac,gesn,smeta-ontology,harvest,stesnennost,lsr-assembly,object-estimate}.md`.
- **Импорт базы ГЭСН-2022 (полная, из ФГИС ЦС, бесплатно):** `uv run python -m tools.gesn_bulk_import --all --rate 1.0 --out data/gesn_base/gesn2022.parquet` (резюмируемый, ~30–90 мин; один сборник — `--sbornik 12`). Альтернативы: `tools.gesn_import IN.xlsx` (выгрузка ГРАНД/НСИ), `tools.gesn_pdf_import` (PDF/JSON). Egress из не-РФ — `LES_FGIS_VIA_SSH=root@HOST`. См. `docs/ALGO-gesn.md`.
- **Приёмка почты из Outlook:** `POST /api/mail/push` (тело+вложения base64) → детерм. классификация: КП→КАЦ, смета/ВОР→RAG, скан→приёмка ИД (pending), прочее→RAG-документ. Плагин — `clients/outlook_addin/`. Legion-Outlook (Windows) → этот Мак через обратный SSH: `bash tools/legion_mail_tunnel.sh` (env `LES_LEGION_SSH`/`LES_PORT`). См. `docs/ALGO-mail-intake.md`.
- **Деплой dev→рантайм:** `make ship` = быстрый итерационный выкат (`verify → test-focused → smoke → deploy-runtime → retry post-deploy-smoke`); `make ship-full` = полный gate версии (`verify → test → smoke → deploy-runtime → retry post-deploy-smoke`). Низкоуровневый деплой: `uv run python -m tools.deploy_to_runtime --apply [--restart]`; scope строится из committed diff `deploy_stamp.deployed_commit..HEAD` плюс working tree, поэтому чистый release commit не становится no-op. Манифест защищает дивергентные runtime-файлы; dry-run по умолчанию. Онбординг провайдера до GUI — `uv run python tools/onboard_provider.py --provider mlx`. Иконки — `tools/build_icons.py`.
- **Public-ready gate:** `make public-check` проверяет tracked git на запрещённые runtime/private пути и высокосигнальные секреты; публичная публикация репозитория всё равно требует ручного owner-review по `docs/PUBLICATION_CHECKLIST.md`.
- **MCP-сервер:** `uv run python tools/les_mcp_server.py` (stdio) / `--list` (каталог). **18 инструментов** наружу: 16 вычислительных/читающих, включая одиночный и пакетный `les_price_lookup[_batch]` и модельный `les_price_browse`, плюс **2 action** (`les_smeta_save`, `les_journal_append`). Требует extra `mcp`. Регистрация в MCP-клиенте — `{"mcpServers":{"les":{"command":"uv","args":["run","python","tools/les_mcp_server.py"],"cwd":"/Users/ovc/LES"}}}`.
- **Режимы local/cloud/mix (один переключатель):** `preset_service` согласованно ставит чат-LLM + скан-OCR + движок приёмки ИД. **local** (mlx+tesseract+local — приватно/бесплатно/валидируется) · **cloud** (openai+cloud-asbuilt — качество, $) · **mix** (локальный чат+OCR, облако только под плотные таблицы ИД). Чат: «режим/какой режим/переключи на облако», команда `/режим <имя>`; API `GET /api/settings/presets`, `POST /api/settings/preset {name}` (пишет .env+environ, действует сразу). Канал `preset` + инструмент agent-роутера.
- **Ярус 2 — агент-роутер (чат сам выбирает инструмент):** за флагом `LES_AGENT_LOOP`. Когда regex-каналы не поймали — LLM выбирает один инструмент (`agent_router_service`: asbuilt/les_md/реестр/объёмы/задачи) и исполняет **детерминированный** обработчик (числа — код). Подключён в `chat.py` ПОСЛЕ детерм. каналов, ПЕРЕД RAG; сбой/«none»/обработчик-отказ → фолбэк на RAG. `channel=agent`, `agent_tool=<имя>`.
- **Реестр проектов (общая карта):** канал `registry` (всегда), команда `/проекты` (`/реестр`,`/объекты`,`/карта`): «реестр проектов», «какие объекты», «общая карта папок» → все объекты + папки + мета из LES.md (`project_service.build_registry`, 0 LLM).
- **Auto-init при индексации:** `index-external` сам пишет LES.md + привязывает к проекту; `LES_AUTO_PIPELINES` (off на целых проектах — нужен guard «это ИД-папка», follow-up) — авто-директивы (ид→asbuilt).
- **LES.md (файл-контекст папки, CLAUDE.md для ЛЕС):** кладёшь `LES.md`/`ЛЕС.md` в папку → ЛЕС понимает её. Чат: «пойми папку «<путь>»» / «сделай LES.md для «<путь>»» (канал `les_md`); API `POST /api/les-md/read|draft`, `GET /api/les-md/context/{pid}`. frontmatter (проект/объект/стадия/шифр/`pipelines`/`ignore`) привязывает папку к объекту (`les_projects`), тело подмешивается в контекст in-project запросов. Нет файла → авто-черновик из скана (типы/шифры/даты). Канон — `docs/ALGO-les-md.md`. Логика: «даём папку → понимает → работает; к проекту, но и вне (двойной режим)».
- **Приёмка смонтированного объёма из исполнительных/чек-листов (сканов):** `POST /api/field/extract-asbuilt` (admin; path внутри `LES_EXTERNAL_SOURCE_ROOTS`; `write=false` → превью, `write=true` → строки в журнал объёмов как `status=pending`). CLI: `uv run python tools/asbuilt_extract.py "<pdf|папка>" --engine local|cloud --rotate auto|90 --preview|--write [--xlsx out]`. Конвейер: рендер→авто-поворот→**locate-then-read** (найти bbox таблицы «…смонтированного…» → прочитать целиком; vision-OCR — единственный LLM-шаг, числа/свод считает код, ADR-11). `local`=gemma4:12b (приватно, но медленно на больших листах — риск таймаута), `cloud`=gpt-4.1 через proxyapi (точнее/быстрее, исполнительная уходит наружу). Строки тегируются `zahvatka=floor/system/line` → свод `/api/field/summary`. **Чат вызывает сам** (канал `asbuilt`, `asbuilt_chat_service`): «вытащи смонтированный объём из «/путь/папка»» (+«облаком» → cloud-движок) → фоновый прогон + запись pending, ack сразу; команда-палитра `/исполнительная`. Канон — `docs/ALGO-asbuilt-intake.md`.
- **Форматы (расширено для реальных проектных архивов):** конвертер берёт legacy `.doc` (через нативный `textutil`; mammoth/markitdown их НЕ читают — раньше тихо индексировались пустыми), `.xlsm`, картинки `jpg/png/tiff`→vision-OCR, `.p7m` (openssl→PDF; открепл. подпись рядом с оригиналом — скип). Архивы `.7z/.zip` — препроцесс `uv run python tools/unpack_archives.py "<папка>"` (`.7z` нужен `uv pip install py7zr`). **DWG не парсится напрямую** (нужен внешний DWG→DXF/JSON). Аудит покрытия типов: гейт `backend/smart_index.SUPPORTED_SUFFIXES`.
- **Выбор vision-OCR-модели тестами:** `uv run python tools/asbuilt_ocr_bench.py --dir "<папка АУПС-СОУЭ>" --models cloud:gpt-4.1 local:gemma4:12b local:qwen3-vl:8b` — recall по числовым якорям (ground-truth 4 листов) + латентность, рейтинг. Кандидаты — текущее поколение (**Qwen3-VL** 4B/8B и сородичи; Qwen2.5-VL — устар.). `--model` есть и в `asbuilt_extract.py`/`process_path`.
- **Env-ручки:** `RAG_OCR_BACKEND` (ollama|mlx), `RAG_OCR_MODEL`, `LES_AUTONOTE_ENABLED` (авто-заметки фактов из чата); приёмка ИД — `LES_ASBUILT_OCR_ENGINE`/`LES_ASBUILT_STRATEGY`/`LES_ASBUILT_DPI`/`LES_ASBUILT_LOCATE_PAD`/`LES_ASBUILT_TILES`. Сметное/ретрив/ярус-3 (`feat/les3-p1`): `LES_LAYOUT_PDF` (layout-aware PDF, дефолт on; +`LES_LAYOUT_COLUMN_GAP_RATIO`/`LES_LAYOUT_MIN_TABLE_ROWS`/`_COLS`), `LES_TABLE_APPENDIX` (подъём pipe-таблиц в ретрив, дефолт true; +`LES_TABLE_APPENDIX_MIN_PIPES`/`_POOL_N`/`_GUARANTEE`), `LES_FGIS_TIMEOUT`/`LES_FGIS_FILE_TIMEOUT`/`LES_FGIS_VIA_SSH` (добор ФГИС ЦС), `LES_SMETNOE_TOKEN`/`LES_SMETNOE_VIA_SSH` (smetnoedelo, квота), `LES_AGENT_LOOP` (Ярус 2/3: агент-роутер + action-инструменты). См. env.example.
- **Алгоритм-доки:** `docs/ALGO-table-query.md` (счёт по ячейкам), `docs/ALGO-spec-to-bor.md` (спец→ВОР), `docs/ALGO-{gesn,fgis-price,kac,stesnennost,lsr-assembly,object-estimate,smeta-ontology,harvest}.md` (сметное ядро), `docs/ALGO-mail-intake.md` (почта), `docs/ALGO-pdf-layout.md` (Ц11), `docs/ALGO-vl-lora.md` (Ц12/Ц13 — решение) — читать перед правкой соответствующего сервиса.

## Documentation

When closing a LES session, update the **living** canon (датированные `SESSION_SUMMARY_*` ретая —
не плодим новые, история в `git log` + `docs/archive/`):

- `ROADMAP_TO_V1.md` — бэклог/состояние до v1
- `docs/releases.md` — версии/что вошло
- `docs/CODE_MAP.md` — при структурных правках
- auto-memory (`MEMORY.md`) — непроизводные факты сессии

Record exact dates, test counts, index counts, model ids, Core ML package names, fallback state, and external smoke state — в коммитах и `/api/version`, не в отдельных саммари.
