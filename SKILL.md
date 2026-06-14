---
name: les
description: Use when working on the local LES_v2 repository, LES runtime, Core ML/MLX/Qdrant/Sovushka/PAUK/VOLK workflows, runtime health, indexing, external les.ovc.me access, docs, tests, or cleanup.
---

# LES Operator Skill

## Workspace

Use `/Users/ovc/Projects/LES_v2` as the project root for development.

**Runtime clone:** launchd services (proxy/sovushka) run from `/Users/ovc/Projects/LES_v2_reinstall_stress` (see `WorkingDirectory` in `~/Library/LaunchAgents/me.ovc.les.*.plist`). Deploy flow: commit+push in LES_v2 → `git pull` in the runtime clone → `launchctl kickstart -k ...`. Editing LES_v2 alone does NOT change the live system.

> ⚠️ **`uv sync` в рантайм-клоне ОБЯЗАТЕЛЬНО с `--extra mac-mlx`** (`uv sync --extra mac-mlx`). `mlx-lm`/`mlx-vlm` — в опциональной группе `mac-mlx` (`[project.optional-dependencies]`); голый `uv sync` (например, после `uv add`) **выкашивает их из venv → MLX-host падает на `ModuleNotFoundError: No module named 'mlx_lm'`** и весь RAG/эмбеддер ложатся. Симптом: `[WARNING] MLX /api/ps error: All connection attempts failed`, ретрив → HTTP 500. Лечение: `uv sync --extra mac-mlx` в клоне + `launchctl kickstart -k gui/$(id -u)/me.ovc.les.mlx`. (Инцидент 2026-06-14.)

Current production posture:

- Proxy: `http://127.0.0.1:8050`
- Sovushka UI (NiceGUI): `http://127.0.0.1:8051` → `/classic` (чат), `/les/classic` (админка). HTML-шеллы lite удалены (W5.4/5.5): `/` и `/les` редиректят в NiceGUI; мост `/lite-api/*` сохранён.
- MLX Host: `http://127.0.0.1:8080`
- Qdrant: `http://127.0.0.1:6333`
- External: `https://les.ovc.me` through P.A.U.K. reverse SSH tunnel and V.O.L.K. API keys; on 2026-06-01 external smoke passes `12/12`.
- ZeroTier trusted GUI/API access: `TRUSTED_NETWORKS=127.0.0.0/8,::1/128,10.195.146.0/24`, `TRUSTED_NETWORK_ROLE=admin`. Trusted clients should open `/classic`, `/les/classic` and `/lite-api/*` without a key; stale browser keys fallback to `trusted-network`, while public clients still receive `401`.

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
- Main model: `mlx-community/Qwen3.5-4B-MLX-4bit`.
- Embedder: Core ML `Qwen/Qwen3-Embedding-0.6B`, `qwen3_embedding_06b_b1_s512_static.mlpackage`, `compute_units=all`, isolated worker, fallback disabled.
- Validator live default: deterministic `rules`. Core ML `MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli` package exists for measured compare/probe, not current production default.
- Hybrid sparse (W2.4): Qdrant-native гибрид dense (Qwen) + BM25/IDF sparse через сайдкар-коллекцию `{RAG_COLLECTION_NAME}_sparse` (sparse-only, `modifier=Idf`, те же point id; основная коллекция не тронута). Включается `RAG_SPARSE_ENABLED=true` → `mode=hybrid+sparse+rerank`; домен-гейт 16/16. Реиндекс: `uv run python tools/reindex_sparse_bge_m3.py --recreate` (~36с на 169k, CPU). Откат: флаг off + рестарт proxy. BM25 выбран вместо BGE-M3 learned-sparse (BGE-M3 на 169k = ~9ч MPS).
- Reranker (W2.2): cross-encoder `BAAI/bge-reranker-v2-m3` via `POST /v1/rerank` (mlx_host, lazy, TTL 600s, separate from `llm_semaphore`). Warm latency ~60ms/8 docs; domain gate 16/16 via rerank path. **Download note:** HF `cdn-lfs` is blocked here — fetch LFS files from the `hf-mirror.com` mirror into the HF cache (`model.safetensors` ~2.27GB, `sentencepiece.bpe.model` ~5MB). Recovery: `curl -sL -C - -o <file> https://hf-mirror.com/BAAI/bge-reranker-v2-m3/resolve/main/<file>` into `~/.cache/huggingface/hub/models--BAAI--bge-reranker-v2-m3/snapshots/<commit>/` (snapshot already holds config/tokenizer). Validate: `safe_open(...).keys()` → 393 tensors.
- Visual OCR: MLX-native `mlx-community/GLM-OCR-4bit` (via `mlx-vlm`, lazy-loaded with explicit Metal cache clearing after processing).
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
- **MLX VLM / GLM-OCR Operational Safeguards**:
  - **AutoImageProcessor / Torchvision Requirement**: Hugging Face `transformers`' `AutoImageProcessor` silently falls back to a plain `TokenizersBackend` if `torchvision` (and `torch`) is missing. This completely disables image feature processing and results in blank OCR. Always list both packages as explicit dependencies in `pyproject.toml` to lock perfectly matched versions (`torchvision==0.25.0`, `torch==2.10.0` on M-series chips) and prevent C++ operator registry mismatches (`RuntimeError: operator torchvision::nms does not exist`).
  - **Template Formatting**: For `GLM-OCR` visual models, always apply the chat template using `apply_chat_template` on the task prompt (e.g. `"Text Recognition:"`) to correctly format and align visual token placeholders `<|image|>` for the language model.
  - **Repetition Mitigation**: In dense document OCR tasks, always pass `repetition_penalty=1.2`, `repetition_context_size=64`, and explicit length constraints like `max_tokens=1024` to prevent infinite token loops at the end of the page text.

## Tests

Run these before finalizing meaningful changes:

```bash
uv run pytest -q
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

Preprocess heavy PDFs before indexing (clean + split >40MB; originals go to `_originals/`, idempotent via state file):

```bash
uv run python tools/pdf_preprocess.py RAG_Content/<folder>/ --dry-run   # сначала посмотреть
uv run python tools/pdf_preprocess.py RAG_Content/<folder>/             # выполнить
# или вместе с индексацией: uv run python tools/qwen_index_until_done.py --preprocess-dirs RAG_Content/<folder>
```

Switch the chat LLM (provider/model) — **no restart needed**, applies per-request:

- GUI: `http://127.0.0.1:8051/les/classic` → шапка **⚙** (диалог настроек) → **LLM Provider** → выбрать mlx / ollama / openrouter / openai, указать модель → **💾 Сохранить**. Строка «СЕЙЧАС ОТВЕЧАЕТ» показывает активный провайдер/модель; валидация Т.О.С.К.А. работает только на MLX, остальные дают UNVALIDATED. (Там же — Mail/IMAP.)
- CLI: `curl -X POST http://127.0.0.1:8050/api/settings -H 'Content-Type: application/json' -d '{"llm_provider":"ollama","ollama_model":"gemma4:12b"}'` (персистится в .env runtime-клона). Вернуться: `-d '{"llm_provider":"mlx"}'`.
- Local models live in Ollama (`ollama list`); Gemma 4 12B = `gemma4:12b`. Cloud = openrouter/openai + API key (поля в той же панели).

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

## Documentation

When closing a LES session, update at least:

- `README.md`
- `RAG_MODERNIZATION_PLAN.md`
- `INFRASTRUCTURE_v2.0.md`
- newest `SESSION_SUMMARY_*.md`

Record exact dates, test counts, index counts, model ids, Core ML package names, fallback state, and external smoke state.
