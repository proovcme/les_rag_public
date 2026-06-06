# LES Installation Notes

This repository has two very different installation paths:

- **ATLAS / АТЛАС standalone viewer:** ready-to-run, offline-friendly, no Python, no LES backend.
- **Full LES runtime:** developer/local stack with Python 3.12, Qdrant, MLX/OpenAI-compatible models and your own indexed data.

ARTEL / АРТЕЛЬ is described in the README as the Revit-family workflow layer
that should call LES APIs. The public snapshot does not ship a production ARTEL
installer or private RFA/catalog data.

## RU - быстрый выбор

Если нужно просто открыть `cad_bim_graph.json` или IFC:

```bash
cd standalone/cad_bim_viewer
./serve.sh 8095
```

Windows:

```powershell
cd standalone\cad_bim_viewer
powershell -ExecutionPolicy Bypass -File .\serve.ps1 -Port 8095
```

Потом открыть:

```text
http://127.0.0.1:8095/
```

Это самый надежный путь для почти голой машины. В папке уже лежат bundled JS/CSS, `web-ifc.wasm`, fragments worker и demo models. Интернет и LES backend не нужны.

## RU - полный LES runtime

### Требования

- macOS/Linux для runtime; Apple Silicon предпочтителен для MLX.
- Python 3.12.
- `uv` для Python dependencies.
- Docker или локальный Qdrant.
- Достаточно памяти для выбранной LLM/embedding модели.
- Собственные данные для индексации.

### Установка

```bash
git clone https://github.com/proovcme/les_rag_public.git
cd les_rag_public
cp env.example .env
```

Если `uv` не установлен:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Отредактировать `.env` минимум:

```text
JWT_SECRET=replace_with_random_string
ADMIN_PASSWORD=replace_with_strong_password
SOVUSHKA_STORAGE_SECRET=replace_with_random_string
QDRANT_URL=http://127.0.0.1:6333
MLX_URL=http://127.0.0.1:8080
```

Для первого запуска без локальных Core ML artifacts проще переключить embeddings на обычный backend:

```text
EMBED_BACKEND=sentence_transformers
COREML_EMBED_LOCAL_FILES_ONLY=false
COREML_VALIDATOR_LOCAL_FILES_ONLY=false
VALIDATOR_BACKEND=rules
```

Установить зависимости:

```bash
uv sync
```

Поднять Qdrant:

```bash
docker compose up -d qdrant
```

Запустить MLX host:

```bash
uv run python mlx_host.py
```

В другом терминале запустить LES proxy:

```bash
uv run uvicorn proxy_server:app --host 127.0.0.1 --port 8050
```

В третьем терминале можно запустить Совушку:

```bash
uv run python sovushka_ng.py
```

Проверить:

```bash
curl http://127.0.0.1:8050/api/health
curl http://127.0.0.1:8080/api/health
```

После этого доступен backend/API слой:

```text
http://127.0.0.1:8050/api/health
http://127.0.0.1:8050/api/status
http://127.0.0.1:8050/api/chat
http://127.0.0.1:8050/api/cad-bim/import
http://127.0.0.1:8050/api/mail/threads
```

Совушка после запуска:

```text
http://127.0.0.1:8051/             lite chat
http://127.0.0.1:8051/les          lite admin
http://127.0.0.1:8051/classic      classic chat
http://127.0.0.1:8051/les/classic  classic admin
```

Это dev/local UI entrypoint. Он не включает приватные launchd scripts, production tunnel config, keys, corpora или готовые индексы.

### Индексация данных

Создай локальную папку:

```bash
mkdir -p RAG_Content
```

Клади туда документы, таблицы, почту и CAD/BIM JSON. Public snapshot поддерживает эти входы:

```text
PDF, DOCX, DOC, MD, TXT
XLSX, XLS, CSV
EML, EMLX, MSG
JSON, JSONL
DWG, DXF, RVT, IFC, IFCZIP at upload boundary
```

Важно: raw DWG/RVT/IFC лучше сначала переводить в canonical JSON:

```text
cad_bim_graph.json
```

Через exporters или IFC/DXF tools, а потом импортировать в LES.

### Почта

Mail pipeline умеет:

- локальные `.eml`, `.emlx`, `.msg`;
- Apple Mail import;
- IMAP import;
- threads / participants / who-to-whom profile;
- attachment text extraction;
- OCR вложений при включенной настройке.

Секреты почты не хранятся в репозитории. Настройки берутся из `.env` или UI/API:

```text
MAIL_IMAP_HOST=
MAIL_IMAP_PORT=993
MAIL_IMAP_SSL=true
MAIL_IMAP_LOGIN=
MAIL_IMAP_PASSWORD=
MAIL_IMAP_FOLDERS=INBOX
MAIL_APPLE_ROOT=~/Library/Mail
```

### Runtime safety

LES не пытается одновременно делать всё любой ценой. В public code есть:

- runtime profiles: `CHAT`, `CHAT_VALIDATED`, `INDEX_LIGHT`, `INDEX_HEAVY_PDF`, `MAINTENANCE`;
- memory pressure states: `GREEN`, `YELLOW`, `RED`, `CRITICAL`;
- chat admission control;
- блокировка генерации при активной тяжелой индексации;
- parse concurrency limits;
- guarded reindex tools;
- MLX memory telemetry and unload hooks.

Это особенно важно на локальных Apple Silicon машинах, где LLM, OCR, embeddings и parsing делят одну память.

### Chunking and retrieval

LES использует не один плоский splitter:

- deterministic document router;
- domain datasets;
- metadata-rich chunks;
- table/mail/CAD-BIM specialized channels;
- vector retrieval + lexical FTS;
- RRF merge;
- optional reranking;
- context windows around retrieved chunks;
- route-change reindex utilities.

Это не делает public snapshot production-ready автоматически, но показывает архитектуру, на которой можно собрать нормальную локальную инженерную базу знаний.

## EN - quick choice

If you only need to open `cad_bim_graph.json` or IFC:

```bash
cd standalone/cad_bim_viewer
./serve.sh 8095
```

Windows:

```powershell
cd standalone\cad_bim_viewer
powershell -ExecutionPolicy Bypass -File .\serve.ps1 -Port 8095
```

Open:

```text
http://127.0.0.1:8095/
```

This is the reliable path for an almost bare workstation. The folder already ships bundled JS/CSS, `web-ifc.wasm`, the fragments worker and demo models. No internet or LES backend is required.

## EN - full LES runtime

### Requirements

- macOS/Linux for runtime; Apple Silicon is preferred for MLX.
- Python 3.12.
- `uv` for Python dependencies.
- Docker or local Qdrant.
- Enough memory for the selected LLM/embedding model.
- Your own data to index.

### Setup

```bash
git clone https://github.com/proovcme/les_rag_public.git
cd les_rag_public
cp env.example .env
```

If `uv` is not installed:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Edit `.env` at least:

```text
JWT_SECRET=replace_with_random_string
ADMIN_PASSWORD=replace_with_strong_password
SOVUSHKA_STORAGE_SECRET=replace_with_random_string
QDRANT_URL=http://127.0.0.1:6333
MLX_URL=http://127.0.0.1:8080
```

For the first run without local Core ML artifacts, use the simpler embedding/validator path:

```text
EMBED_BACKEND=sentence_transformers
COREML_EMBED_LOCAL_FILES_ONLY=false
COREML_VALIDATOR_LOCAL_FILES_ONLY=false
VALIDATOR_BACKEND=rules
```

Install dependencies:

```bash
uv sync
```

Start Qdrant:

```bash
docker compose up -d qdrant
```

Start MLX host:

```bash
uv run python mlx_host.py
```

Start LES proxy in another terminal:

```bash
uv run uvicorn proxy_server:app --host 127.0.0.1 --port 8050
```

Optionally start Sovushka in a third terminal:

```bash
uv run python sovushka_ng.py
```

Check:

```bash
curl http://127.0.0.1:8050/api/health
curl http://127.0.0.1:8080/api/health
```

After that the backend/API layer is available:

```text
http://127.0.0.1:8050/api/health
http://127.0.0.1:8050/api/status
http://127.0.0.1:8050/api/chat
http://127.0.0.1:8050/api/cad-bim/import
http://127.0.0.1:8050/api/mail/threads
```

Sovushka URLs:

```text
http://127.0.0.1:8051/             lite chat
http://127.0.0.1:8051/les          lite admin
http://127.0.0.1:8051/classic      classic chat
http://127.0.0.1:8051/les/classic  classic admin
```

This is a dev/local UI entrypoint. It does not include private launchd scripts, production tunnel config, keys, corpora or ready-made indexes.

### Data indexing

Create a local content folder:

```bash
mkdir -p RAG_Content
```

Supported public inputs:

```text
PDF, DOCX, DOC, MD, TXT
XLSX, XLS, CSV
EML, EMLX, MSG
JSON, JSONL
DWG, DXF, RVT, IFC, IFCZIP at upload boundary
```

For CAD/BIM, the preferred path is JSON-first:

```text
cad_bim_graph.json
```

Use exporters or IFC/DXF tools, then import the JSON into LES.

### Mail

The mail pipeline supports:

- local `.eml`, `.emlx`, `.msg`;
- Apple Mail import;
- IMAP import;
- threads, participants and who-to-whom profile;
- attachment text extraction;
- attachment OCR when enabled.

Mail secrets are not committed. Configure them through `.env` or UI/API:

```text
MAIL_IMAP_HOST=
MAIL_IMAP_PORT=993
MAIL_IMAP_SSL=true
MAIL_IMAP_LOGIN=
MAIL_IMAP_PASSWORD=
MAIL_IMAP_FOLDERS=INBOX
MAIL_APPLE_ROOT=~/Library/Mail
```

### Runtime safety

LES does not try to do everything at once at any cost. The public code includes:

- runtime profiles: `CHAT`, `CHAT_VALIDATED`, `INDEX_LIGHT`, `INDEX_HEAVY_PDF`, `MAINTENANCE`;
- memory pressure states: `GREEN`, `YELLOW`, `RED`, `CRITICAL`;
- chat admission control;
- chat blocking during heavy indexing;
- parse concurrency limits;
- guarded reindex tools;
- MLX memory telemetry and unload hooks.

This matters on local Apple Silicon machines where LLM, OCR, embeddings and parsing share unified memory.

### Chunking and retrieval

LES is not just a flat splitter:

- deterministic document router;
- domain datasets;
- metadata-rich chunks;
- table/mail/CAD-BIM specialized channels;
- vector retrieval + lexical FTS;
- RRF merge;
- optional reranking;
- context windows around retrieved chunks;
- route-change reindex utilities.

The public snapshot is not automatically production-ready, but it shows the architecture needed for a serious local engineering knowledge base.
