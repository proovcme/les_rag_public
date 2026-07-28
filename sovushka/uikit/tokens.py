"""Design tokens and scoped component styles for the Sovushka P0 UI kit."""

UIKIT_CSS = """
<style id="sovushka-uikit-p0">
:root {
  --sov-ui-font-prose: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
    "Helvetica Neue", Inter, system-ui, sans-serif;
  --sov-ui-font-code: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas,
    "Liberation Mono", monospace;
  --sov-ui-font-size-body: 14px;
  --sov-ui-font-size-control: 13px;
  --sov-ui-font-size-meta: 12px;
  --sov-ui-line-body: 1.5;
  --sov-ui-line-control: 1.25;
  --sov-ui-space-1: 4px;
  --sov-ui-space-2: 8px;
  --sov-ui-space-3: 12px;
  --sov-ui-space-4: 16px;
  --sov-ui-space-6: 24px;
  --sov-ui-radius-control: 8px;
  --sov-ui-radius-card: 10px;
  --sov-ui-hit: 40px;
  --sov-ui-shadow-card:
    0 0 0 1px color-mix(in srgb, var(--border) 54%, transparent),
    0 1px 2px rgba(20, 52, 34, .04),
    0 8px 24px rgba(20, 52, 34, .045);
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
  font-size: var(--sov-ui-font-size-body);
  font-weight: 400;
  line-height: var(--sov-ui-line-body);
  font-synthesis: none;
  text-rendering: optimizeLegibility;
}

.sov-ui-shell .q-btn__content,
.sov-ui-shell .q-tab__label,
.sov-ui-shell .q-field__native,
.sov-ui-shell .q-field__label,
.sov-ui-shell .q-item__label,
.sov-ui-shell .q-chip__content,
.sov-ui-shell .q-tooltip {
  font-family: var(--sov-ui-font-prose);
}

.sov-ui-shell .q-btn__content,
.sov-ui-shell .q-tab__label {
  font-size: var(--sov-ui-font-size-control);
  font-weight: 650;
  line-height: var(--sov-ui-line-control);
}

.sov-ui-shell code,
.sov-ui-shell pre,
.sov-ui-shell kbd,
.sov-ui-shell samp,
.sov-ui-shell .sov-ui-status,
.sov-ui-shell .sov-ui-source-chip {
  font-family: var(--sov-ui-font-code);
}

.sov-ui-shell h1,
.sov-ui-shell h2,
.sov-ui-shell h3 {
  line-height: 1.2;
  letter-spacing: -.015em;
  text-wrap: balance;
}

.sov-ui-shell p {
  text-wrap: pretty;
}

.sov-ui-shell .sov-chat-identity {
  display: flex;
  align-items: center;
  gap: 9px;
}

.sov-ui-shell .sov-chat-identity-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
  justify-content: center;
}

.sov-ui-shell .sov-owl-mark {
  display: inline-grid;
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  place-items: center;
  color: var(--accent);
  border: 1px solid color-mix(in srgb, var(--accent) 34%, var(--border));
  border-radius: 9px;
  background: color-mix(in srgb, var(--accent) 8%, var(--bg-panel));
}

.sov-ui-shell .sov-owl-mark svg {
  width: 25px;
  height: 25px;
  overflow: visible;
}

.sov-ui-shell .sov-owl-mark path:first-child,
.sov-ui-shell .sov-owl-mark circle:not(.sov-owl-eye) {
  fill: none;
  stroke: currentColor;
  stroke-width: 1.7;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.sov-ui-shell .sov-owl-eye,
.sov-ui-shell .sov-owl-beak {
  fill: currentColor;
  stroke: none;
}

.sov-ui-shell .sov-chat-title {
  font-family: var(--sov-ui-font-prose);
  font-size: 14px;
  font-weight: 750;
  line-height: 1.25;
  letter-spacing: 0;
}

.sov-ui-shell .sov-chat-subtitle {
  font-family: var(--sov-ui-font-prose);
  font-size: var(--sov-ui-font-size-meta);
  font-weight: 400;
  line-height: 1.35;
}

.sov-ui-header {
  position: relative;
  z-index: 20;
  border-bottom: 1px solid var(--border);
  background: var(--bg-panel);
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

.sov-primary-nav {
  display: flex;
  align-items: center;
  flex-wrap: nowrap;
  gap: 4px;
  padding: 3px;
  border-radius: 10px;
  background: color-mix(in srgb, var(--card-bg) 82%, transparent);
  box-shadow:
    inset 0 0 0 1px color-mix(in srgb, var(--border) 78%, transparent),
    0 5px 16px rgba(15, 23, 42, .07);
}

.sov-nav-switch {
  min-height: var(--sov-ui-hit) !important;
  padding: 0 12px !important;
  border-radius: 7px !important;
  font-family: var(--sov-ui-font-prose) !important;
  font-size: .72rem !important;
  font-weight: 850 !important;
  letter-spacing: .01em;
  white-space: nowrap;
  color: var(--dim) !important;
  background: transparent !important;
  box-shadow: none;
  transition: background-color .16s ease, box-shadow .16s ease,
    color .16s ease, transform .12s ease, filter .16s ease;
}

.sov-nav-switch--active {
  color: #ffffff !important;
  background: var(--accent) !important;
  box-shadow: 0 4px 12px color-mix(in srgb, var(--accent) 22%, transparent);
}

.sov-nav-switch--active .q-btn__content,
.sov-nav-switch--active .q-icon {
  color: #ffffff !important;
}

.sov-nav-switch:active {
  transform: scale(.96);
}

.sov-nav-switch:hover {
  filter: brightness(1.04);
}

.les-top-tabs .sov-primary-tab-mirrored {
  display: none !important;
}

.sov-sidebar-caption {
  display: none;
  color: var(--dim);
  font-size: 10px;
  font-weight: 850;
  letter-spacing: .08em;
}

.sov-app-content {
  min-width: 0;
  background: var(--bg) !important;
}

.sov-app-content .sov-chat-shell {
  background: var(--bg);
}

.sov-app-content .sov-chat-main,
.sov-app-content .sov-artifacts-panel,
.sov-app-content .sov-history-drawer {
  border-color: var(--border);
  border-radius: var(--sov-ui-radius-card);
  background: var(--bg-panel);
  box-shadow: var(--sov-ui-shadow-card);
  backdrop-filter: none;
}

.sov-app-content .sov-chat-topbar {
  background: var(--bg-panel);
  border-bottom-color: var(--border);
}

.sov-app-content .sov-chat-scroll {
  background: color-mix(in srgb, var(--bg) 70%, var(--bg-panel));
}

.sov-app-content .sov-chat-empty {
  border-radius: var(--sov-ui-radius-card);
  background: var(--bg-panel);
  box-shadow: var(--sov-ui-shadow-card);
}

.sov-app-content .sov-composer {
  border: 1px solid var(--border) !important;
  border-radius: 12px !important;
  box-shadow:
    0 0 0 1px color-mix(in srgb, var(--border) 36%, transparent),
    0 10px 28px rgba(20, 52, 34, .09) !important;
}

.sov-app-content .sov-composer-actions .q-btn:last-child,
.sov-app-content .sov-send-btn {
  color: #ffffff !important;
  background: var(--accent) !important;
}

.sov-app-content .sov-composer-actions .q-btn:last-child .q-btn__content,
.sov-app-content .sov-composer-actions .q-btn:last-child .q-icon,
.sov-app-content .sov-send-btn .q-btn__content,
.sov-app-content .sov-send-btn .q-icon {
  color: #ffffff !important;
}

.sov-app-content .sov-attach-btn {
  width: 40px;
  min-width: 40px !important;
  height: 40px;
  min-height: 40px !important;
  padding: 0 !important;
  color: var(--dim) !important;
  border: 1px solid var(--border) !important;
  border-radius: var(--sov-ui-radius-control) !important;
  background: var(--bg-panel) !important;
  box-shadow: 0 1px 2px rgba(20, 52, 34, .04);
}

.sov-app-content .sov-attach-btn:hover {
  color: var(--accent) !important;
  border-color: color-mix(in srgb, var(--accent) 46%, var(--border)) !important;
  background: color-mix(in srgb, var(--accent) 6%, var(--bg-panel)) !important;
}

.sov-app-content .sov-attach-btn .q-btn__content {
  width: 100%;
  height: 100%;
  align-items: center;
  justify-content: center;
}

.sov-app-content .sov-attach-btn .q-icon {
  margin: 0 !important;
  font-size: 20px;
  line-height: 1;
}

.sov-app-content .sov-mode-guide,
.sov-app-content .sov-mode-example {
  border: 1px solid color-mix(in srgb, var(--border) 72%, transparent);
  box-shadow: 0 2px 10px rgba(20, 52, 34, .05);
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

@media (min-width: 901px) {
  .sov-app-shell {
    display: grid !important;
    grid-template-columns: 160px minmax(0, 1fr);
    grid-template-rows: 100vh;
    align-items: stretch;
    overflow: hidden;
  }

  .sov-app-shell > .sov-ui-header {
    grid-column: 1;
    grid-row: 1;
    display: flex !important;
    width: 160px !important;
    height: 100vh !important;
    min-height: 0;
    padding: 12px 8px 10px !important;
    gap: 5px !important;
    align-items: stretch !important;
    flex-direction: column;
    border-right: 1px solid var(--border);
    border-bottom: 0;
    box-shadow: 2px 0 18px rgba(20, 52, 34, .035);
  }

  .sov-app-shell > .sov-app-content {
    grid-column: 2;
    grid-row: 1;
    width: 100%;
    height: 100vh;
    min-height: 0;
  }

  .sov-brand-block {
    min-height: 36px;
    margin: 0 !important;
    padding: 2px 7px;
    justify-content: flex-start;
  }

  .sov-brand-block .les-brand {
    font-size: 15px !important;
    line-height: 1 !important;
    letter-spacing: 0;
  }

  .sov-ui-version-badge {
    align-self: stretch;
    width: 100%;
    margin: 0 0 5px !important;
    padding-inline: 3px !important;
    justify-content: flex-start;
    font-size: 10px !important;
    font-variant-numeric: tabular-nums;
    line-height: 1.2 !important;
    color: var(--dim) !important;
    background: var(--bg) !important;
    border-color: var(--border) !important;
  }

  .sov-primary-nav {
    width: 100%;
    padding: 0;
    gap: 4px;
    flex-direction: column;
    align-items: stretch;
    background: transparent;
    box-shadow: none;
  }

  .sov-nav-switch {
    width: 100%;
    min-height: 44px !important;
    padding: 4px 10px !important;
    justify-content: flex-start;
    font-size: 12px !important;
    line-height: 1.2 !important;
  }

  .sov-nav-switch .q-btn__content {
    width: 100%;
    gap: 8px;
    flex-direction: row;
    justify-content: flex-start;
  }

  .sov-nav-switch .q-icon {
    font-size: 18px;
    line-height: 1;
  }

  .sov-sidebar-caption {
    display: block;
    margin: 11px 10px 3px;
    overflow: hidden;
    font-size: 10px;
    font-weight: 750;
    line-height: 1.2;
    letter-spacing: .04em;
    text-align: left;
    white-space: nowrap;
  }

  .les-top-tabs {
    width: 100%;
    height: auto !important;
    min-height: 0;
  }

  .les-top-tabs .q-tabs__content {
    width: 100%;
    height: 100% !important;
    align-items: stretch;
    flex-direction: column;
    overflow-x: hidden !important;
    overflow-y: auto !important;
  }

  .les-top-tabs .q-tab {
    flex: 0 0 44px !important;
    width: 100%;
    height: 44px !important;
    min-height: 44px !important;
    margin: 1px 0;
    padding: 0 10px;
    border-radius: 7px;
    justify-content: flex-start;
  }

  .les-top-tabs .q-tab__content {
    min-width: 0;
    width: 100%;
    height: 44px !important;
    min-height: 44px !important;
    gap: 8px;
    align-items: center;
    flex-direction: row;
    justify-content: flex-start;
  }

  .les-top-tabs .q-icon {
    font-size: 20px;
    line-height: 1;
  }

  .les-top-tabs .q-tab__label {
    display: block;
    overflow: hidden;
    font-size: 12px;
    line-height: 1.2;
    text-align: left;
    text-overflow: clip;
    white-space: nowrap;
  }

  .les-top-tabs .q-tab__indicator {
    top: 7px;
    right: auto;
    bottom: 7px;
    left: 0;
    width: 3px;
    height: auto;
    border-radius: 0 3px 3px 0;
  }

  .sov-ui-header-controls {
    width: 100%;
    margin: auto 0 0 !important;
    padding-top: 9px;
    gap: 0 !important;
    align-items: center;
    justify-content: flex-start;
    border-top: 1px solid var(--border);
  }

  .sov-ui-header-secondary,
  .sov-ui-header-action {
    width: 100%;
    min-height: 38px;
    justify-content: center;
  }

  .sov-ui-header-action .q-btn__content {
    width: 100%;
    gap: 0;
    justify-content: center;
  }

  .sov-ui-header-action .q-btn__content > :not(.q-icon),
  .sov-ui-header-secondary {
    font-size: 0 !important;
  }

  .sov-app-content .sov-chat-shell {
    height: 100vh;
    min-height: 0;
    padding: 16px 18px;
  }

  .sov-ui-shell .sov-owl-mark {
    width: 30px;
    height: 30px;
    flex-basis: 30px;
  }
}

@media (max-width: 900px) {
  .sov-ui-shell {
    max-width: 100vw;
    overflow-x: clip;
  }
  .sov-app-shell {
    display: flex !important;
    flex-direction: column;
  }
  .sov-ui-card,
  .sov-ui-evidence-card {
    border-radius: 9px;
  }
  .sov-app-shell > .sov-ui-header {
    width: 100% !important;
    height: 62px !important;
    min-height: 62px;
    padding-inline: 6px !important;
    gap: 2px !important;
    flex-direction: row;
    align-items: center !important;
    border-right: 0;
    border-bottom: 1px solid var(--border);
  }
  .sov-ui-version-badge,
  .sov-ui-header-secondary,
  .sov-sidebar-caption {
    display: none !important;
  }
  .sov-brand-block {
    margin-right: 2px !important;
  }
  .les-top-tabs {
    height: 62px !important;
    overflow: hidden;
  }
  .les-top-tabs .q-tabs__content {
    justify-content: flex-start;
  }
  .les-top-tabs .q-tab {
    min-width: 44px;
    min-height: 62px;
    padding-inline: 7px;
  }
  .sov-ui-header-controls {
    display: none !important;
  }
  .sov-ui-header-utility,
  .sov-ui-header-action {
    display: none !important;
  }
  .sov-primary-nav {
    flex: 0 0 auto;
    gap: 2px;
    padding: 1px;
    background: transparent;
    box-shadow: none;
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
  .sov-app-content {
    height: calc(100vh - 62px);
  }
  .sov-app-content .sov-chat-shell {
    height: calc(100vh - 62px);
    min-height: 0;
    padding: 8px;
  }
  .sov-docs-sticky-ask { align-items: stretch; flex-direction: column; }
  .sov-docs-sticky-ask-button { width: 100%; }
  .sov-mail-status-strip { align-items: stretch; flex-wrap: wrap; }
  .sov-mail-status-copy { width: 100%; flex-basis: 100%; }
  .sov-mail-status-metric { flex: 1; }
  .sov-mail-collect-button { width: 100%; }
}

@media (max-width: 520px) {
  .sov-brand-block .les-brand {
    display: none;
  }
  .les-top-tabs .q-tab__label {
    display: none;
  }
  .les-top-tabs .q-tab {
    width: 44px;
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
