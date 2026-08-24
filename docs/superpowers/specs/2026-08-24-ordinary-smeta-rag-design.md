# Ordinary Smeta RAG Design

## Goal

Retire the separate visible “Сметный проект” and “Смета” chat workflow, expose the
trusted estimate norm base as a normal selectable RAG dataset, and make the LES
FreeToken context setting reflect the physical KV cache after every FreeToken restart.

## Product boundary

- The ordinary chat and dataset selector are the only user-facing workflow.
- The legacy RIM page, chat mode and prompts are not reachable from Sovushka.
- Existing RIM records and protected `proxy/smeta_core/**` code are preserved for
  compatibility; no user data is deleted.
- SQLite remains the typed source of truth for norms. The unified LES collection is a
  searchable projection only and uses the standard dense + `bm25_sparse` contract.
- The norm dataset is selected explicitly and is never injected into unrelated project
  questions.
- `FREETOKEN_CONTEXT_TOKENS` is desired physical KV capacity, not merely a prompt limit.
  LES reports desired/effective values and reconciles a restarted loopback FreeToken
  instance before generation.

## Acceptance

1. Sovushka contains neither the RIM tab/page nor a special “Смета” chat button.
2. The system dataset registry contains one stable, visible estimate-norm dataset.
3. Every published norm point uses the general collection contract, has both standard
   vectors and carries dataset/source provenance.
4. A normal RAG request scoped to that dataset can cite known norm codes.
5. FreeToken restart followed by settings read or generation changes an undersized
   physical KV cache to the configured target, or exposes a precise degraded state.
6. No protected smeta-core file, typed base, user dataset or saved RIM record is mutated.
