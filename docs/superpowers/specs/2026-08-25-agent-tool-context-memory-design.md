# Agent Tool, Context and Memory Foundation Design

**Status:** proposed design, owner review pending
**Targets:** planned `0.29.0` foundation and `0.29.1` actions

## Goal and baseline

Build one model-portable agent foundation for internal LES tools and MCP without
turning either the model or memory into an unbounded prompt. Every primary LES
workflow must remain executable on local Qwen 3.5 9B. Qwen 35B receives a richer
preset because live use showed stable dialogue continuity to roughly 35k input,
but it uses the same workflow, evidence and approval contracts.

The architecture preserves the LES invariant: the model connects evidence and
makes professional choices; typed code reads, validates, calculates and records
provenance.

## Release boundary

`0.28.3` first exposes four narrowly scoped estimator LSR/VOR contracts through
the current harness. They are a compatibility bridge: `0.29.0` migrates the same
stable names and semantics into the canonical registry rather than creating a
second tool family. The bridge does not implement a competing general context or
memory manager.

`0.29.0` delivers the foundation and migrates read-only tools:

- canonical Tool Registry and provider projections;
- Capability Broker and Trusted Executor;
- `ContextGovernor`, model presets and context observability;
- a common memory projection over existing session, dataset and Memory Core
  stores;
- migration of current read-only tool-harness/MCP capabilities without changing
  their evidence semantics.

`0.29.1` enables compute and action classes:

- typed calculation tools;
- automatic creation of drafts and append-only revisions;
- explicit approval for commit/finalization, external side effects and
  destructive operations;
- idempotency keys, action receipts and internal/MCP parity tests.

The old specialized smeta chat orchestrator is not migrated or restored.
Protected `proxy/smeta_core/**` remains a compatibility/library boundary.
Reusable typed readers, calculators and provenance contracts may be exposed
through new adapters only when this does not change model-owned decisions.

## Canonical Tool Registry

Every capability is defined once as a provider-neutral `ToolContract`. Provider
adapters project that contract to Ollama/Qwen, FreeToken/OpenAI-compatible,
OpenAI, MCP and LES API/UI formats.

Minimum contract fields:

- stable ASCII `snake_case` name, semantic version, title and concise purpose;
- input and structured-output JSON Schemas;
- effect class: `read`, `compute`, `draft`, `commit`, `external`, `destructive`;
- authentication and approval policy;
- evidence/provenance behavior and `decision_required_from_model`;
- idempotency requirements and retry safety;
- output page/budget policy and cursor schema;
- timeout, concurrency class and availability probe;
- owner/module and deprecation aliases.

Names such as `rag_search_sources` and `fgis_price_lookup` are portable across
providers. Dotted provider-specific names are not canonical. Provider hints and
MCP annotations are projections only; the server does not trust them for
authorization or approval.

Tool results extend the existing typed envelope rather than inventing a second
truth format:

```text
data + sources + missing + warnings + action_receipt + trace + next_cursor
```

Truncation is never silent. A bounded result declares omitted counts and a stable
cursor/reference so the model can request the next relevant page.

## Capability Broker

The broker computes the legal, currently available tool subset from:

- immutable chat-profile allowlist;
- model preset and current workflow state;
- authenticated actor and project/dataset scope;
- provider/runtime availability;
- effect and approval policy;
- current context and call budgets.

It may rank or shorten a tool menu, but it may not choose a professional answer,
norm, coefficient, scope or contractual value. The shortlist and rejection
reason are written to trace. Unknown tools, stale versions and tools outside the
profile allowlist fail closed before model invocation.

## Trusted Executor

All internal and MCP calls enter the same executor. It validates schema, scope,
authorization, approval, idempotency and runtime availability; enforces timeout
and concurrency policy; executes the typed implementation; validates the result
envelope; and writes an audit trace.

Effect policy:

| Class | Default behavior |
|---|---|
| `read` | execute when allowed by profile and scope |
| `compute` | execute automatically; inputs, formula/version and sources are recorded |
| `draft` | create automatically as append-only draft/revision; never present it as final |
| `commit` | require explicit user confirmation bound to the exact proposed revision |
| `external` | require explicit confirmation before the side effect |
| `destructive` | require explicit confirmation and a recoverable/verified target |

Approval is a durable state transition, not a phrase hidden inside the prompt.
Retries of write-capable tools require an idempotency key and return the prior
receipt when the same operation already succeeded.

## Workflow state

Primary workflows use explicit checkpoints rather than relying on raw chat
history. A checkpoint stores workflow/contract version, phase, completed calls
and receipts, unresolved blockers, decision records, evidence references and a
compact typed working state. Resume validates identity before continuing.

The 9B and 35B presets execute the same state machine. A larger model may receive
more evidence or parallelize independent reads; it does not bypass checkpoints,
approval or provenance.

## ContextGovernor

`ContextGovernor` owns the complete inference-packet budget. Individual services
must not independently slice JSON with unrelated `max_chars` values.

Packing order:

1. stable system/profile prefix and exact tool schemas for the current shortlist;
2. current user request and typed workflow checkpoint;
3. compact project/session working memory;
4. selected evidence excerpts and source maps;
5. the latest relevant tool exchange;
6. bounded dialogue turns only when they add information not already represented.

Every packet reserves space for generation and a safety margin before sending.
Preflight estimates provider tokens, rejects impossible packets and records
requested/packed/omitted tokens by layer. Evidence and memory retain references
to full stored objects, allowing explicit reread instead of blind truncation.
Stable prefixes should remain byte-stable where the provider can reuse prompt/KV
cache.

## Model presets

Presets are data/config selected from the effective provider/model identity.
Unknown models receive the restrictive 9B-compatible preset.

### Qwen 3.5 9B — slice-oriented baseline

- every primary workflow must pass here;
- normally expose 1-3 highly relevant tools, hard maximum 5 per turn;
- one model tool decision at a time; no model-request parallelism;
- batch up to 5 homogeneous items when the tool contract supports it;
- compact schemas, working memory and evidence pages;
- frequent deterministic checkpoints and bounded retries;
- preserve output and safety reserve before adding more evidence.

### Qwen 35B — long-context preset

- target model identity currently includes `Qwen3.6-35B-A3B-NVFP4` through
  FreeToken, without hard-coding business behavior to that transport;
- preserve approximately 35k useful input when the physical runtime window is
  configured above it, leaving explicit generation and safety reserves;
- allow a broader coherent shortlist and richer working memory/evidence;
- allow parallel execution only for independent read calls after one validated
  model decision;
- keep the same action approval, checkpoint, evidence and result contracts as
  9B.

Empirical capacities are release-tested settings, not promises inferred from a
model name. If provider-reported capacity is smaller, the governor reduces the
packet before invocation and reports the effective limit.

## Memory boundary

Memory is canonical stored state, not a prompt dump and not evidence. The common
projection exposes five typed views:

- workflow memory: checkpoint, progress, blockers and action receipts;
- decision memory: user/model decisions with revision and rationale references;
- evidence memory: locators and hashes pointing to evidence stored elsewhere;
- conversation memory: compact continuity and unresolved questions;
- project memory: accepted project-scoped advisory facts and preferences.

Existing stores remain authoritative in `0.29.0`: session/context memory,
dataset notebooks and Memory Core are adapted behind the projection instead of
being copied into a new database. Memory Core trust rules remain unchanged:
project-scoped recall, default off, advisory only, never evidence, and no norm or
professional decision selection.

The context governor decides which memory views enter a turn. Full history,
tool results and evidence bodies remain addressable by IDs/cursors and are read
only when relevant. Users must be able to inspect and exclude memory from a
workflow; deletion follows each underlying store's existing safety rules.

## Migration

1. Describe existing read-only `tool_harness_service` tools as canonical
   contracts without changing implementations or result semantics.
2. Project the same registry into chat profiles, API/UI and MCP; keep temporary
   aliases for existing public names and trace their use.
3. Route both internal and MCP execution through Trusted Executor.
4. Introduce context budgets and presets in shadow/trace mode, compare their
   proposed packet with the current packet, then activate per model profile.
5. Adapt existing memory sources into the common projection; do not bulk-copy
   chat history or Memory Core entries.
6. Enable read-only foundation for all four current profiles.
7. Add compute/draft tools, then approval-gated actions in `0.29.1`.

## Verification and observability

Every tool turn records profile revision, model preset, shortlist, schema
version, calls/rejections, latency, result size, cursors, token budget by layer,
checkpoint identity and approval/action receipts. Secrets and raw credentials
are never traced.

Required gates include:

- registry projection parity across internal API and MCP;
- schema/property tests for every adapter and result envelope;
- executor authorization, approval, idempotency and timeout tests;
- context packing tests proving reserves, stable priority order, cursor-based
  overflow and no broken JSON truncation;
- memory tests proving navigation/advisory content never becomes evidence;
- the same primary workflow fixtures on local Qwen 3.5 9B and Qwen 35B, with 9B
  as the mandatory baseline;
- long-session/resume tests around the 35k useful-input target for the configured
  35B runtime;
- regression tests proving ordinary `estimator` remains the common native-RRF
  profile and does not enter the legacy smeta orchestrator;
- `make verify`, `make test` and the applicable live model/release gates.

## Non-goals

- No arbitrary shell or desktop-control tool in the default registry.
- No autonomous commit, publication, message sending or destructive action.
- No memory-based evidence shortcut or automatic professional decision.
- No provider-specific duplicate business implementations.
- No claim that a 35B-only workflow is a primary LES workflow.

## Rollback

Adapters and model presets are activated behind explicit configuration/versioned
contracts. Rollback disables the new broker/governor path and returns profiles to
the existing read-only harness while preserving append-only traces and workflow
state. Action tools remain separately disabled unless `0.29.1` is active.
