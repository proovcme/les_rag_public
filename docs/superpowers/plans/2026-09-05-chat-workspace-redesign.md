# Chat workspace redesign implementation plan

Owner approved the interactive localhost:18952 design on 2026-09-05 and requested
visible Configuration navigation, without Studio/CAD placeholders. Publication is cancelled.

Goal: visible creatable projects and their chats, a unified calm conversation surface,
and preserved source/memory/file/model behaviors.

Architecture: existing ChatWorkspace remains the navigation/state authority. A focused
project-navigation component renders projects and scoped sessions. The existing chat page
keeps all model, attachment, scope and artifact handlers; only their layout changes.
Shared UI-kit tokens own the styles. Configuration retains its current implementation.

- [ ] Regression tests for project creation, navigation refresh and visible controls.
- [ ] Project navigation component, labelled Configuration/Data access and mobile drawer.
- [ ] Chat header, context row, non-overlapping composer and settings dialog.
- [ ] Scope legacy app chrome to compact chat layout; hide Studio/CAD placeholders.
- [ ] Real component preview: create/switch/new chat, memory, settings, artifacts; desktop/390px.
- [ ] Update module/index/ledger/version, focused tests, make verify and make test.

Owner later authorized publication after all checks; use canonical release orchestrator and installed acceptance. No retrieval/model prompt/decision changes.