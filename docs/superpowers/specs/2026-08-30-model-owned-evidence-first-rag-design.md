# Model-Owned Evidence-First RAG Design

**Status:** owner-approved direction; implementation on `0.30.0`
**Base:** `9cddee74b4818bf03d9f3e8b75ac920c85c19692`
**Primary model:** local Qwen 3.5 9B; larger models use the same semantics

## Goal

LES gives the model truth from the sources selected by the user and lets the model decide how to research and answer. Code retrieves, reads, calculates, stores, transports and displays. It does not grade, reject, rewrite, repair or replace the model's semantic or professional decision.

The ordinary grounded-chat path must prove two things:

1. the initial retrieval is the common contract-clean native `dense + bm25_sparse` RRF inside the exact explicit scope;
2. the model sees that initial evidence before it decides whether and how to search or read again.

## Product scope

Document scope has three explicit states:

- `none`: no document RAG and no document search/read tools; LES remains an ordinary AI agent with other profile-authorized tools;
- `selected`: only selected datasets and attachments participate;
- `all`: the user explicitly selected the complete user-visible corpus.

Keywords may suggest sources in the UI but never activate a dataset, infer a professional corpus or turn `none` into `all`. Attachments are explicit sources for the turn. System and role datasets participate only when explicitly selected by the user or explicitly bound by the active role profile.

Documents and permitted web results are evidence. Memory, dataset maps, reader summaries and project guidance are navigation/advisory context, not evidence. Internet search may run automatically when the active profile permits it; web evidence remains separately labelled with direct links.

## Model authority

The model decides:

- what the question means;
- whether the initial evidence is enough;
- what additional query or exact read to request;
- whether a source is relevant or contradictory;
- what conclusion follows;
- whether to continue research or answer.

The final professional decision remains with the person.

Every model output is retained as produced. A tool that cannot execute returns its technical result to the model. An unavailable file, empty search, unresolved locator or interrupted operation never authorizes code to create, replace or suppress the model's answer.

## Target turn flow

For `selected` or explicit `all`:

```text
freeze explicit scope
  -> bypass ready-answer cache
  -> initial native RRF
  -> build exact evidence packet and source map
  -> model receives question + initial evidence + available tools
  -> model optionally requests native-RRF searches and exact reads
  -> execute requested tools in the same scope
  -> return tool results to the same model-owned research conversation
  -> model answers
  -> preserve answer and expose exact model/evidence trace
```

The research decision and final synthesis use the same effective model/profile. A second model is an optional future tool chosen by orchestration, not a requirement or hidden validator.

For `none`, the initial RAG and document tools are absent. The conversation still reaches the configured model.

## Retrieval and tools

Initial retrieval and every model-requested `search_sources` call use one shared operation:

1. preserve the user- or model-authored query except generic Unicode/whitespace normalization;
2. produce the configured dense query embedding;
3. execute named `dense + bm25_sparse` native RRF in the frozen scope;
4. apply only common configured retrieval stages;
5. expand parent/context windows;
6. return evidence with exact source coordinates.

No stage injects domain prose, expected answers, dataset-specific boosts or professional choices. The lexical Document Explorer remains available for exact word diagnostics and in-document reads, but it is not the semantic `search_sources` implementation.

`read_source`, PDF/table readers and other exact readers return source text/rows/pages as requested. Code does not decide whether their content proves the model's conclusion.

## Context contract

The effective context capacity comes from the model connection:

- use the operator-requested context when it is the only declared capacity;
- cap it by observed backend capacity when an observation exists;
- use the factory fallback only when neither requested nor observed capacity exists;
- workflow restrictions may narrow tool effects, but a model-family preset must not silently reduce an explicitly configured larger context to 6000 tokens.

`ContextGovernor` reserves generation and physical safety capacity, then packs in this semantic priority:

1. required profile and current request;
2. current evidence and source map;
3. latest model-requested tool results;
4. workflow checkpoint;
5. compact working memory and navigation;
6. older dialogue.

Objects remain whole. Every omission is visible. Evidence is never silently placed behind advisory memory.

The system may stop physical execution on user cancellation, backend failure or a visible transport/resource limit. It preserves accumulated evidence and output and reports the technical stop reason. It does not stop because code considers a model query repetitive or unproductive.

## Cache and empty retrieval

Semantic answer cache is neither read nor written for grounded turns. Parsing, immutable index and provider KV caches remain allowed because they do not replace fresh retrieval or generation.

Empty retrieval is an ordinary result delivered to the model together with scope and available tools. Code does not return a professional `NO_DATA` answer. The model may reformulate, read a named source or state that the answer was not found.

## Evidence trace

The local trace reconstructs every model call:

- effective model/profile and context capacity source;
- exact explicit scope;
- exact initial and follow-up queries;
- retrieval contract, collection generation and returned source identities;
- exact evidence text and source map actually included in that model call;
- omitted evidence objects with reason and stable reread locator;
- tool shortlist, model-requested calls, tool results and physical stop reason;
- final answer unchanged.

The trace is for the person to inspect what the model saw and did. It is not an answer approval mechanism. Secrets and unrelated private data are never traced.

## Acceptance

Offline tests prove scope, cache bypass, shared native RRF, evidence-first packing, tool access and exact trace reconstruction. They do not grade model quality.

The primary live Qwen 3.5 9B request is exactly:

> Расскажи про датасет.

It runs against one explicitly selected representative project dataset with `rrf_ready=true`. The harness injects no expected topics, document names, conflict hints or answer outline.

Acceptance requires the trace to prove what the model saw and what it requested. The owner evaluates whether the answer gives a useful grounded picture of the dataset, cites exact human-readable source locations, notices contradictions or gaps when present and avoids unsupported corpus claims.

The historical boiler-room `Н/М/Х` case remains a secondary regression for spontaneous contradiction discovery. It does not define the retrieval algorithm and its expected values are never injected into the model path.

## Non-goals

- changing chunking, embeddings, Qdrant vector schema or user data;
- reindexing the complete corpus;
- changing protected `proxy/smeta_core/**` or smeta decisions;
- adding professional answer templates, a critic or a mandatory second model;
- changing updater, installer or public release behavior;
- building the full evidence-inspector UI in this slice.

## Rollback

The change is code/configuration only and performs no dataset migration. Rollback returns to the previous verified commit; user documents, indexes, memories and traces remain untouched.
