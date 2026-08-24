# Chat Profile Studio Design

## Goal

Replace the implicit chat-mode maze with four explicit, versioned profiles:
`search`, `agent`, `estimator`, and `engineer`. Each profile chooses an immutable
prompt revision, an immutable Markdown skill revision, an allowlist of registered
tools, and model/RAG policy. Every chat binds to one immutable profile snapshot.

## Product contract

- The ordinary chat has no Auto mode. Agent is the default.
- The visible modes are Поиск, Агент, Сметчик, Инженер.
- Factory Base revisions cannot be changed or deleted.
- User revisions are edited as drafts. Saving creates a new immutable revision.
- A user can create from scratch, copy, rename, select, activate, or delete a
  user revision. Referenced revisions are tombstoned, not physically erased.
- Prompt and skill are selected inside a profile draft. Neither has a global
  active state; the active profile revision owns the selection.
- Every new chat snapshots the active profile revision. Existing chats continue
  with their snapshot until the operator explicitly applies another revision.
- Tools are implemented once in the typed tool registry. Profiles only select
  registered tools. Side-effecting tools require explicit approval.
- Existing legacy API mode aliases remain accepted during migration, but the UI
  emits only the four canonical profile ids.

## Storage

Use the persistent MetaDB returned by `rag_meta_db_path()`; on Windows it lives
under `%LOCALAPPDATA%\\LES\\data` through the existing state junction. Do not
store user revisions in replaceable `config/prompts`.

The profile store owns four tables:

- `les_prompt_revisions`: immutable prompt text and tombstone metadata.
- `les_skill_revisions`: immutable Markdown skill text and tombstone metadata.
- `les_profile_revisions`: immutable profile snapshot referencing prompt and
  skill revisions and embedding their exact text, hashes, tools, and policies.
- `les_active_profiles`: one active profile revision per canonical mode.
- `les_chat_profile_bindings`: one immutable effective snapshot per chat session.

Factory rows are seeded idempotently from current canonical prompt/skill
contracts. IDs are stable strings so upgrades can reconcile missing Base rows
without replacing user state.

## Runtime resolution

`ChatRequest` accepts `mode`, optional `profile_revision_id`, and an explicit
`apply_profile_revision` flag. Before any professional routing, the chat router
resolves or binds an effective snapshot. The snapshot is added to route/history
trace and passed to the shared RAG application.

Canonical behavior:

- `search`: grounded iterative research with read-only tools.
- `agent`: general grounded agent with the full currently registered read-only
  harness. Future write tools remain approval-gated.
- `estimator`: ordinary native-RRF RAG with estimator prompt/skill/tools and the
  large model; legacy calculation/LSR code is not entered by profile routing.
- `engineer`: grounded engineering and norm-control review.

Commands remain explicit control-plane operations. Keyword handlers such as
XLSX-to-VOR and automatic estimate detection do not pre-empt a profile; the
ordinary chat path no longer contains those hidden interceptors.

The evidence application uses the resolved profile prompt instead of always
building `rag`. The tool loop is controlled by the profile tool allowlist, not a
global environment flag. Search and Agent therefore have observable, testable
differences.

## API

Add `/api/profiles` endpoints for:

- registry snapshot (modes, revisions, active ids, prompt/skill libraries, tool
  registry);
- create/copy profile draft and publish immutable revision;
- create/copy prompt or skill revision;
- activate a profile revision;
- tombstone a user revision;
- inspect and explicitly replace a chat binding.

Base deletion and activation of a mismatched mode return conflict responses.
Unknown tool names or missing prompt/skill revisions are rejected before write.

## UI

The Configuration screen gains one lazy `Профили` tab. The page is a single
vertical working surface:

1. four profile buttons;
2. version selector, Base/Активная/Черновик states, activate/copy/delete actions;
3. selected prompt card with `Выбрать`, `Редактировать`, `Создать копию`;
4. selected skill card with the same actions;
5. tool allowlist and compact model/RAG policy;
6. Markdown editing through bundled NiceGUI `ui.codemirror` and a
   `ui.markdown` preview;
7. one primary `Сохранить версию` action.

Use existing Sovushka UI-kit panels, headings, buttons, selects, status badges,
tokens, feedback states, Russian labels, visible focus, and responsive stacking.
No new dependency or page-local color system is introduced.

The ordinary chat defaults to Agent and sends the canonical profile id. Its
mode buttons show the four profiles; clicking the selected mode does not fall
back to Auto.

## Compatibility and migration

The old `/api/prompts` API remains read-compatible for one release but delegates
effective factory values to the new store where possible. Existing
`prompt_overrides.json` values are imported once as user prompt revisions and
are never used as the durable source of truth afterward.

Legacy aliases map as follows: `rag -> search`, `smeta/smeta_harness ->
estimator`, `review/doc_review -> engineer`, `text/free/agent/unknown -> agent`.
Trace always records both the requested alias and canonical profile id.

## Safety and failure behavior

- No changes to professional decision logic in `proxy/smeta_core/**`.
- A missing/corrupt active revision fails closed with an actionable operator
  error; it never silently selects Auto.
- Snapshot text is bounded and hashed. Empty prompt/skill values are rejected.
- Referenced deletions preserve snapshot history.
- Profile storage failures do not mutate chat history partially.
- Write tools are not introduced in this release; the registry contract keeps
  approval metadata for their later addition.

## Verification

- Unit tests for seed, immutable revisions, activation, tombstones, snapshot
  binding, aliases, and tool validation.
- API tests for authorization and lifecycle operations.
- Chat tests proving Agent default, no Auto, explicit mode binding, prompt
  injection, tool allowlists, and no implicit XLSX/smeta hijack.
- UI contract tests for the Profiles tab, CodeMirror/preview, Russian controls,
  four mode buttons, and responsive UI-kit use.
- Targeted tests, `make verify`, `make test`, release documentation/version
  checks, clean Git status, commit, and push to `origin`.
