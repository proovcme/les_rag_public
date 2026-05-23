# Session Summary — LES v3.5 Resource Governor + Indexing Control

Workspace: `/Users/ovc/Projects/LES_v2`
Date: `2026-05-23`

## Current runtime

- Mode: `chat`
- Chat generation: `allowed`
- MLX models: unloaded after final checks
- Qdrant/SQLite: `points_match_sqlite_chunks=true`
- Final RAG snapshot:
  - `files=801`
  - `indexed_files=9`
  - `pending_files=792`
  - `chunks=850`
  - `qdrant.points=850`
  - `errors=0`

## Implemented

- Host runtime stabilized: Qdrant remains the only Docker/OrbStack service; proxy/SQLite/MLX/UI run on host.
- Smart intake and routing:
  - `backend/smart_index.py`
  - `/api/rag/smart-plan`
  - `/api/rag/sync-smart`
  - `/api/rag/upload-smart`
- Chat quality and safety:
  - clarification gate before retrieval/LLM;
  - table query MVP from Parquet payloads;
  - golden retrieval set in `golden/ntd_golden_set.json`.
- Resource Governor v1:
  - `proxy/services/resource_governor.py`;
  - `/api/indexing-mode`;
  - chat generation returns `409` while indexing mode is active.
- Parse scheduler improvements:
  - priority order: `NTD_FIRE → GKRF → NTD_ELECTRICAL → NTD_STRUCTURAL → TABLE_SMETA → NTD_OTHER`;
  - post-batch memory hysteresis;
  - `warm_embedder`;
  - phase timings: `convert/chunk/embed/upsert/count`.
- BGE/chunk operator knobs:
  - `BGE_MODEL`
  - `BGE_BATCH_SIZE`
  - `RAG_EMBED_BATCH`
  - `RAG_CHUNK_SIZE`
  - `RAG_CHUNK_OVERLAP`
  - `RAG_PARSE_POST_MAX_SWAP_PCT`

## Measured bottleneck

Control NTD_FIRE batch:

```text
elapsed_sec: 30.9
embed_sec:   29.538
chunk_sec:    1.121
convert_sec:  0.084
upsert_sec:   0.086
count_sec:    0.015
```

Conclusion: the indexing bottleneck is BGE-M3 embedding and memory/swap pressure, not Qdrant, SQLite, or conversion.

## Checks

- `uv run pytest -q` → `107 passed`, 1 known Pydantic v1 `@validator` warning.
- Targeted scheduler/parser tests → passed.
- `git diff --check` → OK.
- Live `/api/health` → Qdrant/SQLite match.
- Live `/api/indexing-mode` → `active=false`, `chat_generation_allowed=true`.

## Next session

Start with an independent architecture assessment before more implementation.

Review as an external architect:

- Resource Governor design and failure modes.
- MLX/BGE memory lifecycle and swap policy.
- Parse scheduler strategy and persistence.
- RAG quality gates: golden set, SafeRAG, retrieval traces.
- Operator procedure clarity: chat mode vs indexing mode.
- Whether current abstractions are sufficient or hiding coupling.

Do not start new feature work until risks and priorities are written down.
