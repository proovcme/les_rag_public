# Universal Model Connections Design

**Status:** owner-approved design; not implemented
**Release line:** `0.29.0`
**Base architecture:** [Canonical Tool, Context, Memory and Artifact Update Design](2026-08-26-canonical-tool-context-memory-update-design.md)

## Purpose

LES must connect to local and remote model servers through one professional,
provider-neutral configuration system. Ordinary chat must not contain separate
runtime branches for FreeToken, Ollama, Lemonade, MLX, LM Studio, llama.cpp or
an arbitrary OpenAI-compatible endpoint.

A connection describes how LES reaches a model. A provider or engine name is
only a template and a display label. Runtime behavior is selected from verified
capabilities, not from that label.

This design preserves the existing notebook memory, ContextGovernor, model
presets, Tool Registry, Capability Broker and Trusted Executor. It does not
introduce a new model loop, a new memory system or an estimator workflow.

It also preserves a deployment boundary needed by the future headless mode:
the browser and Sovushka never become model clients. They talk to an LES node;
that node owns files, datasets, retrieval, notebook memory, tools and model
connections. The UI/API entrypoint may later be hosted separately from that
execution node without changing the model-connection contract.

## Confirmed compatibility boundary

The common inference baseline is the OpenAI-compatible Chat Completions API:

- `POST /v1/chat/completions` for ordinary generation and canonical client-owned
  tool calling;
- `GET /v1/models` when the server exposes model discovery;
- `POST /v1/embeddings` when a connection is assigned the embeddings role.

Responses API, structured output, token counting, reranking, model lifecycle
and server-owned tools are optional capabilities. LES never assumes that two
servers implement an optional endpoint or semantic detail identically merely
because both call themselves OpenAI-compatible.

The design is grounded in the official interfaces available on 2026-08-27:

- FreeToken exposes `/v1/models`, `/v1/chat/completions`, `/v1/responses`,
  `/v1/messages` and `/v1/messages/count_tokens` on its local server;
- Ollama documents OpenAI-compatible chat, embeddings and a stateless subset of
  Responses, while native model management remains an Ollama extension;
- Lemonade documents OpenAI-compatible chat, embeddings, Responses and other
  modalities, while Omni is an engine-specific extension;
- LM Studio documents OpenAI-compatible chat, Responses and embeddings;
- llama.cpp documents OpenAI-compatible chat, Responses and embeddings, with
  tool behavior depending on the loaded model template and server options;
- the current LES MLX host exposes OpenAI-compatible models, chat and embeddings,
  while memory, unload, model switching and rerank remain native extensions.

These facts justify one transport contract with capability discovery. They do
not justify one hard-coded feature set.

Primary references:

- [OpenAI Chat API](https://developers.openai.com/api/reference/resources/chat)
- [FreeToken quickstart](https://github.com/FlashML-org/FreeToken/blob/main/docs/quickstart.md)
- [Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility)
- [Lemonade OpenAI-compatible APIs](https://lemonade-server.ai/docs/api/openai/)
- [LM Studio developer documentation](https://lmstudio.ai/docs/developer)
- [llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- [current LES MLX host](../../../mlx_host.py)

## Scope and non-goals

This change includes:

- a global registry of named model connections;
- safe secret references rather than secret values in application data;
- separate role bindings for answer generation, embeddings and local fallback;
- capability detection with recorded evidence and freshness;
- one OpenAI-compatible inference transport;
- optional, isolated engine-management extensions;
- migration from existing environment settings without breaking rollback;
- an administrator UI for creating, testing, assigning and disabling
  connections;
- network, redirect and secret-handling protections.

This change does not:

- modify `proxy/smeta_core/**` or make the smeta core participate in chat;
- replace or remove notebook memory;
- install, launch, update or delete model engines or model files;
- activate a new chat profile, tool profile or professional workflow;
- copy secrets into SQLite, API responses, logs or diagnostics;
- silently switch to any available provider after a failure;
- claim model quality from mocked or synthetic inference;
- make server-owned autonomous tools part of the canonical LES tool loop;
- require Responses API for ordinary chat;
- implement the separate authenticated control-plane protocol needed to place
  Sovushka on a VPS and an LES execution node on another machine;
- let a browser or UI host call a model endpoint directly, even in a split
  deployment;
- publish or deploy a release.

## User model

Connections are global for one LES installation and administered by an
administrator. Ordinary users may see safe operational facts such as display
name, assigned role, locality, model, status and effective context. They never
receive a secret value or an unrestricted administrative endpoint.

Examples of named connections are `Local Qwen 9B`, `FreeToken 35B`,
`Office Ollama` and `OpenAI production`. These names have no runtime semantics.
Copying or renaming a connection cannot change transport behavior.

## Architecture

The request path becomes:

```text
chat/workflow request
  -> role binding
  -> immutable connection revision
  -> secret resolver
  -> capability snapshot
  -> ContextGovernor
  -> OpenAI-compatible transport
  -> existing model response/tool decision
```

### Deployment topology boundary

The logical request path is always:

```text
browser
  -> Sovushka / LES control-plane API
  -> one explicitly selected LES execution node
  -> files + datasets + retrieval + notebook memory + tools
  -> role-bound model connection
```

In the initial release the UI/API and execution node may remain in one LES
installation. A later headless deployment may put Sovushka and its authenticated
control-plane entrypoint on a VPS while the execution node runs on another
machine. That split must preserve these invariants:

- the execution node, not the VPS or browser, owns user files, indices,
  notebook memory, tool execution and model credentials;
- the VPS forwards typed LES requests to one explicitly selected node and does
  not reimplement retrieval, memory, tools or inference;
- the UI never receives a model secret and never connects directly to a model;
- node selection and failover are explicit bindings; connection loss fails
  closed and cannot scan for another node or model;
- attachment transfer is an explicit bounded operation with identity,
  integrity, size and retention metadata, never an implicit VPS copy;
- node authentication, authorization, transport encryption, replay protection,
  audit and reconnect semantics require their own approved design and tests.

`ModelConnectionRegistry` is local to the execution node. It describes how that
node reaches a model; it is not a registry of LES nodes and must not acquire
control-plane routing responsibilities.

Optional engine operations use a separate path:

```text
administrator action
  -> extension registry
  -> exact engine-management adapter
  -> bounded typed result
```

The ordinary inference transport cannot call an engine-management adapter.
Changing the selected connection does not change the tool allowlist, memory,
workflow or model-owned professional decision boundary.

### `ModelConnectionRegistry`

The registry stores append-only revisions. Editing a connection creates a new
revision; in-flight work keeps the revision it resolved at the start. Disabling
a connection prevents new resolution but does not rewrite history.

Each revision contains at least:

- stable `connection_id` and immutable `revision_id`;
- unique human-readable `display_name`;
- protocol, initially exactly `openai_compatible`;
- canonical `base_url` and model identifier;
- explicit locality: `loopback`, `private_network` or `remote`;
- requested context limit;
- optional `secret_ref`;
- enabled state and audit metadata.

The registry stores neither an API key nor provider-specific environment
contents. A template may prefill fields, but the saved result is an ordinary
connection revision.

### `SecretResolver`

The connection stores only a `secret_ref`. The resolver converts that reference
to an authorization value immediately before transport use. The value remains
in memory only for the request and is never returned by registry, settings,
diagnostic or audit APIs.

The first implementation supports references to the existing environment-backed
secrets so migration does not require exposing or moving them. The interface
must permit a later Windows credential-vault implementation without changing
connection records or the chat transport.

The UI reports only `configured`, `missing` or `not_required`. Replacing a
secret uses a masked write-only control and creates an audit event without the
value.

### `ConnectionResolver`

The resolver takes a role and returns one immutable
`ResolvedModelConnection`. The result contains the exact connection revision,
resolved model, verified locality, effective context, safe authorization handle
and capability snapshot identifier.

Resolution is fail-closed. A missing, disabled, stale-incompatible or unsafe
binding returns a typed configuration error before model inference. The
resolver never searches the registry for a convenient substitute.

### Role bindings

The registry maintains independent explicit bindings:

- `answer` — normal chat and workflow inference;
- `embeddings` — vector generation;
- `local_fallback` — the only connection eligible for declared inference
  fallback.

A connection may hold more than one role. Fallback occurs only when the calling
workflow permits it and an administrator assigned the fallback role. There is
no provider scan, hidden cloud-to-local switch or local-to-cloud switch.

Every response records the effective connection revision and whether fallback
was used, without recording credentials.

### `CapabilityProbe` and snapshots

Capability probing is an explicit administrator action and a bounded background
health operation. It is not an extra model call inside a user request.

A snapshot records each capability as `supported`, `unsupported` or `unknown`,
plus evidence source and observation time. Initial capability keys are:

- chat completions;
- streaming;
- client-owned tool calling;
- structured JSON and JSON Schema;
- Responses API and its supported subset;
- embeddings;
- model discovery;
- token counting;
- reranking.

Evidence sources are `probe`, `operator_declaration` or `template_default` in
descending trust order. Safety-critical behavior and canonical tool calling
cannot become supported from a template default alone. A stale snapshot remains
visible but cannot satisfy an active capability requirement until refreshed or
explicitly revalidated.

Probes use minimal bounded requests where necessary. They do not judge answer
quality and do not report a synthetic prompt as live acceptance evidence.

### `OpenAICompatibleTransport`

The common transport receives only `ResolvedModelConnection` and a governed
inference packet. It does not receive a provider enum and must not branch on
FreeToken, Ollama, Lemonade, MLX, LM Studio or llama.cpp names.

Ordinary chat uses Chat Completions. A workflow may use Responses only when its
contract explicitly requires it and the effective snapshot supports the needed
subset. Request and response variations are normalized through declared and
observed protocol capabilities, never a display-name check.

The existing canonical Tool Registry remains the only source of tool schemas.
The existing Broker shortlists tools, and the existing Executor performs calls.
The transport may return at most the model's next tool decision for that turn;
it does not recursively execute tools or ask another provider to decide.

### `EngineExtensionRegistry`

Engine-management behavior is deliberately outside inference. An extension is
selected by an explicit connection extension type configured by an
administrator, not inferred from a display name or URL.

Potential extensions include:

- FreeToken cache/KV information and Anthropic-compatible token counting;
- Ollama model listing, pull/load state and native context controls;
- MLX memory status, TTL, unload, switch-model, Metal status and rerank;
- Lemonade model lifecycle and Omni controls;
- llama.cpp server health and supported native controls.

An absent extension never prevents baseline inference. An extension cannot
alter role bindings, tool profiles or a governed inference packet as a side
effect. Destructive or external engine operations require the existing explicit
approval discipline.

Lemonade Omni or any similar server-owned tool system is disabled for canonical
LES workflows by default. Enabling such an extension is a separate future
design because hidden server-side tool chains would bypass Registry, Broker and
Executor evidence.

## Context, memory and tools

The requested context value belongs to the connection revision. The effective
value is computed by ContextGovernor from the LES model preset, workflow
restriction and verified backend capacity. The GUI shows requested value,
effective value and source.

Switching a connection does not clear or replace notebook memory. The existing
memory remains the durable user-facing memory; its typed projection remains
advisory input to ContextGovernor.

One model turn may produce at most one canonical tool call. Further calls occur
only as explicit subsequent turns after the previous typed result is recorded.
Neither connection resolution, capability probing nor fallback creates a model
decision chain.

## Security boundary

Connection creation and mutation require authenticated administrator access.
Before saving or probing, LES canonicalizes and validates the URL:

- URL user-info, fragments and embedded credentials are rejected;
- `loopback` may use HTTP only for loopback addresses;
- approved `private_network` endpoints may use HTTP only under an explicit local
  policy; remote endpoints require HTTPS;
- link-local, multicast, unspecified and cloud-metadata destinations are
  rejected;
- host resolution is checked before connection and again for every accepted
  address to resist DNS rebinding;
- redirects are disabled by default; any future redirect support must re-run
  the complete destination policy;
- probes and requests use bounded connect/read timeouts and response-size caps.

Locality is explicit verified configuration, not a guess from the provider
name. Privacy routing and fallback decisions use verified locality.

Logs, exceptions, traces and diagnostic exports redact authorization headers,
secret references where necessary, URL query credentials and returned server
messages that echo credentials. A connection test returns a typed safe summary,
not a raw upstream body.

## GUI contract

The administrator sees one `Model connections` registry with:

- connection name, address, model, locality and enabled state;
- assigned roles;
- health and capability freshness;
- requested and effective context with source;
- secret state without its value;
- create from blank or template, copy, test, edit, disable and assign-role
  actions;
- explicit warnings and confirmation for remote, insecure-private or dangerous
  management changes;
- whether a change is immediate or requires service restart.

Ordinary users see only the effective connection name, locality, model, health
and fallback fact relevant to their request. Every active runtime factor is
registered in the existing settings/diagnostics contract; an unregistered
factor remains `UNREGISTERED_RUNTIME_FACTOR`.

## Migration and rollout

Existing environment settings remain valid during migration. LES creates or
resolves deterministic legacy-derived connection revisions that reference the
existing secret variables without copying their values. The initial role
bindings reproduce the previously effective provider and model.

Migration does not delete or rewrite environment values and does not activate a
different connection. Rollback can therefore return to the legacy resolver.

Rollout follows the existing three modes:

- `legacy`: the existing provider-specific resolver serves requests;
- `shadow`: the existing resolver still serves requests while the new resolver
  compares safe configuration and capability facts; it sends no second model
  request and changes no answer;
- `active`: the registry resolver and common transport serve requests.

Promotion to `active` is an explicit administrator action after hermetic gates
and paired live non-regression on the actual configured 9B and 35B connections.
A stale or missing acceptance receipt cannot silently promote the mode.

FreeToken, Ollama, Lemonade, MLX, LM Studio and llama.cpp appear as optional
creation templates. No template automatically installs an engine, chooses a
role, activates a profile or bypasses the capability probe.

## Errors and observability

User-visible failures are typed and actionable:

- connection missing or disabled;
- secret missing;
- endpoint rejected by network policy;
- capability missing or stale;
- model unavailable;
- upstream timeout or protocol mismatch;
- explicit fallback unavailable or failed.

Operational events record role, connection/revision, capability snapshot,
locality, timing, fallback decision and redacted upstream status. They do not
record prompts, attachment contents or secrets merely to diagnose connectivity.

## Verification contract

Hermetic tests must cover:

- immutable registry revisions and atomic role bindings;
- migration parity for every supported legacy environment configuration;
- absence of provider-name branches in the ordinary chat transport;
- FreeToken-, Ollama-, Lemonade-, MLX-, LM Studio- and llama.cpp-shaped fake
  servers with deliberately different optional capabilities;
- capability evidence, expiry and fail-closed requirements;
- secret non-persistence, redaction and write-only UI behavior;
- URL canonicalization, SSRF, DNS rebinding and redirect rejection;
- explicit fallback only, with provenance of the effective connection;
- unchanged ContextGovernor, notebook-memory projection, tool shortlist and
  one-call-per-turn contracts;
- GUI visibility of requested/effective/source/restart facts;
- rollback from `active` to the legacy resolver.

Live acceptance uses the real installed engines and exact model revisions. It
checks connectivity, streaming, tools where supported, context enforcement and
fallback provenance. It does not use a mocked response or the historical
five-row smeta benchmark as evidence of model quality.

## Implementation order and interaction with workbook artifacts

This connection foundation is implemented before provider projections in the
canonical workbook-artifact plan. Artifact revision storage and durable
checkpoint work are independent, but workbook provider projection must consume
`ResolvedModelConnection` rather than add new provider branches.

The implementation plan must proceed in bounded slices:

1. immutable connection and role-binding domain contracts;
2. secret references, URL policy and capability snapshots;
3. common transport and legacy migration in `shadow` mode;
4. administrator API and GUI;
5. explicit fallback and optional engine extensions;
6. paired live acceptance and explicit `active` promotion;
7. resume workbook provider projections over the common connection contract.

No slice may modify `proxy/smeta_core/**`.

The separate VPS-to-headless-node control plane follows this foundation as its
own design and implementation plan. This release must not fake that topology by
exposing model URLs to Sovushka, copying notebook memory to the UI host or
tunnelling arbitrary filesystem operations through the model-connection API.

## Acceptance

The design is complete when an administrator can define multiple named
connections, verify their real capabilities, assign answer/embeddings/fallback
roles and see the effective safe configuration; ordinary chat then reaches the
assigned connection through one provider-neutral transport without changing
memory, tools or workflow semantics.

Renaming a connection must not change behavior. Disabling an assigned
connection must fail closed. A failing answer connection may use only the
explicitly assigned fallback. A server-specific management feature must remain
optional and unable to bypass the canonical tool/evidence path.
