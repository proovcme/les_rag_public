# Sovushka UI review checklist

Use this after reading `docs/modules/sovushka-uikit.md`.

## Before editing

1. Identify the user's primary task on the surface.
2. Find the existing UI-kit primitive for every control, panel, heading and
   state.
3. Record any truly missing role before adding a new primitive.
4. Keep RAG truth, permissions and product behavior outside the visual layer.

## Review

- One primary action per local decision point.
- No duplicate navigation or duplicate dataset selector.
- Icon column is 20 px; icon-to-label gap is 8 px.
- Repeated navigation rows have equal width, height, font and padding.
- Page code adds semantic/layout hooks, not visual `style(...)`.
- Body uses sans-serif; mono is limited to identifiers and numeric diagnostics.
- Text and controls meet WCAG 2.2 AA; focus is visible.
- `prefers-reduced-motion` removes non-essential transitions.
- No page-level horizontal overflow at 390 px.
- Loading, empty, error and blocked are distinguishable in plain language.
- `MISSING/BLOCKED` is not hidden or restyled as a successful answer.

## Verification

Run the narrow UI suite and `make verify`. Inspect the installed web surface on
desktop and at 390 px. Do not build Tauri or update Legion unless the user
explicitly expands the scope.
