---
name: sovushka-ui
description: Use when designing, implementing, reviewing, or documenting the LES Sovushka NiceGUI interface, UI kit, navigation, typography, controls, responsive layout, accessibility, or visual consistency. Enforces the Locia-like shared-component contract and minimizes one-off UI elements.
---

# Sovushka UI

## Overview

Keep Sovushka visually calm, dense and predictable through one token layer and a
small component registry. Optimize the user's working path before adding
decoration.

## Required context

Read in this order:

1. `AGENTS.md`
2. `docs/modules/sovushka-uikit.md`
3. `sovushka/uikit/components.py`
4. `sovushka/uikit/tokens.py`
5. `references/review-checklist.md`

Read only the target page and its targeted tests after that. Treat
`sovushka/styles.py` as a legacy compatibility layer, not the destination for
new design rules.

## Workflow

1. State the primary user task and current UX defect.
2. Reuse `action_button`, `text_field`, `panel`, `section_heading`,
   `status_badge`, `render_feedback_state`, or `acronym_identity`.
3. Add a primitive only when the registry cannot express a recurring role.
4. Put visual tokens and component states in `sovushka/uikit/`; page code owns
   data, behavior and layout hooks.
5. Preserve RAG evidence, `MISSING/BLOCKED`, permissions and runtime behavior.
6. Add a regression test and update the UI-kit doc plus `MODULE_INDEX`.
7. Run targeted UI tests and `make verify`.
8. For a requested Mac web update, use the accepted small transactional updater;
   do not build Tauri, touch Legion, or publish.

## Non-negotiable design rules

- Use one system sans-serif; reserve mono for identifiers and numeric diagnostics.
- Use the shared spacing, radius, color and type tokens.
- Keep icon column at 20 px and icon-to-label gap at 8 px.
- Make repeated navigation rows equal in size and left alignment.
- Keep text contrast at WCAG 2.2 AA, visible focus and reduced-motion support.
- Prefer vertical working surfaces; do not add a permanent content sidebar.
- Do not add dependencies, downloaded fonts, page-local visual hex values, or
  decorative one-off components.
- If three places repeat the same visual role, extract it into the UI kit.

## Handoff

Report the primary before/after change, shared primitives used, desktop/mobile
checks, WCAG result, and any remaining legacy surface. Never claim full UI
migration from a critical-path-only change.


## Контракт качества сметы и быстрой корректировки (Smeta Memory Core v0.3)
1. **Построчное и общее подтверждение качества:**
   - Построчные кнопки `👍 Подтвердить качество` / `VERIFIED` сохраняют эталонные пары ВОР→ГЭСН в Память.
   - Кнопка `Принять качество всей сметы в Память` в шапке панели фиксирует полную сметную ревизию.
2. **Панель быстрой корректировки выделенных строк:**
   - Чекбоксы выбора позиций ВОР объединяются с полем ввода директив.
   - Кнопка `Применить к выделенным` автоматически формирует структурированный промт с нужными `work_id`.
