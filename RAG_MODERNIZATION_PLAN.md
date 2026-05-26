# LES RAG Modernization Plan

Updated: 25.05.2026

This plan starts only after the current Qwen indexing run reaches zero pending files and Qdrant/SQLite counts are verified. The current index is treated as a valuable artifact: no full reindex is allowed unless a step explicitly proves it is necessary.

## Current Constraint

- The active bottleneck is embeddings, not Qdrant, conversion, or chunking: recent parse batches show about 99% of elapsed time in `embed_sec`.
- During indexing, chat generation remains paused by indexing mode to protect MLX memory.
- The small model is currently a validator and optional reranker, not a default query preprocessor.

## Phase 0: Freeze And Verify

1. Wait for `pending_files=0` and `error_files=0`.
2. Verify `sqlite_chunks == qdrant_points`.
3. Snapshot SQLite and Qdrant before Docker removal or retrieval experiments.
4. Run the golden retrieval set and record baseline top sources, scores, latency, memory.

## Phase 1: Fix Cheap Runtime Issues

1. Show `/api/chat` `409 indexing mode` clearly in UI instead of "no answer".
2. Replace chat `innerHTML` rendering with safe DOM/text rendering for answers and sources.
3. Return the effective inferred `dataset_filter` in `/api/chat` responses.
4. Expand validator context from a short arbitrary snippet to cited retrieval windows.
5. Put reranker calls under the same LLM semaphore/resource budget as generation.

## Phase 2: Attack The Embedding Bottleneck

1. Benchmark `RAG_EMBED_BATCH`: `8 -> 16 -> 24 -> 32` on a small controlled sample.
2. Keep concurrency conservative; prefer larger batches over parallel embedding requests.
3. Add chunk-text hash caching for future retries and partial reindexing.
4. Test normative chunk profiles: larger chunk size, lower overlap, no split inside numbered clauses where possible.
5. Keep every benchmark tied to memory, swap, files/hour, chunks/file, and retrieval golden-set quality.

## Phase 3: Retrieval Quality Before More LLM

1. Add query-side instructions for Qwen3 embeddings and test them without reindexing.
2. Add hybrid retrieval: dense vectors + sparse/exact lexical search with RRF/fusion.
3. Add a retrieval evaluator before generation: if top results are weak, conflicting, or too broad, rewrite/expand the query and retrieve again.
4. Add conditional reranking only for uncertain retrieval, not for every request.
5. Prefer a specialized Qwen3 reranker over prompt-reranking through the validator model.

## Phase 3.5: K.O.T. Terminology Filter

The current K.O.T. behavior is only a draft embedded in `query_router.py`, `clarification_service.py`, and `retrieval_service.py`. After indexing, promote it into a first-class configurable semantic terminology filter:

1. Move domain rules, trigger tokens, synonyms, and dataset mappings into YAML or SQLite-backed configuration.
2. Add a small admin UI for terminology domains, synonyms, route priority, and suggested filters.
3. Return K.O.T. trace data in `/api/chat`: route reason, inferred `dataset_filter`, matched domains, clarification reasons, and confidence.
4. Add golden-set tests for engineering wording, abbreviations, mixed Russian/Latin terms, and ambiguous broad-review prompts.
5. Keep the default path deterministic; use a small model only for ambiguous, multi-domain, or multi-hop queries after the rule-based pass.

## Phase 4: Hierarchical And Graph Layers

1. Add parent-document retrieval: retrieve small chunks, then include parent sections around cited chunks.
2. Build RAPTOR-lite summaries for documents/datasets where broad questions are common.
3. Build GraphRAG-lite only for high-value relations:
   - document -> clause
   - clause -> referenced SP/GOST
   - document -> topic/domain
   - project artifact -> normative requirement
4. Do not run full GraphRAG over the whole corpus until the lighter graph proves value on the golden set.

## Phase 5: Small Model Policy

Use the small model conditionally:

- validator after generation;
- reranker when retrieval confidence is low;
- query planner/rewrite only for broad, ambiguous, or multi-hop questions;
- never as a mandatory preprocessor for every simple routed query.

The default path should remain cheap:

```text
rule-based router -> retrieval -> answer -> validation
```

The adaptive path should be explicit:

```text
rule-based router -> retrieval -> retrieval evaluator
  -> conditional rewrite/rerank -> answer -> validation
```

## References To Revisit

- Qdrant hybrid search and RRF/fusion.
- Qdrant multivectors / ColBERT-style late interaction.
- Qwen3 Embedding and Qwen3 Reranker model cards.
- CRAG / corrective retrieval before generation.
- Adaptive-RAG query complexity routing.
- RAPTOR hierarchical retrieval.
- Microsoft GraphRAG, limited to GraphRAG-lite for this corpus.
