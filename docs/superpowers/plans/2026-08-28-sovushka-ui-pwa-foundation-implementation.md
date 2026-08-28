# Sovushka UI and PWA Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:executing-plans` and apply test-driven development task by task.

**Goal:** Establish the approved product-wide Sovushka visual hierarchy and a safe installable PWA foundation before building the Models configuration page.

**Architecture:** NiceGUI remains the single server-backed frontend/BFF. Browser, PWA and Tauri WebView render the same Sovushka. The UI consumes LES APIs only; model connections and domain execution remain backend-owned. PWA caching is limited to an offline shell and static identity assets.

**Spec:** `docs/superpowers/specs/2026-08-28-sovushka-product-ui-pwa-design.md`

## Constraints

- Read and follow `skills/sovushka-ui/SKILL.md` and `docs/modules/sovushka-uikit.md`.
- Reuse shared UI-kit primitives; new recurring icon/navigation roles belong in `sovushka/uikit/`.
- Do not add a frontend dependency or download a font/icon package.
- Do not change LES backend behavior, model routing, RAG, memory or tool contracts.
- Preserve Tauri's local lifecycle URL and bootstrap behavior.
- Mobile is tested at 390 px; controls outside dense desktop configuration are at least 44 px.
- Each task increments build/version surfaces, updates ledger/docs and commits independently.

### Task 1: Shared visual hierarchy and mobile chat shell

**Build:** 613

**Files:**
- Modify: `sovushka/uikit/tokens.py`
- Modify: `sovushka/uikit/components.py` only for a genuinely shared recurring role
- Modify: `sovushka/components/header.py`
- Modify: `sovushka/pages/chat.py`
- Modify: `tests/test_sovushka_uikit.py`
- Modify: `tests/test_sovushka_chat.py`
- Modify: `docs/modules/sovushka-uikit.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: version surfaces and `docs/RELEASE_LEDGER.md`

- [ ] Write RED contracts for 16 px body, 14 px controls, 12 px metadata, 44 px mobile targets, labelled mobile primary navigation, a collapsed suggestion surface and a composer whose first layer contains prompt/attachment/send plus one mode selector.
- [ ] Run the two focused test files and confirm the new assertions fail.
- [ ] Update shared tokens and AppShell hierarchy. Remove decorative gradients and reduce repeated borders/shadows without reducing status truth or keyboard focus.
- [ ] Replace the mobile icon-only primary navigation with three stable labelled destinations. Keep technical sections under Configuration.
- [ ] Collapse chat guidance by default after onboarding. Replace four visible mode buttons with one compact mode selector; keep response settings in its existing secondary surface.
- [ ] Run focused UI tests, version checks and `git diff --check`; update docs/version/ledger and commit `refactor(ui): sharpen Sovushka product shell`.

### Task 2: Safe PWA shell

**Build:** 614

**Files:**
- Create: `frontend/pwa/manifest.webmanifest`
- Create: `frontend/pwa/service-worker.js`
- Create: `frontend/pwa/offline.html`
- Modify: `sovushka_ng.py`
- Create: `tests/test_sovushka_pwa.py`
- Modify: `docs/modules/sovushka-uikit.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `docs/CODE_MAP.md`
- Modify: version surfaces and `docs/RELEASE_LEDGER.md`

- [ ] Write RED tests for static mounting, manifest identity/start URL/display/theme, service-worker registration and a deny-by-default cache boundary for `/api/`, streams, documents and non-GET requests.
- [ ] Run the focused PWA test and confirm failure because the assets and registration do not exist.
- [ ] Mount versioned PWA assets and the existing bundled Tauri icon directory. Add manifest/theme/apple metadata and register the worker from the shared page head.
- [ ] Implement network-first navigation with an offline fallback page. Cache only the offline shell and identity assets; never cache authenticated/API content.
- [ ] The offline page explains that the LES execution node is unavailable and stores only an unsent draft in local browser storage. It never queues or replays a request.
- [ ] Run PWA, static-assets, Tauri and focused UI tests; update docs/version/ledger and commit `feat(ui): add safe Sovushka PWA shell`.

## Handoff

After Task 2, continue Task 9 of
`2026-08-27-universal-model-connections-implementation.md`. The Models page must
reuse the updated shell and may not introduce a parallel visual system.

