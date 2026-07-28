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

.sov-nav-switch {
  min-height: var(--sov-ui-hit) !important;
  padding: 0 15px !important;
  border-radius: 11px !important;
  font-family: var(--sov-ui-font-prose) !important;
  font-size: .76rem !important;
  font-weight: 850 !important;
  letter-spacing: .01em;
  white-space: nowrap;
  box-shadow: 0 5px 16px rgba(15, 23, 42, .10);
}

.sov-nav-switch--chat {
  color: #052e24 !important;
  background: var(--accent) !important;
}

.sov-nav-switch--config {
  color: var(--text) !important;
  background: var(--card-bg) !important;
  box-shadow:
    inset 0 0 0 1px color-mix(in srgb, var(--accent) 58%, var(--border)),
    0 5px 16px rgba(15, 23, 42, .08);
}

.sov-nav-switch:hover {
  filter: brightness(1.04);
}

.sov-source-usage {
  flex: 0 0 auto;
  padding: 3px 8px;
  border: 1px solid var(--border);
  border-radius: 999px;
  font-size: .61rem;
  font-weight: 850;
  font-variant-numeric: tabular-nums;
}
.sov-source-usage--ok {
  color: var(--ok);
  border-color: color-mix(in srgb, var(--ok) 56%, var(--border));
}
.sov-source-usage--warn {
  color: var(--warn);
  border-color: color-mix(in srgb, var(--warn) 62%, var(--border));
}
.sov-source-usage--muted { color: var(--dim); }
.sov-retrieval-notice {
  width: 100%;
  margin: 6px 0;
  padding: 9px 11px;
  border-radius: var(--sov-ui-radius-control);
  background: color-mix(in srgb, var(--warn) 10%, var(--card-bg));
}
.sov-retrieval-notice--warn {
  border: 1px solid color-mix(in srgb, var(--warn) 55%, var(--border));
}
.sov-retrieval-notice-title { font-size: .72rem; font-weight: 850; }
.sov-retrieval-notice-detail { margin-top: 2px; color: var(--dim); font-size: .65rem; }
.sov-docs-sticky-ask {
  position: sticky;
  z-index: 4;
  bottom: 0;
  display: flex;
  width: 100%;
  margin-top: 8px;
  padding: 10px;
  gap: 10px;
  align-items: center;
  border: 1px solid color-mix(in srgb, var(--accent) 58%, var(--border));
  border-radius: 13px;
  background: color-mix(in srgb, var(--card-bg) 90%, var(--accent) 10%);
  box-shadow: 0 -8px 24px rgba(15, 23, 42, .12);
}
.sov-docs-sticky-ask-button {
  min-height: 42px !important;
  color: #052e24 !important;
  background: var(--accent) !important;
  font-weight: 850 !important;
}
.sov-mail-status-strip {
  display: flex;
  width: 100%;
  margin-bottom: 12px;
  padding: 12px 14px;
  gap: 12px;
  align-items: center;
  border: 1px solid var(--border);
  border-radius: 15px;
  background: var(--card-bg);
  box-shadow: var(--sov-ui-shadow-card);
}
.sov-mail-status-copy { min-width: 180px; flex: 1; }
.sov-mail-status-title { font-size: .82rem; font-weight: 850; }
.sov-mail-status-note { margin-top: 2px; color: var(--dim); font-size: .66rem; }
.sov-mail-status-metric {
  min-width: 72px;
  padding: 6px 9px;
  border-radius: 10px;
  text-align: center;
  background: color-mix(in srgb, var(--bg) 82%, transparent);
}
.sov-mail-status-value {
  font-family: var(--sov-ui-font-code);
  font-size: .86rem;
  font-weight: 900;
  font-variant-numeric: tabular-nums;
}
.sov-mail-status-label { color: var(--dim); font-size: .58rem; }
.sov-mail-status-metric--ok .sov-mail-status-value { color: var(--ok); }
.sov-mail-status-metric--warn .sov-mail-status-value { color: var(--warn); }
.sov-mail-collect-button,
.sov-mail-ask-button {
  min-height: 42px !important;
  color: #052e24 !important;
  background: var(--accent) !important;
  font-weight: 850 !important;
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
  .sov-ui-header {
    padding-inline: 6px !important;
  }
  .sov-ui-version-badge,
  .sov-ui-header-secondary {
    display: none !important;
  }
  .sov-ui-header-controls {
    flex-wrap: nowrap !important;
    gap: 0 !important;
    margin-left: 2px !important;
  }
  .sov-ui-header-action {
    width: var(--sov-ui-hit);
    min-width: var(--sov-ui-hit);
    max-width: var(--sov-ui-hit) !important;
    padding-inline: 0 !important;
  }
  .sov-ui-header-action .q-btn__content {
    font-size: 0;
    gap: 0;
  }
  .sov-ui-header-action .q-icon {
    font-size: 20px;
  }
  .sov-nav-switch {
    min-width: var(--sov-ui-hit) !important;
    width: var(--sov-ui-hit);
    padding: 0 !important;
  }
  .sov-nav-switch .q-btn__content {
    gap: 0;
    font-size: 0;
  }
  .sov-nav-switch .q-icon {
    font-size: 20px;
  }
  .sov-docs-sticky-ask { align-items: stretch; flex-direction: column; }
  .sov-docs-sticky-ask-button { width: 100%; }
  .sov-mail-status-strip { align-items: stretch; flex-wrap: wrap; }
  .sov-mail-status-copy { width: 100%; flex-basis: 100%; }
  .sov-mail-status-metric { flex: 1; }
  .sov-mail-collect-button { width: 100%; }
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
