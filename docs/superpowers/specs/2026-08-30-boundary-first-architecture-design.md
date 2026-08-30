# Boundary-First Architecture Design

**Status:** owner-approved design
**Date:** 2026-08-30
**Base:** `e56e8c5b`

## Goal

Make the physical architecture of LES match its product architecture without changing the
product's model-owned decisions, RAG semantics, user data or professional workflows.

The product core is a local assistant for GIP/RP: a model works with explicitly available
evidence, memory and tools. RAG is a truth-delivery layer. Mail, estimates, document generation
and professional checks are connected workflows, not competing application cores.

## Current diagnosis

The repository is not primarily suffering from missing functionality. It is suffering from
unclear ownership and unrestricted dependencies:

- one composition root registers nearly every workflow;
- routers import other routers and the application root;
- services import routers;
- infrastructure under `backend/` imports application services under `proxy/`;
- Sovushka imports internal application modules instead of using stable API contracts;
- dozens of modules connect directly to shared SQLite state without an explicit owner;
- startup requires Qdrant even when the selected conversation mode needs no document RAG;
- old agent/chat implementations remain beside the current universal agent;
- large hub files cannot be split safely while these dependencies remain implicit.

Moving files into new folders would not correct these problems. Rewriting LES would put proven
RAG, updater and professional behavior at unnecessary risk. The migration therefore establishes
boundaries before decomposition.

## Target boundaries

LES has seven product subsystems:

1. **Agent Core** — conversation, model invocation, tool loop and profile contract.
2. **Evidence** — indexing, retrieval, exact readers, evidence packet and trace.
3. **Documents** — datasets, attachments, parsing, catalogue and source identity.
4. **Professional Workflows** — mail, estimates, documents and checks connected to Agent Core.
5. **Project State** — user memory, project memory and durable project metadata.
6. **Runtime** — provider connections, configuration, updater, security and process lifecycle.
7. **Sovushka** — the user interface over public API contracts.

The dependency direction is:

```text
Sovushka / HTTP routers
          |
          v
application use cases and Agent Core
          |
          v
explicit ports and domain contracts
          |
          v
Evidence / Documents / Project State / Runtime adapters

Professional Workflows -> Agent Core ports + their own adapters
```

Composition may depend on every subsystem in order to wire implementations. Subsystems do not
depend on the composition root.

## Dependency rules

The architecture gate will enforce these rules on tracked production modules:

- `proxy/services/**` must not import `proxy/routers/**` or `proxy.app`;
- `proxy/routers/**` must not import another router or `proxy.app`;
- `backend/**` must not import `proxy/services/**` or `proxy/routers/**`;
- `sovushka/**` must not import `proxy/**` or `backend/**`; it uses HTTP/state/UI contracts;
- professional workflows may use Agent Core contracts, evidence ports and exact tools, but do not
  become dependencies of the generic chat path;
- infrastructure adapters implement inward-facing ports and never select a professional answer;
- new exceptions require an explicit allowlist entry with owner, reason and removal condition.

The first gate records current violations as a finite baseline and rejects new violations. Each
migration removes named baseline entries. A broad permanent allowlist is not acceptable.

## Product behavior invariants

The restructuring must preserve these contracts:

- an explicit dataset/attachment scope remains the only document evidence scope;
- `none` reaches the configured model without document RAG;
- `selected` and explicit `all` use the common native `dense + bm25_sparse` RRF contract;
- the model receives evidence and chooses what to search, read and conclude;
- code executes tools, preserves provenance and performs exact calculations; it does not replace
  the model's professional decision;
- empty retrieval is returned to the model, not converted into a code-authored professional answer;
- no answer cache replaces grounded retrieval and generation;
- user documents, Qdrant collections, SQLite state, memories, settings and secrets are preserved;
- `proxy/smeta_core/**` is not changed in this program without a new explicit owner instruction and
  the protected benchmark;
- Mail remains a preserved product workflow even while its UI and contracts continue to evolve.

## Staged migration

### Phase 0 — patch bridge

Before runtime files are removed, the Windows lightweight updater gains transactional deletion.
This is a runtime patch, not an NSIS/full-installer release.

For every deletion entry the patch contains the path and accepted historical SHA-256 identities.
The updater behaves as follows:

- known installed bytes: copy to rollback storage, then delete;
- already absent: accept as an idempotent completed deletion;
- unknown installed bytes: abort before mutation and report the conflicting path;
- failed apply, restart, version check or health check: restore deleted and replaced files and the
  previous deploy stamp;
- successful apply: retain the bounded recovery snapshot under the existing update policy.

The patch launcher already stages target updater code outside the runtime before stopping LES. The
bridge uses this mechanism so an installed `0.30.0` can receive the deletion-capable updater without
first downloading intermediate versions.

### Phase 1 — liveness classification

Classify the 26 service modules currently reachable only from tests or tools:

- delete the proven old Agent v1/chat/profile implementations;
- keep Mail as a product workflow;
- keep CLI/MCP capabilities that have a real entrypoint, but mark them as tool-only and exclude them
  from the Windows runtime unless explicitly shipped;
- resolve ambiguous modules individually from imports, entrypoints and behavior tests;
- correct module maps and MCP/runtime documentation to match what is actually shipped.

Deletion is evidence-based. A module is not removed merely because its name looks old.

### Phase 2 — enforce boundaries

Add the architecture gate with the finite violation baseline, then remove violations in small,
reviewable groups:

1. services importing routers;
2. routers importing routers or `proxy.app`;
3. backend importing proxy services;
4. Sovushka importing backend/proxy internals.

Shared request/response types and ports move to focused neutral modules only when a concrete
violation requires them. No speculative framework or dependency-injection library is introduced.

### Phase 3 — split composition

Replace the single hard-wired application assembly with explicit composition functions:

- Core API and Agent Core;
- Evidence/Documents;
- Project State;
- each professional workflow;
- Runtime/operations.

The default product still exposes the approved workflows. The split makes their registration and
dependencies visible; it does not introduce a plugin marketplace or user-facing scenario system.

### Phase 4 — Qdrant-independent ordinary AI

Process startup no longer fails solely because Qdrant is unavailable. Core chat, configuration,
provider diagnostics and other non-document capabilities start normally. Evidence capabilities
report an explicit unavailable/degraded state. A turn with document scope fails visibly at the
evidence boundary; a turn with scope `none` reaches the model.

Qdrant availability remains mandatory for indexing and document-grounded turns. No silent vector
store fallback or automatic scope change is added.

### Phase 5 — data ownership

Inventory shared SQLite schemas and assign each table group one owning subsystem. Consumers use
owner APIs/repositories instead of opening another subsystem's tables directly. Migration proceeds
schema group by schema group; there is no database rewrite or bulk user-data migration in this
program.

### Phase 6 — decompose hubs

Only after dependency and data ownership gates are effective may the largest hubs be split:

- `proxy/routers/chat.py` by request transport and use case;
- `proxy/routers/datasets.py` by catalogue, intake and administration;
- `backend/qdrant_adapter.py` by infrastructure responsibility.

`proxy/smeta_core/document_workflow.py` is explicitly excluded. Its size alone is not authorization
to change a stable protected workflow.

## Release and patch contract

Every phase produces a working release candidate and an independently reversible commit series.
Pure Python, Sovushka, prompt and supported configuration changes ship as lightweight GitHub
patches. A full installer is required only when a change genuinely alters:

- Tauri/`les-desktop.exe` behavior;
- NSIS or bundled bootstrap;
- the Python dependency graph or `uv.lock` beyond synchronized version metadata;
- bundled portable Python or other immutable installer payload.

The boundary program must not introduce such a change merely for refactoring convenience.

The update feed accepts every trusted installed state on the bounded `0.30.x` ancestry. A user may
update directly from `0.30.0` to the newest compatible patch; the client does not download `.1`,
`.2` and later patches sequentially.

## Testing and acceptance

Every implementation phase includes focused regression tests, documentation, version/build update
and release-ledger entry. Required gates are:

- focused tests for the changed contract;
- `make verify`;
- `make test` for runtime logic;
- updater tests for package validation, skipped-version application, unknown local bytes,
  transactional deletion, forced failure and rollback;
- Windows runtime staging smoke;
- installed-copy smoke proving exact `/api/version`, API/UI readiness and preserved state.

The complete first boundary program is accepted when:

1. an installed `0.30.0` updates directly through the button to the current patch release;
2. bridge apply and forced rollback both preserve runtime and user state;
3. old Agent v1 is gone, CLI/MCP surfaces are truthfully classified, and Mail remains;
4. the architecture gate prevents new reverse dependencies and its baseline is monotonically
   shrinking;
5. ordinary scope-`none` AI starts without Qdrant;
6. RAG, evidence trace and professional workflow behavior remain unchanged;
7. protected smeta files remain unchanged;
8. canonical code/module/release documentation matches the shipped runtime.

Live publication is not part of implementation completion. Publishing any patch still requires the
owner's explicit instruction and the public release gates.

## Plan decomposition

This design is a migration program, not one large implementation diff. It will be implemented with
separate plans and review gates:

1. transactional-deletion bridge patch;
2. liveness classification and old Agent v1 removal;
3. dependency-direction gate and cycle reduction;
4. composition-root split;
5. Qdrant-independent core startup;
6. SQLite ownership migration;
7. hub decomposition.

The next implementation plan covers only item 1. Later plans may refine file-level details but may
not weaken the boundaries or product invariants in this design without owner approval.

## Non-goals

- rewriting LES or changing its product identity;
- adding a scenario engine, mandatory critic model or code-authored professional decisions;
- changing retrieval, chunking, embeddings or Qdrant collection schema;
- reindexing user datasets;
- changing estimate decisions or protected smeta behavior;
- redesigning Sovushka;
- deleting ambiguous code without liveness evidence;
- publishing or deploying a release during architecture implementation.

## Rollback

Code migrations roll back by their bounded commits. Patch application also maintains a verified
file-level recovery snapshot and deploy stamp. No phase deletes or migrates user data. If a phase
cannot preserve functional behavior and a clean rollback, it stops before the next phase begins.
