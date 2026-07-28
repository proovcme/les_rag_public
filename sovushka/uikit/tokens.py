"""Design tokens and scoped component styles for the Sovushka P0 UI kit."""

UIKIT_CSS = """
<style id="sovushka-uikit-p0">
:root {
  --sov-ui-font-prose: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
    "Helvetica Neue", Inter, system-ui, sans-serif;
  --sov-ui-font-code: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas,
    "Liberation Mono", monospace;
  --sov-ui-space-1: 4px;
  --sov-ui-space-2: 8px;
  --sov-ui-space-3: 12px;
  --sov-ui-space-4: 16px;
  --sov-ui-space-6: 24px;
  --sov-ui-radius-control: 10px;
  --sov-ui-radius-card: 14px;
  --sov-ui-hit: 40px;
  --sov-ui-shadow-card: 0 10px 30px rgba(5, 12, 20, .10);
  --sov-ui-shadow-focus: 0 0 0 3px color-mix(in srgb, var(--accent) 24%, transparent);
}

html {
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

.sov-ui-shell {
  min-width: 0;
  color: var(--text);
  background: var(--bg);
  font-family: var(--sov-ui-font-prose);
}

.sov-ui-shell h1,
.sov-ui-shell h2,
.sov-ui-shell h3 {
  text-wrap: balance;
}

.sov-ui-shell p {
  text-wrap: pretty;
}

.sov-ui-header {
  position: relative;
  z-index: 20;
  border-bottom: 1px solid var(--border);
  background: color-mix(in srgb, var(--bg) 94%, transparent);
}

.sov-ui-card,
.sov-ui-evidence-card {
  border: 1px solid var(--border);
  border-radius: var(--sov-ui-radius-card);
  background: var(--card-bg);
  box-shadow: var(--sov-ui-shadow-card);
}

.sov-ui-button,
.sov-ui-input .q-field__control,
.sov-ui-source-chip {
  min-height: var(--sov-ui-hit);
  border-radius: var(--sov-ui-radius-control);
}

.sov-ui-button,
.sov-ui-source-chip {
  transition: background-color .16s ease, border-color .16s ease,
    box-shadow .16s ease, color .16s ease, transform .12s ease;
}

.sov-ui-button:active:not(:disabled),
.sov-ui-source-chip:active {
  transform: scale(.96);
}

.sov-ui-shell :focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
  box-shadow: var(--sov-ui-shadow-focus);
}

.sov-ui-status {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 2px 9px;
  border: 1px solid currentColor;
  border-radius: 999px;
  font-family: var(--sov-ui-font-code);
  font-size: .68rem;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
}

.sov-ui-status--ok { color: var(--ok); }
.sov-ui-status--warn { color: var(--warn); }
.sov-ui-status--error,
.sov-ui-status--blocked { color: var(--err); }
.sov-ui-status--muted { color: var(--dim); }

.sov-ui-source-chip {
  font-family: var(--sov-ui-font-code);
  font-variant-numeric: tabular-nums;
}

.sov-ui-feedback {
  width: 100%;
  min-width: 0;
  margin: var(--sov-ui-space-2) 0;
  padding: var(--sov-ui-space-3);
  border: 1px solid var(--border);
  border-left: 4px solid var(--dim);
  border-radius: var(--sov-ui-radius-control);
  background: color-mix(in srgb, var(--card-bg) 92%, transparent);
}

.sov-ui-feedback--loading { border-left-color: var(--accent); }
.sov-ui-feedback--empty { border-left-color: var(--dim); }
.sov-ui-feedback--error,
.sov-ui-feedback--blocked { border-left-color: var(--err); }
.sov-ui-feedback__title { font-weight: 800; }
.sov-ui-feedback__detail {
  margin-top: var(--sov-ui-space-1);
  color: var(--dim);
  line-height: 1.45;
}

@media (max-width: 720px) {
  .sov-ui-shell {
    max-width: 100vw;
    overflow-x: clip;
  }
  .sov-ui-card,
  .sov-ui-evidence-card {
    border-radius: 12px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .sov-ui-shell *,
  .sov-ui-shell *::before,
  .sov-ui-shell *::after {
    scroll-behavior: auto !important;
    animation-duration: .001ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: .001ms !important;
  }
}
</style>
"""
