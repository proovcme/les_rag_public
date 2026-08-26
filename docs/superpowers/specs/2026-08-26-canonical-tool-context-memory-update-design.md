# Canonical Tool, Context, Memory and Artifact Update Design

**Status:** owner-approved architecture; active for every new change
**Release:** `0.29.0`, delivered as a lightweight GitHub update when the release classifier allows it
**Base:** public `v0.28.2` at `e8ccad2bedbc402f94ddca7db0794f4c137e18d5`

## Purpose

LES already proved that its models can retrieve useful evidence from the common
native-RRF RAG. The next release must not reintroduce a deterministic smeta
orchestrator around that capability. The model reads evidence, makes the
professional choices and composes the result. Typed code exposes bounded tools,
checks references and provenance, calculates deterministic values and writes
versioned artifacts.

Every primary workflow must complete on local Qwen 3.5 9B. Qwen 35B uses the
same workflow and contracts with a larger context/memory budget. A workflow
that only succeeds on 35B is not a primary LES workflow.

## One active architecture

The request path is:

```text
user + attachment + explicit scope
  -> common native-RRF evidence
  -> ContextGovernor(model preset + workflow restriction + backend capacity)
  -> model
  -> Capability Broker shortlist
  -> canonical Tool Registry
  -> Trusted Executor
  -> typed result + provenance + checkpoint
  -> model-composed answer
  -> versioned artifact
```

There is no estimator-specific chat intercept, regex intent router or second
tool family. The protected `proxy/smeta_core/**` remains a compatibility/library
boundary and is not a workflow entry point for new code.

## Canonical workbook tools

PR13 established the correct product contracts:

- `build_lsr_workbook` creates an append-only LSR draft artifact;
- `build_vor_workbook` creates an append-only VOR draft artifact.

These exact names are canonical. Provider projections may adapt their schemas
to Ollama, FreeToken/OpenAI-compatible, OpenAI or MCP, but no provider-specific
business implementation or parallel `estimate_*` alias is introduced.

The model alone decides whether to call a tool. Natural-language regexes may
not force a call. Chat profiles provide an immutable allowlist, but installing
the release never activates a new profile revision or rebinds an existing chat.

The useful PR13 transport behavior is retained:

- `dataset_ids=None` normalizes to an empty explicit scope list;
- long work emits progress/heartbeat through the existing SSE stream;
- once progress begins, the UI never silently retries the request;
- artifacts are harvested into chat history and remain downloadable;
- attachment identity survives retry/resume.

The first adapter may call a verified existing library function internally, but
the public contract and checkpoint must not depend on that implementation. The
old five-row smeta benchmark is not acceptance evidence for this route.

## Registry, broker and executor

Every capability is described once as a provider-neutral `ToolContract` with:

- stable name and semantic version;
- input and structured result schemas;
- effect class (`read`, `compute`, `draft`, `commit`, `external`, `destructive`);
- scope, timeout, retry and idempotency rules;
- provenance behavior and model-owned decision fields;
- result budget, cursor and availability contract.

The Capability Broker intersects the immutable profile allowlist with current
scope, workflow phase, runtime availability, model preset and remaining call
budget. It can shorten the menu but cannot select a norm, coefficient, scope or
professional answer.

The Trusted Executor validates the contract, scope, authorization, approval,
idempotency and result envelope. Drafts are append-only. Commit, external and
destructive effects require explicit durable approval bound to the exact
proposed revision.

## ContextGovernor and model presets

Every model request passes through one `ContextGovernor`. Individual services
may produce typed candidates, but may not independently truncate inference JSON
with unrelated character limits.

Packing priority is:

1. stable profile prefix and the current tool shortlist;
2. current request and workflow checkpoint;
3. compact typed working memory;
4. selected evidence and source map;
5. latest relevant tool exchange;
6. dialogue turns not already represented in memory.

Generation and safety reserves are allocated before evidence expansion.
Overflow returns omitted counts and stable references/cursors; JSON is never
cut in the middle.

Configuration precedence is:

1. safety and workflow invariants;
2. observed backend/model capacity;
3. immutable factory model preset;
4. optional operator preset cloned from a factory preset;
5. workflow/profile restrictions, which may only narrow the result.

Ollama and FreeToken remain authoritative for physical model/KV configuration.
LES does not rewrite or restart them. The GUI shows
`requested -> effective · source` for every factor.

### Qwen 3.5 9B baseline

- 1-3 tools normally, hard maximum 5;
- one model tool decision at a time;
- batches of at most 5 homogeneous items when supported;
- compact evidence and memory pages;
- frequent durable checkpoints;
- reasoning disabled unless explicitly enabled by the profile/call.

### Qwen 35B extended

- the same tools, state machine, approvals and artifact contracts;
- a larger coherent shortlist and evidence/memory pages within observed KV;
- approximately 35k useful input only when backend capacity supports it;
- independent read calls may run in parallel after one validated model decision;
- reasoning remains an independent explicit opt-in.

Unknown identity/capacity receives the restrictive 9B-compatible preset.

## Typed memory and versions

Memory is stored state, not a prompt dump and not evidence. A common projection
adapts existing stores into:

- workflow checkpoint and blockers;
- model/user decisions and revision references;
- evidence locators/hashes;
- compact conversation continuity;
- accepted project-scoped advisory facts.

The ContextGovernor selects views for a turn. Full objects remain addressable by
ID/cursor. Memory cannot become evidence or choose a professional result.

Workbook production creates immutable revisions. A correction creates version
2 linked to version 1; it never overwrites the prior artifact. Each revision
records source scope, profile revision, model identity/preset, tool calls,
decision checkpoint, missing/blockers and artifact hash.

## Private PR intake

Private PRs are sources of reviewed changes, not merge units. Version churn,
stale docs and unrelated files are never copied. Each accepted behavior is
reimplemented or cherry-picked as a focused commit on the public release base.

### Adapt into this update

- PR5: verify served embedder identity rather than vector dimension alone;
- PR7: required OCR fails closed and never indexes placeholder evidence;
- PR9: dense retrieval requires a valid offline index attestation;
- PR10: loopback model/Qdrant clients ignore desktop/VPN proxy variables;
- PR12: per-file ingestion ownership and real provenance;
- PR14: resolve Windows state paths before declaring data absent;
- PR15: stable unique hierarchy-node identity;
- PR16: `/api/search` returns available native-RRF evidence and reports optional
  reranker degradation without allowing reranker to erase evidence;
- PR17: page/sheet/row/bbox provenance reaches the consumer;
- PR18: a parse that fails before mutation does not revoke a valid attestation.

Dependencies between these changes are explicit: PR5/9/15/18 form one index
trust slice; PR7/12/17 form one ingestion/provenance slice. They receive narrow
tests and commits, not a single bulk merge.

### Separate releases

- PR6 changes the bundled native Qdrant and therefore requires a full installer
  release and exact Windows storage acceptance;
- PR8 and PR11 introduce a separate extension subsystem/package and are outside
  this update.

### Do not merge

- private PR13 modifies protected smeta-core behavior. Its immutable-revision
  requirement is implemented in the common artifact layer instead; its core
  changes are not copied without a separate owner instruction and benchmark.

## Documentation and architecture guard

`AGENTS.md` and `docs/CURRENT_ARCHITECTURE.md` must state this architecture as
active. The older estimator bridge documents remain historical and carry an
explicit superseded banner; they are not implementation instructions.

`make architecture-gate` must fail when:

- a parallel `estimate_*` workbook family appears;
- natural-language regex forces a workbook call;
- a new inference path bypasses ContextGovernor;
- a profile update auto-activates or rebinds existing chats;
- 9B and 35B expose different professional workflows;
- a synthetic fixture is presented as live model quality evidence.

## Acceptance

Unit/contract tests prove schemas, scope, budgets, memory projection, immutable
revisions, provider parity and rollback. They do not claim model quality.

Live acceptance uses the real ordinary-chat path:

1. attach a representative large source document;
2. run common RAG and tool selection on local Qwen 3.5 9B;
3. download a complete, readable workbook artifact;
4. request a correction and download version 2;
5. verify both revisions, provenance, missing/blockers and elapsed time;
6. repeat the same workflow on configured 35B without changing its semantics.

A run that spends minutes repeatedly failing to close one row is a failed
acceptance, regardless of unit-test count. The release also requires
`make verify`, `make test`, architecture gate, patch apply/skip/rollback and an
exact GitHub manifest bound to the verified commit.

## Release boundary and rollback

`0.29.0` is a SemVer architecture release but may use the lightweight GitHub
patch channel when classification proves there is no dependency, installer,
native runtime or destructive migration change. PR6 cannot enter that package.

Rollback disables the new registry/governor route and restores the `v0.28.2`
profile/runtime path while preserving append-only artifact revisions,
checkpoints and traces. No user document, index or setting is removed.

## Executable implementation plans

Execute these plans in order; each produces an independently reviewable and
testable checkpoint:

1. [Canonical Agent Foundation](../plans/2026-08-26-canonical-agent-foundation-implementation.md)
   — architecture gate, Registry, Broker, Executor and ordinary-chat tool loop.
2. [Context Governor, Memory and Model Presets](../plans/2026-08-26-context-governor-memory-presets-implementation.md)
   — observed capacity, 9B/35B presets, typed memory and one inference packer.
3. [Canonical Workbook Tools and Versioned Artifacts](../plans/2026-08-26-canonical-workbook-artifacts-implementation.md)
   — PR13 contracts, checkpoints, immutable XLSX revisions and live acceptance.
4. [Private Trust Fixes Adaptation](../plans/2026-08-26-private-trust-fixes-adaptation-implementation.md)
   — focused PR5/7/9/10/12/14–18 behavior without bulk merging private branches.
5. [Canonical Update, Rollback and Release](../plans/2026-08-26-canonical-update-rollback-release-implementation.md)
   — route rollback, exact manifest, apply/skip/rollback and release evidence.
