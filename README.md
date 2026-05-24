# LES RAG

LES RAG is a local-first retrieval-augmented generation project for working with
technical documents. It indexes files into a vector database, retrieves relevant
fragments for a user question, and generates an answer with source references.

The project is designed for private deployments where documents should stay on
the operator's machine or inside a controlled network.

## Features

- Document intake for PDF, DOCX, spreadsheets, text, Markdown, JSON, and mail-like formats.
- Deterministic document routing into domain-specific datasets.
- Qdrant-backed vector search.
- Local embedding and generation endpoints.
- FastAPI proxy for chat, retrieval, indexing, diagnostics, and administration.
- Optional NiceGUI interface for chat and operational views.
- SQLite metadata for datasets, documents, jobs, metrics, and access keys.
- Conservative indexing mode with memory guards and resumable background waves.

## Architecture

```text
Documents
   |
   v
Intake and routing
   |
   v
Chunking and embeddings
   |
   v
Qdrant + SQLite metadata
   |
   v
Retrieval API
   |
   v
Local generation and validation
   |
   v
Answer with sources
```

Typical services:

- `proxy_server.py` starts the FastAPI application.
- `mlx_host.py` provides local model endpoints.
- Qdrant stores vectors.
- SQLite stores metadata and job state.
- `les.command` manages the local runtime.

## Requirements

- macOS or Linux
- Python 3.12+
- `uv`
- Qdrant, either local binary or containerized
- A local embedding/generation endpoint compatible with the configured API

Apple Silicon with MLX is the primary development target, but the repository is
structured so that model and vector services can be configured through
environment variables.

## Quick Start

```bash
git clone https://github.com/proovcme/les_rag_public.git
cd les_rag_public

uv sync
cp env.example .env
```

Edit `.env` for local paths, model endpoints, authentication settings, and
Qdrant settings.

Start the local runtime:

```bash
./les.command start
```

Check health:

```bash
curl http://127.0.0.1:8050/api/health
```

## Indexing Documents

Place source files under `RAG_Content/`, then inspect and run sync/indexing
through the API or UI.

Example:

```bash
curl -s http://127.0.0.1:8050/api/rag/smart-plan | python3 -m json.tool
```

The indexing helpers are intentionally conservative: they process small batches,
respect memory guards, and keep job state visible through `/api/jobs`.

## Development

Run focused tests:

```bash
uv run python -m pytest tests/test_document_router.py tests/test_retrieval_service.py
```

Run syntax checks for operational scripts and services:

```bash
uv run python -m py_compile \
  backend/document_router.py \
  proxy/services/retrieval_service.py \
  tools/qwen_index_until_done.py
```

## Security Notes

This repository is a development project, not a managed service. Before exposing
it outside a local machine or private network, review authentication, trusted
network settings, reverse-proxy headers, firewall rules, secrets, and document
retention policies.

Do not commit private datasets, `.env` files, generated indexes, logs, or local
database files.

## Status

The codebase is under active development. Interfaces, configuration keys, and
operational scripts may change between commits.
