# Project Workspace and Editable Memory Implementation Plan

**Goal:** Project-owned chat sessions with persisted explicit source selection and
editable, inspectable advisory memory in the chat UI.

**Architecture:** Existing les_projects and les_notes remain canonical. A small
session registry stores ownership and UI selection independently of message history.
Typed memory continues through the existing ContextGovernor; no new model call.

**Tech Stack:** Python, SQLite, FastAPI, NiceGUI; existing dependencies only.

**Spec:** ../specs/2026-09-05-project-memory-product-direction.md

## Global constraints

- Local 9–100B models; primary flow must work on 9B; cloud optional.
- No hidden dataset selection or other-project/chat content in model input.
- Preserve original input, evidence, model decisions and existing artifact packaging.
- Do not modify protected document_workflow.py or installed runtime.
- Reuse UI kit; Russian product copy; no permanent content sidebar.
- Existing reranker candidate changes are preserved, not mixed into unrelated rewrites.

## Task 1: Durable session ownership

Files: new proxy/services/chat_session_service.py, new proxy/routers/workspace.py,
tests/test_chat_session_service.py, tests/test_workspace_router.py.

Interfaces: create_session(project_id=None, title='', session_id=None) -> dict;
get_session(session_id) -> dict|None; list_sessions(project_id=None) -> list;
update_session(session_id, title=None, scope=None, role=None) -> dict;
get_session_project_id(session_id) -> int|None (read-only).

Session fields: session_id, project_id nullable, title, role default agent,
scope JSON (explicit scope_type/project_ids/dataset_ids/selected_sources_only),
created_at and updated_at. Project ID cannot change after creation.
Creation validates project existence; new project sessions copy linked datasets
as explicit defaults. Existing history is represented as ordinary chats only;
never infer ownership from text or datasets. No deletion/move of data.

API: /api/workspace/sessions GET(project_id optional), POST;
/api/workspace/sessions/{session_id} GET, PATCH. require_user, errors 404/409/422.

- [x] Write isolated SQLite and API regression tests, observe red.
- [x] Implement service/router; prove persistence and project isolation.
- [x] Review interfaces and migration behavior.

## Task 2: Editable memory and context isolation

Files: memory_service.py, typed_memory_projection_service.py, workspace.py,
chat_evidence_application_service.py, corresponding tests.

Reuse les_notes with enabled boolean and optional origin session reference;
add create/edit/enable/delete APIs scoped to global preferences or one project.
Projection reads enabled notes only, applies scope before limits, and retains
stable note IDs. No price/norm decisions are promoted automatically.
Registered session ownership is the authoritative memory scope. Legacy sessions
retain compatibility until registered; ordinary registered sessions cannot
inherit memory merely by selecting a project dataset.

- [x] Test edit/exclusion, ordinary/project isolation and legacy compatibility.
- [x] Implement explicit note controls and bounded projection with ID trace.
- [x] Verify model input still includes original question and evidence.

## Task 3: Chat workspace UI

Files: new sovushka/components/chat_workspace.py, pages/chat.py, UI tests.

Project picker includes ordinary chat, create project, project chat list and
new chat. Opening a project restores its latest session; new sessions start with
project source defaults. Source/role changes are persisted before send, and
session restoration clears transient attachments/artifacts from the previous chat.
Memory dialog shows global/project records with edit, include/exclude and delete;
labels clarify advisory status. No technical IDs in primary UI.

- [x] Test controller state round trips and no cross-session residue.
- [x] Reuse UI kit primitives and integrate scoped history and memory controls.
- [x] Verify desktop/mobile behavior in isolated preview where available.

## Task 4: Integration and delivery evidence

- [x] Focused tests for storage, API, UI and model-input scope.
- [x] Update module docs/index, candidate version/build, ledger and generated map.
- [x] Run make verify and make test; review complete diff.
- [x] State exact live acceptance limits; no publication or installed-runtime change.

Owner selected explicit manual save only; explicit note CRUD and
project isolation are useful regardless of later automatic capture policy.
