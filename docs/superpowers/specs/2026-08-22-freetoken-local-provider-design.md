# FreeToken Local Provider Design

## Goal

Run FreeToken's local `Qwen3.6-35B-A3B-NVFP4` as a first-class LES answer and tool-routing model on Legion without classifying loopback traffic as cloud, exhausting the model context, or exposing hidden reasoning.

## Boundaries

- Keep Ollama `qwen3.5:9b` as the production default; FreeToken is an explicit operator choice.
- Do not modify `proxy/smeta_core/**` or smeta professional defaults.
- Do not reindex or delete RAG data. Qdrant repair is alias/storage recovery with exact count checks.
- Do not commit, push, publish, or overwrite unrelated dirty-worktree changes.

## Provider contract

`freetoken` is a local provider with `FREETOKEN_BASE_URL`, `FREETOKEN_MODEL`, `FREETOKEN_CONTEXT_TOKENS`, and `FREETOKEN_PROMPT_MAX_CHARS`. It uses the local generation semaphore and memory guard, is never cloud-billed, and is never blocked by dataset sensitivity routing.

Every FreeToken chat-completion body carries `chat_template_kwargs.enable_thinking=false`. The same transport profile is used by normal/free/RAG generation and the small agent-router call.

## Prompt budgeting

The provider publishes a conservative total prompt character ceiling derived from its configured context window. RAG reserves generation tokens, preserves bounded session/working memory, then fills the remaining prompt with the common multi-document evidence assembler. FreeToken does not impose a separate chunk-count cap: the same assembler covers distinct source documents first and stops at the derived capacity. Lower-priority navigation is truncated after evidence. The configurable chars/token ratio is a transport safety estimate, not a domain rule.

## Tools and commands

`QueryIntent.intent` remains a compatibility alias for `channel`, preventing the model-owned research loop from failing before tool selection. The agent router resolves FreeToken automatically when it is the active provider and applies the same no-thinking request profile. `/проекты` continues to rewrite to the model-first registry workflow; the repaired tool loop supplies typed registry evidence instead of treating a registry map as a code-written professional answer.

## Windows and GUI

The Windows start script accepts provider `freetoken`, points answer generation to port 1919 by default, and keeps embeddings on Ollama. FreeToken factors are registered in the GUI-owned runtime registry with effective value, source, and restart metadata.

## Verification

Unit tests cover provider locality, request-body normalization, prompt limits, QueryIntent compatibility, router configuration, and Windows startup. Focused chat/retrieval tests run before `make verify` and `make test`. Live Legion smoke must show the selected model, no reasoning-only empty answer, an under-budget RAG prompt, tool-loop completion, and exact Qdrant alias/count readiness.

### Layered smeta acceptance

FreeToken/smeta failures are diagnosed by the smallest probe that can falsify one
hypothesis. A complete XLSX run is release acceptance, not a debugging tool. The
ordered gates are:

1. offline transport projection: historical audit turns are absent from the
   inference frame while system/source, latest tool exchange, authoritative
   working memory and terminal instruction remain;
2. isolated FreeToken forced-tool probe: the current physical KV budget accepts
   the intended prompt plus generation reserve without touching RAG, datasets or
   checkpoints;
3. offline checkpoint contract: one accepted source row is persisted before the
   next row and resume does not replay it;
4. one live row from a preserved attachment/checkpoint;
5. a bounded five-row resume slice, only after the one-row result is inspected.

Each gate records exact input, expected output, elapsed time and evidence. A
failure stops the sequence and is fixed at that layer; it never triggers a longer
fallback run. The 70-row fixture and other full documents require an explicit
owner decision after gates 1-5 pass. A new upload is not evidence of resume when
the original opaque attachment identity is unavailable.
