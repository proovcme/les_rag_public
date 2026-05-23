# Session Summary — LES v3.6 Qwen Indexing Run

Workspace: `/Users/ovc/Projects/LES_v2`
Date: `2026-05-23`

## Current runtime

- Mode: `indexing`
- Chat generation: `paused`
- Active embedding profile: `qwen`
- Embedding model: `Qwen/Qwen3-Embedding-0.6B`
- API embedding model name: `qwen3-embedding-0.6b`
- Qdrant collection: `les_rag_qwen3_06b`
- SQLite meta DB: `data/les_meta_qwen.db`
- Legacy BGE baseline remains in `les_rag` / `data/les_meta.db`

## Live indexing

- Current scheduler job when this handoff was written: `a532f3d6-d5c`
- Current wave: `max_batches=50`, `batch_limit=1`, `warm_embedder=true`
- Index-until-done LaunchAgent: `me.ovc.les.qwen-index-until-done`
- Runner script: `tools/qwen_index_until_done.py`
- Runner plist: `qwen_index_launchd.plist`
- Runner log: `logs/qwen_index_until_done.log`

The runner waits while any parse scheduler is active. When the current wave finishes, it starts new Qwen waves with `max_batches=1000`, `batch_limit=1`, memory guards enabled, until `pending_files=0`.

## Qwen vs BGE observations

- Qwen uses larger chunks: `RAG_CHUNK_SIZE=1400`, `RAG_CHUNK_OVERLAP=100`.
- Legacy BGE used `900/80`.
- On the first 18 common files:
  - BGE: `3306 chunks`
  - Qwen: `2045 chunks`
  - Ratio: `0.619`
- The lower Qwen chunk count is expected from chunking geometry, not missing documents.
- Bottleneck remains embedding encode (`embed_sec`), not Qdrant/SQLite/conversion.

## Public access

- `https://les.ovc.me` had `502` because VPS Caddy could not reach Mac over ZeroTier `10.195.146.98`.
- Emergency П.А.У.К. reverse tunnel was enabled:
  - Mac SSH tunnel publishes local `8050/8051` to VPS `127.0.0.1:8050/8051`
  - Caddy temporarily points to `127.0.0.1`
- `start_pauk.command` was fixed to use `ssh -f -n -N` and `127.0.0.1` local targets.
- `https://les.ovc.me/` and `/les` currently resolve to `/login` with HTTP 200.
- Caddy now marks requests whose source IP is inside `10.195.146.0/24` with
  `X-LES-Trusted-Network: 1`; UI/proxy trust that header only from
  `TRUSTED_PROXY_NETWORKS`. Spoofed forwarded headers from direct/public clients
  are ignored.

## Implemented in this session

- Embedding profile abstraction in `backend/rag_config.py`.
- Qdrant adapter now reads active collection/vector/chunk/meta settings.
- MLX host loads the configured embedding model and reports profile in health.
- Proxy health/runtime/diagnostics/dataset deletion use the active RAG profile.
- Samovar GUI shows document-level indexed/pending/error status.
- Public `/les` route redirects to login instead of blanking out.
- Qwen benchmark helper: `tools/embedding_profile_benchmark.py`.
- Qwen index-until-done runner: `tools/qwen_index_until_done.py`.

## Checks

- Targeted tests passed:
  - `tests/test_rag_config.py`
  - `tests/test_qdrant_adapter_parse.py`
  - `tests/test_datasets_router.py`
- `git diff --check` passed after edits.
- Live Qdrant/SQLite match stayed true while Qwen indexing was running.

## Next operator actions

- Monitor:
  - `tail -f logs/qwen_index_until_done.log`
  - `curl -s http://localhost:8050/api/health`
  - `curl -s http://localhost:8050/api/jobs`
- Do not start another parse scheduler manually while the runner is active.
- After `pending_files=0`, run BGE vs Qwen golden retrieval comparison before making Qwen the permanent search default.
