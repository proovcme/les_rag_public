# Chat Profile Studio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build persistent, versioned chat profiles with prompt/skill/tool selection and bind every chat to an immutable profile snapshot.

**Architecture:** A focused SQLite-backed profile store seeds factory revisions and exposes immutable lifecycle operations. The chat router resolves one snapshot before routing and passes it into model/tool boundaries; a NiceGUI Profiles page edits and activates revisions without adding dependencies.

**Tech Stack:** Python 3.12, FastAPI, SQLite, NiceGUI 3.12 CodeMirror/Markdown, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-08-24-chat-profile-studio-design.md`

## Global Constraints

- Do not modify `proxy/smeta_core/**`.
- Do not add dependencies.
- Preserve user state in `rag_meta_db_path()` and keep Base revisions immutable.
- The UI emits only `search`, `agent`, `estimator`, and `engineer`; Agent is default.
- User-visible interface text is Russian and uses the Sovushka UI kit.
- Tests use workspace-local `--basetemp=.test-tmp/<gate>` on Windows.

---

### Task 1: Persistent profile domain

**Files:**
- Create: `proxy/services/chat_profile_service.py`
- Create: `tests/test_chat_profile_service.py`

**Interfaces:**
- Produces: `registry_snapshot()`, `resolve_chat_profile()`, `publish_profile_revision()`, `activate_profile_revision()`, `delete_revision()` and immutable snapshot dictionaries.

- [ ] Write failing tests for idempotent Base seed, immutable publish, activation, deletion/tombstone, tool validation, aliases, and session binding.
- [ ] Run `uv run pytest tests/test_chat_profile_service.py -q --basetemp=.test-tmp/chat-profile-red` and confirm failures are caused by the missing service.
- [ ] Implement the minimal SQLite service using `rag_meta_db_path()` and the current prompt/tool registries.
- [ ] Run the same test file with `--basetemp=.test-tmp/chat-profile-green` and confirm it passes.

### Task 2: Profile lifecycle API

**Files:**
- Create: `proxy/routers/profiles.py`
- Modify: `proxy/app.py`
- Create: `tests/test_profiles_router.py`

**Interfaces:**
- Consumes: Task 1 service functions.
- Produces: `/api/profiles` registry, publish/copy/activate/delete, and chat-binding endpoints.

- [ ] Write failing API tests for lifecycle success, invalid cross-mode activation, Base deletion, and explicit chat rebinding.
- [ ] Run the test and confirm missing routes fail.
- [ ] Implement the router and register it in the app.
- [ ] Run the API tests and service tests to green.

### Task 3: Runtime profile binding

**Files:**
- Modify: `proxy/services/profile_resolver.py`
- Modify: `proxy/routers/chat.py`
- Modify: `proxy/services/chat_evidence_application_service.py`
- Modify: `proxy/services/tool_harness_service.py`
- Modify: `proxy/services/smeta_chat_application_service.py`
- Modify: `proxy/services/smeta_chat_adapter_service.py`
- Modify: `proxy/routers/chat_history.py`
- Modify: `tests/test_profile_resolver.py`
- Modify: `tests/test_sovushka_chat.py`
- Modify: `tests/test_chat_spec_to_bor_attachment.py`
- Modify: `tests/test_tool_harness_service.py`

**Interfaces:**
- Consumes: `resolve_chat_profile(session_id, requested_mode, requested_revision_id, apply_revision)`.
- Produces: effective snapshot in `query_route.profile_snapshot`, history, the shared RAG system prompt for all four profiles, and filtered tool shortlist.

- [ ] Write failing behavior tests proving Agent default, canonical aliases, stable chat snapshots, selected prompt injection, profile tool filtering, and explicit profiles bypass legacy automatic spec/smeta interception.
- [ ] Run the narrow tests and confirm the expected old behavior fails.
- [ ] Thread the resolved snapshot through the router and application boundaries without changing smeta-core decisions.
- [ ] Run the narrow runtime tests to green and refactor duplicated mode handling.

### Task 4: Profiles configuration page and chat modes

**Files:**
- Create: `sovushka/pages/profiles.py`
- Modify: `sovushka/components/header.py`
- Modify: `sovushka_ng.py`
- Modify: `sovushka/pages/chat.py`
- Modify: `sovushka/uikit/tokens.py` only if an existing token cannot express the layout.
- Modify: `tests/test_sovushka_chat.py`
- Modify: `tests/test_sovushka_uikit.py`

**Interfaces:**
- Consumes: `/api/profiles` API.
- Produces: one-screen profile studio using `ui.codemirror(language="Markdown")`, `ui.markdown`, shared buttons/panels/selects/badges, and four canonical chat buttons.

- [ ] Write failing UI contract tests for the Profiles tab, four modes, Agent default, select/activate/delete actions, CodeMirror preview, and no Auto fallback.
- [ ] Run the UI tests and confirm failures describe the missing surface.
- [ ] Implement the lazy configuration tab and update chat payload/state.
- [ ] Run UI and API tests to green; inspect desktop and 390 px layout if the local surface is available.

### Task 5: Migration, documentation, version and release

**Files:**
- Modify: `proxy/services/prompt_registry_service.py`
- Modify: `docs/modules/sovushka-uikit.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `docs/CODE_MAP.md`
- Modify: `docs/TEST_INVENTORY.md`
- Modify: `docs/SOFTWARE_VERSIONS.md`
- Modify: `docs/RELEASE_LEDGER.md`
- Modify: `config/version.json`
- Test: `tests/test_prompt_registry_service.py`, `tests/test_software_versions.py`

**Interfaces:**
- Produces: one-time legacy override import/read compatibility and canonical documentation for the shipped profile system.

- [ ] Write a failing migration test proving legacy overrides become durable revisions without replacing existing user state.
- [ ] Implement the compatibility bridge and run its tests.
- [ ] Update module docs, maps, test inventory, SemVer/build, and release ledger in the same change.
- [ ] Run targeted profile/UI/chat tests, `make verify`, and `make test`.
- [ ] Review the full diff for secrets, runtime data, accidental generated files, protected smeta-core edits, and documentation drift.
- [ ] Commit the complete reviewed working tree and push the current branch to `origin`.
