# Proxy Server Architecture

**Updated:** 2026-05-22. The active proxy is the modular `proxy/` package; `proxy_server.py` is a thin compatibility entrypoint. LLM calls go through MLX Host by default, with Ollama kept as a reserve path.

## Overview
The `proxy_server.py` module exposes the FastAPI app, while `proxy/app.py` owns app composition, middleware, router state, startup, and route registration. It interacts with Qdrant, MLX Host, SQLite metadata, and local file storage to provide dataset management, document ingestion, chat queries, SafeRAG validation, jobs, diagnostics, and auth.

> Scope: этот документ описывает **прокси-слой** (FastAPI app, маршрутизация, БД, поток данных). Актуальное ядро продукта — детерминированные каналы чата, ProfileResolver, Parquet-числа (счёт без LLM) и MCP-сервер — см. `docs/MODULE_INDEX.md` и `docs/CODE_MAP.md`.

## Modules and Dependencies
- **FastAPI**: Used for building the web server.
- **asyncio**: For handling asynchronous operations.
- **psutil**: To gather system metrics.
- **sqlite3**: For database interactions.
- **httpx/requests**: For HTTP requests to local MLX/Qdrant/runtime services.
- **sse_starlette**: For Server-Sent Events (SSE) support.
- **proxy/routers/**: Auth, chat, chat history, datasets, diagnostics, jobs, logs, rerank, runtime, settings, status page.
- **proxy/services/**: Retrieval, SafeRAG, semantic cache, durable job tracking.

## Data Flow
1. **Requests Handling**:
   - Incoming requests are processed by FastAPI endpoints.
   - Requests are validated and routed to appropriate handlers.

2. **Database Interactions**:
   - The server interacts with two SQLite databases: `les_meta_qwen.db` and `les_metrics.db`.
   - `les_meta_qwen.db` (active metabase) stores metadata about datasets and documents.
   - `les_metrics.db` logs system metrics for monitoring.

3. **Backend Services**:
   - The server communicates with Qdrant for vector storage and retrieval.
   - MLX Host is used for language model generation, validation and rerank.
   - Ollama is retained only as a reserve/local-assistant dependency.

4. **Job Tracking**:
   - Durable jobs are stored in SQLite and merged with live in-memory jobs by `/api/jobs`.

5. **Server-Sent Events (SSE)**:
   - SSE is used to stream logs and real-time updates to clients.

## SQL Schema
### les_meta_qwen.db
- **datasets**: Stores information about datasets.
  - `id`: Dataset ID.
  - `name`: Dataset name.
  - `status`: Status of the dataset.
  - `doc_count`: Number of documents in the dataset.
  - `chunk_count`: Number of chunks in the dataset.

- **documents**: Stores metadata about individual documents.
  - `id`: Document ID.
  - `dataset_id`: Foreign key to datasets.
  - `file_name`: Name of the file.
  - `content`: Content of the document.

### les_metrics.db
- **metrics**: Logs system metrics.
  - `id`: Metric entry ID.
  - `timestamp`: Timestamp of the metric.
  - `cpu`: CPU usage percentage.
  - `ram_used`: Used RAM in GB.
  - `ram_total`: Total RAM in GB.
  - `swap_used`: Used swap space in GB.
  - `disk_used`: Used disk space in GB.
  - `disk_total`: Total disk space in GB.
  - `ollama_ram`: Ollama's RAM usage in GB.
  - `network_ok`: Number of network targets that are reachable.
  - `heartbeat_collector`: Heartbeat timestamp for the metrics collector.
  - `heartbeat_sse`: Heartbeat timestamp for SSE.

## Endpoints
- **/api/health**: Returns the health status of the backend services.
- **/api/metrics**: Provides system and pipeline metrics, including RAG statistics.
- **/api/rag/datasets**: Lists all datasets.
- **/api/rag/datasets/{name}**: Creates a new dataset with the specified name.
- **/api/rag/sources**: Lists all sources and their associated datasets.
- **/api/rag/sync/{folder}**: Synchronizes a folder with a dataset.
- **/api/rag/upload/{dataset_id}**: Uploads a file to a dataset.
- **/api/chat**: Processes chat queries using the RAG model.
- **/api/chat/history**: Returns chat messages for a session.
- **/api/chat/sessions**: Returns saved sessions for the history drawer.
- **/api/auth/**: В.О.Л.К. key verification and admin key lifecycle.
- **/api/diag**: Read-only diagnostics for Sovushka.
- **/api/jobs**: Returns the status of ongoing jobs.
- **/api/logs/stream**: Streams logs in real-time.
- **/**: Serves proxy status page on port 8050.

UI is served separately by NiceGUI on port 8051:
- **/**: chat shell (AI ЧАТ, history drawer, artifacts panel).
- **/les**: admin shell.

## CRAG (Content Retrieval and Generation)
SafeRAG/CRAG is responsible for retrieving relevant content from datasets and generating responses using a local language model. It involves:
1. Content retrieval from Qdrant based on user queries.
2. Optional reranking by the validation model.
3. Source concentration to reduce context contamination.
4. MLX generation.
5. Т.О.С.К.А. validation (`VERIFIED`, `NO_DATA`, `HALLUCINATION`, `UNKNOWN`).
6. Safe fallback when the answer is not confirmed.

## Cache and Document Routing
- Semantic cache stores only `VERIFIED` answers and invalidates by dataset scope.
- Document Router probes files before ingestion and chooses Markdown, Parquet, PDF table extraction or OCR-needed route.
- XLSX/CSV ingestion creates row-level chunks and `.parquet` artifacts.
