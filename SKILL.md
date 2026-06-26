---
name: les
description: Use when working on the local LES_v2 repository, LES runtime, Core ML/MLX/Qdrant/Sovushka/PAUK/VOLK workflows, runtime health, indexing, external les.ovc.me access, docs, tests, or cleanup.
---

# LES Operator Skill

## Workspace

Use `/Users/ovc/Projects/LES_v2` as the project root for development.

**Runtime clone:** launchd services (proxy/sovushka/mlx/qdrant) run from **`/Users/ovc/LES`** (подтверждено `WorkingDirectory` в `~/Library/LaunchAgents/me.ovc.les.*.plist` + cwd процесса; origin клона — `LES_v2_reinstall_stress`, не dev-репо). **Клон диверговый** (живые незакоммиченные правки), поэтому деплой = **порт правок файлами**: правка в LES_v2 → `cp`/точечный Edit изменённых файлов в `/Users/ovc/LES` → `launchctl kickstart -k gui/$(id -u)/me.ovc.les.proxy` (и `com.les.sovushka` для GUI). НЕ `git pull` (история расходится). Перед перезаписью файла из dirty-set (`proxy/routers/chat.py`, `datasets.py`, `parquet_writer.py`, `samovar.py`, …) — патчить Edit'ом, не overwrite (есть рантайм-онли диверженция). Editing LES_v2 alone does NOT change the live system.

> ⚠️ **`uv sync` в рантайм-клоне ОБЯЗАТЕЛЬНО с `--extra mac-mlx`** (`uv sync --extra mac-mlx`). `mlx-lm`/`mlx-vlm` — в опциональной группе `mac-mlx` (`[project.optional-dependencies]`); голый `uv sync` (например, после `uv add`) **выкашивает их из venv → MLX-host падает на `ModuleNotFoundError: No module named 'mlx_lm'`** и весь RAG/эмбеддер ложатся. Симптом: `[WARNING] MLX /api/ps error: All connection attempts failed`, ретрив → HTTP 500. Лечение: `uv sync --extra mac-mlx` в клоне + `launchctl kickstart -k gui/$(id -u)/me.ovc.les.mlx`. (Инцидент 2026-06-14.)
>
> ⚠️ **Доп. зависимости рантайма ставились через `uv pip install`, НЕ `uv add`** (чтобы не дёрнуть sync и не выкосить mlx): `libpff-python` (архивы `.pst`, extra `mail-pst`), `mcp` (MCP-сервер, extra `mcp`). Любой `uv sync` их тоже уберёт — после sync либо `uv pip install libpff-python mcp`, либо синкать `--extra mac-mlx --extra mail-pst --extra mcp`. (2026-06-19.)

Current production posture:

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
- Main model: `mlx-community/Qwen3.5-9B-MLX-4bit` (4B залипал в повторы; OptiQ медленный). Облако — primary через proxyapi.ru; 9B — приватный fallback.
- Embedder: Core ML `Qwen/Qwen3-Embedding-0.6B`, `qwen3_embedding_06b_b1_s512_static.mlpackage`, `compute_units=all`, isolated worker, fallback disabled.
- Validator live default: deterministic `rules`. Core ML `MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli` package exists for measured compare/probe, not current production default.
- Hybrid sparse (W2.4): Qdrant-native гибрид dense (Qwen) + BM25/IDF sparse через сайдкар-коллекцию `{RAG_COLLECTION_NAME}_sparse` (sparse-only, `modifier=Idf`, те же point id; основная коллекция не тронута). Включается `RAG_SPARSE_ENABLED=true` → `mode=hybrid+sparse+rerank`; домен-гейт 16/16. Реиндекс: `uv run python tools/reindex_sparse_bge_m3.py --recreate` (~36с на 169k, CPU). Откат: флаг off + рестарт proxy. BM25 выбран вместо BGE-M3 learned-sparse (BGE-M3 на 169k = ~9ч MPS).
- Reranker (W2.2): cross-encoder `BAAI/bge-reranker-v2-m3` via `POST /v1/rerank` (mlx_host, lazy, TTL 600s, separate from `llm_semaphore`). Warm latency ~60ms/8 docs; domain gate 16/16 via rerank path. **Download note:** HF `cdn-lfs` is blocked here — fetch LFS files from the `hf-mirror.com` mirror into the HF cache (`model.safetensors` ~2.27GB, `sentencepiece.bpe.model` ~5MB). Recovery: `curl -sL -C - -o <file> https://hf-mirror.com/BAAI/bge-reranker-v2-m3/resolve/main/<file>` into `~/.cache/huggingface/hub/models--BAAI--bge-reranker-v2-m3/snapshots/<commit>/` (snapshot already holds config/tokenizer). Validate: `safe_open(...).keys()` → 393 tensors.
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

## Version / Scope / Sidecar (Unified Construction Harness v0.16–v0.22)

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

Инвентарь тестов v0.16–v0.22 (230 шт) — **[docs/TEST_INVENTORY.md](docs/TEST_INVENTORY.md)**. Гейт `make verify` (офлайн). Run before finalizing meaningful changes:

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

Сводка/сумма по табличному датасету (сметы/ВОР/КС-2) — **детерминированная SUM по полному Parquet, не LLM** (ADR-11). Через чат с `dataset_filter=TABLE_SMETA`, напр. «суммарный метраж кабеля 3х1,5 по всем ведомостям» → `route=table`, ответ «полная выгрузка Parquet». Поле выбирается по запросу (метраж/объём → qty, стоимость → amount); `.xls` читаются через `xlrd`+конвертацию в `parquet_writer`. Типизированный ретрив норм — за флагом `LES_TYPED_RETRIEVAL` (LLM-роутер по каталогу + кэш `doc_router_cache`).

Preprocess heavy PDFs before indexing (clean + split >40MB; originals go to `_originals/`, idempotent via state file):

```bash
uv run python tools/pdf_preprocess.py RAG_Content/<folder>/ --dry-run   # сначала посмотреть
uv run python tools/pdf_preprocess.py RAG_Content/<folder>/             # выполнить
# или вместе с индексацией: uv run python tools/qwen_index_until_done.py --preprocess-dirs RAG_Content/<folder>
```

Switch the chat LLM (provider/model) — **no restart needed**, applies per-request:

- GUI: `http://127.0.0.1:8051/les/classic` → шапка **⚙** (диалог настроек) → **LLM Provider** → выбрать mlx / ollama / openrouter / openai, указать модель → **💾 Сохранить**. Строка «СЕЙЧАС ОТВЕЧАЕТ» показывает активный провайдер/модель; валидация Т.О.С.К.А. работает только на MLX, остальные дают UNVALIDATED. (Там же — Mail/IMAP.)
- CLI: `curl -X POST http://127.0.0.1:8050/api/settings -H 'Content-Type: application/json' -d '{"llm_provider":"ollama","ollama_model":"gemma4:12b"}'` (персистится в .env runtime-клона). Вернуться: `-d '{"llm_provider":"mlx"}'`.
- Локальная RAG-модель — `MLX_MODEL=mlx-community/Qwen3.5-9B-MLX-4bit` (4B залипал в повторы; OptiQ-квант медленный + скрытый `<think>`). Gemma 4 12B в Ollama (`gemma4:12b`) — vision/грязный вход.
- Облако: **из РФ Cloudflare и OpenRouter режутся** → используем OpenAI-совместимый `proxyapi.ru` (`OPENAI_BASE_URL=https://openai.api.proxyapi.ru/v1`, `OPENAI_MODEL=gpt-4.1`, `LES_LLM_PROVIDER=openai`). `LES_CLOUD_MODEL_TIMEOUT_SEC=8` чтобы мёртвое облако не висело.

Task tracker from chat (deterministic regex+SQL, no LLM, works even under memory-guard): «поставь задачу …» / «что по задачам?» / «задача N готова». API: `POST/GET /api/tasks`, `PATCH /api/tasks/{id}`.

Operator memory from chat (same mechanics): «запомни: …» / «заметки» / «забудь заметку N». Relevant notes and past good answers are mixed into the answer context automatically (lexical recall, no LLM; also visible to Т.О.С.К.А. validation).

Run formal normcontrol checks (NK-01 sheet formats, NK-02 scans, NK-03 cipher, NK-04 ведомость↔files; deterministic, no LLM):

```bash
curl -fsS -X POST http://127.0.0.1:8050/api/normcontrol/<dataset_id>/run | python3 -m json.tool
# report: GET /api/normcontrol/<dataset_id>/download
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
- **Скрепка чата:** `POST /api/rag/attach?mode=quick|index` — прикрепить документ (быстрый Parquet-парс / полная индексация). Браузер папок: `GET /api/rag/browse-external`.
- **Сметное ценообразование (2026-06-22):** **ФГИС ЦС lookup** — `GET /api/prices/lookup?code=…` (цена ресурса по коду из «Сплит-формы», exact-match), `/search`, `GET /api/prices/books`, `POST /api/prices/import` (книга в `data/price_base/`); **добор из ФГИС ЦС** — `GET /api/prices/sources/subjects`, `/sources/periods?subject=…` (субъект/квартал), `POST /api/prices/update` (скачать+кэшировать, graceful-fail), `GET /api/prices/needs?code=…` (локаль-первый вердикт «есть в ФГИС ЦС или нужен КАЦ»); GUI «Инструменты»→«ФГИС ЦС». **КАЦ** — `POST /api/kac/analyze` (≥3 КП→экономичный), `/lsr-lines`, `/generate`, `GET /api/kac/needs`; GUI «КАЦ». **Глоссарий/онтология** — `les_glossary`; источник `config/domain/smeta_ontology.yaml`, RAG-глоссарий `docs/smeta_ontology.md`. **Коэф. стеснённости** — `GET /api/lsr/stesnennost/conditions`, `POST /api/lsr/stesnennost/apply` (коэф. к ОЗП/ЭМ→ФОТ/НР/СП/Всего; каталог `config/domain/stesnennost.yaml`); GUI «Коэффициент стеснённости». **ГЭСН норма→ресурсы** — `GET /api/lsr/gesn` (список), `GET /api/lsr/gesn/{code}/expand?qty=…` (разворот нормы); полная база **42408 норм ГЭСН-2022** в `data/gesn_base/gesn2022.parquet`. **Движок сборки ЛСР** — `POST /api/lsr/assemble` (позиция: объём+ресурсы labor/machinist/machine/material → цены ФГИС ЦС/КАЦ → стеснённость → НР/СП → Всего → свод; gold = позиция эталона 11813.04); GUI «Сборка ЛСР». **Объектная смета (чат):** «дай смету на <объект>» (без кода ГЭСН) → `object_estimate_service` (фраза→шаблон→геометрия→ВОР→ЛСР→СМР·непредвиденные·НДС·ВСЕГО); шаблоны `config/domain/object_templates.yaml`, НР/СП `config/domain/nr_sp.yaml`. **Harvest** — `tools/harvest_dataset.py` (verify→train-set+таксономия под VL-LoRA). Каноны: `docs/ALGO-{fgis-price,kac,gesn,smeta-ontology,harvest,stesnennost,lsr-assembly,object-estimate}.md`. Родные бланки форм — `config/forms/templates/{vor,ks2,ks3}.xlsx` (xlsx-шаблон: `{{key}}` + якорь `{{rows}}`).
- **Импорт базы ГЭСН-2022 (полная, из ФГИС ЦС, бесплатно):** `uv run python -m tools.gesn_bulk_import --all --rate 1.0 --out data/gesn_base/gesn2022.parquet` (резюмируемый, ~30–90 мин; один сборник — `--sbornik 12`). Альтернативы: `tools.gesn_import IN.xlsx` (выгрузка ГРАНД/НСИ), `tools.gesn_pdf_import` (PDF/JSON). Egress из не-РФ — `LES_FGIS_VIA_SSH=root@HOST`. См. `docs/ALGO-gesn.md`.
- **Приёмка почты из Outlook:** `POST /api/mail/push` (тело+вложения base64) → детерм. классификация: КП→КАЦ, смета/ВОР→RAG, скан→приёмка ИД (pending), прочее→RAG-документ. Плагин — `clients/outlook_addin/`. Legion-Outlook (Windows) → этот Мак через обратный SSH: `bash tools/legion_mail_tunnel.sh` (env `LES_LEGION_SSH`/`LES_PORT`). См. `docs/ALGO-mail-intake.md`.
- **Деплой dev→рантайм (вместо ручных cp/Edit):** `uv run python -m tools.deploy_to_runtime --apply [--restart]` (манифест, дивергентные рантайм-файлы пропускаются и патчатся вручную; dry-run по умолчанию). Онбординг провайдера до GUI — `uv run python tools/onboard_provider.py --provider mlx`. Иконки — `tools/build_icons.py`.
- **MCP-сервер:** `uv run python tools/les_mcp_server.py` (stdio) / `--list` (каталог). **16 инструментов** наружу: 14 счётных (`les_table_sum/les_table_agg/reconcile/bor/spec_to_bor/project_summary/form_generate` + `les_price_lookup/les_glossary/les_kac/les_stesnennost/les_lsr_assemble/les_gesn_expand/les_gesn_fetch`) + **2 action** (`les_smeta_save` — собранная смета→ВОР/ЛСР в проект, не перезаписывает; `les_journal_append` — запись в журнал `pending`, идемпотентно по `idem_key`). Требует extra `mcp`. Регистрация в MCP-клиенте — `{"mcpServers":{"les":{"command":"uv","args":["run","python","tools/les_mcp_server.py"],"cwd":"/Users/ovc/LES"}}}`.
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
